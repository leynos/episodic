"""Request parsing and payload builders for Falcon resource adapters.

This module centralizes common API-layer transformations used by resource
classes and shared handlers. It provides audit metadata extraction,
optimistic-lock field parsing, and construction of typed service request
objects for profile/template create and update operations. Query-parameter
and payload-shape parsing utilities (UUID parsing, pagination, and generic
query-parameter helpers) live in :mod:`episodic.api.helpers_query`, which
this module re-exports so existing import paths keep working.

Examples
--------
Parse and validate identifiers before service dispatch:

>>> profile_id = parse_uuid(raw_profile_id, "profile_id")

Build a typed update request from JSON payload:

>>> request = build_profile_update_request(profile_id, payload)
"""

import copy
import dataclasses as dc
import re
import typing as typ

from episodic.canonical.profile_templates import (
    AuditMetadata,
    EpisodeTemplateData,
    EpisodeTemplateUpdateFields,
    SeriesProfileCreateData,
    SeriesProfileUpdateFields,
    UpdateEpisodeTemplateRequest,
    UpdateSeriesProfileRequest,
)

from .errors import validation_error
from .helpers_query import (
    parse_enum_param,
    parse_optional_uuid_param,
    parse_pagination,
    parse_uuid,
    require_payload_dict,
    require_query_params,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from .types import JsonPayload

__all__ = [
    "build_audit_metadata",
    "build_profile_create_kwargs",
    "build_profile_update_request",
    "build_template_create_kwargs",
    "build_template_update_request",
    "parse_enum_param",
    "parse_expected_revision",
    "parse_optional_uuid_param",
    "parse_pagination",
    "parse_uuid",
    "require_payload_dict",
    "require_query_params",
]

_INT_RE = re.compile(r"[+-]?\d+")


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
        If ``expected_revision`` is missing, not an integer, or not strictly
        positive; the exception carries the validation error envelope.
    """  # noqa: DOC501, DOC502  # validation_error returns this concrete Falcon exception.
    raw = _require_field(payload, "expected_revision")
    parsed = _coerce_strict_positive_int(raw)
    if parsed is not None:
        return parsed
    msg = f"Invalid integer for expected_revision: {raw!r}."
    raise validation_error(
        msg,
        field="expected_revision",
        constraint="positive-integer",
    )


def _require_field(payload: JsonPayload, field_name: str) -> object:
    """Return a required payload field or raise HTTP 400."""
    if field_name not in payload:
        msg = f"Missing required field: {field_name}"
        raise validation_error(msg, field=field_name, constraint="required")
    return payload[field_name]


def _coerce_strict_positive_int(value: object) -> int | None:
    """Return ``value`` as a strict positive integer or ``None``."""
    match value:
        case bool():
            return None
        case int():
            return value if value > 0 else None
        case str():
            stripped_value = value.strip()
            if _INT_RE.fullmatch(stripped_value) is None:
                return None
            parsed = int(stripped_value)
            return parsed if parsed > 0 else None
        case _:
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


def _optional_json_object_field(
    payload: JsonPayload,
    field_name: str,
) -> dict[str, object] | None:
    """Return an optional JSON-object field or raise HTTP 400."""
    if field_name not in payload:
        return None
    value = payload[field_name]
    if not isinstance(value, dict):
        msg = f"{field_name} must be a JSON object."
        raise validation_error(msg, field=field_name, constraint="object")
    return typ.cast("dict[str, object]", copy.deepcopy(value))


def _build_profile_data(payload: JsonPayload) -> SeriesProfileUpdateFields:
    """Build ``SeriesProfileUpdateFields`` from payload fields."""
    return SeriesProfileUpdateFields(
        title=typ.cast("str", _require_field(payload, "title")),
        description=typ.cast("str | None", payload.get("description")),
        configuration=typ.cast(
            "dict[str, object]",
            _require_field(payload, "configuration"),
        ),
        guardrails=_optional_json_object_field(payload, "guardrails") or {},
    )


def _build_template_fields(
    payload: JsonPayload,
) -> EpisodeTemplateUpdateFields:
    """Build ``EpisodeTemplateUpdateFields`` from payload fields."""
    return EpisodeTemplateUpdateFields(
        title=typ.cast("str", _require_field(payload, "title")),
        description=typ.cast("str | None", payload.get("description")),
        structure=typ.cast(
            "dict[str, object]",
            _require_field(payload, "structure"),
        ),
        guardrails=_optional_json_object_field(payload, "guardrails") or {},
    )


def _build_typed_update_request[DataT, RequestT](
    entity_id: uuid.UUID,
    payload: JsonPayload,
    *,
    data_builder: cabc.Callable[[JsonPayload], DataT],
    request_builder: cabc.Callable[
        [uuid.UUID, int, DataT, AuditMetadata],
        RequestT,
    ],
) -> RequestT:
    """Build a typed update request from common payload parsing."""
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
    """
    slug = _require_field(payload, "slug")
    title = _require_field(payload, "title")
    configuration = _require_field(payload, "configuration")
    data = SeriesProfileCreateData(
        slug=typ.cast("str", slug),
        title=typ.cast("str", title),
        description=typ.cast("str | None", payload.get("description")),
        configuration=typ.cast("dict[str, object]", configuration),
        guardrails=_optional_json_object_field(payload, "guardrails") or {},
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
        guardrails=_optional_json_object_field(payload, "guardrails") or {},
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
    """
    return _build_typed_update_request(
        entity_id,
        payload,
        data_builder=_build_profile_data,
        request_builder=lambda eid, rev, data, audit: UpdateSeriesProfileRequest(
            profile_id=eid,
            expected_revision=rev,
            data=typ.cast("SeriesProfileUpdateFields", data),
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
    """
    return _build_typed_update_request(
        entity_id,
        payload,
        data_builder=_build_template_fields,
        request_builder=lambda eid, rev, fields, audit: UpdateEpisodeTemplateRequest(
            template_id=eid,
            expected_revision=rev,
            data=typ.cast("EpisodeTemplateUpdateFields", fields),
            audit=audit,
        ),
    )
