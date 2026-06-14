"""Runtime provider configuration for source-intake services."""

from __future__ import annotations

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

from episodic.observability import NoopMetrics, PerfCounterClock

if typ.TYPE_CHECKING:
    from episodic.observability import MetricsPort, MonotonicClockPort

Clock = cabc.Callable[[], dt.datetime]
UuidFactory = cabc.Callable[[], uuid.UUID]


@dc.dataclass(frozen=True, slots=True)
class SourceIntakeRuntime:
    """Runtime providers used by source-intake command services."""

    clock: Clock
    uuid_factory: UuidFactory
    metrics: MetricsPort
    monotonic_clock: MonotonicClockPort


def source_intake_runtime(
    runtime: SourceIntakeRuntime | None,
) -> SourceIntakeRuntime:
    """Return source-intake runtime providers with production defaults."""
    if runtime is not None:
        return runtime
    return SourceIntakeRuntime(
        clock=_utc_now,
        uuid_factory=_new_uuid,
        metrics=NoopMetrics(),
        monotonic_clock=PerfCounterClock(),
    )


def _utc_now() -> dt.datetime:
    """Return the current UTC timestamp for source-intake entities."""
    return dt.datetime.now(dt.UTC)


def _new_uuid() -> uuid.UUID:
    """Return a new source-intake identifier."""
    return uuid.uuid4()
