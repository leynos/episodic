"""QA-status persistence rows for generated draft scripts (INV-2).

The service writes the caller's QA status; it must not hard-code ``skipped``.
"""

import typing as typ

import pytest

from episodic.canonical.generation_persistence import (
    DraftScriptPersistenceRequest,
    EpisodeMaterialisationRequest,
    materialise_episode_from_ingestion,
    persist_draft_script,
)
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.test_generation_persistence import (
    SequentialUuids,
    _clock,
    _draft_result,
    _persist_ready_job,
    _run,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_DRAFT_XML = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
    "<teiHeader><fileDesc><title>Bridgewater Futures</title></fileDesc></teiHeader>"
    '<text><body><u who="Host">Welcome.</u></body></text></TEI>'
)


@pytest.mark.asyncio
@pytest.mark.parametrize("qa_status", [QaStatus.SKIPPED, QaStatus.PASSED])
async def test_persist_draft_script_writes_the_supplied_qa_status(
    session_factory: object,
    qa_status: QaStatus,
) -> None:
    """The persisted QA status is the caller's, not a hard-coded value."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    _, job = await _persist_ready_job(factory)
    draft_xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Bridgewater Futures</title></fileDesc></teiHeader>"
        '<text><body><u who="Host">Welcome.</u></body></text></TEI>'
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        episode = await materialise_episode_from_ingestion(
            uow,
            EpisodeMaterialisationRequest(
                ingestion_job_id=job.id,
                title="Bridgewater Futures",
                clock=_clock,
                uuid_factory=SequentialUuids(),
            ),
        )
        run = _run(episode.id, job.id)
        await uow.generation_runs.create_run(run)
        updated = await persist_draft_script(
            uow,
            DraftScriptPersistenceRequest(
                episode_id=episode.id,
                generation_run_id=run.id,
                result=_draft_result(draft_xml),
                expected_revision=episode.tei_revision,
                qa_status=qa_status,
                clock=_clock,
            ),
        )
        await uow.commit()

    assert updated.qa_status is qa_status, (
        f"expected persisted qa_status {qa_status!r}, got {updated.qa_status!r}"
    )
