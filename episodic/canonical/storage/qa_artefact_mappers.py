"""Record-to-domain mappings for QA artefacts and their findings."""

import typing as typ

from episodic.canonical.qa_artefact_errors import UnsupportedQaArtefactSchemaError
from episodic.canonical.qa_artefacts import (
    QA_ARTEFACT_SCHEMA_VERSION,
    QaEvaluation,
    QaEvaluationSummary,
    QaFinding,
)

from .qa_artefact_models import QaEvaluationRecord, QaFindingRecord

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid


def summary_from_record(record: QaEvaluationRecord) -> QaEvaluationSummary:
    """Map an evaluation record, without its findings, to the domain summary.

    Parameters
    ----------
    record : QaEvaluationRecord
        Stored evaluation row to map.

    Returns
    -------
    QaEvaluationSummary
        The domain summary, with the row's stored versions and verdict.

    Raises
    ------
    UnsupportedQaArtefactSchemaError
        If the row records a payload shape newer than this release reads.
    """
    if record.artefact_schema_version > QA_ARTEFACT_SCHEMA_VERSION:
        raise UnsupportedQaArtefactSchemaError(
            evaluation_id=record.id,
            episode_id=record.episode_id,
            stored_version=record.artefact_schema_version,
            supported_version=QA_ARTEFACT_SCHEMA_VERSION,
        )
    return QaEvaluationSummary(
        id=record.id,
        episode_id=record.episode_id,
        evaluator=record.evaluator,
        evaluator_version=record.evaluator_version,
        artefact_schema_version=record.artefact_schema_version,
        compliance_policy_version=record.compliance_policy_version,
        compliance_status=record.compliance_status,
        evaluated_at=record.evaluated_at,
        idempotency_key=record.idempotency_key,
        finding_count=record.finding_count,
        generation_run_id=record.generation_run_id,
        summary=record.summary,
        rubric_score=record.rubric_score,
        runtime_estimate_seconds=record.runtime_estimate_seconds,
        evaluator_metadata=record.evaluator_metadata,
        created_at=record.created_at,
    )


def finding_from_record(record: QaFindingRecord) -> QaFinding:
    """Map a finding record to the domain finding.

    Parameters
    ----------
    record : QaFindingRecord
        Stored finding row to map.

    Returns
    -------
    QaFinding
        The domain finding, with ``citations`` re-hydrated as a tuple.
    """
    return QaFinding(
        id=record.id,
        evaluation_id=record.evaluation_id,
        ordinal=record.ordinal,
        severity=record.severity,
        code=record.code,
        summary=record.summary,
        remediation=record.remediation,
        subject_id=record.subject_id,
        subject_text=record.subject_text,
        is_blocking=record.is_blocking,
        citations=tuple(record.citations),
        details=record.details,
    )


def finding_to_record(
    finding: QaFinding,
    *,
    evaluation_id: uuid.UUID,
) -> QaFindingRecord:
    """Map a domain finding to a storage record owned by ``evaluation_id``.

    Parameters
    ----------
    finding : QaFinding
        Domain finding to map.
    evaluation_id : uuid.UUID
        Identifier of the owning evaluation. It is passed explicitly because a
        superseded recording keeps the stored evaluation's identifier rather
        than the one the incoming artefact was built with.

    Returns
    -------
    QaFindingRecord
        The storage record, with ``citations`` flattened to a JSON list.
    """
    return QaFindingRecord(
        id=finding.id,
        evaluation_id=evaluation_id,
        ordinal=finding.ordinal,
        severity=finding.severity,
        code=finding.code,
        summary=finding.summary,
        remediation=finding.remediation,
        subject_id=finding.subject_id,
        subject_text=finding.subject_text,
        is_blocking=finding.is_blocking,
        citations=list(finding.citations),
        details=finding.details,
    )


def evaluation_to_record(
    evaluation: QaEvaluation,
    *,
    created_at: dt.datetime,
) -> QaEvaluationRecord:
    """Map a domain evaluation and its findings to a storage record.

    Parameters
    ----------
    evaluation : QaEvaluation
        Domain evaluation to map.
    created_at : dt.datetime
        Storage timestamp for the new row.

    Returns
    -------
    QaEvaluationRecord
        The parent record, carrying its findings in ordinal order.
    """
    summary = evaluation.summary_record
    record = QaEvaluationRecord(
        id=summary.id,
        episode_id=summary.episode_id,
        generation_run_id=summary.generation_run_id,
        evaluator=summary.evaluator,
        evaluator_version=summary.evaluator_version,
        artefact_schema_version=summary.artefact_schema_version,
        compliance_policy_version=summary.compliance_policy_version,
        compliance_status=summary.compliance_status,
        summary=summary.summary,
        rubric_score=summary.rubric_score,
        runtime_estimate_seconds=summary.runtime_estimate_seconds,
        finding_count=summary.finding_count,
        evaluator_metadata=summary.evaluator_metadata,
        idempotency_key=summary.idempotency_key,
        evaluated_at=summary.evaluated_at,
        created_at=created_at,
    )
    record.findings = [
        finding_to_record(finding, evaluation_id=summary.id)
        for finding in evaluation.findings
    ]
    return record


def evaluation_from_record(record: QaEvaluationRecord) -> QaEvaluation:
    """Map a record and its loaded findings to the domain evaluation.

    Parameters
    ----------
    record : QaEvaluationRecord
        Stored evaluation row whose ``findings`` collection is already loaded.

    Returns
    -------
    QaEvaluation
        The domain evaluation. Findings are re-ordered by ``ordinal`` so a row
        set that was not fetched in order still satisfies the aggregate's
        ordering contract.
    """
    # The summary's schema-version check runs first, so a row written by a
    # newer release reports its unsupported payload shape before any finding is
    # validated. Otherwise a field that release widened would raise
    # ``ValueError`` from here and surface as a 500 rather than the documented
    # 422.
    summary = summary_from_record(record)
    findings = tuple(
        finding_from_record(item)
        for item in sorted(record.findings, key=lambda item: item.ordinal)
    )
    return QaEvaluation(summary_record=summary, findings=findings)
