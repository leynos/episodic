"""Routing tool executor for generation orchestration."""

import dataclasses as dc
import typing as typ

from ._dto import (
    ActionExecutionResult,
    GenerationOrchestrationRequest,
    PlannedAction,
    _coerce_single_action_kind,
)
from ._types import ActionKind, UnsupportedActionError

if typ.TYPE_CHECKING:
    from ._protocols import ToolExecutorPort


@dc.dataclass(slots=True)
class RoutingToolExecutor:
    """Dispatch planned actions to tool executors by normalized action kind."""

    routes: dict[ActionKind | str, ToolExecutorPort]

    def __post_init__(self) -> None:
        """Normalize the action-kind route table."""
        if not self.routes:
            msg = "routes must not be empty."
            raise ValueError(msg)
        normalized_routes: dict[ActionKind | str, ToolExecutorPort] = {}
        raw_routes: dict[ActionKind, tuple[ActionKind | str, ToolExecutorPort]] = {}
        for action_kind, executor in self.routes.items():
            normalized_action_kind = _coerce_single_action_kind(action_kind)
            if normalized_action_kind in normalized_routes:
                original_action_kind, original_executor = raw_routes[
                    normalized_action_kind
                ]
                msg = (
                    "route action kind collision after normalization: "
                    f"{original_action_kind!r} ({original_executor!r}) and "
                    f"{action_kind!r} ({executor!r}) both map to "
                    f"{normalized_action_kind!r}."
                )
                raise ValueError(msg)
            normalized_routes[normalized_action_kind] = executor
            raw_routes[normalized_action_kind] = (action_kind, executor)
        self.routes = normalized_routes

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Execute one planned action through its registered tool executor."""
        executor = self.routes.get(action.action_kind)
        if executor is None:
            msg = f"No tool executor registered for action kind: {action.action_kind}"
            raise UnsupportedActionError(msg)
        return await executor.execute(action, context)
