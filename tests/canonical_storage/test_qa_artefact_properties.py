"""Generated persistence invariants for QA artefacts.

Covers ``INV-FINDING-ORDER``, ``INV-FILTER-SOUND``,
``INV-PAGINATION-PARTITION``, and ``INV-JSONB-ROUNDTRIP`` against the real
SQLAlchemy adapter. Each example builds its own episodes, because the migrated
py-pglite schema is reset per test function rather than per example.
"""

import datetime as dt
import itertools
import typing as typ
import uuid

import hypothesis.strategies as st
import pytest
import sqlalchemy as sa
from hypothesis import HealthCheck, event, given, settings

from episodic.canonical.pagination import Pagination
from episodic.canonical.qa_artefact_ports import QaEvaluationListRequest
from episodic.canonical.qa_artefacts import (
    QA_ARTEFACT_SCHEMA_VERSION,
    QA_COMPLIANCE_POLICY_VERSION,
    QaComplianceStatus,
    QaEvaluation,
    QaEvaluationSummary,
    QaEvaluator,
    QaFinding,
    QaFindingSeverity,
)
from episodic.canonical.storage import QaFindingRecord, SqlAlchemyUnitOfWork
from tests.canonical_storage._qa_artefact_support import (
    EvaluationOptions,
    create_episode,
    make_evaluation,
)
from tests.fixtures.qa_artefact_builders import EVALUATED_AT

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]
else:
    type SessionFactory = object

type CorpusSpec = tuple[QaEvaluator, QaComplianceStatus, int]

_EVALUATORS = tuple(QaEvaluator)
_STATUSES = tuple(QaComplianceStatus)
_SEVERITIES = st.lists(st.sampled_from(tuple(QaFindingSeverity)), max_size=12)
_CORPUS = st.lists(
    st.tuples(
        st.sampled_from(_EVALUATORS),
        st.sampled_from(_STATUSES),
        st.integers(min_value=0, max_value=3),
    ),
    max_size=12,
)
_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    max_size=64,
)
_KEY = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    min_size=1,
    max_size=8,
)
_JSON_SCALARS = st.one_of(st.none(), st.booleans(), st.integers(), _TEXT)
# Root mapping plus one nested container is the documented depth-2 domain.
_JSON_CONTAINERS = st.one_of(
    st.lists(_JSON_SCALARS, max_size=3),
    st.dictionaries(_KEY, _JSON_SCALARS, max_size=3),
)
_JSON_OBJECTS = st.dictionaries(_KEY, _JSON_CONTAINERS, max_size=3)
_SETTINGS = settings(
    max_examples=6,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.filter_too_much,
    ],
)


async def _store_corpus(
    session_factory: SessionFactory,
    episode_id: uuid.UUID,
    specs: list[CorpusSpec],
) -> list[QaEvaluation]:
    """Record one evaluation per spec, returning them in recording order."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = [
            await uow.qa_artefacts.record_evaluation(
                make_evaluation(
                    episode_id,
                    idempotency_key=f"key-{index}",
                    options=EvaluationOptions(
                        evaluator=evaluator,
                        compliance_status=status,
                        evaluated_at=EVALUATED_AT + dt.timedelta(seconds=offset),
                        severities=(QaFindingSeverity.LOW,),
                    ),
                )
            )
            for index, (evaluator, status, offset) in enumerate(specs)
        ]
        await uow.commit()
    return stored


def _matching_evaluation_ids(
    stored: list[QaEvaluation],
    *,
    evaluator: QaEvaluator | None,
    status: QaComplianceStatus | None,
) -> set[uuid.UUID]:
    """Return the stored ids that match every supplied predicate."""
    return {
        item.summary_record.id
        for item in stored
        if (evaluator is None or item.summary_record.evaluator is evaluator)
        and (status is None or item.summary_record.compliance_status is status)
    }


def _record_filter_combination(
    evaluator: QaEvaluator | None,
    status: QaComplianceStatus | None,
) -> None:
    """Emit the event naming the predicates the example applied."""
    if evaluator is not None and status is not None:
        event("both filters applied")
    elif evaluator is not None or status is not None:
        event("one filter applied")


@given(severities=_SEVERITIES)
@_SETTINGS
@pytest.mark.asyncio
async def test_findings_read_back_in_emission_order(
    session_factory: SessionFactory,
    severities: list[QaFindingSeverity],
) -> None:
    """Findings return with ordinals exactly ``0..n-1`` in emission order."""
    factory = session_factory
    episode_id = await create_episode(factory)
    evaluation = make_evaluation(
        episode_id,
        idempotency_key="order",
        options=EvaluationOptions(severities=tuple(severities)),
    )
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.qa_artefacts.record_evaluation(evaluation)
        await uow.commit()

    taxonomy_order = list(QaFindingSeverity)
    if any(
        taxonomy_order.index(left) > taxonomy_order.index(right)
        for left, right in itertools.pairwise(severities)
    ):
        event("severities out of taxonomy order")

    # Insertion order usually survives a sequential scan, so relocate a middle
    # row in the heap before reading to make an unordered query observable.
    if evaluation.findings:
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
    assert [item.ordinal for item in fetched.findings] == list(
        range(len(severities))
    ), "persisted ordinals should be exactly 0..n-1"
    assert [item.code for item in fetched.findings] == [
        f"code-{index}" for index in range(len(severities))
    ], "findings should return in the order the evaluator emitted them"


@given(
    specs=_CORPUS,
    evaluator=st.none() | st.sampled_from(_EVALUATORS),
    status=st.none() | st.sampled_from(_STATUSES),
)
@_SETTINGS
@pytest.mark.asyncio
async def test_listing_applies_every_filter_and_counts_the_same_set(
    session_factory: SessionFactory,
    specs: list[CorpusSpec],
    evaluator: QaEvaluator | None,
    status: QaComplianceStatus | None,
) -> None:
    """The page and its total both describe exactly the filtered population."""
    factory = session_factory
    episode_id = await create_episode(factory)
    stored = await _store_corpus(factory, episode_id, specs)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        summaries, total = await uow.qa_artefacts.list_evaluations(
            QaEvaluationListRequest(
                episode_id=episode_id,
                pagination=Pagination(limit=100, offset=0),
                evaluator=evaluator,
                compliance_status=status,
            )
        )

    expected = _matching_evaluation_ids(
        stored,
        evaluator=evaluator,
        status=status,
    )
    _record_filter_combination(evaluator, status)
    assert {summary.id for summary in summaries} == expected, (
        "the page should contain exactly the evaluations matching every predicate"
    )
    assert total == len(expected), (
        "the total should count the filtered set, not the page length"
    )


@given(
    specs=_CORPUS,
    page_size=st.integers(min_value=1, max_value=5),
)
@_SETTINGS
@pytest.mark.asyncio
async def test_pages_partition_the_ordered_listing(
    session_factory: SessionFactory,
    specs: list[CorpusSpec],
    page_size: int,
) -> None:
    """Concatenating consecutive pages reproduces the listing exactly once."""
    factory = session_factory
    episode_id = await create_episode(factory)
    # Two rows share an instant, so the ``id`` tiebreaker is always exercised.
    tied: list[CorpusSpec] = [
        (QaEvaluator.PEDANTE, QaComplianceStatus.COMPLIANT, 0),
        (QaEvaluator.BROMIDE, QaComplianceStatus.ERRORED, 0),
    ]
    await _store_corpus(factory, episode_id, [*tied, *specs])

    async with SqlAlchemyUnitOfWork(factory) as uow:
        full, total = await uow.qa_artefacts.list_evaluations(
            QaEvaluationListRequest(
                episode_id=episode_id,
                pagination=Pagination(limit=100, offset=0),
            )
        )
        collected: list[uuid.UUID] = []
        offset = 0
        while offset < total:
            page, _ = await uow.qa_artefacts.list_evaluations(
                QaEvaluationListRequest(
                    episode_id=episode_id,
                    pagination=Pagination(limit=page_size, offset=offset),
                )
            )
            assert len(page) <= page_size, "a page should honour its limit"
            collected.extend(summary.id for summary in page)
            offset += page_size

    expected = [summary.id for summary in full]
    assert collected == expected, (
        "concatenated pages should reproduce the full ordered listing"
    )
    assert len(collected) == len(set(collected)) == total, (
        "the pages should cover every row exactly once"
    )


@given(citations=st.lists(_TEXT, max_size=5), details=_JSON_OBJECTS)
@_SETTINGS
@pytest.mark.asyncio
async def test_jsonb_round_trip_preserves_value_and_type(
    session_factory: SessionFactory,
    citations: list[str],
    details: dict[str, object],
) -> None:
    """``citations`` returns as a tuple and both payloads keep their values."""
    factory = session_factory
    episode_id = await create_episode(factory)
    evaluation_id = uuid.uuid7()
    evaluation = QaEvaluation(
        summary_record=QaEvaluationSummary(
            id=evaluation_id,
            episode_id=episode_id,
            evaluator=QaEvaluator.PEDANTE,
            evaluator_version="pedante-1.0.0",
            artefact_schema_version=QA_ARTEFACT_SCHEMA_VERSION,
            compliance_policy_version=QA_COMPLIANCE_POLICY_VERSION,
            compliance_status=QaComplianceStatus.COMPLIANT,
            evaluated_at=EVALUATED_AT,
            idempotency_key="jsonb",
            finding_count=1,
            evaluator_metadata=details,
        ),
        findings=(
            QaFinding(
                id=uuid.uuid7(),
                evaluation_id=evaluation_id,
                ordinal=0,
                severity=QaFindingSeverity.LOW,
                code="code-0",
                summary="Finding 0.",
                citations=tuple(citations),
                details=details,
            ),
        ),
    )
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.qa_artefacts.record_evaluation(evaluation)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched = await uow.qa_artefacts.get_evaluation(evaluation_id)

    assert fetched is not None, "expected the recorded evaluation to be readable"
    stored_finding = fetched.findings[0]
    assert isinstance(stored_finding.citations, tuple), (
        "citations should be re-hydrated as a tuple, not the JSONB list"
    )
    assert stored_finding.citations == tuple(citations), (
        "citations should keep their values and order"
    )
    assert stored_finding.details == details, "finding details should round-trip"
    assert fetched.summary_record.evaluator_metadata == details, (
        "evaluator metadata should round-trip"
    )
