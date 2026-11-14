"""Observability coverage for pricing-snapshot persistence."""

import itertools
import typing as typ
import uuid
from unittest import mock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from episodic.cost import (
    PricingSnapshotId,
    PricingSnapshotIntegrityError,
    PricingSnapshotNotFoundError,
)
from episodic.cost.storage import (
    InstrumentedPricingSnapshotRepository,
    PricingSnapshotRecord,
    SqlAlchemyPricingSnapshotStore,
)
from episodic.observability import MonotonicClockPort, RecordingTracer
from tests.fixtures.cost import v1_pricing_snapshot

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.sql.dml import Insert

    from episodic.cost.pricing_snapshot import PricingSnapshot

    type SessionFactory = async_sessionmaker[AsyncSession]
else:  # pragma: no cover - runtime alias for evaluated test annotations.
    type SessionFactory = object

_ALLOWED_LABEL_KEYS = {
    "operation",
    "outcome",
    "failure_category",
    "pricing_snapshot_id",
}


class _RecordingMetrics:
    """Capture bounded counters and latency observations."""

    def __init__(self) -> None:
        """Initialize empty counter and latency records."""
        self.counters: list[tuple[str, dict[str, str]]] = []
        self.latencies: list[tuple[str, float, dict[str, str]]] = []

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record one counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record one latency observation."""
        self.latencies.append((name, value, dict(labels)))


class _SteppingClock:
    """Return deterministic half-second monotonic steps."""

    def __init__(self) -> None:
        """Initialize the half-second step sequence."""
        self._values = itertools.count(start=1.0, step=0.5)

    def monotonic_seconds(self) -> float:
        """Return the next configured timestamp."""
        return next(self._values)


def _assert_bounded(metrics: _RecordingMetrics, snapshot_id: str) -> None:
    """Assert no unbounded or sensitive values reached the metric labels."""
    labelled = [
        *metrics.counters,
        *((name, labels) for name, _, labels in metrics.latencies),
    ]
    for name, labels in labelled:
        assert name.startswith("pricing_snapshot."), f"unexpected metric {name!r}"
        assert set(labels) <= {"operation", "outcome", "failure_category"}, (
            f"labels must stay bounded; got {labels!r}"
        )
        rendered = str(labels)
        assert snapshot_id not in rendered, "snapshot identifiers must not leak"
        assert "hash" not in rendered.replace("pricing_snapshot", ""), (
            f"content hashes must not leak into labels: {labels!r}"
        )


def _instrumented(
    session: AsyncSession,
    *,
    metrics: _RecordingMetrics,
    tracer: RecordingTracer | None = None,
    clock: MonotonicClockPort | None = None,
) -> InstrumentedPricingSnapshotRepository:
    """Wrap a bare store in the telemetry decorator the unit of work installs."""
    return InstrumentedPricingSnapshotRepository(
        SqlAlchemyPricingSnapshotStore(session),
        metrics=metrics,
        tracer=tracer,
        clock=clock,
    )


@pytest.mark.asyncio
async def test_ensure_snapshot_times_the_whole_repository_call(
    session_factory: SessionFactory,
) -> None:
    """One ensure reads the clock twice, enclosing statement construction."""
    from episodic.cost.storage import pricing_snapshot_store as store_module

    metrics = _RecordingMetrics()
    clock = mock.Mock(wraps=_SteppingClock())
    snapshot = v1_pricing_snapshot()
    original_builder = store_module._snapshot_insert_statement
    readings_at_build: list[int] = []

    def build_inside_the_window(
        value: object,
        pricing_snapshot_id: object,
    ) -> Insert:
        """Record how much of the timing window elapsed before the build."""
        readings_at_build.append(clock.monotonic_seconds.call_count)
        return original_builder(
            typ.cast("PricingSnapshot", value),
            typ.cast("PricingSnapshotId", pricing_snapshot_id),
        )

    async with session_factory() as session:
        store = _instrumented(session, metrics=metrics, clock=clock)
        with mock.patch.object(
            store_module,
            "_snapshot_insert_statement",
            side_effect=build_inside_the_window,
        ) as builder:
            await store.ensure(snapshot)

    assert builder.call_count == 1, "the insert statement must be built once"
    assert readings_at_build == [1], (
        "timing must start before the statement is built, so the whole call is "
        f"measured; saw {readings_at_build!r} prior readings"
    )
    assert clock.monotonic_seconds.call_count == 2, (
        "only the start and completion of the call may read the clock"
    )
    assert metrics.latencies == [
        (
            "pricing_snapshot.ensure.duration_ms",
            pytest.approx(500.0),
            {"operation": "ensure_snapshot", "outcome": "persisted"},
        )
    ], "statement construction must not expand persistence duration"


@pytest.mark.asyncio
async def test_ensure_snapshot_emits_persisted_and_reused(
    session_factory: SessionFactory,
) -> None:
    """A repeat ensure emits one bounded counter and latency per outcome."""
    tracer = RecordingTracer()
    metrics = _RecordingMetrics()
    snapshot = v1_pricing_snapshot()

    async with session_factory() as session:
        store = _instrumented(
            session,
            metrics=metrics,
            tracer=tracer,
            clock=_SteppingClock(),
        )
        first = await store.ensure(snapshot)
        second = await store.ensure(snapshot)

    assert first.outcome.value == "persisted", "the first ensure must insert the row"
    assert second.outcome.value == "reused", "the second ensure must reuse the row"
    assert first.pricing_snapshot_id == second.pricing_snapshot_id, (
        "the same content must reuse one stored identity"
    )
    assert [entry[1]["outcome"] for entry in metrics.counters] == [
        "persisted",
        "reused",
    ], f"expected the outcome sequence, got {metrics.counters!r}"
    assert [entry[0] for entry in metrics.latencies] == [
        "pricing_snapshot.ensure.duration_ms"
    ] * 2, f"expected one latency observation per outcome, got {metrics.latencies!r}"
    assert all(value == pytest.approx(500.0) for _, value, _ in metrics.latencies), (
        f"expected deterministic latencies from the stepping clock, got "
        f"{metrics.latencies!r}"
    )
    _assert_bounded(metrics, str(first.pricing_snapshot_id))

    spans = [
        span for span in tracer.spans if span.name == "pricing_snapshot.ensure_snapshot"
    ]
    assert len(spans) == 2, f"expected one span per ensure call, got {tracer.spans!r}"
    assert all(span.is_completed for span in spans), "every span must complete"
    assert [span.attributes["outcome"] for span in spans] == ["persisted", "reused"], (
        "each span must record its own ensure outcome"
    )
    for span in spans:
        assert set(span.attributes) <= _ALLOWED_LABEL_KEYS, (
            f"span attributes must stay bounded; got {span.attributes!r}"
        )


@pytest.mark.asyncio
async def test_ensure_snapshot_emits_integrity_on_a_conflict_without_a_row() -> None:
    """A conflict with no stored content hash reports the integrity category."""
    session = mock.create_autospec(AsyncSession, instance=True)
    # Drive the real conflict branch: the insert returns no identifier and the
    # fallback lookup finds no row for the content hash.
    result = mock.Mock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    session.scalar.return_value = None
    tracer = RecordingTracer()
    metrics = _RecordingMetrics()
    store = InstrumentedPricingSnapshotRepository(
        SqlAlchemyPricingSnapshotStore(session),
        metrics=metrics,
        tracer=tracer,
        clock=_SteppingClock(),
    )

    with pytest.raises(PricingSnapshotIntegrityError, match="content hash"):
        await store.ensure(v1_pricing_snapshot())

    labels = {
        "operation": "ensure_snapshot",
        "outcome": "error",
        "failure_category": "pricing_snapshot.integrity",
    }
    assert metrics.counters == [("pricing_snapshot.ensure", labels)], (
        f"expected the fixed integrity labels, got {metrics.counters!r}"
    )
    assert metrics.latencies == [
        (
            "pricing_snapshot.ensure.duration_ms",
            pytest.approx(500.0),
            {"operation": "ensure_snapshot", "outcome": "error"},
        )
    ], f"expected one error latency observation, got {metrics.latencies!r}"
    span = tracer.spans[0]
    assert span.attributes["failure_category"] == "pricing_snapshot.integrity", (
        "the span must record the integrity failure category"
    )


_TAMPERED_RATES = [
    pytest.param(
        {"input_tokens": {"amount_minor": 99, "per_units": 1}},
        id="unreconstructable",
    ),
    pytest.param(
        {"input_tokens": {"amount_minor": 99, "per_units": 1, "unit": "token"}},
        id="reconstructable",
    ),
]


_MISSING_SNAPSHOT_ID = "018f15f8-8c12-7c3a-9e9f-9f8f8fa20000"


async def _exercise_read_outcomes(
    session_factory: SessionFactory,
    snapshot: PricingSnapshot,
    tampered_rates: dict[str, dict[str, object]],
) -> tuple[PricingSnapshot, PricingSnapshotId, RecordingTracer, _RecordingMetrics]:
    """Persist, read, miss, then tamper with and re-read one snapshot."""
    tracer = RecordingTracer()
    metrics = _RecordingMetrics()
    async with session_factory() as session:
        store = _instrumented(
            session,
            metrics=metrics,
            tracer=tracer,
            clock=_SteppingClock(),
        )
        ensured = await store.ensure(snapshot)
        snapshot_id = ensured.pricing_snapshot_id
        stored = await store.get(snapshot_id)
        with pytest.raises(PricingSnapshotNotFoundError):
            await store.get(PricingSnapshotId(_MISSING_SNAPSHOT_ID))
        await session.execute(
            sa
            .update(PricingSnapshotRecord)
            .where(PricingSnapshotRecord.id == uuid.UUID(str(snapshot_id)))
            .values(rates=tampered_rates)
        )
        with pytest.raises(PricingSnapshotIntegrityError, match="content hash"):
            await store.get(snapshot_id)
    return stored, snapshot_id, tracer, metrics


def _assert_read_counters(
    stored: PricingSnapshot,
    snapshot: PricingSnapshot,
    metrics: _RecordingMetrics,
) -> None:
    """Assert the found, missing, and tampered reads were counted."""
    assert stored.content_hash == snapshot.content_hash, (
        "the found outcome must return the stored snapshot"
    )
    get_counters = [
        labels for name, labels in metrics.counters if name == "pricing_snapshot.get"
    ]
    assert [labels["outcome"] for labels in get_counters] == [
        "found",
        "not_found",
        "integrity_mismatch",
    ], f"expected the read outcome sequence, got {get_counters!r}"
    assert get_counters[1]["failure_category"] == "pricing_snapshot.not_found", (
        "a missing snapshot must record the not-found category"
    )
    assert get_counters[2]["failure_category"] == "pricing_snapshot.tampered", (
        f"expected the fixed tamper category, got {get_counters[2]!r}"
    )
    assert [
        name
        for name, _value, _labels in metrics.latencies
        if name == "pricing_snapshot.get.duration_ms"
    ] == ["pricing_snapshot.get.duration_ms"] * 3, (
        f"expected one latency observation per read, got {metrics.latencies!r}"
    )


def _assert_read_spans(snapshot_id: PricingSnapshotId, tracer: RecordingTracer) -> None:
    """Assert every read emitted one bounded span with its own outcome."""
    spans = [
        span for span in tracer.spans if span.name == "pricing_snapshot.get_snapshot"
    ]
    assert [span.attributes["outcome"] for span in spans] == [
        "found",
        "not_found",
        "integrity_mismatch",
    ], f"expected one span per read, got {tracer.spans!r}"
    assert spans[2].attributes["pricing_snapshot_id"] == str(snapshot_id), (
        "the tampered identifier belongs on the span"
    )
    assert spans[2].attributes["failure_category"] == "pricing_snapshot.tampered", (
        "the tamper span must record its category"
    )
    for span in spans:
        assert set(span.attributes) <= _ALLOWED_LABEL_KEYS, (
            f"span attributes must stay bounded; got {span.attributes!r}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("tampered_rates", _TAMPERED_RATES)
async def test_get_emits_found_not_found_and_tampered(
    session_factory: SessionFactory,
    tampered_rates: dict[str, dict[str, object]],
) -> None:
    """Reads report found, not_found, and a tampered row as integrity mismatch."""
    snapshot = v1_pricing_snapshot()
    stored, snapshot_id, tracer, metrics = await _exercise_read_outcomes(
        session_factory, snapshot, tampered_rates
    )

    _assert_read_counters(stored, snapshot, metrics)
    _assert_read_spans(snapshot_id, tracer)
    _assert_bounded(metrics, str(snapshot_id))
