"""Builders shared by the QA artefact domain test modules.

Both the model suite and the rubric-score suite need a valid artefact to
mutate, so the identifiers and builders live here rather than in either test
module.
"""

import datetime as dt
import typing as typ
import uuid

from episodic.canonical.qa_artefacts import (
    QA_ARTEFACT_SCHEMA_VERSION,
    QA_COMPLIANCE_POLICY_VERSION,
    QaComplianceStatus,
    QaEvaluationSummary,
    QaEvaluator,
    QaFinding,
    QaFindingSeverity,
)
from episodic.qa.pedante.types import SupportLevel

if typ.TYPE_CHECKING:
    import decimal

    from episodic.canonical.domain_enums import JsonMapping

# Authored from the Pedante taxonomy and the recorded compliance policy. It is
# deliberately not derived from the production `_BLOCKING_SUPPORT_LEVELS`; the
# exact-equality test in `tests/test_qa_artefact_domain.py` turns the pair into
# a transcription check, and the recording properties use this set as their
# oracle so a wrong production set cannot satisfy them.
DOCUMENTED_BLOCKING_LEVELS = frozenset({
    SupportLevel.CITATION_ABSENT,
    SupportLevel.MISQUOTATION,
    SupportLevel.MISINTERPRETED_CLAIM,
    SupportLevel.FABRICATED_CLAIM,
    SupportLevel.INFERENCE_NOT_SUPPORTED,
    SupportLevel.INACCURATE_REINTERPRETATION,
    SupportLevel.INFERENCE_SUPPORTED_WITH_IRRELEVANT_SOURCES,
    SupportLevel.CONTRADICTORY_CLAIMS_IN_DOCUMENT,
})

EPISODE_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e901")
EVALUATION_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e902")
FINDING_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e903")
OTHER_FINDING_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e904")
OTHER_EVALUATION_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e905")
EVALUATED_AT = dt.datetime(2026, 10, 29, 12, 0, 0, tzinfo=dt.UTC)


# pylint: disable-next=too-many-arguments  # mirrors QaFinding's field surface
def finding(
    *,
    finding_id: uuid.UUID = FINDING_ID,
    evaluation_id: uuid.UUID = EVALUATION_ID,
    ordinal: int = 0,
    severity: QaFindingSeverity = QaFindingSeverity.LOW,
    code: str = "citation_absent",
    summary: str = "Claim is unsupported.",
    remediation: str = "",
    subject_id: str = "",
    subject_text: str = "",
    is_blocking: bool = False,
    citations: tuple[str, ...] = (),
    details: JsonMapping | None = None,
) -> QaFinding:
    """Return a valid finding whose fields callers may override.

    Parameters
    ----------
    finding_id : uuid.UUID
        Identifier to give the finding.
    evaluation_id : uuid.UUID
        Identifier of the evaluation the finding claims to belong to.
    ordinal : int
        Position of the finding within its evaluation.
    severity : QaFindingSeverity
        Severity to record.
    code : str
        Machine-readable finding code.
    summary : str
        Human-readable description of the problem.
    remediation : str
        Optional suggested remedy.
    subject_id : str
        Optional identifier of the claim, sentence, or segment assessed.
    subject_text : str
        Optional quoted subject text.
    is_blocking : bool
        Whether the finding blocks the episode from advancing.
    citations : tuple[str, ...]
        Source identifiers supporting the finding.
    details : JsonMapping | None
        Evaluator-specific payload; ``None`` becomes an empty mapping.

    Returns
    -------
    QaFinding
        The constructed finding.
    """
    return QaFinding(
        id=finding_id,
        evaluation_id=evaluation_id,
        ordinal=ordinal,
        severity=severity,
        code=code,
        summary=summary,
        remediation=remediation,
        subject_id=subject_id,
        subject_text=subject_text,
        is_blocking=is_blocking,
        citations=citations,
        details={} if details is None else details,
    )


# pylint: disable-next=too-many-arguments  # mirrors the summary's field surface
def summary(
    *,
    evaluation_id: uuid.UUID = EVALUATION_ID,
    episode_id: uuid.UUID = EPISODE_ID,
    evaluator: QaEvaluator = QaEvaluator.PEDANTE,
    evaluator_version: str = "pedante-1.0.0",
    artefact_schema_version: int = QA_ARTEFACT_SCHEMA_VERSION,
    compliance_policy_version: int = QA_COMPLIANCE_POLICY_VERSION,
    compliance_status: QaComplianceStatus = QaComplianceStatus.COMPLIANT,
    evaluated_at: dt.datetime = EVALUATED_AT,
    idempotency_key: str = "pedante:episode:1",
    finding_count: int = 0,
    generation_run_id: uuid.UUID | None = None,
    summary: str = "",
    rubric_score: decimal.Decimal | None = None,
    runtime_estimate_seconds: int | None = None,
    evaluator_metadata: JsonMapping | None = None,
    created_at: dt.datetime | None = None,
) -> QaEvaluationSummary:
    """Return a valid evaluation summary whose fields callers may override.

    Parameters
    ----------
    evaluation_id : uuid.UUID
        Identifier to give the evaluation.
    episode_id : uuid.UUID
        Canonical episode the evaluation applies to.
    evaluator : QaEvaluator
        Evaluator that produced the artefact.
    evaluator_version : str
        Version of the evaluator's contract.
    artefact_schema_version : int
        Payload schema version to record.
    compliance_policy_version : int
        Compliance policy version to record.
    compliance_status : QaComplianceStatus
        Verdict to record.
    evaluated_at : dt.datetime
        Timezone-aware instant at which the evaluator ran.
    idempotency_key : str
        Key that makes a repeated recording replay this artefact.
    finding_count : int
        Number of findings the evaluation claims to carry.
    generation_run_id : uuid.UUID | None
        Optional launcher run that triggered the evaluation.
    summary : str
        Optional human-readable verdict.
    rubric_score : decimal.Decimal | None
        Optional unit-interval score.
    runtime_estimate_seconds : int | None
        Optional runtime estimate.
    evaluator_metadata : JsonMapping | None
        Evaluator-specific payload; ``None`` becomes an empty mapping.
    created_at : dt.datetime | None
        Optional storage time; ``None`` leaves the artefact unrecorded.

    Returns
    -------
    QaEvaluationSummary
        The constructed summary, with current policy versions stamped.
    """
    return QaEvaluationSummary(
        id=evaluation_id,
        episode_id=episode_id,
        evaluator=evaluator,
        evaluator_version=evaluator_version,
        artefact_schema_version=artefact_schema_version,
        compliance_policy_version=compliance_policy_version,
        compliance_status=compliance_status,
        evaluated_at=evaluated_at,
        idempotency_key=idempotency_key,
        finding_count=finding_count,
        generation_run_id=generation_run_id,
        summary=summary,
        rubric_score=rubric_score,
        runtime_estimate_seconds=runtime_estimate_seconds,
        evaluator_metadata={} if evaluator_metadata is None else evaluator_metadata,
        created_at=created_at,
    )
