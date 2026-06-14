"""Support helpers for source-intake BDD scenarios."""

from __future__ import annotations

import asyncio
import dataclasses as dc
import typing as typ
import uuid

import httpx

from episodic.api import create_app
from episodic.canonical.storage import FilesystemObjectStore
from tests.fixtures.api import build_api_dependencies
from tests.steps.source_intake_api_helpers import (
    create_ingestion_job,
    create_ingestion_job_response,
    create_pending_upload,
    create_series_profile,
    post_text_upload,
    record_error_response,
    source_uri_payload,
    upload_payload,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

type SourceIntakeAction = cabc.Callable[
    [httpx.AsyncClient, SourceIntakeContext],
    cabc.Awaitable[None],
]


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
    error_status: int | None = None
    error_code: str | None = None
    source_list: dict[str, object] | None = None


@dc.dataclass(frozen=True, slots=True)
class _SourceIntakeAppConfig:
    """Infrastructure wiring for a single BDD test app instance."""

    session_factory: async_sessionmaker[AsyncSession]
    tmp_path: Path
    upload_max_bytes: int | None = None


def run_intake_workflow(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Run the happy-path source-intake workflow."""
    _run_source_intake_call(
        context,
        _SourceIntakeAppConfig(session_factory=session_factory, tmp_path=tmp_path),
        _run_intake_api_calls,
    )


def _run_single_error_call(
    context: SourceIntakeContext,
    config: _SourceIntakeAppConfig,
    request_fn: cabc.Callable[[httpx.AsyncClient], cabc.Awaitable[httpx.Response]],
) -> None:
    """Run a single HTTP action, recording the error response into context."""

    async def _action(
        client: httpx.AsyncClient,
        scenario_context: SourceIntakeContext,
    ) -> None:
        response = await request_fn(client)
        record_error_response(response, scenario_context)

    _run_source_intake_call(
        context,
        config,
        _action,
    )


def upload_unsupported_content_type(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Upload source material whose declared content type is not allowlisted."""
    _run_single_error_call(
        context,
        _SourceIntakeAppConfig(session_factory=session_factory, tmp_path=tmp_path),
        lambda client: post_text_upload(
            client,
            key="bdd-unsupported-content-type",
            payload=b"source\n",
            content_type="application/octet-stream",
        ),
    )


def upload_oversized_source(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Upload source material that exceeds the configured byte cap."""
    _run_single_error_call(
        context,
        _SourceIntakeAppConfig(
            session_factory=session_factory,
            tmp_path=tmp_path,
            upload_max_bytes=4,
        ),
        lambda client: post_text_upload(
            client,
            key="bdd-oversized-source",
            payload=b"source\n",
        ),
    )


def attach_unknown_source_discriminator(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Attach source material with an invalid ``type`` discriminator."""
    _run_single_error_call(
        context,
        _SourceIntakeAppConfig(session_factory=session_factory, tmp_path=tmp_path),
        lambda client: client.post(
            f"/v1/ingestion-jobs/{uuid.uuid4()}/sources",
            headers={"Idempotency-Key": "bdd-unknown-source-kind"},
            json={
                "type": "unknown",
                "source_type": "research_paper",
                "weight": 1.0,
                "metadata": {},
            },
        ),
    )


def attach_to_missing_job(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Attach source material to an ingestion job that does not exist."""
    _run_single_error_call(
        context,
        _SourceIntakeAppConfig(session_factory=session_factory, tmp_path=tmp_path),
        lambda client: client.post(
            f"/v1/ingestion-jobs/{uuid.uuid4()}/sources",
            headers={"Idempotency-Key": "bdd-missing-job"},
            json=source_uri_payload(),
        ),
    )


async def _attach_upload_to_new_job(
    client: httpx.AsyncClient,
    *,
    upload_id: str,
    idempotency_key: str,
) -> httpx.Response:
    """Create a profile and ingestion job, then POST an upload attachment."""
    profile_id = await create_series_profile(client)
    job_id = await create_ingestion_job(client, profile_id)
    return await client.post(
        f"/v1/ingestion-jobs/{job_id}/sources",
        headers={"Idempotency-Key": idempotency_key},
        json=upload_payload(upload_id),
    )


def attach_missing_upload(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Attach an unknown upload to a known ingestion job."""
    _run_single_error_call(
        context,
        _SourceIntakeAppConfig(session_factory=session_factory, tmp_path=tmp_path),
        lambda client: _attach_upload_to_new_job(
            client,
            upload_id=str(uuid.uuid4()),
            idempotency_key="bdd-missing-upload",
        ),
    )


def attach_pending_upload(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Attach a pending upload to a known ingestion job."""

    async def _request(client: httpx.AsyncClient) -> httpx.Response:
        upload_id = await create_pending_upload(session_factory)
        return await _attach_upload_to_new_job(
            client,
            upload_id=str(upload_id),
            idempotency_key="bdd-pending-upload",
        )

    _run_single_error_call(
        context,
        _SourceIntakeAppConfig(session_factory=session_factory, tmp_path=tmp_path),
        _request,
    )


def list_attached_sources(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """List source material attached to a new ingestion job."""

    async def _action(
        client: httpx.AsyncClient,
        scenario_context: SourceIntakeContext,
    ) -> None:
        profile_id = await create_series_profile(client)
        upload = await post_text_upload(
            client,
            key="bdd-list-source-upload",
            payload=b"source\n",
        )
        job_id = await create_ingestion_job(client, profile_id)
        source = await client.post(
            f"/v1/ingestion-jobs/{job_id}/sources",
            headers={"Idempotency-Key": "bdd-list-source"},
            json=upload_payload(typ.cast("str", upload.json()["id"])),
        )
        response = await client.get(f"/v1/ingestion-jobs/{job_id}/sources")
        assert source.status_code == 201, source.text
        scenario_context.upload = typ.cast("dict[str, object]", upload.json())
        scenario_context.source_list = typ.cast("dict[str, object]", response.json())

    _run_source_intake_call(
        context,
        _SourceIntakeAppConfig(session_factory=session_factory, tmp_path=tmp_path),
        _action,
    )


def _run_source_intake_call(
    context: SourceIntakeContext,
    config: _SourceIntakeAppConfig,
    action: SourceIntakeAction,
) -> None:
    """Run one BDD action against the source-intake ASGI app."""

    async def _run_workflow() -> None:
        dependencies = build_api_dependencies(
            config.session_factory,
            object_store=FilesystemObjectStore(config.tmp_path / "bdd-objects"),
            upload_max_bytes=config.upload_max_bytes,
        )
        transport = httpx.ASGITransport(
            app=typ.cast("_ASGIApp", create_app(dependencies))
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            await action(client, context)

    asyncio.run(_run_workflow())


async def _run_intake_api_calls(
    client: httpx.AsyncClient,
    context: SourceIntakeContext,
) -> None:
    """Run the source-intake happy path and record response payloads."""
    profile_id = await create_series_profile(client)
    upload = await post_text_upload(client, key="bdd-upload-key", payload=b"source\n")
    upload_replay = await post_text_upload(
        client,
        key="bdd-upload-key",
        payload=b"source\n",
    )
    conflict_first = await post_text_upload(
        client,
        key="bdd-conflict-key",
        payload=b"alpha\n",
    )
    conflict = await post_text_upload(
        client,
        key="bdd-conflict-key",
        payload=b"beta\n",
    )
    job = await create_ingestion_job_response(client, profile_id, "bdd-job-key")
    source = await client.post(
        f"/v1/ingestion-jobs/{job.json()['id']}/sources",
        headers={"Idempotency-Key": "bdd-source-key"},
        json=upload_payload(typ.cast("str", upload.json()["id"])),
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
