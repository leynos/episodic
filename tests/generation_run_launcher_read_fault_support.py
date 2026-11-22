"""Run-read faults and stalls for launcher ownership tests.

A losing launcher must not record a terminal state for a run another
invocation has claimed. These doubles inject the two ways that race shows up:
a read that fails before any claim, and a read that blocks until the task is
cancelled during shutdown.
"""

import asyncio
import dataclasses as dc
import typing as typ

from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import GenerationRun
    from episodic.canonical.generation_run_ports import GenerationRunPort

_FAIL_ONCE = "fail-once"
_BLOCK = "block"


@dc.dataclass(slots=True)
class ReadFault:
    """Schedule applied to the next run read through a proxy store."""

    mode: str = _FAIL_ONCE
    fired: bool = False
    started: asyncio.Event = dc.field(default_factory=asyncio.Event)
    release: asyncio.Event = dc.field(default_factory=asyncio.Event)


class RunReadFaultStore:
    """Run-store proxy that fails or stalls its first ``get_run`` call."""

    def __init__(self, inner: GenerationRunPort, fault: ReadFault) -> None:
        """Wrap the store the fault applies to."""
        self._inner = inner
        self._fault = fault

    def __getattr__(self, name: str) -> object:
        """Delegate every other attribute to the inner store."""
        return getattr(self._inner, name)

    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None:
        """Apply the configured fault, then delegate to the inner store."""
        if self._fault.mode == _FAIL_ONCE and not self._fault.fired:
            self._fault.fired = True
            msg = "transient read fault"
            raise RuntimeError(msg)
        if self._fault.mode == _BLOCK:
            self._fault.started.set()
            await self._fault.release.wait()
        return await self._inner.get_run(run_id)


class RunReadFaultUnitOfWork(SqlAlchemyUnitOfWork):
    """Unit of work whose run read carries a fault."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        fault: ReadFault,
    ) -> None:
        """Open the real unit of work with the supplied read fault."""
        super().__init__(session_factory)
        self._fault = fault

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        """Open the real unit of work and wrap only the run read."""
        uow = await super().__aenter__()
        uow.generation_runs = typ.cast(
            "GenerationRunPort",
            RunReadFaultStore(uow.generation_runs, self._fault),
        )
        return uow


def blocking_read_fault() -> ReadFault:
    """Return a fault that stalls a run read until released."""
    return ReadFault(mode=_BLOCK)
