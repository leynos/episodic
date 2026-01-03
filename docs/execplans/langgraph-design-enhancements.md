# LangGraph design enhancements plan

This ExecPlan is a living document. The sections `Progress`,
`Surprises and discoveries`, `Decision log`, and `Outcomes and retrospective`
must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

## Purpose and big picture

The outcome is an updated system design that incorporates the LangGraph and
Celery practices from the agentic systems and hexagonal architecture guidance,
plus a concrete cost accounting model drawn from the cost management document.
The roadmap is updated to reflect the new design commitments with measurable
work items and exit criteria. Success is observable when the design document
covers control and data plane separation, orchestration patterns for long-
running work, explicit hexagonal guardrails for graph nodes and Celery tasks,
and a task accounting based cost and budget model, while the roadmap includes
atomic tasks that deliver those capabilities.

## Progress

- [x] (2026-01-03 01:53Z) Extract improvement themes from the three reference
  documents and map them to existing design sections.
- [x] (2026-01-03 01:53Z) Draft design document updates for orchestration
  patterns, hexagonal guardrails, and cost accounting.
- [x] (2026-01-03 01:53Z) Draft roadmap updates that sequence the new design
  commitments into measurable tasks.
- [x] (2026-01-03 01:53Z) Validate formatting, Markdown linting, and Mermaid
  diagram checks.

## Surprises and discoveries

- Observation: `make nixie` required escalated permissions to launch the
  Mermaid CLI browser sandbox for diagram validation. Evidence: Nixie failed
  with Puppeteer sandbox errors until rerun with escalated permissions.
- Observation: Markdown lint fixes were required in existing LangGraph and cost
  management docs to satisfy fenced code block and heading rules. Evidence:
  `make fmt` reported MD036 and MD040 failures before updates.

## Decision log

- Decision: Expand the design document with sections for control and data
  plane separation, execution patterns, orchestration ports, and cost
  accounting. Rationale: These additions map directly to the LangGraph and
  Celery guidance and the task accounting model. Date/Author: 2026-01-03, Codex.
- Decision: Update the roadmap with Phase 3 execution pattern tasks and Phase 6
  budget and cost operations items. Rationale: Roadmap sequencing keeps the new
  design commitments measurable and aligned with delivery phases. Date/Author:
  2026-01-03, Codex.
- Decision: Fix Markdown lint errors in supporting LangGraph and cost
  management documents. Rationale: Quality gates require `make fmt` and
  `make markdownlint` to pass. Date/Author: 2026-01-03, Codex.
- Decision: Rename the hexagonal architecture guidance file to correct the
  spelling and update references. Rationale: Avoids broken links and
  inconsistent naming across documentation. Date/Author: 2026-01-03, Codex.
- Decision: Centralize orchestration guardrails in the system design and
  reference them from supporting docs. Rationale: Reduces the risk of
  divergence across documents. Date/Author: 2026-01-03, Codex.
- Decision: Align spelling and pronoun usage in supporting docs with the
  documentation style guide. Rationale: Ensures British English usage and
  removes first or second person pronouns from Markdown content. Date/Author:
  2026-01-03, Codex.

## Outcomes and retrospective

Updates landed in the design and roadmap documents, including control and data
plane guidance, execution patterns, orchestration port contracts, and cost
accounting requirements. Validation completed with formatting, linting, and
Mermaid checks; diagram rendering required an escalated sandbox run.

## Context and orientation

Key references:

- `docs/agentic-systems-with-langgraph-and-celery.md` outlines a two plane
  architecture, LangGraph checkpointing, Celery worker segregation, and suspend
  and resume patterns for long-running tasks, plus tool integration ideas such
  as Model Context Protocol (MCP).
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` enumerates boundary
  risks, enforcement strategies, and guidance for keeping orchestration logic
  out of the domain core.
- `docs/cost-management-in-langgraph-agentic-systems.md` describes task level
  cost accounting, budget enforcement, and anomaly handling for agent loops.
- `docs/episodic-podcast-generation-system-design.md` already defines LangGraph
  StateGraphs, Celery background tasks, and checkpointing in Postgres but does
  not yet document the execution patterns or cost accounting details.
- `docs/roadmap.md` provides the phased delivery plan that will need to include
  the new architecture and cost management work.

Term definitions used in this plan:

- Control plane: The orchestration layer that manages agent state and routing
  decisions, implemented with LangGraph.
- Data plane: The execution layer that performs heavy or blocking work, handled
  by Celery tasks and specialised workers.
- Suspend and resume pattern: An orchestration pattern where LangGraph pauses a
  graph with an interrupt, a Celery task completes work asynchronously, and a
  callback resumes the graph with results.
- Task accounting model: A cost tracking model that records per node or per
  task usage, aggregates cost in LangGraph state, and enforces budgets.
- Large language model (LLM): A model used for text generation via `LLMPort`.

## Plan of work

First, extend `docs/episodic-podcast-generation-system-design.md` to make the
control and data plane separation explicit in the architectural summary and
agent graph sections. Add material on Celery queue routing and worker pool
profiles for input- and output-bound workloads, plus a short rationale for the
RabbitMQ and Valkey (Redis-compatible) split between broker, result backend,
and optional checkpointer.

Next, expand the LangGraph integration guidance to incorporate the operational
patterns in the agentic systems document. Add a subsection that distinguishes
fire-and-forget tasks from suspend and resume tasks, describing the interrupt
and callback flow, idempotency keys, and a reconciliation sweep for orphaned
Celery tasks. Fold the hexagonal architecture guardrails into the existing
boundary enforcement section, including requirements that graph nodes and
Celery tasks only call ports, keep tasks small and idempotent, and keep
checkpoint state minimal compared to domain state stored in Postgres.

Then, incorporate the hybrid inference and tool integration guidance. Add a
short subsection that documents structured output for planning, tool calling
for execution, and model tiering for cost control. If MCP is adopted, document
it as an outbound adapter behind existing ports, with optional skill-based tool
loading to keep context size bounded.

Add a dedicated cost accounting section to the design document. Describe how
token usage, retry counts, and task costs are captured via callbacks, recorded
per task, and aggregated in LangGraph state. Define budget scopes (per user,
per episode run, per organization), budget enforcement hooks, and anomaly
controls such as loop caps, concurrency limits, and dead-letter queues for
budget-exceeded events. Update the configuration and tunables section and the
storage model list to include cost ledger and budget tables, plus cost metrics
in observability.

Finally, update `docs/roadmap.md` to include the new work items. Add atomic
tasks in Phase 3 for LangGraph and Celery execution patterns, port discipline
checks for graph nodes, and cost accounting instrumentation. Add tasks for
budget enforcement and cost dashboards in Phase 6 if they are treated as
operations concerns. Update exit criteria to include observable cost reporting
and budget guardrails.

## Concrete steps

1. Locate the relevant sections in the design document and roadmap.

    rg -n "Architectural Summary" docs/episodic-podcast-generation-system-design.md
    rg -n "LangGraph Integration Principles" docs/episodic-podcast-generation-system-design.md
    rg -n "State Persistence and Checkpointing" docs/episodic-podcast-generation-system-design.md
    rg -n "Configuration and Tunables" docs/episodic-podcast-generation-system-design.md
    rg -n "Observability" docs/episodic-podcast-generation-system-design.md
    rg -n "Intelligent content generation" docs/roadmap.md

2. Edit `docs/episodic-podcast-generation-system-design.md` and
   `docs/roadmap.md`, ensuring sentence case headings, 80 column wrapping, and
   expansions for uncommon acronyms such as Model Context Protocol (MCP).

3. Format Markdown to apply wrapping and table formatting.

    set -o pipefail
    timeout 300 make fmt 2>&1 | tee /tmp/make-fmt.log

4. Lint Markdown to validate style.

    set -o pipefail
    timeout 300 make markdownlint 2>&1 | tee /tmp/make-markdownlint.log

5. Validate Mermaid diagrams.

    set -o pipefail
    timeout 300 make nixie 2>&1 | tee /tmp/make-nixie.log

## Validation and acceptance

Acceptance requires all of the following:

- `docs/episodic-podcast-generation-system-design.md` documents the control and
  data plane split, suspend and resume orchestration, and worker pool routing.
- The design document codifies hexagonal guardrails for LangGraph nodes and
  Celery tasks, including idempotency, checkpoint state minimization, and
  explicit port usage.
- The design document includes a task accounting cost model with per task cost
  records, aggregated state fields, budget enforcement hooks, and anomaly
  protections.
- `docs/roadmap.md` includes atomic tasks and exit criteria for the above
  changes, written in measurable terms without time commitments.
- `make fmt`, `make markdownlint`, and `make nixie` complete successfully with
  logs captured under `/tmp`.

## Idempotence and recovery

The documentation edits are repeatable. If formatting or linting fails, adjust
the offending Markdown and re-run the relevant `make` target using the same
`set -o pipefail` and `tee` pattern. The log files in `/tmp` provide the last
failure context and can be overwritten safely.

## Artifacts and notes

- `/tmp/make-fmt.log` records formatting output.
- `/tmp/make-markdownlint.log` records Markdown lint results.
- `/tmp/make-nixie.log` records Mermaid validation output.

Example success indicator:

    make markdownlint
    …
    markdownlint: 0 errors

## Interfaces and dependencies

Document the following conceptual interfaces in the design update:

- `BudgetPort` for checking and reserving per user, per episode, and per
  organization budgets.
- `CostLedgerPort` for persisting per task cost entries and summarised run
  totals.
- `CheckpointPort` for saving and restoring LangGraph checkpoints.
- `TaskResumePort` for receiving Celery callback data and resuming a suspended
  StateGraph run.
- `LLMPort` should surface token usage metadata for accounting callbacks.

Record dependency expectations in the design document:

- RabbitMQ remains the Celery broker for durable task routing.
- Valkey (Redis-compatible) is available for Celery result backend and optional
  LangGraph checkpoint storage, while Postgres remains the system of record for
  domain and cost ledger data.
- LangGraph interrupt and command mechanisms are required for suspend and
  resume orchestration.

## Revision note

Initial plan created on 2026-01-03 to scope the design and roadmap updates.

Revised on 2026-01-03 to record completion status, validation results, and the
need for escalated Mermaid diagram rendering.

Revised on 2026-01-03 to capture review-driven updates: corrected filename,
centralized guardrails, and style guide alignment.
