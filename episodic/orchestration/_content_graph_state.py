"""Domain state, per-run context, and node ownership for content generation.

The graph state holds domain values only. Application objects such as a claimed
run or a generated draft stay in the run session that implements
:class:`~episodic.canonical.generation_graph_ports.ContentGenerationSteps`, so
a checkpoint or event payload never carries application state.
"""

import dataclasses as dc
import typing as typ

from episodic.canonical.generation_graph_ports import (  # ruff: ignore[typing-only-first-party-import]  # Dataclass annotations are evaluated at runtime.
    ContentGenerationRequest,
    ContentGenerationSteps,
    QualityEvaluation,
    QualityEvaluatorSet,
)
from episodic.canonical.generation_routing import (
    GenerationTerminal,
    QualityBranch,
    QualityVerdict,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc


@dc.dataclass(slots=True)
class ContentGenerationGraphState:
    """State carried by one content-generation graph run.

    Attributes
    ----------
    request : ContentGenerationRequest
        The run being executed and its requested quality mode.
    verdict : QualityVerdict | None
        Aggregate evaluator verdict, set by ``evaluate``.
    evaluations : tuple[QualityEvaluation, ...]
        Per-evaluator results, set by ``evaluate``.
    terminal : GenerationTerminal | None
        Terminal reached, set by the branch's terminal node.
    """

    request: ContentGenerationRequest
    verdict: QualityVerdict | None = None
    evaluations: tuple[QualityEvaluation, ...] = ()
    terminal: GenerationTerminal | None = None


@dc.dataclass(frozen=True, slots=True)
class ContentGenerationContext:
    """Per-run collaborators delivered through the graph's runtime context.

    Attributes
    ----------
    steps : ContentGenerationSteps
        The run session through which nodes reach run state.
    evaluator_set : QualityEvaluatorSet
        Configured evaluators and their timeout.
    """

    steps: ContentGenerationSteps
    evaluator_set: QualityEvaluatorSet


NODE_OWNERSHIP: cabc.Mapping[str, QualityBranch | None] = {
    "initialize": None,
    "generate_draft_without_qa": QualityBranch.DRAFT_WITHOUT_QA,
    "persist_draft_without_qa": QualityBranch.DRAFT_WITHOUT_QA,
    "generate_qa_candidate": QualityBranch.QA_GATED,
    "evaluate": QualityBranch.QA_GATED,
    "persist_qa_passed_draft": QualityBranch.QA_GATED,
    "escalate": QualityBranch.QA_GATED,
}
"""Which quality branch owns each graph node. ``None`` marks a shared node."""
