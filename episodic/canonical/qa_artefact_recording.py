"""Projections from evaluator results onto durable QA artefacts.

An evaluator returns its own result type, but the archive stores one shape for
every evaluator. This module owns that translation and nothing else: each
function is a pure projection that raises ``ValueError`` when the projected data
exceeds a bound the QA artefact types enforce, the compliance policy is a single
predicate over the Pedante finding set, and the idempotency key is a function of
exactly the inputs the store's uniqueness constraint depends on.

The projections are pure. They read no clock and no identifier generator other
than the one the caller supplies, which keeps ``INV-KEY-DETERMINISM`` a property
of the code rather than of its timing. Composing them with a unit of work is
:mod:`episodic.canonical.qa_artefact_service`'s job.
"""

import collections.abc as cabc
import typing as typ
import uuid

from episodic.qa.pedante.types import (
    PEDANTE_CONTRACT_VERSION,
    PedanteEvaluationResult,
    PedanteFinding,
)

from .qa_artefact_compliance import compliance_status_for_pedante
from .qa_artefacts import (
    QA_ARTEFACT_SCHEMA_VERSION,
    QA_COMPLIANCE_POLICY_VERSION,
    QaComplianceStatus,
    QaEvaluation,
    QaEvaluationSummary,
    QaEvaluator,
    QaFinding,
    QaFindingSeverity,
)

if typ.TYPE_CHECKING:
    import datetime as dt

    from episodic.qa.chrono import ChronoRuntimeEstimate

    from .domain_enums import JsonMapping

type UuidFactory = cabc.Callable[[], uuid.UUID]

_NO_GENERATION_RUN = "-"


# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # key is a function of the five pinned inputs
def qa_idempotency_key(  # ruff: ignore[too-many-arguments]
    *,
    evaluator: QaEvaluator,
    evaluator_version: str,
    compliance_policy_version: int,
    tei_content_hash: str,
    generation_run_id: uuid.UUID | None,
) -> str:
    """Build the key that makes a repeated recording a replay.

    The key names every input that changes the artefact's meaning, and nothing
    else. In particular it excludes the clock reading and the evaluator's model
    or provider, so re-running the same evaluator contract over unchanged TEI
    replays the stored artefact instead of duplicating it.

    Parameters
    ----------
    evaluator : QaEvaluator
        Evaluator that produced the artefact.
    evaluator_version : str
        Version of that evaluator's contract.
    compliance_policy_version : int
        Version of the policy that mapped findings to a verdict.
    tei_content_hash : str
        Content hash of the script the evaluation assessed.
    generation_run_id : uuid.UUID | None
        Launcher run that triggered the evaluation, when one exists. An absent
        run is spelled ``-`` so the key stays unambiguous.

    Returns
    -------
    str
        The key, for example
        ``qa:pedante:v1:policy:1:tei:abc123:run:-``.
    """
    run = _NO_GENERATION_RUN if generation_run_id is None else str(generation_run_id)
    return (
        f"qa:{evaluator.value}:v{evaluator_version}"
        f":policy:{compliance_policy_version}"
        f":tei:{tei_content_hash}:run:{run}"
    )


# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # one stamp for every pinned summary field
def _summary_record(  # ruff: ignore[too-many-arguments]
    *,
    evaluation_id: uuid.UUID,
    episode_id: uuid.UUID,
    evaluator: QaEvaluator,
    evaluator_version: str,
    compliance_status: QaComplianceStatus,
    evaluated_at: dt.datetime,
    tei_content_hash: str,
    generation_run_id: uuid.UUID | None,
    finding_count: int,
    summary: str = "",
    runtime_estimate_seconds: int | None = None,
    evaluator_metadata: JsonMapping | None = None,
) -> QaEvaluationSummary:
    """Stamp the payload and policy versions onto a summary.

    Every projection shares this constructor so the version fields and the key
    cannot drift apart per evaluator.

    Returns
    -------
    QaEvaluationSummary
        The summary with its versions, verdict, and derived key filled in.
    """
    return QaEvaluationSummary(
        id=evaluation_id,
        episode_id=episode_id,
        evaluator=evaluator,
        evaluator_version=evaluator_version,
        artefact_schema_version=QA_ARTEFACT_SCHEMA_VERSION,
        compliance_policy_version=QA_COMPLIANCE_POLICY_VERSION,
        compliance_status=compliance_status,
        evaluated_at=evaluated_at,
        idempotency_key=qa_idempotency_key(
            evaluator=evaluator,
            evaluator_version=evaluator_version,
            compliance_policy_version=QA_COMPLIANCE_POLICY_VERSION,
            tei_content_hash=tei_content_hash,
            generation_run_id=generation_run_id,
        ),
        finding_count=finding_count,
        generation_run_id=generation_run_id,
        summary=summary,
        runtime_estimate_seconds=runtime_estimate_seconds,
        evaluator_metadata={} if evaluator_metadata is None else evaluator_metadata,
    )


def _finding_from_pedante(
    finding: PedanteFinding,
    *,
    evaluation_id: uuid.UUID,
    ordinal: int,
) -> QaFinding:
    """Project one Pedante finding onto its QA finding."""
    return QaFinding(
        # Derived rather than random so the projection stays a pure function of
        # its inputs; the store keys findings by (evaluation_id, ordinal) anyway.
        id=uuid.uuid5(evaluation_id, str(ordinal)),
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


# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # the plan pins this keyword interface
def evaluation_from_pedante(  # ruff: ignore[too-many-arguments]
    result: PedanteEvaluationResult,
    *,
    episode_id: uuid.UUID,
    tei_content_hash: str,
    evaluated_at: dt.datetime,
    generation_run_id: uuid.UUID | None = None,
    uuid_factory: UuidFactory = uuid.uuid7,
) -> QaEvaluation:
    """Map a Pedante result onto a persistable evaluation.

    Findings keep the order Pedante emitted them, so ordinals are stable
    across replays and a reviewer sees the same sequence the evaluator saw.

    Parameters
    ----------
    result : PedanteEvaluationResult
        Typed Pedante findings plus its provider metadata.
    episode_id : uuid.UUID
        Canonical episode the evaluation applies to.
    tei_content_hash : str
        Content hash of the script Pedante assessed.
    evaluated_at : dt.datetime
        Timezone-aware instant of the evaluation.
    generation_run_id : uuid.UUID | None
        Launcher run that triggered the evaluation, when one exists.
    uuid_factory : UuidFactory
        Source of the evaluation identifier; injectable for deterministic
        tests.

    Returns
    -------
    QaEvaluation
        The mapped evaluation with ``finding_count`` equal to its findings.

    Raises
    ------
    ValueError
        If the result exceeds a bound declared in
        :mod:`episodic.canonical.qa_artefacts`: a summary longer than
        :data:`~episodic.canonical.qa_artefacts.MAX_SUMMARY_CHARS`, a finding
        field beyond its own limit, or more than
        :data:`~episodic.canonical.qa_artefacts.MAX_FINDINGS_PER_EVALUATION`
        findings. The projection never truncates, so a caller that meets this
        failure records it with :func:`evaluation_from_failure` rather than
        storing a shortened artefact.

    Examples
    --------
    >>> import datetime as dt
    >>> import uuid
    >>> from episodic.llm import LLMUsage
    >>> result = PedanteEvaluationResult("Done.", (), LLMUsage(1, 1, 2))
    >>> evaluation = evaluation_from_pedante(
    ...     result,
    ...     episode_id=uuid.uuid7(),
    ...     tei_content_hash="sha256:0",
    ...     evaluated_at=dt.datetime.now(dt.UTC),
    ... )
    >>> evaluation.summary_record.compliance_status.value
    'compliant'
    """  # ruff: ignore[docstring-extraneous-exception]  # QaEvaluation validates the mapped fields here.
    evaluation_id = uuid_factory()
    return QaEvaluation(
        summary_record=_summary_record(
            evaluation_id=evaluation_id,
            episode_id=episode_id,
            evaluator=QaEvaluator.PEDANTE,
            evaluator_version=PEDANTE_CONTRACT_VERSION,
            compliance_status=compliance_status_for_pedante(result),
            evaluated_at=evaluated_at,
            tei_content_hash=tei_content_hash,
            generation_run_id=generation_run_id,
            finding_count=len(result.findings),
            summary=result.summary,
            evaluator_metadata={
                "model": result.model,
                "provider_response_id": result.provider_response_id,
                "finish_reason": result.finish_reason,
            },
        ),
        findings=tuple(
            _finding_from_pedante(
                finding,
                evaluation_id=evaluation_id,
                ordinal=ordinal,
            )
            for ordinal, finding in enumerate(result.findings)
        ),
    )


# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # the plan pins this keyword interface
def evaluation_from_chrono(  # ruff: ignore[too-many-arguments]
    estimate: ChronoRuntimeEstimate,
    *,
    episode_id: uuid.UUID,
    tei_content_hash: str,
    evaluated_at: dt.datetime,
    generation_run_id: uuid.UUID | None = None,
    uuid_factory: UuidFactory = uuid.uuid7,
) -> QaEvaluation:
    """Map a Chrono runtime estimate onto a persistable evaluation.

    Chrono measures duration rather than correctness, so its artefact carries
    ``NOT_APPLICABLE``: recording it must never read as an approval. The whole
    estimator metadata block is kept because a later reader needs to know which
    heuristic produced the number.

    Parameters
    ----------
    estimate : ChronoRuntimeEstimate
        Estimated seconds plus the metadata that makes estimates comparable.
    episode_id : uuid.UUID
        Canonical episode the evaluation applies to.
    tei_content_hash : str
        Content hash of the script Chrono measured.
    evaluated_at : dt.datetime
        Timezone-aware instant of the evaluation.
    generation_run_id : uuid.UUID | None
        Launcher run that triggered the evaluation, when one exists.
    uuid_factory : UuidFactory
        Source of the evaluation identifier; injectable for deterministic
        tests.

    Returns
    -------
    QaEvaluation
        The mapped evaluation, carrying no findings.
    """
    metadata = estimate.metadata
    return QaEvaluation(
        summary_record=_summary_record(
            evaluation_id=uuid_factory(),
            episode_id=episode_id,
            evaluator=QaEvaluator.CHRONO,
            evaluator_version=metadata.estimator_version,
            compliance_status=QaComplianceStatus.NOT_APPLICABLE,
            evaluated_at=evaluated_at,
            tei_content_hash=tei_content_hash,
            generation_run_id=generation_run_id,
            finding_count=0,
            runtime_estimate_seconds=estimate.estimated_seconds,
            evaluator_metadata={
                "estimator_name": metadata.estimator_name,
                "estimator_version": metadata.estimator_version,
                "input_character_count": metadata.input_character_count,
                "spoken_word_count": metadata.spoken_word_count,
                "words_per_minute": metadata.words_per_minute,
            },
        )
    )


# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # the plan pins this keyword interface
def evaluation_from_failure(  # ruff: ignore[too-many-arguments]
    evaluator: QaEvaluator,
    *,
    episode_id: uuid.UUID,
    evaluator_version: str,
    tei_content_hash: str,
    error_category: str,
    summary: str,
    evaluated_at: dt.datetime,
    generation_run_id: uuid.UUID | None = None,
    uuid_factory: UuidFactory = uuid.uuid7,
) -> QaEvaluation:
    """Map a failed evaluator invocation onto a persistable evaluation.

    A failure is recorded rather than dropped so the archive shows that the
    episode was assessed. It shares the key a later success would produce, so
    the retry supersedes this artefact in place instead of leaving two records
    for one evaluation.

    Parameters
    ----------
    evaluator : QaEvaluator
        Evaluator that failed.
    episode_id : uuid.UUID
        Canonical episode the evaluation applies to.
    evaluator_version : str
        Version of the contract the evaluator attempted.
    tei_content_hash : str
        Content hash of the script the evaluator was given.
    error_category : str
        Bounded category, safe to aggregate, describing why it failed.
    summary : str
        Human-readable account of the failure.
    evaluated_at : dt.datetime
        Timezone-aware instant of the attempt.
    generation_run_id : uuid.UUID | None
        Launcher run that triggered the evaluation, when one exists.
    uuid_factory : UuidFactory
        Source of the evaluation identifier; injectable for deterministic
        tests.

    Returns
    -------
    QaEvaluation
        The mapped evaluation with ``ERRORED`` and no findings.
    """
    return QaEvaluation(
        summary_record=_summary_record(
            evaluation_id=uuid_factory(),
            episode_id=episode_id,
            evaluator=evaluator,
            evaluator_version=evaluator_version,
            compliance_status=QaComplianceStatus.ERRORED,
            evaluated_at=evaluated_at,
            tei_content_hash=tei_content_hash,
            generation_run_id=generation_run_id,
            finding_count=0,
            summary=summary,
            evaluator_metadata={"error_category": error_category},
        )
    )
