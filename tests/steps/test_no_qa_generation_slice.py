"""Behavioural coverage for the no-QA source-to-script REST slice."""

from pytest_bdd import given, parsers, scenario, then, when

from tests.steps import no_qa_generation_slice_assertions
from tests.steps.generation_slice_shared_steps import create_generation_run
from tests.steps.no_qa_generation_slice_support import (
    NoQaGenerationSliceContext,
    assert_replay_headers,
    enable_provider_failure,
    generation_payload,
    select_malformed_completion,
)

_FEATURE = "../features/no_qa_generation_slice.feature"


@scenario(_FEATURE, "Draft generation without QA produces a downloadable TEI-P5 script")
def test_no_qa_generation_produces_downloadable_tei() -> None:
    """Run the no-QA generation happy path."""


@scenario(_FEATURE, "Reusing an idempotency key with the same body replays the run")
def test_no_qa_generation_idempotency_replays_same_body() -> None:
    """Run the idempotent replay scenario."""


@scenario(_FEATURE, "Reusing an idempotency key with a different body conflicts")
def test_no_qa_generation_idempotency_conflicts_on_body_mismatch() -> None:
    """Run the idempotency conflict scenario."""


@scenario(_FEATURE, "A missing rationale is rejected")
def test_no_qa_generation_rejects_missing_rationale() -> None:
    """Run the missing-rationale scenario."""


@scenario(_FEATURE, "An unsupported quality mode is unprocessable")
def test_no_qa_generation_rejects_unsupported_quality_mode() -> None:
    """Run the unsupported-quality-mode scenario."""


@scenario(_FEATURE, "Generation failure is reported on the run")
def test_no_qa_generation_reports_generation_failure() -> None:
    """Run the provider failure scenario."""


@scenario(_FEATURE, "A malformed completion is reported as a failed run")
def test_no_qa_generation_reports_malformed_completion() -> None:
    """Run the malformed-completion scenario."""


@given("the inference server is configured to fail")
def inference_server_fails(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Enable deterministic provider failure injection."""
    enable_provider_failure(generation_slice_context)


@given("the inference server is configured to return a non-TEI completion")
def inference_server_returns_non_tei(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Select a completion that cannot form a TEI draft."""
    select_malformed_completion(generation_slice_context)


@when("I create a draft-without-qa run twice with the same idempotency key and body")
def create_draft_without_qa_run_twice(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Replay an identical generation request."""
    create_generation_run(generation_slice_context, generation_payload())
    create_generation_run(generation_slice_context, generation_payload())


@when("I create a draft-without-qa run, then reuse the key with a different rationale")
def create_draft_without_qa_run_with_changed_body(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Reuse an idempotency key with changed input."""
    create_generation_run(generation_slice_context, generation_payload())
    create_generation_run(
        generation_slice_context,
        generation_payload(skip_qa_rationale="Changed rationale."),
    )


@when("I create a draft-without-qa run without a skip_qa_rationale")
def create_draft_without_qa_run_without_rationale(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Submit a request without its required rationale."""
    create_generation_run(
        generation_slice_context,
        {"quality_mode": "draft_without_qa", "actor": "editor@example.com"},
    )


@when(parsers.parse('I create a generation run with quality_mode "{quality_mode}"'))
def create_generation_run_with_quality_mode(
    generation_slice_context: NoQaGenerationSliceContext,
    quality_mode: str,
) -> None:
    """Submit a request with the requested quality mode."""
    create_generation_run(
        generation_slice_context,
        generation_payload(quality_mode=quality_mode),
    )


@then(
    parsers.parse(
        'the run is created with qa_status "{qa_status}" and my rationale recorded'
    )
)
def run_records_qa_status(
    generation_slice_context: NoQaGenerationSliceContext,
    qa_status: str,
) -> None:
    """Verify QA bypass provenance is represented on creation."""
    body = generation_slice_context.responses[0].json()
    assert body["qa_status"] == qa_status, f"QA status: {body['qa_status']!r}"
    assert body["skip_qa_rationale"] == generation_payload()["skip_qa_rationale"], (
        f"rationale: {body['skip_qa_rationale']!r}"
    )


@then("both responses describe the same run id")
def responses_describe_same_run(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Verify an identical replay resolves to the original run."""
    first_run_id = generation_slice_context.responses[0].json()["id"]
    second_run_id = generation_slice_context.responses[1].json()["id"]
    assert first_run_id == second_run_id, f"replay run id: {second_run_id!r}"


@then("the replayed response carries the same Location and Retry-After")
def replay_preserves_polling_headers(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Verify replay retains long-running operation headers."""
    assert_replay_headers(
        generation_slice_context.responses[0],
        generation_slice_context.responses[1],
    )


@then("the second response is 409 Conflict")
def second_response_is_conflict(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Verify changed input is rejected under the reused key."""
    no_qa_generation_slice_assertions.second_response_is_conflict(
        generation_slice_context
    )
