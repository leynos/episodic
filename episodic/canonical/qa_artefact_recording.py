"""Projections from evaluator results onto durable QA artefacts.

An evaluator returns its own result type, but the archive stores one shape for
every evaluator. Each function is pure: it reads no clock or identifier
generator other than the caller's, and raises ``ValueError`` rather than
truncating when projected data exceeds a bound. Composing the projections with
a unit of work is :mod:`episodic.canonical.qa_artefact_service`'s job.

The Pedante projection, which is the only one that contributes findings, lives
in :mod:`episodic.canonical.qa_artefact_pedante`.
"""

import collections.abc as cabc
import dataclasses as dc
import typing as typ
import uuid

from .qa_artefacts import (
    QA_ARTEFACT_SCHEMA_VERSION,
    QA_COMPLIANCE_POLICY_VERSION,
    QaComplianceStatus,
    QaEvaluation,
    QaEvaluationSummary,
    QaEvaluator,
)

if typ.TYPE_CHECKING:
    import datetime as dt

    from episodic.qa.chrono import ChronoRuntimeEstimate

    from .domain_enums import JsonMapping

type UuidFactory = cabc.Callable[[], uuid.UUID]

_NO_GENERATION_RUN = "-"


@dc.dataclass(frozen=True, slots=True)
class QaEvaluationTarget:
    """Invocation context that every projection stamps onto its artefact.

    Attributes
    ----------
    episode_id : uuid.UUID
        Canonical episode the evaluation applies to.
    tei_content_hash : str
        Content hash of the script that was assessed.
    evaluated_at : dt.datetime
        Timezone-aware instant of the evaluation.
    generation_run_id : uuid.UUID | None
        Launcher run that triggered the evaluation, when one exists.
    uuid_factory : UuidFactory
        Source of the evaluation identifier; injectable for tests.
    """

    episode_id: uuid.UUID
    tei_content_hash: str
    evaluated_at: dt.datetime
    generation_run_id: uuid.UUID | None = None
    uuid_factory: UuidFactory = uuid.uuid7


@dc.dataclass(frozen=True, slots=True)
class QaIdempotencyKeyInputs:
    """The five inputs the idempotency key is a function of.

    Attributes
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
        Launcher run that triggered the evaluation, when one exists.
    """

    evaluator: QaEvaluator
    evaluator_version: str
    compliance_policy_version: int
    tei_content_hash: str
    generation_run_id: uuid.UUID | None


def qa_idempotency_key(inputs: QaIdempotencyKeyInputs) -> str:
    """Build the key that makes a repeated recording a replay.

    It names every input that changes the artefact's meaning, and no others.

    Parameters
    ----------
    inputs : QaIdempotencyKeyInputs
        Evaluator, versions, script hash, and launcher run that decide the key.

    Returns
    -------
    str
        The key, for example ``qa:pedante:v1:policy:1:tei:abc123:run:-``.

    Examples
    --------
    >>> inputs = QaIdempotencyKeyInputs(
    ...     evaluator=QaEvaluator.PEDANTE,
    ...     evaluator_version="1",
    ...     compliance_policy_version=1,
    ...     tei_content_hash="abc123",
    ...     generation_run_id=None,
    ... )
    >>> qa_idempotency_key(inputs)
    'qa:pedante:v1:policy:1:tei:abc123:run:-'
    """
    run = (
        _NO_GENERATION_RUN
        if inputs.generation_run_id is None
        else str(inputs.generation_run_id)
    )
    return (
        f"qa:{inputs.evaluator.value}:v{inputs.evaluator_version}"
        f":policy:{inputs.compliance_policy_version}"
        f":tei:{inputs.tei_content_hash}:run:{run}"
    )


@dc.dataclass(frozen=True, slots=True)
class QaSummaryDraft:
    """Evaluator-contributed summary fields awaiting invocation stamping.

    Attributes
    ----------
    evaluator : QaEvaluator
        Evaluator that produced the verdict.
    evaluator_version : str
        Version of the evaluator's rules, recorded with the artefact.
    compliance_status : QaComplianceStatus
        Verdict the evaluator reached.
    finding_count : int
        Number of findings the evaluator reported.
    summary : str
        Human-readable summary; empty when the evaluator supplies none.
    runtime_estimate_seconds : int | None
        Evaluator's estimate of the run time, when it reports one.
    evaluator_metadata : JsonMapping | None
        Evaluator-specific payload; ``None`` selects an empty mapping when the
        summary is stamped.
    """

    evaluator: QaEvaluator
    evaluator_version: str
    compliance_status: QaComplianceStatus
    finding_count: int
    summary: str = ""
    runtime_estimate_seconds: int | None = None
    evaluator_metadata: JsonMapping | None = None

    def stamp(
        self, *, evaluation_id: uuid.UUID, target: QaEvaluationTarget
    ) -> QaEvaluationSummary:
        """Stamp the invocation identity, versions, and derived key.

        Parameters
        ----------
        evaluation_id : uuid.UUID
            Identifier the caller allocated for this evaluation.
        target : QaEvaluationTarget
            Episode, script hash, timestamp, and launcher run of the invocation.

        Returns
        -------
        QaEvaluationSummary
            The summary with its versions, verdict, and derived key filled in.
        """
        return QaEvaluationSummary(
            id=evaluation_id,
            episode_id=target.episode_id,
            evaluator=self.evaluator,
            evaluator_version=self.evaluator_version,
            artefact_schema_version=QA_ARTEFACT_SCHEMA_VERSION,
            compliance_policy_version=QA_COMPLIANCE_POLICY_VERSION,
            compliance_status=self.compliance_status,
            evaluated_at=target.evaluated_at,
            idempotency_key=qa_idempotency_key(
                QaIdempotencyKeyInputs(
                    evaluator=self.evaluator,
                    evaluator_version=self.evaluator_version,
                    compliance_policy_version=QA_COMPLIANCE_POLICY_VERSION,
                    tei_content_hash=target.tei_content_hash,
                    generation_run_id=target.generation_run_id,
                )
            ),
            finding_count=self.finding_count,
            generation_run_id=target.generation_run_id,
            summary=self.summary,
            runtime_estimate_seconds=self.runtime_estimate_seconds,
            evaluator_metadata=(
                {} if self.evaluator_metadata is None else self.evaluator_metadata
            ),
        )


@dc.dataclass(frozen=True, slots=True)
class QaEvaluatorFailure:
    """An evaluator invocation that produced no result.

    Attributes
    ----------
    evaluator : QaEvaluator
        Evaluator that failed.
    evaluator_version : str
        Version of the contract the evaluator attempted.
    error_category : str
        Bounded category, safe to aggregate, describing why it failed.
    summary : str
        Human-readable account of the failure.
    """

    evaluator: QaEvaluator
    evaluator_version: str
    error_category: str
    summary: str


def evaluation_from_chrono(
    estimate: ChronoRuntimeEstimate,
    *,
    target: QaEvaluationTarget,
) -> QaEvaluation:
    """Map a Chrono runtime estimate onto a persistable evaluation.

    Chrono measures duration, so its artefact carries ``NOT_APPLICABLE``.

    Parameters
    ----------
    estimate : ChronoRuntimeEstimate
        Estimated seconds plus the metadata that makes estimates comparable.
    target : QaEvaluationTarget
        Episode, script hash, timestamp, launcher run, and identifier factory.

    Returns
    -------
    QaEvaluation
        The mapped evaluation, carrying no findings.
    """
    metadata = estimate.metadata
    return QaEvaluation(
        summary_record=QaSummaryDraft(
            evaluator=QaEvaluator.CHRONO,
            evaluator_version=metadata.estimator_version,
            compliance_status=QaComplianceStatus.NOT_APPLICABLE,
            finding_count=0,
            runtime_estimate_seconds=estimate.estimated_seconds,
            evaluator_metadata={
                "estimator_name": metadata.estimator_name,
                "estimator_version": metadata.estimator_version,
                "input_character_count": metadata.input_character_count,
                "spoken_word_count": metadata.spoken_word_count,
                "words_per_minute": metadata.words_per_minute,
            },
        ).stamp(
            evaluation_id=target.uuid_factory(),
            target=target,
        )
    )


def evaluation_from_failure(
    failure: QaEvaluatorFailure,
    *,
    target: QaEvaluationTarget,
) -> QaEvaluation:
    """Map a failed evaluator invocation onto a persistable evaluation.

    A failure is recorded rather than dropped so the archive shows the episode
    was assessed; it shares the key a later success would produce.

    Parameters
    ----------
    failure : QaEvaluatorFailure
        Evaluator, attempted contract version, error category, and explanation.
    target : QaEvaluationTarget
        Episode, script hash, timestamp, launcher run, and identifier factory.

    Returns
    -------
    QaEvaluation
        The mapped evaluation with ``ERRORED`` and no findings.
    """
    return QaEvaluation(
        summary_record=QaSummaryDraft(
            evaluator=failure.evaluator,
            evaluator_version=failure.evaluator_version,
            compliance_status=QaComplianceStatus.ERRORED,
            finding_count=0,
            summary=failure.summary,
            evaluator_metadata={"error_category": failure.error_category},
        ).stamp(
            evaluation_id=target.uuid_factory(),
            target=target,
        )
    )
