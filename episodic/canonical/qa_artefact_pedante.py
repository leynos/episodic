"""Project a Pedante evaluation result onto a durable QA artefact.

Pedante is the only evaluator that contributes findings, so its projection owns
the field-by-field mapping from Pedante's finding shape onto the archive's. The
other projections, which carry no findings, stay in
:mod:`episodic.canonical.qa_artefact_recording`.
"""

import typing as typ

from episodic.qa.pedante.types import (
    PEDANTE_CONTRACT_VERSION,
    PedanteEvaluationResult,
    PedanteFinding,
)

from .qa_artefact_compliance import compliance_status_for_pedante
from .qa_artefact_recording import (
    QaEvaluationTarget,
    QaSummaryDraft,
    UuidFactory,
)
from .qa_artefacts import (
    QaEvaluation,
    QaEvaluator,
    QaFinding,
    QaFindingSeverity,
)

if typ.TYPE_CHECKING:
    import uuid


def _finding_from_pedante(
    finding: PedanteFinding,
    *,
    evaluation_id: uuid.UUID,
    ordinal: int,
    uuid_factory: UuidFactory,
) -> QaFinding:
    """Project one Pedante finding onto its QA finding."""
    return QaFinding(
        # Application-side UUIDv7, like every other primary key in this store.
        id=uuid_factory(),
        evaluation_id=evaluation_id,
        ordinal=ordinal,
        severity=QaFindingSeverity(finding.severity.value),
        code=finding.support_level.value,
        summary=finding.summary,
        remediation=finding.remediation,
        subject_id=finding.claim_id,
        subject_text=finding.claim_text,
        is_blocking=finding.is_blocking,
        citations=finding.cited_source_ids,
        details={"claim_kind": finding.claim_kind.value},
    )


def _pedante_draft(result: PedanteEvaluationResult) -> QaSummaryDraft:
    """Return the evaluator-contributed fields for a Pedante result."""
    return QaSummaryDraft(
        evaluator=QaEvaluator.PEDANTE,
        evaluator_version=PEDANTE_CONTRACT_VERSION,
        compliance_status=compliance_status_for_pedante(result),
        finding_count=len(result.findings),
        summary=result.summary,
        evaluator_metadata={
            "model": result.model,
            "provider_response_id": result.provider_response_id,
            "finish_reason": result.finish_reason,
        },
    )


def evaluation_from_pedante(
    result: PedanteEvaluationResult,
    *,
    target: QaEvaluationTarget,
) -> QaEvaluation:
    """Map a Pedante result onto a persistable evaluation.

    Findings keep Pedante's emission order, so ordinals are stable on replay.

    Parameters
    ----------
    result : PedanteEvaluationResult
        Typed Pedante findings plus its provider metadata.
    target : QaEvaluationTarget
        Episode, script hash, timestamp, launcher run, and identifier factory.

    Returns
    -------
    QaEvaluation
        The mapped evaluation with ``finding_count`` equal to its findings.

    Raises
    ------
    ValueError
        If the result exceeds a bound declared in
        :mod:`episodic.canonical.qa_artefacts`. The projection never truncates,
        so a caller that meets this failure records it with
        :func:`episodic.canonical.qa_artefact_recording.evaluation_from_failure`
        instead.

    Examples
    --------
    >>> import datetime as dt, uuid
    >>> from episodic.llm import LLMUsage
    >>> result = PedanteEvaluationResult("Done.", (), LLMUsage(1, 1, 2))
    >>> target = QaEvaluationTarget(
    ...     uuid.uuid7(), "sha256:0", dt.datetime.now(dt.UTC)
    ... )
    >>> evaluation = evaluation_from_pedante(result, target=target)
    >>> evaluation.summary_record.compliance_status.value
    'compliant'
    """  # ruff: ignore[docstring-extraneous-exception]  # QaEvaluation validates the mapped fields here.
    evaluation_id = target.uuid_factory()
    return QaEvaluation(
        summary_record=_pedante_draft(result).stamp(
            evaluation_id=evaluation_id,
            target=target,
        ),
        findings=tuple(
            _finding_from_pedante(
                finding,
                evaluation_id=evaluation_id,
                ordinal=ordinal,
                uuid_factory=target.uuid_factory,
            )
            for ordinal, finding in enumerate(result.findings)
        ),
    )
