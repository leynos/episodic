"""Error-tagged evaluator results must fail closed (INV-5).

An adapter that reports a passing verdict together with an error classification
is self-contradictory. Treating that as a pass would persist a draft no
evaluator actually approved, so the node normalizes it to an inconclusive
result and the run escalates.
"""

import asyncio
import typing as typ
import uuid

import pytest

from episodic.canonical.generation_graph_ports import (
    ContentGenerationRequest,
    EvaluationSubject,
    QualityEvaluation,
    QualityEvaluatorSet,
)
from episodic.canonical.generation_quality import QualityMode
from episodic.canonical.generation_routing import GenerationTerminal, QualityVerdict
from episodic.orchestration.content_generation import (
    LangGraphContentGenerationGraph,
)
from tests._content_graph_fakes import RecordingSteps

_RUN_ID = "018fdcf0-0000-7000-8000-000000000001"
_TIMEOUT_SECONDS = 0.01


class _ErrorTaggedPassEvaluator:
    """Evaluator that claims a pass but tags the result with an error."""

    @property
    def name(self) -> str:
        """The evaluator's stable slug."""
        return "inconsistent"

    async def evaluate(self, subject: EvaluationSubject) -> QualityEvaluation:
        """Return a passing verdict carrying a timeout classification."""
        _ = subject
        return QualityEvaluation(
            self.name,
            QualityVerdict.PASSED,
            error_type="timeout",
        )


@pytest.mark.asyncio
async def test_error_tagged_pass_escalates() -> None:
    """An error-tagged pass must fail closed rather than persist a draft."""
    graph = LangGraphContentGenerationGraph(
        QualityEvaluatorSet(
            (_ErrorTaggedPassEvaluator(),),
            evaluator_timeout_seconds=_TIMEOUT_SECONDS,
        )
    )
    steps = RecordingSteps()
    terminal = await graph.run(
        ContentGenerationRequest(
            run_id=uuid.UUID(_RUN_ID),
            quality_mode=QualityMode.QA_GATED,
        ),
        steps=steps,
    )

    assert terminal is GenerationTerminal.QA_ESCALATED, terminal
    assert "complete_with_draft" not in steps.step_names(), steps.step_names()
    verdict, evaluations = typ.cast(
        "tuple[QualityVerdict, tuple[QualityEvaluation, ...]]",
        steps.detail_for("escalate"),
    )
    assert verdict is QualityVerdict.INCONCLUSIVE, verdict
    assert evaluations[0].verdict is QualityVerdict.INCONCLUSIVE, evaluations
    assert evaluations[0].error_type == "timeout", evaluations


class _CancellationSwallowingEvaluator:
    """Evaluator that ignores its timeout cancellation and returns a pass."""

    @property
    def name(self) -> str:
        """The evaluator's stable slug."""
        return "swallows-cancellation"

    async def evaluate(self, subject: EvaluationSubject) -> QualityEvaluation:
        """Wait past the deadline, swallow the cancellation, and pass."""
        _ = subject
        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            # A misbehaving adapter could do this; the deadline must win.
            return QualityEvaluation(
                self.name,
                QualityVerdict.PASSED,
            )
        return QualityEvaluation(self.name, QualityVerdict.PASSED)


@pytest.mark.asyncio
async def test_timeout_cannot_be_escaped_by_swallowing_cancellation() -> None:
    """A late result after the deadline must not be accepted as a pass."""
    graph = LangGraphContentGenerationGraph(
        QualityEvaluatorSet(
            (_CancellationSwallowingEvaluator(),),
            evaluator_timeout_seconds=0.01,
        )
    )
    steps = RecordingSteps()
    terminal = await graph.run(
        ContentGenerationRequest(
            run_id=uuid.UUID(_RUN_ID),
            quality_mode=QualityMode.QA_GATED,
        ),
        steps=steps,
    )

    assert terminal is GenerationTerminal.QA_ESCALATED, terminal
    assert "complete_with_draft" not in steps.step_names(), steps.step_names()
    verdict, evaluations = typ.cast(
        "tuple[QualityVerdict, tuple[QualityEvaluation, ...]]",
        steps.detail_for("escalate"),
    )
    assert verdict is QualityVerdict.INCONCLUSIVE, verdict
    assert evaluations[0].error_type == "timeout", evaluations
