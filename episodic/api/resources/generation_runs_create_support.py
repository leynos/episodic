"""Request-body parsing helpers for no-QA generation-run creation."""

import typing as typ

import falcon

from episodic.api.errors import http_error, validation_error
from episodic.api.source_intake_support import require_str
from episodic.canonical.generation_quality import QualityMode

if typ.TYPE_CHECKING:
    from episodic.api.types import JsonPayload


class _CreateGenerationRun(typ.NamedTuple):
    skip_qa_rationale: str
    configuration: JsonPayload
    budget_snapshot: JsonPayload


def _parse_create_request(payload: JsonPayload) -> _CreateGenerationRun:
    quality_mode = require_str(payload, "quality_mode")
    if quality_mode == "qa_gated":
        raise typ.cast(
            "falcon.HTTPUnprocessableEntity",
            http_error(
                falcon.HTTPUnprocessableEntity(
                    description=f"Unsupported quality_mode: {quality_mode}."
                ),
                code="quality_mode_unsupported",
                details={"quality_mode": quality_mode},
            ),
        )
    try:
        parsed_mode = QualityMode(quality_mode)
    except ValueError as exc:
        message = f"Invalid quality_mode: {quality_mode!r}."
        raise validation_error(
            message,
            field="quality_mode",
            constraint="enum",
        ) from exc
    typ.assert_type(parsed_mode, QualityMode)
    configuration = {
        key: payload[key]
        for key in ("template_id", "prompt_overrides")
        if key in payload
    }
    budget_snapshot = _optional_mapping(payload, "budget_hints")
    return _CreateGenerationRun(
        skip_qa_rationale=require_str(payload, "skip_qa_rationale"),
        configuration=configuration,
        budget_snapshot=budget_snapshot,
    )


def _optional_mapping(payload: JsonPayload, field_name: str) -> JsonPayload:
    value = payload.get(field_name, {})
    if not isinstance(value, dict):
        message = f"{field_name} must be a JSON object."
        raise validation_error(
            message,
            field=field_name,
            constraint="object",
        )
    return typ.cast("JsonPayload", value)
