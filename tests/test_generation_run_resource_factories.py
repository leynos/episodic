"""Deterministic factory seams for generation-run HTTP resource creation."""

import datetime as dt
import typing as typ
import uuid

import httpx
import pytest

from episodic.api import create_app
from episodic.api.resources.generation_runs import (
    GenerationRunsResource,
    _CreateGenerationRun,
)
from tests.fixtures.api import build_api_dependencies
from tests.fixtures.generation_run_api import (
    HeaderPrincipalAuthorization,
    RecordingLauncher,
    create_ready_ingestion_job,
)

if typ.TYPE_CHECKING:
    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_generation_run_resource_uses_injected_factories(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run creation should use deterministic IDs and lifecycle timestamps."""
    dependencies = build_api_dependencies(
        session_factory,
        authorization=HeaderPrincipalAuthorization(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=typ.cast("_ASGIApp", create_app(dependencies))
        ),
        base_url="http://testserver",
    ) as client:
        ingestion_job_id = uuid.UUID(
            await create_ready_ingestion_job(
                client, {"Authorization": "Bearer principal-a"}
            )
        )

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
            skip_qa_rationale="Deterministic resource construction.",
            configuration={},
            budget_snapshot={},
        ),
        actor="principal-a",
        idempotency_key="factory-key",
    )

    assert run.id == ids[2], f"expected factory run id {ids[2]}, got {run.id}"
    assert run.episode_id == ids[0], (
        f"expected factory episode id {ids[0]}, got {run.episode_id}"
    )
    assert run.created_at == now, f"expected fixed creation time, got {run.created_at}"
    assert run.updated_at == now, f"expected fixed update time, got {run.updated_at}"
