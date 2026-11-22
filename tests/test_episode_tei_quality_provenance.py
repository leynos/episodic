"""TEI envelope provenance for QA-gated runs (INV-13).

The envelope reports the producing run's quality mode, not a value derived
from the episode's QA status. This test writes a QA-gated run and a passed
episode TEI directly, because run creation refuses ``qa_gated`` until the
REST capability gate lands.
"""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import httpx
import pytest

from episodic.api import create_app
from episodic.canonical.domain import EpisodeTeiUpdate
from episodic.canonical.generation_quality import QaStatus, QualityMode
from tests.fixtures.api import build_api_dependencies
from tests.fixtures.generation_run_api import (
    HeaderPrincipalAuthorization,
    RecordingLauncher,
)
from tests.test_episode_tei_api import _create_generation_run

if typ.TYPE_CHECKING:
    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.dependencies import ApiDependencies

_TEI_XML = "<TEI><text><body><p>Generated script.</p></body></text></TEI>"
_PRINCIPAL_HEADERS = {"Authorization": "Bearer principal-a"}


async def _persist_gated_run(
    dependencies: ApiDependencies,
    episode_id: uuid.UUID,
    base_run_id: uuid.UUID,
) -> uuid.UUID:
    """Persist a QA-gated run cloned from the API-created run's provenance."""
    async with dependencies.uow_factory() as uow:
        base = await uow.generation_runs.get_run(base_run_id)
        assert base is not None, f"base run {base_run_id} disappeared"
        gated = dc.replace(
            base,
            id=uuid.uuid7(),
            status=base.status,
            quality_mode=QualityMode.QA_GATED,
            qa_status=QaStatus.PENDING,
            skip_qa_rationale=None,
        )
        await uow.generation_runs.create_run(gated)
        await uow.commit()
    return gated.id


async def _persist_passed_tei(
    dependencies: ApiDependencies,
    episode_id: uuid.UUID,
    gated_run_id: uuid.UUID,
) -> None:
    """Record a passed draft TEI produced by the gated run."""
    async with dependencies.uow_factory() as uow:
        episode = await uow.episodes.get(episode_id)
        assert episode is not None, f"episode {episode_id} disappeared"
        await uow.episodes.update(
            episode_id,
            update=EpisodeTeiUpdate(
                tei_xml=_TEI_XML,
                qa_status=QaStatus.PASSED,
                last_generation_run_id=gated_run_id,
                expected_revision=episode.tei_revision,
                updated_at=dt.datetime(2026, 7, 22, 12, 0, tzinfo=dt.UTC),
            ),
        )
        await uow.commit()


@pytest.mark.asyncio
async def test_envelope_reports_the_gated_producing_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A QA-gated producing run yields quality_mode qa_gated and passed QA."""
    launcher = RecordingLauncher()
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        authorization=HeaderPrincipalAuthorization(),
        launcher=launcher,
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        episode_id = await _create_generation_run(client, headers=_PRINCIPAL_HEADERS)
        gated_run_id = await _persist_gated_run(
            dependencies,
            episode_id,
            launcher.run_ids[0],
        )
        await _persist_passed_tei(dependencies, episode_id, gated_run_id)

        response = await client.get(
            f"/v1/episodes/{episode_id}/tei",
            headers=_PRINCIPAL_HEADERS,
        )

    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["quality_mode"] == QualityMode.QA_GATED.value, (
        f"envelope quality_mode={envelope['quality_mode']!r}"
    )
    assert envelope["qa_status"] == QaStatus.PASSED.value, (
        f"envelope qa_status={envelope['qa_status']!r}"
    )
    assert envelope["last_generation_run_id"] == str(gated_run_id), (
        "envelope must name the gated run as provenance"
    )
