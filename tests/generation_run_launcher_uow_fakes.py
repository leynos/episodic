"""Unit-of-work fakes that block selected opens for launcher seam tests."""

import typing as typ

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


class BlockingUnitOfWork:
    """Unit-of-work proxy that blocks on entry, then delegates to the real UoW."""

    def __init__(
        self,
        factory: cabc.Callable[[], CanonicalUnitOfWork],
        started: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        """Store the real factory and the coordination events."""
        self._factory = factory
        self._started = started
        self._release = release
        self._inner: CanonicalUnitOfWork | None = None

    async def __aenter__(self) -> CanonicalUnitOfWork:
        """Signal entry, wait for release, then enter the real unit of work."""
        self._started.set()
        await self._release.wait()
        self._inner = self._factory()
        return await self._inner.__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        """Exit the real unit of work."""
        if self._inner is None:
            msg = "unit of work was never entered"
            raise RuntimeError(msg)
        await self._inner.__aexit__(exc_type, exc, typ.cast("typ.Any", traceback))


class BlockingUnitOfWorkFactory:
    """Wrap a unit-of-work factory and block the selected open indices."""

    def __init__(
        self,
        factory: cabc.Callable[[], CanonicalUnitOfWork],
        blocked_opens: cabc.Container[int],
        started: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        """Store the real factory, the open indices to block, and the events."""
        self._factory = factory
        self._blocked_opens = blocked_opens
        self._started = started
        self._release = release
        self._opens = 0

    def __call__(self) -> CanonicalUnitOfWork:
        """Return a blocking proxy for a selected open, or the real unit of work."""
        self._opens += 1
        if self._opens in self._blocked_opens:
            return typ.cast(
                "CanonicalUnitOfWork",
                BlockingUnitOfWork(self._factory, self._started, self._release),
            )
        return self._factory()


__all__ = ["BlockingUnitOfWork", "BlockingUnitOfWorkFactory"]
