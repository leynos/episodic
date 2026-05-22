"""LangGraph state container for generation orchestration."""

import dataclasses as dc
import importlib
import typing as typ

if typ.TYPE_CHECKING:
    from episodic.orchestration import _dto as dto
else:
    dto = importlib.import_module("episodic.orchestration._dto")


@dc.dataclass(slots=True)
class GenerationGraphState:
    """State carried by the structured generation LangGraph workflow.

    ``GenerationGraphState`` stores the values exchanged by the generation
    graph as it moves through initialize, plan, execute, and finish phases.
    Nodes should read the fields they require, return partial dictionaries for
    the fields they produce, and leave unrelated state untouched so LangGraph
    can merge each node result into the next state.

    Parameters
    ----------
    request : dto.GenerationOrchestrationRequest | None, optional
        Original generation request. It provides the user input and
        correlation identifier required by the plan, execute, suspend, and
        finish nodes. It is ``None`` only before graph invocation or in
        deliberately invalid node-validation tests.
    planner_result : dto.PlannerResult | None, optional
        Structured plan emitted by the plan node. The execute, suspend, and
        finish paths require this value before selecting actions or aggregating
        results.
    action_results : tuple[dto.ActionExecutionResult, ...], optional
        Ordered tool execution results emitted by the direct execute path. The
        finish node aggregates these results with ``planner_result``.
    orchestration_result : dto.GenerationOrchestrationResult | None, optional
        Final domain result emitted by the finish node on the direct
        plan -> execute -> finish path.
    suspended_result : dto.SuspendedWorkflowResult | None, optional
        Checkpoint metadata emitted by the suspend path when execution stops
        before side-effecting tool work.

    Attributes
    ----------
    request : dto.GenerationOrchestrationRequest | None
        The request currently attached to the graph state.
    planner_result : dto.PlannerResult | None
        The planner output currently attached to the graph state.
    action_results : tuple[dto.ActionExecutionResult, ...]
        The accumulated action execution outputs in traversal order.
    orchestration_result : dto.GenerationOrchestrationResult | None
        The completed orchestration result, when the finish node has run.
    suspended_result : dto.SuspendedWorkflowResult | None
        The checkpoint suspend result, when the checkpoint path has run.

    Raises
    ------
    None
        The dataclass does not enforce invariants at construction time. Graph
        nodes validate required fields when they run.

    Notes
    -----
    Graph-node authors should treat missing values as normal for earlier
    traversal phases. A node that produces a planner result should return
    ``{"planner_result": result}``; a node that produces action results should
    return ``{"action_results": results}``; and a finish node should return
    ``{"orchestration_result": result}``.

    Examples
    --------
    >>> state = GenerationGraphState(request=request)
    >>> state.request is request
    True
    """

    request: dto.GenerationOrchestrationRequest | None = None
    planner_result: dto.PlannerResult | None = None
    action_results: tuple[dto.ActionExecutionResult, ...] = ()
    orchestration_result: dto.GenerationOrchestrationResult | None = None
    suspended_result: dto.SuspendedWorkflowResult | None = None
