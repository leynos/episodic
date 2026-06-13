"""Contract tests for source-intake REST error paths and read endpoints."""

import contextlib
import datetime as dt
import hashlib
import typing as typ
import uuid

import httpx
import pytest

from episodic.api import create_app
from episodic.canonical.storage import FilesystemObjectStore, SqlAlchemyUnitOfWork
from episodic.canonical.uploads import Upload, UploadState
from tests.fixtures.api import build_api_dependencies

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_source_upload_rejects_unsupported_content_type(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Unsupported declared upload content types return the documented 415."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        response = await _post_text_upload(
            client,
            key="unsupported-content-type",
            payload=b"hello\n",
            content_type="application/octet-stream",
        )

    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_content_type"


@pytest.mark.asyncio
async def test_source_upload_rejects_payload_larger_than_configured_cap(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Oversized upload payloads are rejected while parsing multipart bytes."""
    async with _source_intake_client(
        session_factory,
        tmp_path,
        upload_max_bytes=4,
    ) as client:
        response = await _post_text_upload(
            client,
            key="oversized-upload",
            payload=b"hello\n",
        )

    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"


@pytest.mark.asyncio
async def test_attach_source_rejects_unknown_payload_discriminator(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Unknown source attachment discriminators return the documented 422."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        response = await client.post(
            f"/v1/ingestion-jobs/{uuid.uuid4()}/sources",
            headers={"Idempotency-Key": "unknown-source-kind"},
            json={
                "type": "unknown",
                "source_type": "research_paper",
                "weight": 1.0,
                "metadata": {},
            },
        )

    assert response.status_code == 422
    assert response.json()["code"] == "source_payload_invalid"


@pytest.mark.asyncio
async def test_attach_source_reports_missing_ingestion_job(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Attaching a source URI to an unknown job returns ingestion_job_not_found."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        response = await client.post(
            f"/v1/ingestion-jobs/{uuid.uuid4()}/sources",
            headers={"Idempotency-Key": "missing-job"},
            json=_source_uri_payload(),
        )

    assert response.status_code == 404
    assert response.json()["code"] == "ingestion_job_not_found"


@pytest.mark.asyncio
async def test_attach_upload_reports_missing_upload(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Attaching an unknown upload to a known job returns upload_not_found."""
    job_id = await _create_profile_and_job(session_factory, tmp_path)
    async with _source_intake_client(session_factory, tmp_path) as client:
        response = await client.post(
            f"/v1/ingestion-jobs/{job_id}/sources",
            headers={"Idempotency-Key": "missing-upload"},
            json=_upload_payload(str(uuid.uuid4())),
        )

    assert response.status_code == 404
    assert response.json()["code"] == "upload_not_found"


@pytest.mark.asyncio
async def test_attach_upload_reports_not_ready_upload(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Attaching a pending upload returns upload_not_ready."""
    job_id = await _create_profile_and_job(session_factory, tmp_path)
    upload_id = await _create_pending_upload(session_factory)
    async with _source_intake_client(session_factory, tmp_path) as client:
        response = await client.post(
            f"/v1/ingestion-jobs/{job_id}/sources",
            headers={"Idempotency-Key": "pending-upload"},
            json=_upload_payload(str(upload_id)),
        )

    assert response.status_code == 409
    assert response.json()["code"] == "upload_not_ready"


@pytest.mark.asyncio
async def test_ingestion_job_create_reports_missing_series_profile(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Creating a job for an unknown profile returns series_profile_not_found."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        response = await client.post(
            "/v1/ingestion-jobs",
            headers={"Idempotency-Key": "missing-series-profile"},
            json={"series_profile_id": str(uuid.uuid4()), "target_episode_id": None},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "series_profile_not_found"


@pytest.mark.asyncio
async def test_upload_get_endpoint_returns_upload_metadata(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """GET /v1/uploads/{upload_id} returns the upload response envelope."""
    payload = b"hello\n"
    async with _source_intake_client(session_factory, tmp_path) as client:
        upload_response = await _post_text_upload(
            client,
            key="get-upload",
            payload=payload,
        )
        response = await client.get(f"/v1/uploads/{upload_response.json()['id']}")

    assert response.status_code == 200
    assert response.json()["content_hash"] == (
        f"sha256:{hashlib.sha256(payload).hexdigest()}"
    )


@pytest.mark.asyncio
async def test_upload_get_endpoint_reports_missing_upload(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """GET /v1/uploads/{upload_id} returns upload_not_found for unknown ids."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        response = await client.get(f"/v1/uploads/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "upload_not_found"


@pytest.mark.asyncio
async def test_ingestion_job_sources_get_endpoint_lists_sources(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """GET /v1/ingestion-jobs/{job_id}/sources returns a paged source list."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        profile_id = await _create_series_profile(client)
        upload = await _post_text_upload(client, key="list-source-upload", payload=b"x")
        job_id = await _create_ingestion_job(client, profile_id)
        attach = await client.post(
            f"/v1/ingestion-jobs/{job_id}/sources",
            headers={"Idempotency-Key": "list-source"},
            json=_upload_payload(typ.cast("str", upload.json()["id"])),
        )
        response = await client.get(f"/v1/ingestion-jobs/{job_id}/sources")

    assert attach.status_code == 201, attach.text
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["upload_id"] == upload.json()["id"]


@pytest.mark.asyncio
async def test_ingestion_job_sources_get_reports_missing_job(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """GET /v1/ingestion-jobs/{job_id}/sources reports unknown jobs."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        response = await client.get(f"/v1/ingestion-jobs/{uuid.uuid4()}/sources")

    assert response.status_code == 404
    assert response.json()["code"] == "ingestion_job_not_found"


@contextlib.asynccontextmanager
async def _source_intake_client(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    *,
    upload_max_bytes: int | None = None,
) -> cabc.AsyncIterator[httpx.AsyncClient]:
    """Yield an async client with source-intake object storage configured."""
    object_store = FilesystemObjectStore(tmp_path / "objects")
    dependencies = build_api_dependencies(
        session_factory,
        object_store=object_store,
        upload_max_bytes=upload_max_bytes,
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client


async def _create_series_profile(client: httpx.AsyncClient) -> str:
    """Create a series profile through the public API and return its id."""
    response = await client.post(
        "/v1/series-profiles",
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
    """Create a series profile and an ingestion job; return the job id."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        profile_id = await _create_series_profile(client)
        return await _create_ingestion_job(client, profile_id)


async def _create_pending_upload(
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """Persist one pending upload for not-ready attach tests."""
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
            "file": ("source.txt", payload, "text/plain"),
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
