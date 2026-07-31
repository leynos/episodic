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

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import uuid
from typing import TYPE_CHECKING  # noqa: ICN003  # Review requires this import form.

from episodic.observability import NoopMetrics, PerfCounterClock

if TYPE_CHECKING:
    from episodic.observability import MetricsPort, MonotonicClockPort

type Clock = cabc.Callable[[], dt.datetime]
type UuidFactory = cabc.Callable[[], uuid.UUID]


@dc.dataclass(frozen=True, slots=True)
class SourceIntakeStorageRuntime:
    """Runtime providers used by source-intake SQLAlchemy adapters.

    Attributes
    ----------
    clock
        UTC timestamp provider.
    uuid_factory
        UUID provider.
    metrics
        Metrics implementation.
    monotonic_clock
        Monotonic time provider.
    """

    clock: Clock
    uuid_factory: UuidFactory
    metrics: MetricsPort
    monotonic_clock: MonotonicClockPort


def _utc_now() -> dt.datetime:
    """Return the current UTC timestamp for idempotency records."""
    return dt.datetime.now(dt.UTC)


def _new_uuid() -> uuid.UUID:
    """Return a new idempotency record identifier."""
    return uuid.uuid4()


def source_intake_storage_runtime(
    runtime: SourceIntakeStorageRuntime | None,
    *,
    metrics: MetricsPort | None = None,
    monotonic_clock: MonotonicClockPort | None = None,
) -> SourceIntakeStorageRuntime:
    """Return SQLAlchemy source-intake providers with production defaults.

    Parameters
    ----------
    runtime
        Provider bundle to return unchanged when supplied.
    metrics
        Optional metrics implementation. Defaults to ``NoopMetrics``.
    monotonic_clock
        Optional monotonic time provider. Defaults to ``PerfCounterClock``.

    Returns
    -------
    SourceIntakeStorageRuntime
        The supplied provider bundle or one constructed with production
        defaults.
    """
    if runtime is not None:
        return runtime
    return SourceIntakeStorageRuntime(
        clock=_utc_now,
        uuid_factory=_new_uuid,
        metrics=NoopMetrics() if metrics is None else metrics,
        monotonic_clock=PerfCounterClock()
        if monotonic_clock is None
        else monotonic_clock,
    )
