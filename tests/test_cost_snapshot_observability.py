"""Observability coverage for pricing-snapshot persistence."""

import dataclasses as dc
import itertools
import typing as typ

import pytest

from episodic.cost import PricingSnapshotCollisionError, PricingSnapshotId
from episodic.cost.storage import SqlAlchemyCostLedgerStore
from episodic.observability import RecordingTracer
from tests.test_cost_storage_ledger import _pricing_snapshot

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
async def test_ensure_snapshot_emits_persisted_reused_and_collision(
    session_factory: SessionFactory,
) -> None:
    """Each ensure outcome emits one bounded counter and one latency metric."""
    tracer = RecordingTracer()
    metrics = _RecordingMetrics()
    snapshot = _pricing_snapshot("018f15f8-8c12-7c3a-9e9f-9f8f8f8f8f98")
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
    assert all(entry[1] == 500.0 for entry in metrics.latencies), (
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
