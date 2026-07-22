"""Integration tests for generation-run REST resources."""

import dataclasses as dc
import datetime as dt
import typing as typ

import httpx
import pytest

from episodic.api import create_app
from tests.fixtures.api import build_api_dependencies

if typ.TYPE_CHECKING:
    import uuid

    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dc.dataclass(slots=True)
class RecordingLauncher:
    """Record generation runs scheduled by the HTTP adapter."""

    run_ids: list[uuid.UUID] = dc.field(default_factory=list)

    async def launch(self, run_id: uuid.UUID) -> None:
        """Record one scheduled run."""
        self.run_ids.append(run_id)


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
            f"/v1/episodes/{ingestion_job_id}/generation-runs",
            headers={"Idempotency-Key": "generation-key"},
            json=payload,
        )
        replay = await client.post(
            f"/v1/episodes/{ingestion_job_id}/generation-runs",
            headers={"Idempotency-Key": "generation-key"},
            json=payload,
        )
        run_id = launcher.run_ids[0]
        async with dependencies.uow_factory() as uow:
            for kind in ("run.started", "draft.generated"):
                await uow.generation_runs.append_event(
                    run_id,
                    kind=kind,
                    payload={"kind": kind},
                    occurred_at=dt.datetime(2026, 7, 22, tzinfo=dt.UTC),
                )
            await uow.commit()
        run_response = await client.get(first.headers.get("Location", "/missing"))
        events_response = await client.get(
            f"/v1/generation-runs/{run_id}/events",
            params={"after_seq": 1, "limit": 1},
        )

    assert first.status_code == 202, first.text
    assert replay.status_code == 202, replay.text
    assert replay.json() == first.json()
    assert replay.headers["Location"] == first.headers["Location"]
    assert replay.headers["Retry-After"] == first.headers["Retry-After"]
    assert len(launcher.run_ids) == 1
    assert run_response.status_code == 200, run_response.text
    assert run_response.json()["qa_status"] == "skipped"
    assert run_response.json()["skip_qa_rationale"] == payload["skip_qa_rationale"]
    assert run_response.headers["Retry-After"] == "1"
    assert events_response.status_code == 200, events_response.text
    assert [event["kind"] for event in events_response.json()["items"]] == [
        "draft.generated"
    ]
    assert events_response.json()["after_seq"] == 1


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
        endpoint = f"/v1/episodes/{ingestion_job_id}/generation-runs"
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
    assert changed.status_code == 409
    assert changed.json()["code"] == "idempotency_conflict"
    assert missing_rationale.status_code == 400
    assert unsupported_mode.status_code == 422


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
