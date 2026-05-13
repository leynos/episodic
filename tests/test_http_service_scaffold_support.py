"""Shared test doubles for HTTP service scaffold tests."""

import asyncio
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork

    type ASGIReceive = cabc.Callable[
        [], cabc.Awaitable[cabc.MutableMapping[str, typ.Any]]
    ]
    type ASGISend = cabc.Callable[
        [cabc.MutableMapping[str, typ.Any]], cabc.Awaitable[None]
    ]
    type ASGIApp = cabc.Callable[
        [
            cabc.MutableMapping[str, typ.Any],
            ASGIReceive,
            ASGISend,
        ],
        cabc.Awaitable[None],
    ]

else:
    ASGIApp = typ.Any


class LifespanEvent(typ.TypedDict):
    """ASGI lifespan event carrying a mandatory type key."""

    type: str


class UnexpectedUnitOfWork:
    """Fail fast if a health endpoint tries to open a canonical unit of work."""

    async def __aenter__(self) -> UnexpectedUnitOfWork:
        """Reject accidental unit-of-work entry from health checks."""
        msg = "Health endpoints should not open a canonical unit of work."
        raise AssertionError(msg)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Discard exception details because entry should fail first."""
        del exc_type, exc, traceback


def unexpected_uow_factory() -> CanonicalUnitOfWork:
    """Build a unit of work that should never be used by health probes."""
    return typ.cast("CanonicalUnitOfWork", UnexpectedUnitOfWork())


async def run_asgi_lifespan(
    app: ASGIApp,
    event_sequence: tuple[LifespanEvent, ...],
) -> list[LifespanEvent]:
    """Simulate ASGI lifespan protocol for testing shutdown/startup hooks."""
    import collections.abc as cabc

    sent_events: list[LifespanEvent] = []
    receive_queue = asyncio.Queue[cabc.MutableMapping[str, typ.Any]]()
    for event in event_sequence:
        await receive_queue.put(
            typ.cast("cabc.MutableMapping[str, typ.Any]", event),
        )

    async def receive() -> cabc.MutableMapping[str, typ.Any]:
        return await receive_queue.get()

    async def send(message: cabc.MutableMapping[str, typ.Any]) -> None:
        sent_events.append(LifespanEvent(type=str(message["type"])))
        await asyncio.sleep(0)

    try:
        await asyncio.wait_for(
            app(
                {
                    "type": "lifespan",
                    "asgi": {"spec_version": "2.0", "version": "3.0"},
                },
                receive,
                send,
            ),
            timeout=5.0,
        )
    except TimeoutError as exc:
        msg = "ASGI lifespan simulation timed out."
        raise AssertionError(msg) from exc

    return sent_events
