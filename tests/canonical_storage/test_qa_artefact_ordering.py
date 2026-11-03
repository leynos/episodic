"""Deterministic ordering coverage for persisted QA findings.

The generated ordering property in ``test_qa_artefact_properties`` cannot force
a query plan that returns findings out of order: the
``(evaluation_id, ordinal)`` unique index is the natural access path, so even an
un-ordered query usually reads in ordinal order. These cases make the two
ordering layers individually observable, one through a repeatedly relocated row
and one through a relationship list supplied in reverse.
"""

import typing as typ

import pytest
import sqlalchemy as sa
from sqlalchemy import orm

from episodic.canonical.qa_artefacts import QaFindingSeverity
from episodic.canonical.storage import (
    QaEvaluationRecord,
    QaFindingRecord,
    SqlAlchemyUnitOfWork,
)
from episodic.canonical.storage.qa_artefact_mappers import evaluation_from_record
from tests.canonical_storage._qa_artefact_support import (
    EvaluationOptions,
    create_episode,
    make_evaluation,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]
else:
    type SessionFactory = object


@pytest.mark.asyncio
async def test_findings_order_ignores_physical_row_order(
    session_factory: SessionFactory,
) -> None:
    """A five-finding evaluation reads back in emission order after relocation."""
    factory = session_factory
    episode_id = await create_episode(factory)
    severities = (
        QaFindingSeverity.LOW,
        QaFindingSeverity.CRITICAL,
        QaFindingSeverity.MEDIUM,
        QaFindingSeverity.HIGH,
        QaFindingSeverity.LOW,
    )
    evaluation = make_evaluation(
        episode_id,
        idempotency_key="physical-order",
        options=EvaluationOptions(severities=severities),
    )
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.qa_artefacts.record_evaluation(evaluation)
        await uow.commit()

    relocated = evaluation.findings[len(evaluation.findings) // 2].id
    async with factory() as session:
        await session.execute(
            sa
            .update(QaFindingRecord)
            .where(QaFindingRecord.id == relocated)
            .values(summary="relocated")
        )
        await session.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.qa_artefacts.get_evaluation(evaluation.summary_record.id)

    assert fetched is not None, "expected the recorded evaluation to be readable"
    assert [item.ordinal for item in fetched.findings] == list(range(5)), (
        "the relocated row should still read back at its emitted ordinal"
    )
    assert [item.code for item in fetched.findings] == [
        f"code-{index}" for index in range(5)
    ], "physical row order should not decide the findings order"


@pytest.mark.asyncio
async def test_mapper_reorders_findings_supplied_out_of_order(
    session_factory: SessionFactory,
) -> None:
    """The row-to-domain mapping sorts a relationship list it receives unordered."""
    factory = session_factory
    episode_id = await create_episode(factory)
    severities = (
        QaFindingSeverity.HIGH,
        QaFindingSeverity.LOW,
        QaFindingSeverity.MEDIUM,
    )
    evaluation = make_evaluation(
        episode_id,
        idempotency_key="mapper-order",
        options=EvaluationOptions(severities=severities),
    )
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.qa_artefacts.record_evaluation(evaluation)
        await uow.commit()

    async with factory() as session:
        stored = await session.scalar(
            sa
            .select(QaEvaluationRecord)
            .where(QaEvaluationRecord.id == evaluation.summary_record.id)
            .options(orm.selectinload(QaEvaluationRecord.findings))
        )
        assert stored is not None, "expected the recorded evaluation row"
        stored.findings.reverse()
        mapped = evaluation_from_record(stored)

    assert [item.ordinal for item in mapped.findings] == [0, 1, 2], (
        "the mapping should sort findings by ordinal, not trust the row order"
    )
    assert [item.code for item in mapped.findings] == [
        "code-0",
        "code-1",
        "code-2",
    ], "the reordered rows should retain their emitted content"
