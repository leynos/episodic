"""Observability coverage for pricing-snapshot persistence."""

import dataclasses as dc
import itertools
import typing as typ
from unittest import mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from episodic.cost import PricingSnapshotCollisionError, PricingSnapshotId
from episodic.cost.storage import SqlAlchemyCostLedgerStore
from episodic.observability import RecordingTracer
from tests.fixtures.cost import pricing_snapshot

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.sql.dml import Insert

    from episodic.cost import PricingSnapshot

    type SessionFactory = async_sessionmaker[AsyncSession]
else:  # pragma: no cover - runtime alias for evaluated test annotations.
    type SessionFactory = object

_ALLOWED_LABEL_KEYS = {"operation", "outcome", "failure_category"}


class _RecordingMetrics:
    """Capture bounded counters and latency observations."""

    def __init__(self) -> None:
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
        self._values = itertools.count(start=1.0, step=0.5)

    def monotonic_seconds(self) -> float:
        """Return the next configured timestamp."""
        return next(self._values)


def _assert_bounded(metrics: _RecordingMetrics, snapshot_id: str) -> None:
    """Assert no unbounded or sensitive values reached the labels."""
    for name, labels in metrics.counters:
        assert name.startswith("pricing_snapshot."), f"unexpected metric {name!r}"
        assert set(labels) <= _ALLOWED_LABEL_KEYS, (
            f"labels must stay bounded; got {labels!r}"
        )
        rendered = str(labels)
        assert snapshot_id not in rendered, "snapshot identifiers must not leak"
        assert "hash" not in rendered.replace("pricing_snapshot", ""), (
            f"content hashes must not leak into labels: {labels!r}"
        )


@pytest.mark.asyncio
async def test_invalid_snapshot_timestamp_emits_validation_telemetry() -> None:
    """Rejected input emits bounded validation signals before persistence starts."""
    session = mock.create_autospec(AsyncSession, instance=True)
    clock = mock.Mock(spec=_SteppingClock)
    tracer = RecordingTracer()
    metrics = _RecordingMetrics()
    snapshot = dc.replace(
        pricing_snapshot("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f98"),
        retrieved_at="2026-06-04T09:00:00",
    )
    store = SqlAlchemyCostLedgerStore(
        session, metrics=metrics, tracer=tracer, clock=clock
    )

    with pytest.raises(ValueError, match="timestamp must include timezone information"):
        await store.ensure_snapshot(snapshot)

    session.execute.assert_not_called()
    clock.monotonic_seconds.assert_not_called()
    labels = {
        "operation": "ensure_snapshot",
        "outcome": "error",
        "failure_category": "pricing_snapshot.input_invalid",
    }
    assert metrics.counters == [("pricing_snapshot.input_validation", labels)], (
        "invalid input must emit only the bounded validation counter"
    )
    assert not metrics.latencies, "rejected input must not emit persistence latency"
    assert len(tracer.spans) == 1, "rejected input must emit only one validation span"
    span = tracer.spans[0]
    assert span.name == "pricing_snapshot.input_validation", (
        "rejected input must have a separate validation span"
    )
    assert span.is_completed, "the validation span must complete"
    assert span.attributes == labels, "validation attributes must use fixed values"
    _assert_bounded(metrics, str(snapshot.pricing_snapshot_id))


@pytest.mark.asyncio
async def test_ensure_snapshot_constructs_statement_before_persistence_timing(
    session_factory: SessionFactory,
) -> None:
    """Persistence timing excludes statement construction and stays at 500 ms."""
    from episodic.cost.storage import adapters as adapters_module

    metrics = _RecordingMetrics()
    clock = mock.Mock(wraps=_SteppingClock())
    snapshot = pricing_snapshot("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f98")
    original_builder = adapters_module._snapshot_insert_statement

    def build_before_timing(value: PricingSnapshot) -> Insert:
        """Assert the measurement boundary before constructing the insert."""
        clock.monotonic_seconds.assert_not_called()
        return original_builder(value)

    async with session_factory() as session:
        store = SqlAlchemyCostLedgerStore(session, metrics=metrics, clock=clock)
        with mock.patch.object(
            adapters_module,
            "_snapshot_insert_statement",
            side_effect=build_before_timing,
        ) as builder:
            await store.ensure_snapshot(snapshot)

    builder.assert_called_once_with(snapshot)
    assert clock.monotonic_seconds.call_count == 2, (
        "only persistence start and completion may read the clock"
    )
    assert metrics.latencies == [
        (
            "pricing_snapshot.ensure.duration_ms",
            pytest.approx(500.0),
            {"operation": "ensure_snapshot", "outcome": "persisted"},
        )
    ], "statement construction must not expand persistence duration"


@pytest.mark.asyncio
async def test_ensure_snapshot_emits_persisted_reused_and_collision(
    session_factory: SessionFactory,
) -> None:
    """Each ensure outcome emits one bounded counter and one latency metric."""
    tracer = RecordingTracer()
    metrics = _RecordingMetrics()
    snapshot = pricing_snapshot("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f98")
    colliding = dc.replace(
        snapshot,
        pricing_snapshot_id=PricingSnapshotId("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f99"),
    )

    async with session_factory() as session:
        store = SqlAlchemyCostLedgerStore(
            session,
            metrics=metrics,
            tracer=tracer,
            clock=_SteppingClock(),
        )
        await store.ensure_snapshot(snapshot)
        await store.ensure_snapshot(snapshot)
        with pytest.raises(PricingSnapshotCollisionError):
            await store.ensure_snapshot(colliding)

    assert [entry[1]["outcome"] for entry in metrics.counters] == [
        "persisted",
        "reused",
        "collision",
    ], f"expected the outcome sequence, got {metrics.counters!r}"
    collision_labels = metrics.counters[2][1]
    assert collision_labels == {
        "operation": "ensure_snapshot",
        "outcome": "collision",
        "failure_category": "pricing_snapshot.collision",
    }, f"expected the fixed collision labels, got {collision_labels!r}"
    assert [entry[0] for entry in metrics.latencies] == [
        "pricing_snapshot.ensure.duration_ms"
    ] * 3, f"expected one latency observation per outcome, got {metrics.latencies!r}"
    assert all(value == pytest.approx(500.0) for _, value, _ in metrics.latencies), (
        f"expected deterministic latencies from the stepping clock, got "
        f"{metrics.latencies!r}"
    )
    _assert_bounded(metrics, str(snapshot.pricing_snapshot_id))

    spans = [
        span for span in tracer.spans if span.name == "pricing_snapshot.ensure_snapshot"
    ]
    assert len(spans) == 3, f"expected one span per ensure call, got {tracer.spans!r}"
    assert all(span.is_completed for span in spans), "every span must complete"
    assert spans[0].attributes["outcome"] == "persisted", (
        f"expected a persisted outcome, got {spans[0].attributes!r}"
    )
    assert spans[1].attributes["outcome"] == "reused", (
        f"expected a reused outcome, got {spans[1].attributes!r}"
    )
    assert spans[2].attributes["failure_category"] == "pricing_snapshot.collision", (
        f"expected the collision category, got {spans[2].attributes!r}"
    )
    for span in spans:
        assert set(span.attributes) <= _ALLOWED_LABEL_KEYS, (
            f"span attributes must stay bounded; got {span.attributes!r}"
        )
