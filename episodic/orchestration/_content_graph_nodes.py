"""Framework-free node functions for the content-generation graph.

Every function takes the graph state and the per-run context and returns a
state delta. None imports LangGraph: the builder wraps these functions in
closures that supply ``runtime.context``, which keeps framework mechanics out
of node functions (ADR-022) and lets tests drive them directly.

Evaluators run one at a time under their configured timeout. An evaluator
error, timeout, or self-raised ``CancelledError`` becomes an inconclusive
result with an error classification, so a QA outage is distinguishable from a
verdict and can never pass a draft. A genuine cancellation is re-raised.
"""

import asyncio

from episodic.canonical.generation_graph_ports import (
    EvaluationSubject,
    QualityEvaluation,
    QualityEvaluationUnavailableError,
    QualityEvaluatorPort,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_routing import (
    EvaluationRoute,
    GenerationTerminal,
    QualityBranch,
    QualityVerdict,
    aggregate_verdicts,
    route_after_evaluation,
    route_quality_mode,
)
from episodic.logging import get_logger, log_error
from episodic.orchestration._content_graph_state import (  # ruff: ignore[typing-only-first-party-import]  # Node signatures are evaluated at import time.
    ContentGenerationContext,
    ContentGenerationGraphState,
)

type NodeResult = dict[str, object]

logger = get_logger(__name__)

_TIMEOUT_ERROR = "timeout"
_CANCELLED_ERROR = "cancelled"


def _require_verdict(state: ContentGenerationGraphState) -> QualityVerdict:
    """Return the aggregate verdict, which ``evaluate`` always sets."""
    if state.verdict is None:
        msg = "content-generation state has no aggregate verdict"
        raise ValueError(msg)
    return state.verdict


async def initialize(
    state: ContentGenerationGraphState,
    context: ContentGenerationContext,
) -> NodeResult:
    """Claim and hydrate the run, then refuse an unevaluable QA-gated run.

    The claim comes first so that only the task that won the claim can record
    an ``qa.unavailable`` terminal. Checking earlier would let a losing
    launcher fail another worker's running job.

    Returns
    -------
    NodeResult
        An empty state delta.

    Raises
    ------
    QualityEvaluationUnavailableError
        If the claimed run is QA-gated and no evaluator is configured.
    """
    await context.steps.initialize()
    if (
        state.request.quality_mode is QualityMode.QA_GATED
        and not context.evaluator_set.evaluators
    ):
        msg = "QA-gated generation requires at least one configured evaluator."
        raise QualityEvaluationUnavailableError(msg)
    return {}


async def generate_draft_without_qa(
    state: ContentGenerationGraphState,
    context: ContentGenerationContext,
) -> NodeResult:
    """Generate the no-QA branch's draft."""
    _ = state
    await context.steps.generate_draft()
    return {}


async def generate_qa_candidate(
    state: ContentGenerationGraphState,
    context: ContentGenerationContext,
) -> NodeResult:
    """Generate the QA-gated branch's candidate draft."""
    _ = state
    await context.steps.generate_draft()
    return {}


def _is_external_cancellation() -> bool:
    """Return whether the current task is being cancelled from outside."""
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


async def _evaluate_one(
    evaluator: QualityEvaluatorPort,
    subject: EvaluationSubject,
    timeout_seconds: float,
) -> QualityEvaluation:
    """Run one evaluator, converting every failure into an inconclusive verdict."""
    try:
        async with asyncio.timeout(timeout_seconds):
            evaluation = await evaluator.evaluate(subject)
    except TimeoutError as exc:
        log_error(
            logger,
            "content_generation.evaluator_timeout evaluator=%s",
            evaluator.name,
            exc_info=exc,
        )
        return QualityEvaluation(
            evaluator=evaluator.name,
            verdict=QualityVerdict.INCONCLUSIVE,
            error_type=_TIMEOUT_ERROR,
        )
    except asyncio.CancelledError as exc:
        if _is_external_cancellation():
            raise
        log_error(
            logger,
            "content_generation.evaluator_cancelled evaluator=%s",
            evaluator.name,
            exc_info=exc,
        )
        return QualityEvaluation(
            evaluator=evaluator.name,
            verdict=QualityVerdict.INCONCLUSIVE,
            error_type=_CANCELLED_ERROR,
        )
    except Exception as exc:  # ruff: ignore[blind-except]  # An adapter fault must not fail the generator path.
        log_error(
            logger,
            "content_generation.evaluator_error evaluator=%s error_type=%s",
            evaluator.name,
            type(exc).__name__,
            exc_info=exc,
        )
        return QualityEvaluation(
            evaluator=evaluator.name,
            verdict=QualityVerdict.INCONCLUSIVE,
            error_type=type(exc).__name__,
        )
    if evaluation.error_type is not None:
        log_error(
            logger,
            "content_generation.evaluator_inconsistent evaluator=%s error_type=%s",
            evaluator.name,
            evaluation.error_type,
        )
        return QualityEvaluation(
            evaluator=evaluator.name,
            verdict=QualityVerdict.INCONCLUSIVE,
            summary=evaluation.summary,
            error_type=evaluation.error_type,
        )
    return QualityEvaluation(
        evaluator=evaluator.name,
        verdict=evaluation.verdict,
        summary=evaluation.summary,
    )


async def evaluate(
    state: ContentGenerationGraphState,
    context: ContentGenerationContext,
) -> NodeResult:
    """Evaluate the candidate draft and aggregate the verdicts."""
    _ = state
    evaluators = context.evaluator_set.evaluators
    names = tuple(evaluator.name for evaluator in evaluators)
    await context.steps.begin_evaluation(names)
    subject = context.steps.evaluation_subject()
    results = [
        await _evaluate_one(
            evaluator,
            subject,
            context.evaluator_set.evaluator_timeout_seconds,
        )
        for evaluator in evaluators
    ]
    evaluations = tuple(results)
    return {
        "verdict": aggregate_verdicts(evaluation.verdict for evaluation in evaluations),
        "evaluations": evaluations,
    }


async def persist_draft_without_qa(
    state: ContentGenerationGraphState,
    context: ContentGenerationContext,
) -> NodeResult:
    """Persist a no-QA draft and reach the no-QA terminal."""
    _ = state
    await context.steps.complete_with_draft(QaStatus.SKIPPED, ())
    return {"terminal": GenerationTerminal.DRAFT_PERSISTED_WITHOUT_QA}


async def persist_qa_passed_draft(
    state: ContentGenerationGraphState,
    context: ContentGenerationContext,
) -> NodeResult:
    """Persist a QA-passed draft and reach the QA-passed terminal."""
    await context.steps.complete_with_draft(QaStatus.PASSED, state.evaluations)
    return {"terminal": GenerationTerminal.QA_PASSED_DRAFT_PERSISTED}


async def escalate(
    state: ContentGenerationGraphState,
    context: ContentGenerationContext,
) -> NodeResult:
    """Escalate without persisting TEI and reach the escalation terminal."""
    await context.steps.escalate(_require_verdict(state), state.evaluations)
    return {"terminal": GenerationTerminal.QA_ESCALATED}


def route_after_initialize(state: ContentGenerationGraphState) -> QualityBranch:
    """Return the branch the requested quality mode selects."""
    return route_quality_mode(state.request.quality_mode)


def route_after_evaluate(state: ContentGenerationGraphState) -> EvaluationRoute:
    """Return the persistence or escalation route for the aggregate verdict."""
    return route_after_evaluation(_require_verdict(state))
