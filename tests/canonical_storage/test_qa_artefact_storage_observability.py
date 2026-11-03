"""Operation-observation coverage for the QA artefact storage adapter.

Each test pins the span a store method opens, the bounded outcome it records,
and the latency observation it emits. Only an evaluator, an outcome, and a
stable failure category may reach a span or a metric, so no finding text or
identifier is captured.
"""

import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from episodic.canonical.pagination import Pagination
from episodic.canonical.qa_artefact_errors import UnsupportedQaArtefactSchemaError
from episodic.canonical.qa_artefact_ports import QaEvaluationListRequest
from episodic.canonical.qa_artefacts import QaComplianceStatus, QaFindingSeverity
from episodic.canonical.storage import (
    QaArtefactStorageRuntime,
    QaEvaluationRecord,
    SqlAlchemyQaArtefactStore,
    qa_artefacts,
)
from episodic.canonical.storage.qa_artefact_mappers import evaluation_to_record
from episodic.observability import RecordedSpan, RecordingTracer
from tests.canonical_storage._qa_artefact_support import (
    EvaluationOptions,
    create_episode,
    make_evaluation,
)
from tests.canonical_storage._workflow_checkpoint_support import (
    RecordingMetrics,
    StepClock,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = dt.datetime(2026, 10, 31, 9, 0, tzinfo=dt.UTC)


def _instrumented_runtime(
    tracer: RecordingTracer,
    metrics: RecordingMetrics,
) -> QaArtefactStorageRuntime:
    """Return a storage runtime whose operations report to the test sinks."""
    return QaArtefactStorageRuntime(
        clock=lambda: NOW,
        uuid_factory=uuid.uuid7,
        metrics=metrics,
        tracer=tracer,
        monotonic_clock=StepClock(),
    )


def _span(
    name: str,
    outcome: str,
    *,
    failure_category: str | None = None,
) -> RecordedSpan:
    """Return the completed span an operation with ``outcome`` records."""
    attributes = {"operation": name, "outcome": outcome}
    if failure_category is not None:
        attributes["failure_category"] = failure_category
    return RecordedSpan(name=name, attributes=attributes, is_completed=True)


def _latency(
    name: str,
    labels: dict[str, str],
    value: float = 1.0,
) -> tuple[str, float, dict[str, str]]:
    """Return a latency observation with the millisecond count ``StepClock`` made."""
    return (f"{name}.latency_ms", value, labels)


@pytest.mark.asyncio
async def test_recording_opens_one_span_and_observes_latency(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A first-time recording is one span and one bounded latency."""
    episode_id = await create_episode(session_factory)
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    evaluation = make_evaluation(episode_id, idempotency_key="observed")

    async with session_factory() as session:
        store = SqlAlchemyQaArtefactStore(
            session,
            runtime=_instrumented_runtime(tracer, metrics),
        )
        await store.record_evaluation(evaluation)
        await session.commit()

    assert tracer.spans == [_span("qa_artefact.record", "recorded")], tracer.spans
    assert metrics.latencies == [
        _latency(
            "qa_artefact.record",
            {"evaluator": "pedante", "outcome": "recorded"},
        )
    ], metrics.latencies


@pytest.mark.asyncio
async def test_replay_marks_the_record_span_replayed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A repeated identifier and key records a replayed outcome."""
    episode_id = await create_episode(session_factory)
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    first = make_evaluation(episode_id, idempotency_key="replay")
    replay = make_evaluation(episode_id, idempotency_key="replay")

    async with session_factory() as session:
        store = SqlAlchemyQaArtefactStore(
            session,
            runtime=_instrumented_runtime(tracer, metrics),
        )
        await store.record_evaluation(first)
        await store.record_evaluation(replay)
        await session.commit()

    assert tracer.spans == [
        _span("qa_artefact.record", "recorded"),
        _span("qa_artefact.record", "replayed"),
    ], tracer.spans
    assert [entry[2]["outcome"] for entry in metrics.latencies] == [
        "recorded",
        "replayed",
    ], metrics.latencies


@pytest.mark.asyncio
async def test_supersession_opens_a_nested_span(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Replacing an errored artefact is visible as its own operation."""
    episode_id = await create_episode(session_factory)
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    errored = make_evaluation(
        episode_id,
        idempotency_key="supersede",
        options=EvaluationOptions(
            compliance_status=QaComplianceStatus.ERRORED,
            severities=(QaFindingSeverity.LOW,),
        ),
    )
    compliant = make_evaluation(
        episode_id,
        idempotency_key="supersede",
        options=EvaluationOptions(
            compliance_status=QaComplianceStatus.COMPLIANT,
            severities=(QaFindingSeverity.HIGH,),
        ),
    )

    async with session_factory() as session:
        store = SqlAlchemyQaArtefactStore(
            session,
            runtime=_instrumented_runtime(tracer, metrics),
        )
        await store.record_evaluation(errored)
        await store.record_evaluation(compliant)
        await session.commit()

    assert [(span.name, span.attributes["outcome"]) for span in tracer.spans] == [
        ("qa_artefact.record", "recorded"),
        ("qa_artefact.record", "superseded"),
        ("qa_artefact.supersede", "superseded"),
    ], tracer.spans
    assert metrics.latencies[1] == _latency(
        "qa_artefact.supersede",
        {"evaluator": "pedante", "outcome": "superseded"},
    ), metrics.latencies
    # The outer record span covers the nested supersession, so its elapsed
    # time is the sum of the inner operation's three clock steps.
    assert metrics.latencies[2] == _latency(
        "qa_artefact.record",
        {"evaluator": "pedante", "outcome": "superseded"},
        value=3.0,
    ), metrics.latencies


@pytest.mark.asyncio
async def test_rejected_recording_marks_the_span_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A non-replay constraint violation reaches the caller and the span."""
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    orphan = make_evaluation(uuid.uuid7(), idempotency_key="orphan")

    async with session_factory() as session:
        store = SqlAlchemyQaArtefactStore(
            session,
            runtime=_instrumented_runtime(tracer, metrics),
        )
        with pytest.raises(IntegrityError):
            await store.record_evaluation(orphan)
        await session.rollback()

    assert tracer.spans == [
        _span(
            "qa_artefact.record",
            "failed",
            failure_category="integrity_violation",
        )
    ], tracer.spans
    assert metrics.latencies[0][2] == {
        "evaluator": "pedante",
        "outcome": "failed",
        "failure_category": "integrity_violation",
    }, metrics.latencies


@pytest.mark.asyncio
async def test_storage_error_marks_the_record_span_failed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unclassified database error is reported as ``database_error``."""
    episode_id = await create_episode(session_factory)
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    evaluation = make_evaluation(episode_id, idempotency_key="broken")

    def reject(_evaluation: object, *, created_at: dt.datetime) -> object:
        """Fail the mapping with a database-level error."""
        del created_at
        raise SQLAlchemyError

    monkeypatch.setattr(qa_artefacts, "evaluation_to_record", reject)

    async with session_factory() as session:
        store = SqlAlchemyQaArtefactStore(
            session,
            runtime=_instrumented_runtime(tracer, metrics),
        )
        with pytest.raises(SQLAlchemyError):
            await store.record_evaluation(evaluation)
        await session.rollback()

    assert tracer.spans == [
        _span("qa_artefact.record", "failed", failure_category="database_error")
    ], tracer.spans


@pytest.mark.asyncio
async def test_get_distinguishes_found_and_missing_outcomes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A miss reads as ``not_found`` and a hit as ``success``."""
    episode_id = await create_episode(session_factory)
    tracer = RecordingTracer()
    metrics = RecordingMetrics()
    evaluation = make_evaluation(episode_id, idempotency_key="get")
    async with session_factory() as session:
        session.add(evaluation_to_record(evaluation, created_at=NOW))
        await session.commit()

    async with session_factory() as session:
        store = SqlAlchemyQaArtefactStore(
            session,
            runtime=_instrumented_runtime(tracer, metrics),
        )
        missing = await store.get_evaluation(uuid.uuid7())
        assert missing is None, "an unknown identifier should read as not found"
        stored = await store.get_evaluation(evaluation.summary_record.id)
        assert stored is not None, "a stored identifier should read back"

    assert tracer.spans == [
        _span("qa_artefact.get", "not_found"),
        _span("qa_artefact.get", "success"),
    ], tracer.spans


@pytest.mark.asyncio
async def test_get_marks_an_unreadable_schema_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A row written by a newer release reports ``unsupported_schema``."""
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
            runtime=_instrumented_runtime(tracer, metrics),
        )
        with pytest.raises(UnsupportedQaArtefactSchemaError):
            await store.get_evaluation(evaluation.summary_record.id)

    assert tracer.spans == [
        _span("qa_artefact.get", "failed", failure_category="unsupported_schema")
    ], tracer.spans


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
            runtime=_instrumented_runtime(tracer, metrics),
        )
        await store.list_evaluations(
            QaEvaluationListRequest(
                episode_id=episode_id,
                pagination=Pagination(limit=10, offset=0),
            )
        )

    assert tracer.spans == [_span("qa_artefact.list", "success")], tracer.spans
    assert metrics.latencies == [
        _latency("qa_artefact.list", {"outcome": "success"})
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
            runtime=_instrumented_runtime(tracer, metrics),
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
        _span("qa_artefact.list", "failed", failure_category="database_error")
    ], tracer.spans
