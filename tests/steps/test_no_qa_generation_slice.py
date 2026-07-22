"""Behavioural coverage for the no-QA source-to-script REST slice."""

from __future__ import annotations

import asyncio  # noqa: TC003 - pytest resolves fixture annotations at runtime.
import subprocess  # noqa: S404 - fixture terminates its local Vidai Mock process.
import typing as typ
from pathlib import Path  # noqa: TC003 - pytest resolves step annotations at runtime.

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from episodic.canonical.tei import parse_tei_header
from tests.steps.no_qa_generation_slice_support import (
    NoQaGenerationSliceContext,
    configure_vidaimock,
    enable_provider_failure,
    generation_payload,
    require,
    select_malformed_completion,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def context(
    session_factory: async_sessionmaker[AsyncSession],
    _function_scoped_runner: asyncio.Runner,
) -> cabc.Iterator[NoQaGenerationSliceContext]:
    """Provide shared scenario state and release external resources afterward."""
    ctx = NoQaGenerationSliceContext(session_factory, _function_scoped_runner)
    yield ctx
    ctx.run(ctx.close())
    if ctx.process is not None:
        ctx.process.terminate()
        try:
            ctx.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ctx.process.kill()
            ctx.process.wait(timeout=5)


@scenario(
    "../features/no_qa_generation_slice.feature",
    "Draft generation without QA produces a downloadable TEI-P5 script",
)
def test_no_qa_generation_produces_downloadable_tei() -> None:
    """Run the no-QA generation happy path."""


@scenario(
    "../features/no_qa_generation_slice.feature",
    "Reusing an idempotency key with the same body replays the run",
)
def test_no_qa_generation_idempotency_replays_same_body() -> None:
    """Run the idempotent replay scenario."""


@scenario(
    "../features/no_qa_generation_slice.feature",
    "Reusing an idempotency key with a different body conflicts",
)
def test_no_qa_generation_idempotency_conflicts_on_body_mismatch() -> None:
    """Run the idempotency conflict scenario."""


@scenario(
    "../features/no_qa_generation_slice.feature", "A missing rationale is rejected"
)
def test_no_qa_generation_rejects_missing_rationale() -> None:
    """Run the missing-rationale scenario."""


@scenario(
    "../features/no_qa_generation_slice.feature",
    "An unsupported quality mode is unprocessable",
)
def test_no_qa_generation_rejects_unsupported_quality_mode() -> None:
    """Run the unsupported-quality-mode scenario."""


@scenario(
    "../features/no_qa_generation_slice.feature",
    "Generation failure is reported on the run",
)
def test_no_qa_generation_reports_generation_failure() -> None:
    """Run the provider failure scenario."""


@scenario(
    "../features/no_qa_generation_slice.feature",
    "A malformed completion is reported as a failed run",
)
def test_no_qa_generation_reports_malformed_completion() -> None:
    """Run the malformed-completion scenario."""


@given("a Vidai Mock inference server is running")
def vidai_mock_server_running(
    context: NoQaGenerationSliceContext, tmp_path: Path
) -> None:
    """Start Vidai Mock and wire the complete application stack."""
    configure_vidaimock(context, tmp_path)


@given("a series profile exists")
def series_profile_exists(context: NoQaGenerationSliceContext) -> None:
    """Create the series profile used by the ingestion job."""
    response = context.run(
        context.request(
            "POST",
            "/v1/series-profiles",
            json={
                "slug": "no-qa-bdd",
                "title": "No-QA BDD",
                "description": "BDD fixture.",
                "configuration": {},
                "actor": "editor@example.com",
            },
        )
    )
    assert response.status_code == 201, response.text
    context.profile_id = response.json()["id"]


@given("a host presenter profile and a guest presenter profile are bound")
def presenter_profiles_are_bound(context: NoQaGenerationSliceContext) -> None:
    """Confirm the editorial profile setup precedes source ingestion."""
    assert context.profile_id is not None


@given("an ingestion job with an attached source document")
def ingestion_job_has_source(context: NoQaGenerationSliceContext) -> None:
    """Create a ready ingestion job with deterministic source content."""
    profile_id = require(context.profile_id, "series profile")
    job = context.run(
        context.request(
            "POST",
            "/v1/ingestion-jobs",
            headers={"Idempotency-Key": "no-qa-job"},
            json={"series_profile_id": profile_id},
        )
    )
    assert job.status_code == 201, job.text
    context.ingestion_job_id = job.json()["id"]
    source = context.run(
        context.request(
            "POST",
            f"/v1/ingestion-jobs/{context.ingestion_job_id}/sources",
            headers={"Idempotency-Key": "no-qa-source"},
            json={
                "type": "source_uri",
                "source_uri": "https://example.test/source.txt",
                "source_type": "research_note",
                "weight": 1.0,
                "metadata": {"content": "A deterministic source for the episode."},
            },
        )
    )
    assert source.status_code == 201, source.text


@given("the inference server is configured to fail")
def inference_server_fails(context: NoQaGenerationSliceContext) -> None:
    """Enable deterministic provider failure injection."""
    enable_provider_failure(context)


@given("the inference server is configured to return a non-TEI completion")
def inference_server_returns_non_tei(context: NoQaGenerationSliceContext) -> None:
    """Select a completion that cannot form a TEI draft."""
    select_malformed_completion(context)


def _create(
    context: NoQaGenerationSliceContext,
    payload: dict[str, object],
    key: str = "no-qa-run",
) -> httpx.Response:
    job_id = require(context.ingestion_job_id, "ingestion job")
    response = context.run(
        context.request(
            "POST",
            f"/v1/episodes/{job_id}/generation-runs",
            headers={"Idempotency-Key": key},
            json=payload,
        )
    )
    context.responses.append(response)
    return response


@when("I create a draft-without-qa generation run for the ingested episode")
def create_draft_without_qa_run(context: NoQaGenerationSliceContext) -> None:
    """Create one no-QA generation run."""
    _create(context, generation_payload())


@when("I create a draft-without-qa run twice with the same idempotency key and body")
def create_draft_without_qa_run_twice(context: NoQaGenerationSliceContext) -> None:
    """Replay an identical generation request."""
    _create(context, generation_payload())
    _create(context, generation_payload())


@when("I create a draft-without-qa run, then reuse the key with a different rationale")
def create_draft_without_qa_run_with_changed_body(
    context: NoQaGenerationSliceContext,
) -> None:
    """Reuse an idempotency key with changed input."""
    _create(context, generation_payload())
    _create(context, generation_payload(skip_qa_rationale="Changed rationale."))


@when("I create a draft-without-qa run without a skip_qa_rationale")
def create_draft_without_qa_run_without_rationale(
    context: NoQaGenerationSliceContext,
) -> None:
    """Submit a request without its required rationale."""
    _create(
        context, {"quality_mode": "draft_without_qa", "actor": "editor@example.com"}
    )


@when(parsers.parse('I create a generation run with quality_mode "{quality_mode}"'))
def create_generation_run_with_quality_mode(
    context: NoQaGenerationSliceContext, quality_mode: str
) -> None:
    """Submit a request with the requested quality mode."""
    _create(context, generation_payload(quality_mode=quality_mode))


@when("I poll the generation run until it reaches a terminal state")
def poll_generation_run_until_terminal(context: NoQaGenerationSliceContext) -> None:
    """Drain the in-process launcher and fetch terminal run and event state."""
    launcher = require(context.launcher, "generation launcher")
    context.run(launcher.drain())
    location = context.responses[0].headers["Location"]
    context.run_response = context.run(context.request("GET", location))
    run_id = context.run_response.json()["id"]
    context.events_response = context.run(
        context.request("GET", f"/v1/generation-runs/{run_id}/events")
    )


@when("I fetch the episode TEI as application/tei+xml")
def fetch_episode_tei_as_xml(context: NoQaGenerationSliceContext) -> None:
    """Fetch the generated episode as a TEI attachment."""
    episode_id = context.responses[0].json()["episode_id"]
    context.tei_response = context.run(
        context.request(
            "GET",
            f"/v1/episodes/{episode_id}/tei",
            headers={"Accept": "application/tei+xml"},
        )
    )


@then("the run creation responds 202 Accepted with a Location header")
def run_creation_returns_accepted(context: NoQaGenerationSliceContext) -> None:
    """Verify the asynchronous operation response metadata."""
    response = context.responses[0]
    assert response.status_code == 202
    assert response.headers.get("Location")


@then("the response carries a Retry-After header")
def response_carries_retry_after(context: NoQaGenerationSliceContext) -> None:
    """Verify the server supplies a polling interval."""
    assert context.responses[0].headers["Retry-After"] == "1"


@then(
    parsers.parse(
        'the run is created with qa_status "{qa_status}" and my rationale recorded'
    )
)
def run_records_qa_status(context: NoQaGenerationSliceContext, qa_status: str) -> None:
    """Verify QA bypass provenance is represented on creation."""
    body = context.responses[0].json()
    assert body["qa_status"] == qa_status
    assert body["skip_qa_rationale"] == generation_payload()["skip_qa_rationale"]


@then(parsers.parse('the run status is "{status}"'))
def run_status_is(context: NoQaGenerationSliceContext, status: str) -> None:
    """Verify the polled run reached the expected terminal state."""
    assert require(context.run_response, "run response").json()["status"] == status


@then(parsers.parse('the event log contains a "{event_kind}" event'))
def event_log_contains(context: NoQaGenerationSliceContext, event_kind: str) -> None:
    """Verify the durable event stream contains the named event."""
    items = require(context.events_response, "event response").json()["items"]
    assert event_kind in {item["kind"] for item in items}


@then(parsers.parse('the response is a TEI-P5 attachment with qa_status "{qa_status}"'))
def response_is_tei_attachment(
    context: NoQaGenerationSliceContext, qa_status: str
) -> None:
    """Verify raw TEI download metadata and QA provenance."""
    response = require(context.tei_response, "TEI response")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/tei+xml")
    assert "attachment" in response.headers["content-disposition"]
    assert (
        require(context.run_response, "run response").json()["qa_status"] == qa_status
    )


@then("the TEI validates against the Episodic TEI-P5 profile")
def tei_validates(context: NoQaGenerationSliceContext) -> None:
    """Validate the downloaded document through the canonical TEI parser."""
    assert (
        parse_tei_header(require(context.tei_response, "TEI response").text).title
        == "A deterministic no-QA draft"
    )


@then("both responses describe the same run id")
def responses_describe_same_run(context: NoQaGenerationSliceContext) -> None:
    """Verify an identical replay resolves to the original run."""
    assert context.responses[0].json()["id"] == context.responses[1].json()["id"]


@then("the replayed response carries the same Location and Retry-After")
def replay_preserves_polling_headers(context: NoQaGenerationSliceContext) -> None:
    """Verify replay retains long-running operation headers."""
    assert (
        context.responses[0].headers["Location"]
        == context.responses[1].headers["Location"]
    )
    assert (
        context.responses[0].headers["Retry-After"]
        == context.responses[1].headers["Retry-After"]
    )


@then("the second response is 409 Conflict")
def second_response_is_conflict(context: NoQaGenerationSliceContext) -> None:
    """Verify changed input is rejected under the reused key."""
    assert context.responses[1].status_code == 409


@then("the response is 400 Bad Request")
def response_is_bad_request(context: NoQaGenerationSliceContext) -> None:
    """Verify malformed quality metadata is a bad request."""
    assert context.responses[0].status_code == 400


@then("the response is 422 Unprocessable Entity")
def response_is_unprocessable(context: NoQaGenerationSliceContext) -> None:
    """Verify a recognized unsupported mode is unprocessable."""
    assert context.responses[0].status_code == 422


@then("the run records an error message and an error category")
def run_records_error(context: NoQaGenerationSliceContext) -> None:
    """Verify terminal failures expose stable diagnostic fields."""
    body = require(context.run_response, "run response").json()
    assert body["error_message"]
    assert body["error_category"]
