"""Error-envelope assertions for no-QA generation BDD scenarios."""

import uuid

from tests.steps.no_qa_generation_slice_support import (
    NoQaGenerationSliceContext,
    assert_error_envelope,
)


def second_response_is_conflict(context: NoQaGenerationSliceContext) -> None:
    """Verify changed input is rejected under the reused key."""
    response = context.responses[1]
    details = response.json()["details"]
    assert isinstance(details, dict), f"idempotency error details: {details!r}"
    record_id = details.get("record_id")
    assert isinstance(record_id, str), f"idempotency record id: {record_id!r}"
    uuid.UUID(record_id)
    assert_error_envelope(
        response,
        status=409,
        code="idempotency_conflict",
        message="Idempotency key body mismatch.",
        details={"record_id": record_id},
    )


def response_is_bad_request(context: NoQaGenerationSliceContext) -> None:
    """Verify malformed quality metadata is a bad request."""
    assert_error_envelope(
        context.responses[0],
        status=400,
        code="validation_error",
        message="Missing required field: skip_qa_rationale",
        details={"field": "skip_qa_rationale", "constraint": "required"},
    )


def response_is_unprocessable(context: NoQaGenerationSliceContext) -> None:
    """Verify a recognized unsupported mode is unprocessable."""
    assert_error_envelope(
        context.responses[0],
        status=422,
        code="quality_mode_unsupported",
        message="Unsupported quality_mode: qa_gated.",
        details={"quality_mode": "qa_gated"},
    )
