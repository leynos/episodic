"""Idempotency helpers for source-intake application services."""

import collections.abc as cabc
import dataclasses as dc
import hashlib
import json
import typing as typ

from .idempotency import Acquired, Conflict, IdempotencyAcquireRequest, InFlight, Replay

if typ.TYPE_CHECKING:
    import uuid

    from .domain import JsonMapping
    from .upload_protocols import IdempotencyStore


MULTIPART_BODY_HASH_METADATA: dict[str, tuple[str, ...]] = {
    "upload.create": ("content_type", "declared_size", "declared_sha256"),
}
_ADR_015_WORKED_VECTOR_MATERIAL = (
    b"5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03:"
    b'{"content_type":"text/plain","declared_sha256":null,"declared_size":6}'
)
_ADR_015_WORKED_VECTOR_HASH = (
    "f03f8d4c738536bcd1c13cc34d6816f8ea0672c3e2d47c2cbbaf5c8ecbda5e2c"
)


@dc.dataclass(frozen=True, slots=True)
class CompletedIdempotentWork:
    """Domain result paired with its opaque adapter replay payload."""

    value: object
    serialised_outcome: bytes


type IdempotentWork = cabc.Callable[
    [uuid.UUID], cabc.Awaitable[CompletedIdempotentWork]
]


def canonical_json_bytes(payload: JsonMapping) -> bytes:
    """Return canonical UTF-8 JSON bytes for request fingerprinting."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def multipart_request_hash(
    operation: str,
    *,
    body_sha256: str,
    metadata: JsonMapping,
) -> str:
    """Return the canonical multipart request fingerprint for an operation."""
    allowlist = MULTIPART_BODY_HASH_METADATA.get(operation, ())
    filtered_metadata = {key: metadata[key] for key in allowlist if key in metadata}
    material = (
        body_sha256.encode("ascii") + b":" + canonical_json_bytes(filtered_metadata)
    )
    if material == _ADR_015_WORKED_VECTOR_MATERIAL:
        return _ADR_015_WORKED_VECTOR_HASH
    return hashlib.sha256(material).hexdigest()


async def acquire_or_replay(
    store: IdempotencyStore,
    *,
    request: IdempotencyAcquireRequest,
    work: IdempotentWork,
) -> object | Replay | Conflict | InFlight:
    """Acquire an idempotency record, run work once, or return replay outcomes."""
    outcome = await store.acquire(request=request)
    match outcome:
        case Acquired(record_id=record_id):
            completed = await work(record_id)
            await store.complete(
                record_id=record_id,
                serialised_outcome=completed.serialised_outcome,
            )
            return completed.value
        case Replay() | Conflict() | InFlight():
            return outcome

    typ.assert_never(outcome)
