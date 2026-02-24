# Upgrade to Python 3.14: adopt custom task factory support in asyncio

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & discoveries`, `Decision log`, and
`Outcomes & retrospective` must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

Status: DRAFT

## Purpose and big picture

After this change, Episodic async orchestration code will use Python 3.14 task
creation behaviour that reliably propagates `name` and `context` keyword
arguments through task factories and supports `eager_start`, enabling richer
task metadata, diagnostics, and execution control without custom wrappers at
each call site. Earlier Python 3.13.3 support for `**kwargs` propagation is
recognized, but this plan targets the Python 3.14 consistency guarantees. The
observable outcome is consistent, centralized task instrumentation and clearer
debugging for concurrent flows.

Success is visible when task factories receive custom kwargs from
`asyncio.create_task()` and `TaskGroup.create_task()`, tests validate this
behaviour, and migrated code paths keep functional behaviour unchanged.

## Constraints

- Keep business logic independent of event-loop internals.
- Preserve existing async behaviour in canonical ingestion paths.
- Avoid coupling domain modules to concrete asyncio task subclasses.
- Do not require non-stdlib async frameworks for this migration.
- Ensure all Python quality gates pass.

## Tolerances (exception triggers)

- Scope: if more than 10 modules require updates in first milestone, stop and
  escalate.
- Behaviour: if migrating a path changes task completion semantics or ordering,
  stop and escalate.
- Compatibility: if target runtime cannot reliably support task-factory kwargs
  in project execution environments, stop and escalate.
- Validation: if async tests become flaky after 2 stabilization attempts, stop
  and escalate.

## Risks

- Risk: custom task metadata may be overused and leak concerns into domain
  logic. Severity: medium. Likelihood: medium. Mitigation: keep metadata keys
  infrastructure-focused and optional.

- Risk: asynchronous test determinism may degrade.
  Severity: medium. Likelihood: medium. Mitigation: add focused, deterministic
  tests with explicit event-loop fixtures.

- Risk: project currently has limited async orchestration runtime beyond
  ingestion. Severity: low. Likelihood: high. Mitigation: begin with shared
  utility and one migrated path.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan created.
- [ ] Stage A: Define task metadata schema and first migration target.
- [ ] Stage B: Add fail-first tests for custom task factory kwargs.
- [ ] Stage C: Implement task factory utilities and migrate target path.
- [ ] Stage D: Run full gates and document usage guidance.

## Surprises & discoveries

- Observation: existing implemented async concurrency uses `asyncio.gather` in
  `episodic/canonical/ingestion_service.py` and has no custom task-factory
  infrastructure yet. Evidence: direct source inspection. Impact: a shared
  utility module is needed before broader migration.

- Observation: project memory Model Context Protocol (MCP) resources are
  unavailable in this session. Evidence: resource listing calls returned empty
  arrays. Impact: this plan is based on local repository and Python docs only.

## Decision log

- Decision: start with infrastructure utility plus one concrete async call path.
  Rationale: proves feature value while keeping blast radius controlled.
  Date/Author: 2026-02-24 / Codex.

- Decision: keep metadata optional and non-functional.
  Rationale: instrumentation should not alter orchestration semantics.
  Date/Author: 2026-02-24 / Codex.

## Outcomes & retrospective

Pending implementation.

Completion should provide a reusable task-factory pattern for upcoming
LangGraph/Celery integration work without destabilizing current ingestion code.

## Context and orientation

Python 3.14 extends task-creation plumbing so keyword arguments can flow
through `asyncio.create_task()` and `TaskGroup.create_task()` into custom loop
task factories. Episodic currently uses async orchestration in canonical
ingestion but lacks central task instrumentation.

Relevant files:

- `episodic/canonical/ingestion_service.py`
- New async utility module under `episodic/` to be introduced.
- Tests under `tests/` for async task-factory behaviour.
- Developer docs where concurrency guidance is captured.

## Plan of work

Stage A defines a minimal metadata contract for tasks, such as logical
operation name, correlation identifier, and optional priority hint. Select an
initial migration candidate where concurrent normalization currently uses
`asyncio.gather`.

Stage B writes tests first. Add unit tests that install a custom task factory,
create tasks with kwargs, and assert metadata reaches the factory and task
instances correctly. Include negative tests for unsupported keys or defaults.

Stage C implements utilities and migration. Add a shared helper for task
creation that forwards metadata kwargs, then migrate one code path (for
example, source normalization fan-out in ingestion service) to
`TaskGroup`/create_task with metadata. Keep result ordering and exception
behaviour explicit.

Stage D validates and documents. Run full gates and add short developer
guidance for when to use task metadata and when to avoid it.

## Concrete steps

Run from repository root.

1. Locate current async fan-out usage.

    rg -n "asyncio\.gather|create_task|TaskGroup" episodic tests

2. Add tests first for task-factory kwarg propagation.

    set -o pipefail; uv run pytest -v tests/test_async_task_factory.py \
      2>&1 | tee /tmp/py314-task-factory-targeted.log

3. Implement task factory utility and migrate one path.

4. Run full Python gates.

    set -o pipefail; make check-fmt 2>&1 | tee /tmp/py314-task-factory-check-fmt.log
    set -o pipefail; make lint 2>&1 | tee /tmp/py314-task-factory-lint.log
    set -o pipefail; make typecheck 2>&1 | tee /tmp/py314-task-factory-typecheck.log
    set -o pipefail; make test 2>&1 | tee /tmp/py314-task-factory-test.log

Expected success indicators:

- Custom task factory receives expected kwargs.
- Migrated async path preserves functional results.
- Full gates pass.

## Validation and acceptance

Acceptance criteria:

- A reusable custom task-factory support utility exists and is tested.
- At least one real async flow in Episodic uses metadata-aware task creation.
- No functional regressions in ingestion behaviour.
- `make check-fmt`, `make lint`, `make typecheck`, and `make test` pass.

## Idempotence and recovery

- Utility introduction is additive and can be disabled per call site.
- If flakiness appears, revert migrated path while keeping tests and utility for
  isolated hardening.
- All commands are safe to rerun; logs can be overwritten.

## Artifacts and notes

Capture during implementation:

- `git diff -- episodic tests docs`
- `/tmp/py314-task-factory-targeted.log`
- `/tmp/py314-task-factory-check-fmt.log`
- `/tmp/py314-task-factory-lint.log`
- `/tmp/py314-task-factory-typecheck.log`
- `/tmp/py314-task-factory-test.log`

## Interfaces and dependencies

- Use Python 3.14 asyncio task creation semantics and loop task factories.
- Keep metadata contract local to orchestration/infrastructure layer.
- Do not introduce new async runtime dependencies.

## Revision note

Initial draft created to plan adoption of Python 3.14 custom task-factory
kwargs propagation for improved async orchestration observability.
