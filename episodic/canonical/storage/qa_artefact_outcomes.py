"""Bounded outcome signals for QA artefact recordings.

The counters and the structured log line describe how a recording resolved,
whether the payload was stored, replayed, or superseded, or why it failed. Only
an evaluator and a bounded status or category reach them: no finding text,
summary, or artefact identifier is captured.
"""

import typing as typ

from episodic.logging import log_event as _log_event

if typ.TYPE_CHECKING:
    from episodic.canonical.qa_artefacts import (
        QaComplianceStatus,
        QaEvaluationSummary,
    )
    from episodic.observability import MetricsPort


def emit_recorded(metrics: MetricsPort, summary: QaEvaluationSummary) -> None:
    """Count a first-time recording."""
    metrics.increment_counter(
        "qa_evaluation_recorded",
        labels={
            "evaluator": summary.evaluator.value,
            "compliance_status": summary.compliance_status.value,
        },
    )


def emit_replayed(
    metrics: MetricsPort,
    summary: QaEvaluationSummary,
    stored_status: QaComplianceStatus,
) -> None:
    """Count a replay of an existing artefact."""
    metrics.increment_counter(
        "qa_evaluation_replayed",
        labels={
            "evaluator": summary.evaluator.value,
            "stored_status": stored_status.value,
        },
    )


def emit_failed(
    metrics: MetricsPort,
    summary: QaEvaluationSummary,
    error_category: str,
) -> None:
    """Count a failed recording under a bounded error category."""
    metrics.increment_counter(
        "qa_evaluation_record_failed",
        labels={
            "evaluator": summary.evaluator.value,
            "error_category": error_category,
        },
    )


def log_outcome(
    summary: QaEvaluationSummary,
    *,
    replayed: bool,
    superseded: bool,
) -> None:
    """Log the recording outcome without any finding text."""
    _log_event(
        "info",
        "sql_qa_artefact_store.record_evaluation",
        evaluator=summary.evaluator.value,
        episode_id=str(summary.episode_id),
        replayed=replayed,
        superseded=superseded,
    )
