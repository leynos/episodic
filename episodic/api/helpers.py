"""Request parsing and update-payload builders for Falcon resources."""

from __future__ import annotations

import typing as typ
import uuid

import falcon

from episodic.canonical.profile_templates import (
    AuditMetadata,
    EpisodeTemplateUpdateFields,
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


def build_profile_update_request(
    entity_id: uuid.UUID,
    payload: dict[str, typ.Any],
) -> UpdateSeriesProfileRequest:
    """Build an update request for series profiles."""
    update_kwargs = _build_update_kwargs(payload, "data", _build_profile_data)
    expected_revision = typ.cast("int", update_kwargs["expected_revision"])
    audit = typ.cast("AuditMetadata", update_kwargs["audit"])
    return UpdateSeriesProfileRequest(
        profile_id=entity_id,
        expected_revision=expected_revision,
        data=typ.cast("SeriesProfileData", update_kwargs["data"]),
        audit=audit,
    )


def build_template_update_request(
    entity_id: uuid.UUID,
    payload: dict[str, typ.Any],
) -> UpdateEpisodeTemplateRequest:
    """Build an update request for episode templates."""
    update_kwargs = _build_update_kwargs(payload, "fields", _build_template_fields)
    expected_revision = typ.cast("int", update_kwargs["expected_revision"])
    audit = typ.cast("AuditMetadata", update_kwargs["audit"])
    return UpdateEpisodeTemplateRequest(
        template_id=entity_id,
        expected_revision=expected_revision,
        fields=typ.cast("EpisodeTemplateUpdateFields", update_kwargs["fields"]),
        audit=audit,
    )
