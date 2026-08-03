"""Integration tests for the source-intake REST workflow."""

import asyncio
import dataclasses
import datetime as dt
import hashlib
import typing as typ

import httpx
import pytest

from episodic.api import create_app
from episodic.api.authorization import (
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationResult,
)
from episodic.api.source_idempotency import (
    IdempotentResponse,
    _encode_outcome,
    _idempotent_response,
)
from episodic.canonical.idempotency import Acquired, IdempotencyAcquireRequest
from episodic.canonical.storage import FilesystemObjectStore, SqlAlchemyUnitOfWork
from episodic.canonical.storage.source_intake_models import IdempotencyRecordModel
from tests.fixtures.api import build_api_dependencies

if typ.TYPE_CHECKING:
    from pathlib import Path

    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from syrupy.assertion import SnapshotAssertion


class HeaderPrincipalAuthorization:
    """Permit requests and derive the principal from the Authorization header."""

    async def decide(self, context: AuthorizationContext) -> AuthorizationResult:
        """Return the header value as the authenticated principal."""
        principal = context.authorization_header
        return AuthorizationResult(
            decision=AuthorizationDecision.PERMIT,
            principal_id=principal,
        )


@pytest.mark.asyncio
async def test_source_intake_upload_job_and_attach_flow(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Client can upload bytes, create a job, attach the upload, and poll ready."""
    object_store = FilesystemObjectStore(tmp_path / "objects")
    dependencies = build_api_dependencies(session_factory, object_store=object_store)
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        profile_id = await _create_series_profile(client)
        upload_response = await _post_text_upload(
            client,
            _TextUploadRequest(
                key="upload-key",
                payload=b"hello\n",
                metadata='{"language":"en"}',
            ),
        )
        assert upload_response.status_code == 201, upload_response.text
        replay_response = await _post_text_upload(
            client,
            _TextUploadRequest(
                key="upload-key",
                payload=b"hello\n",
                metadata='{"language":"en"}',
            ),
        )
        job_response = await client.post(
            "/v1/ingestion-jobs",
            headers={"Idempotency-Key": "job-key"},
            json={"series_profile_id": profile_id, "target_episode_id": None},
        )
        assert job_response.status_code == 201, "Expected values to match"
        source_response = await client.post(
            f"/v1/ingestion-jobs/{job_response.json()['id']}/sources",
            headers={"Idempotency-Key": "source-key"},
            json={
                "type": "upload",
                "upload_id": upload_response.json()["id"],
                "source_type": "research_paper",
                "weight": 1.0,
                "metadata": {"language": "en"},
            },
        )
        status_response = await client.get(
            f"/v1/ingestion-jobs/{job_response.json()['id']}"
        )

    assert replay_response.status_code == 201, "Expected values to match"
    assert replay_response.json() == upload_response.json(), "Expected values to match"
    assert upload_response.json()["content_hash"].startswith("sha256:"), (
        "Expected value to have the required prefix"
    )
    assert job_response.json()["intake_state"] == "awaiting_sources", (
        "Expected values to match"
    )
    assert source_response.status_code == 201, "Expected values to match"
    assert source_response.json()["upload_id"] == upload_response.json()["id"], (
        "Expected values to match"
    )
    assert status_response.status_code == 200, "Expected values to match"
    assert status_response.json()["intake_state"] == "ready_for_generation", (
        "Expected values to match"
    )


@pytest.mark.asyncio
async def test_source_intake_idempotency_conflict(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Same idempotency key with different upload body returns 409."""
    object_store = FilesystemObjectStore(tmp_path / "objects")
    dependencies = build_api_dependencies(session_factory, object_store=object_store)
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        first_request = _TextUploadRequest(key="conflict-key", payload=b"hello\n")
        second_request = _TextUploadRequest(key="conflict-key", payload=b"bye\n")
        first = await _post_text_upload(client, first_request)
        second = await _post_text_upload(client, second_request)

    assert first.status_code == 201, first.text
    assert second.status_code == 409, "Expected values to match"
    assert second.json()["code"] == "idempotency_conflict", "Expected values to match"


@pytest.mark.asyncio
async def test_source_intake_idempotency_is_scoped_by_authorized_principal(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """The authorization principal scopes idempotency records for upload replay."""
    object_store = FilesystemObjectStore(tmp_path / "objects")
    dependencies = build_api_dependencies(
        session_factory,
        authorization=HeaderPrincipalAuthorization(),
        object_store=object_store,
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        principal_a_request = _TextUploadRequest(
            key="principal-key",
            payload=b"same\n",
            authorization="principal-a",
        )
        principal_b_request = _TextUploadRequest(
            key="principal-key",
            payload=b"same\n",
            authorization="principal-b",
        )
        first = await _post_text_upload(client, principal_a_request)
        second = await _post_text_upload(client, principal_b_request)
        replay = await _post_text_upload(client, principal_a_request)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert replay.status_code == 201, replay.text
    assert first.json()["id"] != second.json()["id"], "Expected values to differ"
    assert replay.json()["id"] == first.json()["id"], "Expected values to match"


@pytest.mark.asyncio
async def test_source_intake_response_envelope_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot stable fields from source-intake response envelopes."""
    object_store = FilesystemObjectStore(tmp_path / "objects")
    dependencies = build_api_dependencies(session_factory, object_store=object_store)
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        profile_id = await _create_series_profile(client)
        upload_response = await _post_text_upload(
            client,
            _TextUploadRequest(key="snapshot-upload-key", payload=b"snapshot\n"),
        )
        job_response = await client.post(
            "/v1/ingestion-jobs",
            headers={"Idempotency-Key": "snapshot-job-key"},
            json={"series_profile_id": profile_id, "target_episode_id": None},
        )
        source_response = await client.post(
            f"/v1/ingestion-jobs/{job_response.json()['id']}/sources",
            headers={"Idempotency-Key": "snapshot-source-key"},
            json={
                "type": "upload",
                "upload_id": upload_response.json()["id"],
                "source_type": "research_paper",
                "weight": 0.75,
                "metadata": {"language": "en"},
            },
        )
        status_response = await client.get(
            f"/v1/ingestion-jobs/{job_response.json()['id']}"
        )

    assert upload_response.status_code == 201, upload_response.text
    assert job_response.status_code == 201, job_response.text
    assert source_response.status_code == 201, source_response.text
    assert status_response.status_code == 200, status_response.text
    response_envelopes = {
        "upload": _stable_upload_fields(upload_response.json()),
        "job": _stable_job_fields(job_response.json()),
        "source": _stable_source_fields(source_response.json()),
        "status": _stable_job_fields(status_response.json()),
    }
    assert response_envelopes == snapshot, "actual output must match snapshot"


async def _acquire_and_run_failing_work(
    session_factory: async_sessionmaker[AsyncSession],
    idempotency_key: str,
) -> Acquired:
    """Acquire an idempotency record and exercise failing work."""
    request = _idempotency_request(idempotency_key)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        outcome = await uow.idempotency.acquire(request=request)
        await uow.commit()
    assert isinstance(outcome, Acquired), "Expected value to have the required type"

    async def failing_work() -> IdempotentResponse:
        await asyncio.sleep(0)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await _idempotent_response(
            lambda: SqlAlchemyUnitOfWork(session_factory),
            outcome,
            failing_work,
        )
    return outcome


@pytest.mark.asyncio
async def test_idempotent_response_deletes_in_flight_on_work_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A failed acquired operation clears its in-flight idempotency row."""
    outcome = await _acquire_and_run_failing_work(
        session_factory, "failure-cleanup-key"
    )

    async with session_factory() as session:
        record = await session.get(IdempotencyRecordModel, outcome.record_id)

    assert record is None, "Expected value to be absent"


@pytest.mark.asyncio
async def test_idempotent_response_allows_retry_after_work_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A failed acquired operation can be acquired again immediately."""
    await _acquire_and_run_failing_work(session_factory, "failure-retry-key")

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        retry_outcome = await uow.idempotency.acquire(
            request=_idempotency_request("failure-retry-key")
        )
        await uow.commit()

    assert isinstance(retry_outcome, Acquired), (
        "Expected value to have the required type"
    )


def test_idempotency_outcome_encoding_rejects_large_payloads() -> None:
    """Idempotency replay envelopes are capped at 64 KiB."""
    response = IdempotentResponse(
        "201 Created",
        {"content": "x" * (64 * 1024)},
    )

    with pytest.raises(ValueError, match="64 KiB"):
        _encode_outcome(response)


async def _create_series_profile(client: httpx.AsyncClient) -> str:
    """Create a series profile through the public API and return its id."""
    response = await client.post(
        "/v1/series-profiles",
        json={
            "slug": "source-intake",
            "title": "Source Intake",
            "description": "Created for intake tests.",
            "configuration": {"tone": "clear"},
            "guardrails": {"instruction": "Keep claims sourced."},
            "actor": "api-user@example.com",
            "note": "Initial profile",
        },
    )
    assert response.status_code == 201, response.text
    return typ.cast("str", response.json()["id"])


def _stable_upload_fields(payload: dict[str, object]) -> dict[str, object]:
    """Return the stable upload fields that define the public response shape."""
    content_hash = typ.cast("str", payload["content_hash"])
    return {
        "state": payload["state"],
        "content_hash_algorithm": content_hash.split(":", maxsplit=1)[0],
        "content_type": payload["content_type"],
        "size_bytes": payload["size_bytes"],
        "metadata": payload["metadata"],
    }


def _stable_job_fields(payload: dict[str, object]) -> dict[str, object]:
    """Return stable ingestion-job response fields."""
    return {
        "status": payload["status"],
        "intake_state": payload["intake_state"],
        "next_poll_after_seconds": payload.get("next_poll_after_seconds"),
    }


def _stable_source_fields(payload: dict[str, object]) -> dict[str, object]:
    """Return stable source-attachment response fields."""
    return {
        "type": payload["type"],
        "source_type": payload["source_type"],
        "weight": payload["weight"],
        "source_uri": payload["source_uri"],
        "metadata": payload["metadata"],
    }


def _idempotency_request(idempotency_key: str) -> IdempotencyAcquireRequest:
    """Build a source-intake idempotency request fixture."""
    return IdempotencyAcquireRequest(
        principal_id="principal",
        operation="upload.create",
        idempotency_key=idempotency_key,
        body_hash="body-a",
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
    )


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _TextUploadRequest:
    """Describe a deterministic text-upload multipart request."""

    key: str
    payload: bytes
    authorization: str | None = None
    metadata: str | None = None


async def _post_text_upload(
    client: httpx.AsyncClient,
    request: _TextUploadRequest,
) -> httpx.Response:
    """Post a text upload with a deterministic multipart shape."""
    headers = {"Idempotency-Key": request.key}
    if request.authorization is not None:
        headers["Authorization"] = request.authorization
    files: dict[
        str,
        tuple[str, bytes, str] | tuple[None, str] | tuple[None, str, str],
    ] = {
        "file": ("source.txt", request.payload, "text/plain"),
        "content_type": (None, "text/plain"),
        "declared_size": (None, str(len(request.payload))),
        "declared_sha256": (None, hashlib.sha256(request.payload).hexdigest()),
    }
    if request.metadata is not None:
        files["metadata"] = (None, request.metadata, "application/json")
    return await client.post("/v1/uploads", headers=headers, files=files)
