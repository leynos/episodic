# Add QA-gated mode branching and content-generation graph routing (4.4.1)

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & discoveries`, `Decision log`,
`Outcomes & retrospective`, `Conformance basis`, and `Verification plan` must
be kept up to date as work proceeds.

Status: DRAFT

## Purpose / big picture

Today a generation run can only be created with
`quality_mode=draft_without_qa`. The in-process launcher claims the run,
generates one draft, persists the TEI-P5 script with `qa_status=skipped`, and
marks the run `succeeded`. A request for `quality_mode=qa_gated` is refused with
`422 Unprocessable Entity`, and there is no graph that could route such a run
anywhere.

After this change, every generation run executes through a small LangGraph
`StateGraph`, the first slice of the *Content Generation Graph* described in
`docs/episodic-podcast-generation-system-design.md`. The graph has one
conditional edge, the *quality branch*, that sends a run down exactly one of
two branches:

- `draft_without_qa` runs go straight from generation to draft persistence,
  exactly as they do today. The event stream and terminal state for these runs
  are unchanged.
- `qa_gated` runs go into an evaluation branch. The branch runs the configured
  QA evaluators and aggregates their verdicts. A run whose verdict is a pass
  persists its draft with `qa_status=passed` and succeeds. Any other verdict
  sends the run to an *escalate* terminal, which leaves the TEI unwritten and
  fails the run with the stable category `qa.escalation_required`.

Each branch owns its own terminal nodes. No node or terminal is reachable from
both branches except the shared prefix (`initialize` and `generate`).
Hypothesis property tests prove this for generated run states.

A user can observe the result over REST. Creating a `qa_gated` run returns
`202 Accepted` with `qa_status: "pending"` in deployments that have QA
evaluators configured. Polling then shows either `succeeded` with
`qa_status: "passed"` and a downloadable TEI whose envelope reports
`quality_mode: "qa_gated"`, or `failed` with
`error_category: "qa.escalation_required"`, `qa_status: "failed"` and a
`qa.escalated` event. Deployments without evaluators, which includes production
until roadmap item 4.4.2 binds Chrono, keep returning the existing
`422 quality_mode_unsupported` response for `qa_gated`. A QA-gated request can
therefore never spend inference budget on a branch that cannot pass.

## Constraints

- Preserve the `draft_without_qa` contract byte for byte. The REST request and
  response shapes, the error envelopes, the event kinds, the event order, the
  event payloads, `current_node` values, the metric names and labels, and the
  persisted TEI provenance must all stay as they are. The existing snapshot
  files must not be regenerated for any `draft_without_qa` case. A changed
  no-QA snapshot is a failed constraint, not a reason to run
  `--snapshot-update`.
- Keep a single writer per run. The launcher task that claimed a run is the
  only code that appends its events or changes its status. Graph nodes reach
  run state only through the step port that the launcher supplies for that run.
  They never open a unit of work themselves.
- Keep event publication ordered. Every event for a run is appended from that
  run's launcher task, in graph order. No graph branch may run in parallel in
  this item.
- Keep cancellation shutdown-safe. Cancelling a run at any node, including
  while an evaluator is awaiting, must record the existing `launcher.shutdown`
  failure exactly once, must not persist TEI, and must leave `qa_status` at
  `pending` for a `qa_gated` run.
- Respect the hexagonal boundaries enforced by Hecate (`[tool.hecate]` in
  `pyproject.toml`, ADR 014 and ADR 022):
  - Domain policy and port protocols live in the `domain_ports` group and
    import only `domain_ports`.
  - Graph nodes and graph state live in the `orchestration_nodes` group and
    import only `orchestration_nodes`, `domain_ports` and
    `orchestration_checkpoint`.
  - The graph builder and runner live in the `orchestration` group.
  - The launcher stays in `application` (`episodic.generation`) and must not
    import `episodic.orchestration`. The composition root injects the graph.
- Do not weaken a Hecate rule. Only add prefixes to existing groups. Never
  reorder groups and never broaden an `allowed` list.
- Fail closed. An empty evaluator set, an evaluator error and an
  `inconclusive` verdict must never produce `qa_status=passed`, a persisted TEI
  or a `succeeded` run.
- Never persist TEI for a `qa_gated` run before its aggregate verdict is a
  pass. `EpisodeTeiUpdate` must refuse `pending` and `failed` QA statuses.
- Database changes are additive only. Add enum labels with
  `ALTER TYPE ... ADD VALUE IF NOT EXISTS`. Do not rename or reorder any
  existing label, and add no columns to `episodes`.
- No new third-party dependency. LangGraph (`>=1.2.11`), Hypothesis, pytest,
  pytest-bdd, syrupy, py-pglite and Vidai Mock are already available.
- Keep every code file under 400 lines (`AGENTS.md`). The launcher mixins are
  already 100–250 lines each, so new behaviour goes into new cohesive modules
  rather than enlarging existing ones.
- Use en-GB Oxford spelling (`-ize`, `-yse`, `-our`) in comments and docs, and
  follow `docs/documentation-style-guide.md`.

## Tolerances (exception triggers)

- Scope: stop and escalate if implementation needs more than 45 changed files
  or more than 2,500 net added lines, excluding snapshots and this plan.
- Interface: stop and escalate if the `GenerationRunLauncher.launch(run_id)`
  signature must change, or if any public REST field must be removed or renamed.
- No-QA contract: stop and escalate if any `draft_without_qa` snapshot, event
  sequence or BDD scenario has to change to make the work pass.
- Architecture: stop and escalate if a Hecate `allowed` list must be broadened
  or a group reordered, or if a graph node needs to import an application
  module.
- Dependencies: stop and escalate if a new package or a version bump is
  required.
- Persistence: stop and escalate if py-pglite or PostgreSQL rejects
  `ALTER TYPE ... ADD VALUE` inside the Alembic transaction and the
  `autocommit_block()` fallback (see `Risks`) also fails.
- Semantics: stop and escalate if any stakeholder requires the escalate
  terminal to pause the run (`paused` plus a checkpoint) in this item rather
  than in 4.4.4.
- Iterations: stop and escalate if a milestone's gates still fail after three
  focused fix attempts.
- Ambiguity: stop and present options if a design question arises that this
  plan does not settle and the choice changes observable behaviour.

## Risks

- Risk: py-pglite or the Alembic transaction refuses
  `ALTER TYPE ... ADD VALUE`, or a value added in the same transaction is used
  before commit. Severity: medium. Likelihood: low. Mitigation: the migration
  only adds labels and never uses them in the same transaction, which
  PostgreSQL 12 and later allow. If py-pglite still rejects it, wrap the
  statements in `op.get_context().autocommit_block()`. The migration test in
  milestone EP-M2 proves this either way.
- Risk: LangGraph's `get_graph()` does not report explicit `path_map` targets
  as expected, which would weaken the static topology test. Severity: low.
  Likelihood: low. Mitigation: the LangGraph reference states that a `path_map`
  (or a `Literal` return annotation) bounds the drawn targets. Pin this with a
  focused test early in EP-M3. If it fails, derive topology from the builder's
  own declarative edge table instead, which is the same table that feeds
  `add_conditional_edges`.
- Risk: Alembic `compare_metadata` (used by `make check-migrations`) ignores
  enum label drift, so a missing `ADD VALUE` would not be caught. Severity:
  medium. Likelihood: high. Mitigation: EP-M2 adds a migration test that
  compares `pg_enum` labels with the Python enum values after `upgrade head`.
- Risk: snapshot churn in `tests/__snapshots__/test_generation_run_domain.ambr`
  when new enum members appear in a `repr`. Severity: low. Likelihood: medium.
  Mitigation: regenerate only the qa-gated snapshot entries. Review each
  changed line, and record the regeneration in `Decision log` with the diff
  summary.
- Risk: the nose duplication gate or the Skylos dead-code gate flags the two
  persist nodes, or `QaStatus` members that only tests reach. Severity: low.
  Likelihood: medium. Mitigation: both persist nodes delegate to one step
  method with a `qa_status` argument, so there is no duplicated body. Every new
  enum member has a production writer in this item.
- Risk: Hypothesis tests that drive a compiled LangGraph are slow on a
  contended host (see the shared-host pytest-timeout memory). Severity: low.
  Likelihood: medium. Mitigation: compile the graph once per module. Use
  `max_examples=100` with `deadline=None`. Each example uses only in-memory
  fakes, so it costs milliseconds.
- Risk: the escalate terminal fails runs in 4.4.1. Roadmap item 4.4.4 will
  turn the same outcome into a persisted escalation checkpoint, which would be
  a visible change for clients that key on `failed`. Severity: medium.
  Likelihood: high. Mitigation: this is acceptable because the project is
  pre-1.0. ADR 024 and the users' guide state that `qa.escalation_required` is
  the 4.4.1 stand-in for human review, and that the category and event kind
  remain stable when 4.4.4 lands.
- Risk: the API's accepted-mode set and the graph's evaluator set drift, so a
  runtime accepts `qa_gated` while the graph has no evaluators. Severity:
  medium. Likelihood: low. Mitigation: the composition root derives both from
  one `QualityEvaluatorSet` value. Even if they drift, an empty set fails
  closed to escalate. A runtime test asserts that the two agree.

## Progress

- [x] (2026-10-17) Renamed the branch to `4-4-1-qa-gated-mode-branching`.
- [x] (2026-10-17) Wyvern reconnaissance of run creation, orchestration and
  documentation.
- [x] (2026-10-17) Drafted this ExecPlan.
- [ ] Expert-panel design review and revision.
- [ ] Plan approved by the user.
- [ ] EP-M1: domain quality policy, routing and validation.
- [ ] EP-M2: persistence, migration and lifecycle updates.
- [ ] EP-M3: content-generation graph in orchestration.
- [ ] EP-M4: launcher executes runs through the graph.
- [ ] EP-M5: REST and composition-root acceptance of `qa_gated`.
- [ ] EP-M6: documentation, ADR acceptance, roadmap update and final gates.

## Surprises & discoveries

- Observation: the 4.3.2 no-QA run does not use LangGraph at all.
  Evidence: `episodic/generation/launcher_scheduling.py` `_execute_run` calls
  `_claim`, `_generate`, `_record_draft_generated` and `_persist_success`
  directly. The only `StateGraph`s are the planning graph
  (`episodic/orchestration/_graph_builder.py`), Pedante
  (`episodic/qa/langgraph.py`) and Chrono (`episodic/qa/chrono_langgraph.py`).
  Impact: "graph route plumbing" means introducing the content-generation graph
  and moving the launcher's post-claim sequence into it.
- Observation: `qa_gated` cannot be represented anywhere below the HTTP
  parser. Evidence: `QualityMode` has only `DRAFT_WITHOUT_QA` and `QaStatus`
  only `SKIPPED` (`episodic/canonical/generation_quality.py`).
  `_validate_draft_without_qa_metadata` rejects every other mode
  (`episodic/canonical/domain_validation.py:47`). The PostgreSQL enums carry
  one label each
  (`alembic/versions/20260624_000010_add_generation_run_tables.py:30`). Impact:
  domain, ORM and migration changes are prerequisites for routing.
- Observation: the TEI envelope hard-codes `quality_mode`, and `episodes` has
  no `quality_mode` column. Evidence: `episodic/api/serializers.py:280`.
  Impact: see decision D6.
- Observation: `generation_run_qa_bypass_total` is incremented for every
  claimed run, whatever its mode. Evidence:
  `episodic/generation/launcher_claim.py:62`. Impact: it must become
  conditional on `draft_without_qa`, otherwise QA-gated runs would be counted
  as bypasses.
- Observation: the design diagram sends both `draft_without_qa` and a QA pass
  through one shared `Persist Draft` node and on into `Prepare for Approval`.
  The prose and ADR 017 say no-QA drafts have no approval flow. The editorial
  approval state machine (roadmap 4.2.1) is not yet built. Impact: see
  decisions D3 and D4.
- Observation: a planning probe against the pinned LangGraph 1.2.11
  confirmed several behaviours.
  - `StateGraph(State, context_schema=Ctx)` with
    `async def node(state, runtime: Runtime[Ctx])` receives
    `ainvoke(..., context=Ctx(...))`.
  - `get_graph().edges` reports conditional edges with `conditional=True`,
    exactly once for each `path_map` target.
  - `astream(stream_mode="updates")` yields one `{node_name: delta}` mapping
    per executed node, and a node returning `{}` appears as `None`.
  - `ainvoke` returns a plain `dict` of the final state, not the state
    dataclass.

  Evidence: the scratch script `/tmp/lgprobe441/probe.py`, run with
  `uv run --frozen python -I`. Its output listed the edges `generate→evaluate`
  and `generate→persist_a` as conditional, and the node logs `['gen', 'pa']` and
  `['gen', 'ev']`. Impact:
  - AXM-1 and AXM-2 are supported by evidence.
  - `LangGraphContentGenerationGraph.run` must read `result["terminal"]`.
  - The INV-5 trace must treat `None` updates as visited nodes.
  - Scratch Python under `/tmp` must run from a dedicated directory with
    `-I`, because a stray `/tmp/bisect.py` shadows the standard library.
- Observation: Alembic `compare_metadata` does not compare enum labels.
  Evidence: `episodic/canonical/storage/migration_check.py` uses
  `alembic.autogenerate.compare_metadata`, which does not diff enum values.
  Impact: a dedicated migration test is needed (EP-M2).

## Decision log

Decisions D1 to D9 are proposed in this draft and await the expert-panel
review. ADR 024 records them during EP-M1 and is accepted in EP-M6.

- Decision D1: the content-generation graph is a LangGraph `StateGraph` that
  is compiled once and injected into the launcher through a domain-level port.
  `ContentGenerationGraphPort` lives in `domain_ports`. The LangGraph adapter
  `LangGraphContentGenerationGraph` lives in `orchestration`. The composition
  root passes the adapter to `InProcessGenerationRunLauncher` as a new required
  field, `content_graph`. Rationale: Hecate forbids `application` from importing
  `orchestration`, so the dependency has to be inverted. ADR 017 anticipated
  that 4.4.1 would replace the one-pass policy without changing the launcher
  port, and `launch(run_id)` is unchanged. Roadmap items 4.4.2 and 4.4.3 need a
  real cyclic graph, so introducing LangGraph now is not speculative. Per-run
  collaborators reach nodes through LangGraph's runtime context
  (`StateGraph(..., context_schema=...)` with `Runtime[...]` node arguments).
  That keeps the compiled graph stateless and shareable across concurrent runs.
  Date/Author: 2026-10-17, planning agent.
- Decision D2: graph state holds only domain values: `run_id`,
  `quality_mode`, `verdict` and `terminal`. Heavy application objects
  (`ClaimedRun`, `DraftScriptResult`) stay inside a per-run *run session*
  object owned by the launcher. That object implements the
  `ContentGenerationSteps` port. Rationale: nodes must not import application
  types (ADR 022). Keeping the session as the single writer satisfies the
  roadmap's single-writer and ordered-publication requirement. Checkpoint
  payloads stay orchestration metadata only. Date/Author: 2026-10-17, planning
  agent.
- Decision D3: each branch owns its own terminal nodes.
  `persist_draft_without_qa` belongs to `draft_without_qa`.
  `persist_qa_passed_draft` and `escalate` belong to `qa_gated`. Both persist
  nodes delegate to one step method, `complete_with_draft(qa_status=...)`.
  Rationale: the roadmap asks for "distinct terminal states without ambiguous
  branch ownership". A shared `Persist Draft` node would make the terminal
  ambiguous: its owner could only be told from history, not from the node.
  Splitting the node is a small refinement of the design diagram. ADR 024
  records it and EP-M6 updates the diagram. Date/Author: 2026-10-17, planning
  agent.
- Decision D4: `Prepare for Approval`, `Refine`, `Aggregate` as a separate
  node, parallel evaluator fan-out and checkpointed `Escalate` are out of
  scope. In 4.4.1, `escalate` is a terminal that fails the run with
  `error_category="qa.escalation_required"` and `qa_status=failed`, writes no
  TEI, and appends a `qa.escalated` event whose `reason` is `failed` or
  `inconclusive`. Rationale: the approval state machine (4.2.1), Chrono in-loop
  (4.4.2), refinement and iteration caps (4.4.3) and escalation checkpoints
  (4.4.4) are separate roadmap items. A failed terminal is deterministic,
  terminal under `GenerationRunStatus.is_terminal()`, and honest. Later items
  can replace it without changing the event kind or the category. Date/Author:
  2026-10-17, planning agent.
- Decision D5: QA-status lifecycle.
  - `QaStatus` gains `PENDING`, `PASSED` and `FAILED`.
  - For `draft_without_qa`, `qa_status` is always `skipped` and
    `skip_qa_rationale` is required and non-blank, as today.
  - For `qa_gated`, `skip_qa_rationale` must be absent.
  - For `qa_gated`, `qa_status` is `pending` while the run is non-terminal,
    `passed` if and only if the run is `succeeded`, and `pending` or `failed`
    when the run is `failed` or `cancelled`.
  - `GenerationRunStatusUpdate` gains an optional `qa_status`, where `None`
    means unchanged. Adapters validate the would-be run before mutating.
  Rationale: this makes "a QA-gated run succeeded" equivalent to "QA passed",
  which is the central safety invariant. A skip rationale on a gated run would
  be contradictory provenance, so it is rejected rather than ignored.
  Date/Author: 2026-10-17, planning agent.
- Decision D6: the TEI envelope derives `quality_mode` from the episode's
  persisted `qa_status`. `skipped` maps to `draft_without_qa` and `passed` maps
  to `qa_gated`. `EpisodeTeiUpdate` refuses any other status. No
  `episodes.quality_mode` column is added. Rationale: only these two statuses
  can ever be persisted onto an episode under D5, so the mapping is total and
  injective over the reachable domain. A column would duplicate derivable data
  and require a backfill migration. A pure function
  `quality_mode_for_persisted_qa_status` owns the rule and is tested
  exhaustively. Date/Author: 2026-10-17, planning agent.
- Decision D7: REST acceptance of `qa_gated` depends on capability.
  `ApiDependencies` gains `accepted_quality_modes`, which defaults to
  `frozenset({QualityMode.DRAFT_WITHOUT_QA})`. The composition root derives it
  from the same `QualityEvaluatorSet` that configures the graph. A runtime that
  does not accept the mode returns the existing `422 quality_mode_unsupported`
  envelope unchanged. Where the mode is accepted, a body containing
  `skip_qa_rationale` is rejected with `400 validation_error` and
  `constraint: "forbidden"`. Rationale: production has no QA evaluator until
  4.4.2. Accepting the mode unconditionally would spend inference budget on
  runs that must always escalate. Gating keeps the 4.3.2 forward-compatibility
  promise ("422 → 202 is forward-compatible") and lets tests, BDD and
  end-to-end tests exercise the whole branch by binding a deterministic
  evaluator. Date/Author: 2026-10-17, planning agent.
- Decision D8: verdict aggregation is "all must pass".
  - An empty evaluator list gives `inconclusive`.
  - Any `failed` verdict gives `failed`.
  - Otherwise, any `inconclusive` verdict gives `inconclusive`.
  - Otherwise the result is `passed`.
  - An evaluator that raises is treated as `inconclusive` for that evaluator.
    The exception is logged with the evaluator name and is not re-raised,
    because a QA tool outage must not be mistaken for a generator failure.
    Cancellation (`asyncio.CancelledError`) is always re-raised.
  Rationale: the system design's default aggregation policy is "all must pass".
  Configurable policies are 4.4.2 and 4.4.3 work. Date/Author: 2026-10-17,
  planning agent.
- Decision D9: the event stream for `qa_gated` runs is:
  1. `run.started` (unchanged).
  2. `draft.generated` (unchanged).
  3. `qa.evaluation_started`, with payload
     `{"current_node": "evaluate", "evaluators": [<names>]}`, together with a
     non-terminal status update setting `current_node="evaluate"`.
  4. `qa.result`, with payload
     `{"verdict": <passed|failed|inconclusive>, "evaluator_count": <n>}`.
  5. Either `tei.persisted` with `qa_status="passed"`, then `run.succeeded`,
     or `qa.escalated` with `{"reason": <failed|inconclusive>}`, then
     `run.failed` with `error_category="qa.escalation_required"`.

  `draft_without_qa` runs emit no new events. The branch decision is logged
  (`generation_run.quality_branch run_id=%s branch=%s`) and set as a span
  attribute. Rationale: `qa.result` already appears in the TUI API event
  catalogue. ADR 009 asks for the branch decision to be observable. Constraint
  1 forbids changing the no-QA stream. Date/Author: 2026-10-17, planning agent.

## Outcomes & retrospective

Not started. Complete this at each milestone and at the end. Before marking the
plan `COMPLETE`, reconcile discoveries with ADR 017, ADR 022, ADR 024, the
system design and the TUI API design.

## Context and orientation

The repository is a Python 3.14 service named `episodic`, with its package in
`episodic/` and its tests in `tests/`. It follows hexagonal architecture:
domain types and port protocols are pure, and adapters implement them. Hecate,
an import-boundary checker configured under `[tool.hecate]` in
`pyproject.toml`, enforces the layers. Groups match by module prefix, and the
first matching group wins, so a broad prefix listed earlier silently captures
modules intended for a later group.

Terms used in this plan:

- A *generation run* is a durable record of one attempt to turn ingested
  sources into a TEI-P5 podcast script. Its domain type is `GenerationRun`
  (`episodic/canonical/domain_generation.py`), its statuses are in
  `GenerationRunStatus` (`episodic/canonical/domain_enums.py`), and its ports
  are in `episodic/canonical/generation_run_ports.py`.
- *Quality mode* is the requested QA policy for a run (`QualityMode` in
  `episodic/canonical/generation_quality.py`). *QA status* (`QaStatus`) is the
  recorded QA outcome on the run and on the episode TEI it wrote.
- The *launcher* is `InProcessGenerationRunLauncher`
  (`episodic/generation/launcher.py`), a dataclass composed of three mixins:
  - `launcher_scheduling.py` handles admission, the task registry, shutdown
    and `_execute_run`.
  - `launcher_claim.py` handles the atomic `pending→running` claim,
    hydration and draft generation.
  - `launcher_persistence.py` handles events, TEI, costs and terminal
    writes.

  `launcher_host.py` declares the shared mixin surface as a protocol that
  exists only for type checking. Issue #350 tracks replacing these mixins with
  injected components. This plan adds new behaviour in new modules and does not
  attempt that refactor.
- A *step port* is a protocol through which a graph node asks the launcher to
  perform one I/O step for the run it is executing.
- A *terminal* is a graph node after which the graph ends, together with the
  `GenerationTerminal` value that node returns.
- *Branch ownership* means that every non-shared graph node, and every
  terminal, belongs to exactly one quality branch.
- *Vidai Mock* is an offline, wire-accurate mock of OpenAI-compatible
  inference servers, used by the behavioural tests
  (`tests/steps/vidaimock_harness.py`). It requires `vidaimock` 0.2.8 or later.
  Fixtures pass `--isolated`.

The key files for this work are:

- `episodic/canonical/generation_quality.py`,
  `episodic/canonical/domain_validation.py` and
  `episodic/canonical/domain_generation.py` hold the quality enums and run
  validation.
- `episodic/canonical/domain_episodes.py` holds `EpisodeTeiUpdate`, and
  `episodic/canonical/generation_persistence.py` holds `persist_draft_script`.
- The run store adapters are `episodic/canonical/generation_run_ports.py`,
  `episodic/canonical/storage/generation_runs.py` (SQL) and
  `episodic/canonical/adapters/generation_runs.py` (in-memory).
- The ORM enums and columns are in
  `episodic/canonical/storage/models_base.py` and
  `episodic/canonical/storage/generation_run_models.py`.
- Migrations live in `alembic/versions/`. The current head is
  `20261010_000013_name_pricing_snapshot_constraint.py`.
- The REST surface is `episodic/api/resources/generation_runs.py`,
  `episodic/api/resources/generation_runs_create_support.py`,
  `episodic/api/serializers.py` and `episodic/api/dependencies.py`. The
  composition root is `episodic/api/runtime.py`.
- The launcher modules are `episodic/generation/launcher*.py`.
- The existing graph examples are in `episodic/orchestration/_graph_builder.py`,
  `episodic/qa/langgraph.py` and `episodic/qa/chrono_langgraph.py`.
- The tests most affected are:
  - `tests/test_generation_run_domain.py`, with its snapshot
    `tests/__snapshots__/test_generation_run_domain.ambr`.
  - `tests/test_generation_run_api.py`, which currently asserts the 422 for
    `qa_gated` at lines 371–398.
  - `tests/test_generation_run_launcher*.py` and
    `tests/generation_run_launcher_support.py`.
  - `tests/test_generation_run_port_contract.py`,
    `tests/canonical_storage/test_generation_runs.py`, and
    `tests/test_production_hecate_orchestration_config.py`.
  - The `tests/features/no_qa_generation_slice.feature` scenario "An
    unsupported quality mode is unprocessable", and its steps in
    `tests/steps/test_no_qa_generation_slice.py`.

Signposted documentation (read before starting each milestone):

- `docs/roadmap.md` §4.4, which gives the item text and the 4.4 concurrency
  model.
- `docs/episodic-podcast-generation-system-design.md`, in particular the
  "Content Generation Graph", "LangGraph Integration Principles", "Quality
  Assurance Stack", "Configuration and Tunables" and "Source-to-script vertical
  slice" sections.
- `docs/episodic-tui-api-design.md`, in particular "Generation runs", the
  event catalogue and the source-to-script vertical slice.
- ADR 009, ADR 014, ADR 015 (generation-run port split), ADR 017 and ADR 022
  in `docs/adr/`.
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` (conditional
  routing as application policy) and
  `docs/agentic-systems-with-langgraph-and-celery.md`.
- `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md` and
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.
- In `docs/developers-guide.md`: "Generation-run domain ports", "No-QA
  launcher and TEI retrieval", "Testing the orchestration slice" and the Vidai
  Mock harness section.
- `docs/documentation-style-guide.md`, which defines the ADR format. The next
  free ADR number is 024.

Signposted skills for the implementer:

- `hexagonal-architecture`, for port placement and the dependency rule.
- `python-router`, which routes on to `python-types-and-apis`,
  `python-data-shapes`, `python-concurrency` and `python-testing`.
- `hypothesis` and `python-verification`, for property design and
  non-vacuity.
- `vidai-mock`, for the behavioural inference server.
- `codegraph-mcp` (or `leta`), for caller and impact analysis before editing
  the launcher.
- `skylos`, for the dead-code gate.
- `execplans`, for maintaining this document.
- `commit-message` and `pr-creation`, for delivery.

## Conformance basis

Upstream artefacts:

- Roadmap item `docs/roadmap.md` §4.4.1 and the §4.4 preamble, at commit
  `468923ed` on `main`. There are no Terms of Reference document and no
  numbered requirement register, so this plan assigns local identifiers.
- The technical design is `docs/episodic-podcast-generation-system-design.md`
  at `468923ed`, section "Content Generation Graph" (SD-CGG).
- ADRs:
  - ADR 009, source-to-script slice (ADR-009).
  - ADR 017, no-QA execution and launcher port (ADR-017).
  - ADR 022, orchestration architecture enforcement (ADR-022).
  - ADR 014, hexagonal enforcement (ADR-014).
- Governing standards are `AGENTS.md`, `docs/documentation-style-guide.md`
  and `.rules/python-*.md`.

Local identifiers:

- `RM-441-A`: extend run creation and run-state validation for `qa_gated`.
- `RM-441-B`: preserve `draft_without_qa` as a direct route to draft
  persistence.
- `RM-441-C`: route `qa_gated` into the evaluation branch of SD-CGG.
- `RM-441-D`: Hypothesis properties showing distinct terminal states without
  ambiguous ownership.
- `RM-441-S`: deterministic, distinct branches with clear terminal states
  (the success criterion).
- `RM-44-CONC`: single-writer run state, ordered event publication and
  shutdown-safe cancellation (the §4.4 preamble).

Trace links:

```plaintext
RM-441-A -> SD-CGG.Initialize -> D5, D7 -> EP-M1, EP-M2, EP-M5 -> INV-1, INV-2, INV-11, INV-12
RM-441-B -> SD-CGG.QualityBranch -> D3, D9 -> EP-M3, EP-M4 -> INV-5, INV-8
RM-441-C -> SD-CGG.Evaluate -> D1, D4, D8 -> EP-M3, EP-M4 -> INV-4, INV-5
RM-441-D -> SD-CGG -> D3 -> EP-M1, EP-M3 -> INV-3, INV-5, INV-6, INV-7
RM-441-S -> SD-CGG -> D1-D9 -> EP-M5 -> BDD qa_gated_generation_routing.feature
RM-44-CONC -> ADR-017 -> D2 -> EP-M4 -> INV-9, INV-10
ADR-022 -> D1, D2 -> EP-M3 -> make lint (Hecate), tests/test_production_hecate_orchestration_config.py
```

Deviations from SD-CGG:

- D3 splits the shared Persist Draft node into two nodes.
- D4 defers Aggregate as a node, Refine, Prepare for Approval and
  checkpointed Escalate.

Both deviations are recorded in ADR 024, and the SD-CGG prose and diagram are
updated in EP-M6.

## Verification plan

This change introduces real invariants over states and transitions, so examples
alone are not enough. The obligations below are listed in dependency order.

Axioms (trusted, not verified):

- AXM-1: LangGraph `StateGraph` with explicit `path_map` conditional edges
  calls the router with the post-node state and follows only mapped targets.
  `ainvoke` on a graph without parallel branches runs nodes sequentially in the
  caller's task. `context=` delivers the runtime context to nodes that declare a
  `Runtime[...]` parameter. This is documented at
  `docs.langchain.com/oss/python/langgraph/graph-api` ("Conditional edges",
  "Runtime context").
- AXM-2: `CompiledStateGraph.get_graph()` reports declared edges. With a
  `path_map`, its conditional edges list exactly the mapped targets (LangGraph
  reference for `add_conditional_edges`). EP-M3 pins this axiom with a focused
  test, because INV-7 relies on it.
- AXM-3: PostgreSQL `ALTER TYPE ... ADD VALUE IF NOT EXISTS` appends a label.
  The label cannot be used inside the same transaction, and labels cannot be
  dropped without recreating the type (PostgreSQL 18 manual, `ALTER TYPE`
  notes).
- AXM-4: py-pglite faithfully implements PostgreSQL enum semantics for these
  statements.
- AXM-5: Hypothesis's shrinking and example generation behave as documented.
  Vidai Mock returns its configured responses wire-accurately.
- AXM-6: asyncio delivers `CancelledError` at the awaiting point of a
  cancelled task, and `asyncio.shield` protects the inner write.

Obligations:

- INV-1 (quality-metadata validity). Statement: `GenerationRun(...)`
  constructs without error if and only if
  `(quality_mode, status, qa_status, skip_qa_rationale)` satisfies the D5
  policy table.
  - Method: Hypothesis property against an independently written oracle
    function in the test module, plus a parameterized witness table (one
    named row per policy cell).
  - Domain: all `QualityMode` × `GenerationRunStatus` × (`QaStatus` | `None`),
    with rationales drawn from `None`, blank or whitespace-only text, and
    non-blank text.
  - Artefact: `tests/test_generation_quality_policy_properties.py`.
  - Evidence: `make test` with `-k quality_policy`. It fails before EP-M1
    because `qa_gated` cannot be constructed. It passes afterwards.
  - Non-vacuity: `hypothesis.event()` labels each (mode, accept/reject)
    class, and a companion test asserts that all four classes occur within
    the run's statistics. A seeded mutation, deleting the "rationale
    forbidden for qa_gated" check, must make the property fail. Run it once
    under `mutmut` or by hand and record it in `Artefacts and notes`.
- INV-2 (QA-gated success iff passed). Statement: for `qa_gated`, `status`
  is `succeeded` if and only if `qa_status` is `passed`. For `draft_without_qa`,
  `qa_status` is always `skipped`. Store adapters reject any
  `GenerationRunStatusUpdate` that would violate this, and leave the stored row
  unchanged.
  - Method: INV-1 for construction, plus a Hypothesis property over
    `(initial run, update)` pairs against both the in-memory and SQL adapters
    through the existing port-contract harness.
  - Artefacts: `tests/test_generation_run_port_contract.py` (extended) and
    `tests/canonical_storage/test_sql_generation_run_property_contract.py`
    (extended).
  - Non-vacuity: the generator must produce both accepted and rejected
    updates, and must cover every terminal status, checked with `event()`.
    Negative control: the SQL adapter variant that mutates before validating
    (a seeded fault in a test-local subclass) must be caught by the "row
    unchanged after rejection" assertion.
- INV-3 (routing totality, determinism and injectivity). Statement:
  `route_quality_mode` is defined for every `QualityMode`, returns the same
  `QualityBranch` on every call, and maps distinct modes to distinct branches.
  `branch_for_terminal` is total over `GenerationTerminal`. Every branch owns
  at least one terminal.
  - Method: exhaustive parameterized test (the domain is finite and small),
    plus a static exhaustiveness guarantee from a `match` with
    `typ.assert_never`, which pyright checks.
  - Artefact: `tests/test_generation_routing_policy.py`.
  - Non-vacuity: adding a hypothetical enum member breaks type checking.
    Demonstrate this once in a scratch branch and record it. The
    injectivity assertion fails if both modes are mapped to one branch.
- INV-4 (verdict aggregation). Statement: `aggregate_verdicts(vs)` is
  `passed` if and only if `vs` is non-empty and every element is `passed`. It is
  `failed` if any element is `failed`. Otherwise it is `inconclusive`. The
  result is invariant under permutation and duplication of elements.
  - Method: Hypothesis over `lists(sampled_from(QualityVerdict))`, with an
    independent oracle and permutation and duplication metamorphic
    relations.
  - Artefact: `tests/test_generation_routing_policy.py`.
  - Non-vacuity: classify examples by result with `event()`, and require all
    three results plus the empty list. Negative control: an "any passes"
    implementation, injected through a test-local function, must fail the
    oracle.
- INV-5 (branch ownership at runtime). Statement: for every generated run
  state (quality mode, a list of evaluator verdicts or raised errors, and an
  optional fault-injection point in
  `{initialize, generate, evaluate, persist, escalate}`), invoking the compiled
  content-generation graph with fake step ports gives one of two results.
  Either it returns exactly one `GenerationTerminal` and every visited node
  lies in `SHARED ∪ owned_nodes(route_quality_mode(mode))`, with
  `branch_for_terminal(terminal) == route_quality_mode(mode)`, or it propagates
  the injected fault with no terminal step call recorded. Additionally:
  - `draft_without_qa` never calls `begin_evaluation`, any evaluator, or
    `escalate`.
  - `qa_gated` calls `complete_with_draft` only after a `passed` aggregate,
    and always with `qa_status=PASSED`.
  - `draft_without_qa` calls `complete_with_draft` only with
    `qa_status=SKIPPED`.

  Further details:
  - Method: Hypothesis property driving the real compiled graph
    (`astream(stream_mode="updates")` to observe the node sequence) with a
    recording fake `ContentGenerationSteps` and fake evaluators.
  - Artefacts: `tests/test_content_generation_graph_properties.py`, with
    fakes in `tests/_content_graph_fakes.py`.
  - Non-vacuity: `event()` classification over (mode, terminal or fault
    point), and a test asserting that all five classes are reached: no-QA
    persisted, QA passed, QA escalated failed, QA escalated inconclusive, and
    fault. The property's checker, `assert_branch_ownership(trace, mode)`, is
    itself tested against hand-built bad traces (a no-QA trace that visits
    `evaluate`, and a QA trace ending in `persist_draft_without_qa`), and it
    must reject both. A seeded fault, building the graph with a deliberately
    swapped `path_map` through a test-only builder argument, must make the
    property fail.
- INV-6 (determinism). Statement: invoking the graph twice with the same
  generated input yields identical node sequences, identical step-call logs and
  identical terminals.
  - Method: folded into the INV-5 property as a second invocation per
    example.
  - Non-vacuity: the step-call logs must be non-empty in every non-fault
    class.
- INV-7 (static topology). Statement: in `compiled.get_graph()`:
  - the node sets reachable from `persist_draft_without_qa` and from
    `evaluate` are disjoint, apart from `__end__`;
  - every terminal node has exactly one outgoing edge, to `__end__`;
  - every conditional edge's targets equal the declared `path_map` values;
  - `__start__` reaches every node.
  - Method: a structural unit test over the compiled graph, plus a syrupy
    snapshot of `draw_mermaid()` to pin the topology for reviewers.
  - Artefacts: `tests/test_content_generation_graph_topology.py` and
    `tests/__snapshots__/test_content_generation_graph_topology.ambr`.
  - Non-vacuity: the reachability helper is tested on a hand-built graph
    with a shared node, and must report the overlap. AXM-2 is pinned by a
    focused test.
- INV-8 (no-QA stream preservation). Statement: a `draft_without_qa` run's
  event kinds, payloads, `current_node` values, terminal status, error fields,
  metrics and persisted TEI provenance are identical to those of 4.3.2.
  - Method: regression evidence. All existing tests and snapshots pass
    without regeneration.
  - Artefacts: the existing `tests/test_generation_run_launcher*.py`, the
    `.ambr` files and `tests/features/no_qa_generation_slice.feature`.
  - Evidence: `git diff --stat tests/__snapshots__/` shows no change to
    no-QA entries at the end of EP-M4 and EP-M5.
  - Non-vacuity: these tests already fail on any change to event payloads.
    That was established in 4.3.2.
- INV-9 (single writer and ordered publication). Statement: for every
  mode × outcome in
  `{succeeded, escalated, generator failure, evaluator error, cancelled}`, a
  run's events have strictly increasing `seq`, exactly one terminal event
  (`run.succeeded` or `run.failed`) which is the last event, and only the
  launcher task appends them.
  - Method: parameterized launcher test over the full product, reusing the
    `test_generation_run_launcher_properties.py` pattern, against py-pglite.
  - Artefact: `tests/test_generation_run_launcher_quality_modes.py`.
  - Non-vacuity: each product cell asserts its specific terminal kind, so a
    missing or duplicated terminal fails the cell.
- INV-10 (shutdown-safe cancellation in the QA branch). Statement: cancelling
  a `qa_gated` run while an evaluator is awaiting records one `run.failed` with
  `launcher.shutdown`. The run's `qa_status` stays `pending`, there is no
  `tei.persisted` event, and the episode TEI revision is unchanged.
  - Method: a concrete interleaving test with a `BlockingEvaluator` that
    awaits an `asyncio.Event`, followed by `launcher.shutdown()`.
  - Artefact: `tests/test_generation_run_launcher_quality_modes.py`.
  - Non-vacuity: the test asserts that the evaluator was entered before
    shutdown, so the cancellation point really is inside `evaluate`.
- INV-11 (migration label parity). Statement: after `alembic upgrade head`,
  the `pg_enum` labels for `quality_mode` and `qa_status` equal the Python enum
  values. A `qa_gated` run row can be inserted and read back. Downgrade
  refuses, with a clear error, when rows use the new labels, and succeeds
  (recreating the types) when none do.
  - Method: py-pglite migration tests following
    `tests/test_pricing_snapshot_constraint_migration.py`.
  - Artefact: `tests/test_qa_gated_quality_mode_migration.py`.
  - Non-vacuity: the parity check runs first against the previous revision
    and must report the missing labels there.
- INV-12 (REST capability gate). Statement: `POST .../generation-runs` with
  `quality_mode=qa_gated` returns `202` if and only if
  `QualityMode.QA_GATED in accepted_quality_modes` and no `skip_qa_rationale`
  is supplied. With the mode accepted, a rationale gives `400` with
  `constraint: "forbidden"`. With the mode not accepted, the response is the
  unchanged `422 quality_mode_unsupported` envelope. Unknown modes stay `400`
  with `constraint: "enum"`.
  - Method: a parameterized Falcon test over (accepted set) × (mode) ×
    (rationale present), plus syrupy snapshots of the three error envelopes.
  - Artefacts: `tests/test_generation_run_api_quality_modes.py` and the
    `.ambr` file.
- INV-13 (TEI envelope mode derivation). Statement:
  `quality_mode_for_persisted_qa_status` maps `skipped` to `draft_without_qa`
  and `passed` to `qa_gated`, and raises for every other status.
  `EpisodeTeiUpdate` rejects `pending` and `failed`.
  - Method: an exhaustive parameterized test over `QaStatus`.
  - Artefact: `tests/test_generation_routing_policy.py`.

Residual gaps:

- Parallel evaluator execution, real evaluators, iteration caps and resume
  replay are out of scope (roadmap items 4.4.2 to 4.4.4).
- INV-5 uses fake step ports, and INV-9 and INV-10 together cover the real
  launcher. Interleavings across process restarts are not covered; that is
  roadmap item 2.6.2.

## Plan of work

Stage A, understand and propose (this document): complete once the expert
review is folded in and the user approves.

Stage B, red: each milestone below opens with failing tests. Where pytest
supports it, mark them `@pytest.mark.xfail(strict=True, reason="4.4.1 red: …")`
until the red failure has been observed for the intended reason. Remove the
marker in the green step.

Stage C, green: make the smallest production change that turns each red test
green, building verification scaffolding (fakes, oracles) alongside it.

Stage D, refactor and document: clean up, run all gates, and update
documentation.

### EP-M1: domain quality policy, routing and validation

Red tests:

- `tests/test_generation_quality_policy_properties.py` (INV-1).
- `tests/test_generation_routing_policy.py` (INV-3, INV-4 and INV-13).
- New rows in `tests/test_generation_run_domain.py` for `qa_gated`
  construction.

Production changes:

1. `episodic/canonical/generation_quality.py`:
   - Add `QualityMode.QA_GATED = "qa_gated"`, and
     `QaStatus.PENDING = "pending"`, `PASSED = "passed"` and
     `FAILED = "failed"`.
   - Add `quality_metadata_violation(*, quality_mode, status, qa_status,
     skip_qa_rationale) -> str | None`. This pure query returns the first
     violated rule's message, or `None`. Express it as a `match` on
     `quality_mode` that ends in `typ.assert_never`.
   - Add `quality_mode_for_persisted_qa_status(qa_status) -> QualityMode`.

   This module must not import `GenerationRunStatus` from a module that imports
   it back. `domain_enums` is a leaf, so importing from it is safe.
2. `episodic/canonical/domain_validation.py`: replace
   `_validate_draft_without_qa_metadata` with `_validate_quality_metadata`,
   which raises `ValueError(message)` when `quality_metadata_violation` returns
   a message. Keep the existing `draft_without_qa` messages verbatim, because
   the error-message snapshot pins them.
3. `episodic/canonical/domain_generation.py`: call the new validator with
   `status`. Keep the field defaults (`quality_mode=DRAFT_WITHOUT_QA`,
   `qa_status=None`) so that callers built for 4.3.2 behave identically.
4. New `episodic/canonical/generation_routing.py`, a `domain_ports` module
   holding only pure policy:
   - `QualityBranch(StrEnum)`, with `DRAFT_WITHOUT_QA` and `QA_GATED`.
   - `QualityVerdict(StrEnum)`, with `PASSED`, `FAILED` and `INCONCLUSIVE`.
   - `GenerationTerminal(StrEnum)`, with `DRAFT_PERSISTED_WITHOUT_QA`,
     `QA_PASSED_DRAFT_PERSISTED` and `QA_ESCALATED`.
   - `route_quality_mode(mode) -> QualityBranch` and
     `branch_for_terminal(terminal) -> QualityBranch`.
   - `aggregate_verdicts(verdicts: cabc.Iterable[QualityVerdict]) ->
     QualityVerdict`.
   - `route_after_evaluation(verdict) -> GenerationTerminal`.
   - `TerminalOutcome`, a frozen dataclass holding `status`, `qa_status`,
     `error_category` and `error_message`, and
     `terminal_outcome(terminal, *, verdict) -> TerminalOutcome`.
5. New `episodic/canonical/generation_graph_ports.py`, a `domain_ports`
   module holding only protocols and value objects:
   - `EvaluationSubject`, a frozen dataclass of `run_id`, `episode_id`,
     `tei_xml` and `content_hash`.
   - `QualityEvaluatorPort`, with a `name: str` property and
     `async evaluate(subject) -> QualityVerdict`.
   - `QualityEvaluatorSet`, a frozen dataclass wrapping
     `tuple[QualityEvaluatorPort, ...]`, with `accepted_quality_modes() ->
     frozenset[QualityMode]`.
   - `ContentGenerationSteps`, a protocol with:
     - `initialize() -> None`.
     - `generate_draft() -> None`.
     - `begin_evaluation(evaluator_names: tuple[str, …]) ->
       EvaluationSubject`.
     - `record_quality_result(verdict, evaluator_count) -> None`.
     - `complete_with_draft(qa_status) -> None`.
     - `escalate(verdict) -> None`.
   - `ContentGenerationRequest`, a frozen dataclass of `run_id` and
     `quality_mode`.
   - `ContentGenerationGraphPort`, with `async run(request, *, steps) ->
     GenerationTerminal`.
6. `pyproject.toml`: add `episodic.canonical.generation_routing` and
   `episodic.canonical.generation_graph_ports` to the `domain_ports` prefixes.
   Check that neither prefix is a string-prefix of a module in another group.
7. Write
   `docs/adr/adr-024-qa-gated-mode-branching-and-content-generation-graph.md`
   with status `Proposed`, recording D1 to D9.

Regenerate only the qa-gated entries in
`tests/__snapshots__/test_generation_run_domain.ambr`, and only if a `repr`
changed. Review the diff by hand.

### EP-M2: persistence, migration and lifecycle updates

Red tests:

- `tests/test_qa_gated_quality_mode_migration.py` (INV-11).
- Port-contract and SQL property extensions (INV-2).
- An `EpisodeTeiUpdate` rejection test (INV-13).
- `persist_draft_script` writes the supplied `qa_status`.

Production changes:

1. New `alembic/versions/20261017_000014_add_qa_gated_quality_mode.py`,
   with `down_revision` set to `20261010_000013`.
   - Upgrade: `ALTER TYPE quality_mode ADD VALUE IF NOT EXISTS 'qa_gated'`,
     and `ALTER TYPE qa_status ADD VALUE IF NOT EXISTS` for `pending`,
     `passed` and `failed`.
   - Downgrade:
     1. Refuse with `RuntimeError` if any `generation_runs` or `episodes` row
        uses a new label.
     2. Otherwise rename each type to `*_old`.
     3. Create the original single-label type.
     4. `ALTER COLUMN ... TYPE ... USING col::text::<type>`.
     5. Drop `*_old`.
2. `episodic/canonical/generation_run_ports.py`: add
   `qa_status: QaStatus | None = None` to `GenerationRunStatusUpdate`, where
   `None` means unchanged, and document it in the NumPy docstring.
3. `episodic/canonical/storage/generation_runs.py` and
   `episodic/canonical/adapters/generation_runs.py`: in `update_run_status`,
   compute the resulting `(status, qa_status)` and call
   `quality_metadata_violation`, raising `ValueError` before mutating anything.
   Then apply `qa_status` when it is not `None`. Keep both adapters in step
   through the shared contract tests.
4. `episodic/canonical/domain_episodes.py`: `EpisodeTeiUpdate.__post_init__`
   rejects any `qa_status` other than `SKIPPED` or `PASSED`.
5. `episodic/canonical/generation_persistence.py`:
   `DraftScriptPersistenceRequest` gains `qa_status: QaStatus`, and
   `persist_draft_script` writes it. The only existing caller passes
   `QaStatus.SKIPPED`, so no-QA behaviour is unchanged.
6. `episodic/api/serializers.py`: `serialize_tei_envelope` uses
   `quality_mode_for_persisted_qa_status(episode.qa_status)` when `qa_status`
   is set. It keeps emitting `draft_without_qa` when `qa_status` is `None`, as
   it does today, so 4.3.2 envelopes are byte-identical.

### EP-M3: content-generation graph in orchestration

Red tests:

- `tests/test_content_generation_graph_properties.py` (INV-5 and INV-6).
- `tests/test_content_generation_graph_topology.py` (INV-7 and the AXM-2 pin).
- The extended `tests/test_production_hecate_orchestration_config.py`
  mapping.

Production changes:

1. New `episodic/orchestration/_content_graph_state.py`
   (`orchestration_nodes`):
   - `ContentGenerationGraphState`, a `@dc.dataclass(slots=True)` with
     `request: ContentGenerationRequest`, `verdict: QualityVerdict | None =
     None` and `terminal: GenerationTerminal | None = None`.
   - `ContentGenerationContext`, a frozen dataclass holding
     `steps: ContentGenerationSteps` and
     `evaluators: tuple[QualityEvaluatorPort, ...]`.
   - The node-name constants and the ownership table:
     - `SHARED_NODES = ("initialize", "generate")`.
     - `BRANCH_NODES: Mapping[QualityBranch, tuple[str, ...]]`, mapping
       `DRAFT_WITHOUT_QA` to `("persist_draft_without_qa",)` and `QA_GATED`
       to `("evaluate", "persist_qa_passed_draft", "escalate")`.
2. New `episodic/orchestration/_content_graph_nodes.py`
   (`orchestration_nodes`), with one small async function per node. Each takes
   `(state, runtime: Runtime[ContentGenerationContext])` and returns a state
   delta:
   - `initialize` and `generate` delegate to the matching step.
   - `evaluate` calls `begin_evaluation`, then awaits each evaluator in
     order. An evaluator exception (other than `CancelledError`) is mapped to
     `INCONCLUSIVE` and logged. The node then aggregates the verdicts, calls
     `record_quality_result`, and returns `{"verdict": ...}`.
   - The two persist nodes call `complete_with_draft` with `SKIPPED` or
     `PASSED` and set `terminal`.
   - `escalate` calls `steps.escalate(verdict)` and sets `QA_ESCALATED`.
   - The routers `route_after_generate(state) -> QualityBranch` and
     `route_after_evaluation_node(state) -> GenerationTerminal` delegate to
     the domain policy.
3. New `episodic/orchestration/content_generation.py` (`orchestration`):
   - `build_content_generation_graph(*, path_maps: _PathMaps | None = None)`.
     The private `path_maps` argument exists only so that the INV-5
     seeded-fault test can swap targets. It defaults to the production
     mapping, which is defined once beside the builder.
     - The graph is built with `StateGraph(ContentGenerationGraphState,
       context_schema=ContentGenerationContext)`.
     - Edges: `START→initialize→generate`.
     - Conditional edges from `generate`, with an explicit `path_map`:
       `{DRAFT_WITHOUT_QA: "persist_draft_without_qa", QA_GATED:
       "evaluate"}`.
     - Conditional edges from `evaluate`, with an explicit `path_map`:
       `{QA_PASSED_DRAFT_PERSISTED: "persist_qa_passed_draft",
       QA_ESCALATED: "escalate"}`.
     - Each terminal has an edge to `END`.
   - `LangGraphContentGenerationGraph`, which implements
     `ContentGenerationGraphPort`. It compiles once in `__post_init__`,
     holds a `QualityEvaluatorSet`, and in `run()` calls `ainvoke` with
     `context=ContentGenerationContext(...)`. `ainvoke` returns a plain
     `dict`, so it reads the final state's `"terminal"` key, coerces the
     value to `GenerationTerminal`, and raises
     `ContentGenerationIncompleteError` if the key is missing or `None`.
4. `pyproject.toml`: add `episodic.orchestration._content_graph_state` and
   `episodic.orchestration._content_graph_nodes` to the `orchestration_nodes`
   prefixes. Update `EXPECTED_PRODUCTION_ORCHESTRATION_GROUPS` in
   `tests/test_production_hecate_orchestration_config.py` with all three new
   modules. Re-export `LangGraphContentGenerationGraph` and
   `build_content_generation_graph` from `episodic/orchestration/__init__.py`
   if that matches the existing export style, and add a Skylos entry-point rule
   naming `episodic.api.runtime` as the caller if Skylos flags them.

### EP-M4: launcher executes runs through the graph

Red tests:

- `tests/test_generation_run_launcher_quality_modes.py` (INV-9 and INV-10).
- The existing launcher tests are adapted only by constructing the launcher
  with the graph (test support change). Their assertions stay unchanged (INV-8).

Production changes:

1. New `episodic/generation/launcher_session.py` (`application`):
   - `_LauncherRunSession`, a slotted dataclass holding the launcher host,
     the claimed `GenerationRun`, and mutable `claimed: ClaimedRun | None`
     and `draft: DraftScriptResult | None` fields. It implements
     `ContentGenerationSteps` structurally.
   - `initialize()` performs today's hydration: episode, source documents,
     presenter bindings and `_load_sources`. Split it out of `_claim` into
     `_hydrate(run)` in `launcher_claim.py`.
   - `generate_draft()` calls `_generate` and `_record_draft_generated`.
   - `begin_evaluation()` appends `qa.evaluation_started` and updates
     `current_node="evaluate"` in one unit of work, then returns
     `EvaluationSubject`.
   - `record_quality_result()` appends `qa.result`.
   - `complete_with_draft(qa_status)` calls `_persist_success(claimed,
     draft, qa_status=…)`.
   - `escalate(verdict)` calls a new `_record_escalation` in a new
     `episodic/generation/launcher_quality.py` mixin, which appends
     `qa.escalated` and `run.failed` and applies the FAILED update with
     `qa_status=FAILED` in one unit of work.
2. `episodic/generation/launcher_claim.py`:
   - `_claim` becomes `_claim_and_start` plus `_hydrate`.
   - The QA-bypass metric is incremented only when
     `run.quality_mode is QualityMode.DRAFT_WITHOUT_QA`.
   - Add `_METRIC_QA_GATE = "generation_run_qa_gate_total"`, labelled with
     `verdict`, recorded by `record_quality_result`.
3. `episodic/generation/launcher_scheduling.py` `_execute_run`: claim, then
   `terminal = await self.content_graph.run(ContentGenerationRequest(…),
   steps=_LauncherRunSession(…))`,
   log the branch, set the span attribute `quality_branch`, and return
   `_ExecutionOutcome(outcome=terminal.value)`. The broad `except Exception`
   boundary and the cancellation handling are unchanged.
4. `episodic/generation/launcher_persistence.py`: `_persist_success` and
   `_record_success_transition` take `qa_status` and put it in the
   `tei.persisted` payload. For no-QA runs this is still `"skipped"`.
5. `episodic/generation/launcher.py` and `launcher_host.py`: add the required
   field `content_graph: ContentGenerationGraphPort` and the new mixin. Update
   the protocol surface. Update `tests/generation_run_launcher_support.py`
   (`launcher(...)`), `tests/test_generation_source_limits.py` and
   `tests/steps/no_qa_generation_slice_support.py` to pass
   `LangGraphContentGenerationGraph(QualityEvaluatorSet(()))`.

### EP-M5: REST and composition-root acceptance of `qa_gated`

Red tests:

- `tests/test_generation_run_api_quality_modes.py` and its snapshots
  (INV-12).
- `tests/features/qa_gated_generation_routing.feature` with
  `tests/steps/test_qa_gated_generation_routing.py`.
- Move the existing "unsupported quality mode" BDD scenario and its
  `test_generation_run_api.py` assertion into the new suite unchanged in
  behaviour: they still expect 422 because their dependencies do not accept
  `qa_gated`.

Production changes:

1. `episodic/api/dependencies.py`: add
   `accepted_quality_modes: frozenset[QualityMode] = frozenset({QualityMode.DRAFT_WITHOUT_QA})`.
   Validate that it is non-empty and contains `DRAFT_WITHOUT_QA`.
2. `episodic/api/resources/generation_runs_create_support.py`:
   - `_parse_create_request(payload, *, accepted_modes)` parses the enum
     first.
   - If the mode is not in `accepted_modes`, it raises the existing 422
     envelope.
   - For `draft_without_qa` it requires `skip_qa_rationale` as today.
   - For `qa_gated` it rejects a present `skip_qa_rationale` with
     `validation_error(…, field="skip_qa_rationale",
     constraint="forbidden")`.
   - It returns the parsed `quality_mode` in `_CreateGenerationRun`.

   The idempotency body hash still covers the whole payload, so replaying a key
   across modes conflicts with 409.
3. `episodic/api/resources/generation_runs.py` `_create_run`: build
   `GenerationRun` with the parsed mode, setting `qa_status=SKIPPED`/rationale
   for no-QA and `qa_status=PENDING`/`None` for gated.
4. `episodic/api/runtime.py`: build one
   `QualityEvaluatorSet(())`. (It is empty in 4.4.1, and 4.4.2 appends Chrono.)
   Construct `LangGraphContentGenerationGraph(evaluator_set)`, pass it to the
   launcher, and set
   `accepted_quality_modes=evaluator_set.accepted_quality_modes()`. Add a
   runtime test asserting that both are derived from the same set.

### EP-M6: documentation, ADR acceptance and roadmap

1. ADR 024: set the status to `Accepted (2026-MM-DD)` with a summary,
   reconcile it with what was built, and link it from the design document's
   "Content Generation Graph" and "Source-to-script vertical slice" sections.
2. `docs/episodic-podcast-generation-system-design.md`: update the graph
   prose and the Mermaid diagram to split the persist nodes, state the 4.4.1
   escalate semantics, and replace "Generation creation accepts only
   `draft_without_qa`" with the capability-gated rule. Keep the accessible "For
   screen readers" description in step with the diagram.
3. `docs/episodic-tui-api-design.md`: document the `qa_gated` request rules,
   the `qa_status` values, the new event kinds (`qa.evaluation_started`,
   `qa.result` and `qa.escalated`) and the error codes.
4. `docs/users-guide.md`: add a "QA-gated generation runs" subsection after
   the no-QA run instructions. Cover:
   - when `qa_gated` is accepted;
   - that `skip_qa_rationale` is forbidden;
   - how to read `qa_status`;
   - what `qa.escalation_required` means;
   - that the TEI envelope reports `quality_mode`.
5. `docs/developers-guide.md`: add a "Content-generation graph and quality
   branch" section covering:
   - the ports and the injection path;
   - the node ownership table;
   - how to add an evaluator (4.4.2 onwards);
   - the rule that nodes never open units of work;
   - the Hypothesis conventions used (`event()` classification, independent
     oracles and seeded-fault controls).

   Update "No-QA launcher and TEI retrieval" for the session and graph.
6. ADR 017: add a short "Superseded in part by ADR 024" note on the 422
   rule.
7. `docs/contents.md`: index ADR 024 if ADRs are indexed there.
8. `docs/roadmap.md`: mark 4.4.1 as `[x]` with a one-line summary of what
   shipped.
9. Run `make fmt`, `make markdownlint` and `make nixie`, then the full gates.

## Milestones and plateaus

- EP-M1
  - Outcome: domain types can represent and validate `qa_gated` runs, and
    the pure routing and aggregation policy exists. No runtime path uses it
    yet, and the REST layer still returns 422.
  - Requirements: RM-441-A (domain), RM-441-D (policy).
  - Acceptance: INV-1, INV-3, INV-4 and INV-13 pass, and the existing
    domain tests pass.
  - Conformance check:
    - RM-441-A is satisfied at the domain layer.
    - The design is followed (D5, D8).
    - No upstream assumption is falsified.
    - No public interface change.
    - No persistence change.
    - Trace links are current.
  - Recovery: revert the milestone commits. Nothing depends on them yet.
  - Remaining gaps: persistence, graph, launcher, REST and documentation.
  - Compatibility decision: none.
- EP-M2
  - Outcome: the database and adapters store the new labels and enforce
    INV-2, persistence writes the supplied QA status, and the envelope
    derives the mode.
  - Requirements: RM-441-A (persistence).
  - Acceptance: INV-2, INV-11 and INV-13 pass, `make check-migrations`
    passes, and all no-QA tests pass unchanged.
  - Conformance check:
    - The additive migration is the only persisted-format change, and it is
      approved by this plan.
    - No other interface change.
  - Recovery: `alembic downgrade 20261010_000013` on a database without
    `qa_gated` rows, then revert.
  - Remaining gaps: the graph, the launcher and REST.
  - Compatibility decision: deployed PostgreSQL databases at revision
    `20261010_000013` must upgrade in place. That is why the migration is
    additive.
- EP-M3
  - Outcome: a compiled content-generation graph exists, with property-tested
    branch ownership, but no production caller yet.
  - Requirements: RM-441-B, RM-441-C and RM-441-D at the graph level.
  - Acceptance: INV-5, INV-6 and INV-7 pass, and Hecate passes with the new
    prefixes.
  - Conformance check:
    - ADR 022 groups are respected.
    - No allowed-list changes.
    - SD-CGG is followed apart from the recorded D3 and D4 deviations.
  - Recovery: revert. Nothing depends on the graph yet.
  - Remaining gaps: launcher integration.
  - Compatibility decision: none.
- EP-M4
  - Outcome: all runs execute through the graph, the no-QA behaviour is
    byte-identical, and `qa_gated` runs (constructed directly in tests) reach
    the passed or escalated terminals with correct events.
  - Requirements: RM-441-B, RM-441-C and RM-44-CONC.
  - Acceptance: INV-8, INV-9 and INV-10 pass. No no-QA snapshot changed
    (`git diff --stat tests/__snapshots__`).
  - Conformance check:
    - Single writer preserved.
    - The `launch` signature is unchanged.
    - The `content_graph` field is a new required launcher field, which is
      an application-internal API, so no compatibility layer is needed.
  - Recovery: revert the EP-M4 commits. EP-M1 to EP-M3 remain coherent.
  - Remaining gaps: REST acceptance and documentation.
  - Compatibility decision: none. Every constructor caller (the runtime and
    three test helpers) is updated in the same commit.
- EP-M5
  - Outcome: clients can create `qa_gated` runs where evaluators are
    configured, and production keeps returning 422.
  - Requirements: RM-441-A (creation) and RM-441-S.
  - Acceptance: INV-12 and the new BDD feature pass, and the existing
    no-QA feature passes unchanged.
  - Conformance check:
    - The REST shape is unchanged.
    - New error detail values are documented.
    - The 422 behaviour is preserved for production.
  - Recovery: revert the EP-M5 commits. EP-M4 still runs no-QA runs through
    the graph.
  - Remaining gaps: documentation.
  - Compatibility decision: existing clients that send `draft_without_qa`
    are unaffected.
- EP-M6
  - Outcome: the documentation matches the behaviour, ADR 024 is accepted,
    and the roadmap is marked done.
  - Acceptance: `make markdownlint` and `make nixie` pass, and the full gates
    pass.
  - Conformance check: every deviation is reconciled upstream.
  - Recovery: documentation-only commits are trivially revertible.
  - Compatibility decision: none.

## Concrete steps

Run all commands from the repository root (the worktree). Capture gate output
with `tee`, using `/tmp/$ACTION-episodic-4-4-1-qa-gated-mode-branching.out`.
Run gates sequentially, never in parallel. Prefer delegating full gate runs to
the `scrutineer` agent.

At each milestone:

```shell
make fmt
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-4-4-1-qa-gated-mode-branching.out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-4-4-1-qa-gated-mode-branching.out
make lint 2>&1 | tee /tmp/lint-episodic-4-4-1-qa-gated-mode-branching.out
make test 2>&1 | tee /tmp/test-episodic-4-4-1-qa-gated-mode-branching.out
```

For focused red and green loops:

```shell
uv run pytest tests/test_generation_quality_policy_properties.py -q
uv run pytest tests/test_content_generation_graph_properties.py -q --hypothesis-show-statistics
uv run pytest tests/test_qa_gated_quality_mode_migration.py -q
uv run pytest tests/steps/test_qa_gated_generation_routing.py -q
```

Expected red output at the start of EP-M1, before production changes:

```plaintext
tests/test_generation_quality_policy_properties.py::test_quality_metadata_matches_policy XFAIL (4.4.1 red: qa_gated unsupported)
```

The expected statistics fragment for INV-5 lists every class:

```plaintext
  - Events:
    * ..%, branch=draft_without_qa terminal=draft_persisted_without_qa
    * ..%, branch=qa_gated terminal=qa_passed_draft_persisted
    * ..%, branch=qa_gated terminal=qa_escalated reason=failed
    * ..%, branch=qa_gated terminal=qa_escalated reason=inconclusive
    * ..%, fault=<node>
```

For documentation milestones:

```shell
make fmt
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-4-4-1-qa-gated-mode-branching.out
make nixie 2>&1 | tee /tmp/nixie-episodic-4-4-1-qa-gated-mode-branching.out
```

Also run `make check-migrations` after EP-M2. Commit after each green step,
gating each commit.

## Validation and acceptance

BDD feature specification for EP-M5, in
`tests/features/qa_gated_generation_routing.feature`:

```gherkin
Feature: QA-gated generation routing

  As an integration client
  I want QA-gated runs to pass through evaluation before any draft is saved
  So that only QA-passed scripts are persisted while no-QA drafts keep their direct route

  Background:
    Given a Vidai Mock inference server is running
    And a series profile exists
    And a host presenter profile and a guest presenter profile are bound

  Scenario: A QA-gated run whose evaluators pass persists a QA-passed draft
    Given QA evaluation is configured with a passing evaluator
    And an ingestion job with an attached source document
    When I create a qa-gated generation run for the ingested episode
    Then the run creation responds 202 Accepted with a Location header
    And the run is created with qa_status "pending" and no skip rationale
    When I poll the generation run until it reaches a terminal state
    Then the run status is "succeeded" with qa_status "passed"
    And the event log records "qa.evaluation_started", "qa.result" and "tei.persisted" in order
    When I fetch the episode TEI as JSON
    Then the envelope reports quality_mode "qa_gated" and qa_status "passed"

  Scenario: A QA-gated run whose evaluators fail escalates without persisting a draft
    Given QA evaluation is configured with a failing evaluator
    And an ingestion job with an attached source document
    When I create a qa-gated generation run for the ingested episode
    And I poll the generation run until it reaches a terminal state
    Then the run status is "failed" with qa_status "failed"
    And the run records the error category "qa.escalation_required"
    And the event log contains a "qa.escalated" event and no "tei.persisted" event
    And the episode TEI is not found

  Scenario: A QA-gated run with a skip rationale is rejected
    Given QA evaluation is configured with a passing evaluator
    And an ingestion job with an attached source document
    When I create a qa-gated generation run with a skip_qa_rationale
    Then the response is 400 Bad Request with constraint "forbidden"

  Scenario: QA-gated runs are unprocessable when no evaluators are configured
    Given no QA evaluators are configured
    And an ingestion job with an attached source document
    When I create a generation run with quality_mode "qa_gated"
    Then the response is 422 Unprocessable Entity

  Scenario: A draft-without-QA run still takes the direct route when evaluators exist
    Given QA evaluation is configured with a failing evaluator
    And an ingestion job with an attached source document
    When I create a draft-without-qa generation run for the ingested episode
    And I poll the generation run until it reaches a terminal state
    Then the run status is "succeeded" with qa_status "skipped"
    And the event log contains no "qa.evaluation_started" event
```

Vidai Mock serves the draft completion for every scenario, so the generator
path is real end to end. The evaluator is a deterministic in-process test
double bound through `ApiDependencies`/launcher construction. No inference is
involved in evaluation until 4.4.2.

Quality criteria:

- Tests: `make test` passes. Each new test listed under the milestones fails
  before its green step, for the intended reason, and passes afterwards. All
  4.3.2 tests and snapshots pass without regeneration.
- Verification: INV-1 to INV-13 are discharged as described, with their
  non-vacuity evidence recorded in `Artefacts and notes`.
- Lint and typecheck: `make check-fmt`, `make typecheck` and `make lint`
  pass. The lint run covers Hecate, Ruff, Pylint, df12, ambrleaks, Skylos and
  nose.
- Documentation: `make markdownlint` and `make nixie` pass.
- Migrations: `make check-migrations` passes.

## Idempotence and recovery

Every step can be re-run. The migration uses `ADD VALUE IF NOT EXISTS`, so
re-running the upgrade is harmless. Downgrade refuses when data would be lost.
The gates are read-only apart from `make fmt`. If a milestone fails halfway,
reset to the last green commit with `git reset --hard <sha>` after confirming
that `git status` holds no wanted changes, or fix forward within the
milestone's iteration tolerance. Never regenerate a no-QA snapshot to recover.

## Artefacts and notes

Record red and green transcripts, Hypothesis statistics excerpts, and
seeded-fault outcomes here as each milestone completes.

## Interfaces and dependencies

At the end of EP-M5, the following must exist. The signatures are prescriptive
and the docstrings are NumPy-style.

In `episodic/canonical/generation_quality.py`:

```python
class QualityMode(enum.StrEnum):
    DRAFT_WITHOUT_QA = "draft_without_qa"
    QA_GATED = "qa_gated"


class QaStatus(enum.StrEnum):
    SKIPPED = "skipped"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


def quality_metadata_violation(
    *,
    quality_mode: QualityMode,
    status: GenerationRunStatus,
    qa_status: QaStatus | None,
    skip_qa_rationale: str | None,
) -> str | None: ...


def quality_mode_for_persisted_qa_status(qa_status: QaStatus) -> QualityMode: ...
```

In `episodic/canonical/generation_routing.py`:

```python
class QualityBranch(enum.StrEnum):
    DRAFT_WITHOUT_QA = "draft_without_qa"
    QA_GATED = "qa_gated"


class QualityVerdict(enum.StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class GenerationTerminal(enum.StrEnum):
    DRAFT_PERSISTED_WITHOUT_QA = "draft_persisted_without_qa"
    QA_PASSED_DRAFT_PERSISTED = "qa_passed_draft_persisted"
    QA_ESCALATED = "qa_escalated"


def route_quality_mode(mode: QualityMode) -> QualityBranch: ...
def branch_for_terminal(terminal: GenerationTerminal) -> QualityBranch: ...
def aggregate_verdicts(verdicts: cabc.Iterable[QualityVerdict]) -> QualityVerdict: ...
def route_after_evaluation(verdict: QualityVerdict) -> GenerationTerminal: ...


@dc.dataclass(frozen=True, slots=True)
class TerminalOutcome:
    status: GenerationRunStatus
    qa_status: QaStatus
    error_category: str | None
    error_message: str | None


def terminal_outcome(
    terminal: GenerationTerminal, *, verdict: QualityVerdict | None
) -> TerminalOutcome: ...
```

In `episodic/canonical/generation_graph_ports.py`:

```python
@dc.dataclass(frozen=True, slots=True)
class EvaluationSubject:
    run_id: uuid.UUID
    episode_id: uuid.UUID
    tei_xml: str
    content_hash: str


class QualityEvaluatorPort(typ.Protocol):
    @property
    def name(self) -> str: ...
    async def evaluate(self, subject: EvaluationSubject) -> QualityVerdict: ...


@dc.dataclass(frozen=True, slots=True)
class QualityEvaluatorSet:
    evaluators: tuple[QualityEvaluatorPort, ...]

    def accepted_quality_modes(self) -> frozenset[QualityMode]: ...


@dc.dataclass(frozen=True, slots=True)
class ContentGenerationRequest:
    run_id: uuid.UUID
    quality_mode: QualityMode


class ContentGenerationSteps(typ.Protocol):
    async def initialize(self) -> None: ...
    async def generate_draft(self) -> None: ...
    async def begin_evaluation(
        self, evaluator_names: tuple[str, ...]
    ) -> EvaluationSubject: ...
    async def record_quality_result(
        self, verdict: QualityVerdict, evaluator_count: int
    ) -> None: ...
    async def complete_with_draft(self, qa_status: QaStatus) -> None: ...
    async def escalate(self, verdict: QualityVerdict) -> None: ...


class ContentGenerationGraphPort(typ.Protocol):
    async def run(
        self,
        request: ContentGenerationRequest,
        *,
        steps: ContentGenerationSteps,
    ) -> GenerationTerminal: ...
```

In `episodic/orchestration/content_generation.py`:

```python
def build_content_generation_graph(
    *, path_maps: _PathMaps | None = None
) -> CompiledStateGraph[ContentGenerationGraphState, ContentGenerationContext, ...]: ...


@dc.dataclass(slots=True)
class LangGraphContentGenerationGraph:
    evaluator_set: QualityEvaluatorSet

    async def run(
        self,
        request: ContentGenerationRequest,
        *,
        steps: ContentGenerationSteps,
    ) -> GenerationTerminal: ...
```

In `episodic/generation/launcher.py`, `InProcessGenerationRunLauncher` gains
the required field `content_graph: ContentGenerationGraphPort`.

In `episodic/api/dependencies.py`, `ApiDependencies` gains
`accepted_quality_modes: frozenset[QualityMode]`.

Dependencies: no new packages. Use `langgraph.graph.StateGraph`, `START`, `END`
and `langgraph.runtime.Runtime`. `Runtime` and `context_schema` are new to this
repository, but they ship with the pinned LangGraph 1.2.11 and the planning
probe confirmed them (see `Surprises & discoveries`). Also use Hypothesis 6.x,
pytest-bdd, syrupy and py-pglite.

## Revision note

- 2026-10-17: initial draft written from Wyvern reconnaissance and
  primary-source reading. It awaits expert-panel review.
