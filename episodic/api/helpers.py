"""Request parsing and payload builders for Falcon resource adapters.

This module centralizes common API-layer transformations used by resource
classes and shared handlers. It provides utilities for UUID parsing, payload
shape validation, optimistic-lock field parsing, and construction of typed
service request objects for profile/template create and update operations.

Examples
--------
Parse and validate identifiers before service dispatch:

>>> profile_id = parse_uuid(raw_profile_id, "profile_id")

Build a typed update request from JSON payload:

>>> request = build_profile_update_request(profile_id, payload)
"""

from __future__ import annotations

import dataclasses as dc
import re
import typing as typ
import uuid

import falcon

from episodic.canonical.profile_templates import (
    AuditMetadata,
    EpisodeTemplateData,
    EpisodeTemplateUpdateFields,
    SeriesProfileCreateData,
    SeriesProfileUpdateFields,
    UpdateEpisodeTemplateRequest,
    UpdateSeriesProfileRequest,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from .types import JsonPayload

_INT_RE = re.compile(r"[+-]?\d+")


def parse_uuid(raw_value: str, field_name: str) -> uuid.UUID:
    """Parse a UUID string for a named request field.

    Parameters
    ----------
    raw_value : str
        Raw string value to parse.
    field_name : str
        Request field name used in validation error messages.

    Returns
    -------
    uuid.UUID
        Parsed UUID value.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when ``raw_value`` cannot be parsed as a UUID.
    """
    try:
        return uuid.UUID(raw_value)
    except (TypeError, ValueError, AttributeError) as exc:
        msg = f"Invalid UUID for {field_name}: {raw_value!r}."
        raise falcon.HTTPBadRequest(description=msg) from exc


def require_payload_dict(payload: object) -> JsonPayload:
    """Validate that request media is a JSON object mapping.

    Parameters
    ----------
    payload : object
        Parsed Falcon request media.

    Returns
    -------
    JsonPayload
        Validated JSON object payload.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when request media is not a JSON object.
    """
    if not isinstance(payload, dict):
        msg = "JSON object payload is required."
        raise falcon.HTTPBadRequest(description=msg)
    return typ.cast("JsonPayload", payload)


def build_audit_metadata(payload: JsonPayload) -> AuditMetadata:
    """Extract audit metadata fields from a request payload.

    Parameters
    ----------
    payload : JsonPayload
        Request payload that may contain ``actor`` and ``note`` keys.

    Returns
    -------
    AuditMetadata
        Audit metadata value object for service-layer calls.
    """
    return AuditMetadata(
        actor=typ.cast("str | None", payload.get("actor")),
        note=typ.cast("str | None", payload.get("note")),
    )


def parse_expected_revision(payload: JsonPayload) -> int:
    """Parse and validate optimistic-lock ``expected_revision``.

    Parameters
    ----------
    payload : JsonPayload
        Request payload that must contain ``expected_revision``.

    Returns
    -------
    int
        Parsed integer revision value.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when ``expected_revision`` is missing, not an integer, or not
        strictly positive.
    """
    raw = _require_field(payload, "expected_revision")
    parsed = _coerce_strict_positive_int(raw)
    if parsed is not None:
        return parsed
    msg = f"Invalid integer for expected_revision: {raw!r}."
    raise falcon.HTTPBadRequest(description=msg)


def _require_field(payload: JsonPayload, field_name: str) -> object:
    """Return a required payload field or raise HTTP 400."""
    if field_name not in payload:
        msg = f"Missing required field: {field_name}"
        raise falcon.HTTPBadRequest(description=msg)
    return payload[field_name]


def _coerce_strict_positive_int(value: object) -> int | None:
    """Return ``value`` as a strict positive integer or ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        stripped_value = value.strip()
        if _INT_RE.fullmatch(stripped_value) is None:
            return None
        parsed = int(stripped_value)
        return parsed if parsed > 0 else None
    return None


@dc.dataclass(frozen=True, slots=True)
class _ParsedUpdatePayload[DataT]:
    """Typed parsed components used to build update request objects."""

    expected_revision: int
    data: DataT
    audit: AuditMetadata


def _build_update_kwargs[DataT](
    payload: JsonPayload,
    *,
    data_builder: cabc.Callable[[JsonPayload], DataT],
) -> _ParsedUpdatePayload[DataT]:
    """Build generic update kwargs with optimistic-lock fields."""
    return _ParsedUpdatePayload(
        expected_revision=parse_expected_revision(payload),
        data=data_builder(payload),
        audit=build_audit_metadata(payload),
    )


def _build_profile_data(payload: JsonPayload) -> SeriesProfileUpdateFields:
    """Build ``SeriesProfileUpdateFields`` from payload fields."""
    title = _require_field(payload, "title")
    configuration = _require_field(payload, "configuration")
    return SeriesProfileUpdateFields(
        title=typ.cast("str", title),
        description=typ.cast("str | None", payload.get("description")),
        configuration=typ.cast("dict[str, object]", configuration),
    )


def _build_template_fields(
    payload: JsonPayload,
) -> EpisodeTemplateUpdateFields:
    """Build ``EpisodeTemplateUpdateFields`` from payload fields."""
    title = _require_field(payload, "title")
    structure = _require_field(payload, "structure")
    return EpisodeTemplateUpdateFields(
        title=typ.cast("str", title),
        description=typ.cast("str | None", payload.get("description")),
        structure=typ.cast("dict[str, object]", structure),
    )


def _build_typed_update_request[DataT, RequestT](  # noqa: PLR0913  # TODO(@episodic-dev): https://github.com/leynos/episodic/issues/1234 explicit collaborators keep type-safe generic mapping clear
    entity_id: uuid.UUID,
    payload: JsonPayload,
    *,
    data_key: str,
    data_builder: cabc.Callable[[JsonPayload], DataT],
    request_builder: cabc.Callable[
        [uuid.UUID, int, DataT, AuditMetadata],
        RequestT,
    ],
) -> RequestT:
    """Build a typed update request from common payload parsing."""
    if data_key != "data":
        msg = f"Unsupported update payload key: {data_key}."
        raise ValueError(msg)
    update_kwargs = _build_update_kwargs(payload, data_builder=data_builder)
    return request_builder(
        entity_id,
        update_kwargs.expected_revision,
        update_kwargs.data,
        update_kwargs.audit,
    )


def build_profile_create_kwargs(payload: JsonPayload) -> dict[str, object]:
    """Build service kwargs for creating a series profile.

    Parameters
    ----------
    payload : JsonPayload
        Request payload containing profile create fields and optional audit
        metadata.

    Returns
    -------
    dict[str, object]
        Keyword arguments for ``create_series_profile``.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when required profile fields are missing.
    """
    slug = _require_field(payload, "slug")
    title = _require_field(payload, "title")
    configuration = _require_field(payload, "configuration")
    data = SeriesProfileCreateData(
        slug=typ.cast("str", slug),
        title=typ.cast("str", title),
        description=typ.cast("str | None", payload.get("description")),
        configuration=typ.cast("dict[str, object]", configuration),
    )
    return {
        "data": data,
        "audit": build_audit_metadata(payload),
    }


def build_template_create_kwargs(payload: JsonPayload) -> dict[str, object]:
    """Build service kwargs for creating an episode template.

    Parameters
    ----------
    payload : JsonPayload
        Request payload containing template create fields and optional audit
        metadata.

    Returns
    -------
    dict[str, object]
        Keyword arguments for ``create_episode_template``.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when required template fields are missing or invalid.
    """
    raw_series_profile_id = _require_field(payload, "series_profile_id")
    slug = _require_field(payload, "slug")
    title = _require_field(payload, "title")
    structure = _require_field(payload, "structure")

    audit = build_audit_metadata(payload)
    data = EpisodeTemplateData(
        slug=typ.cast("str", slug),
        title=typ.cast("str", title),
        description=typ.cast("str | None", payload.get("description")),
        structure=typ.cast("dict[str, object]", structure),
    )
    return {
        "series_profile_id": parse_uuid(
            typ.cast("str", raw_series_profile_id),
            "series_profile_id",
        ),
        "data": data,
        "audit": audit,
    }


def build_profile_update_request(
    entity_id: uuid.UUID,
    payload: JsonPayload,
) -> UpdateSeriesProfileRequest:
    """Build a typed update request for series-profile updates.

    Parameters
    ----------
    entity_id : uuid.UUID
        Identifier of the series profile to update.
    payload : JsonPayload
        Request payload containing revision, profile fields, and optional audit
        metadata.

    Returns
    -------
    UpdateSeriesProfileRequest
        Typed service request value for ``update_series_profile``.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when required revision or profile fields are missing/invalid.
    """
    return _build_typed_update_request(
        entity_id,
        payload,
        data_key="data",
        data_builder=_build_profile_data,
        request_builder=lambda eid, rev, data, audit: UpdateSeriesProfileRequest(
            profile_id=eid,
            expected_revision=rev,
            data=data,
            audit=audit,
        ),
    )


def build_template_update_request(
    entity_id: uuid.UUID,
    payload: JsonPayload,
) -> UpdateEpisodeTemplateRequest:
    """Build a typed update request for episode-template updates.

    Parameters
    ----------
    entity_id : uuid.UUID
        Identifier of the episode template to update.
    payload : JsonPayload
        Request payload containing revision, template fields, and optional audit
        metadata.

    Returns
    -------
    UpdateEpisodeTemplateRequest
        Typed service request value for ``update_episode_template``.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when required revision or template fields are missing/invalid.
    """
    return _build_typed_update_request(
        entity_id,
        payload,
        data_key="data",
        data_builder=_build_template_fields,
        request_builder=lambda eid, rev, data, audit: UpdateEpisodeTemplateRequest(
            template_id=eid,
            expected_revision=rev,
            data=data,
            audit=audit,
        ),
    )
