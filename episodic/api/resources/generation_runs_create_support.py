"""Request-body parsing and capability checks for generation-run creation.

The parser enforces the body rules that hold for every quality mode before
any idempotency work starts. The capability check and the gated-mode
rationale rule run inside the idempotent work, so a rejected request releases
its idempotency key and the ordering matches the published contract.
"""

import dataclasses as dc
import typing as typ

import falcon

from episodic.api.errors import http_error, validation_error
from episodic.api.source_intake_support import require_str
from episodic.canonical.generation_quality import QualityMode

if typ.TYPE_CHECKING:
    import uuid

    from episodic.api.types import JsonPayload

_GATED_RATIONALE_MESSAGE = (
    "skip_qa_rationale is not accepted with quality_mode qa_gated."
)


@dc.dataclass(frozen=True, slots=True)
class _Submission:
    """One parsed create request together with its request context."""

    req: falcon.Request
    payload: JsonPayload
    request: _CreateGenerationRun
    source_bundle_id: uuid.UUID
    actor: str


class _CreateGenerationRun(typ.NamedTuple):
    """Parsed fields of a no-QA generation-run creation request."""

    quality_mode: QualityMode

    skip_qa_rationale: str | None
    configuration: JsonPayload
    budget_snapshot: JsonPayload


def _parse_create_request(payload: JsonPayload) -> _CreateGenerationRun:
    """Validate a no-QA create payload and return its parsed fields."""
    quality_mode = require_str(payload, "quality_mode")
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
    return _CreateGenerationRun(
        quality_mode=parsed_mode,
        skip_qa_rationale=None,
        configuration=configuration,
        budget_snapshot={},
    )


def _require_accepted_mode(
    quality_mode: QualityMode,
    accepted_quality_modes: frozenset[QualityMode],
) -> None:
    """Reject a quality mode this deployment cannot execute.

    Raises
    ------
    falcon.HTTPUnprocessableEntity
        If the mode is not accepted. The envelope is unchanged from the
        pre-capability 422.
    """  # ruff: ignore[docstring-missing-exception, docstring-extraneous-exception]  # http_error returns the concrete Falcon exception.
    if quality_mode in accepted_quality_modes:
        return
    raise typ.cast(
        "falcon.HTTPUnprocessableEntity",
        http_error(
            falcon.HTTPUnprocessableEntity(
                description=f"Unsupported quality_mode: {quality_mode.value}."
            ),
            code="quality_mode_unsupported",
            details={"quality_mode": quality_mode.value},
        ),
    )


def _validate_quality_request(
    request: _CreateGenerationRun,
    payload: JsonPayload,
    accepted_quality_modes: frozenset[QualityMode],
) -> _CreateGenerationRun:
    """Apply the capability, budget, and rationale rules in their base order.

    The capability check comes first so an unaccepted mode keeps its ``422``
    even when the body is otherwise malformed. The budget hint is then read
    before the no-QA rationale, matching the pre-4.4.1 parser, so a request
    that is wrong in both ways reports the budget error.

    Returns
    -------
    _CreateGenerationRun
        The parsed request with its rationale and budget hint resolved.

    Raises
    ------
    falcon.HTTPUnprocessableEntity
        If the deployment does not accept the requested mode.
    falcon.HTTPBadRequest
        If the budget hint is not an object, or the body breaks its mode's
        rationale rule.
    """  # ruff: ignore[docstring-extraneous-exception]  # Delegated helpers raise the concrete Falcon exceptions.
    _require_accepted_mode(request.quality_mode, accepted_quality_modes)
    budget_snapshot = _optional_mapping(payload, "budget_hints")
    if request.quality_mode is QualityMode.DRAFT_WITHOUT_QA:
        rationale: str | None = require_str(payload, "skip_qa_rationale")
    else:
        _require_no_gated_rationale(payload, request.quality_mode)
        rationale = None
    return request._replace(
        skip_qa_rationale=rationale,
        budget_snapshot=budget_snapshot,
    )


def _require_no_gated_rationale(
    payload: JsonPayload,
    quality_mode: QualityMode,
) -> None:
    """Reject a gated request that carries a no-QA rationale.

    Raises
    ------
    falcon.HTTPBadRequest
        If a QA-gated body carries ``skip_qa_rationale``.
    """  # ruff: ignore[docstring-missing-exception, docstring-extraneous-exception]  # http_error returns the concrete Falcon exception.
    if quality_mode is not QualityMode.QA_GATED or "skip_qa_rationale" not in payload:
        return
    raise typ.cast(
        "falcon.HTTPBadRequest",
        http_error(
            falcon.HTTPBadRequest(description=_GATED_RATIONALE_MESSAGE),
            code="validation_error",
            details={
                "field": "skip_qa_rationale",
                "constraint": "exclusive_with_quality_mode",
                "quality_mode": quality_mode.value,
            },
        ),
    )


def _optional_mapping(payload: JsonPayload, field_name: str) -> JsonPayload:
    """Return the named payload field as a mapping, defaulting to empty."""
    value = payload.get(field_name, {})
    if not isinstance(value, dict):
        message = f"{field_name} must be a JSON object."
        raise validation_error(
            message,
            field=field_name,
            constraint="object",
        )
    return typ.cast("JsonPayload", value)
