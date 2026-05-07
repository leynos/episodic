"""Protocol definitions for generation orchestration boundaries."""

import typing as typ

if typ.TYPE_CHECKING:
    from episodic.generation import ShowNotesResult
    from episodic.orchestration._dto import (
        ActionExecutionResult,
        GenerationOrchestrationRequest,
        PlannedAction,
        PlannerResult,
    )


class ToolExecutorPort(typ.Protocol):
    """Application-level port for executing planned enrichment actions."""

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Execute one planned action against the available generation context."""


class PlannerPort(typ.Protocol):
    """Application-level port for structured orchestration planning."""

    async def plan(
        self,
        request: GenerationOrchestrationRequest,
    ) -> PlannerResult:
        """Return a typed execution plan for the supplied generation request."""


class _ShowNotesGeneratorPort(typ.Protocol):
    """Abstraction for show-notes generation used by the first tool executor."""

    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: dict[str, object] | None = None,
    ) -> ShowNotesResult:
        """Generate show notes from the supplied TEI context."""
