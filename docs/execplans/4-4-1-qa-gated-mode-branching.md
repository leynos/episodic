# Add QA-gated mode branching and content-generation graph routing (4.4.1)

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & discoveries`, `Decision log`,
`Outcomes & retrospective`, `Conformance basis`, and `Verification plan` must
be kept up to date as work proceeds.

Status: COMPLETE

## Purpose / big picture

Today a generation run can only be created with
`quality_mode=draft_without_qa`. The in-process launcher claims the run,
generates one draft, persists the TEI-P5 script with `qa_status=skipped`, and
marks the run `succeeded`. A request for `quality_mode=qa_gated` is refused with
`422 Unprocessable Entity`. There is also no graph that could route such a run
anywhere.

After this change, every generation run executes through a small LangGraph
`StateGraph`. This is the first slice of the *Content Generation Graph*
described in `docs/episodic-podcast-generation-system-design.md`. Straight
after its `initialize` node, a conditional edge called the *quality branch*
sends the run down exactly one of two branches:

- **`draft_without_qa`.** The run generates a draft and goes directly to draft
  persistence, exactly as it does today. Its event stream, metrics, span
  attributes and terminal state are unchanged.
- **`qa_gated`.** The run generates a *candidate* draft and enters an
  evaluation branch. That branch runs the configured QA evaluators, each with a
  timeout, and aggregates their verdicts.
  - If the verdict is a pass, the run persists its draft with
    `qa_status=passed` and succeeds.
  - Any other verdict ends the run at an *escalate* terminal. The TEI is not
    written, but the inference cost is still recorded. The run fails with the
    stable category `qa.escalation_required`.

Each branch owns its own nodes and terminals; the only shared node is
`initialize`. Hypothesis property tests over generated run states prove this,
and a static topology check confirms it.

In deployments that have QA evaluators configured, a user can see this over
REST:

1. Creating a `qa_gated` run returns `202 Accepted` with
   `qa_status: "pending"`.
2. Polling then shows one of two outcomes:
   - `succeeded` with `qa_status: "passed"`, and a downloadable TEI whose
     envelope reports `quality_mode: "qa_gated"`; or
   - `failed` with `error_category: "qa.escalation_required"`,
     `qa_status: "failed"`, and a `qa.escalated` event.

Deployments without evaluators keep returning the existing
`422 quality_mode_unsupported` for `qa_gated`. Production is one of these until
roadmap item 4.4.2 binds Chrono. This means a QA-gated request can never spend
inference budget on a branch that cannot pass.

## Constraints

- **Preserve the `draft_without_qa` contract exactly.** None of the following
  may change for no-QA runs:
  - REST request and response shapes, and error envelopes. This includes the
    existing `422` for an unaccepted `qa_gated`.
  - Event kinds, their order, and their payloads.
  - `current_node` values.
  - Metric names, labels, and emission points.
  - The trace-span `outcome` attribute: `"completed"`, `"failed"`, or
    `"not_claimed"`.
  - Persisted TEI provenance.
  - The behaviour when the generator itself raises `asyncio.CancelledError`,
    which today is recorded as `launcher.shutdown`.

  A characterization test captures all of these on the current code before any
  refactor (EP-M0). It must pass unmodified at every later milestone.
  `tests/features/no_qa_generation_slice.feature` must not be edited.
- **Keep a single writer per run.** The launcher task that claimed a run is
  the only code that appends that run's events or changes its status.
  - Graph nodes reach run state only through the step port that the launcher
    supplies for that run.
  - Graph nodes never open a unit of work.
  - No unit of work is held open across an evaluator `await`.
- **Keep event publication ordered.** Every event for a run is appended from a
  task named `generation-run-{run_id}`, in graph order. D16 records that
  LangChain wraps each node in a child task owned and named by the invocation,
  so "named for the run" is the contract rather than "the one launcher task".
  In this item:
  - No graph branch may run in parallel.
  - The graph must not use `step_timeout`, subgraphs, `stream_eager`, or the
    `messages` or `custom` stream modes. Each of these moves node execution
    off the caller's task (see AXM-1).
- **Keep cancellation shutdown-safe.** A run may be cancelled at any node,
  including while an evaluator is awaiting or while a terminal unit of work is
  in progress. In every case:
  - The existing `launcher.shutdown` failure is recorded at most once.
  - No TEI is persisted that was not already committed.
  - A `qa_gated` run's `qa_status` stays at `pending`, unless a terminal had
    already committed.
  - The same rule covers every failure before a QA decision: a generator
    error, an evaluator set that is unavailable at execution time, and a
    shutdown cancellation all end `failed` with `qa_status` still `pending`.
    `qa_status=failed` is recorded only when evaluation completed and did not
    pass.
- **Respect the hexagonal boundaries enforced by Hecate.** These are
  configured under `[tool.hecate]` in `pyproject.toml` and described in ADR
  0014 and ADR 0022.
  - Domain policy and port protocols live in `domain_ports`.
  - Graph node functions and graph state live in `orchestration_nodes`. They
    must not import `langgraph`, because ADR 0022 says to "keep LangGraph
    framework mechanics out of node functions". Hecate does not check
    third-party imports, so code review must enforce this.
  - The graph builder and the graph runner live in `orchestration`.
  - The launcher stays in `application` (`episodic.generation`) and must not
    import `episodic.orchestration`. The composition root injects the graph.
- **Do not weaken any Hecate rule.** Only add prefixes to existing groups.
  Never reorder groups, and never broaden an `allowed` list.
- **Fail closed.** None of the following may ever produce `qa_status=passed`,
  a persisted TEI, or a `succeeded` run:
  - an empty evaluator set;
  - an evaluator error;
  - an evaluator timeout;
  - an evaluator that raises `CancelledError` itself;
  - an `inconclusive` verdict.
- **Never persist TEI for a `qa_gated` run before its aggregate verdict is a
  pass.** `EpisodeTeiUpdate` must refuse the `pending` and `failed` QA statuses.
- **Make database changes additive only.** Add enum labels with
  `ALTER TYPE ... ADD VALUE IF NOT EXISTS`. Do not rename or reorder labels.
  D23 records the one accepted exception: a nullable
  `generation_runs.claim_token` column in revision `20261123_000019`, needed so
  a lost commit acknowledgement is reconciled against a unique proof rather
  than a shared timestamp.
- **Add no new third-party dependency.** LangGraph (`>=1.2.11`), Hypothesis,
  pytest, pytest-bdd, syrupy, py-pglite and Vidai Mock are already available.
- **Keep every code file under 400 lines** (`AGENTS.md`). The launcher's
  components are 100–250 lines and the run-store adapters are about 358 and 390
  lines. New behaviour therefore goes into new cohesive modules or shared
  domain helpers, not into those files.
- **Write en-GB Oxford spelling** (`-ize`, `-yse`, `-our`) in comments and
  documentation, and follow `docs/documentation-style-guide.md`.

## Tolerances (exception triggers)

- **Scope.** Stop and escalate if implementation needs more than 65 changed
  files or more than 3,500 net added lines, excluding snapshots and this plan.
  The work may be split into two stacked pull requests if review load requires
  it: EP-M0 to EP-M3, then EP-M4 to EP-M6.
- **Interface.** Stop and escalate if any of these must change:
  - the `GenerationRunLauncher.launch(run_id)` signature;
  - an existing public REST field, by removal or renaming.
- **No-QA contract.** Stop and escalate if any of these must change to make
  the work pass:
  - the EP-M0 characterization snapshots;
  - any existing no-QA test assertion;
  - `tests/features/no_qa_generation_slice.feature`.
- **Architecture.** Stop and escalate if a Hecate `allowed` list must be
  broadened or a group reordered, or if a node function needs to import an
  application module or `langgraph`.
- **Dependencies.** Stop and escalate if a new package or a version bump is
  required.
- **Persistence.** Stop and escalate if py-pglite or PostgreSQL rejects
  `ALTER TYPE ... ADD VALUE` inside the Alembic transaction. There is
  deliberately no `autocommit_block()` fallback, because migrations in this
  repository must not own the transaction.
- **Semantics.** Stop and escalate if any stakeholder requires the escalate
  terminal to pause the run (`paused` plus a checkpoint) in this item rather
  than in 4.4.4.
- **Iterations.** Stop and escalate if a milestone's gates still fail after
  three focused fix attempts.
- **Ambiguity.** Stop and present options if a design question arises that
  this plan does not settle and the choice changes observable behaviour.

## Risks

- **Risk: LangGraph's execution model shifts under the launcher.** It might
  stop running nodes inline. It also converts a node's self-raised
  `CancelledError` into `NodeCancelledError`, which is a plain `Exception`
  (`.venv/.../langgraph/pregel/_retry.py:777-792`).
  - Severity: high. Likelihood: medium.
  - Mitigation:
    - The runner translates `NodeCancelledError` back into
      `asyncio.CancelledError` (`raise asyncio.CancelledError from exc`).
      This preserves today's `launcher.shutdown` classification for a
      generator that raises `CancelledError` itself.
    - A characterization case pins that behaviour.
    - INV-9 asserts that every event is appended from the
      `generation-run-{id}` task, so a LangGraph upgrade that moves nodes off
      that task fails loudly.
- **Risk: a hung evaluator holds a launcher concurrency permit and starves
  no-QA runs.**
  - Severity: high. Likelihood: medium.
  - Mitigation:
    - Each evaluator runs under `asyncio.timeout(evaluator_timeout_seconds)`,
      which defaults to 120 seconds on `QualityEvaluatorSet`. A timeout maps
      to `inconclusive` with `errored: true`.
    - The evaluator-error counter and the `qa.result` payload make the cause
      visible.
    - Lease renewal is listed under `Residual gaps`.
- **Risk: an evaluator adapter regression turns every gated run into an
  escalation.** This would look like "QA rejecting drafts" rather than a bug.
  - Severity: medium. Likelihood: medium.
  - Mitigation:
    - `qa.result` records `errored` and `error_type` for each evaluator.
    - `generation_run_qa_evaluator_errors_total{evaluator}` counts the
      errors.
    - Exceptions are logged through `log_exception` with `run_id` and the
      evaluator name.
    - The developers' guide says to alert on the evaluator-error rate, not on
      the escalation rate.
- **Risk: the escalate terminal fails runs in 4.4.1, but 4.4.4 will pause
  them instead.** In 4.4.4 the same outcome becomes a `paused` run with a
  persisted escalation checkpoint. Paused runs carry no `error_category`, and
  clients that "poll until terminal" would wait on them.
  - Severity: medium. Likelihood: high.
  - Mitigation:
    - The project is pre-1.0.
    - ADR 0029 and the users' guide state that the `qa.escalated` event is the
      stable signal, and that `qa.escalation_required` is specific to 4.4.1.
    - They also state that `paused` is a reachable status meaning "action
      needed".
- **Risk: enum label drift goes undetected.** Alembic `compare_metadata`
  (used by `make check-migrations`) ignores enum labels.
  - Severity: medium. Likelihood: high.
  - Mitigation: INV-11 compares the `pg_enum` labels with the Python enum
    values after the upgrade.
- **Risk: the tests hide the `ADD VALUE` transaction restriction.** A label
  added with `ADD VALUE` cannot be used inside the same transaction. The
  fresh-schema fixture runs every migration in one transaction
  (`episodic/canonical/storage/alembic_helpers.py:113`), and there the type is
  created in that same transaction, so the restriction never bites.
  - Severity: medium. Likelihood: medium.
  - Mitigation: INV-11 downgrades to `20261110_000017` and commits, then
    upgrades to head and commits, and only then inserts a `qa_gated` row.
- **Risk: rolling back to 4.3.2 code fails on rows with a new label,** because
  its enum lookup raises.
  - Severity: medium. Likelihood: low.
  - Mitigation: production still returns 422 in 4.4.1, so no such rows are
    written there. The plan states that a code rollback is safe only while no
    `qa_gated` rows exist.
- **Risk: the nose duplication gate or the Skylos dead-code gate flags the
  new code.**
  - Severity: low. Likelihood: medium.
  - Mitigation:
    - Escalation reuses `_record_failure` rather than adding a parallel write
      path.
    - The two generate nodes delegate to one step method, and so do the two
      persist nodes.
    - Every new domain symbol has a production caller: the builder registers
      nodes from the ownership table, the runner checks
      `branch_for_terminal`, and the session uses `terminal_outcome`.
- **Risk: Hypothesis tests that drive a compiled LangGraph are slow on a
  contended host.**
  - Severity: low. Likelihood: medium.
  - Mitigation: compile the graph once per module, use `max_examples=100`
    with `deadline=None`, and use in-memory fakes only, so each example costs
    milliseconds.
- **Risk: the `draw_mermaid()` topology snapshot churns when LangGraph is
  upgraded.**
  - Severity: low. Likelihood: medium.
  - Mitigation: the structural INV-7 assertions are authoritative, and the
    snapshot is only a review aid. It may be regenerated after a LangGraph
    bump once INV-7 passes.

## Progress

- [x] (2026-10-17) Renamed the branch to `4-4-1-qa-gated-mode-branching`.
- [x] (2026-10-17) Completed Wyvern reconnaissance of run creation,
  orchestration and documentation.
- [x] (2026-10-17) Drafted the ExecPlan (commit `5814b812`).
- [x] (2026-10-17) Ran LangGraph probes covering runtime context, `path_map`
  topology, and exception and cancellation propagation.
- [x] (2026-10-17) Held the expert-panel design review (Pandalump, Wafflecat,
  Telefono, Buzzy Bee, Doggylump, Dinolump). The verdict was "proceed with
  conditions", and every condition is folded into this revision.
- [x] (2026-11-22) Plan approved by the user, with every expert-panel
  recommendation (D1 to D13) accepted as written.
- [x] (2026-11-22) EP-M0: no-QA characterization baseline. All seven cases are
  green on the unmodified launcher code; see `Artefacts and notes`.
- [x] (2026-11-22) EP-M1: domain quality policy and validation. The pure
  routing policy and graph ports moved to EP-M3 under D14, because the blocking
  Skylos dead-code gate runs on every commit and those symbols have no
  production caller until the graph exists.
- [x] (2026-11-22) EP-M2: persistence, migration and lifecycle updates.
- [x] (2026-11-22) EP-M3: content-generation graph in orchestration.
- [x] (2026-11-22) EP-M4: launcher executes runs through the graph.
- [x] (2026-11-22) EP-M5: REST and composition-root acceptance of `qa_gated`.
- [x] (2026-11-22) EP-M6: documentation, ADR acceptance, roadmap update and
  final gates.
- [x] (2026-11-22) Rebases onto `main @ d0bdabe3` and the CodeRabbit
  completeness assessment; see D17 and D18.
- [x] (2026-11-23) Merged `main` at #438 and ported the QA-gated feature onto
  the injected launcher components; see D19 to D23 and the integration record.
- [x] (2026-11-24) Eighth round: the two CodeRabbit pre-merge rows accepted
  and implemented — a store-level claim-token gate on every terminal write, a
  private reconciliation deadline, an injectable source loader, narrow
  per-stage runtime protocols, an explicit claim-token return, and a split
  failure command.
- [x] (2026-11-26) Ninth round: the 2026-11-26 CodeRabbit findings. The
  keyed-conflict precondition now reuses the submission's prepared validation
  (`GenerationRunsResource._submit` memoizes it); the recording-unit-of-work
  test gained a delegated-write negative control and a session `before_flush`
  listener, each proven to fail when removed; and the plan's gate blocks state
  `set -o pipefail` for both the correctness and documentation milestones.
- [x] (2026-11-24) Seventh round, from CodeRabbit's pre-merge rows at
  `788119cf`..`bfd4aa78`: bounded shutdown (D24) with a normal-drain contract,
  in-transaction failure reconciliation and post-write QA metrics (D25), the
  foreign-run token guard, `claim_token_for` and `read_owned_episode_and_run`
  direct tests, and the honest scope of the claim token. CodeRabbit reports no
  new functional defect at `bfd4aa78`; the remaining blockers are the
  stakeholder decisions listed under Residual gaps.
- [x] (2026-11-24) Sixth round: the bounded cancellation write (D24), the
  claim-proof-preserving test helper, identifier escaping in the PostgreSQL
  DDL, and the D7/D20 and INV-8/D15 record reconciliations.
- [x] (2026-11-23) Fifth assessment round: Alembic's own offline downgrade is
  snapshotted (INV-11), the precedence envelopes are snapshotted including the
  accepted-gated rationale and unknown-mode cases (INV-12), the INV-1 seeded
  mutation is measured, and the two-connection claim race runs as a DSN-gated
  test against real PostgreSQL (measured for commit-loses and rollback-wins)
  alongside the launcher-level fault tests and the claim-task cancellation
  interleaving.

## Surprises & discoveries

- **Observation: the 4.3.2 no-QA run does not use LangGraph at all.**
  - Evidence: `_execute_run` in `episodic/generation/launcher_scheduling.py`
    calls `_claim`, `_generate`, `_record_draft_generated` and
    `_persist_success` directly. The only `StateGraph`s are planning
    (`episodic/orchestration/_graph_builder.py`), Pedante
    (`episodic/qa/langgraph.py`) and Chrono
    (`episodic/qa/chrono_langgraph.py`).
  - Impact: "graph route plumbing" means introducing the content-generation
    graph and moving the launcher's post-claim sequence into it.
- **Observation: `qa_gated` cannot be represented anywhere below the HTTP
  parser.**
  - Evidence:
    - `QualityMode` has only `DRAFT_WITHOUT_QA`, and `QaStatus` has only
      `SKIPPED` (`episodic/canonical/generation_quality.py`).
    - `_validate_draft_without_qa_metadata` rejects every other mode
      (`episodic/canonical/domain_validation.py:47`).
    - The PostgreSQL enums carry one label each
      (`alembic/versions/20260624_000010_add_generation_run_tables.py:30`).
  - Impact: domain, migration and adapter changes are prerequisites. The ORM
    needs no edit, because `values_callable` in
    `episodic/canonical/storage/models_base.py:82-91` follows the Python
    enums.
- **Observation: the TEI envelope hard-codes `quality_mode`,** at
  `episodic/api/serializers.py:280.` However, `EpisodeTeiResource` already
  loads the producing run (`episode_tei.py:87-93`), and it serves TEI only when
  `qa_status` is set (`episode_tei.py:158-163`).
  - Impact: D6 uses `run.quality_mode`.
- **Observation: `generation_run_qa_bypass_total` is incremented for every
  run that has been claimed and hydrated, whatever its mode.** It fires only
  after source loading succeeds (`episodic/generation/launcher_claim.py:61-65`).
  - Impact: it must become conditional on `draft_without_qa`, and it must stay
    at the end of hydration.
- **Observation: `_record_costs` runs only on the success path**
  (`launcher_persistence.py:125`).
  - Impact: D10 records costs on escalation.
- **Observation: the existing 422 test sends `qa_gated` together with a
  `skip_qa_rationale`.** See `tests/test_generation_run_api.py:373-377` and
  `tests/fixtures/generation_run_api.py:129-130`.
  - Impact: for unaccepted modes, the capability check must run before the
    gated-rationale rule. Otherwise that 422 would become a 400 (D7).
- **Observation: `IdempotencyStore.fail` deletes the in-flight record,** so the
  client can retry immediately
  (`episodic/canonical/storage/source_intake_repositories.py:292`).
  - Impact: a 4xx raised inside `run_idempotent`'s `work()` releases the key
    cleanly (D7).
- **Observation: the design diagram and the prose disagree about no-QA
  drafts.** The diagram sends both modes through one shared `Persist Draft`
  node and on into `Prepare for Approval`. The prose and ADR 0017 say no-QA
  drafts have no approval flow. In any case, the approval state machine (4.2.1)
  is not built.
  - Impact: D3 and D4.
- **Observation: the planning probes against the pinned LangGraph 1.2.11
  confirmed the runtime behaviour this plan relies on.**
  - `StateGraph(State, context_schema=Ctx)` with
    `async def node(state, runtime: Runtime[Ctx])` receives the context
    passed as `ainvoke(..., context=Ctx(...))`.
  - `get_graph().edges` reports conditional edges with `conditional=True`,
    once for each `path_map` target.
  - `astream(stream_mode="updates")` yields one `{node_name: delta}` for each
    executed node, and an empty delta appears as `None`.
  - `ainvoke` returns a plain `dict`.
  - An exception raised in a node reaches the caller unwrapped.
  - Cancelling the outer task while a node is awaiting raises
    `asyncio.CancelledError` out of `ainvoke`.
  - Evidence: `/tmp/lgprobe441/probe.py` and `probe2.py`, run with
    `uv run --frozen python -I`. The output included `raised MyErr True bad
    tei` and `cancelled ok True`.
  - Impact:
    - AXM-1 and AXM-2 hold.
    - The runner reads `result["terminal"]`.
    - `classify_failure` keeps working.
    - Scratch Python under `/tmp` must run from a dedicated directory with
      `-I`, because a stray `/tmp/bisect.py` shadows the standard library.
- **Observation (found by the expert panel): LangGraph converts a
  `CancelledError` raised by a node itself (`current_task().cancelling() == 0`)
  into `NodeCancelledError`, which is an `Exception`.**
  - Evidence:
    `.venv/lib/python3.14/site-packages/langgraph/pregel/_retry.py:777-792`.
  - Impact: the runner translates it back. The `evaluate` node re-raises
    `CancelledError` only when `cancelling() > 0`.
- **Observation: Alembic `compare_metadata` does not compare enum labels**
  (`episodic/canonical/storage/migration_check.py`).
  - Impact: INV-11.
- **Observation: nothing pins most of the no-QA observable behaviour.** No
  existing snapshot or test pins the launcher event payloads, the qa-bypass,
  terminal, draft-error or latency metrics, or the `"completed"` span outcome.
  The only metric assertions cover admission and pending depth
  (`tests/test_generation_run_launcher.py:366-375`).
  - Impact: EP-M0 adds a characterization suite before any refactor.
- **Observation: py-pglite serves one connection at a time, so no test in
  this harness can interleave two database sessions.**
  - Evidence: a scratch probe opened one session and then a second on the
    migrated `session_factory`. Holding the first idle and running
    `SELECT 1` on the second failed with
    `sqlalchemy.exc.OperationalError: (psycopg.errors.ConnectionTimeout)`,
    and a second probe that entered a transaction on the first session timed
    out waiting for the second to connect. The probe file was deleted after
    the measurement.
  - Impact: the race needs a real PostgreSQL server, not py-pglite. The
    committed test `tests/canonical_storage/test_generation_run_claim_concurrency.py`
    runs it when `EPISODIC_TEST_POSTGRES_DSN` is set and skips otherwise; it
    passed against PostgreSQL 17.11 for the commit-loses, rollback-wins and
    held-failure-transaction directions. Launcher-level fakes cover the same race
    without a second connection, and the INV-9 method names both.

## Decision log

Decisions D1 to D12 were proposed in the first draft (`5814b812`) and revised
after the expert-panel review. ADR 0029 records them during EP-M1 and is
accepted in EP-M6. D13 records the review itself.

- **Decision D1: compile the content-generation graph once and inject it
  through a domain port.**
  - The graph is a LangGraph `StateGraph` compiled once.
  - It is injected into the launcher through `ContentGenerationGraphPort`,
    which lives in `domain_ports`.
  - `LangGraphContentGenerationGraph` lives in `orchestration` and
    implements the port. The composition root passes it to
    `InProcessGenerationRunLauncher` as the new required field
    `content_graph`.
  - Per-run collaborators reach nodes through LangGraph's runtime context.
    The builder wraps each plain node function in a closure,
    `lambda state, runtime: node(state, runtime.context)`, so node functions
    never import `langgraph`.
  - Rationale:
    - Hecate forbids `application` from importing `orchestration`.
    - ADR 0017 anticipated this replacement.
    - `launch(run_id)` is unchanged.
    - Roadmap items 4.4.2 and 4.4.3 need a real cyclic graph.
    - The runtime context keeps the compiled graph stateless and shareable.
  - Date/Author: 2026-10-17, planning agent. The closure wrapping was adopted
    from Pandalump.
- **Decision D2: graph state holds domain values only.**
  - `ContentGenerationGraphState` holds `request`, a
    `ContentGenerationRequest` carrying `run_id` and `quality_mode`. It also
    holds `verdict`, `evaluations` and `terminal`.
  - Application objects (`ClaimedRun`, `DraftScriptResult`) stay inside a
    per-run *run session*. The launcher owns the session, and the session
    implements `ContentGenerationSteps`.
  - Rationale: this satisfies ADR 0022, gives each run a single writer, and
    keeps checkpoint payloads to orchestration metadata only.
  - Date/Author: 2026-10-17, planning agent.
- **Decision D3: fork before generation, and give each branch its own
  nodes.** The topology is:

  ```plaintext
  START → initialize → [quality branch]
    draft_without_qa: generate_draft_without_qa → persist_draft_without_qa → END
    qa_gated:         generate_qa_candidate → evaluate → [evaluation route]
                        pass:     persist_qa_passed_draft → END
                        escalate: escalate → END
  ```

  - Both generate nodes delegate to `generate_draft()`, and both persist
    nodes delegate to `complete_with_draft(...)`.
  - The only shared node is `initialize`.
  - Rationale:
    - The roadmap requires "distinct terminal states without ambiguous
      branch ownership", and shared generate or persist nodes make ownership
      visible only from history.
    - The design's Initialize step already "validate[s] the requested quality
      mode".
    - 4.4.3 can add `refine → generate_qa_candidate` inside the QA branch
      while INV-7's reachability check still holds.
    - The cost is one extra recorded deviation from the system-design
      diagram, reconciled in EP-M6.
  - Date/Author: 2026-10-17, planning agent. The early fork was adopted from
    Wafflecat and Pandalump.
- **Decision D4: defer the rest of the evaluation branch, and make `escalate`
  a failing terminal for now.**
  - Out of scope: `Prepare for Approval`, `Refine`, `Aggregate` as its own
    node, parallel evaluator fan-out, and a checkpointed `Escalate`.
  - In 4.4.1, `escalate` is a terminal that does the following:
    - fails the run with `error_category="qa.escalation_required"` and
      `qa_status=failed`;
    - writes no TEI;
    - records the provider cost (D10);
    - appends `qa.escalated` with `reason` set to `failed` or
      `inconclusive`.
  - Rationale: the deferred pieces belong to other roadmap items:
    - the approval state machine to 4.2.1;
    - Chrono in-loop to 4.4.2;
    - refinement and iteration caps to 4.4.3;
    - escalation checkpoints and a durable draft artefact to 4.4.4.

    A failed terminal is deterministic, terminal, and honest.
  - Date/Author: 2026-10-17, planning agent.
- **Decision D5: define the QA-status lifecycle.** `QaStatus` gains
  `PENDING`, `PASSED` and `FAILED`.
  - For `draft_without_qa`:
    - `qa_status` is always `skipped`.
    - `skip_qa_rationale` is required and non-blank, as today.
  - For `qa_gated`:
    - `skip_qa_rationale` must be `None`.
    - `qa_status` must be in `{pending, passed, failed}`; `None` and
      `skipped` are invalid.
    - `passed` holds if and only if the run is `succeeded`.
    - Every other run status, terminal or not, allows `pending` or `failed`.
      This leaves room for a `running` refine loop (4.4.3) and a `paused`
      escalation (4.4.4).
  - `GenerationRunStatusUpdate` gains `qa_status: QaStatus | Unchanged`,
    which defaults to the sentinel `UNCHANGED`. This contrasts with the error
    fields, where an omitted value clears the field, and the docstring states
    the contrast.
  - Both adapters compute the resulting run through one shared domain helper,
    `apply_status_update(run, update) -> GenerationRun`. The helper
    re-validates via `dc.replace`. Fields are written only if it succeeds.
  - Validation runs in this order: not found, then already terminal, then
    lifecycle, then quality. With this order, a late shutdown write against a
    terminal run still raises `RunAlreadyTerminal`, which `_record_failure`
    swallows, rather than `ValueError`.
  - Rationale:
    - "A QA-gated run succeeded" becomes equivalent to "QA passed".
    - A skip rationale on a gated run would be contradictory provenance.
    - The sentinel avoids silently resetting `qa_status` on failure writes.
  - Date/Author: 2026-10-17, planning agent. The relaxed non-terminal rule
    came from Telefono and the validation order from Doggylump.
- **Decision D6: the TEI envelope reports the producing run's
  `quality_mode`.**
  - `serialize_tei_envelope(episode, *, quality_mode)` receives
    `run.quality_mode` from `EpisodeTeiResource`, which already loads the
    run.
  - `EpisodeTeiUpdate` refuses any `qa_status` other than `skipped` or
    `passed`.
  - No `episodes.quality_mode` column is added.
  - Rationale: the run is authoritative. Deriving the mode from `qa_status`,
    as the first draft proposed, breaks once a human-override status or an
    advisory, non-gating QA mode is added.
  - Date/Author: 2026-10-17, planning agent, revised from Telefono.
- **Decision D7: accept `qa_gated` over REST only where the deployment can
  evaluate it.**
  - `ContentGenerationGraphPort.accepted_quality_modes()` is the single
    source of truth.
    - The composition root copies it into the new
      `ApiDependencies.accepted_quality_modes`.
    - That field defaults to `frozenset({QualityMode.DRAFT_WITHOUT_QA})`.
    - `episodic/api/app.py` passes the field to `GenerationRunsResource`.
  - The checks run in this order:
    1. **Before idempotency**, `_parse_create_request` keeps today's body
       rules:
       - a missing or invalid `quality_mode` returns 400 with constraint
         `enum`;
       - `draft_without_qa` without `skip_qa_rationale` returns 400 with
         constraint `required`.
    2. **An unaccepted mode** returns the unchanged
       `422 quality_mode_unsupported` envelope. Where it runs depends on the
       request: with no `Idempotency-Key` it runs before `run_idempotent`,
       because no replay is possible; with a key it runs inside `work()`.
    3. **Next**, a `qa_gated` body carrying `skip_qa_rationale` returns
       `400 validation_error(field="skip_qa_rationale",
       constraint="exclusive_with_quality_mode",
       details.quality_mode="qa_gated")`, in the same position as step 2.
  - Amendment (D20): the original text placed both checks inside `work()`
    unconditionally, which changed the keyless precedence and lost the
    malformed-budget error. D20 restores the pre-4.4.1 order and applies the
    keyed and keyless orders separately, as above.
  - Both errors raised inside `work()` release the idempotency key.
  - Replaying an accepted request still returns the stored `202` after the
    deployment withdraws the capability.
  - Rationale:
    - Production has no evaluator until 4.4.2.
    - Accepting the mode unconditionally would pay for drafts that must
      escalate.
    - This ordering keeps the existing 422 assertion, which sends a
      rationale with `qa_gated`, byte-identical.
    - `forbidden` is already the 403 error code, so the constraint uses a
      different name.
  - Date/Author: 2026-10-17, planning agent. The idempotency ordering and the
    constraint name came from Telefono.
- **Decision D8: aggregate verdicts with "all must pass", and isolate
  evaluator errors.**
  - Aggregation rules:
    - an empty list gives `inconclusive`;
    - any `failed` gives `failed`;
    - otherwise, any `inconclusive` gives `inconclusive`;
    - otherwise the result is `passed`.
  - Each evaluator runs under `asyncio.timeout`. The following each become
    that evaluator's `QualityEvaluation(verdict=INCONCLUSIVE,
    error_type=…)`:
    - an `Exception`;
    - a timeout, recorded as `error_type="timeout"`;
    - a `CancelledError` raised while `current_task().cancelling() == 0`.

    These cases are logged with `log_exception`. A genuine cancellation
    (`cancelling() > 0`) is always re-raised.
  - `initialize` raises `QualityEvaluationUnavailableError`, category
    `qa.unavailable`, for a `qa_gated` run with no evaluators, before any
    generation spend.
  - Rationale:
    - "All must pass" is the system design's default policy.
    - A QA tool outage must not be mistaken for a generator failure, and
      errors must stay distinguishable from genuine verdicts.
  - Date/Author: 2026-10-17, planning agent. Error visibility, the timeout and
    the fail-fast check came from Doggylump, Buzzy Bee and Pandalump.
- **Decision D9: define the event stream for `qa_gated` runs.** In order:
  1. `run.started`, unchanged.
  2. `draft.generated`, unchanged.
  3. `qa.evaluation_started`, with payload
     `{"current_node": "evaluate", "evaluators": [<slug>, …],
     "content_hash": <hash>}`. The same unit of work makes a non-terminal
     status update setting `current_node="evaluate"`.
  4. One terminal unit of work. It appends `qa.result`, with payload
     `{"verdict": <aggregate>, "evaluators": [{"name", "verdict", "errored",
     "error_type"}]}`, followed by one of these:
     - `tei.persisted` (`qa_status="passed"`), then `run.succeeded`;
     - `qa.escalated` (`{"reason": <failed|inconclusive>, "content_hash":
       <hash>}`), then `run.failed`
       (`error_category="qa.escalation_required"`).

  - `draft_without_qa` runs emit no new events. Their branch decision is
    logged as `generation_run.quality_branch run_id=%s branch=%s` and
    recorded in the span attributes `quality_branch` and `terminal`.
  - The span `outcome` stays `"completed"` for every successful terminal. It
    is `"escalated"` for a `qa_gated` escalation, which has no 4.3.2
    precedent.
  - Rationale:
    - The event catalogue defines `qa.result` as "Evaluator scores and
      remediation hints", and the per-evaluator payload lets 4.4.2 add
      findings without a breaking change.
    - Putting `qa.result` in the terminal unit of work removes a round trip
      and cannot leave a dangling result after a crash.
    - Evaluator names are stable slugs.
  - Date/Author: 2026-10-17, planning agent, revised from Telefono and Buzzy
    Bee.
- **Decision D10: escalation reuses the failure write path.**
  - `Failure`, in `episodic/generation/launcher_support_events.py`, gains
    three fields:
    - `qa_status: QaStatus | Unchanged`, defaulting to `UNCHANGED`;
    - `is_draft_error: bool`, defaulting to `True`;
    - `escalation: EscalationEvent | None`, defaulting to `None`.
  - `_record_failure(run_id, failure, *, draft=None)` changes as follows:
    - it appends `qa.escalated` before `run.failed` when `escalation` is
      set;
    - it records costs when `draft` is given;
    - it records the terminal-state metric with the failure's category;
    - it increments `generation_run_draft_errors_total` only when
      `is_draft_error` is true;
    - it logs at info rather than error level when `is_draft_error` is
      false.
  - The `qa.result` event is appended in the same unit of work.
  - Rationale:
    - The escalated draft did spend inference.
    - QA verdicts must not page on-call as draft errors.
    - Reusing the path avoids a duplicate write path that the nose gate would
      flag, and avoids adding to the mixin debt tracked in #350.
  - Date/Author: 2026-10-17, adopted from Pandalump, Buzzy Bee and Doggylump.
- **Decision D11: validate the generator's draft as TEI before evaluation.**
  - `generate_draft()` runs `parse_tei_header` after recording
    `draft.generated`. A failure raises `InvalidDraftTeiError`, as
    persistence does today.
  - Persistence still validates as well.
  - Rationale: QA must not pass invalid TEI. For no-QA runs, both the failure
    classification and the event order (`draft.generated`, `tei.invalid`,
    `run.failed`) are unchanged, and the EP-M0 invalid-TEI case pins this.
  - Date/Author: 2026-10-17, adopted from Pandalump.
- **Decision D12: the runner translates graph-level failures.**
  `LangGraphContentGenerationGraph.run` does three things:
  - It translates LangGraph's `NodeCancelledError` into
    `asyncio.CancelledError`, preserving 4.3.2 behaviour.
  - It raises the domain error `ContentGenerationGraphError(reason)` when the
    final state has no terminal, or when the terminal's owning branch is not
    the run's branch. This error gets the new category
    `orchestration.incomplete` in `_FAILURE_CATEGORIES`.
  - It passes no `step_timeout` and uses no checkpointer in 4.4.1, like the
    planning graph.
  - Rationale: this gives INV-5 defence in depth in production, keeps the
    no-QA constraint, and gives operators a stable category if the wiring is
    wrong.
  - Date/Author: 2026-10-17, adopted from Doggylump.
- **Decision D13: record the expert-panel review.**
  - Verdict: "proceed with conditions".
  - The blocking findings, all resolved in the decisions above:
    1. The success update lacked `qa_status`, so every passing gated run
       would have failed.
    2. Escalated runs dropped their inference cost.
    3. LangGraph imports leaked into node functions.
    4. The INV-8 evidence did not pin metrics, spans or event payloads.
    5. The self-raised `NodeCancelledError` conversion was unhandled.
    6. The non-vacuity checks could not be executed under xdist.
    7. Moving the existing 422 scenario would have broken the no-QA
       tolerance.
  - The strongest alternative was the early fork, which was adopted as D3.
  - Rejected alternatives:
    - A pure router in the launcher with no LangGraph: 4.4.3 would have to
      redo it.
    - Letting the graph own the claim: the `not_claimed` outcome would have
      no owning branch.
    - Accepting `qa_gated` unconditionally: it would spend inference on runs
      that must escalate.
    - One shared persist node with a branch-tagged terminal: ownership would
      be visible only from history.
  - Date/Author: 2026-10-17, Logisphere panel via the planning agent.

- **Decision D17: record the accepted scope deviation for the rebase-era
  diff.**
  - The plan's Tolerance section caps a change at 65 files and 3,500 net added
    lines, excluding snapshots and the plan.
  - The delivered diff against `main` is larger, and the overrun is not new
    feature work: it is the rebase crossing ADR renumbering, the df12 gate
    migrations, the logging port, QA artefact persistence, and three
    intervening migrations, plus the test support the new gates require.
  - The scope itself is unchanged: the plan's milestones, acceptance
    criteria, and verification obligations are exactly as approved.
  - The measured diff is 81 files and 7,031 net added lines excluding this
    plan and the snapshots. 4.3.2's no-QA path used no graph at all, so this
    item necessarily introduces the graph, its ports, the QA policy, the
    migration, the API surface, the behavioural feature and the
    characterization snapshot together; no subset is independently
    shippable.
  - Accepted by the user's instruction to implement the approved plan to
    completion, which supersedes the size tolerance for this delivery. A
    reviewer who rejects the size can still halt the branch before merge;
    nothing in the code depends on the decision.
  - Date/Author: 2026-11-22, implementation agent, after the CodeRabbit
    completeness assessment raised the overrun.
- **Decision D18: apply the five correctness repairs CodeRabbit's assessment
  found.**
  - `initialize` claims before it refuses an unevaluable run, so a losing
    launcher can never fail a claimed run.
  - Node tasks are tracked per graph invocation, so cancelling one runner
    cannot cancel another runner's tasks.
  - The initial quality-mode read is inside `_execute_run`'s failure boundary,
    so a read fault records a terminal failure.
  - An evaluation that reports `error_type` with a `passed` verdict is
    normalized to `inconclusive`, so an inconsistent adapter fails closed.
  - Budget-hint validation runs inside the idempotent work, after the
    capability and gated-rationale checks, restoring the historical 422
    precedence.
  - The shielded shutdown write runs in a task named
    `generation-run-{run_id}`, so the INV-9 task-name invariant covers
    cancellation as well as the three normal outcomes.
  - Each repair has a test: the duplicate-claim interleaving, two concurrent
    graph invocations, the injected read fault, the error-tagged pass, the
    malformed-budget precedence case, and a four-cell task-name matrix over
    gated-passed, gated-failed, no-QA, and shutdown.
  - Consequence: the capability refusal now follows the claim, so its run
    records `run.started` before `run.failed`; the existing assertion was
    updated to the new event sequence.
  - Date/Author: 2026-11-22, implementation agent.
- **Decision D19: a claim, not a task name, authorizes a terminal write.**
  - A task name records which invocation wrote an event. It does not prove
    that invocation owns the run, because two launchers in one process can
    target the same run id.
  - A frozen `ClaimToken` is the authority to write a terminal state.
    `RunClaim` holds one per launcher invocation; `_claim_and_start` stores
    the token inside its unit of work as soon as the pending-to-running
    transition commits, and `_claim_for_failure` returns one for a failure
    that arrives first. The token, not a boolean and not a task name, is what
    `_record_failure` consults.
  - `_record_failure` returns whether it wrote. A failure on a run this
    invocation neither claimed nor can claim writes nothing, records nothing
    in metrics, and reports `not_claimed` on the span. The cancellation path
    uses the same gate.
  - Consequence: a losing launcher can no longer fail a run for any reason,
    including a pre-claim read fault or a shutdown before its claim. Tests:
    `tests/test_generation_run_launcher_quality_ownership.py`.
  - Cost: a run abandoned by its claimant before the first claim transition
    stays pending, rather than being failed by an uninvolved launcher. That is
    the correct trade: the alternative overwrites a live writer. Such a run is
    not covered by lease reclamation, which selects expired *running* runs;
    the next launcher's compare-and-set picks it up, subject to any stalled
    transaction holding its row lock (D24).
  - Date/Author: 2026-11-22, implementation agent.
- **D19 scope note: the claim token is decided by the launcher and enforced by
  the store.**
  - Originally `update_run_status` took no token: the row lock and terminal
    checks protected concurrent writers, and the atomic pending-to-running
    claim was the only store-level guard. That historical position was
    superseded by the terminal-claim gate recorded under Residual gaps: every
    terminal write now names its claim proof, and both adapters compare it
    under the row lock, raising `RunClaimMismatch` for an absent or different
    token. A run with no stored claim has no owner to check, so an internal
    path (a launch failure, or reclamation) may still terminate it.
  - A cached token names exactly one run: `_failure_authority` refuses a
    token whose `run_id` differs from the run being failed. That is a
    launcher-side guard against a *different* run's token; separately, the
    store compares the same-run proof under its row lock and raises
    `RunClaimMismatch`, so the two checks are complementary rather than one
    substituting for the other.
  - The gate is now implemented: every terminal write names its claim proof,
    both adapters compare it under the row lock, and contract tests cover a
    wrong token, a missing token and an unclaimed run.
  - Date/Author: 2026-11-24, implementation agent, from CodeRabbit's Domain
    Architecture warning.
- **Decision D20: restore the pre-4.4.1 request-error precedence.**
  - The base parser read the capability 422 first, then `budget_hints`, then
    the no-QA rationale. The 4.4.1 parser moved the budget read into the
    idempotent work, so an unaccepted mode without an idempotency key returned
    the missing-key 400 instead of the 422, and a malformed budget lost to the
    rationale check.
  - `_validate_quality_request` now applies capability, budget, then rationale
    in that order. It runs before `run_idempotent` when no key is present,
    because no replay is possible; with a key it still runs inside `work()`, so
    a stored 202 replays after the capability is withdrawn and a rejection
    releases the key (INV-12).
  - Tests: `test_no_qa_budget_error_outranks_the_missing_key`,
    `test_unaccepted_mode_outranks_other_validation` (with and without a key),
    and `test_missing_key_with_an_accepted_mode_is_reported`.
  - Date/Author: 2026-11-22, implementation agent.
- **Decision D21: harden the ownership boundary at its three edges.**
  - A refused cancellation no longer marks the run cancelled: the run id is
    added to the dedup set only when the write was actually recorded, so a
    losing invocation cannot suppress its owner's terminal write.
  - `ownership.claimed` is set inside the claim's unit of work, immediately
    after `commit()`, not after the session closes. A close fault now keeps
    the ownership its committed claim earned and records the failure instead
    of leaving the run running with no entitled writer.
  - Request validation runs before the missing-launcher 503, restoring the
    base precedence: an unsupported mode is 422 and a malformed budget is 400
    even when no launcher is configured. With a key the validation still runs
    inside the idempotent work, after replay detection.
  - Tests: `test_refused_cancellation_does_not_suppress_the_owner`,
    `test_claim_survives_a_session_close_fault`, and
    `test_request_errors_outrank_a_missing_launcher` (three cases).
  - Date/Author: 2026-11-22, implementation agent.
- **Decision D22: keep ownership and precedence correct across commit and
  conflict boundaries.**
  - A failure-path claim is recorded only after the failure transaction
    commits. If that transaction rolls back, the flag stays unset and a later
    cancellation retries the pending-to-running compare-and-set rather than
    trusting a claim that no longer exists.
  - `run_idempotent` accepts an optional `precondition` applied after a stored
    replay is ruled out and before a conflict or in-flight outcome is
    reported. A reused key can no longer turn a malformed body into a 409,
    while a stored gated 202 still replays after capability withdrawal. A
    freshly acquired record is not pre-checked: the work validates, so a
    rejection releases the key.
  - Tests: `test_rolled_back_failure_claim_is_not_reused`,
    `test_claim_exit_fault_still_records_the_failure` (close error and
    cancelled close), `test_reused_key_still_reports_the_body_error`, and
    `test_no_qa_missing_launcher_outranks_idempotency` (replay and conflict).
  - A no-QA request is validated and launcher-resolved before idempotency,
    matching the base: a removed launcher is a 503 rather than a replay or a
    409. A QA-gated request keeps D7's ordering, which is key-dependent: with
    no `Idempotency-Key` its checks run before `run_idempotent`, and with a
    key they run in the work (or in the precondition for a conflict), so a
    rejection releases the key and a stored 202 still replays after the
    capability is withdrawn.
  - Date/Author: 2026-11-22, implementation agent.
- **Decision D23: authorize and reconcile claims with a unique proof.**
  - The pending-to-running claim stores a per-attempt UUID in the nullable
    `generation_runs.claim_token` column (revision `20261123_000019`). A
    cancelled commit acknowledgement is reconciled by comparing that exact
    proof, not the start timestamp, because a frozen test clock or a
    microsecond collision can make timestamps equal.
  - The failure authority claims and writes inside one transaction: a separate
    claim transaction would release the run before the failure lands. If the
    claim already exists it is reconciled first, so a second cancellation
    during shielded reconciliation still adopts the durable claim.
  - A tokenless duplicate cancellation may not suppress the claim holder's
    write; only `_cancelled_run_ids` (recorded writes) deduplicates
    unconditionally.
  - Date/Author: 2026-11-23, implementation agent.
- **Decision D25: reconcile inside the failure transaction and publish QA
  metrics only after the write.**
  - `GenerationRunFailurePersistence` no longer takes a separate
    `reconcile_claim` authority. It compares the durable
    `claim_token_for(run_id)` with the attempt's proof inside the caller's
    unit of work, so a failure write runs no nested unit of work and no hidden
    I/O inside its own open transaction. The proof rule applies to the
    tokenless path: an attempt with no token writes only when the stored proof
    matches, and if it matches nothing it may still claim the pending run in
    this same transaction before writing. An attempt that already holds a
    token for this run is trusted without re-reading the proof, because the
    launcher set that token only after the claim committed (D19's scope note).
  - `_LauncherRunSession` records QA outcome metrics after
    `persist_success` commits and after `record_failure` reports a written
    escalation, so a refused or failed write emits no QA verdict metrics.
  - Tests: `test_refused_escalation_records_no_qa_metrics`, the unchanged
    same-unit-of-work test, and the existing escalation metric assertions in
    the INV-9 matrix.
  - Date/Author: 2026-11-24, implementation agent, from CodeRabbit's Unit
    Architecture pre-merge row.
- **Decision D24: bound the cancellation and reconciliation waits.**
  - A cancellation write is shielded so a second cancellation cannot lose it,
    which also means an unresponsive database call could hold `shutdown()`
    open forever. During shutdown, `drain()`, `record_cancellation_owned` and
    the claim cancellation path (`_claim_and_start`'s shielded reconciliation)
    wait at most their own deadlines: the scheduler uses
    `cancellation_write_timeout_seconds`, and the claimer uses
    `reconcile_timeout_seconds`. Both default to 10 seconds and are
    independent settings, so tightening one never changes the other. A normal
    `drain()` stays unbounded and rechecks both the task and cancellation-write
    registries until both are empty, so a run admitted while it waits — on
    either registry — is still awaited.
  - An unverified claim is never adopted: a reconciliation that misses the
    deadline leaves `claim.token` unset, so the run is not failed by an
    invocation whose ownership the database did not confirm.
  - A write that misses the deadline is abandoned, not cancelled: it stays
    shielded so it can still land. Recovery covers both shapes. A run whose
    earlier execution claim committed is running with that claim's lease and
    is recovered by expired-lease reclamation. A failure-only claim commits
    with the terminal write it authorizes, so it never leaves a separate
    running state: a stalled one leaves the run pending, and the next
    launcher's compare-and-set claims it once any transaction still holding its
    row lock is released, for example by terminating that backend. Each miss
    increments
    `generation_run_cancellation_write_timeouts_total`, so an operator can see
    that shutdown did not confirm the write.
  - The run tasks themselves are bounded by the same deadline *during
    shutdown only*, because a unit of work's rollback or session close can
    stall after the cancellation arrives;
    `generation_run_shutdown_task_timeouts_total` records that case. A normal
    `drain()` keeps its documented unbounded contract and never counts a
    shutdown timeout, since callers rely on it returning only once the work
    has finished.
  - A stalled transaction can hold the row lock while its run stays pending.
    The recovery is operational and measured: terminate the stalled backend,
    which aborts its transaction and releases the row, and the next claim
    proceeds. `test_a_stalled_claim_transaction_is_recoverable` holds a claim
    open on a real PostgreSQL connection, blocks the competitor, terminates
    the holder's backend, and asserts the competitor then wins with its own
    proof durable.
  - Tests: `test_shutdown_abandons_a_stalled_cancellation_write` proves the
    cancellation-write bound and its counter,
    `test_shutdown_abandons_a_stalled_run_task` proves the task bound,
    `test_stalled_reconciliation_is_bounded` proves an unverified claim is not
    adopted, and
    `test_shutdown_waits_for_a_cancelled_cancellation_write` keeps proving
    that a write which does finish is awaited.
  - Date/Author: 2026-11-24, implementation agent, from a CodeRabbit finding.
- **Decision D16: own the graph task and name every node task.**
  - The runner creates the `ainvoke` task itself, names it
    `generation-run-{run_id}`, and on cancellation cancels and drains it and
    then every task in that invocation's `RunTaskRegistry` before
    re-raising.
  - Ownership is per invocation, not per name. Two graph invocations for the
    same run id use the same task name, so cancelling by name would reach
    into another invocation's nodes; D18 replaced an earlier name-based sweep
    with the registry for exactly that reason.
  - The builder's wrapper renames the task LangChain creates for each node to
    the same convention and registers it, so every `append_event` happens on
    a task named for its run, as INV-9 requires.
  - Rationale: LangChain's `coro_with_context` always creates a task for a
    node, so cancelling the launcher task alone would leave an in-flight
    evaluator or terminal unit of work running after shutdown.
  - Date/Author: 2026-11-22, implementation agent. Found by INV-9's task-name
    assertion on the first QA-gated launcher test.
- **Decision D15: keep D9's span attributes and record the one deliberate
  INV-0 snapshot change.**
  - INV-0 captures span attributes. D9 mandates `quality_branch` and
    `terminal` span attributes on no-QA runs. The two requirements collide.
  - D9 is the more specific, later decision, so the success-case snapshot now
    includes those two attributes. The `outcome` value, events, metrics, and
    persisted rows are unchanged, and every other INV-0 case is byte-identical.
  - This is the only snapshot change; the snapshot was not regenerated, only
    those two lines were added.
  - Date/Author: 2026-11-22, implementation agent.
- **Decision D14: land each new domain symbol in the commit that gives it a
  production caller.**
  - The Skylos dead-code gate is blocking and runs on every commit.
  - `generation_routing` and `generation_graph_ports` therefore move from
    EP-M1 to EP-M3, where the graph builder, the graph runner and the evaluate
    node call them.
  - `terminal_outcome` moves to EP-M4, where the launcher session records it.
  - `apply_status_update` moves to EP-M2 with both store adapters.
  - Rationale: adding entry-point allow-list rules for symbols with no caller
    yet would record an unverified runtime caller, which the repository's
    Skylos policy explicitly forbids.
  - Date/Author: 2026-11-22, implementation agent. The gate evidence is the
    EP-M1 Skylos run recorded in `Artefacts and notes`.

## Outcomes & retrospective

Roadmap item `4.4.1` is implemented. Every generation run executes through a
compiled content-generation graph; `draft_without_qa` keeps its direct route
and its entire observable contract, and `qa_gated` is accepted only where the
deployment has evaluators.

What was delivered:

- Domain policy: `qa_gated`, the four QA statuses, one exhaustive
  quality-metadata rule, and a persisted-draft-only `EpisodeTeiUpdate`.
- Persistence: additive enum labels in revision `20261122_000018` and the
  D23 claim-token column in `20261123_000019`, the `UNCHANGED` QA sentinel with
  one shared status-update helper in both adapters, and a TEI envelope that
  reports the producing run's mode.
- Orchestration: pure routing policy, graph ports, node functions that import
  no framework, a compiled graph with per-branch nodes and terminals, and a
  runner that owns its graph task and translates LangGraph's cancellation
  wrapper.
- Application: a per-run session as the only path from node to run state, QA
  event payloads and metrics, escalation through the existing failure path with
  costs preserved, and fail-closed `qa.unavailable`.
- REST and composition root: the capability gate, the gated-rationale rule,
  idempotency-key release, and one graph whose accepted modes are advertised to
  the API.
- Documentation: ADR 0029 accepted, ADR 0017 annotated, and the system design,
  TUI API design, users' guide, developers' guide, contents index, and roadmap
  updated.

What changed against the plan, and why:

- D14 moved the routing policy and graph ports from EP-M1 to EP-M3, and
  `apply_status_update` to EP-M2, so the blocking Skylos gate never sees a
  symbol without a production caller.
- D15 kept D9's span attributes and added exactly two lines to the INV-0
  success snapshot. Every other INV-0 case is byte-identical, and the
  invariant's `outcome` value is unchanged.
- D16 corrected AXM-1: LangChain always wraps a node call in a task. The
  runner owns and names the graph task, renames node tasks, and cancels and
  drains them at shutdown.
- `EpisodeTeiUpdate`'s persisted-draft rule landed in EP-M1 rather than EP-M2
  so that milestone stayed green.
- The runtime composition root injects the graph in EP-M4 rather than EP-M5,
  because the constructor field became required in EP-M4.

Verification summary:

- INV-0 to INV-13 are discharged as described in the verification plan, with
  the literal tables, Hypothesis witnesses, counters, and seeded faults
  recorded in `Artefacts and notes`.
- The final gate run passed `make check-fmt`, `make typecheck`, `make lint`,
  `make test`, `make check-migrations`, `make markdownlint`, and `make nixie`.
  `make test` reported 2006 passed, 1 skipped (Docker-conditional), and 63
  snapshots.

Remaining gaps, unchanged from the plan:

- Roadmap items `4.4.2` to `4.4.4` own real evaluators, parallel evaluation,
  refinement, `recursion_limit` sizing, resume replay, a durable draft
  artefact, and the paused escalation terminal.
- `2.6.2` must not reclaim a run on a stale lease while
  `current_node="evaluate"`.
- `accepted_quality_modes` always contains `draft_without_qa`; a deployment
  that forbids it awaits the approval workflow.

## Context and orientation

The repository is a Python 3.14 service named `episodic`, with the package in
`episodic/` and tests in `tests/`. It follows hexagonal architecture: domain
types and port protocols are pure, and adapters implement them. Hecate, an
import-boundary checker configured under `[tool.hecate]` in `pyproject.toml`,
enforces the layers. Groups match modules by prefix and the first matching
group wins, so a broad prefix listed early silently captures modules meant for
a later group.

Terms used in this plan:

- **Generation run.** A durable record of one attempt to turn ingested
  sources into a TEI-P5 podcast script.
  - Domain type: `GenerationRun` (`episodic/canonical/domain_generation.py`).
  - Statuses: `GenerationRunStatus` (`episodic/canonical/domain_enums.py`).
  - Ports module: `episodic/canonical/generation_run_ports.py`, which is not
    in any Hecate group today.
- **Quality mode and QA status.** The quality mode is the requested QA policy
  for a run (`QualityMode` in `episodic/canonical/generation_quality.py`). The
  QA status (`QaStatus`) is the recorded QA outcome, both on the run and on the
  episode TEI that the run wrote.
- **Launcher.** `InProcessGenerationRunLauncher`
  (`episodic/generation/launcher.py`) is the orchestration boundary over four
  injected components:
  - `GenerationRunScheduler` (`launcher_scheduling.py`) owns admission, the
    task registry, cancellation bookkeeping and shutdown.
  - `GenerationRunClaimer` (`launcher_claim.py`) owns the claim, its token and
    proof, hydration and draft generation.
  - `GenerationRunPersistence` (`launcher_persistence.py`) owns draft events,
    TEI, costs and successful terminals.
  - `GenerationRunFailurePersistence` (`launcher_failure.py`) owns
    authoritative failure terminals.

  The launcher keeps the graph invocation and failure classification in
  `_execute_run`. Issue #350 landed this split on `main`; the QA-gated work is
  merged onto it.
- **Step port.** A protocol through which a graph node asks the launcher to
  perform one I/O step for the run that the node is executing.
- **Terminal.** A graph node after which the graph ends, together with the
  `GenerationTerminal` value that the node sets.
- **Branch ownership.** Every node except `initialize`, and every terminal,
  belongs to exactly one quality branch.
- **Vidai Mock.** An offline, wire-accurate mock of OpenAI-compatible
  inference servers, used by the behavioural tests
  (`tests/steps/vidaimock_harness.py`). It requires `vidaimock` 0.2.8 or later,
  and the fixtures pass `--isolated`.

Key files:

- **Quality enums and run validation:**
  `episodic/canonical/generation_quality.py`,
  `episodic/canonical/domain_validation.py`, and
  `episodic/canonical/domain_generation.py`.
- **Episode TEI writes:** `EpisodeTeiUpdate` in
  `episodic/canonical/domain_episodes.py`, and `persist_draft_script` in
  `episodic/canonical/generation_persistence.py`.
- **Ports and run stores:** the ports in
  `episodic/canonical/generation_run_ports.py`, the SQL adapter
  `episodic/canonical/storage/generation_runs.py`, and the in-memory adapter
  `episodic/canonical/adapters/generation_runs.py`.
- **Migrations:** `alembic/versions/`. The head is
  `20261010_000013_name_pricing_snapshot_constraint.py`, whose `CommandError`
  and offline-mode guard are the model for the downgrade.
- **REST:**
  - `episodic/api/resources/generation_runs.py` and
    `episodic/api/resources/generation_runs_create_support.py`.
  - `episodic/api/resources/episode_tei.py`.
  - `episodic/api/serializers.py` and `episodic/api/dependencies.py`.
  - `episodic/api/app.py`, which wires `GenerationRunsResource` field by
    field at about line 271.
  - `episodic/api/source_idempotency.py`.
- **Composition root:** `episodic/api/runtime.py`.
- **Launcher:** `episodic/generation/launcher*.py`, and
  `episodic/generation/launcher_support_events.py`, which holds `Failure`,
  `classify_failure` and `_FAILURE_CATEGORIES`.
- **Graph examples:** `episodic/orchestration/_graph_builder.py` (closure
  wrappers at about lines 101–150), `episodic/qa/langgraph.py`, and
  `episodic/qa/chrono_langgraph.py`.
- **Affected tests:**
  - `tests/test_generation_run_domain.py`.
  - `tests/test_generation_run_api.py`; its 422 assertion at lines 371–398
    stays unchanged.
  - `tests/test_generation_run_launcher*.py` and
    `tests/generation_run_launcher_support.py`.
  - `tests/test_generation_source_limits.py`.
  - `tests/test_generation_run_port_contract.py`.
  - `tests/canonical_storage/test_sql_generation_run_property_contract.py`.
  - `tests/test_production_hecate_orchestration_config.py`.
  - `tests/steps/test_no_qa_generation_slice.py` (385 lines, holding the
    shared Background steps) and
    `tests/steps/no_qa_generation_slice_support.py`.

Documentation to read before each milestone:

- `docs/roadmap.md` §4.4: the item text and the 4.4 concurrency model.
- `docs/episodic-podcast-generation-system-design.md`: the sections "Content
  Generation Graph", "LangGraph Integration Principles", "Quality Assurance
  Stack", "Configuration and Tunables" and "Source-to-script vertical slice".
- `docs/episodic-tui-api-design.md`: "Generation runs", the event catalogue
  (about lines 636–647), and the source-to-script vertical slice.
- ADRs 009, 014, 015 (generation-run port split), 017 and 022, in
  `docs/adrs/`.
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` (conditional
  routing as application policy) and
  `docs/agentic-systems-with-langgraph-and-celery.md`.
- `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md` and
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.
- `docs/developers-guide.md`: "Generation-run domain ports", "No-QA launcher
  and TEI retrieval", "Testing the orchestration slice", and the Vidai Mock
  harness section.
- `docs/documentation-style-guide.md`, for the ADR format. The next free ADR
  number is 024.

Skills to load during implementation:

- `hexagonal-architecture`.
- `python-router`, which routes on to `python-types-and-apis`,
  `python-data-shapes`, `python-concurrency`, `python-errors-and-logging` and
  `python-testing`.
- `hypothesis` and `python-verification`.
- `vidai-mock`.
- `codegraph-mcp` or `leta`, for caller and impact analysis before editing
  the launcher.
- `skylos`.
- `execplans`.
- `commit-message` and `pr-creation`.

## Conformance basis

Upstream artefacts:

- **Roadmap:** `docs/roadmap.md` §4.4.1 and the §4.4 preamble, at `main`
  commit `468923ed`. There are no Terms of Reference and no numbered
  requirement register, so this plan assigns local identifiers.
- **Technical design:** `docs/episodic-podcast-generation-system-design.md`
  at `468923ed`, section "Content Generation Graph" (SD-CGG).
- **ADRs:**
  - ADR 0009, the source-to-script slice (ADR-0009).
  - ADR 0014, hexagonal enforcement (ADR-0014).
  - ADR 0017, no-QA execution and the launcher port (ADR-0017).
  - ADR 0022, orchestration architecture enforcement (ADR-0022).
- **Governing standards:** `AGENTS.md`, `docs/documentation-style-guide.md`,
  and `.rules/python-*.md`.

Local identifiers:

- `RM-441-A`: extend run creation and run-state validation for `qa_gated`.
- `RM-441-B`: preserve `draft_without_qa` as a direct route to draft
  persistence.
- `RM-441-C`: route `qa_gated` into the SD-CGG evaluation branch.
- `RM-441-D`: Hypothesis properties showing distinct terminal states without
  ambiguous ownership.
- `RM-441-S`: deterministic, distinct branches with clear terminal states
  (the success criterion).
- `RM-44-CONC`: single-writer run state, ordered publication, and
  shutdown-safe cancellation (the §4.4 preamble).

Trace links:

```plaintext
RM-441-A -> SD-CGG.Initialize -> D5, D7, D8 -> EP-M1, EP-M2, EP-M5 -> INV-1, INV-2, INV-11, INV-12
RM-441-B -> SD-CGG.QualityBranch -> D3, D9, D11, D12 -> EP-M0, EP-M3, EP-M4 -> INV-5, INV-8
RM-441-C -> SD-CGG.Evaluate -> D1, D4, D8, D10 -> EP-M3, EP-M4 -> INV-4, INV-5, INV-9
RM-441-D -> SD-CGG -> D3 -> EP-M1, EP-M3 -> INV-3, INV-5, INV-7
RM-441-S -> SD-CGG -> D1-D12 -> EP-M5 -> tests/features/qa_gated_generation_routing.feature
RM-44-CONC -> ADR-0017 -> D2, D5, D12 -> EP-M4 -> INV-9, INV-10
ADR-0022 -> D1, D2 -> EP-M3 -> make lint (Hecate), tests/test_production_hecate_orchestration_config.py
```

Deviations from SD-CGG, all recorded in ADR 0029 and reconciled in EP-M6:

1. The fork comes before generation, with one generate node per branch (D3).
2. Persist Draft is split into one node per branch (D3).
3. Aggregate as a separate node, Refine, Prepare for Approval, and a
   checkpointed Escalate are deferred (D4).

## Verification plan

This change introduces real invariants over states and transitions. The
obligations below are listed in dependency order.

Non-vacuity is shown only by executable means:

- `@example(...)` witnesses for every required class.
- An inner `@given` function called from a plain test. The plain test fills a
  local `collections.Counter` and then asserts that every class was reached.
  This works under `pytest-xdist`.
- Seeded faults that the check must reject.

`hypothesis.event()` is used only as diagnostics, through
`--hypothesis-show-statistics`.

### Axioms

These are trusted, not verified.

- **AXM-1: LangGraph `StateGraph` runtime behaviour.** This holds provided
  the graph uses no `step_timeout`, no subgraphs, no `stream_eager`, and no
  `messages` or `custom` stream mode (`langgraph/pregel/_runner.py:392`,
  `main.py:3395-3400`):
  - Explicit `path_map` conditional edges call the router with the post-node
    state and follow only the mapped targets.
  - Nodes run sequentially in one task per run, but **not inline in the
    caller's task**: `langchain_core.runnables.utils.coro_with_context`
    always wraps a node call in `asyncio.create_task`, even on the runner's
    single-task fast path (verified against the pinned LangGraph 1.2.11 and
    its langchain-core).
  - `context=` delivers the runtime context to `Runtime[...]` node
    parameters.
  - Exceptions raised in a node propagate unwrapped.

  The LangGraph Graph API documentation and the planning probes support the
  remaining points. D16 compensates for the child-task behaviour so INV-9's
  task attribution and shutdown safety still hold.
- **AXM-2: graph introspection.** `CompiledStateGraph.get_graph()` reports
  the declared edges. With a `path_map`, its conditional edges list exactly the
  mapped targets (LangGraph reference for `add_conditional_edges`, and the
  probe).
- **AXM-3: PostgreSQL enum labels.** `ALTER TYPE … ADD VALUE IF NOT EXISTS`
  appends a label. The label cannot be used inside the same transaction, and
  labels cannot be dropped without recreating the type (PostgreSQL 18 manual,
  `ALTER TYPE` notes).
- **AXM-4: py-pglite fidelity.** py-pglite implements these PostgreSQL enum
  semantics faithfully.
- **AXM-5: tool fidelity.** Hypothesis generates and shrinks examples as
  documented, and Vidai Mock returns its configured responses wire-accurately.
- **AXM-6: asyncio cancellation.** asyncio delivers `CancelledError` at the
  awaiting point of a cancelled task. `Task.cancelling()` is positive during
  external cancellation. `asyncio.shield` protects the inner write.

### Obligations

- **INV-0: no-QA characterization.**
  - Statement: before any refactor, the current code's observable no-QA
    behaviour is captured. The capture records the full event list (kind and
    payload), the final run row, every metrics call (name, labels, value),
    and the span attributes, for each of these cases:
    - success;
    - provider failure;
    - invalid TEI;
    - source limit;
    - missing episode;
    - generator self-raising `CancelledError`;
    - cancel during generation via `shutdown()`.
  - Method: syrupy snapshot characterization. Identifiers and timestamps are
    normalized through the existing `tests/snapshot_redaction.py`.
  - Artefact: `tests/test_generation_run_launcher_no_qa_characterization.py`
    and its `.ambr`.
  - Evidence: green on the unmodified code at EP-M0, committed before any
    production change.
  - Non-vacuity: each case also asserts its terminal kind outside the
    snapshot, so an empty or truncated recording fails.
- **INV-1: quality-metadata validity.**
  - Statement: `GenerationRun(...)` constructs if and only if
    `(quality_mode, status, qa_status, skip_qa_rationale)` satisfies the D5
    policy.
  - Method: an exhaustive parameterized test over the finite product, checked
    against a literal truth table in the test module rather than a
    re-implemented oracle. The product is 2 modes × 6 statuses × 5 QA-status
    values (the 4 `QaStatus` values plus `None`) × 3 rationale classes
    (`None`, blank, non-blank), which is 180 cells. A small Hypothesis
    property covers the text dimension: whitespace-only versus
    non-whitespace rationales.
  - Artefact: `tests/test_generation_quality_policy.py`.
  - Evidence: red before EP-M1, because `qa_gated` cannot be constructed;
    green after.
  - Non-vacuity:
    - A pre-check asserts that the table has accept and reject cells for each
      mode.
    - Seeded mutation: deleting the "rationale forbidden for `qa_gated`" rule
      must fail named rows. Measured: with the rule removed,
      `tests/test_generation_quality_policy.py` reports 22 failed and 165
      passed, every failure a `qa_gated` cell with `DID NOT RAISE ValueError`;
      restoring the rule returns 187 passed. The seeded list in
      `Artefacts and notes` records the same result.
- **INV-2: a QA-gated run succeeds if and only if QA passed, and the stores
  enforce it.**
  - Statement:
    - For `qa_gated`, `status` is `succeeded` if and only if `qa_status` is
      `passed`.
    - For `draft_without_qa`, `qa_status` is always `skipped`.
    - Both store adapters reject a violating `GenerationRunStatusUpdate` with
      `ValueError`, after the not-found and already-terminal checks.
    - A late failure write against a terminal run raises
      `RunAlreadyTerminal`.
  - Method:
    - a Hypothesis property over (initial run, update) pairs, run against the
      in-memory adapter through the existing port-contract harness;
    - a fixed witness table against the SQL adapter on py-pglite (the
      existing SQL property contract uses `max_examples=6`, which is too few
      to cover the classes);
    - a named contract test for "cancel after a QA-passed terminal".
  - Artefacts:
    - `tests/test_generation_run_port_contract.py` (extended);
    - `tests/canonical_storage/test_generation_run_quality_updates.py` (new);
    - `tests/test_generation_run_status_update_policy.py` (for
      `apply_status_update`).
  - Non-vacuity:
    - `@example`s cover accept and reject for each terminal status and both
      modes.
    - Negative control: a test-local `apply_status_update` that skips quality
      validation must fail the property.
    - There is no SQL "row unchanged" control. A rejection rolls the unit of
      work back, so such a control cannot distinguish behaviours.
- **INV-3: routing is total and injective.**
  - Statement:
    - `route_quality_mode` is total and maps distinct modes to distinct
      branches.
    - `branch_for_terminal` is total.
    - Every branch owns at least one terminal.
    - The node ownership table assigns every graph node except `initialize`
      to exactly one branch.
  - Method: an exhaustive parameterized test, plus static exhaustiveness
    through `match` and `typ.assert_never`, which pyright checks.
  - Artefact: `tests/test_generation_routing_policy.py`.
  - Non-vacuity: the injectivity assertion fails if both modes map to one
    branch.
- **INV-4: verdict aggregation.**
  - Statement:
    - `aggregate_verdicts(vs)` is `passed` if and only if `vs` is non-empty
      and every element is `passed`.
    - It is `failed` if any element is `failed`.
    - Otherwise it is `inconclusive`.
    - The result is invariant under permutation and duplication.
  - Method: Hypothesis over `lists(sampled_from(QualityVerdict))`, with a
    literal-rule oracle and metamorphic relations.
  - Artefact: `tests/test_generation_routing_policy.py`.
  - Non-vacuity:
    - `@example([])`, `@example([PASSED])`, `@example([PASSED, FAILED])` and
      `@example([PASSED, INCONCLUSIVE])`.
    - Negative control: an "any passes" implementation must fail.
- **INV-5: branch ownership holds at runtime, deterministically.** (The
  first draft's separate INV-6, determinism, is folded into this obligation.)
  - Statement. A generated run state consists of:
    - a quality mode;
    - an evaluator set, possibly empty, in which each evaluator returns a
      verdict, raises, times out, or self-raises `CancelledError`;
    - an optional fault injected at one of `initialize`, `generate`,
      `begin_evaluation`, `complete_with_draft` or `escalate`.

    Invoke `LangGraphContentGenerationGraph.run()` on that state with a
    recording fake `ContentGenerationSteps`. The result must take one of two
    forms.

    In the first form, the runner returns exactly one `GenerationTerminal`,
    and all of the following hold:
    - Every visited node is in `{initialize} ∪ owned_nodes(branch(mode))`.
    - `branch_for_terminal(terminal) == route_quality_mode(mode)`.
    - A `draft_without_qa` run never calls `begin_evaluation`, any
      evaluator, or `escalate`.
    - A `qa_gated` run calls `complete_with_draft` only after a `passed`
      aggregate, and only with `qa_status=PASSED`.
    - A `draft_without_qa` run calls `complete_with_draft` only with
      `qa_status=SKIPPED`.

    In the second form, the runner propagates the injected fault, or
    `QualityEvaluationUnavailableError` for a `qa_gated` run with an empty
    evaluator set, and no terminal step is recorded after the fault.

    Finally, a second invocation with the same input yields an identical
    step-call log and the same terminal.
  - Method: a Hypothesis property driving the production runner. The trace
    comes from the fake's step-call log, plus an `astream` side channel for
    the node names.
  - Artefacts: `tests/test_content_generation_graph_properties.py`, with
    fakes in `tests/_content_graph_fakes.py`.
  - Non-vacuity:
    - `@example`s cover each class:
      - no-QA persisted;
      - QA passed;
      - QA escalated after a failed verdict;
      - QA escalated after an inconclusive verdict;
      - QA escalated after an evaluator timeout;
      - QA unavailable;
      - a fault at each injection point.
    - A plain test runs the inner `@given` function with a local `Counter`
      and asserts that every class was reached.
    - The checker `assert_branch_ownership(trace, mode)` is tested against
      hand-built bad traces and must reject both: a no-QA trace that visits
      `evaluate`, and a QA trace that ends in `persist_draft_without_qa`.
    - Seeded fault: the test builds a graph from the same public node
      functions with swapped `path_map` targets, and the property must fail.
      Production code has no test-only parameter.
- **INV-7: static topology.**
  - Statement: in `compiled.get_graph()`, all of the following hold:
    - The nodes reachable from `generate_draft_without_qa` and from
      `generate_qa_candidate` are disjoint apart from `__end__`.
    - `initialize` is the only node with edges into both branches.
    - Every terminal node has exactly one outgoing edge, to `__end__`.
    - The targets of every conditional edge equal its declared `path_map`
      values.
    - `__start__` reaches every node.
  - Method: a structural unit test, plus a syrupy snapshot of
    `draw_mermaid()` as a review aid.
  - Artefacts: `tests/test_content_generation_graph_topology.py` and its
    `.ambr`.
  - Non-vacuity: the reachability helper is tested on a hand-built graph that
    has a shared node, and it must report the overlap. A focused test pins
    AXM-2.
- **INV-8: no-QA behaviour is preserved.**
  - Statement: INV-0's snapshots and every existing no-QA test pass after
    EP-M2, EP-M4 and EP-M5, apart from the two span attributes D15 records.
  - Method: regression against EP-M0.
  - Evidence: over
    `tests/features/no_qa_generation_slice.feature` and
    `tests/__snapshots__/test_generation_run_launcher_no_qa_characterization.ambr`
    since `d6876cba`, the feature file is unchanged and the snapshot differs
    by exactly the two D9 span attributes plus the D15 record.
  - Amendment (D15): the original statement required the snapshot to be
    unmodified, which the two added span attributes in the same INV-0 snapshot
    contradict. D15 records the deviation and this bullet carries it; the
    feature file itself remains byte-identical.
  - Non-vacuity: INV-0's own assertions.
- **INV-9: one writer per run, with ordered publication.**
  - Statement: the valid mode × outcome cells are:
    - `draft_without_qa`: succeeded, generator failure, cancelled.
    - `qa_gated`: passed, escalated (failed), escalated (inconclusive),
      evaluator error, unavailable, generator failure, cancelled.

    For every cell, all of the following hold:
    - `seq` is strictly increasing.
    - There is exactly one terminal event, and it is the last event.
    - Every `append_event` happens on the task named
      `generation-run-{run_id}`.
    - Escalated runs have provider-call cost rows.
    - `generation_run_draft_errors_total` is not incremented for
      escalations.
  - Method: a parameterized launcher test over the valid cells against
    py-pglite. A `uow_factory` wrapper asserts the task name inside
    `append_event`. The competing-writer precondition (a second connection
    claiming the same run while the first transaction is open) cannot be
    expressed on py-pglite: it serves one connection at a time, and a second
    session fails to connect even while the first is idle (measured
    `psycopg.errors.ConnectionTimeout` after the harness's connect timeout).
    It is covered two ways:
    - `tests/canonical_storage/test_generation_run_claim_concurrency.py`
      runs the real race against a PostgreSQL server when
      `EPISODIC_TEST_POSTGRES_DSN` names a disposable server whose base
      database ends in `_test`, and skips otherwise. The support module
      `tests/canonical_storage/_postgres_claim_race_support.py` gives every
      fixture invocation its own
      `<database>_w<worker>_<pid>_<nonce>` database, so independent runs and
      parallel xdist workers cannot collide, and it never drops a pre-existing
      database: a collision fails the test. The name is truncated by UTF-8
      bytes so the suffix survives a multibyte base name. Every server-backed
      test goes through the `require_dsn` guard, which fails a base database
      without the `_test` suffix. Unit tests cover the naming, multibyte
      truncation and guard rejection; server-backed tests prove a repeated
      create is refused while the existing database survives, and that two
      concurrent invocations own distinct databases through their teardown.
      Each test starts the competing claim and
      then polls `pg_stat_activity` until a backend reports a lock wait, so
      the release is synchronized on the database rather than a sleep.
      Measured against PostgreSQL 17.11:
      - an open claim transaction blocks the competitor, which loses after
        the claim commits (`claim_token` stays the winner's proof) and wins
        after the claim rolls back;
      - a failure write that holds its transaction blocks the competitor,
        which is refused with `RunAlreadyTerminal` after the failure
        commits, with `run.failed` the only event and the failure's proof
        still durable.
    - Launcher-level faults cover the same race without a second connection:
      `tests/test_generation_run_launcher_quality_ownership.py` (the
      `claim-exit` fault matrix and refused cancellation),
      `tests/test_generation_run_launcher_claim_reconciliation.py` (lost
      acknowledgement, same-unit-of-work authority and append, proof
      mismatch) and
      `tests/test_generation_run_launcher_claim_cancellation.py`
      (cancellation of the claim task during shielded reconciliation,
      blocked reconciliation, the bounded stalled reconciliation, and a
      stalled cancellation write that shutdown abandons).
  - Artefact: `tests/test_generation_run_launcher_quality_modes.py`.
  - Non-vacuity:
    - Each cell asserts its specific terminal kind and category.
    - The task-name wrapper is checked against a deliberate append from a
      different task, which it must reject.
- **INV-10: cancellation in the QA branch is shutdown-safe.**
  - Statement: a `qa_gated` run can be cancelled at three points:
    - while an evaluator is awaiting;
    - inside the passing terminal unit of work, using a blocking fake cost
      recorder (which is called inside that transaction);
    - inside the escalation unit of work.

    In every case exactly one terminal event is recorded.
    - If the terminal had not committed, the run ends `failed` with
      `launcher.shutdown`, `qa_status` stays `pending`, there is no
      `tei.persisted`, and the episode TEI revision is unchanged.
    - If the terminal had already committed, the committed terminal stands
      and `RunAlreadyTerminal` is swallowed.
  - Method: concrete interleaving tests with fakes gated on `asyncio.Event`,
    plus `launcher.shutdown()`.
  - Artefact: `tests/test_generation_run_launcher_quality_modes.py`.
  - Non-vacuity: each test asserts that the blocking point was entered before
    shutdown.
- **INV-11: migration label parity.**
  - Statement:
    - After the upgrade, the `pg_enum` labels for `quality_mode` and
      `qa_status` equal the Python enum values.
    - A `qa_gated` row can be inserted after the upgrade transaction commits.
    - Downgrade raises `alembic.util.CommandError` when rows use the new
      labels, and recreates the original types when no rows do.
    - Offline (`--sql`) mode emits a `DO $$` guard, as `20261010_000013`
      does.
  - Method: py-pglite migration tests following
    `tests/test_pricing_snapshot_constraint_migration.py`:
    1. downgrade to `20261110_000017` and commit;
    2. upgrade to head and commit;
    3. insert a row and read it back.
  - Artefact: `tests/test_qa_gated_quality_mode_migration.py`. The offline
    guard is exercised through Alembic itself, not a helper call:
    `command.downgrade(config, "20261123_000019:20261110_000017", sql=True)`
    with `capsys` compared to a syrupy snapshot of the emitted SQL.
  - Non-vacuity: the parity check first runs at `20261110_000017`, where it
    must report the missing labels.
- **INV-12: the REST capability gate, and its ordering.**
  - Statement, over accepted set × mode × rationale-present × replay:
    - `qa_gated` returns `202` if and only if the mode is accepted and no
      rationale is sent.
    - An accepted `qa_gated` with a rationale returns `400` with constraint
      `exclusive_with_quality_mode`.
    - An unaccepted `qa_gated` returns the unchanged `422`, with or without a
      rationale.
    - An unknown mode stays `400` with constraint `enum`.
    - Replaying an accepted request after the accepted set shrinks returns
      the stored `202`.
    - An error raised inside `work()` releases the key, so a corrected retry
      with the same key succeeds.
  - Method: a parameterized Falcon test, plus syrupy snapshots of the new
    error envelopes.
  - Artefacts: `tests/test_generation_run_api_quality_modes.py` and its
    `.ambr`, plus `tests/test_generation_run_api_quality_precedence.py` and
    its `.ambr`, which snapshots the error envelopes for the no-launcher,
    accepted-gated-rationale and unknown-mode cases against the same request
    bodies the precedence table uses.
- **INV-13: TEI provenance.**
  - Statement:
    - The envelope's `quality_mode` equals the producing run's
      `quality_mode`.
    - Its `qa_status` is `skipped` for no-QA runs and `passed` for gated
      runs.
    - `EpisodeTeiUpdate` rejects `pending` and `failed`.
  - Method: an exhaustive parameterized test over `QaStatus` for
    `EpisodeTeiUpdate`, plus an API test per mode.
  - Artefacts: `tests/test_generation_routing_policy.py` and
    `tests/test_episode_tei_api.py` (extended).

### Residual gaps

- These belong to roadmap items 4.4.2 to 4.4.4: parallel evaluator execution,
  real evaluators, iteration caps, `recursion_limit` sizing, and resume replay.
- The candidate draft lives only in the session's memory. 4.4.4 needs a
  durable draft artefact for escalation review and for resume. It must also
  choose between a LangGraph checkpointer and event replay. The runtime context
  is not serialized, which is fine either way.
- No lease renewal happens at `evaluate`. 2.6.2 must not reclaim on a stale
  lease while `current_node="evaluate"`.
- INV-5 uses fake step ports, and INV-9 and INV-10 cover the real launcher.
  Interleavings across process restarts belong to 2.6.2.
- `accepted_quality_modes` always contains `draft_without_qa`, so a
  deployment policy that forbids it is not supported. Revisit this with the
  approval workflow (4.2.x).
- A later Unit Architecture pass required three more separations, now made.
  `read_owned_episode_and_run`'s test wraps both repositories in a proxy that
  records every call that is not a `get*` read, and asserts the session has no
  `new`, `dirty` or `deleted` instances. The cancellation-write bookkeeping,
  its deadline and its timeout counter moved out of the scheduler into
  `episodic/generation/launcher_cancellation_writes.CancellationWrites`, which
  the scheduler delegates to (the scheduler also exposes read-only properties
  with the old attribute names, so the tests that inspect them still work). The
  QA-bypass counter moved from the claimer to the per-run session's
  `initialize`, where per-run observations belong. Two negative controls guard
  the recording boundary: one writes through a wrapped repository and requires
  the proxy to record it, and one stages a valid row and flushes it from inside
  a delegated read, which the unit of work's `before_flush` listener must
  record even though the session's collections are empty afterwards. Both fail
  when their instrumentation is removed.
- The Unit Architecture row's five items were implemented at `HEAD` as
  follows. `_LauncherRunSession.begin_evaluation` now calls
  `GenerationRunPersistence.record_evaluation_started`, so every run-state
  write goes through one persistence path. Metrics and logging moved out of the
  failure component into the module-level `record_failure_observation`, which
  runs only after the commit. `GenerationRunsResource._submit` validates a
  request once per submission: its memoized `validate()` serves the work
  directly and the keyed-conflict precondition reuses the same prepared result,
  so no path applies the rules twice. `read_owned_episode_and_run` has a
  recording-unit-of-work test that fails on any write, flush, commit or
  rollback. The claimer, persistence and failure components are composed once in
  `__post_init__`. Draft-cost recording stays inside the failure transaction,
  deliberately: those rows must commit with the terminal state they document,
  or an escalation would be recorded without the inference it consumed.
- Two further Unit Architecture suggestions were assessed and declined, with
  reasons recorded rather than left unaddressed:
  - **Splitting `launcher_scheduling.py`.** At 384 lines it is under the
    400-line limit and its admission, drain and cancellation logic shares the
    same registries. The split the review proposed would also rename the
    internal sets that `test_generation_run_launcher_claim_cancellation` and
    `test_generation_run_launcher_claim_reconciliation` inspect to prove the
    single-writer rule, so it would reduce test strength for no behavioural
    gain. The cancellation-write logic already lives behind one method
    (`record_cancellation_owned`), which is the seam a future split would use.
- The remaining Domain Architecture item — `apply_status_update` importing its
  `GenerationRunStatusUpdate` DTO from the ports module — is recorded rather
  than changed. Moving the DTO into `domain_generation` was attempted and
  reverted: `domain_validation` imports `GenerationRunStatus` only under
  `TYPE_CHECKING`, so the dataclass fails at class-creation time under PEP 649
  when the module is imported before `domain_enums`. `generation_run_ports`
  imports `GenerationRunStatus` under `TYPE_CHECKING` as well, so the move
  would have to relocate the enum, which is a wider refactor than the finding
  asks for. The domain module's dependency on the DTO is therefore a type-level
  coupling to a frozen dataclass of domain-shaped fields, not hidden state. The
  graph nodes' `asyncio.current_task().cancelling()` check stays as well: AXM-6
  records the asyncio cancellation semantics it relies on, and the runner
  translates LangGraph's `NodeCancelledError`. The check is what distinguishes
  an external cancellation from an evaluator-raised `CancelledError`, and the
  node module is otherwise framework-free.
- The two CodeRabbit pre-merge rows are accepted and implemented, not deferred.
- **Store-level token gate (Domain Architecture).** Every terminal write names
  the claim that owns the run. `GenerationRunStatusUpdate` carries an optional
  `claim_token`; both store adapters compare it with the stored value inside
  the same locked transaction and raise `RunClaimMismatch` on an absent or
  different token. A run with no stored claim — a launch failure before any
  claim, or a reclamation candidate — has no owner to check, so an internal
  path may still terminate it. Tests:
  `test_a_terminal_write_requires_the_ matching_claim` (missing and wrong
  tokens rejected, correct token accepted) and
  `test_an_unclaimed_run_needs_no_token`. `ClaimToken` now carries the
  per-attempt `proof`, which is the value the store compares.
- **Unit Architecture structural items.**
  1. Claim reconciliation has its own `reconcile_timeout_seconds`; it no longer
     borrows the cancellation-write deadline.
  2. The source-document loader is an injectable launcher dependency
     (`source_document_loader`), used when supplied; the module-level seam is
     only the default, because existing tests replace it.
  3. Each runtime view is typed against a narrow per-stage Protocol
     (`_SchedulerHost`, `_ClaimerHost`, `_PersistenceHost`, `_SourceLoadHost`)
     rather than the whole launcher, so a stage's dependency is explicit in
     the type while reads still go through the host at use time, which keeps
     the live-replacement contract.
  4. `_claim_and_start` returns a `ClaimedRunResult` carrying the token;
     `ClaimedRun` also carries it, so the success and failure paths name their
     authority instead of relying on hidden state. The one documented
     exception is the cancelled-commit path, which cannot return a value and
     therefore still adopts the token in place.
  5. `GenerationRunFailurePersistence.record_failure` is split into
     authority-plus-transaction (`_write_failure`) and post-commit
     observation (`_observe_written_failure`).

## Plan of work

- **Stage A: understand and propose.** This document. It completes once the
  user approves it.
- **Stage B: red.** Each milestone opens with failing tests, marked
  `@pytest.mark.xfail(strict=True, reason="4.4.1 red: ...")` until the red
  failure has been observed for the intended reason. The green step removes the
  marker. EP-M0 is the exception: it is green by construction.
- **Stage C: green.** Make the smallest production change that turns each
  red test green, building fakes and truth tables alongside.
- **Stage D: refactor and document.** Clean up, run all gates, and update
  the documentation.

### EP-M0: no-QA characterization baseline

1. Add `tests/test_generation_run_launcher_no_qa_characterization.py`
   recording INV-0's cases. Use the doubles in
   `tests/generation_run_launcher_support.py`: a recording metrics port, a
   recording tracer, and a generator that raises `CancelledError`. Add any of
   these that are missing.
2. Generate the snapshot on the unmodified code and commit it on its own.

### EP-M1: domain quality policy and validation

Under D14, items 4 and 5 of the original plan (the pure routing policy and the
graph ports) move to EP-M3, and `apply_status_update` moves to EP-M2, so every
new symbol lands with a production caller.

Red tests:

- `tests/test_generation_quality_policy.py` (INV-1, and the
  `EpisodeTeiUpdate` part of INV-13).
- `tests/test_generation_routing_policy.py` (INV-3 and INV-4), which lands in
  EP-M3 with the graph.
- New `qa_gated` rows in `tests/test_generation_run_qa_lifecycle.py`.

Production changes:

1. **`episodic/canonical/generation_quality.py`.**
   - Add `QualityMode.QA_GATED = "qa_gated"`, plus `QaStatus.PENDING`,
     `PASSED` and `FAILED`.
   - Add the pure query `quality_metadata_violation(*, quality_mode, status,
     qa_status, skip_qa_rationale) -> str | None`. Write it as a `match` on
     `quality_mode` that ends in `typ.assert_never`.
   - Import `GenerationRunStatus` from `domain_enums`, which is a leaf
     module.
   - Keep the existing `draft_without_qa` messages verbatim: "qa_status must
     be skipped for draft_without_qa runs." and "skip_qa_rationale must be a
     non-empty string."
2. **`episodic/canonical/domain_validation.py`.** Replace
   `_validate_draft_without_qa_metadata` with `_validate_quality_metadata`,
   which raises `ValueError(message)`.
3. **`episodic/canonical/domain_generation.py`.**
   - Pass `status` to the validator.
   - Keep the defaults `quality_mode=DRAFT_WITHOUT_QA` and
     `qa_status=None`.
   - `apply_status_update` moves to EP-M2 under D14.
4. **`episodic/canonical/domain_episodes.py`.** `EpisodeTeiUpdate` rejects any
   `qa_status` other than `skipped` or `passed` (moved here from EP-M2 under
   D14 so the INV-13 test is green in this milestone).
5. **ADR 0029.** Write
   `docs/adrs/adr-0029-qa-gated-mode-branching-and-content-generation-graph.md`
   with status `Proposed`, recording D1 to D12.

### EP-M2: persistence, migration and lifecycle updates

Red tests:

- INV-11.
- INV-2: the port contract, the SQL witness table, and the status-update
  policy.
- A test that `persist_draft_script` writes the supplied `qa_status`.
- A test that `EpisodeTeiUpdate` rejects the new non-persistable statuses.

Production changes:

1. **New migration
   `alembic/versions/20261122_000018_add_qa_gated_quality_mode.py`**, with
   `down_revision="20261110_000017"`.
   - Upgrade: `ALTER TYPE quality_mode ADD VALUE IF NOT EXISTS 'qa_gated'`,
     then the same statement on `qa_status` for `pending`, `passed` and
     `failed`.
   - Downgrade:
     1. If any `generation_runs.quality_mode`, `generation_runs.qa_status` or
        `episodes.qa_status` uses a new label, raise `CommandError` when
        online. When offline, emit an equivalent `DO $$` guard instead.
     2. Rename each type to `*_old`.
     3. Create the original single-label type.
     4. Run `ALTER COLUMN ... TYPE ... USING col::text::<type>`.
     5. Drop `*_old`.
   - Do not touch the ORM.
2. **`episodic/canonical/generation_run_ports.py`.** Add
   `qa_status: QaStatus | Unchanged = UNCHANGED` to
   `GenerationRunStatusUpdate`. Document the contrast with the error fields,
   where an omitted value clears the field.
3. **Both store adapters.** `update_run_status` first checks not-found and
   already-terminal (`_require_mutable_run`). It then calls
   `apply_status_update` on the current domain run, and writes the resolved
   fields only if that call succeeds. This keeps both files under 400 lines.
4. **`episodic/canonical/domain_episodes.py`.** `EpisodeTeiUpdate.__post_init__`
   rejects any `qa_status` other than `SKIPPED` or `PASSED`.
5. **`episodic/canonical/generation_persistence.py`.** Add
   `qa_status: QaStatus` to `DraftScriptPersistenceRequest`, and make
   `persist_draft_script` write it. The only existing caller passes `SKIPPED`.
6. **`episodic/api/serializers.py` and
   `episodic/api/resources/episode_tei.py`.** Change the signature to
   `serialize_tei_envelope(episode, *, quality_mode)` and pass the producing
   run's mode. For no-QA episodes this is still `draft_without_qa`, so the
   bytes are unchanged.

### EP-M3: content-generation graph in orchestration

Red tests:

- INV-5.
- INV-7, including the AXM-2 pin.
- The extended `EXPECTED_PRODUCTION_ORCHESTRATION_GROUPS` mapping in
  `tests/test_production_hecate_orchestration_config.py`.

Production changes:

1. **New `episodic/orchestration/_content_graph_state.py`**
   (`orchestration_nodes`), containing:
   - `ContentGenerationGraphState`, a `@dc.dataclass(slots=True)` with these
     fields:
     - `request`;
     - `verdict: QualityVerdict | None = None`;
     - `evaluations: tuple[QualityEvaluation, ...] = ()`;
     - `terminal: GenerationTerminal | None = None`.
   - `ContentGenerationContext`, a frozen dataclass holding `steps` and
     `evaluator_set`.
   - The node ownership table `NODE_OWNERSHIP: Mapping[str, QualityBranch |
     None]`, where `None` means shared. Only `initialize` is shared.
2. **New `episodic/orchestration/_content_graph_nodes.py`**
   (`orchestration_nodes`). This holds plain async functions with the signature
   `(state, context)`. They import no `langgraph` and return state deltas.
   - `initialize`: if the mode is `qa_gated` and the evaluator set is empty,
     raise `QualityEvaluationUnavailableError`. Otherwise call
     `steps.initialize()`.
   - `generate_draft_without_qa` and `generate_qa_candidate`: each calls
     `steps.generate_draft()`.
   - `evaluate`, in order:
     1. Call `steps.begin_evaluation(names)` and take
        `steps.evaluation_subject()`.
     2. Await each evaluator under `asyncio.timeout`, mapping errors as D8
        describes.
     3. Aggregate the results.
     4. Return `{"verdict": ..., "evaluations": ...}`.
   - `persist_draft_without_qa`: calls `steps.complete_with_draft(SKIPPED,
     ())`.
   - `persist_qa_passed_draft`: calls `steps.complete_with_draft(PASSED,
     evaluations)`.
   - `escalate`: calls `steps.escalate(verdict, evaluations)`.
   - Each terminal node returns `{"terminal": ...}`.
   - The routers `route_after_initialize` and `route_after_evaluate`
     delegate to the domain policy.
3. **New `episodic/orchestration/content_generation.py`** (`orchestration`).
   - `build_content_generation_graph()`:
     - registers nodes by iterating the ownership table;
     - wraps each node in a closure
       `async def _n(state, runtime: Runtime[ContentGenerationContext])`;
     - builds
       `StateGraph(ContentGenerationGraphState, context_schema=ContentGenerationContext)`
       with explicit `path_map` conditional edges.
   - `LangGraphContentGenerationGraph`:
     - compiles the graph once and holds a `QualityEvaluatorSet`;
     - `accepted_quality_modes()` delegates to the set;
     - `run()` calls `ainvoke(..., context=...)`, reads
       `result["terminal"]`, and checks
       `branch_for_terminal(terminal) == route_quality_mode(mode)`;
     - it translates `NodeCancelledError` and raises
       `ContentGenerationGraphError` as D12 describes.
4. **`pyproject.toml` and the Hecate test.**
   - Add the two private modules to the `orchestration_nodes` prefixes.
   - Update `EXPECTED_PRODUCTION_ORCHESTRATION_GROUPS` with all three new
     modules.
   - Re-export `LangGraphContentGenerationGraph` and
     `build_content_generation_graph` from
     `episodic/orchestration/__init__.py`, following its existing style.

### EP-M4: launcher executes runs through the graph

Red tests:

- `tests/test_generation_run_launcher_quality_modes.py` (INV-9 and INV-10).
- The existing launcher tests change only in how they construct the launcher.

Production changes:

1. **`episodic/generation/launcher_claim.py`.**
   - Extract the claim-and-hydrate path (`_claim_and_hydrate` in this
     branch, later `GenerationRunClaimer.claim`) from the claim step.
   - Delete `_claim` and `LauncherHost._claim`.
   - Keep the qa-bypass increment at the end of the hydration step, after
     `_load_sources`, guarded by
     `run.quality_mode is QualityMode.DRAFT_WITHOUT_QA`.
2. **New `episodic/generation/launcher_session.py`** (`application`).
   `_LauncherRunSession` is a slotted dataclass that implements
   `ContentGenerationSteps` structurally:
   - `initialize()` calls the claim-and-hydrate step.
   - `generate_draft()` calls `_generate` and `_record_draft_generated`, then
     validates the TEI header (D11).
   - `begin_evaluation(names)` appends `qa.evaluation_started` and updates
     `current_node="evaluate"` in one unit of work.
   - `evaluation_subject()` builds the subject from the draft.
   - `complete_with_draft(qa_status, evaluations)` calls `_persist_success`
     with both arguments.
   - `escalate(verdict, evaluations)` calls `_record_failure(run_id,
     Failure.escalation(…), draft=self.draft)` (D10).
   - The session records `generation_run_qa_gate_total{verdict}` and
     `generation_run_qa_evaluator_errors_total{evaluator}`.
   - Keep the metric names and payload builders in a small new
     `launcher_quality.py` module of plain functions, not a mixin.
3. **`episodic/generation/launcher_persistence.py`.**
   - `_persist_success` and `_record_success_transition` take `qa_status`
     and `evaluations`.
   - For gated runs, append `qa.result` first.
   - Put `qa_status` in the `tei.persisted` payload.
   - In the SUCCEEDED `GenerationRunStatusUpdate`, pass `qa_status=PASSED`
     for gated runs and `UNCHANGED` for no-QA runs, so the no-QA update is
     identical.
   - Extend `_record_failure` and `_append_failure_events` as D10 describes.
4. **`episodic/generation/launcher_support_events.py`.**
   - Extend `Failure` as D10 describes.
   - Add `QualityEvaluationUnavailableError → "qa.unavailable"` and
     `ContentGenerationGraphError → "orchestration.incomplete"` to
     `_FAILURE_CATEGORIES`.
5. **`episodic/generation/launcher_scheduling.py`.** `_execute_run` does the
   following:
   1. Claims the run.
   2. Calls `self.content_graph.run(...)` with a fresh session.
   3. Logs the branch, and sets the span attributes `quality_branch` and
      `terminal`.
   4. Returns `_ExecutionOutcome(outcome="completed")` for succeeded
      terminals, or `"escalated"` for `QA_ESCALATED`.

   The exception and cancellation handling is unchanged.
6. **`episodic/generation/launcher.py` and `launcher_host.py`.**
   - Add the required field `content_graph: ContentGenerationGraphPort`, and
     update the protocol surface.
   - Pass `LangGraphContentGenerationGraph(QualityEvaluatorSet(()))` in
     `tests/generation_run_launcher_support.py`,
     `tests/test_generation_source_limits.py` and
     `tests/steps/no_qa_generation_slice_support.py`.

### EP-M5: REST and composition-root acceptance of `qa_gated`

Red tests:

- `tests/test_generation_run_api_quality_modes.py` and its snapshots
  (INV-12).
- `tests/features/qa_gated_generation_routing.feature`, with
  `tests/steps/test_qa_gated_generation_routing.py`.
- The existing 422 BDD scenario and API assertion stay exactly where they
  are, unchanged.

Production and test-support changes:

1. **`episodic/api/dependencies.py`.** Add
   `accepted_quality_modes: frozenset[QualityMode]`, defaulting to
   `frozenset({QualityMode.DRAFT_WITHOUT_QA})`. Validate that it contains
   `DRAFT_WITHOUT_QA`.
2. **`episodic/api/app.py`.** Pass the new field to `GenerationRunsResource`.
   If the constructor's argument count exceeds the existing
   `too-many-arguments` suppression, group `launcher`, `max_source_count` and
   `accepted_quality_modes` into a small `GenerationRunPolicy` value object.
3. **`episodic/api/resources/generation_runs_create_support.py` and
   `generation_runs.py`.**
   - The parser keeps the enum rule and the no-QA rationale rule, and returns
     the parsed mode.
   - Inside `work()`, run the capability check (422) and then the
     gated-rationale check (400).
   - `_create_run` sets `qa_status=PENDING` and no rationale for `qa_gated`.
     The no-QA path is unchanged.
4. **`episodic/api/runtime.py`.**
   - Build one `QualityEvaluatorSet(())`. It is empty in 4.4.1; 4.4.2 appends
     Chrono.
   - Build `LangGraphContentGenerationGraph` from it, pass it to the
     launcher, and set
     `ApiDependencies.accepted_quality_modes=graph.accepted_quality_modes()`.
   - Add a runtime test asserting that the two agree.
5. **Test support.**
   - Extract the Background, poll and assertion steps from
     `tests/steps/test_no_qa_generation_slice.py` into
     `tests/steps/generation_slice_shared_steps.py`, and import them from
     both step modules.
   - The new "QA evaluation is configured" Given rebuilds the launcher and
     dependencies with `dc.replace`, binding a deterministic evaluator from
     `tests/_content_graph_fakes.py`.
   - The qa-gated When builds a body without `skip_qa_rationale`.
   - The no-QA feature file and its scenario behaviour are untouched.

### EP-M6: documentation, ADR acceptance and roadmap

1. **ADR 0029.**
   - Set the status to `Accepted (YYYY-MM-DD)` with a summary.
   - Reconcile it with what was built.
   - Link it from the design document's "Content Generation Graph" and
     "Source-to-script vertical slice" sections.
   - Add a "superseded in part by ADR 0029" note to ADR 0017's 422 rule.
2. **`docs/episodic-podcast-generation-system-design.md`.**
   - Update the graph prose and the Mermaid diagram for D3 and D4.
   - Keep the "For screen readers" description in step with the diagram.
   - Replace "Generation creation accepts only `draft_without_qa`" with the
     capability-gated rule.
3. **`docs/episodic-tui-api-design.md`.**
   - Document the `qa_gated` request rules and their ordering, the
     `qa_status` values, and the error codes.
   - Add `qa.evaluation_started` and `qa.escalated` to the event catalogue
     table, and refine `qa.result`.
   - Note that `paused` becomes reachable from 4.4.4.
4. **`docs/users-guide.md`.** Add a "QA-gated generation runs" subsection
   after the no-QA instructions. Cover:
   - when `qa_gated` is accepted;
   - that `skip_qa_rationale` is rejected;
   - how to read `qa_status`;
   - `qa.escalation_required`, and that the `qa.escalated` event is the
     stable signal;
   - the TEI envelope's `quality_mode`;
   - that `paused` will appear later.
5. **`docs/developers-guide.md`.** Add a "Content-generation graph and
   quality branch" section covering:
   - the ports and how the graph is injected;
   - the closure-wrapped node rule;
   - the ownership table;
   - the single-writer and no-open-unit-of-work rules;
   - how to add an evaluator: a stable slug name, under a timeout;
   - alerting on evaluator errors;
   - the Hypothesis conventions: `@example` witnesses, in-test `Counter`
     coverage, literal truth tables and seeded faults.

   Update "No-QA launcher and TEI retrieval" to match.
6. **`docs/contents.md`.** Index ADR 0029.
7. **`docs/roadmap.md`.** Mark 4.4.1 `[x]` with a one-line summary.
8. **Gates.** Run `make fmt`, `make markdownlint` and `make nixie`, then the
   full gates.

## Milestones and plateaus

- **EP-M0.**
  - Outcome: no-QA behaviour is pinned.
  - Acceptance: INV-0 is green on the unmodified code.
  - Conformance: no production change.
  - Recovery: drop the commit.
  - Compatibility: none.
- **EP-M1.**
  - Outcome: domain types represent and validate `qa_gated`, and the pure
    policy exists. No runtime path uses it yet, and REST still returns 422.
  - Requirements: RM-441-A (domain) and RM-441-D (policy).
  - Acceptance: INV-1, INV-3, INV-4 and INV-0 pass.
  - Conformance check:
    - D5 and D8 are followed.
    - No public interface change.
    - No persistence change.
    - Trace links are current.
  - Recovery: revert; nothing depends on this milestone yet.
  - Remaining gaps: persistence, graph, launcher, REST and documentation.
  - Compatibility: none.
- **EP-M2.**
  - Outcome: the database and adapters store the new labels and enforce
    INV-2. Persistence writes the supplied QA status, and the envelope uses
    the run's mode.
  - Requirements: RM-441-A (persistence).
  - Acceptance: INV-2, INV-11, INV-13, `make check-migrations` and INV-0 all
    pass.
  - Conformance: the additive migration is the only persisted-format change,
    and this plan approves it.
  - Recovery: run `alembic downgrade 20261110_000017` on a database without
    new-label rows, then revert.
  - Compatibility: deployed databases at `20261110_000017` upgrade in place.
    A code rollback is safe while no new-label rows exist.
- **EP-M3.**
  - Outcome: a compiled graph exists, with property-tested branch ownership.
    It has no production caller yet.
  - Requirements: RM-441-B, RM-441-C and RM-441-D at the graph level.
  - Acceptance: INV-5, INV-7 and Hecate pass.
  - Conformance check:
    - ADR 0022 is respected.
    - No `allowed` list changes.
    - No `langgraph` import in `orchestration_nodes`.
    - The only deviations from SD-CGG are D3 and D4.
  - Recovery: revert.
  - Compatibility: none.
- **EP-M4.**
  - Outcome: all runs execute through the graph, and no-QA behaviour is
    identical. `qa_gated` runs constructed in tests reach the passed,
    escalated and unavailable outcomes with the correct events, costs and
    metrics.
  - Requirements: RM-441-B, RM-441-C and RM-44-CONC.
  - Acceptance: INV-8, INV-9 and INV-10 pass.
  - Conformance check:
    - The single writer is preserved.
    - `launch` is unchanged.
    - `content_graph` is a new required internal field, and all four
      constructor call sites are updated in the same commit.
  - Recovery: revert the EP-M4 commits; EP-M1 to EP-M3 remain coherent.
  - Compatibility: none.
- **EP-M5.**
  - Outcome: clients can create `qa_gated` runs where evaluators are
    configured. Production keeps its 422.
  - Requirements: RM-441-A (creation) and RM-441-S.
  - Acceptance: INV-12, the new BDD feature, and the unchanged no-QA feature
    all pass.
  - Conformance: the REST shape is unchanged, and the new error details are
    documented.
  - Recovery: revert the EP-M5 commits.
  - Compatibility: existing `draft_without_qa` clients are unaffected.
- **EP-M6.**
  - Outcome: the documentation matches the behaviour, ADR 0029 is accepted,
    and the roadmap is marked done.
  - Acceptance: `make markdownlint`, `make nixie` and the full gates pass.
  - Conformance: every deviation is reconciled upstream.
  - Compatibility: none.

## Concrete steps

Run all commands from the repository root (the worktree). Capture gate output
with `tee` to `/tmp/$ACTION-episodic-4-4-1-qa-gated-mode-branching.out`. Run
gates sequentially, never in parallel. Prefer delegating full gate runs to the
`scrutineer` agent.

At each milestone, run. `set -o pipefail` is required: without it a pipeline
reports `tee`'s status, so a failing `make` would still record a passing gate.

```shell
set -o pipefail
make fmt
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-4-4-1-qa-gated-mode-branching.out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-4-4-1-qa-gated-mode-branching.out
make lint 2>&1 | tee /tmp/lint-episodic-4-4-1-qa-gated-mode-branching.out
make test 2>&1 | tee /tmp/test-episodic-4-4-1-qa-gated-mode-branching.out
```

For focused loops during development:

```shell
uv run pytest tests/test_generation_run_launcher_no_qa_characterization.py -q
uv run pytest tests/test_generation_quality_policy.py tests/test_generation_routing_policy.py -q
uv run pytest tests/test_content_generation_graph_properties.py -q --hypothesis-show-statistics
uv run pytest tests/test_qa_gated_quality_mode_migration.py -q
uv run pytest tests/steps/test_qa_gated_generation_routing.py -q
```

The expected red output at the start of EP-M1 is:

```plaintext
tests/test_generation_quality_policy.py::test_quality_metadata_policy[qa_gated-pending-pending-none] XFAIL
  (4.4.1 red: qa_gated unsupported)
```

The expected coverage assertion in INV-5, from the in-test `Counter`, is:

```plaintext
reached classes: no_qa_persisted, qa_passed, qa_escalated_failed, qa_escalated_inconclusive,
qa_escalated_timeout, qa_unavailable, fault@initialize, fault@generate, fault@begin_evaluation,
fault@complete_with_draft, fault@escalate
```

For the documentation milestone, run in the same shell session, so the
`pipefail` set above still applies:

```shell
set -o pipefail
make fmt
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-4-4-1-qa-gated-mode-branching.out
make nixie 2>&1 | tee /tmp/nixie-episodic-4-4-1-qa-gated-mode-branching.out
```

Run `make check-migrations` after EP-M2. Commit after each green step, and gate
each commit.

## Validation and acceptance

The BDD feature specification for EP-M5 is
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
    Then the response is 400 Bad Request with constraint "exclusive_with_quality_mode"

  Scenario: QA-gated runs are unprocessable when no evaluators are configured
    Given no QA evaluators are configured
    And an ingestion job with an attached source document
    When I create a qa-gated generation run for the ingested episode
    Then the response is 422 Unprocessable Entity

  Scenario: A draft-without-QA run still takes the direct route when evaluators exist
    Given QA evaluation is configured with a failing evaluator
    And an ingestion job with an attached source document
    When I create a draft-without-qa generation run for the ingested episode
    And I poll the generation run until it reaches a terminal state
    Then the run status is "succeeded" with qa_status "skipped"
    And the event log contains no "qa.evaluation_started" event
```

Vidai Mock serves the draft completion in every scenario, so the generator path
is real end to end. The evaluator is a deterministic in-process test double; no
inference is involved in evaluation until 4.4.2.

Quality criteria:

- **Tests.** `make test` passes. Each new test fails for the intended reason
  before its green step and passes afterwards. INV-0 and every 4.3.2 test pass
  without modification.
- **Verification.** INV-0 to INV-13 are discharged as described, with
  non-vacuity evidence recorded in `Artefacts and notes`.
- **Lint and type checks.** `make check-fmt`, `make typecheck` and
  `make lint` pass. The lint gate covers Hecate, Ruff, Pylint, df12, ambrleaks,
  Skylos and nose.
- **Documentation.** `make markdownlint` and `make nixie` pass.
- **Migrations.** `make check-migrations` passes.

## Idempotence and recovery

Every step is re-runnable.

- The migration uses `ADD VALUE IF NOT EXISTS`, and the downgrade refuses
  when it would lose data.
- The gates are read-only, apart from `make fmt`.
- If a milestone fails halfway, either reset to the last green commit with
  `git reset --hard <sha>` (after confirming `git status` holds nothing you
  want to keep), or fix forward within the milestone's iteration tolerance.
- Never regenerate the INV-0 snapshot to recover.

## Artefacts and notes

Record the following here as each milestone completes:

- red and green transcripts;
- Hypothesis coverage counters;
- seeded-fault outcomes;
- the INV-8 `git diff --stat` evidence.

### EP-M0

- Green on the unmodified launcher code: `7 passed` for
  `tests/test_generation_run_launcher_no_qa_characterization.py`, and
  `16 passed` together with `tests/test_generation_run_launcher.py`.
- Artefacts:
  - `tests/test_generation_run_launcher_no_qa_characterization.py`;
  - `tests/no_qa_characterization_support.py`, the deterministic payload
    builder;
  - `tests/generation_run_launcher_observation_support.py`, the recording
    metrics double;
  - `tests/__snapshots__/test_generation_run_launcher_no_qa_characterization.ambr`.
- The snapshot records, per case, the event kinds and payloads, the final run
  and episode rows, every metrics emission in call order, and the execution
  span attributes. Latency values render as `<elapsed_ms>` and content hashes as
  `<sha256>`, so the snapshot is deterministic and passes ambrleaks.
- Gate evidence: `make check-fmt`, `make typecheck`, `make lint`, `make test`
  (1732 passed, 1 skipped), `make check-migrations`, `make markdownlint` and
  `make nixie` all passed on this tree. The `make markdownlint` spelling
  prerequisite regenerated `typos.toml`; the generated bytes are committed
  separately as a base change.
- Surprise: the materialized episode already carries a placeholder TEI hash,
  so the "missing episode" case has to inject the fault by replacing the
  episode repository rather than by storing a dangling run: both
  `generation_runs.episode_id` and `source_bundle_id` are foreign keys with
  cascade behaviour.

### Rebases and the CodeRabbit completeness assessment

- Replayed onto `main @ d0bdabe3` (commit `c240f579`):
  - the QA-gated migration is `20261122_000018` on top of `20261110_000017`;
  - ADR 024 became
    `docs/adrs/adr-0029-qa-gated-mode-branching-and-content-generation-graph.md`;
  - routes moved to `episodic/api/routes.py` with
    `GenerationRunsResourceConfig`;
  - the episode TEI resource reads its producing run through
    `read_owned_episode_and_run`.
- Addressed the hosted CodeScene review (`8e316dce`, `dca6c479`) by extracting
  helpers and grouping arguments; `cs delta origin/main HEAD` is clean.
- CodeRabbit's completeness assessment (`4.4.1-completeness-dca6c479`) named
  five correctness defects and four evidence gaps. All five defects are fixed
  under D18 with new tests, and this section plus D17 supply the missing
  evidence. The scope overrun is recorded as D17.
- The repair round for that assessment is commit `eac73e3b`. It adds the sixth
  repair (the shutdown write runs in a task named for its run) and splits
  `tests/test_content_generation_graph_properties.py` so every module stays
  under the 400-line ceiling.
- A second assessment round raised two correctness items and four
  verification items. All six are repaired:
  - D19: a claim, not a task name, authorizes a terminal write, so a losing
    launcher cannot fail a run through a pre-claim read fault or a shutdown.
  - D20: the pre-4.4.1 request-error precedence is restored for the
    capability, budget and rationale checks.
  - INV-2: the property asserts its rejection branch with a named message and
    is exercised against a policy-free store, which must fail it.
  - INV-5: `observed_nodes` records node entry through the debug stream, so a
    faulting node is still checked for ownership.
  - INV-9: `tests/test_generation_run_launcher_quality_matrix.py` covers all
    ten plan cells, and
    `tests/test_generation_run_launcher_quality_ownership.py` covers the
    competing-launcher cases.
  - Evidence: this section now holds the milestone transcripts, Hypothesis
    counters, seeded-fault outcomes and the INV-8 comparison.
- A third assessment round raised three correctness items, repaired under
  D21: conditional cancellation dedup, ownership across the claim session's
  close, and request-error precedence when no launcher is configured.
- A fourth round raised two items, repaired under D22: a rolled-back failure
  claim must not be retained, and a reused idempotency key must not pre-empt a
  body error. The round also asked for the cancellation case at the post-commit
  close boundary, which
  `test_cancellation_at_claim_exit_still_ records_the_failure` now covers.
- Evidence at `eac73e3b` (the pre-#438 head) was: `make check-fmt`,
  `make typecheck`, `make lint` (Hecate, Ruff, Pylint, df12, interrogate,
  ambrleaks, Skylos, df12-duplication), `make test` (2,448 passed, 1 skipped,
  82 snapshots), `make check-migrations`, `make markdownlint` and `make nixie`.
  At the current head (see the integration record below) the suite reports
  2,776 passed, 7 skipped and 84 snapshots. The INV-8 comparison is
  `git diff --stat` over the characterization snapshot and
  `tests/features/no_qa_generation_slice.feature` since `d6876cba`: the feature
  file is unchanged, and the snapshot differs only by the two D9 span
  attributes plus the D15 record.

### Milestone evidence record

Each milestone was developed and gated on its working tree with the full
sequence: `make check-fmt`, `make typecheck`, `make lint`, `make test`,
`make check-migrations`, `make markdownlint` and `make nixie`. That claim holds
for the tree as built. It does not hold for every *committed* tree: the rebase
that produced `c240f579` corrupted three files in the replayed commits, as
recorded under the transcripts below. The commits, in order, are:

- EP-M0, `e4e0fd8f`: the no-QA characterization snapshot and its payload and
  recording-metrics doubles. Green on unchanged launcher code.
- EP-M1, `9159f52b`: `QualityMode.QA_GATED`, `QaStatus`, and the pure
  `quality_metadata_violation` policy. Red first through the literal policy
  table, which could not construct `qa_gated` before this commit.
- EP-M2, `a3b52653`: the staged enum migration `20261122_000018`, the
  `UNCHANGED` sentinel, `apply_status_update`, and both store adapters. The
  downgrade refuses when persisted `qa_gated` rows would be lost.
- EP-M3, `887d177b`: the content-generation graph, its ports, the QA policy
  routing, and the graph property, miswiring and topology tests.
- EP-M4, `b2e54499`: the launcher, session and persistence paths run through
  the graph; D16's per-invocation task ownership and cancellation drains land
  here. Red first: the INV-9 task-name assertion saw LangChain's `Task-9`
  before D16 named every node task.
- EP-M5, `0e97c196`: the capability-gated REST surface and its accepted-set
  plumbing.
- EP-M6, `e85118dd`: ADR 0029 and the design and users' guide updates.

Rebase, review and repair commits after EP-M6 are `c240f579`, `8e316dce`,
`dca6c479`, `eac73e3b`, `873ce747`, `9951571e` and the evidence commit that
carries this record.

Transcripts, re-run for this record:

- EP-M0 at `e4e0fd8f`:
  `tests/test_generation_run_launcher_no_qa_characterization.py` and
  `tests/test_generation_run_launcher.py`, 16 passed.
- EP-M1 at `9159f52b`: `tests/test_generation_quality_policy.py` and
  `tests/test_generation_run_qa_lifecycle.py`, 193 passed.
- EP-M0 INV-0 at the current head: 7 passed.
- EP-M2, EP-M3, EP-M4 and EP-M5 are re-run at the current head, not at their
  original commits, because the rebase that produced `c240f579` left
  `episodic/canonical/storage/generation_runs.py` unparsable in the
  intermediate commits `a3b52653` through `0e97c196`. Those commits cannot be
  collected, so their own transcripts cannot be reproduced. The current head's
  tree is clean, and `c240f579` is the commit that restored it.
  - EP-M2 paths, 25 passed: `test_generation_run_status_update_policy.py`,
    `canonical_storage/test_generation_run_quality_updates.py`,
    `test_qa_gated_quality_mode_migration.py`,
    `test_generation_run_qa_lifecycle.py`.
  - EP-M3 paths, 31 passed: `test_content_generation_graph_properties.py`,
    `test_content_generation_graph_miswiring.py`,
    `test_content_generation_graph_topology.py`,
    `test_generation_routing_policy.py`.
  - EP-M4 paths, 39 passed: `test_generation_run_launcher.py`,
    `test_generation_run_launcher_no_qa_characterization.py`,
    `test_generation_run_launcher_quality_modes.py`,
    `test_generation_run_launcher_quality_matrix.py`,
    `test_generation_run_launcher_quality_ownership.py`.
  - EP-M5 paths, 110 passed and 1 skipped: `test_generation_run_api.py`,
    `test_generation_run_api_quality_modes.py` and `tests/steps`.
  - Red evidence: EP-M1's policy table could not construct `qa_gated` before
    `9159f52b`; EP-M4's INV-9 assertion observed LangChain's unnamed
    `Task-9` before D16; the D18 and D19/D20 repairs were each written as a
    failing test first, and the policy-free-store control still fails the
    INV-2 property by construction.
  - Known defect in history: a reviewer bisecting `a3b52653` to `0e97c196`
    will find a non-parsing file. It is repaired at `c240f579`, and the
    published head is clean; the branch was not force-rewritten to hide it.

Reproducible non-vacuity evidence, measured on this tree:

- Hypothesis counters: `test_branch_ownership_property` ran 100 passing
  examples with 0 failing and 19 rejected; `test_quality_update_property` ran
  60 passing examples with 0 failing and 0 rejected
  (`pytest --hypothesis-show-statistics`).
- Witness matrix: `test_property_reaches_every_class` asserts that all eleven
  documented observation classes are reached, and fails if any class is missing.
- Seeded checks that must reject:
  - the swapped `path_map` graph (`test_swapped_path_map_is_rejected`);
  - the foreign generate node followed by a correct terminal
    (`test_foreign_generate_node_is_rejected_by_observed_visits`);
  - the policy-free store (`test_policy_free_store_fails_the_property`);
  - an append from a foreign task
    (`assert_off_task_append_is_rejected`, called by the matrix);
  - the ten-cell INV-9 matrix, where each cell has its own terminal,
    category, QA status, cost and metric expectations;
  - the observer's commit ordering: moving the `observe` call above
    `_write_failure` fails all three observer tests, including the
    refused-write one, because a refused token then emits a callback;
  - the proof factory: making `RunClaim` ignore `proof_factory` fails
    `test_an_injected_proof_factory_supplies_the_proof`;
  - the stale-session test: removing `populate_existing=True` from the locked
    read fails `test_a_stale_session_cannot_bypass_the_claim_gate`, and
    restoring it passes, both measured against PostgreSQL 17.11;
  - the in-memory terminal gate: removing `require_terminal_claim` from
    `InMemoryGenerationRunStore.update_run_status` fails both refusal cases in
    `tests/test_generation_run_in_memory_terminal_claim.py`;
  - the INV-1 seeded mutation: deleting the `qa_gated` rationale rule from
    `quality_metadata_violation` makes
    `tests/test_generation_quality_policy.py` report 22 failed and 165
    passed, every failure a `test_quality_metadata_policy[qa_gated-*]` cell
    failing with `DID NOT RAISE ValueError`; restoring the rule returns
    187 passed.
- Coverage counters: at `eac73e3b`, `make lint`'s interrogate stage reported
  100% docstring coverage over 7,364 definitions and pytest reported 2,448
  passed, 1 skipped and 82 snapshots. At the current head it reports 8,008
  definitions and 2,776 passed, 7 skipped and 84 snapshots. The extra skips are
  the DSN-gated real-PostgreSQL claim races.
- INV-8:
  `git diff --stat d6876cba HEAD -- tests/features/no_qa_generation_slice.feature`
  is empty, and the characterization snapshot differs by exactly the two D9
  span attributes plus the D15 record.

Scope acceptance: D17 records the deviation from the 65-file and 3,500-line
limits. The implementation proceeded under the operator's explicit instruction
to implement the approved plan to completion, not to stop short of it, and to
accept the recommendations for outstanding decisions; that instruction is the
acceptance this record relies on, and a stakeholder who disagrees can still
halt the branch before merge.

The same instruction is the acceptance basis for the three items CodeRabbit
left to a stakeholder, all of which are now decided:

- **Substitute milestone evidence.** No milestone has a separate stakeholder
  transcript. The evidence is the per-milestone test transcripts, the
  Hypothesis counters, the seeded-fault rejections and the gate logs recorded
  in this document, and that is accepted as sufficient for this delivery.
- **D17, the size deviation.** Accepted: the change exceeds the 65-file and
  3,500-line tolerance because the feature spans the domain policy, both store
  adapters, two migrations, the graph, the launcher components, the REST gate
  and the documentation. Splitting it would leave a half-gated state in which
  the schema accepts `qa_gated` while nothing evaluates it.
- **D23, the `claim_token` schema column.** Accepted: the nullable
  `generation_runs.claim_token` column is the durable per-attempt proof the
  terminal-claim gate compares. A side table would add a join to every terminal
  write for no benefit, and dropping the column on downgrade loses only claim
  evidence, never run data.

### Integration with the injected launcher components (#438)

`main` replaced the launcher mixins with `GenerationRunScheduler`,
`GenerationRunClaimer` and `GenerationRunPersistence`, so this branch is merged
rather than rebased (`436ae804`) and the QA-gated work is ported onto that
structure:

- `GenerationRunClaimer` owns the claim token, its unique proof and
  reconciliation, and hydrates the run.
- `GenerationRunFailurePersistence` (`launcher_failure.py`) is new: it owns
  authoritative failure writes, the escalation events, escalation costs and the
  failure observation.
- `GenerationRunPersistence` gained `qa`-aware `persist_success` and a public
  `record_costs` the failure component reuses.
- `_LauncherRunSession` receives the three components plus a unit-of-work
  factory, clock and metrics, instead of the launcher itself.
- `InProcessGenerationRunLauncher._execute_run` reads the run's quality mode,
  runs the content graph, and reports `quality_branch` and `terminal` on the
  span; the scheduler tracks and drains shielded cancellation writes.
- The live runtime views moved to `launcher_runtime_views.py` to keep the
  launcher under the file-size ceiling.

## Interfaces and dependencies

At the end of EP-M5 the following must exist. The signatures are prescriptive,
and docstrings are NumPy-style.

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


class EvaluationRoute(enum.StrEnum):
    PASS = "pass"
    ESCALATE = "escalate"


class GenerationTerminal(enum.StrEnum):
    DRAFT_PERSISTED_WITHOUT_QA = "draft_persisted_without_qa"
    QA_PASSED_DRAFT_PERSISTED = "qa_passed_draft_persisted"
    QA_ESCALATED = "qa_escalated"


def route_quality_mode(mode: QualityMode) -> QualityBranch: ...
def branch_for_terminal(terminal: GenerationTerminal) -> QualityBranch: ...
def aggregate_verdicts(verdicts: cabc.Iterable[QualityVerdict]) -> QualityVerdict: ...
def route_after_evaluation(verdict: QualityVerdict) -> EvaluationRoute: ...


@dc.dataclass(frozen=True, slots=True)
class TerminalOutcome:
    status: GenerationRunStatus
    qa_status: QaStatus
    error_category: str | None


def terminal_outcome(terminal: GenerationTerminal) -> TerminalOutcome: ...
```

In `episodic/canonical/generation_graph_ports.py`:

```python
@dc.dataclass(frozen=True, slots=True)
class EvaluationSubject:
    run_id: uuid.UUID
    episode_id: uuid.UUID
    tei_xml: str
    content_hash: str


@dc.dataclass(frozen=True, slots=True)
class QualityEvaluation:
    evaluator: str
    verdict: QualityVerdict
    summary: str | None = None
    error_type: str | None = None


class QualityEvaluatorPort(typ.Protocol):
    @property
    def name(self) -> str: ...  # stable slug, used in events and metric labels
    async def evaluate(self, subject: EvaluationSubject) -> QualityEvaluation: ...


@dc.dataclass(frozen=True, slots=True)
class QualityEvaluatorSet:
    evaluators: tuple[QualityEvaluatorPort, ...]
    evaluator_timeout_seconds: float = 120.0

    def accepted_quality_modes(self) -> frozenset[QualityMode]: ...


@dc.dataclass(frozen=True, slots=True)
class ContentGenerationRequest:
    run_id: uuid.UUID
    quality_mode: QualityMode


class ContentGenerationSteps(typ.Protocol):
    async def initialize(self) -> None: ...
    async def generate_draft(self) -> None: ...
    async def begin_evaluation(self, evaluator_names: tuple[str, ...]) -> None: ...
    def evaluation_subject(self) -> EvaluationSubject: ...
    async def complete_with_draft(
        self, qa_status: QaStatus, evaluations: tuple[QualityEvaluation, ...]
    ) -> None: ...
    async def escalate(
        self, verdict: QualityVerdict, evaluations: tuple[QualityEvaluation, ...]
    ) -> None: ...


class ContentGenerationGraphPort(typ.Protocol):
    def accepted_quality_modes(self) -> frozenset[QualityMode]: ...
    async def run(
        self, request: ContentGenerationRequest, *, steps: ContentGenerationSteps
    ) -> GenerationTerminal: ...


class QualityEvaluationUnavailableError(RuntimeError): ...


class ContentGenerationGraphError(RuntimeError): ...
```

In `episodic/orchestration/content_generation.py`:

```python
def build_content_generation_graph() -> CompiledStateGraph[
    ContentGenerationGraphState,
    ContentGenerationContext,
    ContentGenerationGraphState,
    ContentGenerationGraphState,
]: ...


@dc.dataclass(slots=True)
class LangGraphContentGenerationGraph:
    evaluator_set: QualityEvaluatorSet

    def accepted_quality_modes(self) -> frozenset[QualityMode]: ...
    async def run(
        self, request: ContentGenerationRequest, *, steps: ContentGenerationSteps
    ) -> GenerationTerminal: ...
```

Changes to existing classes:

- `InProcessGenerationRunLauncher` gains the required field
  `content_graph: ContentGenerationGraphPort`.
- `GenerationRunStatusUpdate` gains
  `qa_status: QaStatus | Unchanged = UNCHANGED`.
- `ApiDependencies` gains `accepted_quality_modes: frozenset[QualityMode]`.

Dependencies: no new packages.

- Use `langgraph.graph.StateGraph`, `START`, `END` and
  `langgraph.runtime.Runtime`, in
  `episodic/orchestration/content_generation.py` only. `Runtime` and
  `context_schema` are new to this repository but ship with the pinned
  LangGraph 1.2.11.
- Use Hypothesis 6.x, pytest-bdd, syrupy and py-pglite.

## Revision note

- 2026-10-17: initial draft (commit `5814b812`), written from Wyvern
  reconnaissance and primary-source reading.
- 2026-11-22: implementation completed across EP-M0 to EP-M6. D14 resequenced
  symbol landing for the dead-code gate, D15 recorded the only INV-0 snapshot
  change, and D16 corrected the inline-execution axiom after INV-9 exposed the
  child-task behaviour. ADR 0029 was accepted.
- 2026-10-17: revised after the expert-panel design review (D13). The
  changes are:
  - Moved the fork before generation (D3).
  - Wrapped node functions in closures so they import no LangGraph (D1).
  - Relaxed the non-terminal QA-status rule, and added the `UNCHANGED`
    sentinel and a fixed validation order (D5).
  - Took the TEI envelope's mode from the run (D6).
  - Moved the capability check inside the idempotent work, after the parser,
    and renamed the constraint (D7).
  - Added evaluator timeouts, error isolation and the fail-fast check (D8).
  - Restructured the event payloads, with `qa.result` in the terminal unit of
    work (D9).
  - Recorded costs on escalation, reusing the failure path (D10).
  - Added TEI validation before evaluation (D11).
  - Added runner failure translation (D12).
  - Added the EP-M0 characterization baseline.
  - Made INV-1 exhaustive.
  - Replaced non-vacuity checks that could not be executed with `@example`
    witnesses and in-test counters.
  - Corrected the factual errors the panel found.
  - Raised the scope tolerance.

  The remaining work is user approval, then EP-M0.
