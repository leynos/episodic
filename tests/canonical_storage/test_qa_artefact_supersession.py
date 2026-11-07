"""QA artefact supersession contract tests.

Covers ``INV-ERRORED-SUPERSEDED``: a stored ``ERRORED`` artefact is replaced in
place by a later non-errored recording under the same episode and idempotency
key, and keeps the identifier the failure created.
"""

import dataclasses as dc
import datetime as dt

import pytest

from episodic.canonical.qa_artefact_recording import (
    QaEvaluationTarget,
    QaEvaluatorFailure,
    evaluation_from_chrono,
    evaluation_from_failure,
)
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
from tests.fixtures.qa_artefact_recording_builders import (
    EVALUATED_AT,
    TEI_CONTENT_HASH,
    chrono_estimate,
    chrono_metadata,
)

# Distinct from every other recorded field, so an assertion on it cannot pass
# because some other column happened to carry the same value.
RETRY_RUNTIME_ESTIMATE_SECONDS = 412
# The failure records the contract version it attempted, and the retry's
# estimate carries the same one; that is what makes the two share a key.
CHRONO_CONTRACT_VERSION = "1"
RETRY_AT = dt.datetime(2026, 11, 1, 9, 0, tzinfo=dt.UTC)


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

    Both artefacts come from the production projections, so this case also
    pins that a recorded failure and the estimate that retries it derive the
    same idempotency key. Chrono measures duration, so the retry is
    ``NOT_APPLICABLE`` and carries a runtime estimate: the supersession rule
    may not be narrowed to verdict-bearing evaluators without failing here.
    """
    episode_id = await create_episode(session_factory)
    target = QaEvaluationTarget(
        episode_id=episode_id,
        tei_content_hash=TEI_CONTENT_HASH,
        evaluated_at=EVALUATED_AT,
    )
    failed = evaluation_from_failure(
        QaEvaluatorFailure(
            evaluator=QaEvaluator.CHRONO,
            evaluator_version=CHRONO_CONTRACT_VERSION,
            error_category="estimator_timeout",
            summary="Chrono did not answer before the deadline.",
        ),
        target=target,
    )
    retried = evaluation_from_chrono(
        chrono_estimate(
            estimated_seconds=RETRY_RUNTIME_ESTIMATE_SECONDS,
            metadata=chrono_metadata(estimator_version=CHRONO_CONTRACT_VERSION),
        ),
        target=dc.replace(target, evaluated_at=RETRY_AT),
    )

    assert (
        failed.summary_record.idempotency_key == retried.summary_record.idempotency_key
    ), "the retry must derive the key the failure was recorded under"

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored_failed = await uow.qa_artefacts.record_evaluation(failed)
        await uow.qa_artefacts.record_evaluation(retried)
        await uow.commit()

    assert (
        stored_failed.summary_record.compliance_status is QaComplianceStatus.ERRORED
    ), "the failed run should be recorded as an errored artefact"

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        reread = await uow.qa_artefacts.get_evaluation(failed.summary_record.id)

    assert reread is not None, "the superseded artefact should still exist"
    assert reread.summary_record.id == failed.summary_record.id, (
        "the retry should keep the identifier the failure created"
    )
    assert (
        reread.summary_record.compliance_status is QaComplianceStatus.NOT_APPLICABLE
    ), "the retry should store its own verdict rather than replay the failure"
    assert reread.summary_record.runtime_estimate_seconds == (
        RETRY_RUNTIME_ESTIMATE_SECONDS
    ), "the superseded artefact should carry the retry's runtime estimate"
    assert reread.summary_record.evaluator_metadata["estimator_version"] == (
        CHRONO_CONTRACT_VERSION
    ), "the superseded artefact should carry the retry's estimator metadata"
    async with session_factory() as session:
        assert await count_rows(session, QaEvaluationRecord) == 1, (
            "the retry should replace the failed artefact, not add a second row"
        )
