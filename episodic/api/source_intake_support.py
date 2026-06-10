"""Support helpers for source-intake Falcon resources."""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import typing as typ

import falcon

from episodic.api.errors import http_error, validation_error
from episodic.api.helpers import parse_uuid
from episodic.canonical.idempotency_service import canonical_json_bytes
from episodic.canonical.ingestion_sources import AttachmentKind
from episodic.canonical.source_intake_service import AttachSourceRequest

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.api.types import JsonPayload
    from episodic.canonical.object_store import ObjectStorePort

_MULTIPART_REQUIRED = "multipart/form-data payload is required."
_FILE_REQUIRED = "Missing required multipart field: file"
_CONTENT_TYPE_REQUIRED = "Missing required multipart field: content_type"
_METADATA_OBJECT_REQUIRED = "metadata must be a JSON object."
_METADATA_JSON_REQUIRED = "metadata must contain valid JSON."
_DECLARED_SIZE_REQUIRED = "Missing required multipart field: declared_size"
_DECLARED_SIZE_TYPE = "declared_size must be an integer."
_DECLARED_SIZE_RANGE = "declared_size must be non-negative."
_SOURCE_KIND_INVALID = "Invalid source attachment type."
_WEIGHT_NUMBER_REQUIRED = "weight must be a number."
_WEIGHT_RANGE_REQUIRED = "weight must be between 0 and 1."
_REQUIRED_FIELD_TEMPLATE = "Missing required field: {field_name}"
_UUID_FIELD_TEMPLATE = "{field_name} must be a UUID string."
_UPLOAD_TOO_LARGE = "Upload payload is too large."


class _ReadablePartStream(typ.Protocol):
    """Readable multipart part stream."""

    def read(self) -> bytes | cabc.Awaitable[bytes]:
        """Read the remaining bytes from the part stream."""
        raise NotImplementedError


class _MultipartPart(typ.Protocol):
    """Multipart part shape used by Falcon ASGI and WSGI adapters."""

    name: str | None
    content_type: str | None
    stream: _ReadablePartStream
    text: str | cabc.Awaitable[str]
    media: object | cabc.Awaitable[object]


@dataclasses.dataclass(frozen=True, slots=True)
class UploadResourceConfig:
    """Configuration required by the uploads resource."""

    object_store: ObjectStorePort | None
    max_bytes: int
    content_types: frozenset[str]


@dataclasses.dataclass(frozen=True, slots=True)
class ParsedUpload:
    """Parsed multipart upload fields."""

    payload: bytes
    content_type: str
    declared_size: int
    declared_sha256: str | None
    metadata: JsonPayload


async def parse_upload_form(req: falcon.Request) -> ParsedUpload:
    """Parse the supported multipart upload form shape."""
    media = await req.get_media()
    _require_multipart_media(media)
    fields, file_bytes, file_content_type = await _collect_upload_form_parts(media)
    if file_bytes is None:
        raise validation_error(_FILE_REQUIRED, field="file")
    return _parsed_upload_from_fields(fields, file_bytes, file_content_type)


def reject_oversized(payload: bytes, max_bytes: int) -> None:
    """Reject upload bodies larger than the configured cap."""
    if len(payload) <= max_bytes:
        return
    raise http_error(
        falcon.HTTPPayloadTooLarge(description=_UPLOAD_TOO_LARGE),
        code="payload_too_large",
        details={"max_bytes": max_bytes},
    )


def build_attach_source_request(
    job_id: uuid.UUID,
    payload: JsonPayload,
) -> AttachSourceRequest:
    """Build a typed source-attachment request from JSON payload."""
    raw_kind = payload.get("type")
    try:
        attachment_kind = AttachmentKind(typ.cast("str", raw_kind))
    except ValueError as exc:
        raise _source_payload_invalid(_SOURCE_KIND_INVALID) from exc
    source_type = require_str(payload, "source_type")
    weight = _parse_weight(payload.get("weight"))
    metadata = _metadata_from_payload(payload)
    if attachment_kind is AttachmentKind.UPLOAD:
        return AttachSourceRequest(
            ingestion_job_id=job_id,
            attachment_kind=attachment_kind,
            upload_id=parse_uuid(require_str(payload, "upload_id"), "upload_id"),
            source_uri=None,
            source_type=source_type,
            weight=weight,
            metadata=metadata,
        )
    return AttachSourceRequest(
        ingestion_job_id=job_id,
        attachment_kind=attachment_kind,
        upload_id=None,
        source_uri=require_str(payload, "source_uri"),
        source_type=source_type,
        weight=weight,
        metadata=metadata,
    )


def require_str(payload: JsonPayload, field_name: str) -> str:
    """Return a required string payload field."""
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise _required_field_error(field_name)
    return value


def parse_optional_payload_uuid(
    payload: JsonPayload,
    field_name: str,
) -> uuid.UUID | None:
    """Parse an optional UUID from JSON payload."""
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _uuid_field_error(field_name)
    return parse_uuid(value, field_name)


def json_body_hash(payload: JsonPayload) -> str:
    """Return the SHA-256 hash for a canonical JSON request body."""
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _parsed_upload_from_fields(
    fields: dict[str, object],
    file_bytes: bytes,
    file_content_type: str | None,
) -> ParsedUpload:
    """Build a parsed upload from collected multipart fields."""
    content_type = typ.cast("str | None", fields.get("content_type"))
    if content_type is None:
        content_type = file_content_type
    if content_type is None:
        raise validation_error(_CONTENT_TYPE_REQUIRED, field="content_type")
    metadata = fields.get("metadata", {})
    if not isinstance(metadata, dict):
        raise validation_error(_METADATA_OBJECT_REQUIRED, field="metadata")
    return ParsedUpload(
        payload=file_bytes,
        content_type=content_type,
        declared_size=_parse_declared_size(fields.get("declared_size")),
        declared_sha256=typ.cast("str | None", fields.get("declared_sha256")),
        metadata=typ.cast("JsonPayload", metadata),
    )


def _require_multipart_media(media: object) -> None:
    """Reject request media that is not a multipart part iterable."""
    if not hasattr(media, "__iter__") and not hasattr(media, "__aiter__"):
        raise validation_error(_MULTIPART_REQUIRED)


async def _collect_upload_form_parts(
    media: object,
) -> tuple[dict[str, object], bytes | None, str | None]:
    """Collect supported upload form fields from multipart parts."""
    fields: dict[str, object] = {}
    file_bytes: bytes | None = None
    file_content_type: str | None = None
    async for part in _iter_multipart_parts(media):
        if part.name == "file":
            file_bytes = await _read_part_bytes(part)
            file_content_type = part.content_type
        elif part.name == "metadata":
            fields["metadata"] = await _read_metadata_part(part)
        elif part.name is not None:
            fields[part.name] = await _read_part_text(part)
    return fields, file_bytes, file_content_type


async def _iter_multipart_parts(media: object) -> cabc.AsyncIterator[_MultipartPart]:
    """Yield multipart body parts from Falcon sync or async form objects."""
    if hasattr(media, "__aiter__"):
        async for part in typ.cast("cabc.AsyncIterable[_MultipartPart]", media):
            yield part
        return
    for part in typ.cast("cabc.Iterable[_MultipartPart]", media):
        yield part


async def _read_part_bytes(part: _MultipartPart) -> bytes:
    """Read a multipart part body across Falcon sync and async streams."""
    data = part.stream.read()
    if inspect.isawaitable(data):
        data = await data
    return typ.cast("bytes", data)


async def _read_part_text(part: _MultipartPart) -> str:
    """Read multipart text across Falcon sync and async body-part APIs."""
    text = part.text
    if inspect.isawaitable(text):
        text = await text
    return typ.cast("str", text)


async def _read_metadata_part(part: _MultipartPart) -> JsonPayload:
    """Read and validate the optional metadata multipart field."""
    media = part.media
    if inspect.isawaitable(media):
        media = await media
    if isinstance(media, dict):
        return typ.cast("JsonPayload", media)
    try:
        parsed = json.loads(await _read_part_text(part))
    except json.JSONDecodeError as exc:
        raise validation_error(_METADATA_JSON_REQUIRED, field="metadata") from exc
    if not isinstance(parsed, dict):
        raise validation_error(_METADATA_OBJECT_REQUIRED, field="metadata")
    return typ.cast("JsonPayload", parsed)


def _parse_declared_size(value: object) -> int:
    """Parse a required non-negative declared upload size."""
    if not isinstance(value, str):
        raise validation_error(_DECLARED_SIZE_REQUIRED, field="declared_size")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise validation_error(
            _DECLARED_SIZE_TYPE,
            field="declared_size",
            constraint="type",
        ) from exc
    if parsed < 0:
        raise validation_error(
            _DECLARED_SIZE_RANGE,
            field="declared_size",
            constraint="range",
        )
    return parsed


def _metadata_from_payload(payload: JsonPayload) -> JsonPayload:
    """Return optional source metadata from a JSON payload."""
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise _source_payload_invalid(_METADATA_OBJECT_REQUIRED)
    return typ.cast("JsonPayload", metadata)


def _parse_weight(value: object) -> float:
    """Parse source weight from JSON."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise _source_payload_invalid(_WEIGHT_NUMBER_REQUIRED)
    parsed = float(value)
    if not 0 <= parsed <= 1:
        raise _source_payload_invalid(_WEIGHT_RANGE_REQUIRED)
    return parsed


def _required_field_error(field_name: str) -> falcon.HTTPBadRequest:
    """Build a required-field validation error."""
    return validation_error(
        _REQUIRED_FIELD_TEMPLATE.format(field_name=field_name),
        field=field_name,
        constraint="required",
    )


def _uuid_field_error(field_name: str) -> falcon.HTTPBadRequest:
    """Build a UUID-type validation error."""
    return validation_error(
        _UUID_FIELD_TEMPLATE.format(field_name=field_name),
        field=field_name,
        constraint="uuid",
    )


def _source_payload_invalid(message: str) -> falcon.HTTPUnprocessableEntity:
    """Return a source payload discriminator validation error."""
    return typ.cast(
        "falcon.HTTPUnprocessableEntity",
        http_error(
            falcon.HTTPUnprocessableEntity(description=message),
            code="source_payload_invalid",
        ),
    )
