"""Profile and episode-template request payload construction."""

import typing as typ

from episodic.canonical.profile_templates import (
    EpisodeTemplateData,
    EpisodeTemplateUpdateFields,
    SeriesProfileCreateData,
    SeriesProfileUpdateFields,
    UpdateEpisodeTemplateRequest,
    UpdateSeriesProfileRequest,
)

if typ.TYPE_CHECKING:
    import uuid

    from episodic.api.types import JsonPayload


def build_profile_create_kwargs(payload: JsonPayload) -> dict[str, object]:
    """Build service keyword arguments for creating a series profile."""
    from episodic.api import helpers

    data = SeriesProfileCreateData(
        slug=typ.cast("str", helpers._require_field(payload, "slug")),
        title=typ.cast("str", helpers._require_field(payload, "title")),
        description=typ.cast("str | None", payload.get("description")),
        configuration=typ.cast(
            "dict[str, object]", helpers._require_field(payload, "configuration")
        ),
        guardrails=helpers._optional_json_object_field(payload, "guardrails") or {},
    )
    return {"data": data, "audit": helpers.build_audit_metadata(payload)}


def build_template_create_kwargs(payload: JsonPayload) -> dict[str, object]:
    """Build service keyword arguments for creating an episode template."""
    from episodic.api import helpers

    raw_profile_id = helpers._require_field(payload, "series_profile_id")
    data = EpisodeTemplateData(
        slug=typ.cast("str", helpers._require_field(payload, "slug")),
        title=typ.cast("str", helpers._require_field(payload, "title")),
        description=typ.cast("str | None", payload.get("description")),
        structure=typ.cast(
            "dict[str, object]", helpers._require_field(payload, "structure")
        ),
        guardrails=helpers._optional_json_object_field(payload, "guardrails") or {},
    )
    return {
        "series_profile_id": helpers.parse_uuid(
            typ.cast("str", raw_profile_id), "series_profile_id"
        ),
        "data": data,
        "audit": helpers.build_audit_metadata(payload),
    }


def build_profile_update_request(
    entity_id: uuid.UUID, payload: JsonPayload
) -> UpdateSeriesProfileRequest:
    """Build the typed update request for a series profile."""
    from episodic.api import helpers

    return helpers._build_typed_update_request(
        entity_id,
        payload,
        data_builder=helpers._build_profile_data,
        request_builder=lambda eid, rev, data, audit: UpdateSeriesProfileRequest(
            profile_id=eid,
            expected_revision=rev,
            data=typ.cast("SeriesProfileUpdateFields", data),
            audit=audit,
        ),
    )


def build_template_update_request(
    entity_id: uuid.UUID, payload: JsonPayload
) -> UpdateEpisodeTemplateRequest:
    """Build the typed update request for an episode template."""
    from episodic.api import helpers

    return helpers._build_typed_update_request(
        entity_id,
        payload,
        data_builder=helpers._build_template_fields,
        request_builder=lambda eid, rev, fields, audit: UpdateEpisodeTemplateRequest(
            template_id=eid,
            expected_revision=rev,
            data=typ.cast("EpisodeTemplateUpdateFields", fields),
            audit=audit,
        ),
    )
