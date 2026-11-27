"""Event payloads and metrics for QA-gated launcher outcomes.

These are plain functions rather than another mixin: they translate
evaluations into the ``qa.result`` payload and record the bounded QA metrics,
so the launcher session and the persistence mixin share one definition.
"""

import dataclasses as dc
import typing as typ

from episodic.canonical.generation_quality import (
    QaStatus,  # ruff: ignore[typing-only-first-party-import]  # Dataclass annotations are evaluated at runtime.
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import JsonMapping
    from episodic.canonical.generation_graph_ports import QualityEvaluation
    from episodic.canonical.generation_routing import QualityVerdict
    from episodic.observability import ValueMetricsPort


@dc.dataclass(frozen=True, slots=True)
class QaOutcome:
    """QA status and evaluations a successful persistence step records.

    Attributes
    ----------
    status : QaStatus
        ``skipped`` for a no-QA draft, ``passed`` for a QA-gated one.
    evaluations : tuple[QualityEvaluation, ...]
        Per-evaluator results; empty for no-QA runs.
    """

    status: QaStatus
    evaluations: tuple[QualityEvaluation, ...]


_METRIC_QA_GATE = "generation_run_qa_gate_total"
_METRIC_QA_EVALUATOR_ERRORS = "generation_run_qa_evaluator_errors_total"


def qa_result_payload(
    verdict: QualityVerdict,
    evaluations: tuple[QualityEvaluation, ...],
) -> JsonMapping:
    """Build the ``qa.result`` event payload.

    Parameters
    ----------
    verdict : QualityVerdict
        Aggregate verdict for the run.
    evaluations : tuple[QualityEvaluation, ...]
        Per-evaluator results, in evaluation order.

    Returns
    -------
    JsonMapping
        Aggregate verdict plus one entry per evaluator, including its error
        classification when it failed rather than returned a verdict.
    """
    return {
        "verdict": verdict.value,
        "evaluators": [
            {
                "name": evaluation.evaluator,
                "verdict": evaluation.verdict.value,
                "errored": evaluation.error_type is not None,
                "error_type": evaluation.error_type,
            }
            for evaluation in evaluations
        ],
    }


def record_qa_metrics(
    metrics: ValueMetricsPort,
    verdict: QualityVerdict,
    evaluations: tuple[QualityEvaluation, ...],
) -> None:
    """Record the QA gate verdict and any evaluator errors.

    Parameters
    ----------
    metrics : ValueMetricsPort
        Launcher metrics sink.
    verdict : QualityVerdict
        Aggregate verdict for the run.
    evaluations : tuple[QualityEvaluation, ...]
        Per-evaluator results. Each failed evaluator increments the
        evaluator-error counter under its stable slug, so an adapter
        regression is visible separately from genuine QA rejections.
    """
    metrics.increment_counter(
        _METRIC_QA_GATE,
        labels={"verdict": verdict.value},
    )
    for evaluation in evaluations:
        if evaluation.error_type is None:
            continue
        metrics.increment_counter(
            _METRIC_QA_EVALUATOR_ERRORS,
            labels={"evaluator": evaluation.evaluator},
        )
