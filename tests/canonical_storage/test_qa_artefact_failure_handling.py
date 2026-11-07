"""QA artefact recording failure and replay-locking contract tests.

Covers the failure side of ``INV-REPLAY-IDEMPOTENT``: a rejected supersession
rolls back alone and stays observable, a non-idempotency violation is not
mistaken for a replay, and the replay lookup locks the row it may supersede.
"""

import typing as typ
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from episodic.canonical.qa_artefacts import (
    QaComplianceStatus,
    QaFinding,
    QaFindingSeverity,
)
from episodic.canonical.storage import (
    QaArtefactStorageRuntime,
    QaFindingRecord,
    SqlAlchemyQaArtefactStore,
    SqlAlchemyUnitOfWork,
    qa_artefacts,
)
from episodic.observability import RecordingTracer
from tests.canonical_storage._qa_artefact_support import (
    REPLAYED_AT,
    EvaluationOptions,
    SessionFactory,
    create_episode,
    make_evaluation,
)
from tests.canonical_storage._workflow_checkpoint_support import RecordingMetrics

if typ.TYPE_CHECKING:
    from episodic.canonical.qa_artefacts import QaEvaluation


def _supersession_pair(
    episode_id: uuid.UUID,
) -> tuple[QaEvaluation, QaEvaluation]:
    """Return an errored artefact and the compliant replacement for it."""
    first = make_evaluation(
        episode_id,
        idempotency_key="supersede-failure",
        options=EvaluationOptions(
            compliance_status=QaComplianceStatus.ERRORED,
            severities=(QaFindingSeverity.LOW,),
        ),
    )
    incoming = make_evaluation(
        episode_id,
        idempotency_key="supersede-failure",
        options=EvaluationOptions(
            compliance_status=QaComplianceStatus.COMPLIANT,
            severities=(QaFindingSeverity.HIGH,),
            evaluated_at=REPLAYED_AT,
        ),
    )
    return first, incoming


def _reject_replacement_ordinals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the next replacement write a finding ordinal the schema rejects."""
    real_finding_to_record = qa_artefacts.finding_to_record

    def reject_replacement_findings(
        finding: QaFinding,
        *,
        evaluation_id: uuid.UUID,
    ) -> QaFindingRecord:
        """Build a replacement finding that violates the ordinal check."""
        record = real_finding_to_record(finding, evaluation_id=evaluation_id)
        record.ordinal = -1
        return record

    monkeypatch.setattr(qa_artefacts, "finding_to_record", reject_replacement_findings)


@pytest.mark.asyncio
async def test_supersession_failure_is_counted_and_keeps_the_transaction_usable(
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected supersession is bounded, reported, and rolled back alone."""
    episode_id = await create_episode(session_factory)
    first, incoming = _supersession_pair(episode_id)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = await uow.qa_artefacts.record_evaluation(first)
        await uow.commit()

    metrics = RecordingMetrics()
    tracer = RecordingTracer()
    runtime = QaArtefactStorageRuntime(
        clock=lambda: REPLAYED_AT,
        metrics=metrics,
        tracer=tracer,
    )
    async with session_factory() as session:
        _reject_replacement_ordinals(monkeypatch)
        store = SqlAlchemyQaArtefactStore(session, runtime=runtime)
        with pytest.raises(IntegrityError):
            await store.record_evaluation(incoming)
        assert await session.scalar(sa.text("SELECT 1")) == 1, (
            "a rejected supersession must leave the caller's transaction usable"
        )
        await session.rollback()

    async with session_factory() as session:
        reloaded = await SqlAlchemyQaArtefactStore(session).get_evaluation(
            stored.summary_record.id
        )

    assert reloaded is not None, "the stored evaluation should still be readable"
    assert reloaded.summary_record.compliance_status is QaComplianceStatus.ERRORED, (
        "a failed supersession should leave the stored verdict untouched"
    )
    assert [item.severity for item in reloaded.findings] == [QaFindingSeverity.LOW], (
        "a failed supersession should leave the stored findings untouched"
    )
    assert metrics.counters == [
        (
            "qa_evaluation_record_failed",
            {"evaluator": "pedante", "error_category": "supersede_failed"},
        )
    ], "a supersession failure should count one bounded failure"
    outer_spans = [span for span in tracer.spans if span.name == "qa_artefact.record"]
    assert len(outer_spans) == 1, "the recording should open exactly one outer span"
    assert outer_spans[0].attributes["failure_category"] == "supersede_failed", (
        "the outer record span must name the supersession failure, not unexpected_error"
    )


@pytest.mark.asyncio
async def test_caller_owned_constraint_failure_is_not_counted_as_a_qa_failure(
    session_factory: SessionFactory,
) -> None:
    """A caller's invalid pending row fails without a QA failure metric."""
    episode_id = await create_episode(session_factory)
    first = make_evaluation(episode_id, idempotency_key="caller-pending")
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = await uow.qa_artefacts.record_evaluation(first)
        await uow.commit()

    metrics = RecordingMetrics()
    runtime = QaArtefactStorageRuntime(
        clock=lambda: REPLAYED_AT,
        metrics=metrics,
    )
    incoming = make_evaluation(episode_id, idempotency_key="caller-pending-other")
    async with session_factory() as session:
        session.add(
            QaFindingRecord(
                id=uuid.uuid7(),
                evaluation_id=stored.summary_record.id,
                ordinal=-1,
                severity=QaFindingSeverity.LOW,
                code="caller-owned",
                summary="A pending row the caller owns.",
                is_blocking=False,
            )
        )
        store = SqlAlchemyQaArtefactStore(session, runtime=runtime)
        with pytest.raises(IntegrityError):
            await store.record_evaluation(incoming)
        await session.rollback()

    assert not metrics.counters, (
        "a caller-owned constraint failure must not be counted as a QA failure"
    )


@pytest.mark.asyncio
async def test_replay_lookup_locks_the_stored_row_against_supersession(
    session_factory: SessionFactory,
) -> None:
    """The replay lookup must lock the row before it decides to supersede.

    A racing pair of recordings cannot be interleaved deterministically here:
    once one transaction has updated the stored artefact, the other's insert
    blocks on that row lock before it ever reaches the replay lookup. The
    locking clause is therefore asserted directly as the observable substitute
    for the concurrent race.
    """
    episode_id = await create_episode(session_factory)
    errored = make_evaluation(
        episode_id,
        idempotency_key="locked-replay",
        options=EvaluationOptions(
            compliance_status=QaComplianceStatus.ERRORED,
            severities=(QaFindingSeverity.LOW,),
        ),
    )
    incoming = make_evaluation(
        episode_id,
        idempotency_key="locked-replay",
        options=EvaluationOptions(
            compliance_status=QaComplianceStatus.COMPLIANT,
            severities=(QaFindingSeverity.HIGH,),
            evaluated_at=REPLAYED_AT,
        ),
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.qa_artefacts.record_evaluation(errored)
        await uow.commit()

    statements: list[str] = []

    def capture_statement(*args: object) -> None:
        """Record each statement the session sends."""
        statement = args[2]
        if isinstance(statement, str):
            statements.append(statement)

    async with session_factory() as session:
        bind = session.get_bind()
        event.listen(bind, "before_cursor_execute", capture_statement)
        try:
            await SqlAlchemyQaArtefactStore(session).record_evaluation(incoming)
        finally:
            event.remove(bind, "before_cursor_execute", capture_statement)

    replay_lookups = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
        and "qa_evaluations.idempotency_key =" in statement
    ]
    assert replay_lookups, "the replay should look the stored artefact up by key"
    for statement in replay_lookups:
        assert "FOR UPDATE" in statement, (
            "the replay lookup must lock the stored artefact so a concurrent "
            "supersession is replayed rather than collided with"
        )
