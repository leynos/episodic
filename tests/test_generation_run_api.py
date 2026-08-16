"""Integration tests for generation-run REST resources."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid
from unittest import mock

import httpx
import pytest

from episodic.api import create_app
from tests.fixtures.api import build_api_dependencies

if typ.TYPE_CHECKING:
    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.types import UowFactory


@dc.dataclass(slots=True)
class RecordingLauncher:
    """Record generation runs scheduled by the HTTP adapter."""

    run_ids: list[uuid.UUID] = dc.field(default_factory=list)
    launch: mock.AsyncMock = dc.field(init=False)

    def __post_init__(self) -> None:
        """Bind the asynchronous launch surface to the run recorder."""
        self.launch = mock.AsyncMock(side_effect=self.run_ids.append)


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


@pytest.mark.asyncio
async def test_generation_run_create_replay_and_poll(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Create once, replay response metadata, and poll the stored run."""
    launcher = RecordingLauncher()
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        launcher=launcher,
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        ingestion_job_id = await _create_ready_ingestion_job(client)
        payload = _generation_payload()
        first = await client.post(
            f"/v1/ingestion-jobs/{ingestion_job_id}/generation-runs",
            headers={"Idempotency-Key": "generation-key"},
            json=payload,
        )
        replay = await client.post(
            f"/v1/ingestion-jobs/{ingestion_job_id}/generation-runs",
            headers={"Idempotency-Key": "generation-key"},
            json=payload,
        )
        run_id = launcher.run_ids[0]
        await _append_generation_events(dependencies.uow_factory, run_id)
        run_response = await client.get(first.headers.get("Location", "/missing"))
        events_response = await client.get(
            f"/v1/generation-runs/{run_id}/events",
            params={"after_seq": 1, "limit": 1},
        )

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
    assert run_response.status_code == 200, run_response.text
    assert run_response.json()["qa_status"] == "skipped", (
        f"expected skipped QA status, got {run_response.json()['qa_status']!r}"
    )
    assert run_response.json()["skip_qa_rationale"] == payload["skip_qa_rationale"], (
        f"expected rationale {payload['skip_qa_rationale']!r}, "
        f"got {run_response.json()['skip_qa_rationale']!r}"
    )
    assert run_response.headers["Retry-After"] == "1", (
        f"expected retry delay '1', got {run_response.headers['Retry-After']!r}"
    )
    _assert_generation_event_page(events_response)


@pytest.mark.asyncio
async def test_generation_run_validation_and_idempotency_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Reject invalid quality metadata and changed idempotent bodies."""
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        launcher=RecordingLauncher(),
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        ingestion_job_id = await _create_ready_ingestion_job(client)
        endpoint = f"/v1/ingestion-jobs/{ingestion_job_id}/generation-runs"
        accepted = await client.post(
            endpoint,
            headers={"Idempotency-Key": "conflict-key"},
            json=_generation_payload(),
        )
        changed = await client.post(
            endpoint,
            headers={"Idempotency-Key": "conflict-key"},
            json={**_generation_payload(), "skip_qa_rationale": "Changed."},
        )
        missing_rationale = await client.post(
            endpoint,
            headers={"Idempotency-Key": "missing-key"},
            json={"quality_mode": "draft_without_qa", "actor": "editor"},
        )
        unsupported_mode = await client.post(
            endpoint,
            headers={"Idempotency-Key": "mode-key"},
            json={**_generation_payload(), "quality_mode": "qa_gated"},
        )

    assert accepted.status_code == 202, accepted.text
    assert changed.status_code == 409, (
        f"expected conflict status 409, got {changed.status_code}"
    )
    assert changed.json()["code"] == "idempotency_conflict", (
        f"expected idempotency_conflict, got {changed.json()['code']!r}"
    )
    assert missing_rationale.status_code == 400, (
        f"expected missing-rationale status 400, got {missing_rationale.status_code}"
    )
    assert unsupported_mode.status_code == 422, (
        f"expected unsupported-mode status 422, got {unsupported_mode.status_code}"
    )


@pytest.mark.asyncio
async def test_generation_run_resource_uses_injected_factories(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run creation should use deterministic IDs and lifecycle timestamps."""
    from episodic.api.resources.generation_runs import (
        GenerationRunsResource,
        _CreateGenerationRun,
    )

    dependencies = build_api_dependencies(session_factory)
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        ingestion_job_id = uuid.UUID(await _create_ready_ingestion_job(client))

    ids = tuple(uuid.uuid7() for _ in range(4))
    now = dt.datetime(2026, 7, 22, tzinfo=dt.UTC)
    resource = GenerationRunsResource(
        dependencies.uow_factory,
        launcher=RecordingLauncher(),
        clock=lambda: now,
        uuid_factory=iter(ids).__next__,
    )
    run = await resource._create_run(
        ingestion_job_id,
        _CreateGenerationRun(
            actor="editor@example.com",
            skip_qa_rationale="Deterministic resource construction.",
            configuration={},
            budget_snapshot={},
        ),
        idempotency_key="factory-key",
        idempotency_principal_id=None,
    )

    assert run.id == ids[3], f"expected factory run id {ids[3]}, got {run.id}"
    assert run.episode_id == ids[0], (
        f"expected factory episode id {ids[0]}, got {run.episode_id}"
    )
    assert run.created_at == now, f"expected fixed creation time, got {run.created_at}"
    assert run.updated_at == now, f"expected fixed update time, got {run.updated_at}"


async def _create_ready_ingestion_job(client: httpx.AsyncClient) -> str:
    profile = await client.post(
        "/v1/series-profiles",
        json={
            "slug": "generation-api-profile",
            "title": "Generation API profile",
            "description": "Generation endpoint fixture.",
            "configuration": {},
            "actor": "editor@example.com",
        },
    )
    assert profile.status_code == 201, profile.text
    job = await client.post(
        "/v1/ingestion-jobs",
        headers={"Idempotency-Key": "generation-job-key"},
        json={"series_profile_id": profile.json()["id"]},
    )
    assert job.status_code == 201, job.text
    source = await client.post(
        f"/v1/ingestion-jobs/{job.json()['id']}/sources",
        headers={"Idempotency-Key": "generation-source-key"},
        json={
            "type": "source_uri",
            "source_uri": "https://example.test/source.txt",
            "source_type": "research_note",
            "weight": 1.0,
            "metadata": {"content": "A concise source for the episode."},
        },
    )
    assert source.status_code == 201, source.text
    return typ.cast("str", job.json()["id"])


def _generation_payload() -> dict[str, object]:
    """Return a valid no-QA generation request body."""
    return {
        "quality_mode": "draft_without_qa",
        "skip_qa_rationale": "Initial editorial draft.",
        "actor": "editor@example.com",
        "template_id": "future-template",
        "prompt_overrides": {"tone": "clear"},
        "budget_hints": {"max_tokens": 1200},
    }
