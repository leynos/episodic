"""Ownership assertions for the content-generation graph's branches (INV-5).

The checks are shared by the property test, which generates inputs, and the
mis-wiring test, which builds a deliberately wrong graph, so both reject a
trace against the same definition of branch ownership. This is a support
module rather than a test module, so its helpers keep the repository's plain
``assert`` style by declaring the exemption explicitly.
"""

import contextlib
import typing as typ
import uuid

from episodic.canonical.generation_graph_ports import (
    ContentGenerationRequest,
    QualityEvaluatorSet,
)
from episodic.canonical.generation_quality import QualityMode
from episodic.canonical.generation_routing import (
    GenerationTerminal,
    branch_for_terminal,
    route_quality_mode,
)
from episodic.orchestration._content_graph_state import (
    NODE_OWNERSHIP,
    ContentGenerationContext,
    ContentGenerationGraphState,
)
from episodic.orchestration.content_generation import build_content_generation_graph
from tests._content_graph_fakes import RecordingSteps, ScriptedEvaluator

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_RUN_ID = "018fdcf0-0000-7000-8000-000000000001"
_TIMEOUT_SECONDS = 0.01


def _visited_nodes(mode: QualityMode, step_names: cabc.Sequence[str]) -> set[str]:
    """Return the graph nodes a step log proves the run visited."""
    visited: set[str] = {"initialize"}
    if "generate_draft" in step_names:
        visited.add(
            "generate_qa_candidate"
            if mode is QualityMode.QA_GATED
            else "generate_draft_without_qa"
        )
    if "begin_evaluation" in step_names:
        visited.add("evaluate")
    if "complete_with_draft" in step_names:
        visited.add(
            "persist_qa_passed_draft"
            if mode is QualityMode.QA_GATED
            else "persist_draft_without_qa"
        )
    if "escalate" in step_names:
        visited.add("escalate")
    return visited


def assert_observed_ownership(
    mode: QualityMode,
    observed_nodes: cabc.Sequence[str],
) -> None:
    """Reject an executed node that the run's quality branch does not own."""
    branch = route_quality_mode(mode)
    for node in observed_nodes:
        owner = NODE_OWNERSHIP[node]
        assert owner in {None, branch}, f"{node} belongs to {owner}, not {branch}"


async def observed_nodes(
    mode: QualityMode,
    behaviours: cabc.Sequence[str],
    fault: str | None,
) -> tuple[str, ...]:
    """Return the nodes the compiled graph actually executed for one input."""
    graph = build_content_generation_graph()
    evaluators = tuple(
        ScriptedEvaluator(f"evaluator-{index}", behaviour)
        for index, behaviour in enumerate(behaviours)
    )
    steps = RecordingSteps(fault_step=fault)
    context = ContentGenerationContext(
        steps=steps,
        evaluator_set=QualityEvaluatorSet(
            evaluators,
            evaluator_timeout_seconds=_TIMEOUT_SECONDS,
        ),
    )
    observed: list[str] = []
    with contextlib.suppress(Exception):
        # A fault ends observation; the visits recorded before it remain evidence.
        async for update in graph.astream(
            ContentGenerationGraphState(
                request=ContentGenerationRequest(
                    run_id=uuid.UUID(_RUN_ID),
                    quality_mode=mode,
                )
            ),
            context=context,
            stream_mode="updates",
        ):
            observed.extend(update.keys())
    return tuple(observed)


def assert_branch_ownership(
    mode: QualityMode,
    step_names: cabc.Sequence[str],
    terminal: GenerationTerminal | None,
) -> None:
    """Reject a trace that visits a node its quality branch does not own."""
    branch = route_quality_mode(mode)
    if mode is QualityMode.DRAFT_WITHOUT_QA:
        assert "begin_evaluation" not in step_names, "no-QA runs never evaluate"
        assert "escalate" not in step_names, "no-QA runs never escalate"
    for node in _visited_nodes(mode, step_names):
        owner = NODE_OWNERSHIP[node]
        assert owner in {None, branch}, f"{node} belongs to {owner}, not {branch}"
    if terminal is not None:
        assert branch_for_terminal(terminal) is branch, (
            f"{terminal} does not belong to {branch}"
        )
