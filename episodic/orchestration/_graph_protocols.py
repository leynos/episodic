"""Provider-neutral ports used by graph nodes and graph construction."""

import typing as typ

if typ.TYPE_CHECKING:
    from ._dto import (
        ActionExecutionResult,
        GenerationOrchestrationRequest,
        PlannedAction,
        PlannerResult,
    )


class ToolExecutorPort(typ.Protocol):
    """Port for executing planned enrichment actions."""

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Execute one planned action against the generation context."""


class PlannerPort(typ.Protocol):
    """Port for producing a structured execution plan."""

    async def plan(
        self,
        request: GenerationOrchestrationRequest,
    ) -> PlannerResult:
        """Return a typed execution plan for the generation request."""
