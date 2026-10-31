"""Unit tests for the Chrono and failure projections onto QA artefacts.

Both outcomes record an evaluation the episode did not pass on merit: Chrono
renders no compliance verdict at all, and a failure must be visible in the
archive yet still be superseded by a later success. These cases pin both, while
``tests/test_qa_artefact_recording.py`` covers the Pedante projection.
"""

import typing as typ

from episodic.canonical.qa_artefact_recording import (
    evaluation_from_chrono,
    evaluation_from_failure,
)
from episodic.canonical.qa_artefacts import (
    QaComplianceStatus,
    QaEvaluator,
)
from tests.fixtures.qa_artefact_recording_builders import (
    EPISODE_ID,
    EVALUATED_AT,
    GENERATION_RUN_ID,
    TEI_CONTENT_HASH,
    chrono_estimate,
)

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


def test_chrono_estimate_becomes_a_not_applicable_artefact(
    snapshot: SnapshotAssertion,
) -> None:
    """Chrono renders no compliance verdict, so its artefact says so."""
    estimate = chrono_estimate()

    evaluation = evaluation_from_chrono(
        estimate,
        episode_id=EPISODE_ID,
        tei_content_hash=TEI_CONTENT_HASH,
        evaluated_at=EVALUATED_AT,
    )

    assert evaluation.summary_record.evaluator is QaEvaluator.CHRONO, (
        "a Chrono estimate should map to the Chrono evaluator"
    )
    assert evaluation.summary_record.compliance_status is (
        QaComplianceStatus.NOT_APPLICABLE
    ), "Chrono should record the not-applicable verdict"
    assert evaluation.summary_record.runtime_estimate_seconds == 600, (
        "the estimate should be recorded in whole seconds"
    )
    assert evaluation.summary_record.evaluator_version == "1", (
        "the evaluator version should come from the estimator metadata"
    )
    assert evaluation.summary_record.evaluator_metadata == snapshot, (
        "the whole estimator metadata projection should be recorded"
    )
    assert not evaluation.findings, "Chrono produces no findings"
    assert evaluation.summary_record.finding_count == 0, (
        "an empty finding list should record a zero count"
    )


def test_chrono_version_changes_the_key() -> None:
    """A new estimator version starts a new artefact rather than a replay."""
    first = evaluation_from_chrono(
        chrono_estimate(estimator_version="1"),
        episode_id=EPISODE_ID,
        tei_content_hash=TEI_CONTENT_HASH,
        evaluated_at=EVALUATED_AT,
    )
    second = evaluation_from_chrono(
        chrono_estimate(estimator_version="2"),
        episode_id=EPISODE_ID,
        tei_content_hash=TEI_CONTENT_HASH,
        evaluated_at=EVALUATED_AT,
    )

    assert (
        first.summary_record.idempotency_key != second.summary_record.idempotency_key
    ), "a changed estimator version reused the previous artefact's key"


def test_failure_becomes_an_errored_artefact() -> None:
    """A failed invocation is recorded so a later success can supersede it."""
    evaluation = evaluation_from_failure(
        QaEvaluator.ANTHEM,
        episode_id=EPISODE_ID,
        evaluator_version="4",
        tei_content_hash=TEI_CONTENT_HASH,
        error_category="provider_timeout",
        summary="Anthem did not answer before the deadline.",
        evaluated_at=EVALUATED_AT,
        generation_run_id=GENERATION_RUN_ID,
    )

    assert evaluation.summary_record.evaluator is QaEvaluator.ANTHEM, (
        "the failure should be attributed to the evaluator that failed"
    )
    assert evaluation.summary_record.compliance_status is (
        QaComplianceStatus.ERRORED
    ), "a failed invocation should record the errored verdict"
    assert evaluation.summary_record.evaluator_version == "4", (
        "the failure should record the version the evaluator attempted"
    )
    assert evaluation.summary_record.evaluator_metadata == {
        "error_category": "provider_timeout"
    }, "the failure should record its bounded error category"
    assert evaluation.summary_record.summary == (
        "Anthem did not answer before the deadline."
    ), "the recorded failure should explain itself"
    assert not evaluation.findings, "a failed invocation has no findings"


def test_a_retry_reuses_the_failed_evaluations_key() -> None:
    """Recording a success after a failure supersedes rather than replays."""
    failure = evaluation_from_failure(
        QaEvaluator.CHRONO,
        episode_id=EPISODE_ID,
        evaluator_version="1",
        tei_content_hash=TEI_CONTENT_HASH,
        error_category="invalid_tei",
        summary="Chrono could not parse the script.",
        evaluated_at=EVALUATED_AT,
    )
    success = evaluation_from_chrono(
        chrono_estimate(estimator_version="1"),
        episode_id=EPISODE_ID,
        tei_content_hash=TEI_CONTENT_HASH,
        evaluated_at=EVALUATED_AT,
    )

    assert (
        failure.summary_record.idempotency_key == success.summary_record.idempotency_key
    ), "a retry of the same evaluation must reuse its key so it can supersede"
