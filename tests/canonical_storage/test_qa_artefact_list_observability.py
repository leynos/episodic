"""Operation-observation coverage for QA artefact listing.

Each test pins the span ``list_evaluations`` opens, the bounded outcome it
records, and the latency observation it emits. Only an outcome and a stable
failure category may reach a span or a metric, so no finding text or
identifier is captured.
"""

import typing as typ

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from episodic.canonical.pagination import Pagination
from episodic.canonical.qa_artefact_errors import UnsupportedQaArtefactSchemaError
from episodic.canonical.qa_artefact_ports import QaEvaluationListRequest
from episodic.canonical.storage import (
    QaEvaluationRecord,
    SqlAlchemyQaArtefactStore,
    qa_artefacts,
)
from episodic.canonical.storage.qa_artefact_mappers import evaluation_to_record
from episodic.observability import RecordingTracer
from tests.canonical_storage._qa_artefact_observability_support import (
    NOW,
    expected_latency,
    expected_span,
    instrumented_runtime,
)
from tests.canonical_storage._qa_artefact_support import (
    create_episode,
    make_evaluation,
)
from tests.canonical_storage._workflow_checkpoint_support import RecordingMetrics

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_list_records_success_and_latency(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A served page is one successful listing span with no extra labels."""
    episode_id = await create_episode(session_factory)
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    async with session_factory() as session:
        session.add(
            evaluation_to_record(
                make_evaluation(episode_id, idempotency_key="list"),
                created_at=NOW,
            )
        )
        await session.commit()

    async with session_factory() as session:
        store = SqlAlchemyQaArtefactStore(
            session,
            runtime=instrumented_runtime(tracer, metrics),
        )
        await store.list_evaluations(
            QaEvaluationListRequest(
                episode_id=episode_id,
                pagination=Pagination(limit=10, offset=0),
            )
        )

    assert tracer.spans == [expected_span("qa_artefact.list", "success")], tracer.spans
    assert metrics.latencies == [
        expected_latency("qa_artefact.list", {"outcome": "success"})
    ], metrics.latencies


@pytest.mark.asyncio
async def test_list_marks_an_unreadable_schema_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A listed page containing a newer row reports ``unsupported_schema``.

    ``get_evaluation`` already names this category, so the listing must not
    fall back to the unclassified failure its ``SQLAlchemyError`` handler
    cannot catch.
    """
    episode_id = await create_episode(session_factory)
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    evaluation = make_evaluation(episode_id, idempotency_key="newer")
    async with session_factory() as session:
        session.add(evaluation_to_record(evaluation, created_at=NOW))
        await session.execute(
            sa
            .update(QaEvaluationRecord)
            .where(QaEvaluationRecord.id == evaluation.summary_record.id)
            .values(artefact_schema_version=99)
        )
        await session.commit()

    async with session_factory() as session:
        store = SqlAlchemyQaArtefactStore(
            session,
            runtime=instrumented_runtime(tracer, metrics),
        )
        with pytest.raises(UnsupportedQaArtefactSchemaError):
            await store.list_evaluations(
                QaEvaluationListRequest(
                    episode_id=episode_id,
                    pagination=Pagination(limit=10, offset=0),
                )
            )

    assert tracer.spans == [
        expected_span(
            "qa_artefact.list",
            "failed",
            failure_category="unsupported_schema",
        )
    ], tracer.spans
    assert metrics.latencies == [
        expected_latency(
            "qa_artefact.list",
            {"outcome": "failed", "failure_category": "unsupported_schema"},
        )
    ], metrics.latencies


@pytest.mark.asyncio
async def test_list_marks_a_database_failure(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A query failure is reported as ``database_error`` and re-raised."""
    episode_id = await create_episode(session_factory)
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    async with session_factory() as session:
        session.add(
            evaluation_to_record(
                make_evaluation(episode_id, idempotency_key="list-failure"),
                created_at=NOW,
            )
        )
        await session.commit()

    def reject(_record: object) -> object:
        """Fail while reading a row back from the database."""
        raise SQLAlchemyError

    monkeypatch.setattr(qa_artefacts, "summary_from_record", reject)

    async with session_factory() as session:
        store = SqlAlchemyQaArtefactStore(
            session,
            runtime=instrumented_runtime(tracer, metrics),
        )
        with pytest.raises(SQLAlchemyError):
            await store.list_evaluations(
                QaEvaluationListRequest(
                    episode_id=episode_id,
                    pagination=Pagination(limit=10, offset=0),
                )
            )
        await session.rollback()

    assert tracer.spans == [
        expected_span("qa_artefact.list", "failed", failure_category="database_error")
    ], tracer.spans
