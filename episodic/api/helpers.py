"""Request parsing and update-payload builders for Falcon resources."""

from __future__ import annotations

import typing as typ
import uuid

import falcon

from episodic.canonical.profile_templates import (
    AuditMetadata,
    EpisodeTemplateData,
    EpisodeTemplateUpdateFields,
    SeriesProfileCreateData,
    SeriesProfileData,
    UpdateEpisodeTemplateRequest,
    UpdateSeriesProfileRequest,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc


def parse_uuid(raw_value: str, field_name: str) -> uuid.UUID:
    """Parse a UUID string or raise HTTP 400."""
    try:
        return uuid.UUID(raw_value)
    except ValueError as exc:
        msg = f"Invalid UUID for {field_name}: {raw_value!r}."
        raise falcon.HTTPBadRequest(description=msg) from exc


def require_payload_dict(payload: object) -> dict[str, typ.Any]:
    """Validate request media payload shape."""
    if not isinstance(payload, dict):
        msg = "JSON object payload is required."
        raise falcon.HTTPBadRequest(description=msg)
    return typ.cast("dict[str, typ.Any]", payload)


def build_audit_metadata(payload: dict[str, typ.Any]) -> AuditMetadata:
    """Extract audit metadata from request payload."""
    return AuditMetadata(
        actor=typ.cast("str | None", payload.get("actor")),
        note=typ.cast("str | None", payload.get("note")),
    )


def parse_expected_revision(payload: dict[str, typ.Any]) -> int:
    """Parse expected revision or raise HTTP 400."""
    if "expected_revision" not in payload:
        msg = "Missing required field: expected_revision"
        raise falcon.HTTPBadRequest(description=msg)

    raw_expected_revision = payload["expected_revision"]
    try:
        return int(raw_expected_revision)
    except (TypeError, ValueError) as exc:
        msg = f"Invalid integer for expected_revision: {raw_expected_revision!r}."
        raise falcon.HTTPBadRequest(description=msg) from exc


def _build_update_kwargs[DataT](
    payload: dict[str, typ.Any],
    data_key: str,
    data_builder: cabc.Callable[[dict[str, typ.Any]], DataT],
) -> dict[str, typ.Any]:
    """Build generic update service kwargs with optimistic locking."""
    return {
        "expected_revision": parse_expected_revision(payload),
        data_key: data_builder(payload),
        "audit": build_audit_metadata(payload),
    }


def _build_profile_data(payload: dict[str, typ.Any]) -> SeriesProfileData:
    """Build SeriesProfileData from payload."""
    return SeriesProfileData(
        title=typ.cast("str", payload["title"]),
        description=typ.cast("str | None", payload.get("description")),
        configuration=typ.cast("dict[str, typ.Any]", payload["configuration"]),
    )


def _build_template_fields(
    payload: dict[str, typ.Any],
) -> EpisodeTemplateUpdateFields:
    """Build EpisodeTemplateUpdateFields from payload."""
    return EpisodeTemplateUpdateFields(
        title=typ.cast("str", payload["title"]),
        description=typ.cast("str | None", payload.get("description")),
        structure=typ.cast("dict[str, typ.Any]", payload["structure"]),
    )


def _build_typed_update_request[DataT, RequestT](  # noqa: PLR0913  # Context: generic builder requires explicit typed factories
    entity_id: uuid.UUID,
    payload: dict[str, typ.Any],
    *,
    data_key: str,
    data_builder: cabc.Callable[[dict[str, typ.Any]], DataT],
    request_builder: cabc.Callable[
        [uuid.UUID, int, DataT, AuditMetadata],
        RequestT,
    ],
) -> RequestT:
    """Build a typed update request from common payload parsing."""
    update_kwargs = _build_update_kwargs(payload, data_key, data_builder)
    expected_revision = typ.cast("int", update_kwargs["expected_revision"])
    audit = typ.cast("AuditMetadata", update_kwargs["audit"])
    data_or_fields = typ.cast("DataT", update_kwargs[data_key])
    return request_builder(entity_id, expected_revision, data_or_fields, audit)


def build_profile_create_kwargs(payload: dict[str, typ.Any]) -> dict[str, object]:
    """Build create kwargs for ``create_series_profile``."""
    data = SeriesProfileCreateData(
        slug=typ.cast("str", payload["slug"]),
        title=typ.cast("str", payload["title"]),
        description=typ.cast("str | None", payload.get("description")),
        configuration=typ.cast("dict[str, object]", payload["configuration"]),
    )
    return {
        "data": data,
        "audit": build_audit_metadata(payload),
    }


def build_template_create_kwargs(payload: dict[str, typ.Any]) -> dict[str, object]:
    """Build create kwargs for ``create_episode_template``."""
    audit = build_audit_metadata(payload)
    data = EpisodeTemplateData(
        slug=typ.cast("str", payload["slug"]),
        title=typ.cast("str", payload["title"]),
        description=typ.cast("str | None", payload.get("description")),
        structure=typ.cast("dict[str, object]", payload["structure"]),
        actor=audit.actor,
        note=audit.note,
    )
    return {
        "series_profile_id": parse_uuid(
            typ.cast("str", payload["series_profile_id"]),
            "series_profile_id",
        ),
        "data": data,
    }


def build_profile_update_request(
    entity_id: uuid.UUID,
    payload: dict[str, typ.Any],
) -> UpdateSeriesProfileRequest:
    """Build an update request for series profiles."""
    return _build_typed_update_request(
        entity_id,
        payload,
        data_key="data",
        data_builder=_build_profile_data,
        request_builder=lambda eid, rev, data, audit: UpdateSeriesProfileRequest(
            profile_id=eid,
            expected_revision=rev,
            data=typ.cast("SeriesProfileData", data),
            audit=audit,
        ),
    )


def build_template_update_request(
    entity_id: uuid.UUID,
    payload: dict[str, typ.Any],
) -> UpdateEpisodeTemplateRequest:
    """Build an update request for episode templates."""
    return _build_typed_update_request(
        entity_id,
        payload,
        data_key="fields",
        data_builder=_build_template_fields,
        request_builder=lambda eid, rev, fields, audit: UpdateEpisodeTemplateRequest(
            template_id=eid,
            expected_revision=rev,
            fields=typ.cast("EpisodeTemplateUpdateFields", fields),
            audit=audit,
        ),
    )
