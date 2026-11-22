"""Static topology tests for the content-generation graph (INV-7).

These assertions are authoritative over the Mermaid snapshot: they state the
structural facts the design depends on, so a LangGraph upgrade that changes
``get_graph()`` reporting fails here even if the snapshot is regenerated.
"""

import asyncio
import typing as typ

import pytest
from langgraph.graph import END, START, StateGraph

from episodic.canonical.generation_routing import QualityBranch
from episodic.orchestration._content_graph_nodes import initialize
from episodic.orchestration._content_graph_state import (
    NODE_OWNERSHIP,
    ContentGenerationContext,
    ContentGenerationGraphState,
)
from episodic.orchestration.content_generation import build_content_generation_graph
from tests._content_graph_fakes import wrap_node

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from langgraph.graph.state import CompiledStateGraph
    from syrupy.assertion import SnapshotAssertion

_NO_QA_GENERATE = "generate_draft_without_qa"
_QA_GENERATE = "generate_qa_candidate"
_TERMINALS = {
    "persist_draft_without_qa",
    "persist_qa_passed_draft",
    "escalate",
}


def _edges(
    graph: CompiledStateGraph[
        ContentGenerationGraphState,
        ContentGenerationContext,
        ContentGenerationGraphState,
        ContentGenerationGraphState,
    ],
) -> tuple[tuple[str, str, bool], ...]:
    """Return ``(source, target, is_conditional)`` triples for every edge."""
    drawn = graph.get_graph()
    return tuple(
        (edge.source, edge.target, bool(edge.conditional)) for edge in drawn.edges
    )


def _targets(
    edges: cabc.Iterable[tuple[str, str, bool]],
    source: str,
) -> set[str]:
    """Return the targets of every edge leaving a node."""
    return {target for origin, target, _conditional in edges if origin == source}


def _reachable(
    edges: cabc.Iterable[tuple[str, str, bool]],
    start: str,
) -> set[str]:
    """Return every node reachable from ``start``."""
    adjacency: dict[str, set[str]] = {}
    for origin, target, _conditional in edges:
        adjacency.setdefault(origin, set()).add(target)
    seen: set[str] = set()
    pending = [start]
    while pending:
        node = pending.pop()
        if node in seen:
            continue
        seen.add(node)
        pending.extend(adjacency.get(node, set()) - seen)
    return seen


@pytest.fixture(scope="module")
def edges() -> tuple[tuple[str, str, bool], ...]:
    """Return the compiled graph's edges."""
    return _edges(build_content_generation_graph())


def test_only_initialize_is_shared(edges: tuple[tuple[str, str, bool], ...]) -> None:
    """The branches share no node other than ``initialize``."""
    no_qa = _reachable(edges, _NO_QA_GENERATE)
    qa_gated = _reachable(edges, _QA_GENERATE)

    assert no_qa & qa_gated == {END}, (
        f"branches must be disjoint apart from END, overlap={no_qa & qa_gated}"
    )
    assert no_qa | qa_gated, "both branches must be non-empty"


def test_only_initialize_has_edges_into_both_branches(
    edges: tuple[tuple[str, str, bool], ...],
) -> None:
    """``initialize`` is the single fork point."""
    no_qa = _reachable(edges, _NO_QA_GENERATE) - {END}
    qa_gated = _reachable(edges, _QA_GENERATE) - {END}
    sources = {source for source, _target, _ in edges} - {END}
    into_both = {
        source
        for source in sources
        if _targets(edges, source) & no_qa and _targets(edges, source) & qa_gated
    }

    assert into_both == {"initialize"}, (
        f"only initialize may fork, got {sorted(into_both)}"
    )


def test_every_terminal_ends_the_graph(
    edges: tuple[tuple[str, str, bool], ...],
) -> None:
    """Each terminal has exactly one outgoing edge, to END."""
    for terminal in _TERMINALS:
        assert _targets(edges, terminal) == {END}, (
            f"{terminal} must end the graph, got {_targets(edges, terminal)}"
        )


def test_conditional_edges_match_their_path_maps(
    edges: tuple[tuple[str, str, bool], ...],
) -> None:
    """Conditional targets are exactly the declared ``path_map`` values."""
    from_initialize = {
        target
        for source, target, is_conditional in edges
        if source == "initialize" and is_conditional
    }
    from_evaluate = {
        target
        for source, target, is_conditional in edges
        if source == "evaluate" and is_conditional
    }

    assert from_initialize == {_NO_QA_GENERATE, _QA_GENERATE}, (
        f"quality branch targets={sorted(from_initialize)}"
    )
    assert from_evaluate == {"persist_qa_passed_draft", "escalate"}, (
        f"evaluation route targets={sorted(from_evaluate)}"
    )


def test_start_reaches_every_node(edges: tuple[tuple[str, str, bool], ...]) -> None:
    """Every registered node is reachable from START."""
    reached = _reachable(edges, START)
    missing = set(NODE_OWNERSHIP) - reached

    assert not missing, f"unreachable nodes: {sorted(missing)}"


def test_every_branch_owns_its_nodes() -> None:
    """Each node except initialize belongs to exactly one branch."""
    shared = [node for node, owner in NODE_OWNERSHIP.items() if owner is None]
    owned = {
        branch: sorted(
            node for node, owner in NODE_OWNERSHIP.items() if owner is branch
        )
        for branch in QualityBranch
    }

    assert shared == ["initialize"], f"shared nodes={shared}"
    assert all(nodes for nodes in owned.values()), f"branch ownership={owned}"


@pytest.mark.parametrize("shared_name", ["persist_shared", "generate_shared"])
def test_reachability_reports_a_shared_node(shared_name: str) -> None:
    """The reachability helper must report overlap when a node is shared."""

    async def noop(
        state: ContentGenerationGraphState,
        context: ContentGenerationContext,
    ) -> dict[str, object]:
        _ = (state, context)
        await asyncio.sleep(0)
        return {}

    graph = StateGraph(
        ContentGenerationGraphState,
        context_schema=ContentGenerationContext,
    )
    graph.add_node("initialize", wrap_node(initialize))
    graph.add_node("left", wrap_node(noop))
    graph.add_node("right", wrap_node(noop))
    graph.add_node(shared_name, wrap_node(noop))
    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "left")
    graph.add_edge("initialize", "right")
    graph.add_edge("left", shared_name)
    graph.add_edge("right", shared_name)
    graph.add_edge(shared_name, END)
    compiled_edges = _edges(graph.compile())

    overlap = _reachable(compiled_edges, "left") & _reachable(compiled_edges, "right")

    assert shared_name in overlap, f"shared node not reported: {sorted(overlap)}"


def test_topology_snapshot(snapshot: SnapshotAssertion) -> None:
    """Record the Mermaid rendering as a review aid, not the authority."""
    graph = build_content_generation_graph()
    assert graph.get_graph().draw_mermaid() == snapshot, (
        "topology snapshot is a review aid; regenerate only after INV-7 passes"
    )
