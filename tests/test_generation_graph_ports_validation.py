"""Validation for the content-generation graph ports.

A bad evaluator set or timeout corrupts reporting or hangs a run, so the
value objects reject it at construction.
"""

import math

import pytest

from episodic.canonical.generation_graph_ports import (
    EvaluationSubject,
    QualityEvaluation,
    QualityEvaluatorPort,
    QualityEvaluatorSet,
)
from episodic.canonical.generation_routing import QualityVerdict
from tests._content_graph_fakes import ScriptedEvaluator


class _NamedEvaluator:
    """Minimal evaluator that only carries a slug."""

    def __init__(self, name: str) -> None:
        """Store the slug."""
        self._name = name

    @property
    def name(self) -> str:
        """The evaluator's stable slug."""
        return self._name

    async def evaluate(self, subject: EvaluationSubject) -> QualityEvaluation:
        """Never called by these tests."""
        _ = subject
        return QualityEvaluation(self._name, QualityVerdict.PASSED)


def _evaluators(*names: str) -> tuple[QualityEvaluatorPort, ...]:
    """Build evaluators carrying the given slugs."""
    return tuple(_NamedEvaluator(name) for name in names)


@pytest.mark.parametrize(
    "timeout",
    [0.0, -1.0, math.inf, -math.inf, math.nan],
    ids=["zero", "negative", "infinity", "negative-infinity", "nan"],
)
def test_evaluator_timeout_must_be_finite_and_positive(timeout: float) -> None:
    """Every non-finite or non-positive timeout is rejected."""
    with pytest.raises(ValueError, match="finite positive"):
        QualityEvaluatorSet(_evaluators("pedante"), evaluator_timeout_seconds=timeout)


@pytest.mark.parametrize("name", ["", "   "], ids=["empty", "blank"])
def test_evaluator_names_must_not_be_blank(name: str) -> None:
    """A blank evaluator slug is rejected."""
    with pytest.raises(ValueError, match="non-empty slug"):
        QualityEvaluatorSet(_evaluators(name))


def test_evaluator_names_must_be_unique() -> None:
    """Duplicate evaluator slugs are rejected."""
    with pytest.raises(ValueError, match="unique"):
        QualityEvaluatorSet(_evaluators("pedante", "pedante"))


def test_a_valid_evaluator_set_is_accepted() -> None:
    """The positive control constructs a usable set."""
    evaluators = (ScriptedEvaluator("pedante", "passed"),)
    evaluator_set = QualityEvaluatorSet(
        evaluators,
        evaluator_timeout_seconds=5.0,
    )
    assert evaluator_set.evaluators == evaluators, evaluator_set.evaluators
    assert evaluator_set.accepted_quality_modes() == frozenset({
        "draft_without_qa",
        "qa_gated",
    }), evaluator_set.accepted_quality_modes()
