"""Integration tests for generation-run REST resources."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import httpx
import pytest

from episodic.api import create_app
from episodic.observability import RecordingTracer
from tests.fixtures.api import build_api_dependencies
from tests.fixtures.generation_run_api import (
    HeaderPrincipalAuthorization,
    RecordingLauncher,
    create_ready_ingestion_job,
    generation_payload,
)

if typ.TYPE_CHECKING:
    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.types import UowFactory


async def _append_generation_events(
    uow_factory: UowFactory,
    run_id: uuid.UUID,
) -> None:
    """Persist events needed to verify event pagination."""
    async with uow_factory() as uow:
        for kind in ("run.started", "draft.generated"):
            await uow.generation_runs.append_event(
                run_id,
                kind=kind,
                payload={"kind": kind},
                occurred_at=dt.datetime(2026, 7, 22, tzinfo=dt.UTC),
            )
        await uow.commit()


def _assert_generation_event_page(response: httpx.Response) -> None:
    """Assert the cursor-filtered generation event page contract."""
    assert response.status_code == 200, response.text
    assert [event["kind"] for event in response.json()["items"]] == [
        "draft.generated"
    ], f"expected one draft.generated event, got {response.json()['items']!r}"
    assert response.json()["after_seq"] == 1, (
        f"expected after_seq 1, got {response.json()['after_seq']!r}"
    )
    assert response.json()["offset"] == 0, (
        f"expected offset 0, got {response.json()['offset']!r}"
    )
    assert response.json()["total"] == 1, (
        f"expected one matching event, got {response.json()['total']!r}"
    )


class _ExpectedError(typ.NamedTuple):
    """Describe one stable REST error response."""

    status: int
    code: str
    message: str
    details: dict[str, str]


def _assert_error_envelope(
    response: httpx.Response,
    expected: _ExpectedError,
) -> None:
    """Assert one complete API error response contract."""
    assert response.status_code == expected.status, response.text
    payload = response.json()
    assert set(payload) == {"code", "message", "details"}, payload
    assert payload["code"] == expected.code, payload
    assert payload["message"] == expected.message, payload
    assert payload["details"] == expected.details, payload


def _assert_generation_run_replay(
    first: httpx.Response,
    replay: httpx.Response,
    launcher: RecordingLauncher,
) -> None:
    """Assert idempotent replay preserves the accepted response contract."""
    assert first.status_code == 202, first.text
    assert replay.status_code == 202, replay.text
    assert replay.json() == first.json(), (
        f"expected replay payload {first.json()!r}, got {replay.json()!r}"
    )
    assert replay.headers["Location"] == first.headers["Location"], (
        f"expected replay location {first.headers['Location']!r}, "
        f"got {replay.headers['Location']!r}"
    )
    assert replay.headers["Retry-After"] == first.headers["Retry-After"], (
        f"expected retry delay {first.headers['Retry-After']!r}, "
        f"got {replay.headers['Retry-After']!r}"
    )
    assert len(launcher.run_ids) == 1, (
        f"expected one launched run, got {launcher.run_ids!r}"
    )


def _assert_polled_generation_run(
    response: httpx.Response,
    payload: dict[str, object],
) -> None:
    """Assert the pending generation-run polling response contract."""
    assert response.status_code == 200, response.text
    assert response.json()["qa_status"] == "skipped", (
        f"expected skipped QA status, got {response.json()['qa_status']!r}"
    )
    assert response.json()["skip_qa_rationale"] == payload["skip_qa_rationale"], (
        f"expected rationale {payload['skip_qa_rationale']!r}, "
        f"got {response.json()['skip_qa_rationale']!r}"
    )
    assert response.headers["Retry-After"] == "1", (
        f"expected retry delay '1', got {response.headers['Retry-After']!r}"
    )


def _assert_generation_run_conflict(response: httpx.Response) -> None:
    """Assert an idempotency conflict retains the original record identifier."""
    assert response.status_code == 409, response.text
    payload = response.json()
    assert set(payload) == {"code", "message", "details"}, payload
    assert payload["code"] == "idempotency_conflict", payload
    assert payload["message"] == "Idempotency key body mismatch.", payload
    changed_details = payload["details"]
    assert isinstance(changed_details, dict), changed_details
    record_id = changed_details.get("record_id")
    assert isinstance(record_id, str), changed_details
    uuid.UUID(record_id)
    _assert_error_envelope(
        response,
        _ExpectedError(
            status=409,
            code="idempotency_conflict",
            message="Idempotency key body mismatch.",
            details={"record_id": record_id},
        ),
    )


@pytest.mark.asyncio
async def test_generation_run_create_replay_and_poll(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Create once, replay response metadata, and poll the stored run."""
    launcher = RecordingLauncher()
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        authorization=HeaderPrincipalAuthorization(),
        launcher=launcher,
        tracer=RecordingTracer(),
    )
    headers = {"Authorization": "Bearer principal-a"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=typ.cast("_ASGIApp", create_app(dependencies))
        ),
        base_url="http://testserver",
    ) as client:
        ingestion_job_id = await create_ready_ingestion_job(client, headers)
        payload = generation_payload()
        first = await client.post(
            f"/v1/ingestion-jobs/{ingestion_job_id}/generation-runs",
            headers={**headers, "Idempotency-Key": "generation-key"},
            json=payload,
        )
        replay = await client.post(
            f"/v1/ingestion-jobs/{ingestion_job_id}/generation-runs",
            headers={**headers, "Idempotency-Key": "generation-key"},
            json=payload,
        )
        run_id = launcher.run_ids[0]
        await _append_generation_events(dependencies.uow_factory, run_id)
        run_response = await client.get(
            first.headers.get("Location", "/missing"), headers=headers
        )
        events_response = await client.get(
            f"/v1/generation-runs/{run_id}/events",
            headers=headers,
            params={"after_seq": 1, "limit": 1},
        )

    _assert_generation_run_replay(first, replay, launcher)
    _assert_polled_generation_run(run_response, payload)
    _assert_generation_event_page(events_response)
    _assert_trace_span(
        typ.cast("RecordingTracer", dependencies.tracer),
        "generation_run.read",
        {"operation": "generation_run.read", "outcome": "success"},
    )
    _assert_trace_span(
        typ.cast("RecordingTracer", dependencies.tracer),
        "generation_run.events.list",
        {
            "operation": "generation_run.events.list",
            "pagination": "cursor",
            "outcome": "success",
        },
    )


@pytest.mark.asyncio
async def test_generation_run_get_routes_trace_rejected_and_missing_requests(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Record bounded read-route outcomes without request data or identifiers."""
    tracer = RecordingTracer()
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        authorization=HeaderPrincipalAuthorization(),
        tracer=tracer,
    )
    headers = {"Authorization": "Bearer principal-a"}
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        invalid = await client.get("/v1/generation-runs/not-a-uuid", headers=headers)
        missing = await client.get(
            f"/v1/generation-runs/{uuid.uuid7()}", headers=headers
        )
        invalid_events = await client.get(
            f"/v1/generation-runs/{uuid.uuid7()}/events",
            headers=headers,
            params={"after_seq": "1", "offset": "1"},
        )

    assert invalid.status_code == 400, invalid.text
    assert missing.status_code == 404, missing.text
    assert invalid_events.status_code == 400, invalid_events.text
    actual_spans = [span.attributes for span in tracer.spans]
    expected_spans = [
        {
            "operation": "generation_run.read",
            "outcome": "rejected",
            "failure_category": "invalid_input",
        },
        {
            "operation": "generation_run.read",
            "outcome": "not_found",
            "failure_category": "run.not_found",
        },
        {
            "operation": "generation_run.events.list",
            "outcome": "rejected",
            "failure_category": "invalid_input",
        },
    ]
    assert actual_spans == expected_spans, tracer.spans


@pytest.mark.asyncio
async def test_generation_run_resources_enforce_principal_ownership(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Derive run actors from the authenticated principal and hide other runs."""
    launcher = RecordingLauncher()
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        authorization=HeaderPrincipalAuthorization(),
        launcher=launcher,
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    principal_a = {"Authorization": "Bearer principal-a"}
    principal_b = {"Authorization": "Bearer principal-b"}
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        ingestion_job_id = await create_ready_ingestion_job(client, principal_a)
        response = await client.post(
            f"/v1/ingestion-jobs/{ingestion_job_id}/generation-runs",
            headers={**principal_a, "Idempotency-Key": "principal-a-run"},
            json={**generation_payload(), "actor": "spoofed@example.test"},
        )
        assert response.status_code == 202, response.text
        assert response.json()["actor"] == "principal-a", response.json()
        run_location = response.headers.get("Location", "/missing")
        response = await client.get(run_location, headers=principal_a)
        assert response.status_code == 200, response.text
        response = await client.get(run_location)
        assert response.status_code == 401, response.text
        response = await client.post(
            f"/v1/ingestion-jobs/{ingestion_job_id}/generation-runs",
            headers={**principal_b, "Idempotency-Key": "principal-b-run"},
            json=generation_payload(),
        )
        assert response.status_code == 404, response.text
        response = await client.get(run_location, headers=principal_b)
        assert response.status_code == 404, response.text
        response = await client.get(
            f"/v1/generation-runs/{launcher.run_ids[0]}/events",
            headers=principal_b,
        )
        assert response.status_code == 404, response.text


def _assert_trace_span(
    tracer: RecordingTracer,
    name: str,
    attributes: dict[str, str],
) -> None:
    """Assert one completed trace span with the safe bounded attributes."""
    span = next(record for record in tracer.spans if record.name == name)
    assert span.attributes == attributes, span
    assert span.is_completed, span


@pytest.mark.asyncio
async def test_generation_run_validation_and_idempotency_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Reject invalid quality metadata and changed idempotent bodies."""
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        authorization=HeaderPrincipalAuthorization(),
        launcher=RecordingLauncher(),
    )
    headers = {"Authorization": "Bearer principal-a"}
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        ingestion_job_id = await create_ready_ingestion_job(client, headers)
        endpoint = f"/v1/ingestion-jobs/{ingestion_job_id}/generation-runs"
        accepted = await client.post(
            endpoint,
            headers={**headers, "Idempotency-Key": "conflict-key"},
            json=generation_payload(),
        )
        changed = await client.post(
            endpoint,
            headers={**headers, "Idempotency-Key": "conflict-key"},
            json={**generation_payload(), "skip_qa_rationale": "Changed."},
        )
        missing_rationale = await client.post(
            endpoint,
            headers={**headers, "Idempotency-Key": "missing-key"},
            json={"quality_mode": "draft_without_qa", "actor": "editor"},
        )
        unsupported_mode = await client.post(
            endpoint,
            headers={**headers, "Idempotency-Key": "mode-key"},
            json={**generation_payload(), "quality_mode": "qa_gated"},
        )

    assert accepted.status_code == 202, accepted.text
    _assert_generation_run_conflict(changed)
    _assert_error_envelope(
        missing_rationale,
        _ExpectedError(
            status=400,
            code="validation_error",
            message="Missing required field: skip_qa_rationale",
            details={"field": "skip_qa_rationale", "constraint": "required"},
        ),
    )
    _assert_error_envelope(
        unsupported_mode,
        _ExpectedError(
            status=422,
            code="quality_mode_unsupported",
            message="Unsupported quality_mode: qa_gated.",
            details={"quality_mode": "qa_gated"},
        ),
    )
