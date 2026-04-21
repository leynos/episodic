# ADR-005: Structured planning and tool execution for generation orchestration

## Status

Accepted

## Context

Roadmap item `2.4.1` requires the generation pipeline to plan its own work
using structured output, then execute enrichment work through controlled
tool-calling patterns. The surrounding roadmap already splits checkpoint
persistence, queue routing, and cost-ledger storage into later steps, so this
decision needs to capture the first implementation slice without absorbing
those adjacent concerns.

Three constraints shape the solution:

- LangGraph remains an internal orchestration mechanism rather than a new
  integration boundary.
- `LLMPort` remains the only provider-facing inference port for current
  planning and enrichment steps.
- Existing enrichment logic such as show-notes generation must not be invoked
  by direct cross-adapter imports from LangGraph nodes.

## Decision

Implement roadmap item `2.4.1` with a dedicated `episodic/orchestration/`
package that separates planning, execution, and graph wiring.

The accepted design is:

- Use strict JSON-only planner output and parse it into typed DTOs:
  `ExecutionPlan`, `PlannedAction`, and `PlannerResult`.
- Represent model tiering as configuration, not billing logic.
  `GenerationOrchestrationConfig` selects one planning model and one execution
  model, and the planner result records those selections in the returned plan.
- Execute enrichment actions through a single application-level
  `ToolExecutorPort.execute(...)` operation rather than importing concrete
  generators directly into LangGraph nodes.
- Ship show notes as the first concrete tool by implementing
  `ShowNotesToolExecutor`, which adapts planned `generate_show_notes` actions
  onto the existing `ShowNotesGenerator`.
- Provide a small in-process LangGraph wrapper that sequences
  `plan -> execute -> finish`, leaving checkpointing, suspend-and-resume, and
  queue dispatch to later roadmap items.

## Rationale

Strict planner output makes the orchestration contract testable and keeps
malformed model output from leaking deeper into the workflow. That aligns with
existing local patterns in Pedante and show notes, where large language model
(LLM) responses are validated immediately and converted into typed results.

Routing execution through `ToolExecutorPort` preserves the hexagonal boundary.
LangGraph nodes depend on ports and typed orchestration state, whilst the
actual show-notes tool remains a separate application service that continues to
depend only on `LLMPort`.

Configuration-based model tiering satisfies the current roadmap need for cost
control without prematurely introducing `PricingCataloguePort`,
`CostLedgerPort`, or `BudgetPort` persistence. The current implementation can
select a stronger planning model and a cheaper execution model now, and later
roadmap items can layer pricing and accounting on top of that seam.

Show notes are the first shipped tool because they already exist, already use
`LLMPort`, and already expose strict JSON parsing and behavioural coverage via
Vidai Mock. That makes them the lowest-risk way to prove the tool-calling
pattern before chapter markers, guest biographies, or sponsorship copy exist.

## Consequences

### Positive

- The repository now has a general generation-orchestration seam beyond the
  Pedante-specific graph.
- Planner output, execution routing, and model-tier selection are covered by
  unit tests and a live Vidai Mock behaviour scenario.
- Future enrichment tools can slot into the same planning contract without
  changing the planner schema.

### Negative

- The first tool layer is intentionally narrow and does not yet provide a full
  plugin registry or external tool catalogue.
- Checkpoint persistence, Celery routing, and cost-ledger writes are still
  separate implementation steps and remain unavailable in this slice.

### Neutral

- LangGraph remains an implementation detail for orchestration control flow.
  The durable integration boundaries are still the application ports and DTOs.

## Deferred work

The following responsibilities remain outside ADR-005 and continue to belong to
later roadmap items:

- `2.4.2` LangGraph suspend-and-resume checkpointing
- `2.4.3` Celery queue routing and worker isolation
- `2.4.4` hierarchical cost-ledger persistence and metering
- `2.5.x` pricing-catalogue, SLA ingestion, and budget enforcement

## References

Roadmap item `2.4.1` in `docs/roadmap.md`.[^1] ExecPlan:
`docs/execplans/2-4-1-structured-output-planning-and-tool-calling-execution.md`.
 [^2] Implementation: `episodic/orchestration/generation.py` and
`episodic/orchestration/langgraph.py`.[^3] Tests:
`tests/test_generation_orchestration.py`,
`tests/test_generation_orchestration_langgraph.py`,
`tests/features/generation_orchestration.feature`, and
`tests/steps/test_generation_orchestration_steps.py`.[^4]

[^1]: Roadmap item `2.4.1` in `docs/roadmap.md`
[^2]: ExecPlan:
  `docs/execplans/2-4-1-structured-output-planning-and-tool-calling-execution.md`
[^3]: Implementation: `episodic/orchestration/generation.py` and
  `episodic/orchestration/langgraph.py`
[^4]: Tests: `tests/test_generation_orchestration.py`,
  `tests/test_generation_orchestration_langgraph.py`,
  `tests/features/generation_orchestration.feature`, and
  `tests/steps/test_generation_orchestration_steps.py`
