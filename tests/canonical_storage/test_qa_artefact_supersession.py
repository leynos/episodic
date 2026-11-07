"""QA artefact supersession contract tests.

Covers ``INV-ERRORED-SUPERSEDED``: a stored ``ERRORED`` artefact is replaced in
place by a later non-errored recording under the same episode and idempotency
key, and keeps the identifier the failure created.
"""

import pytest

from episodic.canonical.qa_artefacts import (
    QaComplianceStatus,
    QaEvaluator,
    QaFindingSeverity,
)
from episodic.canonical.storage import (
    QaEvaluationRecord,
    QaFindingRecord,
    SqlAlchemyUnitOfWork,
)
from tests.canonical_storage._qa_artefact_support import (
    REPLAYED_AT,
    EvaluationOptions,
    SessionFactory,
    count_rows,
    create_episode,
    make_evaluation,
)


@pytest.mark.parametrize(
    ("stored_status", "incoming_status", "is_superseded"),
    [
        (QaComplianceStatus.COMPLIANT, QaComplianceStatus.COMPLIANT, False),
        (QaComplianceStatus.COMPLIANT, QaComplianceStatus.ERRORED, False),
        (QaComplianceStatus.NON_COMPLIANT, QaComplianceStatus.COMPLIANT, False),
        (QaComplianceStatus.NON_COMPLIANT, QaComplianceStatus.ERRORED, False),
        (QaComplianceStatus.NOT_APPLICABLE, QaComplianceStatus.COMPLIANT, False),
        (QaComplianceStatus.NOT_APPLICABLE, QaComplianceStatus.ERRORED, False),
        (QaComplianceStatus.ERRORED, QaComplianceStatus.COMPLIANT, True),
        (QaComplianceStatus.ERRORED, QaComplianceStatus.NON_COMPLIANT, True),
        (QaComplianceStatus.ERRORED, QaComplianceStatus.ERRORED, False),
    ],
)
@pytest.mark.asyncio
async def test_errored_artefact_is_superseded_in_place(
    session_factory: SessionFactory,
    stored_status: QaComplianceStatus,
    incoming_status: QaComplianceStatus,
    *,
    is_superseded: bool,
) -> None:
    """Only an errored artefact is replaced, and it keeps its identifier."""
    episode_id = await create_episode(session_factory)
    first = make_evaluation(
        episode_id,
        idempotency_key="supersede",
        options=EvaluationOptions(
            compliance_status=stored_status,
            severities=(QaFindingSeverity.LOW,),
        ),
    )
    incoming = make_evaluation(
        episode_id,
        idempotency_key="supersede",
        options=EvaluationOptions(
            compliance_status=incoming_status,
            severities=(QaFindingSeverity.HIGH, QaFindingSeverity.HIGH),
            evaluated_at=REPLAYED_AT,
        ),
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored_first = await uow.qa_artefacts.record_evaluation(first)
        stored_repeat = await uow.qa_artefacts.record_evaluation(incoming)
        await uow.commit()

    assert stored_repeat.summary_record.id == first.summary_record.id, (
        "supersession should keep the stored identifier"
    )
    async with session_factory() as session:
        assert await count_rows(session, QaEvaluationRecord) == 1, (
            "supersession should not create a second evaluation row"
        )
        assert await count_rows(session, QaFindingRecord) == (
            2 if is_superseded else 1
        ), "only a superseding recording should replace the findings"

    if not is_superseded:
        assert stored_repeat == stored_first, (
            "a non-superseding replay should return the stored artefact unchanged"
        )
        return

    assert stored_repeat.summary_record.compliance_status is incoming_status, (
        "the superseded artefact should carry the incoming verdict"
    )
    assert stored_repeat.summary_record.evaluated_at == REPLAYED_AT, (
        "the superseded artefact should carry the incoming evaluation time"
    )
    assert [item.severity for item in stored_repeat.findings] == [
        QaFindingSeverity.HIGH,
        QaFindingSeverity.HIGH,
    ], "the superseded artefact should carry the incoming findings"


@pytest.mark.asyncio
async def test_errored_chrono_recording_is_superseded_by_its_retry(
    session_factory: SessionFactory,
) -> None:
    """A retried Chrono run replaces the errored artefact it first recorded.

    A failed Chrono run is recorded as an ``ERRORED`` artefact under the same
    idempotency key the successful retry will derive, so the retry must persist
    its verdict rather than replay the failure.
    """
    episode_id = await create_episode(session_factory)
    failed = make_evaluation(
        episode_id,
        idempotency_key="chrono-retry",
        options=EvaluationOptions(
            evaluator=QaEvaluator.CHRONO,
            compliance_status=QaComplianceStatus.ERRORED,
        ),
    )
    retried = make_evaluation(
        episode_id,
        idempotency_key="chrono-retry",
        options=EvaluationOptions(
            evaluator=QaEvaluator.CHRONO,
            compliance_status=QaComplianceStatus.COMPLIANT,
            evaluated_at=REPLAYED_AT,
            severities=(QaFindingSeverity.LOW,),
        ),
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored_failed = await uow.qa_artefacts.record_evaluation(failed)
        stored_retried = await uow.qa_artefacts.record_evaluation(retried)
        reread = await uow.qa_artefacts.get_evaluation(failed.summary_record.id)
        await uow.commit()

    assert (
        stored_failed.summary_record.compliance_status is QaComplianceStatus.ERRORED
    ), "the failed run should be recorded as an errored artefact"
    assert stored_retried.summary_record.id == failed.summary_record.id, (
        "the retry should keep the identifier the failure created"
    )
    assert (
        stored_retried.summary_record.compliance_status is QaComplianceStatus.COMPLIANT
    ), "the retry should store its own verdict rather than replay the failure"
    assert reread == stored_retried, (
        "a later read should return the superseded artefact"
    )
