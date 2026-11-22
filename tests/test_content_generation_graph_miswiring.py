"""Mis-wiring check for the content-generation graph's branch ownership (INV-5).

The production graph cannot be mis-wired from a test, so this module builds an
equivalent graph from the same public node functions with swapped
``path_map`` targets. The property's ownership check must reject it.
"""

import typing as typ
import uuid

import pytest
from langgraph.graph import END, START, StateGraph

from episodic.canonical.generation_graph_ports import (
    ContentGenerationRequest,
    QualityEvaluatorSet,
)
from episodic.canonical.generation_quality import QualityMode
from episodic.canonical.generation_routing import (
    EvaluationRoute,
    GenerationTerminal,
    QualityBranch,
    branch_for_terminal,
    route_quality_mode,
)
from episodic.orchestration._content_graph_nodes import (
    escalate,
    evaluate,
    generate_draft_without_qa,
    generate_qa_candidate,
    initialize,
    persist_draft_without_qa,
    persist_qa_passed_draft,
    route_after_evaluate,
    route_after_initialize,
)
from episodic.orchestration._content_graph_state import (
    ContentGenerationContext,
    ContentGenerationGraphState,
)
from tests._content_graph_fakes import RecordingSteps, ScriptedEvaluator, wrap_node
from tests.test_content_generation_graph_properties import assert_branch_ownership

if typ.TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

_RUN_ID = "018fdcf0-0000-7000-8000-000000000001"
_TIMEOUT_SECONDS = 0.01

_NODES = {
    "initialize": initialize,
    "generate_draft_without_qa": generate_draft_without_qa,
    "persist_draft_without_qa": persist_draft_without_qa,
    "generate_qa_candidate": generate_qa_candidate,
    "evaluate": evaluate,
    "persist_qa_passed_draft": persist_qa_passed_draft,
    "escalate": escalate,
}


def _swapped_graph() -> CompiledStateGraph[
    ContentGenerationGraphState,
    ContentGenerationContext,
    ContentGenerationGraphState,
    ContentGenerationGraphState,
]:
    """Build a graph that routes the gated branch down the no-QA path."""
    graph = StateGraph(
        ContentGenerationGraphState,
        context_schema=ContentGenerationContext,
    )
    for name, node in _NODES.items():
        graph.add_node(name, wrap_node(node))
    graph.add_edge(START, "initialize")
    graph.add_conditional_edges(
        "initialize",
        route_after_initialize,
        path_map={
            QualityBranch.DRAFT_WITHOUT_QA: "generate_draft_without_qa",
            QualityBranch.QA_GATED: "generate_draft_without_qa",
        },
    )
    graph.add_edge("generate_draft_without_qa", "persist_draft_without_qa")
    graph.add_edge("persist_draft_without_qa", END)
    graph.add_edge("generate_qa_candidate", "evaluate")
    graph.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        path_map={
            EvaluationRoute.PASS: "persist_qa_passed_draft",
            EvaluationRoute.ESCALATE: "escalate",
        },
    )
    graph.add_edge("persist_qa_passed_draft", END)
    graph.add_edge("escalate", END)
    return graph.compile()


@pytest.mark.asyncio
async def test_swapped_path_map_is_rejected() -> None:
    """A mis-wired graph reaches a terminal its branch does not own."""
    steps = RecordingSteps()
    passing = ScriptedEvaluator("evaluator-0", "passed")
    result = await _swapped_graph().ainvoke(
        ContentGenerationGraphState(
            request=ContentGenerationRequest(
                run_id=uuid.UUID(_RUN_ID),
                quality_mode=QualityMode.QA_GATED,
            )
        ),
        context=ContentGenerationContext(
            steps=steps,
            evaluator_set=QualityEvaluatorSet(
                (passing,),
                evaluator_timeout_seconds=_TIMEOUT_SECONDS,
            ),
        ),
    )
    terminal = typ.cast("GenerationTerminal", result["terminal"])
    assert terminal is GenerationTerminal.DRAFT_PERSISTED_WITHOUT_QA, (
        f"mis-wired graph reached {terminal!r}"
    )
    assert branch_for_terminal(terminal) is not route_quality_mode(
        QualityMode.QA_GATED
    ), "the mis-wired terminal must be catchable by the ownership check"
    with pytest.raises(AssertionError):
        assert_branch_ownership(
            QualityMode.QA_GATED,
            steps.step_names(),
            terminal,
        )
