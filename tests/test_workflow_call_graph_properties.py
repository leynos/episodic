"""Property tests for the pull-request lane's reachability closure.

`workflow_call_graph.reachable` closes a call graph over its entries. It is
compared here with an independent reference: a fixed-point iteration that
widens the reached set until nothing changes, sharing nothing with the
implementation's work list. Generated graphs are bounded and finite. They
include multiple roots, branches, converging edges, cycles, self-calls,
duplicate calls and disconnected workflows, which a fixed example cannot all
show.
"""

import typing as typ

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.workflow_call_graph import UnresolvedWorkflowCallError, reachable

if typ.TYPE_CHECKING:
    import collections.abc as cabc

NAMES = [f"w{index}.yml" for index in range(8)]


@st.composite
def call_graphs(
    draw: st.DrawFn,
) -> tuple[dict[str, frozenset[str]], list[str]]:
    """Draw a closed call graph over a subset of names, and its entries."""
    nodes = draw(st.lists(st.sampled_from(NAMES), min_size=1, max_size=8, unique=True))
    calls = {
        node: frozenset(draw(st.lists(st.sampled_from(nodes), max_size=4)))
        for node in nodes
    }
    entries = draw(st.lists(st.sampled_from(nodes), max_size=4))
    return calls, entries


def _fixed_point(
    calls: cabc.Mapping[str, frozenset[str]], entries: list[str]
) -> frozenset[str]:
    """Widen the entry set by one call step until it stops growing."""
    reached = frozenset(entries)
    while True:
        widened = reached.union(*(calls[node] for node in reached))
        if widened == reached:
            return reached
        reached = widened


@given(call_graphs())
def test_the_closure_matches_a_fixed_point(
    graph: tuple[dict[str, frozenset[str]], list[str]],
) -> None:
    """Reach exactly what the fixed-point reference reaches, cycles included."""
    calls, entries = graph
    assert reachable(calls, entries) == _fixed_point(calls, entries), (
        f"closure disagrees with the reference for {calls!r} from {entries!r}"
    )


@given(call_graphs(), st.sampled_from(["gone.yml", "missing.yml"]))
def test_a_dangling_reachable_call_is_refused(
    graph: tuple[dict[str, frozenset[str]], list[str]], missing: str
) -> None:
    """Refuse a reachable call to a workflow the graph does not hold."""
    calls, _ = graph
    root = next(iter(calls))
    calls = {**calls, root: calls[root] | {missing}}
    with pytest.raises(UnresolvedWorkflowCallError, match=missing):
        reachable(calls, [root])
