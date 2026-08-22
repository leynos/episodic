"""Contract tests for source-intake REST error paths and read endpoints."""

import dataclasses as dc
import hashlib
import typing as typ
import uuid

import httpx
import pytest
import sqlalchemy as sa

from episodic.api import create_app
from episodic.canonical.storage import (
    FilesystemObjectStore,
    IngestionJobRecord,
)
from tests.fixtures.api import build_api_dependencies
from tests.test_source_intake_api_contract_support import (
    _create_ingestion_job,
    _create_pending_upload,
    _create_profile_and_job,
    _create_ready_upload,
    _create_series_profile,
    _post_attach_source,
    _post_text_upload,
    _source_intake_client,
    _source_uri_payload,
    _upload_payload,
)

if typ.TYPE_CHECKING:
    from pathlib import Path

    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dc.dataclass(frozen=True, slots=True)
class _InvalidUploadExpectation:
    """Expected result for a rejected source-upload attachment."""

    create_pending_upload: bool
    idempotency_key: str
    status_code: int
    code: str


def _assert_api_error(
    response: httpx.Response,
    *,
    status_code: int,
    code: str,
) -> None:
    """Assert an API error response."""
    assert response.status_code == status_code, response.text
    payload = typ.cast("dict[str, object]", response.json())
    assert payload["code"] == code, response.text


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

    _assert_api_error(
        response,
        status_code=415,
        code="unsupported_content_type",
    )


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

    _assert_api_error(response, status_code=413, code="payload_too_large")


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

    _assert_api_error(
        response,
        status_code=422,
        code="source_payload_invalid",
    )


@pytest.mark.asyncio
async def test_attach_source_reports_missing_ingestion_job(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Attaching a source URI to an unknown job returns ingestion_job_not_found."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        response = await _post_attach_source(
            client,
            str(uuid.uuid4()),
            idempotency_key="missing-job",
            payload=_source_uri_payload(),
        )

    _assert_api_error(
        response,
        status_code=404,
        code="ingestion_job_not_found",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected",
    [
        pytest.param(
            _InvalidUploadExpectation(
                create_pending_upload=False,
                idempotency_key="missing-upload",
                status_code=404,
                code="upload_not_found",
            ),
            id="missing_upload",
        ),
        pytest.param(
            _InvalidUploadExpectation(
                create_pending_upload=True,
                idempotency_key="pending-upload",
                status_code=409,
                code="upload_not_ready",
            ),
            id="not_ready_upload",
        ),
    ],
)
async def test_attach_upload_reports_invalid_upload(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    expected: _InvalidUploadExpectation,
) -> None:
    """Upload attachment rejects missing and non-ready uploads."""
    job_id = await _create_profile_and_job(session_factory, tmp_path)
    if expected.create_pending_upload:
        upload_id = await _create_pending_upload(session_factory)
    else:
        upload_id = uuid.uuid4()
    async with _source_intake_client(session_factory, tmp_path) as client:
        response = await _post_attach_source(
            client,
            job_id,
            idempotency_key=expected.idempotency_key,
            payload=_upload_payload(str(upload_id)),
        )

    _assert_api_error(
        response,
        status_code=expected.status_code,
        code=expected.code,
    )


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

    _assert_api_error(
        response,
        status_code=404,
        code="series_profile_not_found",
    )


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

    assert response.status_code == 200, "upload metadata GET must return HTTP 200"
    assert response.json()["content_hash"] == (
        f"sha256:{hashlib.sha256(payload).hexdigest()}"
    ), "upload content_hash must match the uploaded payload"


@pytest.mark.asyncio
async def test_upload_get_endpoint_reports_missing_upload(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """GET /v1/uploads/{upload_id} returns upload_not_found for unknown ids."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        response = await client.get(f"/v1/uploads/{uuid.uuid4()}")

    _assert_api_error(response, status_code=404, code="upload_not_found")


@pytest.mark.asyncio
async def test_source_intake_hides_other_principals_resources(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A different principal cannot read or attach another owner's intake data."""
    async with _source_intake_client(session_factory, tmp_path) as owner:
        profile_id = await _create_series_profile(owner)
        upload = await _post_text_upload(owner, key="owned-upload", payload=b"x")
        job_id = await _create_ingestion_job(owner, profile_id)
        attached = await _post_attach_source(
            owner,
            job_id,
            idempotency_key="owned-source",
            payload=_upload_payload(typ.cast("str", upload.json()["id"])),
        )
        assert attached.status_code == 201, attached.text

    async with _source_intake_client(
        session_factory,
        tmp_path,
        principal="principal-b",
    ) as other:
        upload_response = await other.get(f"/v1/uploads/{upload.json()['id']}")
        job_response = await other.get(f"/v1/ingestion-jobs/{job_id}")
        sources_response = await other.get(f"/v1/ingestion-jobs/{job_id}/sources")
        attach_response = await _post_attach_source(
            other,
            job_id,
            idempotency_key="other-source",
            payload=_source_uri_payload(),
        )
        listing_response = await other.get("/v1/ingestion-jobs")

    for response, code in (
        (upload_response, "upload_not_found"),
        (job_response, "ingestion_job_not_found"),
        (sources_response, "ingestion_job_not_found"),
        (attach_response, "ingestion_job_not_found"),
    ):
        _assert_api_error(response, status_code=404, code=code)
    assert listing_response.status_code == 200, listing_response.text
    assert listing_response.json()["items"] == [], listing_response.json()


@pytest.mark.asyncio
async def test_source_intake_rejects_client_target_episode_id(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Client-selected episode identifiers do not create ingestion jobs."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        profile_id = await _create_series_profile(client)
        response = await client.post(
            "/v1/ingestion-jobs",
            headers={"Idempotency-Key": "client-target"},
            json={
                "series_profile_id": profile_id,
                "target_episode_id": str(uuid.uuid7()),
            },
        )

    _assert_api_error(response, status_code=400, code="validation_error")
    assert response.json()["details"] == {
        "field": "target_episode_id",
        "constraint": "unsupported",
    }, response.text
    async with session_factory() as session:
        count = await session.scalar(sa.select(sa.func.count(IngestionJobRecord.id)))
    assert count == 0, f"ingestion jobs created after rejected request: {count}"


@pytest.mark.asyncio
async def test_permit_all_composition_hides_named_upload_without_principal(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A missing principal cannot read a named upload under PermitAll tests."""
    upload_id = await _create_ready_upload(session_factory, owner="principal-a")
    dependencies = build_api_dependencies(
        session_factory,
        object_store=FilesystemObjectStore(tmp_path / "objects"),
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get(f"/v1/uploads/{upload_id}")

    _assert_api_error(response, status_code=404, code="upload_not_found")


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
    assert response.status_code == 200, "source-list GET must return HTTP 200"
    assert response.json()["total"] == 1, "source-list total must equal one"
    assert response.json()["items"][0]["upload_id"] == upload.json()["id"], (
        "listed source upload_id must identify the attached upload"
    )


@pytest.mark.asyncio
async def test_ingestion_job_sources_get_reports_missing_job(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """GET /v1/ingestion-jobs/{job_id}/sources reports unknown jobs."""
    async with _source_intake_client(session_factory, tmp_path) as client:
        response = await client.get(f"/v1/ingestion-jobs/{uuid.uuid4()}/sources")

    _assert_api_error(
        response,
        status_code=404,
        code="ingestion_job_not_found",
    )
