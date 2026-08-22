"""Generation-run API admission failure integration tests."""

import dataclasses as dc
import typing as typ
import uuid

import httpx
import pytest

from episodic.api import create_app
from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.generation import GenerationRunAdmissionError
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


async def _post_generation_run(
    client: httpx.AsyncClient,
    job_id: str,
) -> httpx.Response:
    """Submit one authenticated generation request for a ready job."""
    return await client.post(
        f"/v1/ingestion-jobs/{job_id}/generation-runs",
        headers={
            "Authorization": "Bearer principal-a",
            "Idempotency-Key": "admission-key",
        },
        json=generation_payload(),
    )


@pytest.mark.asyncio
async def test_generation_run_admission_failure_marks_persisted_run_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Capacity rejection records one terminal run before returning HTTP 503."""
    launcher = RecordingLauncher()
    launcher.launch.side_effect = GenerationRunAdmissionError("capacity exhausted")
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        authorization=HeaderPrincipalAuthorization(),
        launcher=launcher,
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        headers = {"Authorization": "Bearer principal-a"}
        job_id = await create_ready_ingestion_job(client, headers)
        response = await _post_generation_run(client, job_id)

    assert response.status_code == 503, response.text
    assert response.json()["code"] == "generation_overloaded", response.text
    assert launcher.launch.await_count == 1, launcher.launch.await_args_list
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        job = await uow.ingestion_jobs.get(uuid.UUID(job_id))
        assert job is not None, f"missing job {job_id}"
        assert job.target_episode_id is not None, job
        runs = await uow.generation_runs.list_runs(job.target_episode_id)
    assert len(runs) == 1, runs
    assert runs[0].status is GenerationRunStatus.FAILED, runs[0]
    assert runs[0].error_category == "launcher.overloaded", runs[0]


@pytest.mark.asyncio
async def test_generation_run_scheduling_failure_marks_persisted_run_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Unexpected launcher failures leave the durable run terminal."""
    launcher = RecordingLauncher()
    launcher.launch.side_effect = RuntimeError("task allocation failed")
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        authorization=HeaderPrincipalAuthorization(),
        launcher=launcher,
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        headers = {"Authorization": "Bearer principal-a"}
        job_id = await create_ready_ingestion_job(client, headers)
        response = await _post_generation_run(client, job_id)

    assert response.status_code == 500, response.text
    assert launcher.launch.await_count == 1, launcher.launch.await_args_list
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        job = await uow.ingestion_jobs.get(uuid.UUID(job_id))
        assert job is not None, f"missing job {job_id}"
        assert job.target_episode_id is not None, job
        runs = await uow.generation_runs.list_runs(job.target_episode_id)
    assert len(runs) == 1, runs
    assert runs[0].status is GenerationRunStatus.FAILED, runs[0]
    assert runs[0].error_category == "launcher.scheduling", runs[0]


@pytest.mark.asyncio
async def test_generation_run_rejects_requests_without_a_launcher(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An unavailable launcher rejects creation before materialisation begins."""
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        authorization=HeaderPrincipalAuthorization(),
        launcher=None,
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        headers = {"Authorization": "Bearer principal-a"}
        job_id = await create_ready_ingestion_job(client, headers)
        response = await _post_generation_run(client, job_id)

    assert response.status_code == 503, response.text
    assert response.json()["code"] == "service_unavailable", response.text
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        job = await uow.ingestion_jobs.get(uuid.UUID(job_id))
    assert job is not None, f"missing job {job_id}"
    assert job.target_episode_id is None, job
