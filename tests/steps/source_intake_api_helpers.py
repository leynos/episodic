"""Low-level API helpers for source-intake BDD scenarios."""

from __future__ import annotations

import datetime as dt
import hashlib
import typing as typ
import uuid

from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.uploads import Upload, UploadState

if typ.TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def post_text_upload(
    client: httpx.AsyncClient,
    *,
    key: str,
    payload: bytes,
    content_type: str = "text/plain",
) -> httpx.Response:
    """Post a text upload with a deterministic multipart shape."""
    return await client.post(
        "/v1/uploads",
        headers={"Idempotency-Key": key},
        files={
            "file": ("source.txt", payload, "text/plain"),
            "content_type": (None, content_type),
            "declared_size": (None, str(len(payload))),
            "declared_sha256": (None, hashlib.sha256(payload).hexdigest()),
            "metadata": (None, '{"language":"en"}', "application/json"),
        },
    )


def record_error_response(response: httpx.Response, context: object) -> None:
    """Record a source-intake error response on the shared BDD context."""
    error_context = typ.cast("typ.Any", context)
    error_context.error_status = response.status_code
    error_context.error_code = typ.cast("str", response.json()["code"])


async def create_series_profile(client: httpx.AsyncClient) -> str:
    """Create a series profile through the public API and return its id."""
    response = await client.post(
        "/v1/series-profiles",
        json={
            "slug": f"bdd-source-intake-{uuid.uuid4()}",
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


async def create_ingestion_job(client: httpx.AsyncClient, profile_id: str) -> str:
    """Create an ingestion job through the public API and return its id."""
    response = await create_ingestion_job_response(
        client,
        profile_id,
        f"bdd-job-{uuid.uuid4()}",
    )
    assert response.status_code == 201, response.text
    return typ.cast("str", response.json()["id"])


async def create_ingestion_job_response(
    client: httpx.AsyncClient,
    profile_id: str,
    key: str,
) -> httpx.Response:
    """Create an ingestion job and return the raw response."""
    return await client.post(
        "/v1/ingestion-jobs",
        headers={"Idempotency-Key": key},
        json={"series_profile_id": profile_id, "target_episode_id": None},
    )


async def create_pending_upload(
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """Persist one pending upload for not-ready BDD coverage."""
    now = dt.datetime.now(dt.UTC)
    upload = Upload(
        id=uuid.uuid4(),
        owner_principal_id="api-user",
        content_type="text/plain",
        declared_size=1,
        actual_size=None,
        declared_sha256=None,
        content_hash=None,
        storage_key=f"uploads/{uuid.uuid4()}",
        state=UploadState.PENDING,
        metadata={},
        created_at=now,
        updated_at=now,
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.uploads.add(upload)
        await uow.commit()
    return upload.id


def upload_payload(upload_id: str) -> dict[str, object]:
    """Return a valid upload-source attachment payload."""
    return {
        "type": "upload",
        "upload_id": upload_id,
        "source_type": "research_paper",
        "weight": 1.0,
        "metadata": {"language": "en"},
    }


def source_uri_payload() -> dict[str, object]:
    """Return a valid URI-source attachment payload."""
    return {
        "type": "source_uri",
        "source_uri": "https://example.test/source.txt",
        "source_type": "research_paper",
        "weight": 1.0,
        "metadata": {"language": "en"},
    }
