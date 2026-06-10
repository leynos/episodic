"""Behavioural tests for source-intake upload and attachment workflows."""

from __future__ import annotations

import asyncio
import dataclasses as dc
import hashlib
import typing as typ

import httpx
from pytest_bdd import given, scenario, then, when

from episodic.api import create_app
from episodic.canonical.storage import FilesystemObjectStore
from tests.fixtures.api import build_api_dependencies

if typ.TYPE_CHECKING:
    from pathlib import Path

    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dc.dataclass(slots=True)
class SourceIntakeContext:
    """Shared state for source-intake BDD steps."""

    upload: dict[str, object] | None = None
    upload_replay: dict[str, object] | None = None
    conflict: dict[str, object] | None = None
    conflict_status: int | None = None
    job: dict[str, object] | None = None
    source: dict[str, object] | None = None
    status: dict[str, object] | None = None


@scenario(
    "../features/source_intake.feature",
    "Editorial team uploads and attaches source material",
)
def test_source_intake_behaviour() -> None:
    """Run source-intake API scenario."""


@given("source-intake API fixtures exist", target_fixture="context")
def source_intake_fixtures() -> SourceIntakeContext:
    """Create an empty context for the source-intake API scenario."""
    return SourceIntakeContext()


@when("an editor uploads source material and attaches it to a new ingestion job")
def upload_and_attach_source(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Exercise the public upload, job creation, source attachment, and poll flow."""

    async def _run_workflow() -> None:
        dependencies = build_api_dependencies(
            session_factory,
            object_store=FilesystemObjectStore(tmp_path / "bdd-objects"),
        )
        transport = httpx.ASGITransport(
            app=typ.cast("_ASGIApp", create_app(dependencies))
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            profile_id = await _create_series_profile(client)
            upload = await _post_text_upload(
                client,
                key="bdd-upload-key",
                payload=b"source\n",
            )
            upload_replay = await _post_text_upload(
                client,
                key="bdd-upload-key",
                payload=b"source\n",
            )
            conflict_first = await _post_text_upload(
                client,
                key="bdd-conflict-key",
                payload=b"alpha\n",
            )
            conflict = await _post_text_upload(
                client,
                key="bdd-conflict-key",
                payload=b"beta\n",
            )
            job = await client.post(
                "/v1/ingestion-jobs",
                headers={"Idempotency-Key": "bdd-job-key"},
                json={"series_profile_id": profile_id, "target_episode_id": None},
            )
            source = await client.post(
                f"/v1/ingestion-jobs/{job.json()['id']}/sources",
                headers={"Idempotency-Key": "bdd-source-key"},
                json={
                    "type": "upload",
                    "upload_id": upload.json()["id"],
                    "source_type": "research_paper",
                    "weight": 1.0,
                    "metadata": {"language": "en"},
                },
            )
            status = await client.get(f"/v1/ingestion-jobs/{job.json()['id']}")

        assert upload.status_code == 201, upload.text
        assert upload_replay.status_code == 201, upload_replay.text
        assert conflict_first.status_code == 201, conflict_first.text
        assert job.status_code == 201, job.text
        assert source.status_code == 201, source.text
        assert status.status_code == 200, status.text
        context.upload = typ.cast("dict[str, object]", upload.json())
        context.upload_replay = typ.cast("dict[str, object]", upload_replay.json())
        context.conflict = typ.cast("dict[str, object]", conflict.json())
        context.conflict_status = conflict.status_code
        context.job = typ.cast("dict[str, object]", job.json())
        context.source = typ.cast("dict[str, object]", source.json())
        context.status = typ.cast("dict[str, object]", status.json())

    asyncio.run(_run_workflow())


@then("the ingestion job is ready for generation")
def assert_job_ready(context: SourceIntakeContext) -> None:
    """Verify the source attachment transitioned the intake state."""
    assert context.upload is not None
    assert context.job is not None
    assert context.source is not None
    assert context.status is not None
    assert context.job["intake_state"] == "awaiting_sources"
    assert context.source["upload_id"] == context.upload["id"]
    assert context.status["intake_state"] == "ready_for_generation"


@then("repeated upload requests replay the stored response")
def assert_upload_replay(context: SourceIntakeContext) -> None:
    """Verify an identical idempotency key/body pair returns the stored upload."""
    assert context.upload is not None
    assert context.upload_replay == context.upload


@then("changed upload bodies with the same idempotency key conflict")
def assert_upload_conflict(context: SourceIntakeContext) -> None:
    """Verify a reused idempotency key with a different body returns 409."""
    assert context.conflict_status == 409
    assert context.conflict is not None
    assert context.conflict["code"] == "idempotency_conflict"


async def _create_series_profile(client: httpx.AsyncClient) -> str:
    """Create a series profile through the public API and return its id."""
    response = await client.post(
        "/v1/series-profiles",
        json={
            "slug": "bdd-source-intake",
            "title": "BDD Source Intake",
            "description": "Created for source-intake behaviour tests.",
            "configuration": {"tone": "clear"},
            "guardrails": {"instruction": "Keep claims sourced."},
            "actor": "bdd-source-intake@example.com",
            "note": "Initial profile",
        },
    )
    assert response.status_code == 201, response.text
    return typ.cast("str", response.json()["id"])


async def _post_text_upload(
    client: httpx.AsyncClient,
    *,
    key: str,
    payload: bytes,
) -> httpx.Response:
    """Post a text upload with a deterministic multipart shape."""
    return await client.post(
        "/v1/uploads",
        headers={"Idempotency-Key": key},
        files={
            "file": ("source.txt", payload, "text/plain"),
            "content_type": (None, "text/plain"),
            "declared_size": (None, str(len(payload))),
            "declared_sha256": (None, hashlib.sha256(payload).hexdigest()),
            "metadata": (None, '{"language":"en"}', "application/json"),
        },
    )
