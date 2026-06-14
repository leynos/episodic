"""Protocol definitions for generation orchestration boundaries.

The generation graph is deliberately written against these ports so domain
policy remains independent from LangGraph, SQLAlchemy, Celery, and LLM
provider adapters. `PlannerPort` and `ToolExecutorPort` drive the normal
plan/execute flow. `CheckpointPort` and `TaskResumePort` define the
suspend/resume seam: graph nodes persist typed checkpoint DTOs before
side-effecting work and later consume externally supplied action results
without knowing which queue, worker, or user interface produced them.
"""

import typing as typ

if typ.TYPE_CHECKING:
    from episodic.cost.ports import BillingPeriodKey, CostLedgerEntryId
    from episodic.cost.recorder import CostProviderOperation, ProviderCallRecord
    from episodic.generation import GuestBioSource, GuestBiosResult, ShowNotesResult
    from episodic.orchestration._dto import (
        ActionExecutionResult,
        GenerationOrchestrationRequest,
        PlannedAction,
        PlannerResult,
        ResumeWorkflowCommand,
        WorkflowCheckpoint,
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


class CostRecorderPort(typ.Protocol):
    """Application-level port for cost-ledger side effects."""

    async def pin_run_pricing(
        self,
        workflow_run_id: str,
        providers: tuple[CostProviderOperation, ...],
        billing_period_key: BillingPeriodKey,
    ) -> None:
        """Pin pricing snapshots for a run before provider calls are recorded."""

    async def record_provider_call(
        self,
        record: ProviderCallRecord,
    ) -> CostLedgerEntryId:
        """Record one priced provider call."""

    async def finalize_run(
        self,
        workflow_run_id: str,
        workflow_node: str | None,
    ) -> CostLedgerEntryId:
        """Write the final task roll-up for a completed run."""


class CheckpointPort(typ.Protocol):
    """Persistence port for suspended generation workflow checkpoints."""

    async def get(self, checkpoint_id: str) -> WorkflowCheckpoint | None:
        """Return a checkpoint by identifier, or None when it is unknown."""

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> WorkflowCheckpoint | None:
        """Return the checkpoint recorded for a suspendable step key."""

    async def save_or_reuse(self, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
        """Persist the checkpoint if the idempotency key is new.

        Return the existing record unchanged if the key was already written
        (first-write-wins).
        """

    async def mark_resumed(self, checkpoint_id: str) -> WorkflowCheckpoint:
        """Mark a checkpoint as resumed and return the updated record."""


class TaskResumePort(typ.Protocol):
    """Application-level port for resuming suspended workflow tasks."""

    async def resume(self, command: ResumeWorkflowCommand) -> ActionExecutionResult:
        """Return the externally supplied result for a suspended task."""


class _ShowNotesGeneratorPort(typ.Protocol):
    """Abstraction for show-notes generation used by the first tool executor."""

    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: dict[str, object] | None = None,
    ) -> ShowNotesResult:
        """Generate show notes from the supplied TEI context."""


class _GuestBiosGeneratorPort(typ.Protocol):
    """Abstraction for guest-bios generation used by the guest-bios executor."""

    async def generate(
        self,
        script_tei_xml: str,
        sources: tuple[GuestBioSource, ...],
        *,
        template_structure: dict[str, object] | None = None,
    ) -> GuestBiosResult:
        """Generate guest biographies from the supplied TEI and sources."""
