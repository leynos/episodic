"""Provide injectable runtime dependencies for source-intake repositories.

The provider bundle supplies clocks, identifier generation, and metrics to
SQLAlchemy adapters while retaining production defaults for ordinary callers.
Tests can pass a deterministic ``SourceIntakeStorageRuntime`` instead.

Examples
--------
Resolve the production provider bundle:

>>> runtime = source_intake_storage_runtime(None)
>>> callable(runtime.clock)
True
"""

import dataclasses as dc
import uuid
from typing import TYPE_CHECKING  # ruff: ignore[banned-import-from]  # Review requires this import form.

from episodic.observability import NoopMetrics, PerfCounterClock
from episodic.runtime_providers import Clock, UuidFactory, utc_now

if TYPE_CHECKING:
    from episodic.observability import MetricsPort, MonotonicClockPort


@dc.dataclass(frozen=True, slots=True)
class SourceIntakeStorageRuntime:
    """Runtime providers used by source-intake SQLAlchemy adapters.

    Attributes
    ----------
    clock : Clock
        Provider for the current UTC time.
    uuid_factory : UuidFactory
        Provider for new idempotency record identifiers.
    metrics : MetricsPort
        Sink for source-intake repository metrics.
    monotonic_clock : MonotonicClockPort
        Provider for monotonic timing measurements.
    """

    clock: Clock
    uuid_factory: UuidFactory
    metrics: MetricsPort
    monotonic_clock: MonotonicClockPort


def _new_uuid() -> uuid.UUID:
    """Return a new idempotency record identifier."""
    return uuid.uuid4()


def source_intake_storage_runtime(
    runtime: SourceIntakeStorageRuntime | None,
    *,
    metrics: MetricsPort | None = None,
    monotonic_clock: MonotonicClockPort | None = None,
) -> SourceIntakeStorageRuntime:
    """Build SQLAlchemy source-intake providers with production defaults.

    Parameters
    ----------
    runtime : SourceIntakeStorageRuntime | None
        Complete runtime to return unchanged, or ``None`` to build one.
    metrics : MetricsPort | None, optional
        Metrics sink, defaulting to ``NoopMetrics``.
    monotonic_clock : MonotonicClockPort | None, optional
        Monotonic clock, defaulting to ``PerfCounterClock``.

    Returns
    -------
    SourceIntakeStorageRuntime
        The supplied runtime or a runtime populated with production defaults.
    """
    if runtime is not None:
        return runtime
    return SourceIntakeStorageRuntime(
        clock=utc_now,
        uuid_factory=_new_uuid,
        metrics=NoopMetrics() if metrics is None else metrics,
        monotonic_clock=PerfCounterClock()
        if monotonic_clock is None
        else monotonic_clock,
    )
