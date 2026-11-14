"""Runtime provider configuration for source-intake services."""

import dataclasses as dc
import typing as typ
import uuid

from episodic.observability import NoopMetrics, PerfCounterClock
from episodic.runtime_providers import Clock, UuidFactory, utc_now

if typ.TYPE_CHECKING:
    from episodic.observability import MetricsPort, MonotonicClockPort


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
        clock=utc_now,
        uuid_factory=_new_uuid,
        metrics=NoopMetrics(),
        monotonic_clock=PerfCounterClock(),
    )


def _new_uuid() -> uuid.UUID:
    """Return a new source-intake identifier."""
    return uuid.uuid4()
