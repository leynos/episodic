"""Behavioural scaffold for the no-QA source-to-script REST slice."""

from __future__ import annotations

import dataclasses

import pytest
from pytest_bdd import given, parsers, scenario, then, when

_XFAIL_REASON = "4.3.2 no-QA source-to-script slice is not implemented yet"


@dataclasses.dataclass(slots=True)
class NoQaGenerationSliceContext:
    """Placeholder context for the future end-to-end REST workflow."""

    has_vidai_mock: bool = False
    has_series_profile: bool = False
    has_presenter_profiles: bool = False
    has_ingestion_job: bool = False
    inference_failure_mode: str | None = None


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
@scenario(
    "../features/no_qa_generation_slice.feature",
    "Draft generation without QA produces a downloadable TEI-P5 script",
)
def test_no_qa_generation_produces_downloadable_tei() -> None:
    """Run the no-QA generation happy-path scenario."""


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
@scenario(
    "../features/no_qa_generation_slice.feature",
    "Reusing an idempotency key with the same body replays the run",
)
def test_no_qa_generation_idempotency_replays_same_body() -> None:
    """Run the no-QA generation idempotency replay scenario."""


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
@scenario(
    "../features/no_qa_generation_slice.feature",
    "Reusing an idempotency key with a different body conflicts",
)
def test_no_qa_generation_idempotency_conflicts_on_body_mismatch() -> None:
    """Run the no-QA generation idempotency conflict scenario."""


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
@scenario(
    "../features/no_qa_generation_slice.feature",
    "A missing rationale is rejected",
)
def test_no_qa_generation_rejects_missing_rationale() -> None:
    """Run the no-QA generation missing-rationale scenario."""


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
@scenario(
    "../features/no_qa_generation_slice.feature",
    "An unsupported quality mode is unprocessable",
)
def test_no_qa_generation_rejects_unsupported_quality_mode() -> None:
    """Run the no-QA generation unsupported-quality-mode scenario."""


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
@scenario(
    "../features/no_qa_generation_slice.feature",
    "Generation failure is reported on the run",
)
def test_no_qa_generation_reports_generation_failure() -> None:
    """Run the no-QA generation failure-reporting scenario."""


@pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
@scenario(
    "../features/no_qa_generation_slice.feature",
    "A malformed completion is reported as a failed run",
)
def test_no_qa_generation_reports_malformed_completion() -> None:
    """Run the no-QA generation malformed-completion scenario."""


@given(
    "a Vidai Mock inference server is running",
    target_fixture="context",
)
def vidai_mock_server_running() -> NoQaGenerationSliceContext:
    """Create an empty no-QA slice context."""
    return NoQaGenerationSliceContext(has_vidai_mock=True)


@given("a series profile exists")
def series_profile_exists(context: NoQaGenerationSliceContext) -> None:
    """Record that the future scenario has a series profile."""
    context.has_series_profile = True


@given("a host presenter profile and a guest presenter profile are bound")
def presenter_profiles_are_bound(context: NoQaGenerationSliceContext) -> None:
    """Record that the future scenario has presenter profiles."""
    context.has_presenter_profiles = True


@given("an ingestion job with an attached source document")
def ingestion_job_has_source(context: NoQaGenerationSliceContext) -> None:
    """Record that the future scenario has ingested source material."""
    context.has_ingestion_job = True


@given("the inference server is configured to fail")
def inference_server_fails(context: NoQaGenerationSliceContext) -> None:
    """Record the future LLM failure mode."""
    context.inference_failure_mode = "provider_failure"


@given("the inference server is configured to return a non-TEI completion")
def inference_server_returns_non_tei(context: NoQaGenerationSliceContext) -> None:
    """Record the future malformed-completion failure mode."""
    context.inference_failure_mode = "non_tei_completion"


@when("I create a draft-without-qa generation run for the ingested episode")
def create_draft_without_qa_run(_: NoQaGenerationSliceContext) -> None:
    """Create the no-QA generation run once the REST endpoint exists."""
    pytest.fail(_XFAIL_REASON)


@when("I create a draft-without-qa run twice with the same idempotency key and body")
def create_draft_without_qa_run_twice(_: NoQaGenerationSliceContext) -> None:
    """Create the same no-QA generation run twice once idempotency exists."""
    pytest.fail(_XFAIL_REASON)


@when("I create a draft-without-qa run, then reuse the key with a different rationale")
def create_draft_without_qa_run_with_changed_body(
    _: NoQaGenerationSliceContext,
) -> None:
    """Create a no-QA run with a conflicting idempotency replay."""
    pytest.fail(_XFAIL_REASON)


@when("I create a draft-without-qa run without a skip_qa_rationale")
def create_draft_without_qa_run_without_rationale(
    _: NoQaGenerationSliceContext,
) -> None:
    """Create a no-QA generation run missing its required rationale."""
    pytest.fail(_XFAIL_REASON)


@when(parsers.parse('I create a generation run with quality_mode "{quality_mode}"'))
def create_generation_run_with_quality_mode(
    _: NoQaGenerationSliceContext,
    quality_mode: str,
) -> None:
    """Create a generation run with the requested quality mode."""
    assert quality_mode == "qa_gated"
    pytest.fail(_XFAIL_REASON)


@when("I poll the generation run until it reaches a terminal state")
def poll_generation_run_until_terminal(_: NoQaGenerationSliceContext) -> None:
    """Poll the run resource until the launcher reaches a terminal state."""


@when("I fetch the episode TEI as application/tei+xml")
def fetch_episode_tei_as_xml(_: NoQaGenerationSliceContext) -> None:
    """Fetch the generated TEI XML attachment."""


@then("the run creation responds 202 Accepted with a Location header")
def run_creation_returns_accepted(_: NoQaGenerationSliceContext) -> None:
    """Assert that run creation returns the long-running-operation response."""


@then("the response carries a Retry-After header")
def response_carries_retry_after(_: NoQaGenerationSliceContext) -> None:
    """Assert that polling cadence metadata is returned."""


@then(
    parsers.parse(
        'the run is created with qa_status "{qa_status}" and my rationale recorded'
    )
)
def run_records_qa_status(
    _: NoQaGenerationSliceContext,
    qa_status: str,
) -> None:
    """Assert that the run records QA bypass metadata."""
    assert qa_status == "skipped"


@then(parsers.parse('the run status is "{status}"'))
def run_status_is(
    _: NoQaGenerationSliceContext,
    status: str,
) -> None:
    """Assert that the run reaches the expected status."""
    assert status in {"succeeded", "failed"}


@then(parsers.parse('the event log contains a "{event_kind}" event'))
def event_log_contains(
    _: NoQaGenerationSliceContext,
    event_kind: str,
) -> None:
    """Assert that the run event log includes the expected lifecycle event."""
    assert event_kind in {"tei.persisted", "tei.invalid"}


@then(parsers.parse('the response is a TEI-P5 attachment with qa_status "{qa_status}"'))
def response_is_tei_attachment(
    _: NoQaGenerationSliceContext,
    qa_status: str,
) -> None:
    """Assert that the TEI endpoint returns the generated XML attachment."""
    assert qa_status == "skipped"


@then("the TEI validates against the Episodic TEI-P5 profile")
def tei_validates(_: NoQaGenerationSliceContext) -> None:
    """Assert that the generated document satisfies the TEI-P5 profile."""


@then("both responses describe the same run id")
def responses_describe_same_run(_: NoQaGenerationSliceContext) -> None:
    """Assert that identical idempotency replays return the same run."""


@then("the replayed response carries the same Location and Retry-After")
def replay_preserves_polling_headers(_: NoQaGenerationSliceContext) -> None:
    """Assert that idempotent replay preserves long-running-operation headers."""


@then("the second response is 409 Conflict")
def second_response_is_conflict(_: NoQaGenerationSliceContext) -> None:
    """Assert that a changed idempotency replay conflicts."""


@then("the response is 400 Bad Request")
def response_is_bad_request(_: NoQaGenerationSliceContext) -> None:
    """Assert that invalid request shape returns a bad-request error."""


@then("the response is 422 Unprocessable Entity")
def response_is_unprocessable(_: NoQaGenerationSliceContext) -> None:
    """Assert that unsupported quality mode returns an unprocessable error."""


@then("the run records an error message and an error category")
def run_records_error(_: NoQaGenerationSliceContext) -> None:
    """Assert that failed runs expose classified error details."""
