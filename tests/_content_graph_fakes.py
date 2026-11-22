"""Fakes for driving the content-generation graph without infrastructure.

The recording step port stands in for the launcher's run session, and the
scripted evaluators cover every evaluator outcome the graph must classify.
Nothing here opens a unit of work, generates content, or touches a database.
"""

import asyncio
import dataclasses as dc
import typing as typ
import uuid

from langgraph.runtime import Runtime  # ruff: ignore[typing-only-third-party-import]  # Wrapper closure annotations are evaluated at definition.

from episodic.canonical.generation_graph_ports import (
    EvaluationSubject,
    QualityEvaluation,
)
from episodic.canonical.generation_routing import QualityVerdict
from episodic.orchestration._content_graph_state import (
    ContentGenerationContext,  # ruff: ignore[typing-only-first-party-import]  # LangGraph inspects the wrapper's annotations.
    ContentGenerationGraphState,  # ruff: ignore[typing-only-first-party-import]  # LangGraph inspects the wrapper's annotations.
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.generation_quality import QaStatus

FAULT_STEPS: tuple[str, ...] = (
    "initialize",
    "generate_draft",
    "begin_evaluation",
    "complete_with_draft",
    "escalate",
)


class InjectedFaultError(RuntimeError):
    """Raised by the recording step port when a fault is injected."""


SUBJECT = EvaluationSubject(
    run_id=uuid.UUID("018fdcf0-0000-7000-8000-000000000001"),
    episode_id=uuid.UUID("018fdcf0-0000-7000-8000-000000000002"),
    tei_xml="<TEI><text><body><p>Draft.</p></body></text></TEI>",
    content_hash="sha256:" + "a" * 64,
)


@dc.dataclass(slots=True)
class RecordingSteps:
    """Step port that records every call and can fail at one step."""

    fault_step: str | None = None
    calls: list[tuple[str, object]] = dc.field(default_factory=list)

    def _record(self, step: str, detail: object = None) -> None:
        """Record one step and raise the configured fault, if any."""
        self.calls.append((step, detail))
        if self.fault_step == step:
            msg = f"injected {step} fault"
            raise InjectedFaultError(msg)

    async def initialize(self) -> None:
        """Record hydration."""
        self._record("initialize")

    async def generate_draft(self) -> None:
        """Record draft generation."""
        self._record("generate_draft")

    async def begin_evaluation(self, evaluator_names: tuple[str, ...]) -> None:
        """Record the start of evaluation."""
        self._record("begin_evaluation", evaluator_names)

    def evaluation_subject(self) -> EvaluationSubject:
        """Return the fixed subject."""
        _ = self
        return SUBJECT

    async def complete_with_draft(
        self,
        qa_status: QaStatus,
        evaluations: tuple[QualityEvaluation, ...],
    ) -> None:
        """Record the successful terminal."""
        self._record("complete_with_draft", (qa_status, evaluations))

    async def escalate(
        self,
        verdict: QualityVerdict,
        evaluations: tuple[QualityEvaluation, ...],
    ) -> None:
        """Record the escalated terminal."""
        self._record("escalate", (verdict, evaluations))

    def step_names(self) -> list[str]:
        """Return the step names in call order."""
        return [name for name, _detail in self.calls]

    def detail_for(self, step: str) -> object:
        """Return the recorded detail of the first call to a step."""
        for name, detail in self.calls:
            if name == step:
                return detail
        msg = f"{step} was not called"
        raise AssertionError(msg)


class ScriptedEvaluator:
    """Evaluator that returns, raises, hangs, or cancels as scripted."""

    def __init__(self, name: str, behaviour: str) -> None:
        """Store the evaluator slug and its scripted behaviour."""
        self._name = name
        self._behaviour = behaviour
        self.call_count = 0

    @property
    def name(self) -> str:
        """The evaluator's stable slug."""
        return self._name

    async def evaluate(self, subject: EvaluationSubject) -> QualityEvaluation:
        """Produce the scripted outcome."""
        _ = subject
        self.call_count += 1
        match self._behaviour:
            case "passed":
                return QualityEvaluation(self._name, QualityVerdict.PASSED)
            case "failed":
                return QualityEvaluation(
                    self._name,
                    QualityVerdict.FAILED,
                    summary="The draft contradicts a source.",
                )
            case "inconclusive":
                return QualityEvaluation(self._name, QualityVerdict.INCONCLUSIVE)
            case "raise":
                msg = "evaluator adapter fault"
                raise InjectedFaultError(msg)
            case "timeout":
                await asyncio.Event().wait()
                msg = "an event that never fires cannot continue"
                raise AssertionError(msg)
            case "cancel":
                raise asyncio.CancelledError
            case _:
                msg = f"unknown evaluator behaviour: {self._behaviour}"
                raise AssertionError(msg)


def verdict_for(behaviour: str) -> QualityVerdict:
    """Return the verdict a scripted behaviour contributes."""
    return {
        "passed": QualityVerdict.PASSED,
        "failed": QualityVerdict.FAILED,
        "inconclusive": QualityVerdict.INCONCLUSIVE,
        "raise": QualityVerdict.INCONCLUSIVE,
        "timeout": QualityVerdict.INCONCLUSIVE,
        "cancel": QualityVerdict.INCONCLUSIVE,
    }[behaviour]


def expected_aggregate(behaviours: cabc.Sequence[str]) -> QualityVerdict:
    """State the all-must-pass rule over scripted behaviours."""
    verdicts = [verdict_for(behaviour) for behaviour in behaviours]
    if not verdicts:
        return QualityVerdict.INCONCLUSIVE
    if QualityVerdict.FAILED in verdicts:
        return QualityVerdict.FAILED
    if QualityVerdict.INCONCLUSIVE in verdicts:
        return QualityVerdict.INCONCLUSIVE
    return QualityVerdict.PASSED


class NodeFn(typ.Protocol):
    """Plain graph-node function that takes the run context explicitly."""

    def __call__(
        self,
        state: ContentGenerationGraphState,
        context: ContentGenerationContext,
    ) -> cabc.Awaitable[dict[str, object]]:
        """Execute one node with the run's context."""


class GraphNode(typ.Protocol):
    """Graph-callable node that receives LangGraph's runtime."""

    def __call__(
        self,
        state: ContentGenerationGraphState,
        runtime: Runtime[ContentGenerationContext],
    ) -> cabc.Awaitable[dict[str, object]]:
        """Execute one node with LangGraph's runtime."""


def wrap_node(node: NodeFn) -> GraphNode:
    """Wrap a plain node so LangGraph supplies its runtime context."""

    async def run(
        state: ContentGenerationGraphState,
        runtime: Runtime[ContentGenerationContext],
    ) -> dict[str, object]:
        """Execute the wrapped node with the run's context."""
        return await node(state, runtime.context)

    return run
