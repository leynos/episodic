"""Background, polling, and assertion steps shared by generation-slice features.

Both the no-QA and QA-gated feature modules import this module, which registers
the shared steps with pytest-bdd. The ``generation_slice_context`` fixture lives
in this directory's ``conftest.py`` so either feature can request it.
"""

import typing as typ
from pathlib import Path  # ruff: ignore[typing-only-standard-library-import] - pytest resolves step annotations at runtime.

from pytest_bdd import given, parsers, then, when

from episodic.canonical.tei import parse_tei_header
from tests.steps.no_qa_generation_slice_support import (
    NoQaGenerationSliceContext,
    assert_response_status,
    assert_tei_response,
    configure_vidaimock,
    generation_payload,
    require,
)

if typ.TYPE_CHECKING:
    import httpx


@given("a Vidai Mock inference server is running")
def vidai_mock_server_running(
    generation_slice_context: NoQaGenerationSliceContext,
    tmp_path: Path,
) -> None:
    """Start Vidai Mock and wire the complete application stack."""
    configure_vidaimock(generation_slice_context, tmp_path)


@given("a series profile exists")
def series_profile_exists(generation_slice_context: NoQaGenerationSliceContext) -> None:
    """Create the series profile used by the ingestion job."""
    context = generation_slice_context
    response = context.runner.run(
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
def presenter_profiles_are_bound(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Create and bind host and guest profile revisions to the series."""
    context = generation_slice_context
    profile_id = require(context.profile_id, "series profile")
    for kind, name in (("host_profile", "BDD Host"), ("guest_profile", "BDD Guest")):
        document = context.runner.run(
            context.request(
                "POST",
                f"/v1/series-profiles/{profile_id}/reference-documents",
                json={
                    "kind": kind,
                    "lifecycle_state": "active",
                    "metadata": {"name": name},
                },
            )
        )
        assert document.status_code == 201, document.text
        document_id = document.json()["id"]
        revision = context.runner.run(
            context.request(
                "POST",
                f"/v1/series-profiles/{profile_id}/reference-documents/"
                f"{document_id}/revisions",
                json={
                    "content": {"summary": f"{name} profile content."},
                    "content_hash": f"no-qa-{kind}",
                    "author": "editor@example.com",
                    "change_note": "Create BDD presenter.",
                },
            )
        )
        assert revision.status_code == 201, revision.text
        binding = context.runner.run(
            context.request(
                "POST",
                "/v1/reference-bindings",
                json={
                    "reference_document_revision_id": revision.json()["id"],
                    "target_kind": "series_profile",
                    "series_profile_id": profile_id,
                },
            )
        )
        assert binding.status_code == 201, binding.text


@given("an ingestion job with an attached source document")
def ingestion_job_has_source(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Create a ready ingestion job with deterministic source content."""
    context = generation_slice_context
    profile_id = require(context.profile_id, "series profile")
    job = context.runner.run(
        context.request(
            "POST",
            "/v1/ingestion-jobs",
            headers={"Idempotency-Key": "no-qa-job"},
            json={"series_profile_id": profile_id},
        )
    )
    assert job.status_code == 201, job.text
    context.ingestion_job_id = job.json()["id"]
    source = context.runner.run(
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


def create_generation_run(
    context: NoQaGenerationSliceContext,
    payload: dict[str, object],
    key: str = "no-qa-run",
) -> httpx.Response:
    """Create one generation run, wait for execution, and record the response."""
    job_id = require(context.ingestion_job_id, "ingestion job")
    response = context.runner.run(
        context.request(
            "POST",
            f"/v1/ingestion-jobs/{job_id}/generation-runs",
            headers={"Idempotency-Key": key},
            json=payload,
        )
    )
    context.responses.append(response)
    launcher = require(context.launcher, "generation launcher")
    context.runner.run(launcher.drain())
    return response


@when("I create a draft-without-qa generation run for the ingested episode")
def create_draft_without_qa_run(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Create one no-QA generation run."""
    create_generation_run(generation_slice_context, generation_payload())


@when("I poll the generation run until it reaches a terminal state")
def poll_generation_run_until_terminal(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Drain the in-process launcher and fetch terminal run and event state."""
    context = generation_slice_context
    launcher = require(context.launcher, "generation launcher")
    context.runner.run(launcher.drain())
    location = context.responses[0].headers["Location"]
    context.run_response = context.runner.run(context.request("GET", location))
    run_id = context.run_response.json()["id"]
    context.events_response = context.runner.run(
        context.request("GET", f"/v1/generation-runs/{run_id}/events")
    )


def _fetch_episode_tei(
    context: NoQaGenerationSliceContext,
    headers: dict[str, str] | None = None,
) -> None:
    """Fetch the generated episode TEI and store the response."""
    episode_id = context.responses[0].json()["episode_id"]
    context.tei_response = context.runner.run(
        context.request("GET", f"/v1/episodes/{episode_id}/tei", headers=headers)
    )


@when("I fetch the episode TEI as JSON")
def fetch_episode_tei_as_json(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Fetch the generated episode envelope as JSON."""
    _fetch_episode_tei(generation_slice_context)


@when("I fetch the episode TEI as application/tei+xml")
def fetch_episode_tei_as_xml(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Fetch the generated episode as a TEI attachment."""
    _fetch_episode_tei(
        generation_slice_context,
        {"Accept": "application/tei+xml"},
    )


@then("the run creation responds 202 Accepted with a Location header")
def run_creation_returns_accepted(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Verify the asynchronous operation response metadata."""
    response = generation_slice_context.responses[0]
    assert_response_status(response, 202)
    location = response.headers.get("Location")
    assert location, f"expected a non-empty Location header, got {location!r}"


@then("the response carries a Retry-After header")
def response_carries_retry_after(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Verify the server supplies a polling interval."""
    retry_after = generation_slice_context.responses[0].headers["Retry-After"]
    assert retry_after == "1", f"expected Retry-After '1', got {retry_after!r}"


@then(parsers.parse('the run status is "{status}"'))
def run_status_is(
    generation_slice_context: NoQaGenerationSliceContext,
    status: str,
) -> None:
    """Verify the polled run reached the expected terminal state."""
    observed_status = require(
        generation_slice_context.run_response,
        "run response",
    ).json()["status"]
    assert observed_status == status, f"run status: {observed_status!r}"


@then(parsers.parse('the event log contains a "{event_kind}" event'))
def event_log_contains(
    generation_slice_context: NoQaGenerationSliceContext,
    event_kind: str,
) -> None:
    """Verify the durable event stream contains the named event."""
    items = require(
        generation_slice_context.events_response,
        "event response",
    ).json()["items"]
    observed_kinds = {item["kind"] for item in items}
    assert event_kind in observed_kinds, f"event kinds: {observed_kinds!r}"


@then(parsers.parse('the response is a TEI-P5 attachment with qa_status "{qa_status}"'))
def response_is_tei_attachment(
    generation_slice_context: NoQaGenerationSliceContext,
    qa_status: str,
) -> None:
    """Verify raw TEI download metadata and QA provenance."""
    context = generation_slice_context
    assert_tei_response(
        require(context.tei_response, "TEI response"),
        require(context.run_response, "run response"),
        qa_status,
    )


@then("the TEI validates against the Episodic TEI-P5 profile")
def tei_validates(generation_slice_context: NoQaGenerationSliceContext) -> None:
    """Validate the downloaded document through the canonical TEI parser."""
    observed_title = parse_tei_header(
        require(generation_slice_context.tei_response, "TEI response").text
    ).title
    assert observed_title == "A deterministic no-QA draft", f"title: {observed_title}"


@then("the run records an error message and an error category")
def run_records_error(generation_slice_context: NoQaGenerationSliceContext) -> None:
    """Verify terminal failures expose stable diagnostic fields."""
    body = require(generation_slice_context.run_response, "run response").json()
    assert body["error_message"], f"error message: {body['error_message']!r}"
    assert body["error_category"], f"error category: {body['error_category']!r}"


@then("the response is 400 Bad Request")
def response_is_bad_request(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Verify malformed quality metadata is a bad request."""
    from tests.steps import no_qa_generation_slice_assertions

    no_qa_generation_slice_assertions.response_is_bad_request(generation_slice_context)


@then("the response is 422 Unprocessable Entity")
def response_is_unprocessable(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Verify a recognized unsupported mode is unprocessable."""
    from tests.steps import no_qa_generation_slice_assertions

    no_qa_generation_slice_assertions.response_is_unprocessable(
        generation_slice_context
    )
