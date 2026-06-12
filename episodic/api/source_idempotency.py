"""HTTP-adapter idempotency helpers for source-intake routes."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import typing as typ

import falcon

from episodic.api.errors import http_error, validation_error
from episodic.canonical.idempotency import (
    Acquired,
    Conflict,
    IdempotencyAcquireRequest,
    InFlight,
    Replay,
)
from episodic.canonical.idempotency_service import canonical_json_bytes

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.api.types import JsonPayload, UowFactory

_IDEMPOTENCY_TTL = dt.timedelta(hours=24)
_IDEMPOTENCY_KEY_REQUIRED = "Idempotency-Key header is required."
_REPLAY_PAYLOAD_INVALID = "Invalid idempotency replay payload."
_IDEMPOTENCY_CONFLICT = "Idempotency key body mismatch."
_IDEMPOTENCY_IN_FLIGHT = "Idempotent request is in flight."


@dataclasses.dataclass(frozen=True, slots=True)
class IdempotentResponse:
    """HTTP adapter response stored behind an opaque idempotency payload."""

    status: str
    media: JsonPayload


@dataclasses.dataclass(frozen=True, slots=True)
class IdempotencyContext:
    """Inputs required to acquire an idempotency record."""

    req: falcon.Request
    operation: str
    body_hash: str


async def run_idempotent(
    uow_factory: UowFactory,
    *,
    context: IdempotencyContext,
    work: cabc.Callable[[], cabc.Awaitable[IdempotentResponse]],
) -> IdempotentResponse:
    """Run HTTP work once or return a stored adapter-level replay outcome."""
    key = context.req.get_header("Idempotency-Key")
    if key is None or not key.strip():
        raise validation_error(
            _IDEMPOTENCY_KEY_REQUIRED,
            field="Idempotency-Key",
            constraint="required",
        )
    async with uow_factory() as uow:
        outcome = await uow.idempotency.acquire(
            request=IdempotencyAcquireRequest(
                principal_id=principal_id(context.req),
                operation=context.operation,
                idempotency_key=key,
                body_hash=context.body_hash,
                expires_at=dt.datetime.now(dt.UTC) + _IDEMPOTENCY_TTL,
            )
        )
        await uow.commit()
    return await _idempotent_response(uow_factory, outcome, work)


def apply_response(resp: falcon.Response, response: IdempotentResponse) -> None:
    """Apply an idempotent response to the Falcon response object."""
    resp.status = response.status
    resp.media = response.media


def principal_id(req: falcon.Request) -> str | None:
    """Return the principal identifier supplied by the inbound adapter."""
    return typ.cast("str | None", getattr(req.context, "principal_id", None))


async def _idempotent_response(
    uow_factory: UowFactory,
    outcome: Acquired | Replay | Conflict | InFlight,
    work: cabc.Callable[[], cabc.Awaitable[IdempotentResponse]],
) -> IdempotentResponse:
    """Return the adapter response for an idempotency acquire outcome."""
    match outcome:
        case Acquired(record_id=record_id):
            try:
                response = await work()
            except BaseException:
                async with uow_factory() as uow:
                    await uow.idempotency.fail(record_id=record_id)
                    await uow.commit()
                raise
            async with uow_factory() as uow:
                await uow.idempotency.complete(
                    record_id=record_id,
                    serialised_outcome=_encode_outcome(response),
                )
                await uow.commit()
            return response
        case Replay(serialised_outcome=serialised_outcome):
            return _decode_outcome(serialised_outcome)
        case Conflict(record_id=record_id):
            raise _idempotency_conflict(record_id)
        case InFlight(record_id=record_id):
            raise _idempotency_in_flight(record_id)
    typ.assert_never(outcome)


def _build_idempotency_http_conflict(
    record_id: uuid.UUID,
    *,
    description: str,
    code: str,
) -> falcon.HTTPConflict:
    """Build an idempotency-related HTTP 409 error with a record-id detail."""
    return typ.cast(
        "falcon.HTTPConflict",
        http_error(
            falcon.HTTPConflict(description=description),
            code=code,
            details={"record_id": str(record_id)},
        ),
    )


def _idempotency_conflict(record_id: uuid.UUID) -> falcon.HTTPConflict:
    """Build an idempotency conflict error."""
    return _build_idempotency_http_conflict(
        record_id,
        description=_IDEMPOTENCY_CONFLICT,
        code="idempotency_conflict",
    )


def _idempotency_in_flight(record_id: uuid.UUID) -> falcon.HTTPConflict:
    """Build an in-flight idempotency error."""
    return _build_idempotency_http_conflict(
        record_id,
        description=_IDEMPOTENCY_IN_FLIGHT,
        code="idempotency_in_progress",
    )


def _encode_outcome(response: IdempotentResponse) -> bytes:
    """Serialize an HTTP adapter response for idempotent replay."""
    return canonical_json_bytes({"status": response.status, "media": response.media})


def _decode_outcome(payload: bytes) -> IdempotentResponse:
    """Deserialize an HTTP adapter replay response."""
    raw = json.loads(payload.decode("utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(_REPLAY_PAYLOAD_INVALID)
    return IdempotentResponse(
        status=typ.cast("str", raw["status"]),
        media=typ.cast("JsonPayload", raw["media"]),
    )
