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

    assert before_draft.status_code == 404
    assert unacceptable.status_code == 406
    assert json_response.status_code == 200, json_response.text
    assert json_response.json() == {
        "episode_id": str(episode_id),
        "tei_header_id": json_response.json()["tei_header_id"],
        "tei_xml": tei_xml,
        "content_hash": _tei_hash(tei_xml),
        "version": 2,
        "last_generation_run_id": str(launcher.run_ids[0]),
        "quality_mode": "draft_without_qa",
        "qa_status": "skipped",
        "updated_at": "2026-07-22T12:00:00+00:00",
    }
    assert xml_response.status_code == 200
    assert xml_response.text == tei_xml
    assert xml_response.headers["Content-Type"].startswith("application/tei+xml")
    assert xml_response.headers["Content-Disposition"] == (
        f'attachment; filename="episode-{episode_id}.xml"'
    )
    assert xml_response.headers["ETag"] == f'"{_tei_hash(tei_xml)}"'


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
