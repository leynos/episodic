"""Integration tests for episode TEI retrieval."""

import dataclasses as dc
import datetime as dt
import hashlib
import typing as typ
import uuid

import httpx
import pytest

from episodic.api import create_app
from episodic.canonical.domain import EpisodeTeiUpdate
from episodic.canonical.generation_quality import QaStatus
from tests.fixtures.api import build_api_dependencies
from tests.test_generation_run_api import RecordingLauncher

if typ.TYPE_CHECKING:
    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_episode_tei_json_and_xml_retrieval(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Return metadata by default and a TEI attachment when requested."""
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
        before_draft = await client.get(f"/v1/episodes/{episode_id}/tei")
        tei_xml = "<TEI><text><body><p>Generated script.</p></body></text></TEI>"
        async with dependencies.uow_factory() as uow:
            await uow.episodes.update(
                episode_id,
                update=EpisodeTeiUpdate(
                    tei_xml=tei_xml,
                    qa_status=QaStatus.SKIPPED,
                    last_generation_run_id=launcher.run_ids[0],
                    expected_revision=1,
                    updated_at=dt.datetime(2026, 7, 22, 12, 0, tzinfo=dt.UTC),
                ),
            )
            await uow.commit()
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
    assert response.headers["ETag"] == f'"{_tei_hash(tei_xml)}"', (
        f"expected ETag for generated TEI, got {response.headers['ETag']!r}"
    )


async def _create_generation_run(client: httpx.AsyncClient) -> uuid.UUID:
    profile = await client.post(
        "/v1/series-profiles",
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
        headers={"Idempotency-Key": "tei-job-key"},
        json={"series_profile_id": profile.json()["id"]},
    )
    source = await client.post(
        f"/v1/ingestion-jobs/{job.json()['id']}/sources",
        headers={"Idempotency-Key": "tei-source-key"},
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
        f"/v1/episodes/{job.json()['id']}/generation-runs",
        headers={"Idempotency-Key": "tei-generation-key"},
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
