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
        self.routes = {
            _coerce_single_action_kind(action_kind): executor
            for action_kind, executor in self.routes.items()
        }

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
