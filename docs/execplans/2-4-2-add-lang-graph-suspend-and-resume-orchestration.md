# Add LangGraph suspend-and-resume orchestration

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: DRAFT

## Purpose / big picture

Roadmap item `2.4.2` adds durable LangGraph suspend-and-resume orchestration to
the Content Generation Orchestrator. After this change, a generation workflow
can save a checkpoint before pausing, return a typed suspended result to the
caller, and later resume from the persisted checkpoint without repeating
already-dispatched side effects.

This builds directly on roadmap item `2.4.1`, which introduced structured
planning, tool execution, and the in-process LangGraph seam in
`episodic/orchestration/`. It does not implement Celery queue routing from
`2.4.3`, cost ledger persistence from `2.4.4`, budget enforcement from `2.5.x`,
or public generation-run checkpoint APIs from `2.6.x`. It must, however, leave
clean ports and storage contracts for those later items.

Success is observable in these behaviours:

1. A LangGraph generation run can execute until a suspendable step, persist a
   durable checkpoint, and return a state that identifies the checkpoint,
   workflow step, and idempotency key.
2. Re-invoking the same suspendable step with the same idempotency key returns
   the existing checkpoint or recorded outcome instead of dispatching duplicate
   work.
3. A resume call loads the saved checkpoint, injects the task or editor result
   through a `TaskResumePort`, and continues the graph to the next node.
4. Checkpoint state survives a fresh graph instance and a fresh repository or
   unit-of-work instance, proving that state is persisted rather than held only
   in memory.
5. Unit tests, behavioural tests using Vidai Mock for inference calls, and
   property tests demonstrate the suspend/resume and idempotency invariants.
6. Documentation explains the new internal orchestration interface, user-visible
   behaviour, and design decision. Roadmap item `2.4.2` is marked done only
   after implementation and validation succeed.

## Constraints

- Preserve hexagonal architecture boundaries. Domain and application code may
  depend on ports, data transfer objects (DTOs), and orchestration helpers, but
  must not import Falcon resources, SQLAlchemy adapters, concrete OpenAI
  clients, or Celery workers directly.
- Keep LangGraph an internal orchestration mechanism. No public API may expose
  LangGraph classes, checkpoint implementation types, or framework-specific
  command objects.
- Add checkpoint persistence through ports owned by the orchestration or
  canonical boundary. Adapters must implement those ports; graph nodes must
  call the ports rather than concrete SQLAlchemy sessions or tables.
- Keep canonical artefacts out of checkpoint blobs where a canonical repository
  already owns them. Checkpoints may store orchestration state, node routing
  data, provider-neutral DTOs, and references to canonical artefact identifiers.
- Define idempotency keys for every suspendable workflow step before adding the
  persistence adapter. Keys must be deterministic from run identity, workflow
  type, step identity, action identity, and retry attempt where retry changes
  semantics.
- Use Vidai Mock for behavioural tests that exercise inference calls. Do not
  call live LLM providers.
- Add pytest unit tests for every new code unit, pytest-bdd behavioural tests
  for the observable suspend/resume workflow, and Hypothesis property tests for
  idempotency-key and state-transition invariants.
- Update `docs/episodic-podcast-generation-system-design.md`,
  `docs/users-guide.md`, and `docs/developers-guide.md` for the implemented
  behaviour. Add or update an ADR in `docs/adr/` for the durable design
  decision if the existing ADR does not already cover it.
- Do not mark `docs/roadmap.md` item `2.4.2` done until the implementation,
  documentation, and validation gates all pass.
- Run validation commands sequentially, not in parallel:
  `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie`.

## Tolerances (exception triggers)

- Scope: stop and escalate if the implementation requires more than 22 files or
  1500 net new lines before tests pass.
- Interface: stop and escalate if public signatures for `LLMPort`,
  `LLMRequest`, `LLMResponse`, `StructuredGenerationPlanner.plan(...)`,
  `ToolExecutorPort.execute(...)`, or the existing public orchestration DTOs
  must change incompatibly.
- Storage: stop and escalate if checkpoint persistence cannot be implemented
  without a database migration touching unrelated canonical tables.
- Dependency: stop and escalate if a new runtime dependency is required beyond
  packages already declared in `pyproject.toml`.
- Boundary: stop and escalate if a practical implementation requires graph
  nodes to import SQLAlchemy, Falcon, Celery tasks, or concrete provider
  adapters.
- Behaviour: stop and escalate if the same suspend/resume test cluster still
  fails after three implementation attempts.
- Ambiguity: stop and present options if checkpoint scope could reasonably mean
  either a pure LangGraph checkpointer only or a platform-owned
  `workflow_checkpoints` repository with materially different APIs.
- Roadmap coupling: stop and escalate if satisfying `2.4.2` requires landing
  queue routing from `2.4.3`, cost-ledger storage from `2.4.4`, or REST
  checkpoint endpoints from `2.6.x` in the same change.

## Risks

- Risk: LangGraph checkpoint APIs can leak into application or domain code.
  Severity: high. Likelihood: medium. Mitigation: keep framework-specific
  objects in `episodic/orchestration/langgraph.py` and expose provider-neutral
  DTOs and protocols from the orchestration package.

- Risk: idempotency keys may omit a field that distinguishes semantically
  different steps, causing false deduplication. Severity: high. Likelihood:
  medium. Mitigation: introduce a dedicated key builder with Hypothesis tests
  over workflow identifiers, action identifiers, step names, and retry values.

- Risk: checkpoint blobs may accidentally become a second canonical content
  store. Severity: high. Likelihood: medium. Mitigation: persist canonical
  artefacts through existing repositories and keep checkpoint payloads limited
  to graph control state and references.

- Risk: storage tests may become slow or brittle if they require a live
  Postgres service. Severity: medium. Likelihood: medium. Mitigation: follow
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` and existing
  `tests/canonical_storage/` fixtures for py-pglite-backed integration tests.

- Risk: behavioural tests with Vidai Mock may overfit to prompt wording rather
  than workflow behaviour. Severity: medium. Likelihood: medium. Mitigation:
  assert model ordering, suspend/resume state, and final output, but avoid
  matching full prompts.

- Risk: later queue routing may need Celery-specific metadata that `2.4.2`
  does not yet know. Severity: medium. Likelihood: medium. Mitigation: store a
  generic task envelope with optional `external_task_id`, `queue_name`, and
  `resume_token` fields without implementing routing.

## Progress

- [x] (2026-05-07 23:54Z) Loaded the `execplans`, `hexagonal-architecture`,
  `leta`, `vidai-mock`, `commit-message`, and `pr-creation` skills relevant to
  this planning task.
- [x] (2026-05-07 23:54Z) Confirmed the current branch is
  `feat/langgraph-resume-plan`, not the main branch.
- [x] (2026-05-07 23:54Z) Reviewed roadmap item `2.4.2`, adjacent roadmap
  items, the LangGraph integration principles, checkpointing design, cost
  accounting boundary, Vidai Mock behavioural test pattern, and the existing
  `2.4.1` ExecPlan.
- [x] (2026-05-07 23:54Z) Inspected the existing orchestration seam in
  `episodic/orchestration/generation.py`,
  `episodic/orchestration/langgraph.py`, `episodic/orchestration/_dto.py`, and
  `episodic/orchestration/_protocols.py`.
- [x] (2026-05-07 23:54Z) Drafted this pre-implementation ExecPlan for roadmap
  item `2.4.2`.
- [x] (2026-05-08 00:04Z) Ran planning-change validation gates:
  `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie` all passed.
- [ ] Await explicit approval before implementing the feature.
- [ ] Stage A: add fail-first tests for checkpoint DTOs, idempotency keys,
  persistence, graph suspension, graph resumption, Vidai Mock behaviour, and
  Hypothesis invariants.
- [ ] Stage B: implement orchestration DTOs and ports for checkpoint persistence
  and task resumption.
- [ ] Stage C: implement the in-memory adapter used by fast unit tests.
- [ ] Stage D: implement the durable SQLAlchemy checkpoint adapter and wire it
  through composition roots without leaking adapter types into graph nodes.
- [ ] Stage E: update LangGraph orchestration to suspend, persist checkpoints,
  resume from saved state, and deduplicate repeated step invocations.
- [ ] Stage F: update design, user, developer, and ADR documentation.
- [ ] Stage G: run all validation gates, mark roadmap item `2.4.2` done, and
  commit the implementation.

## Surprises & Discoveries

- Observation: `docs/episodic-podcast-generation-system-design.md` already
  names `CheckpointPort` and `TaskResumePort` as orchestration ports. Evidence:
  the "Orchestration ports and adapters" section lists both ports. Impact: the
  implementation should use those names rather than inventing alternative
  abstractions.

- Observation: the existing generation graph is intentionally minimal and
  in-process. Evidence: `episodic/orchestration/langgraph.py` compiles a
  `plan -> execute -> finish` graph without checkpointer configuration. Impact:
  `2.4.2` should extend this seam narrowly and avoid redesigning the whole
  content-generation workflow.

- Observation: `workflow_checkpoints` exists in the design document but not in
  the current SQLAlchemy model set. Evidence:
  `docs/episodic-podcast-generation-system-design.md` describes the table,
  while `episodic/canonical/storage/models.py` currently exposes canonical
  tables such as `approval_events` and `episode_templates`. Impact: the
  implementation probably needs a small migration and repository adapter
  dedicated to checkpoint records.

- Observation: `langgraph` is already declared as a runtime dependency.
  Evidence: `pyproject.toml` contains `langgraph>=1.1,<2.0`. Impact: the
  feature should not need a new orchestration dependency.

- Observation: Vidai Mock is already used by the generation orchestration BDD
  test to serve distinct planning and execution responses. Evidence:
  `tests/steps/test_generation_orchestration_steps.py` starts `vidaimock` and
  records `LLMRequest` values. Impact: the new behavioural test can extend the
  existing scenario style instead of introducing another mock server pattern.

- Observation: the planning-change gates pass, but `make fmt` currently invokes
  a legacy `markdownlint --fix` path that reports repository-wide MD013
  findings in existing documents. Evidence: `/tmp/fmt-episodic-2-4-2-plan.out`
  reported existing long-line findings, while `make check-fmt` and
  `make markdownlint` both passed afterward. Impact: implementation work should
  rely on the explicit gate commands unless the formatter target is repaired in
  a separate change.

## Decision Log

- Decision: Treat this document as a pre-implementation draft and do not begin
  feature implementation until explicit approval is given. Rationale: the
  `execplans` skill requires an approval gate after drafting an initial
  ExecPlan. Date/Author: 2026-05-07, Codex.

- Decision: Define checkpoint persistence and task resumption as ports in the
  orchestration boundary, with SQLAlchemy and in-memory implementations as
  adapters. Rationale: this follows the hexagonal dependency rule and matches
  the design document's `CheckpointPort` and `TaskResumePort` language.
  Date/Author: 2026-05-07, Codex.

- Decision: Keep `2.4.2` focused on durable checkpointing, resume, and
  idempotency, without implementing Celery queue routing, cost ledger storage,
  or public checkpoint REST endpoints. Rationale: those concerns have separate
  roadmap items and would blur the acceptance criteria for this vertical slice.
  Date/Author: 2026-05-07, Codex.

- Decision: Use a platform-owned checkpoint record as the durable system of
  record, even if LangGraph's native checkpointer participates internally.
  Rationale: the design requires auditable checkpoint events, TTL policies, and
  future API exposure. A port-owned record keeps those behaviours independent
  of any one LangGraph persistence implementation. Date/Author: 2026-05-07,
  Codex.

## Outcomes & Retrospective

This section is intentionally empty while the plan remains in draft. Update it
after each implementation milestone with the behaviour achieved, validation
evidence, gaps, and follow-up work.

## Context and orientation

The project is a Python 3.14 service for podcast generation. The generation
orchestration code lives in `episodic/orchestration/`. Roadmap item `2.4.1`
introduced a structured planner and tool executor:

- `episodic/orchestration/generation.py` contains
  `StructuredGenerationPlanner` and `StructuredPlanningOrchestrator`.
- `episodic/orchestration/langgraph.py` builds a small LangGraph graph with
  `GenerationGraphState`, `_plan_node`, `_execute_node`, `_finish_node`, and
  `build_generation_orchestration_graph(...)`.
- `episodic/orchestration/_dto.py` contains immutable DTOs such as
  `GenerationOrchestrationRequest`, `ExecutionPlan`, `PlannedAction`,
  `PlannerResult`, `ActionExecutionResult`, and `GenerationOrchestrationResult`.
- `episodic/orchestration/_protocols.py` currently defines `PlannerPort` and
  `ToolExecutorPort`.
- `episodic/generation/show_notes.py` provides the first concrete enrichment
  service used by the tool executor.
- `episodic/llm/ports.py` defines the provider-neutral `LLMPort` boundary.

"Suspend" means that the graph reaches a node that cannot complete immediately,
saves its state, records the external work or human decision it is waiting for,
and returns control to the caller. "Resume" means that a later input loads that
checkpoint and continues the graph from the paused point. "Idempotency" means
that retrying the same logical step with the same key does not duplicate side
effects, dispatches, or charges.

The canonical persistence layer lives under `episodic/canonical/storage/`.
Existing SQLAlchemy models are in `episodic/canonical/storage/models.py`,
repositories are in `episodic/canonical/storage/repositories.py` and related
files, and the unit-of-work is in `episodic/canonical/storage/uow.py`. Storage
ports are defined in `episodic/canonical/ports.py`. The implementation should
either extend this canonical storage boundary for workflow checkpoints or add a
small orchestration storage boundary that follows the same style.

Relevant documentation:

- `docs/roadmap.md` contains the `2.4.2` acceptance bullet.
- `docs/episodic-podcast-generation-system-design.md` contains the LangGraph
  integration principles, orchestration ports, checkpoint persistence, and cost
  accounting boundary.
- `docs/agentic-systems-with-langgraph-and-celery.md` explains the
  interrupt/resume pattern and callback shape.
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` describes boundary
  risks between graphs, queues, domain logic, and adapters.
- `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md`, and
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` define persistence and
  endpoint testing patterns.

## Plan of work

Stage A is test-first scaffolding. Add unit tests in new or existing files such
as `tests/test_orchestration_checkpointing.py`,
`tests/test_orchestration_resume.py`, and
`tests/test_orchestration_properties.py`. The first tests should describe the
DTOs and ports before implementation exists:

- checkpoint records reject blank run, workflow, step, and idempotency fields;
- the idempotency-key builder is deterministic for identical inputs and changes
  when workflow, step, action, or retry fields change;
- a checkpoint repository can save, fetch, and mark checkpoints resumed;
- a resume service rejects unknown, expired, or already-resumed checkpoints;
- the graph returns a suspended result before a suspendable action and resumes
  after a matching payload arrives;
- property tests prove repeated save/resume calls for the same idempotency key
  converge on one checkpoint state.

Extend `tests/features/generation_orchestration.feature` or add
`tests/features/generation_suspend_resume.feature` with a pytest-bdd scenario
using Vidai Mock. The scenario should start Vidai Mock, run a generation
request that reaches a suspendable inference-backed action, observe a suspended
checkpoint result, construct a fresh graph/repository instance, resume the
checkpoint, and assert that the final orchestration result includes one planner
call and no duplicate execution dispatch for the idempotent step.

Stage B defines the internal contracts. Add DTOs to
`episodic/orchestration/_dto.py` or a focused
`episodic/orchestration/checkpointing.py` module:

- `WorkflowCheckpoint` with `checkpoint_id`, `run_id`, `episode_id`,
  `workflow_type`, `step_name`, `action_id`, `idempotency_key`, `status`,
  `state_payload`, `external_task_id`, `resume_payload`, `created_at`,
  `updated_at`, and `expires_at`;
- `WorkflowCheckpointStatus` with values such as `pending`, `resumed`,
  `expired`, and `failed`;
- `SuspendedWorkflowResult` with the checkpoint identifier, idempotency key,
  waiting reason, and optional task envelope;
- `ResumeWorkflowCommand` with checkpoint identifier, idempotency key, and
  provider-neutral payload.

Add ports to `episodic/orchestration/_protocols.py`:

```python
class CheckpointPort(typ.Protocol):
    async def reserve_or_get(
        self,
        checkpoint: WorkflowCheckpoint,
    ) -> WorkflowCheckpoint:
        """Persist a checkpoint or return the existing idempotent record."""

    async def get(
        self,
        checkpoint_id: str,
    ) -> WorkflowCheckpoint | None:
        """Load a checkpoint by identifier."""

    async def mark_resumed(
        self,
        checkpoint_id: str,
        resume_payload: dict[str, object],
    ) -> WorkflowCheckpoint:
        """Record the payload that resumed a checkpoint."""
```

```python
class TaskResumePort(typ.Protocol):
    async def resume(
        self,
        command: ResumeWorkflowCommand,
    ) -> GenerationOrchestrationResult | SuspendedWorkflowResult:
        """Resume a suspended generation workflow from a checkpoint."""
```

The exact signatures may evolve during implementation, but the key boundary is
that callers use orchestration DTOs and ports, not LangGraph or SQLAlchemy
types.

Stage C implements fast in-memory behaviour. Add an in-memory checkpoint store
under `episodic/orchestration/` or test helpers so unit tests can exercise
deduplication, expiry, and resume transitions without a database. Use this to
settle the DTO invariants and graph behaviour before adding SQLAlchemy.

Stage D implements durable persistence. Add a `workflow_checkpoints` model and
migration following existing canonical storage conventions. A likely table
shape is:

- `id`: UUID primary key;
- `run_id`: UUID or string, indexed;
- `episode_id`: UUID, indexed when available;
- `workflow_type`: bounded string;
- `step_name`: bounded string;
- `action_id`: bounded string;
- `idempotency_key`: bounded string with a uniqueness constraint;
- `status`: bounded enum or string;
- `state_payload`: JSONB;
- `external_task_id`: nullable string;
- `resume_payload`: nullable JSONB;
- `created_at`, `updated_at`, `expires_at`: timezone-aware timestamps.

Add repository methods through a port-owned adapter. The repository must make
`reserve_or_get(...)` atomic using a uniqueness constraint on
`idempotency_key`, so two concurrent retries converge on one record. Use
py-pglite-backed tests that create a checkpoint, open a fresh unit of work,
fetch the checkpoint, and resume it.

Stage E extends LangGraph orchestration. Update
`episodic/orchestration/langgraph.py` so graph construction can receive a
`CheckpointPort` and optional suspend policy. The implementation should keep
the existing immediate `plan -> execute -> finish` path working by default, and
add a new path for suspendable actions. At the suspension point, the node
should:

1. derive the idempotency key from run/workflow/step/action/retry identity;
2. save the graph state and task envelope through `CheckpointPort`;
3. return a `SuspendedWorkflowResult` or state field rather than calling the
   side-effecting executor again;
4. log the checkpoint and idempotency key.

Add a resume service or graph helper that accepts `ResumeWorkflowCommand`,
loads the checkpoint, validates status and idempotency key, reconstructs the
graph input, injects the resume payload, marks the checkpoint resumed, and
continues execution. If using `langgraph.types.Command` internally, keep it
inside the LangGraph module and return only Episodic DTOs to callers.

Stage F updates documentation. In
`docs/episodic-podcast-generation-system-design.md`, record the concrete
checkpoint record shape, lifecycle, idempotency-key fields, and resume
semantics. In `docs/developers-guide.md`, explain how maintainers add a
suspendable orchestration step without violating ports/adapters boundaries. In
`docs/users-guide.md`, describe any service-visible behaviour, such as a run
being reported as suspended or resumable. Add an ADR such as
`docs/adr/adr-006-langgraph-suspend-resume-checkpointing.md` if the decision is
not naturally appended to ADR-005.

Stage G validates and completes. Run formatting and gates sequentially. Mark
`docs/roadmap.md` item `2.4.2` done only after all gates pass. Update this
ExecPlan's `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` sections with actual evidence. Commit the feature as
one or more atomic commits.

## Concrete steps

Work from the repository root:

```plaintext
/home/leynos/.lody/repos/github---leynos---episodic/worktrees/0582a2ca-e6ad-47bb-9b7b-fee35bdb5bc5
```

Confirm branch and clean working tree before implementation:

```bash
git branch --show-current
git status --short
```

Expected branch after the planning PR setup:

```plaintext
2-4-2-add-lang-graph-suspend-and-resume-orchestration
```

Add the fail-first test files and run the focused tests. Use `tee` for logs:

```bash
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 uv run pytest \
  tests/test_orchestration_checkpointing.py \
  tests/test_orchestration_resume.py \
  tests/test_orchestration_properties.py \
  tests/steps/test_generation_suspend_resume_steps.py \
  2>&1 | tee /tmp/test-episodic-2-4-2-focused.out
```

Expected result before implementation:

```plaintext
FAILED ... checkpointing/resume symbols are not implemented
```

Implement Stage B through Stage E in small commits, rerunning the focused tests
after each stage. When focused tests pass, run the full required gates
sequentially:

```bash
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-2-4-2.out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-2-4-2.out
make lint 2>&1 | tee /tmp/lint-episodic-2-4-2.out
make test 2>&1 | tee /tmp/test-episodic-2-4-2.out
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-2-4-2.out
make nixie 2>&1 | tee /tmp/nixie-episodic-2-4-2.out
```

Expected result after implementation:

```plaintext
... passed
```

The exact number of tests may change as the branch evolves; record the final
counts and log paths in this ExecPlan.

## Validation and acceptance

The feature is accepted when all of the following are true:

- Unit tests prove checkpoint DTO validation, idempotency-key construction,
  repository save/load/resume transitions, and resume-service error handling.
- Behavioural pytest-bdd coverage uses Vidai Mock and demonstrates a run that
  suspends, persists a checkpoint, resumes from a fresh graph/repository
  instance, and avoids duplicate idempotent dispatch.
- Hypothesis tests prove key and state-transition invariants over generated
  workflow IDs, action IDs, step names, retry values, and valid transition
  sequences.
- The existing immediate orchestration path from `2.4.1` still works without
  requiring checkpoint configuration.
- Durable checkpoint tests prove the SQLAlchemy adapter can save, reload, and
  mark checkpoints resumed through a fresh unit of work.
- `docs/episodic-podcast-generation-system-design.md` records the concrete
  design decision, `docs/developers-guide.md` records internal practice, and
  `docs/users-guide.md` records user-visible behaviour.
- `docs/roadmap.md` marks item `2.4.2` as done.
- `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie` all pass sequentially.

## Idempotence and recovery

All implementation steps should be re-runnable. Tests may create temporary
Vidai Mock configuration under pytest-managed `tmp_path` directories and must
clean up child processes in fixtures. The checkpoint repository must tolerate a
retry after a partial failure by returning the existing record for the same
idempotency key.

If a migration or repository change fails, roll forward with a corrective
migration or patch rather than deleting user data. Do not run destructive git
or database commands without explicit approval. If a checkpoint is persisted
but the graph resume fails, keep the checkpoint in a non-resumed state with
diagnostic metadata so a later retry can resume or mark it failed.

## Artifacts and notes

Useful existing entrypoints:

```plaintext
episodic/orchestration/langgraph.py
episodic/orchestration/generation.py
episodic/orchestration/_dto.py
episodic/orchestration/_protocols.py
episodic/canonical/storage/models.py
episodic/canonical/storage/uow.py
tests/test_generation_orchestration_langgraph.py
tests/steps/test_generation_orchestration_steps.py
tests/features/generation_orchestration.feature
```

Current design anchors:

```plaintext
docs/episodic-podcast-generation-system-design.md#langgraph-integration-principles
docs/episodic-podcast-generation-system-design.md#state-persistence-and-checkpointing
docs/agentic-systems-with-langgraph-and-celery.md
docs/langgraph-and-celery-in-hexagonal-architecture.md
```

## Interfaces and dependencies

Use existing dependencies from `pyproject.toml`: `langgraph`, `sqlalchemy`,
`alembic`, `pytest`, `pytest-bdd`, `hypothesis`, and Vidai Mock as an external
test executable. Do not add a runtime dependency unless the dependency
tolerance is explicitly approved.

The implementation must leave these interfaces available to application code:

```python
class CheckpointPort(typ.Protocol):
    async def reserve_or_get(
        self,
        checkpoint: WorkflowCheckpoint,
    ) -> WorkflowCheckpoint:
        """Persist a checkpoint or return the existing idempotent record."""

    async def get(
        self,
        checkpoint_id: str,
    ) -> WorkflowCheckpoint | None:
        """Load a checkpoint by identifier."""

    async def mark_resumed(
        self,
        checkpoint_id: str,
        resume_payload: dict[str, object],
    ) -> WorkflowCheckpoint:
        """Record the payload that resumed a checkpoint."""
```

```python
class TaskResumePort(typ.Protocol):
    async def resume(
        self,
        command: ResumeWorkflowCommand,
    ) -> GenerationOrchestrationResult | SuspendedWorkflowResult:
        """Resume a suspended generation workflow from a checkpoint."""
```

The exact method names may change if the implementation discovers a cleaner
local convention, but the semantic contract must remain: checkpointing and
resumption are port-driven, idempotent, durable, and independent of concrete
LangGraph or SQLAlchemy types.

Revision note 2026-05-07: Created the initial draft ExecPlan for roadmap item
`2.4.2` from the roadmap, design documents, existing `2.4.1` orchestration
code, hexagonal architecture guidance, and Vidai Mock testing requirements.
This is a pre-implementation plan and requires explicit approval before code
implementation begins.

Revision note 2026-05-08: Added validation evidence for the planning-only
change and recorded the formatter-target discovery. This does not change the
implementation sequence, but it gives the next implementer the exact branch
gate status and a known documentation tooling caveat.
