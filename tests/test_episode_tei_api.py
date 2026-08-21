"""Integration tests for episode TEI retrieval."""

import dataclasses as dc
import datetime as dt
import hashlib
import typing as typ
import uuid

import falcon
import httpx
import pytest

from episodic.api import create_app
from episodic.api.resources.episode_tei import negotiate_tei_media_type
from episodic.canonical.domain import EpisodeTeiUpdate
from episodic.canonical.generation_quality import QaStatus
from episodic.observability import RecordingTracer
from tests.fixtures.api import build_api_dependencies
from tests.fixtures.generation_run_api import (
    HeaderPrincipalAuthorization,
    RecordingLauncher,
)

if typ.TYPE_CHECKING:
    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.dependencies import ApiDependencies


@pytest.mark.parametrize(
    ("accept", "expected"),
    [
        ("application/tei+xml;q=0, application/json;q=0.5", "application/json"),
        (
            "application/json;q=0.1, application/tei+xml;q=0.9",
            "application/tei+xml",
        ),
        ("application/tei+xml;q=0.1, */*;q=0.5", "application/json"),
    ],
)
def test_negotiate_tei_media_type_honours_accept_quality(
    accept: str,
    expected: str,
) -> None:
    """TEI negotiation selects the highest-quality supported representation."""
    actual = negotiate_tei_media_type(accept)
    assert actual == expected, (
        f"Accept {accept!r}: expected {expected!r}, got {actual!r}"
    )


def test_negotiate_tei_media_type_rejects_zero_quality_ranges() -> None:
    """TEI negotiation rejects headers that exclude every supported type."""
    with pytest.raises(falcon.HTTPNotAcceptable):
        negotiate_tei_media_type("application/json;q=0, application/tei+xml;q=0")


@pytest.mark.asyncio
async def test_episode_tei_json_and_xml_retrieval(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Return metadata by default and a TEI attachment when requested."""
    launcher = RecordingLauncher()
    tracer = RecordingTracer()
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        launcher=launcher,
        tracer=tracer,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=typ.cast("_ASGIApp", create_app(dependencies))
        ),
        base_url="http://testserver",
    ) as client:
        episode_id = await _create_generation_run(client)
        before_draft = await client.get(f"/v1/episodes/{episode_id}/tei")
        tei_xml = "<TEI><text><body><p>Generated script.</p></body></text></TEI>"
        await _persist_generated_tei(dependencies, episode_id, launcher.run_ids[0])
        json_response = await client.get(f"/v1/episodes/{episode_id}/tei")
        xml_response = await client.get(
            f"/v1/episodes/{episode_id}/tei",
            headers={"Accept": "application/tei+xml"},
        )
        unacceptable = await client.get(
            f"/v1/episodes/{episode_id}/tei",
            headers={"Accept": "text/plain"},
        )

    assert before_draft.status_code == 404, (
        f"expected missing draft status 404, got {before_draft.status_code}"
    )
    assert unacceptable.status_code == 406, (
        f"expected unacceptable media status 406, got {unacceptable.status_code}"
    )
    _assert_tei_json_response(
        json_response,
        episode_id=episode_id,
        generation_run_id=launcher.run_ids[0],
        tei_xml=tei_xml,
    )
    _assert_tei_xml_response(
        xml_response,
        episode_id=episode_id,
        tei_xml=tei_xml,
    )
    assert json_response.headers["ETag"] != xml_response.headers["ETag"], (
        "expected representation-specific ETags for JSON metadata and TEI XML"
    )
    _assert_tei_read_spans(tracer)


@pytest.mark.asyncio
async def test_episode_tei_trace_records_invalid_identifier(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Record invalid TEI reads without including the raw route value."""
    tracer = RecordingTracer()
    dependencies = dc.replace(build_api_dependencies(session_factory), tracer=tracer)
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/v1/episodes/not-a-uuid/tei")

    assert response.status_code == 400, response.text
    assert tracer.spans[0].name == "episode_tei.read", tracer.spans
    assert tracer.spans[0].attributes == {
        "operation": "episode_tei.read",
        "outcome": "rejected",
        "failure_category": "invalid_input",
    }, tracer.spans


@pytest.mark.asyncio
async def test_episode_tei_retrieval_enforces_principal_ownership(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Hide generated TEI from other and unauthenticated principals."""
    launcher = RecordingLauncher()
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        authorization=HeaderPrincipalAuthorization(),
        launcher=launcher,
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    principal_a = {"Authorization": "Bearer principal-a"}
    principal_b = {"Authorization": "Bearer principal-b"}
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        episode_id = await _create_generation_run(client, headers=principal_a)
        await _persist_generated_tei(dependencies, episode_id, launcher.run_ids[0])
        endpoint = f"/v1/episodes/{episode_id}/tei"
        allowed = await client.get(endpoint, headers=principal_a)
        unauthenticated = await client.get(endpoint)
        cross_principal = await client.get(endpoint, headers=principal_b)

    assert allowed.status_code == 200, allowed.text
    assert unauthenticated.status_code == 401, unauthenticated.text
    assert cross_principal.status_code == 404, cross_principal.text


@pytest.mark.asyncio
@pytest.mark.parametrize("accept", [None, "application/tei+xml"])
@pytest.mark.parametrize(
    ("validator_kind", "expected_status"),
    [
        ("matching", 304),
        ("nonmatching", 200),
        ("wildcard", 304),
        ("absent", 200),
    ],
)
async def test_episode_tei_honours_conditional_get_validators(
    session_factory: async_sessionmaker[AsyncSession],
    accept: str | None,
    validator_kind: str,
    expected_status: int,
) -> None:
    """Return a body only when the selected TEI representation has changed."""
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
        episode_id = await _create_generation_run(client)
        await _persist_generated_tei(dependencies, episode_id, launcher.run_ids[0])
        headers = {} if accept is None else {"Accept": accept}
        initial_response = await client.get(
            f"/v1/episodes/{episode_id}/tei", headers=headers
        )
        validator = {
            "matching": initial_response.headers["ETag"],
            "nonmatching": '"not-a-match"',
            "wildcard": "*",
            "absent": None,
        }[validator_kind]
        conditional_response = await client.get(
            f"/v1/episodes/{episode_id}/tei",
            headers=headers
            if validator is None
            else headers | {"If-None-Match": validator},
        )

    assert initial_response.status_code == 200, initial_response.text
    assert conditional_response.status_code == expected_status, (
        conditional_response.text
    )
    assert conditional_response.headers["ETag"] == initial_response.headers["ETag"], (
        "expected conditional response to retain the selected representation ETag"
    )
    if expected_status == 304:
        assert conditional_response.content == b"", conditional_response.content


async def _persist_generated_tei(
    dependencies: ApiDependencies,
    episode_id: uuid.UUID,
    generation_run_id: uuid.UUID,
) -> None:
    """Persist generated TEI needed by endpoint retrieval tests."""
    async with dependencies.uow_factory() as uow:
        await uow.episodes.update(
            episode_id,
            update=EpisodeTeiUpdate(
                tei_xml="<TEI><text><body><p>Generated script.</p></body></text></TEI>",
                qa_status=QaStatus.SKIPPED,
                last_generation_run_id=generation_run_id,
                expected_revision=1,
                updated_at=dt.datetime(2026, 7, 22, 12, 0, tzinfo=dt.UTC),
            ),
        )
        await uow.commit()


def _assert_tei_json_response(
    response: httpx.Response,
    *,
    episode_id: uuid.UUID,
    generation_run_id: uuid.UUID,
    tei_xml: str,
) -> None:
    """Assert the TEI metadata response preserves generation provenance."""
    assert response.status_code == 200, response.text
    expected_payload = {
        "episode_id": str(episode_id),
        "tei_header_id": response.json()["tei_header_id"],
        "tei_xml": tei_xml,
        "content_hash": _tei_hash(tei_xml),
        "version": 2,
        "last_generation_run_id": str(generation_run_id),
        "quality_mode": "draft_without_qa",
        "qa_status": "skipped",
        "updated_at": "2026-07-22T12:00:00+00:00",
    }
    assert response.json() == expected_payload, (
        f"expected TEI metadata {expected_payload!r}, got {response.json()!r}"
    )
    assert response.headers["ETag"] == _response_etag(response), (
        f"expected JSON ETag for serialized response, got {response.headers['ETag']!r}"
    )


def _assert_tei_xml_response(
    response: httpx.Response,
    *,
    episode_id: uuid.UUID,
    tei_xml: str,
) -> None:
    """Assert the TEI attachment response preserves its download contract."""
    assert response.status_code == 200, (
        f"expected TEI response status 200, got {response.status_code}"
    )
    assert response.text == tei_xml, (
        f"expected TEI body {tei_xml!r}, got {response.text!r}"
    )
    assert response.headers["Content-Type"].startswith("application/tei+xml"), (
        f"expected TEI content type, got {response.headers['Content-Type']!r}"
    )
    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="episode-{episode_id}.xml"'
    ), (
        "expected episode attachment Content-Disposition, got "
        f"{response.headers['Content-Disposition']!r}"
    )
    assert response.headers["ETag"] == _response_etag(response), (
        f"expected ETag for generated TEI, got {response.headers['ETag']!r}"
    )


def _assert_tei_read_spans(tracer: RecordingTracer) -> None:
    """Assert the TEI retrieval trace sequence."""
    expected_tei_spans = [
        {
            "operation": "episode_tei.read",
            "outcome": "not_found",
            "failure_category": "episode.not_found",
        },
        {
            "operation": "episode_tei.read",
            "representation": "application/json",
            "outcome": "success",
        },
        {
            "operation": "episode_tei.read",
            "representation": "application/tei+xml",
            "outcome": "success",
        },
        {
            "operation": "episode_tei.read",
            "outcome": "rejected",
            "failure_category": "not_acceptable",
        },
    ]
    assert [
        span.attributes for span in tracer.spans if span.name == "episode_tei.read"
    ] == expected_tei_spans, tracer.spans


def _response_etag(response: httpx.Response) -> str:
    """Return the quoted SHA-256 ETag for the response representation bytes."""
    return f'"{hashlib.sha256(response.content).hexdigest()}"'


async def _create_generation_run(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str] | None = None,
) -> uuid.UUID:
    """Create a ready generation run owned by the supplied test principal."""
    request_headers = {} if headers is None else headers
    profile = await client.post(
        "/v1/series-profiles",
        headers={**request_headers, "Idempotency-Key": "tei-profile-key"},
        json={
            "slug": "tei-retrieval-profile",
            "title": "TEI retrieval profile",
            "description": "TEI endpoint fixture.",
            "configuration": {},
            "actor": "editor@example.com",
        },
    )
    job = await client.post(
        "/v1/ingestion-jobs",
        headers={**request_headers, "Idempotency-Key": "tei-job-key"},
        json={"series_profile_id": profile.json()["id"]},
    )
    source = await client.post(
        f"/v1/ingestion-jobs/{job.json()['id']}/sources",
        headers={**request_headers, "Idempotency-Key": "tei-source-key"},
        json={
            "type": "source_uri",
            "source_uri": "https://example.test/source.txt",
            "source_type": "research_note",
            "weight": 1.0,
            "metadata": {"content": "Source text."},
        },
    )
    assert profile.status_code == 201, profile.text
    assert job.status_code == 201, job.text
    assert source.status_code == 201, source.text
    run = await client.post(
        f"/v1/ingestion-jobs/{job.json()['id']}/generation-runs",
        headers={**request_headers, "Idempotency-Key": "tei-generation-key"},
        json={
            "quality_mode": "draft_without_qa",
            "skip_qa_rationale": "TEI retrieval test.",
            "actor": "editor@example.com",
        },
    )
    assert run.status_code == 202, run.text
    return uuid.UUID(run.json()["episode_id"])


def _tei_hash(tei_xml: str) -> str:
    return f"sha256:{hashlib.sha256(tei_xml.encode()).hexdigest()}"
