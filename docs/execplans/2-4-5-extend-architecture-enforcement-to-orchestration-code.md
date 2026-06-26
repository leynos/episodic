# Extend architecture enforcement to orchestration code (2.4.5)

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: IN PROGRESS

## Purpose / big picture

Episodic enforces hexagonal architecture (ports and adapters) with the Hecate
import checker, run by `make check-architecture` (a dependency of `make lint`)
against the `[tool.hecate]` configuration in `pyproject.toml`. Today the
orchestration code is lumped into the generic `application` group and the Celery
worker tasks sit in the permissive `inbound_adapter` group. The system design
explicitly reserved orchestration-specific enforcement for this roadmap slice
(see `docs/episodic-podcast-generation-system-design.md`, the "Hexagonal
architecture enforcement" section, which states that "direct adapter access is
reserved for the later orchestration-specific enforcement slice").

Roadmap item 2.4.5 (`docs/roadmap.md`) asks us to:

1. Validate LangGraph nodes depend on ports only.
2. Validate Celery tasks depend on ports only.
3. Audit checkpoint payload boundaries.

After this change, a developer who tries to import a concrete adapter, storage
or vendor SDK into a LangGraph node, a Celery task, or a checkpoint payload DTO
will see `make lint` fail with a Hecate `ARCH001` violation, and a structural
test will fail if a checkpoint payload DTO grows a field whose type is not
provider-neutral (for example an ORM model or a canonical aggregate entity).
Success is observable by running `make lint` and `make test`: new
architecture fixtures and tests fail before the enforcement is added and pass
after, while the production `hecate check` continues to pass.

This work is preventative: the current orchestration code is already free of
adapter imports, so the new rules pass once the supporting refactors land. The
value is named, fixtured, regression-tested boundaries plus two genuine
boundary fixes (Celery tasks reaching a `kombu`-coupled module for an enum, and
checkpoint DTOs coupling to application-tier generation DTOs).

## Constraints

Hard invariants that must hold throughout implementation. Violation requires
escalation, not a workaround.

- The production `hecate check` (via `make check-architecture` and `make lint`)
  must pass at the end of every milestone. Never weaken a rule to make
  unrelated code pass; fix the boundary instead.
- Hecate behaviour is fixed at the pinned commit
  `46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12`. Do not bump the Hecate pin in
  this slice. The enforcement model is allow-list only, first-match by config
  order, with no per-rule identifiers; design within those limits.
- Public, importable names that other packages already consume must remain
  importable from their current modules. In particular the orchestration
  barrel `episodic.orchestration.__init__` and the worker barrel
  `episodic.worker.__init__` must keep re-exporting every symbol they export
  today (verify with `leta refs <symbol>` before moving a definition).
- No single code file may exceed 400 lines (AGENTS.md). `episodic/orchestration/
  langgraph.py` is already 460 lines; any split must leave each resulting file
  under 400 lines.
- Domain purity: orchestration and worker code must not gain imports of
  transport, storage, ORM, or vendor SDK modules. Cross-adapter imports remain
  forbidden.
- All commentary and documentation use en-GB-oxendict spelling, except where
  quoting external API names.
- Every milestone must pass `make check-fmt`, `make typecheck`, `make lint`,
  and `make test` before its CodeRabbit review, and all CodeRabbit concerns
  must be cleared before the next milestone begins.

## Tolerances (exception triggers)

Adjust per milestone; stop and escalate when a threshold is breached.

- Scope: if a single milestone requires touching more than 25 files or more
  than 600 net lines of production code (excluding tests and fixtures), stop
  and escalate.
- Interface: if making a node or task ports-only would require changing a
  public function or class signature that another package imports, stop and
  escalate with the call sites (from `leta refs`).
- Dependencies: if any new runtime dependency is required, stop and escalate.
  This slice should add no new runtime dependencies.
- Hecate expressivity: if a required rule cannot be expressed in Hecate without
  more than two `[[tool.hecate.ignore_imports]]` entries, stop and escalate;
  the coupling probably needs a refactor rather than an ignore.
- Iterations: if a milestone's gate suite still fails after 3 focused attempts,
  stop and escalate with the failing transcript.
- Ambiguity: if the "ports only" interpretation in the Decision Log conflicts
  with a reviewer's expectation, stop and reconcile before proceeding.

## Risks

- Risk: Hecate counts `TYPE_CHECKING`-guarded and function-body imports as
  dependencies (confirmed from source: it walks the whole AST with `ast.walk`
  and has no type-only exemption). A ports-only group will trip on a type-only
  import of an application DTO.
  Severity: high. Likelihood: high.
  Mitigation: design groups so type-only imports stay within the allowed set,
  or break the coupling by extracting a provider-neutral DTO core. Use a single
  documented `[[tool.hecate.ignore_imports]]` edge only as a last resort, paired
  with the structural test as the binding guarantee.

- Risk: Ungrouped modules inside the `episodic` root are invisible to Hecate
  (imports of them are silently allowed, and they are not checked). A future
  adapter placed in an ungrouped module would bypass enforcement.
  Severity: medium. Likelihood: low.
  Mitigation: ensure every adapter-bearing module the orchestration or worker
  code can reach is matched by a group prefix; add a regression fixture proving
  an adapter import is caught.

- Risk: Splitting `langgraph.py` or moving DTO definitions breaks an import that
  another package relies on.
  Severity: medium. Likelihood: medium.
  Mitigation: keep barrels (`__init__.py`) re-exporting all current names;
  verify every moved symbol with `leta refs` before and after; rely on the full
  test suite plus `make typecheck`.

- Risk: First-match ordering mistakes silently mis-classify a module (for
  example a new specific prefix placed after a broader one never matches).
  Severity: medium. Likelihood: medium.
  Mitigation: place specific prefixes before broader ones, mirror the existing
  composition-root-before-adapter convention, and add fixtures that would fail
  under a mis-ordering.

- Risk: The checkpoint DTO decoupling proves more invasive than expected because
  `ActionExecutionResult` transitively references generation types.
  Severity: medium. Likelihood: medium.
  Mitigation: if a clean ports-only checkpoint group is not reachable within
  tolerance, scope the Hecate group to the genuinely neutral payload modules,
  record a single governed `ignore_imports` edge, and make the structural
  reflection test the primary guarantee. Escalate if more than two ignores are
  needed.

## Progress

- [x] M0 Orientation and red harness (fixtures and failing tests, no
      production changes).
- [x] M1 Dedicated `orchestration` Hecate group and node/builder split.
- [x] M2 Celery task enforcement and `WorkloadClass` extraction.
- [x] M3 Checkpoint payload boundary audit (Hecate group plus structural and
      property tests).
- [x] M4 Behavioural tests, snapshots, documentation, and roadmap update.

2026-06-26: Rebasing the branch onto `origin/main` completed cleanly with no
conflicts. Post-rebase gates passed: `make check-fmt`, `make test`,
`make typecheck`, and `make lint`. The branch was force-pushed with lease, the
PR title was updated to remove the `Plan:` prefix, and the PR references now
point at the active Lody session.

2026-06-26: M0 added the fixture-only orchestration Hecate groups, synthetic
node/task/checkpoint fixtures, and the strict-xfailed production group
expectation. Focused architecture tests passed with `30 passed, 1 xfailed`.
The full milestone gates passed: `make check-fmt`, `make typecheck`,
`make lint`, and `make test` (`1020 passed, 3 skipped, 1 xfailed`).
CodeRabbit review completed with 0 findings.

2026-06-26: M1 split `episodic/orchestration/langgraph.py` into
`_graph_nodes.py` for plan/execute/finish node functions, `_graph_builder.py`
for LangGraph assembly plus callback and cost wiring, and a 57-line
compatibility barrel that preserves the historical `langgraph` import path.
The production Hecate `orchestration` group is now ordered before
`application` and scoped to `_graph_builder`, `_graph_nodes`, and `langgraph`.
Focused validation passed with `68 passed, 1 xfailed`. The full milestone
gates passed: `make check-fmt`, `make typecheck`, `make lint`, and
`make test` (`1020 passed, 3 skipped, 1 xfailed`). CodeRabbit review completed
with 0 findings.

2026-06-26: M2 extracted `WorkloadClass` to the provider-neutral
`episodic/worker/workloads.py` module, retargeted task/runtime imports to that
module, and kept `episodic.worker.WorkloadClass` plus
`episodic.worker.topology.WorkloadClass` importable. The production Hecate
config now classifies `episodic.worker.workloads` as `domain_ports` and
`episodic.worker.tasks` as `orchestration_tasks`, ordered before
`inbound_adapter`. Focused validation passed with `56 passed, 1 xfailed`.
The full milestone gates passed: `make check-fmt`, `make typecheck`,
`make lint`, and `make test` (`1020 passed, 3 skipped, 1 xfailed`).
CodeRabbit review completed with 0 findings.

2026-06-26: M3 extracted provider-neutral payload DTOs and normalisation
helpers into `episodic/orchestration/_payload_dto.py`, retargeted checkpoint
payload and checkpoint DTO modules away from the application-coupled `_dto`
barrel, and kept existing public orchestration imports working through
compatibility aliases. The production Hecate config now declares
`orchestration_checkpoint` before `orchestration`, and checkpoint modules may
only import their own group plus `domain_ports`. `WorkflowCheckpoint` now
rejects non-JSON payload values, and
`tests/test_checkpoint_payload_boundaries.py` adds a structural DTO field audit
plus a Hypothesis JSON round-trip property. Focused validation passed with
`88 passed`. The full milestone gates passed: `make check-fmt`,
`make test` (`1024 passed, 3 skipped`), `make typecheck`, and `make lint`.
CodeRabbit review completed with 0 findings.

2026-06-26: M4 extended the architecture BDD feature with clean orchestration,
LangGraph-node, Celery-task, and checkpoint-payload scenarios; added a
normalised `hecate check --format json` snapshot covering representative
orchestration violations; and added a direct Vidai Mock-backed LangGraph
`plan -> execute -> finish` behavioural test. Focused validation passed
with `33 passed` before documentation updates. Documentation now records
ADR-016, the node/builder split, the `orchestration_nodes`,
`orchestration_tasks`, and `orchestration_checkpoint` groups, the checkpoint
payload audit, and roadmap item `2.4.5` as complete. The full milestone gates
passed: `make check-fmt`, `make test` (`1030 passed, 3 skipped`),
`make typecheck`, `make lint`, `make markdownlint`, and `make nixie`.
CodeRabbit review completed with 0 findings.

## Surprises & discoveries

- Observation: Hecate counts imports inside `if TYPE_CHECKING:` blocks and
  inside function bodies identically to module-level imports.
  Evidence: source review of the pinned Hecate commit; `collect_imports` uses
  `ast.walk` with no guard inspection.
  Impact: ports-only groups must be reachable for type-only imports too; drives
  the DTO-core decoupling in M3.

- Observation: imports of ungrouped in-root modules are silently allowed and
  ungrouped modules are not checked.
  Evidence: `_record_import_edge` returns early when either side's group is
  `None`.
  Impact: `episodic.logging` and similar cross-cutting modules need no group;
  but every adapter must stay grouped or enforcement leaks. Add a guard
  fixture.

- Observation: the current orchestration package imports no adapters; worker
  tasks import only `WorkloadClass` from the `kombu`-coupled
  `episodic.worker.topology`; checkpoint DTOs reach `episodic.generation`
  (application tier) only through the `_dto` barrel
  (`_checkpoint_dto` to `_dto` to `_action_result_dto` to
  `episodic.generation`).
  Evidence: import map gathered with grep over `episodic/orchestration/*.py`
  and `episodic/worker/*.py`.
  Impact: the enforcement is mostly preventative; the two real fixes are the
  `WorkloadClass` extraction (M2) and the checkpoint DTO decoupling (M3).

- Observation: the fixture generator needs an explicit outbound `.adapter`
  prefix as well as `.storage` so the `ungrouped_adapter_is_caught` fixture
  fails if a reachable adapter-like module is left invisible to Hecate.
  Evidence: helper-level tests now assert the outbound prefixes include both
  modules.
  Impact: future fixture additions can model non-storage adapters without
  adding fixture-specific TOML.

- Observation: a broad production prefix of `episodic.orchestration` catches
  the durable checkpoint adapter before M3 has separated checkpoint DTOs.
  Evidence: the first M1 focused run failed `run_hecate_production_check()`
  because `episodic.canonical.storage.workflow_checkpoints` imports
  `WorkflowCheckpoint`, and because two adapters still imported the
  orchestration-local `_log_event` helper.
  Impact: M1 moved the reusable structured logging helper to
  `episodic.logging.log_event` and scoped the production `orchestration` group
  to graph modules only. M3 remains responsible for the checkpoint DTO group
  and the durable checkpoint adapter edge.

- Observation: `WorkloadClass` had only two internal production consumers that
  needed retargeting away from `topology`: `worker.tasks` and `worker.runtime`.
  Evidence: `leta refs WorkloadClass` after the move shows internal imports
  from `episodic.worker.workloads`, while `topology` and the public worker
  barrel re-export the same symbol for existing callers.
  Impact: M2 could preserve the public worker API while giving the task module
  a vendor-free import path.

- Observation: the durable SQLAlchemy checkpoint store is an outbound adapter
  that legitimately implements `CheckpointPort` using `WorkflowCheckpoint`.
  Evidence: `episodic.canonical.storage.workflow_checkpoints` maps SQLAlchemy
  rows to `WorkflowCheckpoint` and accepts `WorkflowCheckpoint` in
  `save_or_reuse`.
  Impact: the production `outbound_adapter` group must be allowed to import
  `orchestration_checkpoint`; the checkpoint DTO group remains strict because
  its own `allowed` list excludes both application and adapter groups.

- Observation: `ActionExecutionResult` carries rich show-notes and guest-bios
  attachments for in-process orchestration results, but checkpoint payload
  serialisation deliberately ignores those attachment fields.
  Evidence: `_action_result_to_payload` stores only action identity, kind,
  model tier, model, summary, and usage, while tests still assert rich
  attachment attributes on direct tool results.
  Impact: `_payload_dto.py` now uses local structural Protocols for attachment
  shapes instead of importing generation DTOs. The structural checkpoint audit
  skips these non-persisted attachment fields and separately enforces
  `WorkflowCheckpoint.payload` JSON serialisability.

## Decision log

- Decision: interpret "depend on ports only" as "depend on the application and
  domain-ports layers only; never import adapters (inbound or outbound),
  storage, ORM, or vendor SDKs", and apply the strictest reading (ports and
  provider-neutral DTOs only) to checkpoint payloads.
  Rationale: the roadmap wording "ports only" is reconciled with the system
  design, which states orchestration "will depend on domain services and ports
  only". Domain services live in the application layer and are not adapters.
  Checkpoint payloads carry a stricter rule because the design says they must
  hold orchestration metadata only, with canonical state persisted through
  repositories.
  Date/Author: 2026-06-15, planning agent.

- Decision: pursue genuine node-level ports-only enforcement by splitting
  `episodic/orchestration/langgraph.py` into a ports-only node module and an
  application-tier graph-builder module, rather than only renaming the group.
  Rationale: it is the most faithful reading of "validate LangGraph nodes
  depend on ports only", and it also resolves the existing 400-line file
  violation. AGENTS.md requires actioning requested changes rather than
  treating them as optional.
  Date/Author: 2026-06-15, planning agent.

- Decision: enforce checkpoint payload boundaries with both a Hecate group and
  a structural reflection test (plus a property test).
  Rationale: Hecate's layer model cannot forbid embedding canonical domain
  entities, because those classify as `domain_ports`. A reflection-based test
  over payload DTO field types is required to fully cover the design rule.
  Date/Author: 2026-06-15, planning agent.

- Decision: the clarifying question on strictness and audit mechanism was
  offered to the user but not answered; the plan adopts the more thorough
  options and records them here so reviewers can scope down during PR review.
  Rationale: a plan is cheaper to narrow than to re-expand, and PR review is the
  approval gate.
  Date/Author: 2026-06-15, planning agent.

- Decision: model production-like specific prefixes in architecture fixtures
  (`orchestration._graph_nodes`, `orchestration._checkpoint_payload`, and
  `worker.tasks`) instead of flat toy module names.
  Rationale: this makes M0 cover the first-match ordering hazard that M1-M3
  must preserve in the real `[tool.hecate]` configuration.
  Date/Author: 2026-06-26, implementation agent.

- Decision: scope the first production `orchestration` Hecate group to graph
  modules (`_graph_builder`, `_graph_nodes`, and the compatibility
  `langgraph` barrel) rather than the whole `episodic.orchestration` package.
  Rationale: M1 proves the node/builder split and prevents graph modules from
  importing adapters without prematurely grouping checkpoint DTOs. A package-
  wide prefix would force the M3 checkpoint DTO decision into M1 and would
  make the durable checkpoint adapter fail before its port DTO boundary has
  been audited.
  Date/Author: 2026-06-26, implementation agent.

- Decision: promote the structured event helper from
  `episodic.orchestration._types._log_event` to
  `episodic.logging.log_event`, while keeping `_types._log_event` as a
  compatibility alias.
  Rationale: canonical adapters were using the helper for generic structured
  logging. Keeping that helper in orchestration created an adapter-to-
  orchestration dependency unrelated to graph policy; the logging module is
  the existing neutral home for logging helpers.
  Date/Author: 2026-06-26, implementation agent.

- Decision: classify `episodic.worker.workloads` as `domain_ports`, not
  `application`.
  Rationale: `WorkloadClass` is a provider-neutral routing contract enum shared
  by task code and the Kombu-backed topology adapter. Treating it as
  `domain_ports` lets both task and topology layers depend on it without
  creating a task-to-topology edge or broadening task permissions.
  Date/Author: 2026-06-26, implementation agent.

- Decision: classify checkpoint DTO and payload modules in a dedicated
  `orchestration_checkpoint` Hecate group, and allow outbound adapters to
  import that group.
  Rationale: checkpoint DTOs are provider-neutral port contracts. Outbound
  checkpoint stores need those contracts to implement `CheckpointPort`, but the
  DTO modules themselves must not import application services, storage, ORM
  models, or vendor SDKs.
  Date/Author: 2026-06-26, implementation agent.

- Decision: keep rich tool-result attachments on `ActionExecutionResult` as
  provider-neutral structural Protocols rather than importing concrete
  generation result DTOs.
  Rationale: existing callers rely on `show_notes_result` and
  `guest_bios_result` attributes for direct orchestration results, but
  checkpoint payload serialisation does not persist those attachments. Local
  Protocols preserve static type usefulness without reintroducing a
  checkpoint-to-application import edge.
  Date/Author: 2026-06-26, implementation agent.

- Decision: no `docs/users-guide.md` update is required for M4.
  Rationale: the slice changes maintainer-facing architecture enforcement,
  tests, and documentation only; no public user workflow, command, or API
  behaviour changed.
  Date/Author: 2026-06-26, implementation agent.

## Outcomes & retrospective

M1 outcome: the LangGraph node functions now live in
`episodic/orchestration/_graph_nodes.py`, graph assembly lives in
`episodic/orchestration/_graph_builder.py`, and the historical
`episodic.orchestration.langgraph` import path re-exports the moved symbols.
The production architecture gate now groups those graph modules separately
from `application`, while leaving checkpoint DTO grouping for M3.

M2 outcome: Celery task code imports `WorkloadClass` from a provider-neutral
worker workload module, while topology remains responsible for Kombu queue
objects. The production architecture gate now groups `episodic.worker.tasks`
as `orchestration_tasks`, so task code may import application and domain port
contracts but not inbound or outbound adapters.

M3 outcome: checkpoint payload modules now belong to
`orchestration_checkpoint`, and `make lint` fails if they import application or
adapter modules. A structural test audits checkpoint payload DTO field types,
and a property test verifies JSON-shaped `WorkflowCheckpoint.payload` values
round-trip unchanged through JSON serialisation.

Remaining outcomes to complete: the behavioural, snapshot, documentation, and
roadmap updates in M4 remain.

## Context and orientation

This section assumes no prior knowledge of the repository.

### Architecture enforcement today

The checker is Hecate, invoked by the `check-architecture` target in the
`Makefile`:

```make
check-architecture: build ## Check hexagonal architecture import boundaries
	$(UV_ENV) $(UV) run hecate check
```

`make lint` runs `check-architecture` first, then Ruff and Pylint. Hecate reads
`[tool.hecate]` from `pyproject.toml`. The configuration declares one root
package (`episodic`), a default rule identifier (`ARCH001`), and five ordered
groups. Each group has a `name`, a list of module `prefixes`, and an `allowed`
list naming the groups it may import from. Matching is first-match by config
order, so specific prefixes must precede broader ones. A group must list its
own name in `allowed` to permit imports between its own modules.

The current groups (see `pyproject.toml`, the `[tool.hecate]` block) are:

1. `composition_root` (`episodic.api.runtime`, `episodic.worker.runtime`) may
   import every layer.
2. `domain_ports` (canonical domain and port protocols, `episodic.cost.ports`,
   `episodic.cost.engine`, `episodic.llm.ports`, `episodic.metrics_ports`, and
   related) may import only `domain_ports`.
3. `application` (canonical services, `episodic.generation`,
   `episodic.orchestration`, `episodic.cost.recorder`, and related) may import
   `application` and `domain_ports`.
4. `inbound_adapter` (`episodic.api`, `episodic.worker.tasks`,
   `episodic.worker.topology`) may import `inbound_adapter`, `application`,
   `domain_ports`.
5. `outbound_adapter` (storage, canonical adapters, OpenAI adapters, cost
   storage, pricing catalogue) may import `outbound_adapter`, `application`,
   `domain_ports`.

### How the architecture tests are wired

`tests/architecture_hecate_config.py` is a helper module (not a test) that
generates per-fixture Hecate TOML and invokes the Hecate CLI by subprocess. It
exposes `write_fixture_config(tmp_path, package_name)`,
`run_hecate_fixture_check(package_name, config_path)`, and
`run_hecate_production_check()`. Fixture packages live under
`tests/fixtures/architecture/<name>/` and are tiny synthetic packages
(`domain.py`, `service.py`, `api.py`, `storage.py`, `runtime.py`, and
`__init__.py`) that model one boundary scenario each. Existing fixtures cover
the allowed case, composition-root wiring, and several violation cases
including re-exported and star-re-exported barrels.

`tests/test_architecture_hecate_config.py` tests the helper itself (TOML shape
and subprocess error wrapping). The fixtures are exercised by the
architecture test and behaviour-driven development (BDD) steps that assert exit
codes and emitted violations. Use `leta grep` and `leta refs` to locate the
exact test entry points before editing; do not assume file names.

### The code under enforcement

LangGraph is a library for building stateful graphs of "nodes" (functions that
take a state and return a state update). The orchestration package builds one
such graph for generation:

- `episodic/orchestration/langgraph.py` (460 lines) defines the node functions
  `_plan_node`, `_execute_node`, `_finish_node`, cost-recording helpers, and the
  graph builder `build_generation_orchestration_graph`. It imports the LangGraph
  library plus sibling orchestration modules. The node functions receive their
  collaborators (`PlannerPort`, `ToolExecutorPort`) by injection; the builder is
  the module's only consumer of `_planning_orchestrator`
  (`StructuredPlanningOrchestrator`, application tier).
- `episodic/orchestration/_protocols.py` defines the port protocols
  (`PlannerPort`, `ToolExecutorPort`, `CostRecorderPort`, and similar).
- `episodic/orchestration/_graph_state.py`, `_types.py`, `_usage.py`,
  `_dto.py`, `_result_dto.py`, `_action_result_dto.py`, `_checkpoint_dto.py`,
  `_checkpoint_payload.py`, `_checkpoint_resume.py`, `checkpoints.py`,
  `generation.py`, and the executors round out the package.

Celery is a distributed task queue. The worker package:

- `episodic/worker/tasks.py` defines representative tasks via injected callable
  seams (`WorkerDependencies`); its only cross-module import is `WorkloadClass`
  from `episodic/worker/topology.py`.
- `episodic/worker/topology.py` imports `kombu` (a vendor SDK) and defines both
  `WorkloadClass` (a pure `enum.StrEnum`) and the `kombu`-coupled queue specs.
- `episodic/worker/runtime.py` is the composition root that wires Celery.

Checkpoint payloads are the durable orchestration state saved when a graph
pauses. `episodic/orchestration/_checkpoint_dto.py` defines `WorkflowCheckpoint`
(its `payload` is a `dict[str, object]`), `SuspendedWorkflowResult`,
`ResumeWorkflowCommand`, and `WorkflowStepIdentity`. It imports
`ActionExecutionResult` and two normalisation helpers from the `_dto` barrel;
the barrel transitively imports `episodic.generation` (application tier) through
`_action_result_dto`.

### Hecate facts that constrain the design (verified from source)

- `TYPE_CHECKING`-guarded and function-body imports are counted as
  dependencies.
- Imports of ungrouped in-root modules are allowed; ungrouped modules are not
  checked.
- A group must list its own name in `allowed` to permit intra-group imports.
- Matching is first-match by config order; prefix containment is at dotted
  boundaries.
- Re-exports, star re-exports, and relative imports resolve to the origin
  module's group.
- `[[tool.hecate.ignore_imports]]` accepts `importer`, `imported`, and a
  required non-empty `reason`; `hecate check` supports `--show-ignored` and
  `--fail-on-unmatched-ignore`.
- CLI: `hecate check` accepts `--config`, `--package` plus `--root` (together),
  `--include-external-packages`, and `--format {text,json}`. Exit codes: 0
  pass, 1 violations, 2 config or validation error.

### Skills and documentation to consult

Load and follow these skills while implementing:

- `hexagonal-architecture` for layer boundaries and drift detection.
- `python-router`, then `python-data-shapes` (DTO design), `python-types-and-apis`
  (Protocols and signatures), and `python-testing` (fixtures, parametrization,
  snapshots).
- `python-verification`, then `hypothesis` for the checkpoint property test
  (and `crosshair` only if a PEP 316 contract is added).
- `vidai-mock` for behavioural tests that exercise the generation graph against
  a simulated inference service.
- `leta` for navigation and safe refactors; `commit-message` for commits;
  `pr-creation` for the pull request.

Read these documents (signposts):

- `docs/episodic-podcast-generation-system-design.md` — "Hexagonal
  architecture enforcement", "Orchestration guardrails", "Orchestration ports
  and adapters", and "Checkpoint payload boundaries". This is where design
  decisions are recorded.
- `docs/agentic-systems-with-langgraph-and-celery.md` and
  `docs/langgraph-and-celery-in-hexagonal-architecture.md` — orchestration
  component architecture; the latter is the home for internal-interface notes.
- `docs/developers-guide.md` — the "Architecture enforcement" section; update it
  with the new groups and conventions.
- `docs/execplans/adopt-hecate.md` — how the groups and fixtures were
  established, including the first-match ordering gotcha and the star-import
  barrel surprise.
- `docs/adr/adr-014-hexagonal-architecture-enforcement.md` — the enforcement
  ADR to extend or cross-reference.
- `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md`, and
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` — testing patterns for
  any persistence-touching behavioural test.
- `docs/documentation-style-guide.md`, `docs/contents.md`, and
  `docs/repository-layout.md` — documentation conventions and indices.

## Plan of work

The work proceeds in five milestones. Each follows Red-Green-Refactor: add the
smallest failing fixture or test first, confirm it fails for the intended
reason, make the minimal production or configuration change, then refactor and
re-run the gates. Architecture rules are validated through the fixture harness
(synthetic packages) for both positive and negative cases, and through the
production `hecate check` for the real code.

### M0 Orientation and red harness (no production changes)

Goal: establish failing tests that specify the new boundaries before any
production or configuration change, and confirm the current baseline.

1. Confirm the baseline gates pass: run `make build`, then
   `make check-architecture`, `make typecheck`, and the architecture tests.
   Record the transcripts as evidence.
2. Add new synthetic fixture packages under `tests/fixtures/architecture/` that
   model the orchestration boundaries (see "Fixtures to add" below). Add them
   first as the Red stage; the new architecture test cases that assert their
   expected exit codes and violations must be added and observed failing or
   xfailing before the corresponding production or config change.
3. Extend the fixture-config generator in
   `tests/architecture_hecate_config.py` so it can emit the new
   orchestration, orchestration-tasks, and checkpoint groups for the synthetic
   packages. Keep the generator data-driven; do not hard-code per-fixture TOML
   beyond what already exists.
4. Add a production-level red expectation: a test asserting that the production
   Hecate config declares the new groups
   (`orchestration`, `orchestration_tasks`, `orchestration_checkpoint`). Mark
   it `@pytest.mark.xfail(strict=True, reason="groups added in M1-M3")` and
   confirm it xfails; remove the marker as the groups land.

Validation: the new fixture tests fail or xfail for the expected reason;
existing gates still pass. No production code or `pyproject.toml` group change
yet.

### M1 Dedicated `orchestration` group and node/builder split

Goal: make a named, fixtured `orchestration` group and prove LangGraph node
code cannot import adapters, with node bodies isolated from application-tier
graph assembly.

1. Refactor `episodic/orchestration/langgraph.py` into two modules:
   - `episodic/orchestration/_graph_nodes.py`: the node functions and their
     direct helpers, importing only port protocols (`_protocols`), graph state
     (`_graph_state`), provider-neutral DTOs, `episodic.llm` (ports),
     `episodic.cost.ports`, and `episodic.logging`. No import of
     `_planning_orchestrator`, `episodic.generation`, or `episodic.cost.recorder`.
   - `episodic/orchestration/_graph_builder.py` (or keep `langgraph.py` as the
     builder): `build_generation_orchestration_graph` and any
     application-tier wiring, importing the nodes plus the planning
     orchestrator.
   Keep both files under 400 lines. Preserve every name currently re-exported by
   `episodic/orchestration/__init__.py`; verify with `leta refs` for each moved
   symbol.
2. Add the `orchestration` group to `[tool.hecate]` in `pyproject.toml`,
   placed before the `application` group (first-match). Remove
   `episodic.orchestration` from the `application` group's prefixes and add it
   under the new group. Decide the node-strictness expression:
   - The node module prefix (`episodic.orchestration._graph_nodes`) gets the
     strictest `allowed` (its own group plus `domain_ports` plus the checkpoint
     group added in M3), proving nodes are ports-and-DTO only.
   - The rest of `episodic.orchestration` keeps `allowed = ["orchestration",
     "application", "domain_ports"]` (domain services permitted, adapters
     forbidden).
   If a single group cannot express both, introduce a separate
   `orchestration_nodes` group (prefix `episodic.orchestration._graph_nodes`)
   ordered before `orchestration`.
3. Add fixtures and tests proving: a node-tier module importing an outbound
   adapter fails; a node-tier module importing a port passes; an orchestration
   (non-node) module importing a domain service passes; any orchestration module
   importing an inbound or outbound adapter fails.

Validation: run `make check-fmt`, `make typecheck`, `make lint` (includes
`hecate check`), and `make test`. The new node-violation fixture fails the
fixture check; the production check passes; the previously xfailing
"declares orchestration group" expectation now passes (remove its marker).

### M2 Celery task enforcement and `WorkloadClass` extraction

Goal: make Celery task code ports-only by removing its dependence on the
`kombu`-coupled topology module, and enforce it with a dedicated group.

1. Extract `WorkloadClass` from `episodic/worker/topology.py` into a new
   provider-neutral module, for example `episodic/worker/workloads.py`, that
   imports no vendor SDK. Re-export `WorkloadClass` from
   `episodic/worker/topology.py` and `episodic/worker/__init__.py` so existing
   importers keep working (verify with `leta refs WorkloadClass`).
2. Update `episodic/worker/tasks.py` to import `WorkloadClass` from
   `episodic.worker.workloads`.
3. Classify `episodic.worker.workloads` as `domain_ports` (it is a
   provider-neutral contract type that both tasks and topology must import; both
   layers already allow `domain_ports`). Add its prefix to the `domain_ports`
   group.
4. Add an `orchestration_tasks` group with prefix `episodic.worker.tasks`,
   ordered before the `inbound_adapter` group, with
   `allowed = ["orchestration_tasks", "application", "domain_ports"]` (no
   inbound or outbound adapter). Remove `episodic.worker.tasks` from the
   `inbound_adapter` group's prefixes.
5. Add fixtures and tests proving: a task-tier module importing an inbound
   adapter fails; a task-tier module importing an outbound adapter fails; a
   task-tier module importing a port and a domain service passes.

Validation: the gate suite passes; the new task-violation fixtures fail the
fixture check; the production check passes. Confirm with `leta refs` that no
caller broke from the `WorkloadClass` move.

### M3 Checkpoint payload boundary audit

Goal: enforce that checkpoint payload DTOs hold orchestration metadata and
provider-neutral DTOs only, with no application coupling and no embedded
canonical or ORM state.

1. Decouple the checkpoint DTOs from the application-coupled `_dto` barrel.
   Inspect what `_checkpoint_dto.py` and `_checkpoint_payload.py` actually need
   (`ActionExecutionResult` and the `_normalize_*` helpers) and whether those
   transitively reference generation types (use `leta show` and
   `leta calls --from`). Extract a provider-neutral DTO core module, for example
   `episodic/orchestration/_payload_dto.py`, that defines or holds the neutral
   DTOs and normalisation helpers and imports only `episodic.llm` (ports) and
   `_types`. Re-point `_checkpoint_dto.py`, `_checkpoint_payload.py`, and
   `_result_dto.py` at the core. Keep the `_dto` barrel re-exporting every
   current name for backward compatibility.
2. Add an `orchestration_checkpoint` group with prefixes for the payload
   modules (`episodic.orchestration._checkpoint_payload`,
   `episodic.orchestration._checkpoint_dto`, and the new `_payload_dto`),
   ordered before the `orchestration` group, with
   `allowed = ["orchestration_checkpoint", "domain_ports"]` (ports and neutral
   DTOs only). If, after step 1, exactly one unavoidable type-only edge to an
   application DTO remains, record a single
   `[[tool.hecate.ignore_imports]]` entry with a clear reason; more than one
   such edge is a tolerance breach to escalate.
3. Add a structural reflection test (the audit) over the checkpoint payload
   DTOs that asserts each field's type is within an allow-list of
   provider-neutral types (primitives, `enum` members, `datetime`, mappings of
   primitives, `LLMUsage`, and other checkpoint DTOs) and explicitly rejects
   SQLAlchemy ORM models and canonical aggregate entity types. This covers the
   design rule that Hecate's layer model cannot express, because canonical
   entities classify as `domain_ports`.
4. Add a Hypothesis property test asserting an invariant over the checkpoint
   payload, for example: for any generated `WorkflowCheckpoint`, its `payload`
   round-trips through JSON serialisation unchanged (proving payloads stay
   JSON-shaped and free of non-serialisable adapter or ORM objects). Follow the
   `hypothesis` skill; keep the strategy bounded and the regression database
   committed per project convention.

Validation: the gate suite passes; the structural and property tests fail
before the decoupling and pass after; the checkpoint-violation fixture (a
payload module importing storage) fails the fixture check; the production check
passes.

### M4 Behavioural tests, snapshots, documentation, and roadmap update

Goal: cover externally observable behaviour, lock output format, and document
the new boundaries.

1. Add a `pytest-bdd` feature that specifies the enforcement workflow from a
   maintainer's perspective. Embed the feature in this plan (see "BDD feature"
   below) and place it under the project's feature directory (locate with
   `leta files tests/` or the existing `*.feature` convention). Steps drive the
   fixture harness: a clean orchestration fixture passes; a node importing an
   adapter is rejected with an `ARCH001` violation naming the node module; a
   Celery task importing an adapter is rejected; a checkpoint payload importing
   storage is rejected.
2. Add a `syrupy` snapshot test capturing the `hecate check --format json`
   output for one representative orchestration-violation fixture, so the
   violation message shape for node, task, and checkpoint rules is regression
   protected. Only snapshot fixture output (deterministic), never the
   production tree.
3. Add a behavioural test that exercises `build_generation_orchestration_graph`
   end to end against a simulated inference service using `vidai-mock`
   (per the `vidai-mock` skill), asserting the graph still plans, executes, and
   finishes after the node/builder split, with the mock standing in for the
   `LLMPort` adapter. This proves the refactor preserved observable behaviour.
4. Documentation:
   - Update `docs/episodic-podcast-generation-system-design.md` to mark the
     orchestration enforcement slice as delivered and to describe the three new
     groups and the checkpoint audit.
   - Update `docs/developers-guide.md` "Architecture enforcement" with the new
     groups, the first-match ordering for the new prefixes, the
     `WorkloadClass` location, and how to add fixtures for orchestration
     boundaries.
   - Update `docs/langgraph-and-celery-in-hexagonal-architecture.md` (the
     orchestration component architecture doc) with the node/builder split, the
     ports-only node rule, the task rule, and the checkpoint payload rule.
   - Add ADR-016 (verify the next free number with `ls docs/adr/`; ADR-015 is
     already used) recording the orchestration-enforcement decisions (the
     "ports only" interpretation, the node/builder split, and the
     checkpoint audit mechanism), and cross-reference it from
     `docs/adr/adr-014-hexagonal-architecture-enforcement.md` and the system
     design. Follow the documentation style guide and the
     `arch-decision-records` conventions.
   - Update `docs/users-guide.md` only if a publicly consumable interface
     changed. This slice is internal enforcement; if no public API changes, note
     in the Decision Log that no users-guide change was required.
   - Add the new ADR and any new component note to `docs/contents.md`.
5. Mark roadmap item 2.4.5 done in `docs/roadmap.md`.

Validation: `make check-fmt`, `make typecheck`, `make lint`, `make test`,
`make markdownlint`, and `make nixie` all pass. The BDD scenarios fail before
their enforcement exists and pass after.

## Fixtures to add

Add synthetic packages under `tests/fixtures/architecture/`, each a minimal
package with an `__init__.py`. Model the orchestration layer with modules named
to match the generated group prefixes the helper emits. Suggested fixtures
(adjust names to the generator's conventions):

1. `orchestration_node_imports_outbound_adapter` — a node-tier module imports a
   storage module; expected violation.
2. `orchestration_node_imports_port` — a node-tier module imports a port;
   expected pass.
3. `orchestration_imports_domain_service` — a non-node orchestration module
   imports an application service; expected pass.
4. `orchestration_imports_inbound_adapter` — an orchestration module imports an
   inbound adapter; expected violation.
5. `celery_task_imports_inbound_adapter` — a task-tier module imports an inbound
   adapter; expected violation.
6. `celery_task_imports_outbound_adapter` — a task-tier module imports an
   outbound adapter; expected violation.
7. `checkpoint_payload_imports_storage` — a checkpoint payload module imports a
   storage module; expected violation.
8. `checkpoint_payload_imports_application` — a checkpoint payload module imports
   an application service; expected violation.
9. `ungrouped_adapter_is_caught` — a guard fixture proving that an adapter the
   orchestration layer can reach is grouped (not invisible), so enforcement does
   not leak through an ungrouped module.

Each fixture gets a positive or negative test case parametrized in the
architecture test, mirroring the existing fixture tests. Extend the helper's
fixture-config generator to emit the orchestration, orchestration-tasks, and
checkpoint groups for these synthetic packages.

## BDD feature

Place under the project's feature directory (confirm the path and step-module
convention first). Keep the specification synchronized with M4.

```gherkin
Feature: Architecture enforcement

  Scenario: A clean orchestration fixture passes
    Given the architecture fixture package "orchestration_node_imports_port"
    When the architecture checker runs
    Then the architecture check passes

  Scenario: A LangGraph node importing an adapter is rejected
    Given the architecture fixture package "orchestration_node_imports_outbound_adapter"
    When the architecture checker runs
    Then the check fails with an ARCH001 violation
    And the architecture diagnostic mentions "orchestration._graph_nodes"

  Scenario: A Celery task importing an adapter is rejected
    Given the architecture fixture package "celery_task_imports_inbound_adapter"
    When the architecture checker runs
    Then the check fails with an ARCH001 violation
    And the architecture diagnostic mentions "worker.tasks"

  Scenario: A checkpoint payload importing storage is rejected
    Given the architecture fixture package "checkpoint_payload_imports_storage"
    When the architecture checker runs
    Then the check fails with an ARCH001 violation
    And the architecture diagnostic mentions "orchestration._checkpoint_payload"
```

## Concrete steps

Run all commands from the repository root
(`/home/leynos/.lody/repos/github---leynos---episodic/worktrees/...` in this
worktree). Capture long output with `tee` to a temporary log for review, per
project convention.

1. Build and baseline:

   ```bash
   make build
   make check-architecture | tee /tmp/check-arch-baseline.out
   make test | tee /tmp/test-baseline.out
   ```

   Expect `check-architecture` to exit 0 and the test suite to pass.

2. Per milestone, add the Red fixture or test, run the focused test and confirm
   the expected failure, implement the minimal change, then run the gates in
   this order (sequential, to benefit from build caching; do not run them in
   parallel):

   ```bash
   make check-fmt | tee /tmp/check-fmt-$(git branch --show-current).out
   make typecheck | tee /tmp/typecheck-$(git branch --show-current).out
   make lint | tee /tmp/lint-$(git branch --show-current).out
   make test | tee /tmp/test-$(git branch --show-current).out
   ```

3. For documentation milestones additionally run:

   ```bash
   make markdownlint | tee /tmp/mdlint-$(git branch --show-current).out
   make nixie
   ```

   Run `make nixie` unsandboxed (it needs a browser sandbox of its own). Guard
   any long inline code spans in Markdown to avoid MD013 from the formatter.

4. After each milestone's gates pass, run the CodeRabbit review and clear every
   concern before the next milestone:

   ```bash
   coderabbit review --agent | tee /tmp/coderabbit-$(git branch --show-current).out
   ```

   CodeRabbit must not be used to catch issues the deterministic gates can
   catch; run the gates first.

5. Commit frequently with the `commit-message` skill (file-based messages, never
   `-m`). Keep functional changes and pure refactors in separate atomic commits.

## Validation and acceptance

Acceptance is behavioural and observable:

- Running `make lint` on the production tree passes (`hecate check` exits 0)
  at every milestone boundary.
- A new architecture fixture in which a LangGraph node imports an outbound
  adapter causes the fixture's Hecate check to exit 1 with an `ARCH001`
  violation; the same node importing a port passes. This new test fails before
  M1's group is added and passes after.
- A new fixture in which a Celery task imports an adapter causes the fixture
  check to exit 1; a task importing a port and a domain service passes. Fails
  before M2, passes after.
- A new fixture in which a checkpoint payload module imports storage causes the
  fixture check to exit 1. The structural reflection test fails if a checkpoint
  payload DTO declares a field whose type is an ORM model or canonical entity,
  and passes for the current provider-neutral fields. Fails before M3, passes
  after.
- The Hypothesis property test shows every generated `WorkflowCheckpoint`
  payload round-trips through JSON unchanged.
- The `vidai-mock`-backed behavioural test shows the generation graph still
  plans, executes, and finishes after the node/builder split.
- The BDD scenarios above pass.

Quality criteria (what "done" means):

- Tests: `make test` passes with the new unit, BDD, snapshot, structural, and
  property tests included.
- Lint and typecheck: `make lint` and `make typecheck` pass; `hecate check`
  exits 0.
- Markdown: `make markdownlint` and `make nixie` pass for all edited docs.
- Architecture: every new rule is proven by both a positive and a negative
  fixture; no rule relies on an ungrouped module to pass.
- Review: CodeRabbit concerns cleared at each milestone.

Quality method (how we check): the `Makefile` gate suite run sequentially after
each milestone, plus the fixture-harness positive and negative cases, plus
CodeRabbit.

## Idempotence and recovery

- Configuration and test additions are re-runnable; re-running the gates is
  safe.
- Symbol moves are the only risky steps. Before moving any definition, record
  its current import sites with `leta refs <symbol>`; after moving, keep the
  original module re-exporting the name and re-run `make typecheck` and
  `make test`. If a downstream import breaks, restore the re-export rather than
  editing the consumer, unless the consumer is within scope.
- If a Hecate group change makes the production check fail for an unforeseen
  edge, revert the `pyproject.toml` group change, capture the violation, and
  decide in the Decision Log whether to refactor the edge or adjust the group
  ordering; do not add an `ignore_imports` to silence a genuine boundary
  violation.

## Interfaces and dependencies

No new runtime dependencies. The following names must exist at the end of the
slice (paths are illustrative where the plan allows a choice; fix the names in
the Decision Log when chosen):

- `episodic/orchestration/_graph_nodes.py` containing the node functions
  (`_plan_node`, `_execute_node`, `_finish_node`, and helpers), importing ports
  and provider-neutral DTOs only.
- `episodic/orchestration/_graph_builder.py` (or retained `langgraph.py`)
  containing `build_generation_orchestration_graph`.
- `episodic/orchestration/_payload_dto.py` containing the provider-neutral
  checkpoint DTO core and normalisation helpers.
- `episodic/worker/workloads.py` containing `WorkloadClass`, re-exported from
  `episodic/worker/topology.py` and `episodic/worker/__init__.py`.
- `[tool.hecate]` groups `orchestration` (and optionally `orchestration_nodes`),
  `orchestration_tasks`, and `orchestration_checkpoint`, ordered before their
  broader counterparts, with `domain_ports` extended to include
  `episodic.worker.workloads`.
- Architecture fixtures and tests as listed under "Fixtures to add", a
  structural reflection test, a Hypothesis property test, a `syrupy` snapshot,
  a `pytest-bdd` feature, and a `vidai-mock`-backed behavioural test.
- `docs/adr/adr-016-*.md` recording the decisions, cross-referenced from
  ADR-014 and the system design.

The orchestration and worker public barrels
(`episodic/orchestration/__init__.py`, `episodic/worker/__init__.py`) must
export exactly the same names they export today.
