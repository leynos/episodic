"""QA artefact SQLAlchemy adapter contract tests.

Covers recording and fetching an evaluation with its findings, timezone
preservation, the repository half of ``INV-COUNT-AGREES`` and
``INV-EPISODE-LINK``, and the adapter's bounded-cardinality observability.
"""

import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_quality import QualityMode
from episodic.canonical.pagination import Pagination
from episodic.canonical.qa_artefact_ports import QaEvaluationListRequest
from episodic.canonical.qa_artefacts import QaFindingSeverity
from episodic.canonical.storage import (
    EpisodeRecord,
    GenerationRunRecord,
    QaArtefactStorageRuntime,
    QaEvaluationRecord,
    QaFindingRecord,
    SqlAlchemyUnitOfWork,
    UnitOfWorkRuntime,
    qa_artefact_outcomes,
)
from tests.canonical_storage._qa_artefact_support import (
    EvaluationOptions,
    count_rows,
    create_episode,
    create_ingestion_job,
    make_evaluation,
)
from tests.canonical_storage._workflow_checkpoint_support import (
    RecordingMetrics,
    StepClock,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from syrupy.assertion import SnapshotAssertion

NOW = dt.datetime(2026, 10, 31, 9, 0, tzinfo=dt.UTC)


@pytest.mark.asyncio
async def test_evaluation_round_trip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A recorded evaluation reads back exactly as it was stored."""
    episode_id = await create_episode(session_factory)
    evaluation = make_evaluation(
        episode_id,
        idempotency_key="round-trip",
        options=EvaluationOptions(
            severities=(
                QaFindingSeverity.LOW,
                QaFindingSeverity.HIGH,
                QaFindingSeverity.MEDIUM,
            ),
            created_at=NOW,
        ),
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = await uow.qa_artefacts.record_evaluation(evaluation)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        fetched = await uow.qa_artefacts.get_evaluation(evaluation.summary_record.id)

    assert fetched is not None, "expected the recorded evaluation to be readable"
    assert fetched == stored, "a later read should equal the recorded artefact"
    assert fetched.summary_record.created_at == NOW, (
        "recording should stamp the caller-supplied storage time"
    )
    assert [item.ordinal for item in fetched.findings] == [0, 1, 2], (
        "findings should read back in emission order"
    )
    assert [item.severity for item in fetched.findings] == [
        QaFindingSeverity.LOW,
        QaFindingSeverity.HIGH,
        QaFindingSeverity.MEDIUM,
    ], "the stored severities should keep their emission order"


@pytest.mark.asyncio
async def test_get_unknown_evaluation_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An unknown identifier reads as absent rather than raising."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        fetched = await uow.qa_artefacts.get_evaluation(uuid.uuid7())

    assert fetched is None, "an unknown evaluation should read as absent"


@pytest.mark.parametrize(
    "offset",
    [dt.UTC, dt.timezone(dt.timedelta(hours=5, minutes=30))],
    ids=["utc", "plus-0530"],
)
@pytest.mark.asyncio
async def test_evaluation_round_trip_preserves_the_instant(
    session_factory: async_sessionmaker[AsyncSession],
    offset: dt.tzinfo,
) -> None:
    """A non-UTC offset round-trips to the same instant and stays aware."""
    episode_id = await create_episode(session_factory)
    evaluated_at = dt.datetime(2026, 10, 29, 12, 0, tzinfo=offset)
    evaluation = make_evaluation(
        episode_id,
        idempotency_key="timezone",
        options=EvaluationOptions(evaluated_at=evaluated_at),
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.qa_artefacts.record_evaluation(evaluation)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        fetched = await uow.qa_artefacts.get_evaluation(evaluation.summary_record.id)

    assert fetched is not None, "expected the recorded evaluation to be readable"
    assert fetched.summary_record.evaluated_at == evaluated_at, (
        "the stored instant should equal the recorded instant"
    )
    assert fetched.summary_record.evaluated_at.tzinfo is not None, (
        "TIMESTAMPTZ should return an aware datetime"
    )


@pytest.mark.parametrize("finding_count", [0, 1, 3])
@pytest.mark.asyncio
async def test_listed_finding_count_agrees_with_stored_findings(
    session_factory: async_sessionmaker[AsyncSession],
    finding_count: int,
) -> None:
    """The listed count equals the detail endpoint's findings length."""
    episode_id = await create_episode(session_factory)
    evaluation = make_evaluation(
        episode_id,
        idempotency_key=f"count-{finding_count}",
        options=EvaluationOptions(
            severities=(QaFindingSeverity.LOW,) * finding_count,
        ),
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.qa_artefacts.record_evaluation(evaluation)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        summaries, total = await uow.qa_artefacts.list_evaluations(
            QaEvaluationListRequest(
                episode_id=episode_id,
                pagination=Pagination(limit=10, offset=0),
            )
        )
        detail = await uow.qa_artefacts.get_evaluation(evaluation.summary_record.id)

    assert detail is not None, "expected the recorded evaluation to be readable"
    assert total == 1, "the episode holds exactly one evaluation"
    assert summaries[0].finding_count == finding_count, (
        "the list projection should carry the stored count"
    )
    assert len(detail.findings) == finding_count, (
        "the detail endpoint should return every stored finding"
    )


@pytest.mark.asyncio
async def test_deleting_episode_cascades_evaluations_and_findings(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Deleting an episode removes its evaluations and their findings."""
    episode_id = await create_episode(session_factory)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        for key, severities in (
            ("first", (QaFindingSeverity.LOW,)),
            ("second", (QaFindingSeverity.LOW, QaFindingSeverity.MEDIUM)),
        ):
            await uow.qa_artefacts.record_evaluation(
                make_evaluation(
                    episode_id,
                    idempotency_key=key,
                    options=EvaluationOptions(severities=severities),
                )
            )
        await uow.commit()

    async with session_factory() as session:
        assert await count_rows(session, QaEvaluationRecord) == 2, (
            "both evaluations should be stored before the delete"
        )
        assert await count_rows(session, QaFindingRecord) == 3, (
            "all three findings should be stored before the delete"
        )
        await session.execute(
            sa.delete(EpisodeRecord).where(EpisodeRecord.id == episode_id)
        )
        await session.commit()
        assert await count_rows(session, QaEvaluationRecord) == 0, (
            "deleting the episode should remove its evaluations"
        )
        assert await count_rows(session, QaFindingRecord) == 0, (
            "deleting the episode should remove the findings too"
        )


@pytest.mark.asyncio
async def test_deleting_generation_run_keeps_evaluation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Deleting a run nulls the link and leaves the evaluation in place."""
    episode_id = await create_episode(session_factory)
    job_id = await create_ingestion_job(session_factory, episode_id)
    run_id = uuid.uuid7()
    run = GenerationRunRecord(
        id=run_id,
        episode_id=episode_id,
        source_bundle_id=job_id,
        actor="tester",
        status=GenerationRunStatus.PENDING,
        budget_snapshot={},
        configuration={},
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        idempotency_principal_id="tester",
    )
    async with session_factory() as session:
        session.add(run)
        await session.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.qa_artefacts.record_evaluation(
            make_evaluation(
                episode_id,
                idempotency_key="run-link",
                options=EvaluationOptions(
                    severities=(QaFindingSeverity.LOW,),
                    generation_run_id=run_id,
                ),
            )
        )
        await uow.commit()

    async with session_factory() as session:
        await session.execute(
            sa.delete(GenerationRunRecord).where(GenerationRunRecord.id == run_id)
        )
        await session.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        summaries, total = await uow.qa_artefacts.list_evaluations(
            QaEvaluationListRequest(
                episode_id=episode_id,
                pagination=Pagination(limit=10, offset=0),
            )
        )

    assert total == 1, "the evaluation should outlive the run that produced it"
    assert summaries[0].generation_run_id is None, (
        "deleting the run should null the evaluation's link"
    )


@pytest.mark.asyncio
async def test_recording_emits_bounded_metrics_and_safe_log(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    """Recording and replay each emit a bounded counter and one log line."""
    # A fixed identifier keeps the log-event snapshot deterministic.
    episode_id = await create_episode(session_factory, episode_id=uuid.UUID(int=7))
    metrics = RecordingMetrics()
    runtime = UnitOfWorkRuntime(
        qa_artefact_runtime=QaArtefactStorageRuntime(
            clock=lambda: NOW,
            metrics=metrics,
            monotonic_clock=StepClock(),
        )
    )
    events: list[tuple[str, str, dict[str, object]]] = []

    def record_log_event(level: str, message: str, **fields: object) -> None:
        events.append((level, message, fields))

    monkeypatch.setattr(qa_artefact_outcomes, "_log_event", record_log_event)
    first = make_evaluation(
        episode_id,
        idempotency_key="observed",
        options=EvaluationOptions(severities=(QaFindingSeverity.LOW,)),
    )
    replay = make_evaluation(
        episode_id,
        idempotency_key="observed",
        options=EvaluationOptions(severities=(QaFindingSeverity.HIGH,)),
    )

    async with SqlAlchemyUnitOfWork(session_factory, runtime=runtime) as uow:
        await uow.qa_artefacts.record_evaluation(first)
        await uow.qa_artefacts.record_evaluation(replay)
        await uow.commit()

    assert metrics.as_snapshot() == snapshot, (
        "recording and replay should each increment one bounded counter"
    )
    for _, _, fields in events:
        assert fields["episode_id"] == str(episode_id), (
            "each log line should carry the episode identifier"
        )
    # The identifier stays out of the snapshot so the recorded evidence holds
    # no UUID; its presence and value are asserted above.
    redacted = [
        (level, message, {**fields, "episode_id": "<episode>"})
        for level, message, fields in events
    ]
    assert redacted == snapshot, (
        "each outcome should log one line carrying identifiers but no finding text"
    )


@pytest.mark.asyncio
async def test_recording_failure_emits_bounded_metric_and_reraises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A rejected insert counts a bounded failure and reaches the caller."""
    metrics = RecordingMetrics()
    runtime = UnitOfWorkRuntime(
        qa_artefact_runtime=QaArtefactStorageRuntime(
            clock=lambda: NOW,
            metrics=metrics,
            monotonic_clock=StepClock(),
        )
    )
    orphan = make_evaluation(uuid.uuid7(), idempotency_key="orphan")

    async with SqlAlchemyUnitOfWork(session_factory, runtime=runtime) as uow:
        with pytest.raises(IntegrityError):
            await uow.qa_artefacts.record_evaluation(orphan)

    assert metrics.counters == [
        (
            "qa_evaluation_record_failed",
            {"evaluator": "pedante", "error_category": "integrity_violation"},
        )
    ], "a non-idempotency violation should count one bounded failure"
