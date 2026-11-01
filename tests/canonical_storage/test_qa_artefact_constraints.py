"""Database constraint tests for the QA artefact tables.

``INV-CONSTRAINT-ENFORCED``. The inserts go through SQLAlchemy Core rather than
the domain constructors, so a rejection can only come from the database. Each
rejected value is paired with a satisfying witness, which proves the statement
would otherwise succeed and the rejection names the constraint under test.
``make check-migrations`` compares tables and columns, not ``CHECK``
constraints, so this needs its own evidence.
"""

import decimal
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from episodic.canonical.qa_artefacts import (
    QaComplianceStatus,
    QaEvaluator,
    QaFindingSeverity,
)
from episodic.canonical.storage import QaEvaluationRecord, QaFindingRecord
from tests.canonical_storage._qa_artefact_support import count_rows, create_episode
from tests.fixtures.qa_artefact_builders import EVALUATED_AT

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _evaluation_values(
    episode_id: uuid.UUID,
    *,
    idempotency_key: str,
    **overrides: object,
) -> dict[str, object]:
    """Return a valid evaluation row whose named columns callers may override."""
    values: dict[str, object] = {
        "id": uuid.uuid7(),
        "episode_id": episode_id,
        "generation_run_id": None,
        "evaluator": QaEvaluator.PEDANTE,
        "evaluator_version": "pedante-1.0.0",
        "artefact_schema_version": 1,
        "compliance_policy_version": 1,
        "compliance_status": QaComplianceStatus.COMPLIANT,
        "summary": "",
        "rubric_score": None,
        "runtime_estimate_seconds": None,
        "finding_count": 0,
        "evaluator_metadata": {},
        "idempotency_key": idempotency_key,
        "evaluated_at": EVALUATED_AT,
    }
    values.update(overrides)
    return values


def _finding_values(
    evaluation_id: object,
    *,
    ordinal: int,
) -> dict[str, object]:
    """Return a valid finding row for ``evaluation_id``."""
    return {
        "id": uuid.uuid7(),
        "evaluation_id": evaluation_id,
        "ordinal": ordinal,
        "severity": QaFindingSeverity.LOW,
        "code": "code-0",
        "summary": "A finding.",
        "remediation": "",
        "subject_id": "",
        "subject_text": "",
        "is_blocking": False,
        "citations": [],
        "details": {},
    }


async def _persist(
    session_factory: async_sessionmaker[AsyncSession],
    model: type[QaEvaluationRecord] | type[QaFindingRecord],
    values: dict[str, object],
    *,
    should_accept: bool,
) -> None:
    """Insert ``values`` and assert the database accepts or rejects them."""
    async with session_factory() as session:
        insert = sa.insert(model).values(**values)
        if should_accept:
            await session.execute(insert)
            await session.commit()
            return
        with pytest.raises(IntegrityError):
            await session.execute(insert)
        await session.rollback()


@pytest.mark.parametrize(
    ("rejected", "witness"),
    [
        (
            {"rubric_score": decimal.Decimal("1.5")},
            {"rubric_score": decimal.Decimal(1)},
        ),
        (
            {"rubric_score": decimal.Decimal("-0.1")},
            {"rubric_score": decimal.Decimal(0)},
        ),
        ({"runtime_estimate_seconds": -1}, {"runtime_estimate_seconds": 0}),
        ({"finding_count": -1}, {"finding_count": 0}),
    ],
    ids=[
        "rubric-above-one",
        "rubric-below-zero",
        "negative-runtime-estimate",
        "negative-finding-count",
    ],
)
@pytest.mark.asyncio
async def test_evaluation_checks_reject_out_of_range_values(
    session_factory: async_sessionmaker[AsyncSession],
    rejected: dict[str, object],
    witness: dict[str, object],
) -> None:
    """Each evaluation CHECK rejects its violating value and accepts a witness."""
    episode_id = await create_episode(session_factory)

    await _persist(
        session_factory,
        QaEvaluationRecord,
        _evaluation_values(episode_id, idempotency_key="rejected", **rejected),
        should_accept=False,
    )
    await _persist(
        session_factory,
        QaEvaluationRecord,
        _evaluation_values(episode_id, idempotency_key="witness", **witness),
        should_accept=True,
    )
    async with session_factory() as session:
        assert await count_rows(session, QaEvaluationRecord) == 1, (
            "only the satisfying witness should be stored"
        )


@pytest.mark.asyncio
async def test_finding_check_rejects_negative_ordinal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The finding ordinal CHECK rejects a negative position."""
    episode_id = await create_episode(session_factory)
    evaluation = _evaluation_values(
        episode_id,
        idempotency_key="ordinal",
        finding_count=1,
    )
    await _persist(
        session_factory,
        QaEvaluationRecord,
        evaluation,
        should_accept=True,
    )

    await _persist(
        session_factory,
        QaFindingRecord,
        _finding_values(evaluation["id"], ordinal=-1),
        should_accept=False,
    )
    await _persist(
        session_factory,
        QaFindingRecord,
        _finding_values(evaluation["id"], ordinal=0),
        should_accept=True,
    )
    async with session_factory() as session:
        assert await count_rows(session, QaFindingRecord) == 1, (
            "only the satisfying witness should be stored"
        )


@pytest.mark.asyncio
async def test_evaluation_foreign_key_rejects_unknown_episode(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An evaluation must reference a stored canonical episode."""
    missing_episode_id = uuid.uuid7()
    await _persist(
        session_factory,
        QaEvaluationRecord,
        _evaluation_values(missing_episode_id, idempotency_key="orphan"),
        should_accept=False,
    )

    episode_id = await create_episode(session_factory)
    await _persist(
        session_factory,
        QaEvaluationRecord,
        _evaluation_values(episode_id, idempotency_key="linked"),
        should_accept=True,
    )
    async with session_factory() as session:
        assert await count_rows(session, QaEvaluationRecord) == 1, (
            "only the episode-linked evaluation should be stored"
        )
