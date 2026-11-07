"""Application services for recording and querying QA artefacts.

Both write entry points are available services now, because callers own
different transaction boundaries. A caller that already holds a unit of work
uses :func:`record_qa_evaluation`, which composes into that transaction and
leaves the commit to its owner. A caller that owns no transaction uses
:class:`QaEvaluationRecorder`, which opens the unit of work, stamps the
evaluation time from its injected clock, and commits exactly once.

Nothing outside this module calls either entry point yet: the QA-gated run path
that will is roadmap item 4.4.1, and the CLI and REST surfaces are
retrieval-only today. Naming that split keeps the recording services from
reading as an already-wired pipeline.

Both routes share :mod:`episodic.canonical.qa_artefact_recording` for the
mapping, so the idempotency key and the compliance verdict cannot differ
between them.
"""

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

from episodic.qa.chrono import ChronoRuntimeEstimate
from episodic.qa.pedante.types import PedanteEvaluationResult

from .qa_artefact_pedante import evaluation_from_pedante
from .qa_artefact_recording import (
    QaEvaluationTarget,
    QaEvaluatorFailure,
    UuidFactory,
    evaluation_from_chrono,
    evaluation_from_failure,
)

if typ.TYPE_CHECKING:
    from .qa_artefact_ports import QaEvaluationListRequest
    from .qa_artefacts import QaEvaluation, QaEvaluationSummary
    from .unit_of_work_protocols import CanonicalUnitOfWork

type Clock = cabc.Callable[[], dt.datetime]


def _utc_now() -> dt.datetime:
    """Return the current timezone-aware UTC timestamp."""
    return dt.datetime.now(dt.UTC)


type QaEvaluationOutcome = (
    PedanteEvaluationResult | ChronoRuntimeEstimate | QaEvaluatorFailure
)


@dc.dataclass(frozen=True, slots=True)
class QaEvaluationRecordingRequest:
    """One fully specified request to record an evaluation.

    The field set is deliberately wider than any single evaluator's result: it
    carries the episode, the script identity, and the timestamp, which belong to
    the invocation rather than to the result.

    Attributes
    ----------
    episode_id : uuid.UUID
        Canonical episode the evaluation applies to.
    tei_content_hash : str
        Content hash of the script that was assessed.
    evaluated_at : dt.datetime
        Timezone-aware instant of the evaluation.
    outcome : QaEvaluationOutcome
        Evaluator result, or the failure that replaced it.
    generation_run_id : uuid.UUID | None
        Launcher run that triggered the evaluation, when one exists.
    uuid_factory : UuidFactory
        Source of the evaluation identifier; injectable for deterministic
        tests.
    """

    episode_id: uuid.UUID
    tei_content_hash: str
    evaluated_at: dt.datetime
    outcome: QaEvaluationOutcome
    generation_run_id: uuid.UUID | None = None
    uuid_factory: UuidFactory = uuid.uuid7


def _evaluation_for(request: QaEvaluationRecordingRequest) -> QaEvaluation:
    """Map a request's outcome onto the artefact to persist."""
    target = QaEvaluationTarget(
        episode_id=request.episode_id,
        tei_content_hash=request.tei_content_hash,
        evaluated_at=request.evaluated_at,
        generation_run_id=request.generation_run_id,
        uuid_factory=request.uuid_factory,
    )
    match request.outcome:
        case QaEvaluatorFailure() as failure:
            return evaluation_from_failure(failure, target=target)
        case ChronoRuntimeEstimate() as estimate:
            return evaluation_from_chrono(estimate, target=target)
        case PedanteEvaluationResult() as result:
            return evaluation_from_pedante(result, target=target)
        case _:
            outcome_type = type(request.outcome).__name__
            msg = f"Unsupported QA evaluation outcome: {outcome_type}."
            raise TypeError(msg)


async def record_qa_evaluation(
    uow: CanonicalUnitOfWork,
    request: QaEvaluationRecordingRequest,
) -> QaEvaluation:
    """Record one evaluation inside the caller's transaction.

    Use this when the evaluation is part of a larger unit of work, such as a
    launcher run that must commit the evaluation with its other effects. The
    caller commits; this function never does.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit of work whose ``qa_artefacts`` repository receives the artefact.
    request : QaEvaluationRecordingRequest
        Episode, script identity, timestamp, and evaluator outcome.

    Returns
    -------
    QaEvaluation
        The stored artefact, with its findings in ordinal order.
    """
    return await uow.qa_artefacts.record_evaluation(_evaluation_for(request))


async def get_qa_evaluation(
    uow: CanonicalUnitOfWork,
    evaluation_id: uuid.UUID,
) -> QaEvaluation | None:
    """Return one evaluation with its findings, or ``None``.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit of work to read through.
    evaluation_id : uuid.UUID
        Identifier of the evaluation to load.

    Returns
    -------
    QaEvaluation | None
        The stored artefact when it exists, otherwise ``None``.
    """
    return await uow.qa_artefacts.get_evaluation(evaluation_id)


async def list_qa_evaluations(
    uow: CanonicalUnitOfWork,
    request: QaEvaluationListRequest,
) -> tuple[list[QaEvaluationSummary], int]:
    """Return one filtered page of evaluation summaries and the total.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit of work to read through.
    request : QaEvaluationListRequest
        Episode scope, optional filters, and the requested page.

    Returns
    -------
    tuple[list[QaEvaluationSummary], int]
        The summaries on the requested page, and the unpaged total.
    """
    return await uow.qa_artefacts.list_evaluations(request)


@dc.dataclass(frozen=True, slots=True)
class QaEvaluationRecorder:
    """Application service that records one evaluation per call.

    It owns the unit of work, so it commits. Callers that are already in a
    transaction should use :func:`record_qa_evaluation` instead; both produce
    the same artefact for the same outcome.

    Attributes
    ----------
    uow_factory : cabc.Callable[[], CanonicalUnitOfWork]
        Opens the unit of work the recording is committed through.
    clock : Clock
        Source of ``evaluated_at``. Injecting it keeps replay tests independent
        of the wall clock.
    uuid_factory : UuidFactory
        Source of the evaluation identifier; injectable for deterministic
        tests.
    """

    uow_factory: cabc.Callable[[], CanonicalUnitOfWork]
    clock: Clock = _utc_now
    uuid_factory: UuidFactory = uuid.uuid7

    async def record(
        self,
        *,
        episode_id: uuid.UUID,
        tei_content_hash: str,
        outcome: QaEvaluationOutcome,
        generation_run_id: uuid.UUID | None = None,
    ) -> QaEvaluation:
        """Record one evaluator outcome in its own committed transaction.

        Parameters
        ----------
        episode_id : uuid.UUID
            Canonical episode the evaluation applies to.
        tei_content_hash : str
            Content hash of the script that was assessed.
        outcome : QaEvaluationOutcome
            Evaluator result, or the failure that replaced it.
        generation_run_id : uuid.UUID | None
            Launcher run that triggered the evaluation, when one exists.

        Returns
        -------
        QaEvaluation
            The stored artefact, with its findings in ordinal order.
        """
        request = QaEvaluationRecordingRequest(
            episode_id=episode_id,
            tei_content_hash=tei_content_hash,
            evaluated_at=self.clock(),
            outcome=outcome,
            generation_run_id=generation_run_id,
            uuid_factory=self.uuid_factory,
        )
        async with self.uow_factory() as uow:
            recorded = await record_qa_evaluation(uow, request)
            await uow.commit()
        return recorded
