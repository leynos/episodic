"""Provide injectable runtime dependencies for generation-run storage.

The provider bundle isolates adapter-owned UTC timestamps and event identifiers
from SQLAlchemy persistence. Production callers use the default bundle, while
tests may provide deterministic collaborators through the unit of work.
"""

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import uuid

type Clock = cabc.Callable[[], dt.datetime]
type UuidFactory = cabc.Callable[[], uuid.UUID]


@dc.dataclass(frozen=True, slots=True)
class GenerationRunStorageRuntime:
    """Runtime providers used by the generation-run SQLAlchemy adapter.

    Attributes
    ----------
    clock : Clock
        UTC timestamp provider for adapter-owned lifecycle writes.
    uuid_factory : UuidFactory
        Identifier provider for appended durable events.
    """

    clock: Clock
    uuid_factory: UuidFactory


def generation_run_storage_runtime(
    runtime: GenerationRunStorageRuntime | None,
) -> GenerationRunStorageRuntime:
    """Return generation-run providers with production defaults.

    Parameters
    ----------
    runtime
        Optional injected providers. When omitted, production UTC-clock and
        UUIDv7 providers are created.

    Returns
    -------
    GenerationRunStorageRuntime
        The supplied runtime, or the production-default provider bundle.
    """
    if runtime is not None:
        return runtime
    return GenerationRunStorageRuntime(
        clock=lambda: dt.datetime.now(dt.UTC),
        uuid_factory=uuid.uuid7,
    )
