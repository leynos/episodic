"""Unit tests for source-intake repository runtime providers."""

import datetime as dt
import uuid

from episodic.canonical.storage.source_intake_repository_runtime import (
    SourceIntakeStorageRuntime,
    source_intake_storage_runtime,
)
from episodic.observability import NoopMetrics, PerfCounterClock


def test_source_intake_storage_runtime_returns_supplied_bundle() -> None:
    """Return a supplied provider bundle unchanged."""
    supplied = SourceIntakeStorageRuntime(
        clock=lambda: dt.datetime(2026, 8, 11, tzinfo=dt.UTC),
        uuid_factory=lambda: uuid.UUID("00000000-0000-4000-8000-000000000001"),
        metrics=NoopMetrics(),
        monotonic_clock=PerfCounterClock(monotonic_seconds=lambda: 1.0),
    )

    result = source_intake_storage_runtime(
        supplied,
        metrics=NoopMetrics(),
        monotonic_clock=PerfCounterClock(monotonic_seconds=lambda: 2.0),
    )

    assert result is supplied, "A supplied runtime must take precedence over overrides"


def test_source_intake_storage_runtime_builds_production_defaults() -> None:
    """Build UTC, UUID, metrics, and monotonic-time defaults."""
    runtime = source_intake_storage_runtime(None)

    timestamp = runtime.clock()
    identifier = runtime.uuid_factory()

    assert timestamp.tzinfo is dt.UTC, "The default clock must produce UTC timestamps"
    assert isinstance(identifier, uuid.UUID), (
        "The default UUID factory must create UUIDs"
    )
    assert isinstance(runtime.metrics, NoopMetrics), (
        "The default metrics sink must be no-op"
    )
    assert isinstance(
        runtime.monotonic_clock,
        PerfCounterClock,
    ), "The default monotonic clock must use perf_counter"


def test_source_intake_storage_runtime_uses_collaborator_overrides() -> None:
    """Use supplied metrics and monotonic-clock collaborators."""
    metrics = NoopMetrics()
    monotonic_clock = PerfCounterClock(monotonic_seconds=lambda: 3.0)

    runtime = source_intake_storage_runtime(
        None,
        metrics=metrics,
        monotonic_clock=monotonic_clock,
    )

    assert runtime.metrics is metrics, (
        "The supplied metrics implementation must be retained"
    )
    assert runtime.monotonic_clock is monotonic_clock, (
        "The supplied monotonic clock must be retained"
    )
