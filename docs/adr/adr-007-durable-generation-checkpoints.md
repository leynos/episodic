# ADR-007: Durable generation checkpoints

## Status

Accepted

## Context

Roadmap item `2.4.2` requires LangGraph orchestration to suspend and resume
reliably. The existing `2.4.1` implementation has a narrow in-process graph
that plans, executes one tool step, and aggregates the result. It does not
persist graph state or provide an idempotency contract around suspendable steps.

The design documents already name `CheckpointPort` and `TaskResumePort` as the
orchestration boundaries. The implementation must keep LangGraph, SQLAlchemy,
Celery, and provider adapters separated by those ports.

## Decision

Persist suspended generation workflows as platform-owned `WorkflowCheckpoint`
records in the `workflow_checkpoints` table.

The graph stores a checkpoint after planning and before the first
side-effecting execution step. The checkpoint payload contains the
orchestration request metadata and planner result as provider-neutral fields.
The graph returns `SuspendedWorkflowResult` with the checkpoint id, workflow
id, step name, and idempotency key. Resume accepts `ResumeWorkflowCommand`,
obtains the external task result through `TaskResumePort`, rebuilds the planner
state from the checkpoint, and aggregates a `GenerationOrchestrationResult`.

Idempotency keys are deterministic strings built from workflow id, workflow
type, step name, action id, and retry attempt. `CheckpointPort.save(...)`
preserves the first checkpoint recorded for a key and returns it to repeated
callers.

## Consequences

- The graph can prove suspend/resume behaviour without exposing LangGraph
  checkpoint classes in public contracts.
- Durable checkpoint state survives fresh unit-of-work and graph instances.
- Queue routing remains a later concern; `TaskResumePort` is the seam that
  future Celery callbacks will use.
- Planning may run again on repeated suspend attempts in this slice, but the
  side-effecting execution step is deduplicated by the checkpoint key.

## References

- Roadmap item `2.4.2` — `docs/roadmap.md`
- ExecPlan —
  `docs/execplans/2-4-2-add-lang-graph-suspend-and-resume-orchestration.md`
- Implementation — `episodic/orchestration/langgraph.py`,
  `episodic/orchestration/checkpoints.py`,
  `episodic/canonical/storage/workflow_checkpoints.py`
