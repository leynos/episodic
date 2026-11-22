"""Failure classification and QA event mapping for the launcher.

These helpers decide the public error category, whether a failure counts as a
draft error, and the payload and metrics an evaluation produces. Each test
pins one contract those call sites depend on.
"""

import typing as typ

import pytest

from episodic.canonical.generation_graph_ports import (
    ContentGenerationGraphError,
    QualityEvaluation,
    QualityEvaluationUnavailableError,
)
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.generation_routing import QualityVerdict
from episodic.generation.draft_script import DraftScriptTransientProviderError
from episodic.generation.launcher_quality import qa_result_payload, record_qa_metrics
from episodic.generation.launcher_support import classify_failure
from tests.generation_run_launcher_observation_support import RecordingMetrics

_METRIC_QA_GATE = "generation_run_qa_gate_total"
_METRIC_EVALUATOR_ERRORS = "generation_run_qa_evaluator_errors_total"


@pytest.mark.parametrize(
    ("error", "category", "is_draft_error"),
    [
        (ContentGenerationGraphError("incomplete"), "orchestration.incomplete", False),
        (
            QualityEvaluationUnavailableError("no evaluators"),
            "qa.unavailable",
            False,
        ),
        (
            DraftScriptTransientProviderError("try later"),
            "provider.transient",
            True,
        ),
    ],
    ids=["graph-incomplete", "qa-unavailable", "provider-transient"],
)
def test_classify_failure_sets_category_and_draft_error(
    error: Exception,
    category: str,
    *,
    is_draft_error: bool,
) -> None:
    """Each failure maps to its stable category and draft-error flag."""
    failure = classify_failure(error)
    assert failure.category == category, failure.category
    assert failure.is_draft_error is is_draft_error, failure.is_draft_error


def test_qa_result_payload_records_each_evaluation() -> None:
    """The payload carries the verdict and one entry per evaluator."""
    evaluations = (
        QualityEvaluation("pedante", QualityVerdict.PASSED),
        QualityEvaluation(
            "chrono",
            QualityVerdict.INCONCLUSIVE,
            error_type="timeout",
        ),
    )
    payload = qa_result_payload(QualityVerdict.INCONCLUSIVE, evaluations)

    assert payload["verdict"] == QualityVerdict.INCONCLUSIVE.value, payload
    evaluators = payload["evaluators"]
    assert isinstance(evaluators, list), evaluators
    first = typ.cast("dict[str, object]", evaluators[0])
    assert first["name"] == "pedante", first
    assert first["verdict"] == QualityVerdict.PASSED.value, first
    assert first["errored"] is False, first
    assert first["error_type"] is None, first
    second = typ.cast("dict[str, object]", evaluators[1])
    assert second["name"] == "chrono", second
    assert second["verdict"] == QualityVerdict.INCONCLUSIVE.value, second
    assert second["errored"] is True, second
    assert second["error_type"] == "timeout", second


def test_record_qa_metrics_labels_the_gate_and_evaluator_errors() -> None:
    """The gate counter carries the verdict and errors carry the evaluator."""
    metrics = RecordingMetrics()
    evaluations = (
        QualityEvaluation("pedante", QualityVerdict.FAILED),
        QualityEvaluation(
            "chrono",
            QualityVerdict.INCONCLUSIVE,
            error_type="timeout",
        ),
    )

    record_qa_metrics(metrics, QualityVerdict.FAILED, evaluations)

    counters = [
        observation
        for observation in metrics.observations
        if observation.kind == "counter"
    ]
    assert counters[0].name == _METRIC_QA_GATE, counters
    assert counters[0].labels == {"verdict": QualityVerdict.FAILED.value}, counters
    assert counters[1].name == _METRIC_EVALUATOR_ERRORS, counters
    assert counters[1].labels == {"evaluator": "chrono"}, counters
    assert len(counters) == 2, counters


def test_qa_outcome_keeps_status_and_evaluations() -> None:
    """The outcome carried into persistence preserves order and status."""
    from episodic.generation.launcher_quality import QaOutcome

    evaluations = (
        QualityEvaluation("pedante", QualityVerdict.PASSED),
        QualityEvaluation("chrono", QualityVerdict.PASSED),
    )
    outcome = QaOutcome(QaStatus.PASSED, evaluations)
    assert outcome.status is QaStatus.PASSED, outcome.status
    assert outcome.evaluations == evaluations, outcome.evaluations
