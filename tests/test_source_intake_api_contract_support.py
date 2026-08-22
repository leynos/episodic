"""Support fixtures for source-intake API contract tests."""

import contextlib
import dataclasses as dc
import datetime as dt
import hashlib
import typing as typ
import uuid

import httpx

from episodic.api import create_app
from episodic.canonical.storage import FilesystemObjectStore, SqlAlchemyUnitOfWork
from episodic.canonical.uploads import Upload, UploadState
from tests.fixtures.api import build_api_dependencies
from tests.fixtures.generation_run_api import HeaderPrincipalAuthorization

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dc.dataclass(frozen=True, slots=True)
class _UploadFixtureState:
    """Storage values that distinguish pending and ready upload fixtures."""

    state: UploadState
    actual_size: int | None
    content_hash: str | None


@contextlib.asynccontextmanager
async def _source_intake_client(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    *,
    upload_max_bytes: int | None = None,
    principal: str = "principal-a",
) -> cabc.AsyncIterator[httpx.AsyncClient]:
    """Yield an async client with source-intake object storage configured."""
    dependencies = build_api_dependencies(
        session_factory,
        authorization=HeaderPrincipalAuthorization(),
        object_store=FilesystemObjectStore(tmp_path / "objects"),
        upload_max_bytes=upload_max_bytes,
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {principal}"},
    ) as client:
        yield client


async def _create_series_profile(client: httpx.AsyncClient) -> str:
    """Create a series profile through the public API and return its id."""
    response = await client.post(
        "/v1/series-profiles",
        headers={"Idempotency-Key": f"profile-{uuid.uuid4()}"},
        json={
            "slug": f"source-intake-{uuid.uuid4()}",
            "title": "Source Intake",
            "description": "Created for intake contract tests.",
            "configuration": {"tone": "clear"},
            "guardrails": {"instruction": "Keep claims sourced."},
            "actor": "api-user@example.com",
            "note": "Initial profile",
        },
    )
    assert response.status_code == 201, response.text
    return typ.cast("str", response.json()["id"])


async def _create_ingestion_job(client: httpx.AsyncClient, profile_id: str) -> str:
    """Create an ingestion job through the public API and return its id."""
    response = await client.post(
        "/v1/ingestion-jobs",
        headers={"Idempotency-Key": f"job-{uuid.uuid4()}"},
        json={"series_profile_id": profile_id, "target_episode_id": None},
    )
    assert response.status_code == 201, response.text
    return typ.cast("str", response.json()["id"])


async def _create_profile_and_job(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> str:
    """Create a series profile and ingestion job; return the job id."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        return await _create_ingestion_job(
            client,
            await _create_series_profile(client),
        )


async def _create_pending_upload(
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """Persist one pending upload for not-ready attach tests."""
    return await _create_upload(
        session_factory,
        owner="principal-a",
        expected=_UploadFixtureState(
            state=UploadState.PENDING,
            actual_size=None,
            content_hash=None,
        ),
    )


async def _create_upload(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner: str,
    expected: _UploadFixtureState,
) -> uuid.UUID:
    """Persist one upload fixture and return its identifier."""
    now = dt.datetime.now(dt.UTC)
    upload = Upload(
        id=uuid.uuid4(),
        owner_principal_id=owner,
        content_type="text/plain",
        declared_size=1,
        actual_size=expected.actual_size,
        declared_sha256=None,
        content_hash=expected.content_hash,
        storage_key=f"uploads/{uuid.uuid4()}",
        state=expected.state,
        metadata={},
        created_at=now,
        updated_at=now,
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.uploads.add(upload)
        await uow.commit()
    return upload.id


async def _create_ready_upload(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner: str,
) -> uuid.UUID:
    """Persist one owner-bound upload for metadata access checks."""
    return await _create_upload(
        session_factory,
        owner=owner,
        expected=_UploadFixtureState(
            state=UploadState.READY,
            actual_size=1,
            content_hash="sha256:upload",
        ),
    )


async def _post_attach_source(
    client: httpx.AsyncClient,
    job_id: str,
    *,
    idempotency_key: str,
    payload: dict[str, object],
) -> httpx.Response:
    """POST a source attachment to an ingestion job and return the response."""
    return await client.post(
        f"/v1/ingestion-jobs/{job_id}/sources",
        headers={"Idempotency-Key": idempotency_key},
        json=payload,
    )


async def _post_text_upload(
    client: httpx.AsyncClient,
    *,
    key: str,
    payload: bytes,
    content_type: str = "text/plain",
) -> httpx.Response:
    """Post a deterministic text upload multipart request."""
    return await client.post(
        "/v1/uploads",
        headers={"Idempotency-Key": key},
        files={
            "file": ("source.txt", payload, content_type),
            "content_type": (None, content_type),
            "declared_size": (None, str(len(payload))),
            "declared_sha256": (None, hashlib.sha256(payload).hexdigest()),
        },
    )


def _upload_payload(upload_id: str) -> dict[str, object]:
    """Return a valid upload-source attachment payload."""
    return {
        "type": "upload",
        "upload_id": upload_id,
        "source_type": "research_paper",
        "weight": 1.0,
        "metadata": {"language": "en"},
    }


def _source_uri_payload() -> dict[str, object]:
    """Return a valid URI-source attachment payload."""
    return {
        "type": "source_uri",
        "source_uri": "https://example.test/source.txt",
        "source_type": "research_paper",
        "weight": 1.0,
        "metadata": {"language": "en"},
    }
