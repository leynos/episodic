"""The ``run_idempotent`` precondition runs only when a replay is ruled out."""

import asyncio
import dataclasses as dc
import types
import typing as typ
import uuid

import falcon
import pytest

from episodic.api.source_idempotency import (
    IdempotencyContext,
    IdempotentResponse,
    run_idempotent,
)
from episodic.canonical.idempotency import Acquired, Conflict, InFlight, Replay

if typ.TYPE_CHECKING:
    import collections.abc as cabc


class _Request:
    """Minimal request carrying the headers idempotency needs."""

    def __init__(self, key: str | None) -> None:
        """Store the idempotency key and principal context."""
        self.context = types.SimpleNamespace(principal_id="principal-a")
        self._key = key

    def get_header(self, name: str) -> str | None:
        """Return the idempotency key for its header name."""
        return self._key if name == "Idempotency-Key" else None


class _IdempotencyStore:
    """Store double returning one configured acquire outcome."""

    def __init__(self, outcome: object) -> None:
        """Store the outcome every acquire returns."""
        self._outcome = outcome

    async def acquire(self, *, request: object) -> object:
        """Return the configured outcome."""
        _ = request
        return self._outcome

    async def fail(self, *, record_id: uuid.UUID) -> None:
        """Accept a failed record without persisting anything."""
        _ = record_id

    async def complete(
        self,
        *,
        record_id: uuid.UUID,
        serialised_outcome: bytes,
    ) -> None:
        """Accept a completed record without persisting anything."""
        _ = (record_id, serialised_outcome)


class _UnitOfWork:
    """Unit of work exposing only the idempotency store."""

    def __init__(self, store: _IdempotencyStore) -> None:
        """Store the idempotency double."""
        self.idempotency = store

    async def __aenter__(self) -> _UnitOfWork:
        """Enter the unit of work."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Leave the unit of work."""
        _ = args

    async def commit(self) -> None:
        """Commit nothing."""
        return


@dc.dataclass(slots=True)
class _Precondition:
    """Record whether the precondition ran."""

    calls: int = 0

    def __call__(self) -> None:
        """Count one invocation."""
        self.calls += 1


class _BodyRejected(falcon.HTTPBadRequest):
    """The 400 a rejected body would produce in production."""


class _RejectingPrecondition:
    """Precondition that rejects the request like a body rule would."""

    def __call__(self) -> None:
        """Raise the 400 the resource's precondition raises."""
        raise _BodyRejected(description="budget_hints must be a JSON object.")


def _factory(store: _IdempotencyStore) -> cabc.Callable[[], _UnitOfWork]:
    """Return a factory for a unit of work over the given store."""
    return lambda: _UnitOfWork(store)


async def _work() -> IdempotentResponse:
    """Return a fixed accepted response."""
    await asyncio.sleep(0)
    return IdempotentResponse(status="202", media={"id": "run"})


def _context() -> IdempotencyContext:
    """Build the idempotency context the tests pass in."""
    return IdempotencyContext(
        req=typ.cast("typ.Any", _Request("run-key")),
        operation="generation_run.command",
        body_hash="hash",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    [
        Acquired(uuid.uuid4()),
        Replay(
            b'{"status": "202", "media": {}, "location": null, "retry_after": null}'
        ),
    ],
    ids=["acquired", "replay"],
)
async def test_precondition_is_skipped_when_work_or_replay_decides(
    outcome: object,
) -> None:
    """An acquired record and a stored replay both bypass the precondition."""
    precondition = _Precondition()

    response = await run_idempotent(
        typ.cast("typ.Any", _factory(_IdempotencyStore(outcome))),
        context=_context(),
        work=_work,
        precondition=precondition,
    )

    assert response.status == "202", response.status
    assert precondition.calls == 0, precondition.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    [Conflict(uuid.uuid4()), InFlight(uuid.uuid4())],
    ids=["conflict", "in-flight"],
)
async def test_precondition_runs_before_a_conflict_is_reported(
    outcome: object,
) -> None:
    """A conflict or in-flight outcome validates the body first."""
    precondition = _Precondition()

    with pytest.raises(falcon.HTTPConflict):
        await run_idempotent(
            typ.cast("typ.Any", _factory(_IdempotencyStore(outcome))),
            context=_context(),
            work=_work,
            precondition=precondition,
        )

    assert precondition.calls == 1, precondition.calls


@pytest.mark.asyncio
async def test_a_rejecting_precondition_outranks_the_conflict() -> None:
    """A precondition error is the response, not the conflict."""
    precondition = _RejectingPrecondition()

    with pytest.raises(falcon.HTTPBadRequest):
        await run_idempotent(
            typ.cast(
                "typ.Any",
                _factory(_IdempotencyStore(Conflict(uuid.uuid4()))),
            ),
            context=_context(),
            work=_work,
            precondition=precondition,
        )
