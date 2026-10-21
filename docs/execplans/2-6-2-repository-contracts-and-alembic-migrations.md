# Implement generation-run repository contracts and Alembic migrations (2.6.2)

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & discoveries`, `Decision log`,
`Outcomes & retrospective`, `Conformance basis`, and `Verification plan` must
be kept up to date as work proceeds.

Status: DRAFT

## Purpose / big picture

A *generation run* is the record of one attempt to turn an ingested source
bundle into a podcast script. It owns an append-only *event log* (a numbered
stream of things that happened during the run) and a set of *review
checkpoints* (pauses where a human reviewer is asked to approve, request
changes, or edit before the run continues).

Roadmap item 2.6.1 defined the domain entities and the port protocols for all
three concepts. Roadmap item 4.3.2 then landed durable PostgreSQL persistence
for *runs and events only*, as a deliberately narrow vertical slice. Reviewer
checkpoints have no table and no SQL adapter; only the in-memory reference
adapter implements them.

Be precise about what that does and does not mean, because the previous draft
of this plan overstated it. `InMemoryGenerationRunStore` is instantiated
**nowhere** in `episodic/` — it is a test and reference adapter only. No
production code path calls `create_checkpoint` today. So no reviewer checkpoint
is currently being lost, because none is currently being created.

This is therefore an **enabling slice**. It builds the durable substrate that
roadmap item 2.6.3 (`POST /v1/generation-runs/{run_id}/checkpoint`) and the
later human-in-the-loop graph require, and it ships with **zero production
consumers**. That is a legitimate and deliberate shape, but the plan states it
plainly so nobody mistakes a durable table for a live capability, and so no
operator believes reviewer checkpoints are in service before 2.6.3 lands.

After this change a developer can do the following and watch it work:

1. Run `make check-migrations` and see no schema drift, with the new
   `review_checkpoints` table present in both the SQLAlchemy models and the
   migration history, and see the migration reverse cleanly without orphaning
   its enum types.
2. Open a `SqlAlchemyUnitOfWork`, create a run, create a checkpoint, respond to
   it, and `commit()`. Then open a *fresh* unit of work and read the responded
   checkpoint back out of PostgreSQL, byte for byte.
3. Run `make test` and see one shared set of checkpoint contract scenarios pass
   against **both** the in-memory adapter and the PostgreSQL adapter, proving
   the two are behaviourally interchangeable within the documented limits.

## Signposts: documentation and skills

Read these before and during implementation. Paths are repository-relative.

Skills to load at session start:

- `leta` — semantic code navigation. Use `leta show <symbol>` instead of
  reading files, `leta refs <symbol>` instead of grepping for usages, and
  `leta implementations <protocol>` to find adapters. Add the workspace once
  with `leta workspace add .`.
- `hexagonal-architecture` — the rule that matters here: domain and ports must
  not import adapters. Everything added under `episodic/canonical/storage/` is
  an *outbound (driven) adapter*.
- `python-router`, then `python-testing` and `python-types-and-apis` as needed.
- `hypothesis` — for the sequencing property tests in Milestone EP-M3.
- `execplans` — the rules this document follows.
- `vidai-mock` — **not used by this slice.** This plan touches persistence
  only; no inference call is made or mocked. It is named here because the
  phase-wide instruction references it, and to record that it was considered
  and found inapplicable.

Repository documentation:

- `AGENTS.md` — normative rules on code style, the 400-line file limit,
  NumPy-style docstrings, en-GB-oxendict spelling, quality gates, and the
  abstraction/port/helper sweep policy.
- `docs/episodic-podcast-generation-system-design.md`, section
  "Content Generation Orchestrator" — "Provides checkpointing for resumable
  workflows, enabling long-running editorial review periods without state
  loss." That requirement is what this slice builds towards.
- `docs/episodic-tui-api-design.md`, section "Generation runs" — the data
  shapes, the `after_seq` replay contract, and the pagination envelope
  (`1 <= limit <= 100`, `offset >= 0`). Note lines 629–633 in particular: the
  backpressure heuristic is the only place the design treats `seq` arithmetic
  as an event count.
- `docs/async-sqlalchemy-with-pg-and-falcon.md` — session and engine
  conventions. Its testing section (savepoint-based rollback) is **superseded**
  in this repository by the py-pglite fixtures; defer to the project-specific
  document below.
- `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` — the fixture stack.
  Use `session_factory` for repository, service, and unit-of-work tests.
- `docs/testing-async-falcon-endpoints.md` — relevant only if a later revision
  extends this slice to API-level assertions. Not exercised here.
- `docs/agentic-systems-with-langgraph-and-celery.md` — background only.
  **Caution:** its "Persistence and Checkpointing" section recommends a
  Redis-backed LangGraph checkpointer. This repository uses PostgreSQL per
  ADR-007. Do not let that document steer this slice towards Redis.
- `docs/developers-guide.md`, sections "Database migrations", "Database
  testing with py-pglite", "Canonical content persistence", "Generation-run
  domain ports", "Manual recovery of expired generation-run leases",
  "Code-duplication gate", and "Module size and façade modules".
- `docs/adr/adr-015-generation-run-port-split.md` — why the port is split, and
  why the user-facing `Checkpoint` differs from `WorkflowCheckpoint`.
- `docs/adr/adr-018-explicit-versioning-and-history-strategy.md` — the
  governing record for versioning, concurrency shapes, immutability, and
  deletion policy. Read it before writing the adapter; it decides D-10 and the
  foreign-key policy.
- `docs/adr/adr-019-episode-tei-revision-history.md` — the template for an
  append-only history table. Read it to see what D-11 deliberately does *not*
  build for review checkpoints.
- `docs/adr/adr-021-adopt-nose-duplication-gate.md` — the blocking duplication
  gate in `make lint`. It scans `episodic/`, so a SQL checkpoint store that
  mirrors the in-memory mixin is in scope; see the duplication constraint.
- `docs/adr/adr-022-orchestration-architecture-enforcement.md` — note that its
  `CheckpointPort` is the *orchestration* port for `WorkflowCheckpoint`, not
  `GenerationCheckpointPort`. Another instance of the Risk 1 confusion.
- `docs/alpha-test-4-3-2-setup-notes.md` — the end-to-end alpha run of the
  4.3.2 slice, including where repository documentation was wrong. It says
  nothing about checkpoints or leases.
- `docs/adr/adr-007-durable-generation-checkpoints.md` — the *orchestration*
  checkpoint. Read it to avoid conflating the two. Note its title is "Durable
  generation checkpoints", which is why this plan does **not** use "generation
  checkpoint" for the new table (see D-7).
- `docs/documentation-style-guide.md` — prose and ADR conventions.
- `docs/execplans/4-3-2-no-qa-generation-runs-and-tei-p5-retrieval.md` — landed
  the run/event half of this roadmap item and deferred checkpoints and lease
  recovery here.
- `docs/execplans/2-6-1-generation-run-port-and-domain-model.md` — defined the
  ports this slice implements.

Existing code and tests this plan extends rather than duplicates:

- `episodic/canonical/storage/generation_runs.py` — the run/event SQL adapter.
- `episodic/canonical/adapters/generation_checkpoints.py` — the in-memory
  checkpoint behaviour the SQL adapter must match.
- `tests/canonical_storage/test_generation_runs.py` — **already** the SQL
  adapter contract suite ("run round-trips, idempotency, event sequence
  allocation, terminal immutability, and transaction rollback"). New SQL
  contract scenarios belong here, not in a parallel module.
- `tests/canonical_storage/_generation_run_support.py` — provides
  `persist_generation_run_prerequisites` and `claim_run_in_independent_uow`.
  **Every** SQL scenario needs the former; see EP-M3.
- `tests/features/generation_run_lifecycle.feature` — already contains
  "Reviewer approves a checkpoint" and "Reviewer cannot respond twice" against
  the in-memory adapter. Extend it; do not create a second checkpoint feature.
- `tests/canonical_storage/test_sql_generation_run_property_contract.py` —
  already discharges the paging and cross-run isolation properties.

## Changes on `main` since the first draft

The plan was first drafted against commit `5af0638`. Everything below has since
landed on `main`; it is recorded so the reasoning in later sections can be
traced to the tree it was checked against. The plan was last reconciled against
`main` at commit `468923ed` on 2026-10-18.

- **PR 278 (roadmap 2.8)** landed ADR-018, the governing record for
  versioning, concurrency shapes, immutability, and deletion policy, and
  ADR-019, episode TEI revision history. Three decisions here conform to
  ADR-018: D-10 (compare-and-set rather than row locking), the
  `ON DELETE RESTRICT` foreign key in Table 1, and D-11 (why a review
  checkpoint is not a versioned aggregate). It also added roadmap step 2.8, so
  follow-ups from this plan must not claim that number.
- **PR 277 (4.3.2 alpha hardening)** moved `uow.py`'s imports out of
  `if typ.TYPE_CHECKING:` because `mock.create_autospec` evaluates method
  annotations at runtime; added a `Raises / RunNotFound` section to
  `count_events`, the precedent Stage C step 7 generalizes; and established
  that **persisted rows survive between Hypothesis examples**, scoping an
  idempotency key per example with `uuid.uuid7()` accordingly.
- **The domain module was split** (PR 276). `episodic/canonical/domain.py` is
  now a 93-line re-exporting façade. `Checkpoint` and `CheckpointResponse` live
  in `episodic/canonical/domain_generation.py`; `CheckpointStatus` and
  `CheckpointAction` live in `episodic/canonical/domain_enums.py`. Import
  through the façade as existing storage code does.
- **A blocking nose duplication gate** (ADR-021, superseding ADR-020's PyChase)
  runs at the end of `make lint` over `episodic/` and `openai_test_types.py`.
  Tests are outside its roots.
- **Pylint now runs on CPython 3.14 over `tests/` as well** (PRs 339 and 346),
  so new test modules are linted. Suppressions take the form
  `# pylint: disable-next=too-many-arguments  # <reason>`.
- **Ruff 0.16.8** replaced `# noqa: TC00x` with named, reasoned suppressions.
  `uow.py` now reads, for example,
  `# ruff: ignore[typing-only-first-party-import] - autospec resolves annotations`.
- **Migration `20261010_000013_name_pricing_snapshot_constraint`** is the new
  head, so this plan's revisions are `000014` and `000015`, not `000013` and
  `000014`.
- **ADR-020 to ADR-023 are taken** (duplication gates, orchestration
  architecture enforcement, the shared CV-005 contract library). This plan's
  ADR is **ADR-024**.
- **`make skylos-allow` takes `SYMBOL=` and `REASON=`**, and
  `make duplication-allow` takes `FIRST=`, optional `SECOND=`, and `REASON=`.
- **`make markdownlint` now includes the en-GB-oxendict spelling gate**;
  `typos.toml` is generated and must never be hand-edited.
- **The test suite has grown from 1227 to 1725 tests.** See `Tolerances`.

## Constraints

Hard invariants. Violating one requires escalation, not a workaround.

- **Do not change the 2.6.1 domain surface.** The `GenerationRun`,
  `GenerationEvent`, `Checkpoint`, and `CheckpointResponse` entities in
  `episodic/canonical/domain_generation.py`, the `GenerationRunStatus`,
  `CheckpointStatus`, and `CheckpointAction` enums in
  `episodic/canonical/domain_enums.py`, and their re-exports from the
  `episodic/canonical/domain.py` façade are frozen for this slice.
- **Do not weaken the existing port protocols.** Methods may be *added* to
  `episodic/canonical/generation_run_ports.py` — roadmap 2.6.2 explicitly
  covers "define repository interfaces" — but no existing signature may change.
- **Hexagonal dependency rule.** New storage modules may import domain types,
  ports, and domain errors. Domain and ports must not import storage.
  `make check-architecture` (Hecate) must pass — but note that it does **not**
  currently enforce this rule for the two modules this slice edits most.
  `episodic.canonical.generation_run_ports` and
  `episodic.canonical.generation_run_errors` match no `[tool.hecate.groups]`
  prefix, and Hecate skips any import edge whose importer or target is
  ungrouped. See D-12.
- **No schema drift.** `make check-migrations` must report no difference
  between `Base.metadata` and the migration history.
- **Single migration head.** New revisions chain off the current head
  `20261010_000013` (`name_pricing_snapshot_constraint`). Confirm with
  `uv run alembic heads`; the `down_revision` chain, not the filename date, is
  authoritative, and existing filenames are *not* in strict date order.
- **Never modify an applied revision.** Once a revision file has been merged,
  it may have run against a developer, CI, or staging database, and Alembic
  will never re-run it. Every schema addition gets its **own** revision, even
  within this plan. `make check-migrations` cannot catch a violation, because
  it rebuilds an ephemeral database from scratch every time and so compares a
  freshly-built schema against the ORM.
- **Name collision avoidance.** The new table and enums must not collide with
  the orchestration `workflow_checkpoints` table, its
  `workflow_checkpoint_status` enum, or — in prose — with ADR-007's title. See
  D-7.
- **Storage conventions.** Timestamps are `sa.DateTime(timezone=True)`. UUID
  primary keys are `postgresql.UUID(as_uuid=True)`, client-assigned UUIDv7; no
  server-side UUID defaults. Structured payloads use `postgresql.JSONB`. Python
  enums map to native PostgreSQL enums declared once in
  `episodic/canonical/storage/models_base.py` with
  `values_callable=lambda enum_cls: [item.value for item in enum_cls]`.
- **File size.** No code file exceeds 400 lines.
  `episodic/canonical/storage/generation_runs.py` is 358 lines and
  `episodic/canonical/adapters/generation_runs.py` is 390, so neither can
  absorb new methods. Moving code between modules means updating any Skylos
  entry point or duplication exception that names the old module.
- **Duplication gate.** `make lint` ends with the blocking nose gate
  (ADR-021). The SQL checkpoint store will share signatures, docstrings, and
  argument guards with `InMemoryGenerationCheckpointMixin`. Prefer extracting a
  shared helper over suppressing a finding. Where the parallel is the port
  itself, record one reasoned exception with `make duplication-allow`,
  mirroring the existing `storage/generation_runs.py` /
  `adapters/generation_runs.py` entry rather than broadening it.
- **Suppression style.** Use Ruff's named form,
  `# ruff: ignore[<rule-name>] - <reason>`, as `uow.py` does, and
  `# pylint: disable-next=<rule>  # <reason>`. `# noqa` codes are no longer
  house style. Pylint lints `tests/` too.
- **Repositories do not own the transaction.** Adapters `flush()`; only
  `SqlAlchemyUnitOfWork.commit()` commits.
- **A unit of work that has appended an event must not span an inference
  call.** `append_event` holds `SELECT ... FOR UPDATE` on the run row until the
  *caller's* transaction commits. A unit of work that appends an event and then
  awaits an LLM response pins that lock for the duration, blocking
  `update_run_status` behind it.
- **No compatibility shims.** These are private, pre-1.0, application-internal
  interfaces with no external consumers. When a port widens, update the
  protocol, both adapters, and every caller in one commit.

## Tolerances (exception triggers)

Stop and escalate rather than improvising when any of these is reached.

- **Scope:** more than 32 files changed, or more than 2200 net added lines
  across production code, tests, and documentation. This is deliberately larger
  than a typical slice: the milestone breakdown below enumerates 28–31 files,
  and a tolerance below that would fire by construction.
- **Interface:** any change to an *existing* signature in
  `episodic/canonical/domain_generation.py`,
  `episodic/canonical/domain_enums.py`, or
  `episodic/canonical/generation_run_ports.py`.
- **Dependencies:** any new entry in `pyproject.toml` dependency groups. This
  slice needs none.
- **Migration graph:** if `uv run alembic heads` reports more than one head, or
  if any already-merged revision file would need editing.
- **Iterations:** if a single failing gate is not green after 4 fix attempts.
- **Runtime:** if per-test `migrated_engine` setup exceeds 0.5 s, or if total
  `make test` wall-clock grows by more than 15% over the Stage A baseline. The
  previous absolute ceiling of 165 s is withdrawn: it was set against **130.58
  s for 1227 passed, 3 skipped** at `5af0638`, and the suite has since grown to
  **1725 passed, 1 skipped**, measured at **334.48 s** of pytest time on
  2026-10-15 on a contended shared host. Neither figure is a usable baseline
  for this slice; Stage A re-measures on an otherwise idle run. Per-test
  `migrated_engine` setup was **0.20–0.38 s** after the one-off session-scoped
  py-pglite start (~3.8 s); re-confirm that too. Note that Hypothesis examples
  do **not** re-run migrations — the fixture is function-scoped and shared
  across every example, which is precisely why
  `suppress_health_check=[HealthCheck.function_scoped_fixture]` is required.
  The corollary, established by PR 277, is that **persisted rows survive
  between examples**: the session factory outlives them. Every database-backed
  property test must scope its own data per example — `make_generation_run()`
  already does so via UUIDv7, but any shared idempotency key, actor, or fixture
  row must be suffixed per example.
- **Concurrency evidence:** if any test intended to demonstrate lock contention
  hangs to the 180 s `pytest-timeout`, stop. See AXIOM-3 and Risk 2 — under
  py-pglite this is the expected outcome, not a bug to debug.
- **Ambiguity:** if EP-M4 turns out to require a scheduler, worker, or Celery
  beat entry, stop — that is orchestration work for a separate roadmap item.

## Risks

- **Risk 1: reviewers conflate the user-facing review checkpoint with the
  orchestration `WorkflowCheckpoint`.** Severity: high. Likelihood: medium.
  Mitigation: distinct table and enum names are a hard constraint; D-7 renames
  away from "generation checkpoint" precisely because ADR-007 is *titled*
  "Durable generation checkpoints"; the `Terms used` section gives a positive
  discriminator; EP-M1 asserts both tables coexist after migration.

- **Risk 2: the plan promises concurrency evidence the test harness cannot
  produce, and a green suite is then misread as proof of concurrency safety.**
  Severity: high. Likelihood: **certain** if unaddressed — see AXIOM-3, which
  records two independent experimental probes. Mitigation: AXIOM-3 is rewritten
  to state that py-pglite serializes transactions globally; INV-SEQ-1 is scoped
  to what is actually observable; the genuine concurrency claim is moved to
  `Residual gaps`; and the `Tolerances` entry above turns the failure mode into
  an escalation rather than a debugging session. This is the most important
  correction in this revision.

- **Risk 3: EP-M4's reclamation predicate fails runs that are legitimately
  awaiting a human reviewer.** Severity: high. Likelihood: high if the
  predicate is written naively. Evidence: the lease is 900 s
  (`episodic/generation/launcher.py`), is set once at claim time, and is
  **never renewed** — no heartbeat exists anywhere in the tree.
  `GenerationRunStatus.PAUSED` exists in the enum and **no code sets it**. So a
  run awaiting review sits in `running` with an unrenewable 15-minute lease.
  Mitigation: EP-M4's predicate must exclude runs with an open checkpoint; the
  state partition must include that case explicitly; and the docstring must
  state that the lease is a wall-clock ceiling, not a liveness signal.

- **Risk 4: a caller forgets `await uow.commit()` and the failure is silent.**
  Severity: high. Likelihood: medium. Evidence:
  `SqlAlchemyUnitOfWork.__aexit__` rolls back only when an exception
  propagates; on the happy path it calls `session.close()`, discarding flushed
  work with no exception, no warning, and no log line. A 2.6.3 endpoint that
  forgets to commit would return `200 OK` with `status: responded` for a
  decision that was never persisted. Mitigation: EP-M2 adds a warning branch in
  `__aexit__` when closing with pending state, and a contract scenario that
  pins the semantics deliberately.

- **Risk 5: `downgrade()` is treated as a safe recovery step after checkpoints
  exist.** Severity: high. Likelihood: medium. Mitigation: the migration
  docstring and EP-M1's recovery note must state that downgrading destroys
  every reviewer decision. The blanket "no destructive step" claim from the
  previous draft is removed.

- **Risk 6: EP-M4's index is added by editing EP-M1's already-merged
  revision.** Severity: high. Likelihood: high — it is the obvious thing to do.
  Mitigation: the "never modify an applied revision" constraint, plus EP-M4
  carrying its own revision number.

- **Risk 7: adding a `CheckpointStatus` or `CheckpointAction` value later is
  harder than it looks.** Severity: medium. Likelihood: medium. Facts, which
  the previous draft got wrong in both directions: `ALTER TYPE ... ADD VALUE`
  **is** transactional on PostgreSQL 12 and later, so it runs inside an
  ordinary Alembic migration — the upgrade cost was overstated. But the new
  value **cannot be used in the same transaction that added it**, so a widening
  plus a backfill must be two migrations; and there is **no `DROP VALUE`**, so
  `downgrade()` requires the four-statement type swap (`CREATE TYPE ..._new`,
  `ALTER TABLE ... TYPE ..._new USING status::text::..._new`, `DROP TYPE ...`,
  `ALTER TYPE ..._new RENAME TO ...`). That collides with INV-MIG-2, which
  makes reversibility a standing criterion, and there is **no
  `ALTER TYPE ... ADD VALUE` precedent anywhere in `alembic/versions/`**.
  Mitigation: keep native enums (D-5) and put the downgrade recipe verbatim in
  ADR-024 so the next author does not invent it under pressure.

- **Risk 8: the architecture gate passes while a port imports an adapter.**
  Severity: medium. Likelihood: low today, rising as the port file grows.
  Evidence: `episodic.canonical.generation_run_ports` and
  `episodic.canonical.generation_run_errors` are in no Hecate group, and
  `hecate.checker` returns early when either side of an import edge is
  ungrouped. `make check-architecture` would stay green if Stage C step 7's
  docstring work, or a later edit, imported `episodic.canonical.storage` from
  the port module. Mitigation: D-12 adds both modules to `domain_ports` in
  EP-M2, with a negative control proving the gate then fires.

- **Risk 9: the shared contract suite certifies a shared blind spot as
  correct.** Severity: medium. Likelihood: medium. Evidence: neither adapter
  checks that `create_checkpoint` targets a non-terminal run, nor that a
  created checkpoint starts in `created`. Both share the hole, so
  "behaviourally interchangeable" would be proven true and still wrong.
  Mitigation: INV-CKPT-5 closes it in both adapters in one commit.

## Progress

- [x] (2026-10-20 20:32Z) EP-M0 Stage A: orientation, production **and test**
      sweep (no changes). Baseline measured; all expectations re-confirmed
      against the tree; no deviation found.
- [x] (2026-10-20 23:20Z) Stage B: red tests written for EP-M1, EP-M2, and
      EP-M3. All five steps landed; every new test fails for the intended
      reason. Stage B's closing condition is met: **36 failed, 24 passed**,
      with every failure an `AttributeError` on a missing checkpoint method, a
      missing table, or `DID NOT RAISE` on an adapter precondition — no import
      error, no fixture typo, no foreign-key violation. The milestones below
      stay unticked: red tests are evidence about what is absent, not
      implementation. Two deviations, both recorded as decisions: the SQL
      driver is a sibling module, not `test_generation_runs.py` (**D-14**), and
      the duplicate-identifier error is named `CheckpointAlreadyExists`
      (**D-13**). One non-vacuity obligation is deferred and cannot be
      discharged here — see the last observation under
      *Surprises & discoveries*.
- [x] (2026-10-21) EP-M1: `review_checkpoints` table, ORM model, reversible
      migration. Revision `20261020_000014` with its two native enums, both
      `.drop(bind, checkfirst=True)` calls, the options-array and
      responded-fields check constraints, and the two indexes.
- [x] (2026-10-21) EP-M2: `SqlAlchemyReviewCheckpointStore`, composite port
      adapter, unit-of-work wiring, commit-safety warning.
- [x] (2026-10-21) EP-M3: shared checkpoint contract scenarios across both
      adapters, plus durability and sequencing evidence.
- [~] Stage C repaired and re-verified in part; EP-M4 stays gated. Gates now
      observed on this revision: `ruff format --check` → `637 files already
      formatted`; `ruff check` → `All checks passed!`; the df12 rule set
      (`R9101`–`R9111`) → `10.00/10`, no findings; `C9112` → `10.00/10`, no
      findings. The seven affected suites give **89 passed** where the same
      selection previously gave 17 failed / 38 passed, in 18s rather than
      1,154s.
      Two corrections of record against the earlier entry. First, the 16
      `ConnectionTimeout` failures were **not** host contention: they reproduce
      in isolation on an idle host, and the cause is that the SQL scenario
      driver's `store` fixture held one unit of work open while each hook opened
      a second connection, which `py-pglite`'s single WebAssembly backend never
      grants. Fixed by making the driver commit before it reads, per the plan's
      "commit-plus-new-unit-of-work" instruction. Second, `make lint` had been
      aborting inside the df12 step, so `ambrleaks`, Skylos dead-code, and the
      nose duplication gate were **unverified rather than passing**; the
      `C9112` findings above were only reachable once that abort was cleared.
      Still outstanding: `make lint` and `make test` verdicts on the repaired
      revision. (2026-10-21)
- [x] (2026-10-21) EP-M3 committed as `60f8f740`; `make test` green on that
      commit — **1784 passed, 1 skipped, 0 failed, 0 errors** in 186.17 s,
      against a Stage A baseline of 748.53 s with 1 failed + 1 error. The
      fifteen-per-cent growth tolerance is met with a 75 per cent *reduction*
      in wall clock, confirming the baseline was contention-dominated rather
      than the change being cheap. Both previously-red checkpoint suites now
      pass in full (23 contract tests; 16 pricing-migration tests). The single
      skip remains the pre-existing `EPISODIC_RUN_DOCKER_TESTS` opt-in.
- [x] (2026-10-21 05:05Z) Stage C negative controls: **all four discharged**
      against frozen candidate `60f8f740`. INV-MIG-2 both enum drops fail
      independently; INV-SEQ-1's cross-run predicate removal fails two property
      tests; INV-CKPT-3's `set()` and scalar-options breaks each fail the
      fidelity assertion they cover; INV-CKPT-2 fires **only** on the
      stale-writer route — the plan's stated sequential route is falsified, and
      the Verification plan has been corrected accordingly. Transcripts under
      *Artefacts and notes*. Every break was reverted; the four touched files
      are byte-identical to the commit and `git status --porcelain` is empty.
- [x] (2026-10-21) **Stage C fully green.** All seven gates ran as complete
      ordered lanes against `74f84a64`, sequentially, with HEAD verified
      unchanged before and after: `make check-fmt` (824 files already
      formatted; mdtablefix 127 unchanged), `make lint` (55 s — **every step
      ran**, including the three that had never executed on this branch:
      `ambrleaks`, the blocking Skylos dead-code scan, and the nose duplication
      gate, which passed with "30 allowed by reasoned exceptions"),
      `make typecheck` (`ty 0.0.32` — all checks passed), `make markdownlint`
      (127 files, 0 issues), `make nixie` (all diagrams validated),
      `make check-migrations` (15 migrations applied through `20261020_000014`,
      then `compare_metadata` reached — the log's final line is the `SAWarning`
      raised from `migration_check.py:44`, which executes only after every
      migration is applied, and exit 0 is reachable only past the `if diffs:`
      block), and `make test` (**1784 passed, 1 skipped, 30 warnings in
      170.70 s**; 55 snapshots passed; no `pytest-timeout` kill). No gate
      required a retry.
      The `make lint` result matters more than its exit code: the earlier
      overstatement was that an abbreviated run had passed, and the specific
      risk was that the *later* steps had never run at all. They now have, and
      the log shows each printing its own trailing output after the pylint
      steps rather than the recipe aborting behind them.
- [x] (2026-10-21) Removed one stale nose duplication allow entry reported by
      the now-running gate (`storage/generation_runs.py` ~
      `adapters/generation_runs.py`). Pre-existing rather than introduced here
      — added in `d9e5ac0d` (2026-09-25), and neither member is touched by this
      slice; the duplication stopped matching after `e1cda7a7` (2026-10-03).
      Removed anyway because `AGENTS.md` asks for it and because a dormant
      entry is a latent hazard: if those modules drift back into a shared
      block, the entry silently suppresses the finding and nothing announces
      that it went live. `make lint` re-run green afterwards.
- [x] (2026-10-21) EP-M4: lease-reclamation primitive. Stage D steps 1–5 all
      landed. `fail_expired_leases` sits on the composite `GenerationRunPort`
      only, declared in the new `episodic/canonical/generation_run_lease_ports.py`
      because it is the union of repository and event-log behaviour rather than
      either alone; the SQL mixin reclaims with a correlated `NOT EXISTS`
      checkpoint guard, and the in-memory adapter is an honest no-op whose
      docstring says the emptiness is a divergence and that a shared suite must
      not treat agreement as evidence. Revision `20261020_000015` adds the
      partial index in its **own** revision with `000014` untouched, and both
      the migration and the ORM index consume one shared predicate constant
      (D-20). Both duplicated test helpers are now port calls, and the de-
      duplication surfaced a real assertion gap that the merge closed. No
      scheduler, worker, or beat entry was added, per the Risk 3 gate.
      Focused suite: **36 passed**. `make check-migrations` exit 0 with
      `Running upgrade 20261020_000014 -> 20261020_000015`. Ruff, `make
      typecheck`, `make fmt`, and `make markdownlint` all clean. Every touched
      code file is within the 400-line ceiling. The first gate attempt was
      **red**: stock Pylint 4.0.9 scored 10.00/10, but the next recipe line,
      `$(DF12_PYLINT)`, failed with `C9105 reexport-by-assignment` on
      `generation_run_schema.py:13`, aborting `make lint` at Makefile:145 and
      leaving C9112, `ambrleaks`, Skylos, and the nose duplication gate
      unrun. Repaired by inlining the interpolated status into the predicate
      and dropping the unconsumed export (see the surprise below); the repair
      is behaviour-preserving, with the predicate still evaluating to
      `status = 'running'`. The Stage D audit gates and the milestone CLI
      review are recorded below once dispatched.
- [ ] EP-M5: documentation, ADR-024, and roadmap reconciliation.

Record a timestamp against each item as it completes, in the form
`- [x] (2026-10-20 14:05Z) EP-M1 ...`.

## Surprises & discoveries

- **Observation: roadmap 2.6.2 is materially pre-built.** Durable persistence
  for `GenerationRun` and `GenerationEvent`, the `20260624_000010` migration,
  and sequencing property tests all already exist. Evidence:
  `episodic/canonical/storage/generation_runs.py` (now 358 lines),
  `generation_run_models.py`,
  `alembic/versions/20260624_000010_add_generation_run_tables.py`,
  `tests/canonical_storage/test_sql_generation_run_property_contract.py`. All
  landed in commit `5af0638` under
  `docs/execplans/4-3-2-no-qa-generation-runs-and-tei-p5-retrieval.md`, whose
  scope statement leaves "human-review checkpoint persistence (2.6.2)" and "an
  automated stuck-run recovery worker (2.6.2)" out of scope. Impact: this plan
  is scoped to the remaining gap. See D-1.

- **Observation: py-pglite serializes *all* transactions globally.** It is a
  single WebAssembly PostgreSQL backend, so only one transaction executes at a
  time. Evidence: two independent probes during design review. (a) A session
  holding `SELECT ... FOR UPDATE` on a row blocked a second session's
  `FOR UPDATE NOWAIT` on the same row — which on real PostgreSQL returns error
  `55P03` *immediately* — until the holder committed. (b) Decisively, a holder
  with an open transaction also blocked an **unrelated** connection's
  `SELECT 42`. (c) Two concurrent `append_event` calls returned `[1, 2]` *both
  with and without* the run-row lock, and instrumented traces showed the second
  appender did not issue its first statement until after the first committed.
  Impact: this falsifies the previous draft's AXIOM-3. Every `asyncio.gather`
  test in `tests/canonical_storage/` is measuring sequential replay, not
  concurrency. Those tests remain valid evidence for compare-and-set predicate
  logic; they are **not** evidence about lock behaviour, and this plan no
  longer cites them as such. See AXIOM-3 and Risk 2.

- **Observation: the API design does not require gapless sequences.** It
  requires *prefix stability*. Evidence: `docs/episodic-tui-api-design.md` —
  half-open paging needs monotonicity; `run.ack(seq)` and `resume_from` need a
  total order and a resumable cursor. The only place contiguity is assumed is
  the backpressure heuristic at lines 629–633, which treats a `seq` difference
  as an event count; with gaps it over-estimates lag and compacts early. That
  is a soft heuristic, not a correctness requirement. Impact: D-3's rationale
  is rebuilt on the stronger, true argument.

- **Observation: the in-memory adapter cannot honestly implement lease
  reclamation.** `lease_expires_at` is a storage column with no domain
  counterpart: `run_to_record` hardcodes `lease_expires_at=None`,
  `run_from_record` never reads it, and `InMemoryGenerationRunStore` documents
  that it "does not retain it: `GenerationRun` has no lease field". Impact:
  shapes D-6's port placement.

- **Observation: the lease-reclamation transaction already exists three
  times** — `_recover_expired_lease` in
  `tests/canonical_storage/test_sql_generation_run_property_contract.py`,
  `_manually_fail_expired_run` in
  `tests/canonical_storage/test_generation_run_claims.py`, and the manual SQL
  runbook in `docs/developers-guide.md`. None is production code and all three
  must stay in step. Impact: this is the strongest argument *for* EP-M4, and it
  is now in D-6.

- **Observation: `StaleEventSequence` is declared, never raised, never
  imported.** `episodic/canonical/generation_run_errors.py` declares it with a
  `# noqa: N818` suppression. ADR-015 decided that "event sequence allocation
  is owned by the adapter, not the caller", which makes the error unreachable
  by construction. Impact: dead surface that will eventually trip Skylos.
  Deleting it touches a frozen module, so it is recorded as a follow-up rather
  than actioned here.

- **Observation: the architecture gate does not see the generation-run port
  modules.** Evidence: `[tool.hecate.groups]` lists `episodic.canonical.domain`,
  `domain_generation`, `ports`, and `unit_of_work_protocols` under
  `domain_ports`, but neither `generation_run_ports` nor
  `generation_run_errors`. Hecate's `first_matching_group` uses dotted-segment
  prefixes, so `episodic.canonical.domain` does not cover them, and
  `checker.py` skips any edge with an ungrouped endpoint. Impact: the hexagonal
  constraint was unenforced for exactly the files this slice edits. See D-12
  and Risk 8. (2026-10-18)

- **Observation: the migration number and ADR number this plan reserved were
  taken while it sat in review.** `20261010_000013` (pricing snapshot
  constraint) and ADR-020 to ADR-023 landed on `main`. Impact: revisions are now
  `000014` and `000015`, and the ADR is ADR-024. Any further delay will repeat
  this; Stage A re-checks both. (2026-10-18)

- **Observation: widening `CanonicalUnitOfWork.generation_runs` is lower risk
  than the previous draft rated it.** Exactly one class declares the attribute:
  `SqlAlchemyUnitOfWork`, an explicit protocol subclass, so `make typecheck`
  checks the assignment directly. Every other unit-of-work double in the tree
  is a structural stub reached through `typ.cast` and none declares
  `generation_runs`. The one additional implementer to update is
  `NoopGenerationRunPort` in
  `tests/test_generation_run_port_contract_support.py`, which already stubs all
  five checkpoint methods; only `list_checkpoints` (and, under EP-M4,
  `fail_expired_leases`) must be added. Re-confirmed 2026-10-18.

- **Observation: Stage B step 2 cannot "still pass" as written, and that is
  the finding rather than a defect in the work.** The step says re-pointing
  `tests/test_generation_checkpoint_port_contract.py` at the shared scenarios
  is "a pure refactor and the safety net for step 3" that "must still pass". It
  does not: four scenarios fail against `InMemoryGenerationRunStore` with
  `DID NOT RAISE` — the three `creation_rejects_terminal_status` cases and
  `creation_rejects_duplicate_identifier`. Evidence: that is precisely what
  INV-CKPT-5 asserts about the current tree, "neither adapter checks either
  today", and its rationale names the in-memory overwrite explicitly. A shared
  suite that passes against an unguarded adapter would be certifying the
  divergence as interchangeable — the Risk 8 blind spot. Impact: the step's
  premise holds for the *other* nineteen scenarios, which do pass unchanged and
  are the real safety net; the four failures are the intended INV-CKPT-5 red,
  surfaced one stage earlier than the plan sequenced it. Re-pointing stays a
  genuine no-behaviour-change refactor — the four failures are assertions the
  old module did not make. (2026-10-20)

- **Observation: the domain forbids constructing a `RESPONDED` checkpoint
  without its response fields, which constrains every fixture that builds one.**
  `Checkpoint.__post_init__` routes to `_validate_responded_fields`, so
  `make_checkpoint(..., status=RESPONDED)` with `responded_at=None` raises
  `ValueError: responded checkpoints require responded_at.` — not the
  `CheckpointAlreadyTerminal` a creation-precondition scenario expects. Impact:
  the shared factory must populate `responded_at`, `responded_by`, and
  `response_action` for `RESPONDED` (and `responded_at` for the other two
  terminal states, which the domain permits to be bare). Caught by the first
  run of the re-pointed driver; a fixture typo of exactly the kind Stage B's
  closing condition rules out as an acceptable red. (2026-10-20)

- **Observation: Stage B step 3's "into
  `tests/canonical_storage/test_generation_runs.py`" is not affordable, and
  Stage A's own headline finding said so.** That module is 368 lines against a
  **hard** pylint `max-module-lines = 400`, and `PYLINT_TARGETS` includes
  `tests`, so the cap binds. A SQL driver needs one `@dc.dataclass` bundle of
  hooks, one `pytest_asyncio.fixture` to build them, and nine thin wrappers
  each carrying a docstring and a `prepare_run`/`read_fresh` call — roughly 130
  lines, against 32 available. The result would be a 500-line module that fails
  `make lint` outright. The plan's intent is unambiguous and is stated twice:
  "New SQL contract scenarios belong here, **not in a parallel module**."
  Impact: the wrappers go into a sibling
  `tests/canonical_storage/test_generation_run_checkpoint_contract.py`, which
  is not a *parallel* suite — it is a driver for the shared scenario module
  exactly as `tests/test_generation_checkpoint_port_contract.py` is, so there
  is still one definition of each checkpoint contract and no duplicated
  assertions. `test_generation_runs.py` keeps its run- and event-level
  scenarios untouched. Recorded as D-14. (2026-10-20)

- **Observation: the first SQL driver run was not a red at all, and only a
  control run could tell the difference.** It reported 23 errors, every one
  `Failed: Timeout (>180.0s) from pytest-timeout` — but the whole run took
  `180.66s`, which is one wall-clock, not 23. All 23 were `ERROR at setup`, and
  the captured setup log shows PGlite reaching "PGlite server started
  successfully" before hanging. The host was at load average 27–36 on 6 cores
  with all 4 compile slots held. Re-running the **pre-existing**
  `tests/canonical_storage/test_generation_runs.py` as a control gave
  `10 passed in 9.05s`, which localizes the cause to the environment rather
  than to the new module; the driver then re-ran clean in 9.49s. Lesson worth
  keeping: a red that is uniformly a setup timeout across every test, with a
  total runtime equal to the timeout, is a fixture stall and carries no
  information about the code under test. The control run is what makes that
  distinguishable, and it costs 9 seconds. (2026-10-20)

- **Observation: `SqlAlchemyUnitOfWork.__aexit__` does not commit, so the
  durability scenario must commit explicitly — and a failing scenario leaks its
  open session.** The step "the unit of work is committed and closed" therefore
  cannot be pure Gherkin decoration; it is the only thing that persists the
  response. More sharply, when the scenario fails *before* that step, the unit
  of work is never closed and SQLAlchemy emits
  `SAWarning: The garbage collector
  is trying to clean up non-checked-in connection … [INTRANS]`.
  That warning appeared in the first successful red and is a real defect in
  the step module, not noise: it is the same class of leak Risk 4 describes.
  Fixed by holding the unit of work open on a `contextlib.AsyncExitStack`,
  which the context's `tear_down()` closes; pylint then flagged the initial
  `__aenter__`/`__aexit__` calls directly as `C2801 unnecessary-dunder-call`,
  which is what pointed at the exit stack. The `SAWarning` is the signal that
  this worked. (2026-10-20)

- **Observation: three of the eight new Step 4 tests cannot be red, by
  construction, and one passes vacuously.**
  `test_review_checkpoint_migration_creates_table_and_enums`,
  `test_upgrade_downgrade_upgrade_leaves_schema_identical`, and
  `test_review_checkpoints_keeps_its_check_constraints` fail today for the
  intended reason (no table), but `test_downgrade_removes_table_and_both_enums`
  **passes** — there is nothing to drop yet, so
  `"review_checkpoints" not in _table_names(...)` holds and
  `_enum_types(...) == set()` holds trivially. It becomes discriminating only
  once revision `000014` exists. This is worth stating rather than counting as
  a red: INV-MIG-2's non-vacuity requirement ("remove either explicit
  `.drop(bind, checkfirst=True)` call and the test must fail; verify both fail
  independently") is an obligation for **Stage C**, not something Stage B can
  discharge, and it cannot be discharged by a green run. (2026-10-20)

- **Observation: the migration test must reach the new revision as `head`, not
  by name.** The plan writes the revision as
  `alembic/versions/YYYYMMDD_000014_add_review_checkpoints.py` and dates it "on
  the day it is written", so its literal identifier is not knowable when the
  test is written. Hard-coding `"20261020_000014"` produced
  `ResolutionError: No such revision or branch '20261020_000014'` — a failure
  about the test's own coupling, which Stage B's closing condition explicitly
  rules out. Using `"head"` for the upgrade removes the coupling and is
  equivalent here, because the migration under test is the head. (2026-10-20)

- **Observation: Stage C step 9's pending-state test is vacuous as written, and
  the defect is real.** The plan specifies
  `session.new or session.dirty or session.deleted` as the trigger for the Risk
  4 warning. Probe evidence shows that predicate cannot see either write path
  this slice cares about: a `flush()` empties `.new`, and a **core** `UPDATE`
  issued through `Session.execute` — which is exactly how D-10's
  compare-and-set transition persists — populates none of the three collections
  at all. `SqlAlchemyReviewCheckpointStore._resolve` uses that core `UPDATE`,
  so INV-COMMIT-1's warning would never fire on the transition it was written
  to guard. Confirmed by `test_uncommitted_response_does_not_persist` failing
  on its warning assertion while its persisted-state assertion passed. Fixed
  with `episodic/canonical/storage/session_write_tracker.py`, which listens for
  `before_flush` and `do_orm_execute`, reading `is_insert`, `is_update`, and
  `is_delete` off the execute state — the two events every write passes through
  regardless of shape. A design that cleared the flag on `after_commit` was
  rejected: that event also fires on savepoint release, and `create_checkpoint`
  wraps its insert in `begin_nested()`. Non-vacuity: reverting
  `_has_pending_changes` to the original predicate makes the test fail again,
  and the tracker has its own seven-case suite covering the reads and no-op
  flush that must *not* count. (2026-10-21)

- **Observation: `caplog` cannot observe the Risk 4 warning, whatever the
  predicate.** `episodic.logging.get_logger` returns a femtologging
  `FemtoLogger`, not a stdlib `Logger`, and its records never reach a stdlib
  handler — verified directly. The plan's INV-COMMIT-1 test as drafted would
  therefore have failed even once the write detection was correct. The warning
  is now emitted as a structured event
  (`canonical_unit_of_work.closed_with_uncommitted_changes`) through the same
  `log_event` helper the storage adapters use, and asserted by patching
  `_log_event` — the pattern
  `tests/canonical_storage/test_workflow_checkpoint_payload_observability.py`
  already uses. This is a strict improvement on the plan's intent: the event is
  greppable *and* observable, which a bare `logger.warning` was not.
  (2026-10-21)

- **Observation: the 16 `ConnectionTimeout` failures were a defect in this
  slice's test driver, not host contention.** The first gate run attributed
  them to "suspected host contention" at low confidence. That is falsified:
  running `test_creation_persists_checkpoint` alone on an idle host reproduces
  it after 68.08s, which is the connection string's `connect_timeout=60` and
  nothing else. The mechanism is in
  `tests/canonical_storage/ test_generation_run_checkpoint_contract.py`. Its
  `store` fixture yielded a composite port bound to an *open* unit of work, and
  every hook that observes committed state then opened a *second* session.
  `py-pglite` serves one WebAssembly PostgreSQL backend, so the second
  connection is never granted and the scenario dies on the connect timeout. The
  pass/fail split confirms it: all 16 failures use `read_fresh` or
  `count_checkpoints`, and all 7 passes use neither. Fixed by sharing one
  `scenario_uow` fixture between `store` and the hooks, and committing it
  before any observation — the plan's "commit-plus-new-unit-of-work" shape. With
  `NullPool` the commit closes the DBAPI connection, releasing the backend. 16
  failures at ~68s each became 23 passes in 7.51s. The general lesson: under
  `py-pglite` a test that needs to observe committed state must not hold a
  session open while it observes, and a `ConnectionTimeout` is a
  connection-contention signal long before it is a host one. (2026-10-21)

- **Observation: `make lint` aborting inside the df12 step hid three later
  gates.** The df12 pylint step exited 24, so `ambrleaks`, the blocking Skylos
  dead-code scan, and the nose duplication gate never ran on this branch. After
  the df12 findings were repaired, re-running revealed five `C9112`
  (`redundant-future-annotations`) findings in this slice's own new test
  modules — a real gate failure that the abort had masked. The branch is on a
  3.14 baseline, where `from __future__ import annotations` is redundant. An
  aborted lint run means every later gate in the recipe is **unverified**, not
  passing, and the record must say so. (2026-10-21)

- **Observation: the pricing migration tests coupled to `"head"`, and this
  slice's revision broke them.** `20261020_000014` chains off
  `20261010_000013`, so every place the pricing suite asked for `"head"` began
  resolving one revision further up and pulling this slice's
  `review_checkpoints` SQL into assertions and offline snapshots about pricing.
  The fix is to pin the pricing revision explicitly (`_PRICING_REVISION`) at
  the five sites that targeted `"head"`, which *uncouples* the suite rather
  than re-baselining it: the two syrupy snapshots still pass **unchanged**,
  because the offline range once again spans exactly the one migration under
  test. Had the snapshots been regenerated instead, the suite would have kept
  the coupling and grown an unexplained dependency on a later revision's SQL.
  The general lesson: a migration test that says `"head"` is asserting about
  every future migration too. (2026-10-21)

- **Surprise: the INV-CKPT-2 negative control as written in the Verification
  plan could not fire, and the reason was a real property of where the guard
  lives — not a weak test.** The plan's route ("widen the predicate; confirm
  every terminal case fails") produced **23 passed**. `_resolve` calls
  `transition(checkpoint_from_record(record))`, and
  `Checkpoint.respond`/`time_out`/`cancel` each call `_raise_if_terminal()`
  *inside* that call, before `_resolve` builds the `UPDATE`. So every terminal
  case is refused by the domain, the statement is never issued, and no
  predicate can be what rejects it. Whole-suite instrumentation:
  `CAS_RESOLVE_ENTERED: 27`,
  `DOMAIN_GUARD_RAISED CheckpointAlreadyTerminal: 10`, `LOST_RACE_ENTERED: 0`,
  and 14 `UPDATE`s issued for exactly the 14 *successful* transitions. The
  predicate is nonetheless load-bearing — a caller holding a **stale
  pre-terminal** copy reaches the `UPDATE`, and under the widened predicate it
  silently overwrites a terminal row instead of raising. The lesson generalizes
  to the next test of this shape: a compare-and-set predicate is only exercised
  by a caller whose view is stale, and "mutate the row between two sequential
  calls" does not produce one when the domain re-reads and re-guards on every
  call. (2026-10-21)

- **Observation: the green-suite figure is the honest one, and the earlier gate
  figure was not.** The EP-M3 entry above had recorded `make lint`,
  `make check-fmt`, and `make typecheck` as passing. Reading the logs showed
  the post-repair runs were **per-step, out of lane order, and before** commit
  `60f8f740`. Complete ordered lanes have not been observed on that commit and
  the Progress entry now says so. A step-by-step pass is not a lane pass: the
  recipe's later steps are the ones that abort, and a lane that aborted is
  unverified rather than green — the same failure mode as the df12 abort
  recorded above, which is exactly how it went unnoticed the first time.
  (2026-10-21)

- **Observation: Stage D's "delete the duplicates" step was the whole point,
  and the two helpers had already drifted apart.** `_recover_expired_lease` in
  `test_sql_generation_run_property_contract.py` appended
  `payload={"error_category": "launcher.lease_expired"}` — category only —
  while its own `update_run_status` call wrote **both** category and message.
  Nothing observed the disagreement, because both were the same hand-rolled
  transaction under test and no assertion compared them. Re-expressing the
  helper as a call to `fail_expired_leases` forced the question, and the richer
  pair won, so the run's error fields and its event payload now agree. The
  lesson: a duplicated transaction is not merely extra text, it is an
  independent chance to drift, and only the de-duplication makes the drift
  visible. (2026-10-21)

- **Observation: the plan's own predicate literal was a fourth specification of
  the same fact.** Stage D step 4 writes
  `postgresql_where=sa.text("status = 'running'")` and asks for it to be
  "mirrored exactly in the ORM `__table_args__`". Two literal copies of a
  predicate that Alembic **provably cannot compare** (alembic#750:
  partial-index predicates are outside what `compare_metadata` reaches, so
  `make check-migrations` reports no drift however far the two diverge) is a
  guard that fails open. The landed form shares one constant,
  `GENERATION_RUN_EXPIRED_LEASE_PREDICATE_SQL` in
  `episodic/canonical/storage/generation_run_schema.py`, and both sites
  `sa.text(...)` that. The cited precedent (`reference_document_schema.py` plus
  `20260228_000004`) shares *values* — the enum members interpolated into
  f-strings — but still writes predicate text at each site, and the ORM side
  uses SQLAlchemy expressions rather than matching text, so it does not close
  this hole either. Sharing the predicate text is a deliberate strengthening of
  the precedent, not a departure from it. (2026-10-21)

- **Observation: `SKIP LOCKED` was considered and deliberately not used.**
  Stage D does not request it. It was ruled out because AXIOM-3 holds: under
  `py-pglite`'s single WebAssembly backend every session serializes, so no test
  can show the clause skipping a locked row. Shipping it would assert a
  concurrency guarantee nothing here demonstrates. `expired_lease_candidates`
  documents the omission, and `grep -rn "skip_locked" episodic/` returns
  nothing. (2026-10-21)

- **Observation: a lease expiry is not proof of abandonment, and the plan
  accounted for this only on the code side.** The checkpoint clause was
  specified for `fail_expired_leases` but not for the manual SQL runbook in
  `docs/developers-guide.md`, which is the copy an operator actually runs. A
  run suspended at a human-review checkpoint is legitimately `running` while it
  waits, and its lease expires regardless, so the unguarded runbook would fail
  exactly the runs the review mechanism exists to protect. The runbook gained
  the same `NOT EXISTS` predicate as the primitive, preceded by a read-only
  diagnostic `SELECT`. (2026-10-21)

- **Observation: the aborted-df12 lesson recurred on EP-M4, and a green stock
  Pylint is what made it recur.** The observation above records this failure
  mode for the Stage C revision; EP-M4 repeated it, which is itself the
  finding. The artisan reported "pinned Pylint 4.0.9 at 10.00/10 on every
  touched file" and that was literally true — but it had run only `$(PYLINT)`,
  the stock step with `--load-plugins=` empty. `C9105` is emitted **only** by
  `$(DF12_PYLINT)` on the next recipe line, so no amount of green stock-Pylint
  evidence could have found it. Two corollaries worth carrying forward: a
  *score line* is not a verdict — 10.00/10 is computed across ~800 files, so a
  single convention message rounds away, while the same finding measured on an
  isolated two-statement probe scores 5.00/10; and the exit code, not the
  score, is what `make` acts on. Only the Makefile recipe is evidence of a
  passing lint. (2026-10-21)

- **Observation: the EP-M4 `C9105` hit a constant that nothing consumed.** The
  flagged line was
  `GENERATION_RUN_RUNNING_STATUS = GenerationRunStatus.RUNNING .value`,
  exported in `__all__` but referenced in exactly three places — its own
  definition, the f-string on the next line, and `__all__` itself. Both real
  consumers (`generation_run_models.py` and the `000015` migration) import only
  the index name and the predicate. The honest repair was therefore to inline
  `GenerationRunStatus.RUNNING.value` into the predicate and drop the name, not
  to re-export it via a from-import: satisfying the checker by adding an import
  would have preserved an export no one consumes. The predicate still evaluates
  to `status = 'running'`, verified by exec-ing the old and new modules side by
  side. The shared-constant guard survives because what both sides must agree
  on is the *predicate*, and that constant remains. (2026-10-21)

Append further observations here as work proceeds.

## Decision log

- **D-1. Scope this slice to the genuine remaining gap.**
  Rationale: run and event persistence, the migration, and sequencing property
  tests already exist. Redelivering them would churn a working, tested adapter.
  The gap is checkpoint persistence, a composite-port implementation,
  cross-adapter contract equivalence, and the lease-reclamation primitive that
  4.3.2 deferred here by name. Date/Author: 2026-08-23, planning agent.

- **D-2. Use composition, not a mixin — and keep the table.**
  Two questions, answered together because the review challenged both.

  *Composition over inheritance.* The previous draft proposed a
  `SqlAlchemyGenerationCheckpointMixin` mirroring the in-memory adapter's
  mixin. Rejected. The in-memory mixin is a legitimate mixin: it shares genuine
  mutable in-process state with its host — `_lock`, `_runs`, `_checkpoints` —
  and reads `self._runs` *while holding the host's lock*, which cannot be
  expressed by delegation without leaking the lock. The SQL equivalent shares
  only `_session` and `_runtime`, both constructor-injectable in one line.
  There is no shared mutable state and no shared lock, so inheritance buys
  nothing and costs a bidirectional coupling: the mixin would need the host's
  private `_get_record` to validate the parent run, i.e. a base class reaching
  upward into its subclass. It also re-declares `_session` and `_runtime` as
  bare annotations, a second declaration site that can silently drift from
  `__init__`. `AGENTS.md` says "use functions and composition"; this is
  file-splitting wearing a design costume. Further, ADR-015 argues *against*
  the mixin: its stated benefits are that "tests can fake only the sub-port
  they exercise" and that "the later SQL adapter can use different locking and
  uniqueness strategies for run state, events, and checkpoints". A
  non-instantiable mixin denies both, because no SQL object would implement
  `GenerationCheckpointPort` alone. Decision: an instantiable
  `SqlAlchemyReviewCheckpointStore(session, *, runtime=None)`, plus a thin
  composite that holds both stores and delegates. Note that "one attribute on
  the unit of work" and "one class" are orthogonal: a composite delegator
  satisfies `uow.generation_runs: GenerationRunPort` just as well as a mixin
  would.

  *Why a table at all.* Design review raised a genuinely different alternative:
  do not persist checkpoints as rows. Fold `CheckpointStatus` over the existing
  event log (`checkpoint.created`, `checkpoint.responded`, …), project
  `get_checkpoint` as a read model, and let the run-row lock that
  `append_event` already takes enforce terminality. That removes EP-M1 entirely
  — no table, no two native enums, no migration, no `downgrade()`, no
  `ALTER TYPE` debt — and gives one source of truth for run history. It is
  rejected, but on narrow grounds that should be revisited if they change.
  First, `GenerationCheckpointPort.get_checkpoint(checkpoint_id)` addresses a
  checkpoint by bare identifier with no run id; an event fold would need an
  expression or GIN index on `payload->>'checkpoint_id'`, a JSONB indexing
  pattern used nowhere in this repository. Second, the alternative partially
  reverses ADR-015's separation of `Checkpoint` from `WorkflowCheckpoint` and
  so needs an ADR *amendment*, not just a new ADR. Third, `Checkpoint` is
  frozen for this slice by `Constraints`, and the fold changes
  `create_checkpoint` semantics. Recorded honestly: the deciding question is
  whether any query needs a cross-run list of open checkpoints — a reviewer
  inbox. On the current API surface there is none; checkpoints are only ever
  addressed as `POST /v1/generation-runs/{run_id}/checkpoint`. If 2.6.3 and the
  TUI roadmap never introduce such a query, this table is speculative
  normalization of data the event log already stores gaplessly and
  transactionally. Revisit before adding any second checkpoint-shaped table.
  Date/Author: 2026-08-23, planning agent.

- **D-3. Keep pessimistic row locking, on the prefix-stability argument.**
  The previous draft justified this by saying the `after_seq` replay contract
  requires *gapless* sequences. That is not what the API document says. What
  `after_seq` polling actually needs is **prefix stability**: once a reader has
  seen up to sequence S, nothing with sequence ≤ S may become visible later.
  Gaplessness is sufficient but not necessary. The true argument is stronger.
  Taking `SELECT ... FOR UPDATE` on the run row before allocating means
  **allocation order equals commit order**, which *is* prefix stability,
  directly. Keep the existing pattern for that reason, with
  `UNIQUE (generation_run_id, seq)` as defence in depth. Alternatives, with
  verdicts:
  - *Global `BIGSERIAL` plus client-side ordering* — **incorrect**, not merely
    inelegant. A transaction that took sequence 5 can commit after one that
    took 7, so a client that has paged past 7 never sees 5. That is silent
    event loss on the `after_seq` path.
  - *Optimistic append with unique-violation retry* — viable, roughly a wash.
    It preserves prefix stability (a duplicate-key insert blocks on the unique
    index until the winner commits, then fails and retries) and stops
    `append_event` contending with `update_run_status`. Costs a `begin_nested()`
    savepoint per attempt — an idiom already used in `create_run` — plus a
    retry bound. Under the actual write pattern (one launcher owns a run)
    contention is near zero, so it is cheaper in the common case. Not worth
    rewriting a working path for.
  - *CTE-guarded conditional insert* — requires the caller to supply the
    expected sequence, which ADR-015 forbids ("event sequence allocation is
    owned by the adapter, not the caller"). Do not reopen without amending
    ADR-015. It would, however, make `StaleEventSequence` reachable.
  - *Advisory `pg_advisory_xact_lock(run_id)`* — reject. A second, invisible
    mutual-exclusion regime alongside `FOR UPDATE`; 64-bit hashing can
    false-serialize unrelated runs; and its only benefit is also delivered by
    optimistic append.
  - *Per-run counter column with `UPDATE ... RETURNING`* — **the identified
    strict improvement, deliberately deferred.**
    `UPDATE generation_runs SET next_seq = next_seq + 1 WHERE id = :id AND
    status NOT IN (…) RETURNING next_seq` replaces the `SELECT … FOR UPDATE`
    *plus* `SELECT MAX(seq)` with one statement that both locks and allocates:
    identical guarantees, one fewer round trip, and the sequence stops
    depending on the contents of `generation_events`, so future archival cannot
    renumber a stream. This is Temporal's `next_event_id` and Marten's
    `mt_streams.version`. Deferred because it needs a column plus a backfill
    and would double EP-M1's migration risk for no benefit to this slice.
  Prior art supports the choice: gapless per-stream numbering is always bought
  with a single writer per stream — server-enforced (EventStoreDB, Kafka),
  lock-enforced (Marten), or compare-and-set-enforced (Temporal). Marten's most
  complex subsystem, its high-water-mark agent, exists solely because its
  *global* sequence is a PostgreSQL sequence and therefore gappy. Date/Author:
  2026-08-23, planning agent.

- **D-4. Store `Checkpoint.options` as `JSONB`, with a shape guard.**
  Rationale: `postgresql.ARRAY` is used nowhere in this repository; `JSONB` is
  the established convention and preserves array order, which is all `options`
  needs. But JSONB does not enforce element type, and the domain validator will
  not catch the gap: if the column holds the JSON string `"approve"`, a naive
  `tuple(record.options)` yields seven single-character strings, which are all
  non-blank and pass every domain check silently. So the column carries
  `CHECK (jsonb_typeof(options) = 'array' AND jsonb_array_length(options) > 0)`
  and the mapper validates element types explicitly rather than trusting the
  domain. `ARRAY(TEXT)` is not worse on type precision — it is worse only on
  repository consistency, which is the weaker argument, so the guard is the
  price of consistency. Date/Author: 2026-08-23, planning agent.

- **D-5. Native PostgreSQL enums for checkpoint status and action.**
  Rationale: consistency with every other enum in this schema. The cost is
  documented accurately in Risk 7 and the downgrade recipe goes in ADR-024.
  Date/Author: 2026-08-23, planning agent.

- **D-6. Include the lease-reclamation *primitive* on the composite port;
  exclude the reaper *worker*.** Rationale: 4.3.2 deferred "an automated
  stuck-run recovery worker" here by name. The decisive argument, which the
  previous draft missed, is de-duplication: the reclamation transaction already
  exists three times (two test helpers and a manual runbook), none in
  production code, all of which must stay in step. EP-M4 collapses them into
  one tested method. That is not new scope; it is paying down duplication the
  previous slice created. Placement: on the composite `GenerationRunPort`,
  **not** on `GenerationRunRepository`. The method must append a `run.failed`
  event, which is `GenerationEventLog` behaviour; putting it on the narrow
  repository port would oblige every future implementer of that port to also be
  an event log — exactly the coupling ADR-015 removed. The primitive/worker
  line is drawn at the transaction boundary: the primitive is one transaction
  with a finite state partition, testable in process; the worker needs a
  scheduler, at-most-once semantics, and an operational owner. Date/Author:
  2026-08-23, planning agent.

- **D-7. Name the table `review_checkpoints`, not `generation_checkpoints`.**
  Rationale: Risk 1's mitigation must be more than distinct identifiers.
  `docs/adr/adr-007-durable-generation-checkpoints.md` is *titled* "Durable
  generation checkpoints" and is entirely about `WorkflowCheckpoint`. Naming
  the new table `generation_checkpoints` would make a developer grepping for
  "generation checkpoint" land squarely on the wrong ADR — the exact failure
  Risk 1 predicts. `review_checkpoints`, `review_checkpoint_status`, and
  `review_checkpoint_action` are unambiguous and match the users' guide phrase
  "human review checkpoints". The domain entity stays `Checkpoint` and the port
  stays `GenerationCheckpointPort` because `domain.py` and the ports are frozen
  here; renaming them to `ReviewCheckpoint` and `ReviewCheckpointPort` is a
  recorded follow-up. Document the mapping explicitly in ADR-024 so the
  asymmetry reads as deliberate. Date/Author: 2026-08-23, planning agent.

- **D-8. Name the timestamp column `resolved_at`, not `responded_at`.**
  Rationale: `Checkpoint.time_out(at)` and `.cancel(at)` both write
  `responded_at=at` while leaving `responded_by` and `response_action` `None`.
  The overloading is semantically fine — it is one field, "the instant this
  checkpoint left `created`" — but the *name* lies: a DBA reading
  `responded_at NOT NULL` beside `status = 'timed_out'` will conclude the data
  is corrupt. The mapper is already a named seam, so bridging costs one line
  each way, and a column name is far more expensive to change later than a
  dataclass field. Renaming `Checkpoint.responded_at` to `resolved_at` is a
  recorded follow-up. Date/Author: 2026-08-23, planning agent.

- **D-9. Enforce only the forward half of the responded-fields constraint.**
  Rationale: `Checkpoint._validate_responded_fields` enforces one direction
  only — `status is RESPONDED` implies `resolved_at`, `responded_by`, and
  `response_action` are all set. It enforces nothing in reverse, so
  `Checkpoint(status=TIMED_OUT, response_action=APPROVE, ...)` is a legal
  domain value today. A symmetric CHECK would make the database stricter than
  the domain, and under the shared contract suite that value would round-trip
  in memory and raise `IntegrityError` in SQL — collapsing the
  interchangeability claim on an input the test factories could easily
  generate. Tightening the domain instead is forbidden by `Constraints`. So:
  add the forward implication as a CHECK, and record in ADR-024 that the
  converse is deliberately not enforced, with a follow-up to tighten the domain
  validator and add the reverse constraint together. Date/Author: 2026-08-23,
  planning agent.

- **D-10. Use compare-and-set for checkpoint transitions, not row locking.**
  Rationale: ADR-018 records the project's versioning and concurrency strategy
  and names two shapes, warning that "applying the wrong one produces either
  lost updates or spurious conflicts". For "concurrent writers racing on one
  mutable row" — which is exactly a checkpoint transition — the named house
  shape is **compare-and-set with a typed domain error**, not
  `SELECT ... FOR UPDATE`. The precedent is
  `SqlAlchemyEpisodeRepository.update`: a conditional
  `UPDATE ... WHERE id = :id AND <expected state>`, a `rowcount` check, and a
  re-fetch to distinguish not-found from conflict. The previous revision of
  this plan specified `with_for_update()`. That is replaced. Three reasons, in
  ascending order of weight. It is not the recorded house shape. It buys
  nothing the domain does not already give: there is no sequence to allocate,
  and `Checkpoint._raise_if_terminal` already rejects the loser. And
  decisively, **a compare-and-set predicate is verifiable under py-pglite while
  lock contention is not** (AXIOM-3): the `WHERE status = 'created'` clause can
  be exercised sequentially by mutating stored state between calls, whereas
  `FOR UPDATE` blocking cannot be observed at all. This converts an
  unverifiable design into a verifiable one, which is the same correction Risk
  2 applies to INV-SEQ-1. Concretely:
  `UPDATE review_checkpoints SET ... WHERE id = :id AND status = 'created'`; if
  `rowcount != 1`, re-read — absent means `CheckpointNotFound`, present means
  `CheckpointAlreadyTerminal`. The domain transition still computes the new
  value; the adapter only writes it. Note also what shape `create_checkpoint`
  is **not**. ADR-018's insert-once-then-reuse shape is for "duplicate
  deliveries of one logical operation" keyed on an idempotency key — as
  `create_run` and `SqlAlchemyCostLedgerStore.ensure_snapshot` do. Checkpoint
  creation has no idempotency key and no defined retry semantics, so a
  duplicate identifier is a plain conflict (INV-CKPT-5), classified through
  `integrity_helpers.constraint_name`. If 2.6.3 gives the checkpoint endpoint an
  `Idempotency-Key`, revisit and adopt insert-once-then-reuse rather than
  conflating the two shapes. Date/Author: 2026-08-23, planning agent.

- **D-11. A review checkpoint is not a versioned aggregate; it needs no
  history table.** Rationale: ADR-018 requires that "new versioned aggregates
  must follow this pattern: explicit repository writes in one unit of work,
  typed conflict errors, append-only or content-addressed immutability, and
  pinning at consumption boundaries." A review checkpoint is a state machine
  that transitions from `created` to a terminal state exactly once; it has no
  revision counter, no successive versions, and nothing to pin. The response
  fields are written once and never overwritten, so the row *is* the audit
  record and a separate `review_checkpoint_history` table would duplicate it.
  Recorded explicitly to pre-empt the conformance question, and because the
  deletion half of ADR-018's policy **does** apply — see the foreign key.
  Date/Author: 2026-08-23, planning agent.

- **D-12. Bring the generation-run port modules under the architecture
  gate.** Rationale: Risk 8. Add `episodic.canonical.generation_run_ports` and
  `episodic.canonical.generation_run_errors` to the `domain_ports` group in
  `[tool.hecate.groups]`, in the EP-M2 commit, since that is the commit that
  widens the port. Place them beside the other `episodic.canonical` entries;
  `domain_ports` is the first group whose prefixes could match, so ordering
  cannot misroute them (Hecate's first-match group ordering is described in the
  developers' guide and in ADR-022). Non-vacuity: temporarily add
  `import episodic.canonical.storage` to `generation_run_ports.py`, confirm
  `make check-architecture` fails with `ARCH001`, then remove it. If adding the
  modules exposes an existing violation, stop and escalate rather than adding a
  Hecate ignore. Date/Author: 2026-10-18, planning agent.

- **D-13. Name the duplicate-identifier error `CheckpointAlreadyExists`.**
  Rationale: INV-CKPT-5 requires `create_checkpoint` to reject a duplicate
  identifier identically in both adapters, and D-10 classifies that case as "a
  plain conflict … classified through `integrity_helpers.constraint_name`", but
  the plan names **no exception** for it anywhere. Stage C enumerates only
  `RunNotFound`, `CheckpointNotFound`, and `CheckpointAlreadyTerminal` for the
  adapter. The omission is real and blocks Stage B: a shared scenario cannot
  assert the duplicate rule without naming the type it expects.
  `CheckpointAlreadyExists` is chosen over reusing `CheckpointAlreadyTerminal`
  because the two are genuinely different: a duplicate identifier is a conflict
  on the key, and a terminal checkpoint is a conflict on the state machine. A
  replay against a `responded` checkpoint is **both**, so the two preconditions
  can collide on one input. No scenario here exercises that collision — the
  duplicate scenario replays a `created` entity, which passes the status
  precondition, and the terminal-status scenario uses a fresh identifier — so
  the relative order of the two checks is deliberately left unobservable, and
  Stage C should validate the incoming entity's own status first because that
  is an argument check rather than a storage lookup. It lives in
  `episodic/canonical/generation_run_errors.py` beside its siblings, carrying
  the same
  `# ruff: ignore[error-suffix-on-exception-name] - stable ExecPlan contract.`
  marker, and follows the house message shape
  (`"generation checkpoint already exists: {checkpoint_id}"`). Consequence for
  Stage C: the in-memory adapter must gain the duplicate check in
  `InMemoryGenerationCheckpointMixin.create_checkpoint` in the **same commit**
  as the SQL adapter, as INV-CKPT-5 already requires.

  Sequencing note, because it bears on the Stage B red evidence: adding the
  class is a contract *declaration*, and the shared scenarios cannot be
  imported without it. It is therefore added in Stage B, before the Stage C
  behaviour, so that the red is the intended behavioural failure
  (`DID NOT RAISE`) rather than an `ImportError` — which the stage-closing
  condition rules out by name. Date/Author: 2026-10-20, implementation agent.

- **D-14. Drive the SQL scenarios from a sibling module, not by growing
  `test_generation_runs.py` past the module-length cap.** Rationale: Stage B
  step 3 says to add the SQL parameterization "into
  `tests/canonical_storage/test_generation_runs.py`", and
  `Context and orientation` reinforces it — "New SQL contract scenarios belong
  here, not in a parallel module." That is affordable only if the module has
  room. It does not: 368 lines against pylint's `max-module-lines = 400`, a
  target that includes `tests`, leaving 32 lines where a driver needs roughly
  130. The two requirements — stay in that file, and pass `make lint` — cannot
  both hold, so one must yield, and the length cap is the non-negotiable one
  (`AGENTS.md`: "No single code file should be longer than 400 lines").
  Decision: the nine driver wrappers live in
  `tests/canonical_storage/test_generation_run_checkpoint_contract.py`. This
  preserves the intent behind "not in a parallel module", which is that there
  must be **one** definition of each checkpoint contract: the scenarios stay in
  `tests/generation_run_contract_scenarios.py` and drive both adapters, and the
  new module adds no assertions of its own. `test_generation_runs.py` keeps its
  run- and event-level coverage unchanged. (2026-10-20)

- **D-15. Hold the Stage B red tests out of `git` until the milestone that
  turns them green, rather than committing them as a red commit.** Rationale:
  the plan's *Idempotence and recovery* says "Each milestone is a separate
  commit, so `git revert` returns the tree to the previous plateau" — and Stage
  B is not a milestone. `AGENTS.md` is explicit and unconditional: "Do not
  commit changes that fail any quality gate," and `make test` is a quality
  gate. A red commit would therefore be a commit that fails `make test` by
  construction; the plan never asks for one, and *Concrete steps* runs "full
  gates at every milestone boundary" — not per stage. Consequence for
  sequencing, which is the substantive part: Stage B and its consumers must
  interleave at file granularity rather than landing as one blob. The red tests
  for EP-M1 (`test_review_checkpoint_migration.py`) go in the EP-M1 commit;
  those for EP-M2 and EP-M3 (`test_review_checkpoints.py`, the SQL driver, the
  BDD scenario, and the in-memory duplicate/terminal-status preconditions) go
  in the EP-M2 commit, because EP-M2 is the commit that adds
  `SqlAlchemyReviewCheckpointStore` and the `CheckpointAlreadyExists` check in
  the in-memory mixin. EP-M3 then carries no test changes of its own; its
  milestone is the *shared* scenario module driving both adapters, which is
  already satisfied by those two commits. This is a deliberate departure from a
  literal reading of "Write the failing tests before any production code",
  which the ordering still honours in the working tree — the tests are written
  and observed failing before any production code exists. It is the *commit*
  boundary that moves, not the work order. Recorded here rather than silently,
  because a reviewer reading the Stage C commit will see tests and
  implementation arriving together and should know that is intended.
  (2026-10-20)

- **D-16. Replace the planned `apply_checkpoint_to_record` mapper with
  `resolved_values`, and refresh rather than mutate the identity-mapped
  record.** Stage C step 4 names three mapper functions in
  `review_checkpoint_mappers.py`: `checkpoint_from_record`,
  `checkpoint_to_record`, and
  `apply_checkpoint_to_record(record, checkpoint) -> None`, the last justified
  as necessary because "`checkpoint_to_record` manufactures a *new* record, and
  `session.add()` would raise on the primary key". That justification presumes
  transitions are applied by assigning ORM attributes onto the loaded record.
  They are not: D-10's compare-and-set is a **core
  `UPDATE … WHERE id = :id AND status = 'created'`** with a `rowcount` check,
  which is what makes the lost-race branch (D-10) and INV-CKPT-5's identical
  conflict classification possible. Under that shape
  `apply_checkpoint_to_record` has no correct caller. The record is already in
  the session's identity map and already matches the row the `UPDATE` just
  wrote, so writing the resolved columns onto it would mark it **dirty** and
  emit a second, redundant `UPDATE` at the next flush — the same values, on a
  row that is already correct, from a session that has not refreshed it. That
  is not merely wasteful: it is a second write path to columns the store's
  docstring promises nothing else writes. The alternative — reverting to ORM
  attribute assignment — would trade one guarded statement for a
  load-then-flush pair and make the `rowcount` check indirect, which is the
  whole mechanism D-10 chose. Decision: `review_checkpoint_mappers.py` exports
  `checkpoint_from_record`, `checkpoint_to_record`, and `resolved_values`, where
  `resolved_values(checkpoint) -> dict[str, object]` returns the exact column
  mapping the compare-and-set `UPDATE` writes. `resolved_values` keeps the
  property the plan wanted from `apply_checkpoint_to_record` — one site naming
  which columns a resolution writes, so the `UPDATE` and the entity the caller
  receives cannot drift — but as a value the statement consumes rather than a
  mutation of a record the session owns. Reconciliation of the session's stale
  copy is `await session.refresh(record)` in `_refresh_resolved`, which is
  recorded in that helper's docstring. This is a deviation from an explicit
  Stage C instruction and is recorded rather than applied silently. (2026-10-20)

- **D-17. Detect pending writes with a session-event tracker, not with
  `Session.new`/`.dirty`/`.deleted`, and emit the Risk 4 warning as a
  structured event.** Rationale: the plan's literal predicate is blind to both
  write paths this slice uses (see *Surprises & discoveries*), so implementing
  step 9 as written would have shipped a guard that never fires. The
  replacement lives in `episodic/canonical/storage/session_write_tracker.py`
  and is consulted through the existing `_has_pending_changes()` seam, so
  `__aexit__` keeps the single branch the plan asked for. The tracker is
  cleared by `commit()`, `rollback()`, and the exception path of `__aexit__`,
  since all three settle the session. Second, the warning is emitted through
  `log_event` rather than `logger.warning`, because `caplog` cannot see a
  femtologging record; the event name
  `canonical_unit_of_work.closed_with_uncommitted_changes` follows the
  `<component>.<event>` convention already used across `storage/`. Both changes
  are deviations from explicit Stage C instructions and are recorded rather
  than applied silently. (2026-10-21)

- **D-18. Re-stamp `updated_at` in the reclamation mixin rather than widening
  `GenerationRunStatusUpdate`.**
  `SqlAlchemyGenerationRunStore.update_run_status` stamps
  `record.updated_at = self._runtime.clock()` and does not accept an instant,
  so taking that transition's return value would publish a second "now"
  different from `now`. Stage D step 1 requires one instant per call
  (`ended_at`, `updated_at`, and the event's `occurred_at`), so the mixin
  overwrites `record.updated_at = now` and maps the record itself via
  `run_from_record`. This is the one site where the implementation departs from
  a literal Stage D instruction, which said to use the transition's return
  value; the return value cannot carry `now`, because `update_run_status` owns
  that field. The re-stamp is safe because `expired_lease_candidates` loaded
  that row into the same session, so the mixin writes the instance the
  transition just updated, and `_require_mutable_run(..., lock=True)` resolves
  through the identity map to the same object. The alternative — threading
  `updated_at` through `GenerationRunStatusUpdate` — would widen a shared
  domain-input type for one caller, and the asymmetry is recorded here as a
  reviewer consideration rather than hidden. (2026-10-21)

- **D-19. Assert the append-before-update ordering rather than document it.**
  INV-LEASE-1 requires the `run.failed` event to be appended **before** the
  status update, because the reverse order raises `RunAlreadyTerminal` on an
  already-terminal row. A docstring cannot hold that, and a test that merely
  inspects the final database state passes under either order.
  `test_generation_run_lease_transitions.py` therefore monkeypatches
  `append_event` and `update_run_status` to record call names, asserts
  `calls == ["append_event", "update_run_status"]`, and additionally asserts
  that a post-transition append raises `RunAlreadyTerminal`. Non-vacuity was
  verified by temporarily swapping the two calls and observing the module go 4
  failed / 0 passed — every test died with `RunAlreadyTerminal` — then
  restoring. (2026-10-21)

- **D-20. Split the lease suite three ways and record a shared predicate
  constant question for review.** The first draft of
  `test_generation_run_lease_reclamation.py` reached 422 lines, which Pylint's
  `max-module-lines = 400` rejects; `tests` **is** a `PYLINT_TARGETS` member
  (Makefile:41), so the ceiling binds test modules too. Splitting into a
  support module plus a reclamation-state module plus a transitions module
  landed at 146/226/176 and, in the process, replaced a count assertion with an
  exact-identifier-set assertion over the full partition, with
  `assert expected` and `assert len(expected) < len(PARTITION)` guarding
  against a vacuous pass. Separately, and left open deliberately: nothing
  asserts that the migration and the ORM agree on the partial-index predicate,
  and `make check-migrations` **cannot** — see the alembic#750 observation
  above. The shared constant makes divergence require editing one file rather
  than two, but a test reading `pg_indexes` (or `postgresql_where`) would be
  the actual guard; `test_pricing_snapshot_constraint_migration.py` is the
  nearest precedent. Raised for review rather than added unprompted, because it
  is outside the slice's stated acceptance criteria. (2026-10-21)

Append further decisions here, including any decision to escalate.

## Outcomes & retrospective

To be completed at each milestone boundary and at completion. Before setting
this plan to `COMPLETE`, reconcile every implementation discovery against the
artefacts named in `Conformance basis`, and confirm that `docs/roadmap.md` item
2.6.2 has been ticked by the implementor.

## Context and orientation

Assume no prior knowledge of this repository.

**What the project is.** Episodic generates podcast scripts from ingested
source material. Python 3.14, Falcon for HTTP, SQLAlchemy 2.x with `asyncio`
over PostgreSQL, Alembic for migrations, `uv` for dependencies and tasks. It
follows hexagonal architecture: a pure domain, port protocols the domain
declares, and adapters that implement them.

**Where things live.**

- `episodic/canonical/domain.py` — a re-exporting façade. The generation-run
  entities live in `domain_generation.py` and their enums in `domain_enums.py`.
  `Checkpoint` carries the transitions `respond()`, `time_out()`, and
  `cancel()`; each calls `_raise_if_terminal()` and returns a *new* frozen
  instance via `dataclasses.replace`. All three raise
  `CheckpointAlreadyTerminal` once the checkpoint has left `created`.
- `episodic/canonical/generation_run_ports.py` — the port protocols.
  `GenerationCheckpointPort` declares `create_checkpoint`, `get_checkpoint`,
  `respond_to_checkpoint`, `time_out_checkpoint`, and `cancel_checkpoint`.
  `GenerationRunPort` is the composite of all three sub-protocols.
- `episodic/canonical/generation_run_errors.py` — `GenerationRunError` and its
  subclasses.
- `episodic/canonical/adapters/generation_runs.py` (390 lines) —
  `InMemoryGenerationRunStore`, the reference adapter, which gains checkpoint
  behaviour from `InMemoryGenerationCheckpointMixin` in
  `episodic/canonical/adapters/generation_checkpoints.py`.
- `episodic/canonical/storage/models_base.py` — the SQLAlchemy `Base` and the
  shared native-enum declarations.
- `episodic/canonical/storage/generation_run_models.py` —
  `GenerationRunRecord` and `GenerationEventRecord`.
- `episodic/canonical/storage/generation_runs.py` (358 lines) —
  `SqlAlchemyGenerationRunStore`, implementing `GenerationRunRepository` and
  `GenerationEventLog` only.
- `episodic/canonical/storage/generation_run_mappers.py` — pure record/domain
  mapping functions. Adapters never build domain dataclasses inline.
- `episodic/canonical/storage/uow.py` — `SqlAlchemyUnitOfWork`, whose
  `__aenter__` instantiates every repository from one shared `AsyncSession`.
- `episodic/canonical/unit_of_work_protocols.py` — `CanonicalUnitOfWork`, which
  at the Stage A baseline declared `generation_runs: GenerationRunEventStore`;
  this slice widened it to the composite `GenerationRunPort`.
- `alembic/versions/` — migrations named `YYYYMMDD_NNNNNN_description.py`,
  chained linearly by `down_revision`. Head at the Stage A baseline
  (`2026-10-20`): `20261010_000013`; the chain reaches `20261020_000015` at
  merge time, `000014` from EP-M1 and `000015` from EP-M4. Filename dates are
  not in chain order (`20260601_000009` follows `20260610_000009`), so trust
  `down_revision`, not `ls`.
- `tests/` — top-level `test_*.py` are unit tests; `tests/canonical_storage/`
  holds PostgreSQL-backed integration tests; `tests/features/*.feature` with
  `tests/steps/test_*_steps.py` hold behavioural tests.
- `tests/fixtures/database.py` — the py-pglite fixture stack. The chain is
  `pglite_sqlalchemy_manager` (session-scoped) → `pglite_engine` →
  `migrated_engine` (drops and recreates the `public` schema, then applies the
  full Alembic chain, per test function) → `session_factory` and
  `pglite_session`.

**The specific gap, as it stood at the Stage A baseline (`2026-10-20`).**
`SqlAlchemyGenerationRunStore` had no checkpoint methods. There was no
checkpoint table. `tests/test_generation_checkpoint_port_contract.py` ran
against the in-memory store only. `uow.generation_runs` was typed as the
narrower `GenerationRunEventStore`, and nothing in the repository implemented
the composite `GenerationRunPort` except a no-op stub used for type-checking.
Every clause of this paragraph was closed by the slice; it is retained because
it is the diagnosis that motivated the work, not a description of the tree at
merge time.

**Terms used in this plan.**

- *Port* — a Protocol the domain declares and adapters implement.
- *Adapter* — an implementation of a port that touches the outside world.
- *Aggregate* — an entity cluster with one transactional boundary. The
  aggregate root here is `GenerationRun`; events and checkpoints belong to it.
- *Checkpoint* (the domain entity, stored in `review_checkpoints`) — a pause
  where a **human** is asked to decide. Owned by the canonical domain.
- *WorkflowCheckpoint* (stored in `workflow_checkpoints`) — serialized
  LangGraph state so a **machine** can resume. Owned by orchestration. The two
  never convert into one another.
- *Prefix stability* — once a reader has seen events up to sequence S, no
  event with sequence ≤ S ever becomes visible later. This is what `after_seq`
  replay actually requires.
- *Gapless sequence* — after N successful appends the set of sequence numbers
  is exactly `{1, ..., N}`. Stronger than prefix stability.
- *Lease* — `generation_runs.lease_expires_at`, a fixed 900-second wall-clock
  ceiling set once when a worker claims a run. It is **not** renewed and is
  **not** a liveness signal.
- *Drift* — a difference between the ORM metadata and the migration history.

## Conformance basis

There is no formal Terms of Reference artefact; the roadmap and design
documents serve that role. Upstream items traced by this plan:

- `ROADMAP-2.6.2` — `docs/roadmap.md`, lines 323–325: "Implement repository
  contracts and Alembic migrations. Define repository interfaces for
  generation-run aggregates. Add integration tests validating event ordering."
- `DESIGN-ORCH-CKPT` — `docs/episodic-podcast-generation-system-design.md`,
  "Content Generation Orchestrator": "Provides checkpointing for resumable
  workflows, enabling long-running editorial review periods without state loss."
- `API-GENRUN-CKPT` — `docs/episodic-tui-api-design.md`, "Generation runs": the
  `Checkpoint` data shape and `POST /v1/generation-runs/{run_id}/checkpoint`.
- `API-GENRUN-SEQ` — same document: events carry "a monotonically increasing
  `seq` number for ordering and replay", with `resume_from` replay. The
  operative requirement is **prefix stability**, not gaplessness; the only
  gap-sensitive text is the backpressure heuristic at lines 629–633.
- `ADR-015` — the port split and the `Checkpoint` / `WorkflowCheckpoint`
  separation.
- `ADR-018` — `docs/adr/adr-018-explicit-versioning-and-history-strategy.md`:
  the governing record for versioning, concurrency shapes, immutability, and
  deletion policy. Three clauses bind this slice. "Applying the wrong
  [concurrency shape] produces either lost updates or spurious conflicts" — see
  D-10. "Deletion policy protects the audit trail", with `ON DELETE RESTRICT`
  for references to the immutable records that explain durable state — see the
  foreign key in Table 1. "New versioned aggregates must follow this pattern" —
  see D-11 for why a review checkpoint is not one.
- `EP-4.3.2-DEFER` — "Out of scope and left to later tasks: human-review
  checkpoint persistence (2.6.2) … and an automated stuck-run recovery worker
  (2.6.2)."

Trace links from upstream item, through milestone, to acceptance evidence:

```plaintext
ROADMAP-2.6.2    -> EP-M1 -> make check-migrations reports no drift
ROADMAP-2.6.2    -> EP-M3 -> tests/canonical_storage/test_generation_runs.py
API-GENRUN-SEQ   -> EP-M3 -> test_sql_generation_run_property_contract.py
DESIGN-ORCH-CKPT -> EP-M1 -> alembic/versions/20261020_000014_add_review_checkpoints.py
DESIGN-ORCH-CKPT -> EP-M2 -> episodic/canonical/storage/review_checkpoints.py
API-GENRUN-CKPT  -> EP-M2 -> uow.generation_runs satisfies GenerationRunPort
API-GENRUN-CKPT  -> EP-M3 -> tests/features/generation_run_lifecycle.feature
ADR-015          -> EP-M5 -> docs/adr/adr-024-review-checkpoint-persistence.md
ADR-018          -> EP-M2 -> compare-and-set transitions; ON DELETE RESTRICT
ADR-014          -> EP-M2 -> generation_run_ports in Hecate domain_ports (D-12)
EP-4.3.2-DEFER   -> EP-M4 -> tests/canonical_storage/test_generation_run_lease_reclamation.py
EP-4.3.2-DEFER   -> EP-M4 -> alembic/versions/20261020_000015_add_expired_lease_index.py
```

When an artefact is renamed or folded into an existing module, update this
table in the same commit; a stale trace table is worse than none.

A new ADR is warranted. ADR-018 to ADR-023 now exist, so the next free number
is **024**; re-check at EP-M5, because two numbers this plan reserved were
taken while it was in review. Separately, three files already share 015
(`adr-015-cost-accounting-ports-and-pricing-engine.md`,
`adr-015-upload-and-idempotency-ports.md`,
`adr-015-generation-run-port-split.md`), and **two of them are absent from
`docs/contents.md` entirely**. Renumbering to 015/018/019 and re-indexing is
out of scope here; add it to the roadmap as a docs-only follow-up rather than
leaving it as a remark in a plan that will be marked `COMPLETE`.

## Verification plan

### Axioms (assumed, not verified)

- **AXIOM-1.** PostgreSQL `SELECT ... FOR UPDATE` under `READ COMMITTED` blocks
  a second transaction attempting to lock the same row until the first
  completes. This is documented PostgreSQL behaviour and is the basis of
  allocation-order-equals-commit-order.
- **AXIOM-2.** `alembic.autogenerate.compare_metadata` detects differences in
  tables, columns, types, constraints, and enums. Exercised by
  `tests/features/schema_migrations.feature`.
- **AXIOM-3.** **py-pglite reproduces PostgreSQL SQL semantics, DDL, native
  enums, and constraint enforcement faithfully, and serializes transactions
  globally.** It is a single WebAssembly backend, so only one transaction runs
  at a time and an open transaction blocks *every* other session, related or
  not. It therefore **cannot** exhibit lock contention, lost updates, or
  `FOR UPDATE` blocking, and no test running under it can provide evidence
  about concurrent behaviour. This replaces the previous draft's claim that
  py-pglite reproduces locking semantics, which two independent probes
  falsified — see `Surprises & discoveries`. Do not cite the existing
  `asyncio.gather` tests as concurrency evidence; they measure sequential
  replay.
- **AXIOM-4.** `uuid.uuid7()` returns unique, time-ordered identifiers.
- **AXIOM-5.** `postgresql.JSONB` round-trips any JSON-compatible mapping or
  list without reordering array elements.

Do not verify the internals of SQLAlchemy, Alembic, or PostgreSQL. Do verify
this repository's *use* of them.

### INV-SEQ-1 — sequence allocation is prefix-stable and gapless per run

- Obligation: for any run `r`, after `N` sequential successful `append_event`
  calls the persisted sequence numbers are exactly `{1, ..., N}`; and
  `list_events` never returns a previously-unseen sequence at or below one it
  has already returned.
- Method: Hypothesis property test against py-pglite, **sequential appends
  only**, plus explicit assertions on the `WHERE` predicates that make the
  allocation correct.
- Rationale, and the honest limit: gaplessness under *genuine concurrent
  writers* rests on AXIOM-1 and is **not observable under py-pglite**
  (AXIOM-3). The property test therefore verifies the allocation arithmetic,
  the run-id predicate, and the ordering — the parts that can fail
  independently of concurrency — and the concurrency claim moves to
  `Residual gaps`. This is a deliberate downgrade from the previous draft,
  which promised evidence its harness cannot produce.
- Domain: 1–8 events per run, event kinds from a bounded alphabet.
- Artefact:
  `tests/canonical_storage/test_sql_generation_run_property_contract.py`.
- Evidence:

```bash
uv run pytest \
  tests/canonical_storage/test_sql_generation_run_property_contract.py -v
```

- Settings: `max_examples=25`, `deadline=None`,
  `suppress_health_check=[HealthCheck.function_scoped_fixture]`. Raised from
  the previous draft's 5–6: measured cost is ~0.05 s per example because the
  function-scoped fixture is shared across examples, so 25 examples costs about
  1.3 s, and 6 draws do not reliably satisfy the non-vacuity requirement below.
- Non-vacuity: classify examples with `hypothesis.event()` by event count and
  confirm multi-event runs occur; assert `len(events) >= 2` in at least one.
  Negative control: drop the `generation_run_id` predicate from the `MAX(seq)`
  subquery and confirm the cross-run case fails. **Do not** use "remove
  `lock=True`" as the negative control — it provably does not reproduce under
  py-pglite, and a control that cannot fire is worse than none. **Discharged
  2026-10-21:** with the predicate dropped,
  `test_sql_event_batches_are_gap_free_and_isolated` fails as a Hypothesis
  `FlakyFailure` from inconsistent replays and
  `test_sql_pages_match_creation_and_cursor_reference_slices` fails on a wrong
  `GenerationEvent` sequence — `2 failed, 2 passed`, transcript under
  *Artefacts and notes*.

### INV-SEQ-2 and INV-SEQ-3 — paging and cross-run isolation

- Status: **already discharged** by
  `test_sql_pages_match_creation_and_cursor_reference_slices` and
  `test_sql_event_batches_are_gap_free_and_isolated` in
  `tests/canonical_storage/test_sql_generation_run_property_contract.py`. This
  plan adds no new obligation here and claims no new deliverable. Confirm they
  still pass; do not rewrite them.

### INV-CKPT-1 — SQL checkpoint transitions match the domain transitions

- Obligation: `respond_to_checkpoint`, `time_out_checkpoint`, and
  `cancel_checkpoint` persist exactly the entity returned by the corresponding
  domain method. The adapter must not reimplement the transition rules.
- Method: shared checkpoint contract scenarios executed against both adapters.
- Rationale: the risk is drift between two implementations of one rule set.
- Artefact: `tests/generation_run_contract_scenarios.py` (a plain module of
  `async def scenario_*(store, ...)` functions — **not** an abstract test base
  class; see EP-M3), driven from
  `tests/test_generation_checkpoint_port_contract.py` and
  `tests/canonical_storage/test_generation_runs.py`.
- Non-vacuity: the SQL parameterization must be seen failing first, for the
  intended reason. Record the transcript.
- Limit, stated because it bounds what this obligation is worth: the in-memory
  adapter stores whole frozen dataclasses behind an `asyncio.Lock`, so it
  structurally cannot exhibit timezone truncation, JSONB round-trip shape,
  tuple-versus-list coercion, or foreign-key violations. The contract suite is
  a **shape check**; INV-CKPT-3 carries the real fidelity evidence.

### INV-CKPT-2 — terminal checkpoints reject further transitions

- Obligation: any transition on a checkpoint in `responded`, `timed_out`, or
  `cancelled` raises `CheckpointAlreadyTerminal` and leaves the row unchanged.
- Method: parameterized test over the nine (starting state × transition)
  combinations — finite and small, so enumeration is exhaustive.
- Non-vacuity: after each expected exception, re-read through the scenario
  module's `read_fresh` hook and assert the status is unchanged. Without the
  re-read the test passes even if the adapter wrote the mutation and then
  raised. Negative control: widen the compare-and-set predicate to
  `WHERE id = :id` and confirm the stale-writer route below then fails.
- **Corrected 2026-10-21 after the control was run.** The original text here
  claimed the control could be driven by "mutating stored state between calls,
  sequentially, which py-pglite supports", and that this made the
  `WHERE status = 'created'` clause exercised by the terminal cases. **It is
  not.** The nine terminal cases never reach the `UPDATE`: `_resolve` calls
  `transition(checkpoint_from_record(record))`, and the domain's
  `_raise_if_terminal()` fires inside that call, before the statement is built.
  Widening the predicate therefore leaves all 23 checkpoint contract tests
  passing — observed, not inferred (`CAS_RESOLVE_ENTERED: 27`,
  `DOMAIN_GUARD_RAISED CheckpointAlreadyTerminal: 10`, `LOST_RACE_ENTERED: 0`;
  14 `UPDATE`s issued for exactly the 14 *successful* transitions). The
  load-bearing route is a caller holding a *stale pre-terminal* copy of the
  record: the domain guard then passes, the `UPDATE` is issued, and
  `rowcount == 0` is the only thing refusing the transition. Under the widened
  predicate that route silently overwrites a terminal row
  (`Failed: DID NOT RAISE CheckpointAlreadyTerminal`). See the INV-CKPT-2
  transcript under *Artefacts and notes*.
- This obligation is *verifiable* precisely because D-10 chose compare-and-set:
  `rowcount == 0` is observable by a caller that holds a stale view, which is
  what the corrected control above constructs. Had the adapter relied on
  `FOR UPDATE`, that losing-writer path would have been unobservable for the
  same reason INV-SEQ-1's concurrency claim is — and, as corrected above, the
  terminal cases would not have exercised the predicate either.

### INV-CKPT-3 — checkpoints round-trip through PostgreSQL exactly

- Obligation: a checkpoint written and committed, then read in a fresh unit of
  work, equals the original — including `options` tuple ordering,
  `response_payload` contents, and timezone-aware timestamps.
- Method: integration test over two sequential unit-of-work scopes.
- Artefact: `tests/canonical_storage/test_review_checkpoints.py`.
- Non-vacuity: use a non-alphabetical `options` value such as
  `("edit", "approve", "request_changes")` so a sorting bug is visible, and a
  `response_payload` containing a nested mapping and a list. Negative controls:
  (a) map `options` through `set()` and confirm the ordering assertion fails;
  (b) write `'"approve"'::jsonb` into `options` directly and confirm the read
  fails loudly rather than yielding seven single-character options. **Both
  discharged 2026-10-21.** (a) fails with
  `AssertionError: option order: ('request_changes', 'edit', 'approve')` — a
  hash-ordered permutation of the declared tuple. (b) requires dropping
  `ck_review_checkpoints_options_array` first, since the constraint makes the
  write otherwise unreachable; the control then confirms the stored column
  really reads back as a Python `str` and `_options_to_tuple` raises
  `TypeError` on it rather than iterating it. Transcripts under *Artefacts and
  notes*.
- No syrupy snapshot. `AGENTS.md` scopes snapshots to "multivariant output
  format consistency"; there is one variant here, and explicit field assertions
  on a twelve-field frozen dataclass already catch everything a snapshot would.

### INV-CKPT-4 — a checkpoint cannot reference a non-existent run

- Obligation: `create_checkpoint` for an unknown run raises `RunNotFound` and
  writes no row.
- Non-vacuity: assert both that `RunNotFound` is raised *and* that
  `SELECT count(*)` on `review_checkpoints` returns zero. Asserting only the
  exception would pass even if an `IntegrityError` were mistranslated after a
  partial write.

### INV-CKPT-5 — creation preconditions are enforced in both adapters

- Obligation: `create_checkpoint` rejects a checkpoint whose status is not
  `created`, and rejects a duplicate identifier, identically in both adapters.
- Rationale: neither adapter checks either today. The in-memory version
  silently overwrites on duplicate id — including overwriting a `responded`
  checkpoint back to `created` — while SQL would raise `IntegrityError`. Left
  alone, the shared suite would certify a divergence as interchangeable. This
  is the "shared blind spot" of Risk 8.
- Decision: define duplicate-id as raising, and fix the in-memory adapter in
  the same commit. The "no compatibility shims / update both adapters together"
  constraint licenses this.
- Deliberately **not** enforced: the parent run's status. In-memory
  `create_checkpoint` checks run *existence* only, and the obvious SQL
  implementation would reuse `_require_mutable_run`, which raises
  `RunAlreadyTerminal` — a divergence. Stage C therefore instructs explicitly:
  check existence only; do **not** call `_require_mutable_run`. Record the
  choice in the port docstring.

### INV-MIG-1 — no schema drift

- Method: the existing repository drift check, `make check-migrations`.
- Non-vacuity: already provided by the "Drift detected when models diverge"
  scenario in `tests/features/schema_migrations.feature`. Confirm it passes.
- Known blind spot, recorded because it caused Risk 6: this check rebuilds an
  ephemeral database from scratch, so it cannot detect divergence between a
  *live* database's applied-revision history and the current migration files.

### INV-MIG-2 — the migration is reversible and orphans no enum

- Obligation: `upgrade` → `downgrade` → `upgrade` leaves the schema identical
  to a single `upgrade`, and the intermediate `downgrade` removes the table and
  **both** new enum types.
- Rationale: `downgrade()` is rarely exercised, and native enums are the usual
  thing left behind — dropping a table does not drop its enum type.
- Artefact: `tests/canonical_storage/test_review_checkpoint_migration.py`.
- Evidence: upgrade to head, downgrade one revision, assert the table is absent
  **and** that
  `SELECT 1 FROM pg_type WHERE typname IN
  ('review_checkpoint_status', 'review_checkpoint_action')`
  returns no rows, then upgrade again and assert no drift.
- Non-vacuity: the `pg_type` assertion is the point. Remove either explicit
  `.drop(bind, checkfirst=True)` call and the test must fail; verify both fail
  independently before trusting it. **Discharged 2026-10-21.** Each drop was
  removed in turn, with the other restored: both give `1 failed, 3 passed` with
  `AssertionError: downgrade must drop both enum types`. Neither drop is
  redundant and the test discriminates each one separately; transcript under
  *Artefacts and notes*.

### INV-COMMIT-1 — uncommitted work does not persist, and says so

- Obligation: a unit of work that responds to a checkpoint and exits without
  `commit()` leaves the checkpoint `created`, and logs a warning.
- Rationale: this pins the semantics of Risk 4 deliberately instead of leaving
  them accidental, and gives the warning a regression test.
- Artefact: `tests/canonical_storage/test_review_checkpoints.py`.
- Non-vacuity: assert both the persisted state *and* the emitted warning.
  Asserting only the state would pass today, before the warning exists.

### INV-LEASE-1 — lease reclamation is selective and idempotent (EP-M4)

- Obligation: the reclamation query transitions a run to `failed` **only** if
  its status is `running`, `lease_expires_at` is non-null and at or before the
  supplied instant, **and the run has no checkpoint in `created`**. For each
  reclaimed run it appends exactly one `run.failed` event, in the same
  transaction, at the next sequence number. A second invocation reclaims
  nothing.
- Rationale for the checkpoint clause: see Risk 3. Without it the primitive
  fails every run awaiting human review fifteen minutes after it was claimed —
  precisely the runs this slice exists to protect.
- Ordering constraint, which the implementation will otherwise get wrong:
  `append_event` calls `_require_mutable_run(..., lock=True)`, which raises
  `RunAlreadyTerminal`. The `run.failed` event **must** be appended *before*
  the status update, or the method fails at runtime. The reverse order
  type-checks cleanly, so this must be asserted, not merely documented.
- Method: parameterized tests over the state partition — `pending`; `running`
  with no lease; `running` with a future lease; `running` with an expired lease
  and no checkpoint; `running` with an expired lease and an open checkpoint;
  each terminal status — plus an idempotence test.
- Artefact: `tests/canonical_storage/test_generation_run_lease_reclamation.py`.
- Non-vacuity: assert the exact set of reclaimed run identifiers, not a count;
  the partition must contain at least one reclaimed and at least one of each
  non-reclaimed kind. Negative controls: drop the
  `lease_expires_at IS NOT NULL` predicate and confirm the no-lease case fails;
  drop the checkpoint clause and confirm the open-checkpoint case fails.
- Limit: `FOR UPDATE SKIP LOCKED` **cannot be shown to skip anything** under
  py-pglite (AXIOM-3). The state-partition cases are sequential and will pass,
  but the `SKIP LOCKED` clause itself is unverified. Recorded in
  `Residual gaps`.

### Residual gaps

- **Concurrency is unverified.** Gaplessness and prefix stability under
  genuine concurrent writers rest on AXIOM-1 and cannot be demonstrated under
  py-pglite. Discharging them requires an opt-in test tier against a real
  PostgreSQL container, marked with the existing but currently unused `slow`
  marker and excluded from `make test`. That is a separate slice; it is named
  here so the gap is visible rather than assumed closed.
- **`FOR UPDATE SKIP LOCKED` semantics are unverified**, for the same reason.
- **Behavioural equivalence holds only under a single writer per run.** The
  in-memory adapter serializes with an in-process `asyncio.Lock` that no
  cross-connection adapter can reproduce.
- **Value-domain limits diverge between adapters.** `node` is `String(160)`
  and `responded_by` is `String(240)` in SQL, while the domain validates
  non-blank only. A 300-character `node` is in-memory-legal and raises
  `DataError` in SQL. Contract-test factories must stay inside the bounds, and
  the port docstring must note that adapters may impose length limits.
- **Under `EPISODIC_TEST_DB=sqlite` the py-pglite fixtures are disabled and
  dependent tests skip**, so "one suite, both adapters" silently becomes one
  adapter. Do not read a green run in that mode as equivalence evidence.
- **Checkpoints have no deadline.** `time_out_checkpoint(checkpoint_id, at=)`
  requires the caller to already know which checkpoint expired, and neither the
  domain entity nor the proposed table carries an `expires_at`. So nothing can
  discover a checkpoint due for time-out, and a checkpoint on a reclaimed run
  is left in `created` forever attached to a `failed` run. Adding
  `Checkpoint.expires_at` needs a domain change, forbidden by `Constraints`; a
  storage-only column would be write-only. Recorded as a roadmap follow-up.
- **`count_events` is O(N) and is issued on every page request.** Because
  sequences are gapless and append-only with no delete path,
  `count_events(run, after_seq=s)` is exactly `max(0, max_seq(run) - s)` — the
  same O(log N) backward index scan as `MAX(seq)`, instead of a full
  `COUNT(*)`. Walking a 10,000-event log at the default page size of 20
  currently costs ~5 million index-tuple reads in counts alone. Not changed
  here to keep this slice's diff honest; recorded as a high-value follow-up
  that INV-SEQ-1 licenses.
- **Event payloads are unbounded and there is no retention path.** Row counts
  are harmless (~50 MB/month at expected volume), but a run logging full LLM
  node payloads into `payload` could be tens of megabytes alone.
- **`StaleEventSequence` is dead surface** — declared, never raised, never
  imported, and unreachable given ADR-015's decision that the adapter owns
  sequence allocation. Deleting it touches a frozen module; follow-up.
- **Episode deletion is already broken.** `generation_runs.episode_id` cascades
  from `episodes`, but `generation_events.generation_run_id` has no `ondelete`,
  so deleting an episode with any run that has any event raises a foreign-key
  violation. No application code deletes episodes today. Not fixed here;
  recorded so a retention story starts from the truth.

## Plan of work

### Stage A — understand and sweep (no code changes)

Load the `leta`, `hexagonal-architecture`, and `python-router` skills, then run
`leta workspace add .`.

Perform the abstraction sweep `AGENTS.md` requires — **on production and test
code both**. The previous draft swept only production code and consequently
proposed test modules duplicating suites that already exist.

```bash
leta grep "Checkpoint" -k class -d
leta implementations GenerationCheckpointPort
leta refs GenerationRunEventStore
leta refs CanonicalUnitOfWork
rg -l "create_checkpoint|respond_to_checkpoint" tests/ episodic/
rg -n "class Test" tests/test_generation_run_port_contract.py \
  tests/test_generation_checkpoint_port_contract.py
```

Confirm from that output that no SQL checkpoint adapter exists, that
`SqlAlchemyWorkflowCheckpointStore` is a different concept, that
`tests/canonical_storage/test_generation_runs.py` is already the SQL contract
suite, and that `tests/features/generation_run_lifecycle.feature` already
covers checkpoint approve and respond-twice in memory. Confirm the head:

```bash
uv run alembic heads
```

Expected: a single head, `20261010_000013 (head)`. More than one head means
stop and escalate; a *different* single head means another revision landed, so
renumber this plan's revisions and update the trace table before writing code.
Likewise confirm the next free ADR number with `ls docs/adr/`.

Re-measure the runtime baseline the `Tolerances` entry depends on, alone on the
host:

```bash
make test 2>&1 | tee /tmp/baseline-episodic-$(git branch --show-current).out
```

Record the pass, skip, and wall-clock figures in `Artefacts and notes`.

Confirm the Hecate blind spot D-12 addresses is still present:

```bash
rg -n "generation_run_ports|generation_run_errors" pyproject.toml
```

Expected: no match inside `[tool.hecate.groups]`.

### Stage B — red tests

Write the failing tests before any production code.

1. Add `tests/generation_run_contract_scenarios.py` as a plain module of
   `async def scenario_*(store, *, prepare_run, read_fresh)` **functions** —
   not an abstract test base class. Two reasons. First, plain shared-helper
   modules are this repository's actual convention
   (`tests/canonical_storage/_generation_run_support.py`,
   `tests/steps/source_intake_support.py`). Second, and decisively, a
   `Test`-prefixed class in an uncollected module is **still collected** when
   imported into a collected module, under the importer's namespace, where an
   abstract fixture raises. Any class in this module must therefore not carry a
   `Test` prefix at all. Note the deliberate departure: at the `tests/` root
   the majority convention prefixes support modules
   (`test_generation_run_port_contract_support.py`). The unprefixed
   subdirectory convention is the better one — prefixed support modules get
   collected for no reason — and new root-level support modules should follow
   it. Scope the module to the **checkpoint** scenarios plus the composite-port
   shape check. Do not migrate the ~30 run and event scenarios: they are
   already covered by `tests/canonical_storage/test_generation_runs.py`,
   `test_generation_run_claims.py`, `test_generation_run_terminal_claims.py`,
   and the property module, and re-running them against SQL would pay
   py-pglite's per-function cost for no new information. The three hooks are
   not optional. `prepare_run` is a no-op in memory and
   `persist_generation_run_prerequisites(session_factory, run)` in SQL —
   **every** SQL scenario needs it, because `generation_runs.episode_id` and
   `source_bundle_id` are foreign keys to `episodes` and `ingestion_jobs`, and
   the existing helper commits a series profile, TEI header, episode, and
   ingestion job across three units of work before any run can be created.
   Without it every SQL scenario dies on `IntegrityError`, not on the intended
   missing-method error. `read_fresh` is a no-op lookup in memory and
   commit-plus-new-unit-of-work in SQL; INV-CKPT-2 and INV-CKPT-3 both need it.
2. Re-point `tests/test_generation_checkpoint_port_contract.py` at those
   scenario functions with `InMemoryGenerationRunStore`. Run it; it must still
   pass. This is a pure refactor and the safety net for step 3.
3. Add the SQL parameterization **into**
   `tests/canonical_storage/test_generation_runs.py`. Run it. It must fail with
   `AttributeError` on `create_checkpoint`. Record that transcript — it is the
   red evidence for INV-CKPT-1.
4. Add `tests/canonical_storage/test_review_checkpoint_migration.py`
   (INV-MIG-2) and `tests/canonical_storage/test_review_checkpoints.py`
   (INV-CKPT-3, INV-COMMIT-1). Both must fail because the table does not exist.
5. Add **one** scenario to the existing
   `tests/features/generation_run_lifecycle.feature` — the durability claim,
   which is the only thing Gherkin expresses that the contract suite does not.
   Do not create a second checkpoint feature file, and do not restate
   INV-CKPT-2 or INV-CKPT-4 in Gherkin; they are contract assertions in
   costume, and each costs a py-pglite fixture setup.

```gherkin
  Scenario: A responded checkpoint survives a new unit of work
    Given a generation run persisted in PostgreSQL
    And a checkpoint created against that run
    When the reviewer responds with action "approve"
    And the unit of work is committed and closed
    Then reading the checkpoint in a new unit of work reports status "responded"
    And the recorded reviewer action is "approve"
```

   Extend `tests/steps/test_generation_run_lifecycle_steps.py` using the
   repository's `@scenario`-decorator style (`scenarios()` appears nowhere in
   the tree) and `parsers.parse` for placeholders.

Stage B ends when every new test fails for the intended reason — a missing
table or missing method, not an import error, a fixture typo, or a foreign-key
violation.

### Stage C — implementation

1. **Enums.** In `episodic/canonical/storage/models_base.py`, add
   `REVIEW_CHECKPOINT_STATUS` and `REVIEW_CHECKPOINT_ACTION` using the existing
   `values_callable` idiom.
2. **ORM model.** Add
   `episodic/canonical/storage/review_checkpoint_models.py` with
   `ReviewCheckpointRecord` per the table in `Interfaces and dependencies`.
   Re-export from `models.py` and `storage/__init__.py`.
3. **Migration.** Add
   `alembic/versions/20261020_000014_add_review_checkpoints.py` (the plan's
   `YYYYMMDD` placeholder resolved to the day it was written), chained off
   `20261010_000013`. Follow `20260624_000010_add_generation_run_tables.py`
   exactly — not the current head, `20261010_000013`, which is an offline-aware
   constraint rename with a catalogue precondition check and a different shape
   entirely: module docstring, a private `_enum(name, *values)` helper returning
   `postgresql.ENUM(*values, name=name, create_type=False)`, and
   `_create_enums` / `_drop_enums` / `_create_*_table` / `_drop_*_table`
   helpers composed by `upgrade()` and `downgrade()`. Create enums before the
   table and drop them after it. The developers' guide prescribes
   `alembic revision --autogenerate`; run it first to catch drift, then
   restructure the output to match `000010`'s helper decomposition, which
   autogenerate does not produce. Put a **Data loss** line in the module
   docstring: downgrading this revision destroys every reviewer decision. Run
   `make check-migrations`.
4. **Mappers.** Add
   `episodic/canonical/storage/review_checkpoint_mappers.py` with three
   functions, not two:
   - `checkpoint_from_record` — validates the `options` shape explicitly (D-4)
     and restores a `tuple[str, ...]`.
   - `checkpoint_to_record` — writes `created_at` **explicitly**; the column's
     `server_default` must not win, or the entity returned by
     `create_checkpoint` disagrees with the persisted row.
   - `apply_checkpoint_to_record(record, checkpoint) -> None` — copies mutable
     fields onto an already-attached record in place. Without it the transition
     methods cannot persist: `checkpoint_to_record` manufactures a *new*
     record, and `session.add()` would raise on the primary key. The three
     transition methods must route through this rather than mutating inline,
     which is exactly the drift INV-CKPT-1 guards against.
5. **Adapter.** Add `episodic/canonical/storage/review_checkpoints.py` with
   `SqlAlchemyReviewCheckpointStore(session, *, runtime=None, metrics=None)`.
   It must:
   - Delegate every state change to the domain transition and persist the
     returned entity. Do not reimplement the rules.
   - Let `CheckpointAlreadyTerminal` propagate unchanged.
   - Raise `RunNotFound` when the parent run is absent and `CheckpointNotFound`
     when the checkpoint is absent. Check run **existence only** — do not call
     `_require_mutable_run`, which would raise `RunAlreadyTerminal` and diverge
     from the in-memory adapter (INV-CKPT-5).
   - Wrap the insert in `async with self._session.begin_nested():`, mirroring
     `create_run`, so a foreign-key violation does not poison the outer
     transaction and abort unrelated pending writes.
   - Apply transitions by **compare-and-set**, not `with_for_update()` — see
     D-10 and ADR-018. Issue
     `UPDATE review_checkpoints SET ... WHERE id = :id AND status = 'created'`,
     check `rowcount`, and on a miss re-read to distinguish
     `CheckpointNotFound` from `CheckpointAlreadyTerminal`. Mirror
     `SqlAlchemyEpisodeRepository.update`, which is the established shape.
   - Emit structured log events with the **`sql_review_checkpoint_store.`**
     prefix, matching `sql_generation_run_store.` in the run adapter. "The same
     events as the in-memory mixin" would wrongly give both adapters the same
     prefix.
   - Increment the metrics in `Interfaces and dependencies` through the
     existing `MetricsPort`, as `SqlAlchemyWorkflowCheckpointStore` already
     does.
   - `flush()` but never `commit()`.
6. **Compose.** Add
   `episodic/canonical/storage/generation_run_port_adapter.py` with
   `SqlAlchemyGenerationRunPortAdapter`, holding a
   `SqlAlchemyGenerationRunStore` and a `SqlAlchemyReviewCheckpointStore` and
   delegating to each. It satisfies the composite `GenerationRunPort`.
7. **Port docstrings.** Promote the contracts this plan discovered into
   `episodic/canonical/generation_run_ports.py` as class-level Notes and NumPy
   `Raises` sections. This is not optional polish: it is where the contract
   lives once this plan is archived. Today
   `GenerationCheckpointPort.create_checkpoint` reads, in full, "Persist a
   checkpoint." — from which two independent implementers could not agree on
   whether the parent run is validated, whether its status matters, what a
   duplicate identifier does, whether the return value is the input or a
   re-read, which exception a missing checkpoint raises, or whether `options`
   ordering survives. At minimum, document: gaplessness and its single-writer
   precondition on `GenerationEventLog`; `RunNotFound` and `RunAlreadyTerminal`
   on `append_event`; `RunNotFound` on `list_events`, `count_events`, and
   `create_checkpoint`; `CheckpointNotFound` and `CheckpointAlreadyTerminal` on
   the three transitions; the duplicate-identifier rule; the
   existence-not-status precondition; and that adapters may impose length
   limits.
8. **Wire the unit of work.** Change
   `episodic/canonical/unit_of_work_protocols.py` to
   `generation_runs: GenerationRunPort`, instantiate the composite in
   `SqlAlchemyUnitOfWork.__aenter__`, and update `NoopGenerationRunPort`. Run
   `make typecheck` and fix every implementer it names in the same commit.
   Import discipline: PR 277 moved `uow.py`'s imports **out of**
   `if typ.TYPE_CHECKING:`, because `mock.create_autospec` evaluates method
   annotations at runtime and deferred imports raise `NameError`. They now
   carry named Ruff suppressions, for example
   `# ruff: ignore[typing-only-first-party-import] - autospec resolves annotations`.
   Any import added here must follow that convention, or the latent bug PR 277
   fixed comes straight back. Also update the `generation_runs` entry in the
   `SqlAlchemyUnitOfWork` class docstring's `Attributes` section, which
   currently names `SqlAlchemyGenerationRunStore`.
9. **Commit safety.** In `SqlAlchemyUnitOfWork.__aexit__`, when `exc is None`
   and the session has pending state
   (`session.new or session.dirty or session.deleted`), emit a `warning` before
   closing. One branch; it converts the most likely durability bug in the next
   slice from invisible to greppable (Risk 4, INV-COMMIT-1).
10. **Skylos.** Pre-write the `[[tool.skylos.dead_code.entrypoints]]` entries;
    the gate scans `alembic episodic openai_test_types.py` and tests do not
    count as callers. Two certain hits: the migration's `_drop_enums` and
    `_drop_*_table` helpers, added to the existing `type = "function"` entry
    that lists the `20260624_000010` downgrade helpers; and
    `SqlAlchemyReviewCheckpointStore`, which has no production caller until
    2.6.3. For the store, add a **new** `type = "class"` entry rather than
    joining the one that lists `InMemoryGenerationRunStore`, whose reason
    ("instantiated by application composition and local-development
    consumers") would be false here. The honest reason is "no runtime caller
    until roadmap 2.6.3". Match any method entry as `type = "method"`.
11. **Architecture gate.** Apply D-12: add the two port modules to
    `domain_ports`, run the negative control it describes, and record the
    transcript.
12. **Duplication gate.** Run `make lint` and read the nose report before
    reaching for an exception. Extract shared guards (for example the
    checkpoint-transition argument checks) into a helper both adapters call
    where that is simpler. Only a genuine port-shaped parallel between
    `episodic/canonical/storage/review_checkpoints.py` and
    `episodic/canonical/adapters/generation_checkpoints.py` earns a
    `make duplication-allow FIRST=... SECOND=... REASON=...` entry.

### Stage D — lease reclamation (EP-M4, gated)

Start only if Stage C is fully green. Re-read D-6 and the matching `Tolerances`
entry: if this starts to require a scheduler, a Celery beat entry, or a
long-running worker, **stop and escalate**.

1. Add `fail_expired_leases` to the composite `GenerationRunPort` — **not** to
   `GenerationRunRepository` (D-6):

```python
async def fail_expired_leases(
    self,
    *,
    now: dt.datetime,
    limit: int = 100,
) -> tuple[GenerationRun, ...]:
    """Fail runs whose execution lease expired at or before ``now``."""
    raise NotImplementedError
```

   Contract, all of which belongs in the docstring: selects runs with
   `status == running`, non-null `lease_expires_at <= now`, and **no checkpoint
   in `created`**; appends the `run.failed` event **before** the status update
   (see INV-LEASE-1); uses `now` for the predicate *and* for `ended_at`,
   `updated_at`, and the event's `occurred_at`, so one call does not end up
   with two different "nows"; orders by `(lease_expires_at, id)` so a backlog
   drains oldest-first deterministically; returns the runs *post-transition*;
   raises `ValueError` for non-positive `limit`; and requires callers draining
   a backlog to re-invoke until an empty tuple returns.
2. Implement in both adapters. In memory this is necessarily a no-op returning
   `()`, because `GenerationRun` has no lease field — record that in the
   docstring so the shared suite does not certify the no-op as equivalence.
3. **Delete the duplicates.** Re-express `_recover_expired_lease` in
   `test_sql_generation_run_property_contract.py` and
   `_manually_fail_expired_run` in `test_generation_run_claims.py` as calls to
   the new method. This is an acceptance criterion, not a nicety: without it
   the slice ships a fourth copy of the same transaction.
4. Add the revision `20261020_000015_add_expired_lease_index.py` (the plan's
   `YYYYMMDD` placeholder resolved to the day it was written) for the partial
   index `ix_generation_runs_expired_lease` on `(lease_expires_at)` with
   `postgresql_where=sa.text("status = 'running'")`, mirrored exactly in the ORM
   `__table_args__`. **Its own revision** — never edit `000014`, which EP-M1
   already applied (Risk 6). Follow
   `episodic/canonical/storage/reference_models.py` and
   `alembic/versions/20260228_000004_add_reference_document_model.py`, the
   established partial-index precedent, rather than improvising the predicate
   form.
5. **Keep the manual SQL runbook** in `docs/developers-guide.md`. Do not
   replace it. At 03:00 an operator with a `psql` prompt and a correct,
   `FOR UPDATE`-guarded procedure is better served than one holding a
   documented Python method that no scheduler invokes and that they would have
   to drive from an ad-hoc script against production. Add the method alongside,
   with a short invocation snippet or a `python -m` entry point mirroring
   `migration_check.py`, and say plainly that nothing schedules it yet and how
   to tell a backlog remains (`len(result) == limit`).

### Stage E — documentation and reconciliation

1. `docs/developers-guide.md` §"Generation-run domain ports": describe the SQL
   checkpoint store, the composite adapter, and the widened
   `CanonicalUnitOfWork.generation_runs` type. Add a note on deployment
   ordering: migrate before deploying, because the schema leads the code, and
   the application does not apply migrations itself.
2. `docs/users-guide.md`: **leave the "Generation runs and review checkpoints"
   section alone.** Its current text — "this release establishes the domain
   model and in-memory reference port used by those later endpoints" — remains
   accurate, because no production path creates a checkpoint until 2.6.3.
   Telling users that checkpoints "are durably stored and survive a restart"
   would describe a capability with no entry point, and an operator who
   believes checkpoints are live will not look for the missing scheduler.
   Revisit in 2.6.3.
3. Add `docs/adr/adr-024-review-checkpoint-persistence.md` — **024**, the next
   free number at the last reconciliation; re-check with `ls docs/adr/` —
   following the shape of `adr-015-generation-run-port-split.md` (Status,
   Context, Decision, Consequences with Positive/Negative/Neutral, References)
   rather than the style guide's literal template. Every ADR from 010 onwards
   does the same, so this is house practice, not a deviation. Cover **D-2 and
   D-3** as decisions; D-4, D-5, D-7, D-8, and D-9 belong in one Consequences
   paragraph each, since "use JSONB like everywhere else" is a convention
   application, not a decision. Include: the `ALTER TYPE` downgrade recipe from
   Risk 7; the `Checkpoint` / `review_checkpoints` naming asymmetry from D-7;
   the D-9 half-constraint and why; that a returned entity is provisional until
   its unit of work commits; that the aggregate's deletion policy is `RESTRICT`
   under ADR-018's audit-trail policy; and D-11's reasoning that a review
   checkpoint is not a versioned aggregate and so needs no ADR-019-style
   history table. Add it to `docs/contents.md` after the ADR-023 entry, and
   reference it from the design document.
4. Correct `docs/episodic-tui-api-design.md`: at line 1025 it states event
   logs are "partitioned by `generation_run_id` for efficient range queries".
   They are not, and should not be — `generation_run_id` is a UUID, so that
   means hash partitioning, which buys nothing when every query is already
   `WHERE generation_run_id = ?` served in O(log N) by the composite index. The
   only partitioning that would pay is range on `created_at`, and its payoff is
   cheap retention drops. Leaving an unimplementable performance claim in an
   authoritative document is how someone eventually builds it.
5. Reconcile the roadmap: item 2.6.2 is ticked by the implementor on
   completion, with a one-line note that run and event persistence landed
   earlier under 4.3.2. Add the ADR-015 renumbering follow-up (see
   `Conformance basis`) and the follow-ups named in `Residual gaps`.
6. Run `make fmt`, then `make markdownlint` and `make nixie`.

Recorded interaction: `make fmt` can introduce MD013 violations on long inline
code spans. If `make markdownlint` fails after `make fmt`, wrap or shorten the
offending span rather than reverting the format.

## Milestones and plateaus

### EP-M1 — review-checkpoint table and reversible migration

- Outcome: `review_checkpoints` exists in the ORM metadata and the migration
  history with both enums. No adapter uses it yet; the schema simply leads the
  code.
- Requirements: `DESIGN-ORCH-CKPT`, `ROADMAP-2.6.2` (migration half).
- Acceptance evidence: `make check-migrations` clean;
  `test_review_checkpoint_migration.py` passes including both `pg_type`
  assertions.
- Conformance check: single head; no collision with `workflow_checkpoints`;
  enum naming follows `models_base.py`; no existing persisted format changed.
- Recovery: `uv run alembic downgrade -1`, delete the revision file, re-run
  `make check-migrations`. Safe **only at this milestone** — see EP-M2.
- Compatibility decision: none required. The table is new.

### EP-M2 — SQL checkpoint store and composite port

- Outcome: `uow.generation_runs` satisfies `GenerationRunPort`; reviewer
  checkpoints are durable when written; uncommitted work warns.
- Requirements: `API-GENRUN-CKPT`, `ADR-015`.
- Acceptance evidence: checkpoint scenarios pass against both adapters; the
  durability scenario passes; INV-COMMIT-1 passes.
- Conformance check: `make check-architecture` passes; no existing port
  signature changed; every file under 400 lines; no new dependency; **ADR-018
  conformance** — transitions use the compare-and-set shape with a typed domain
  error (D-10), the foreign key is `RESTRICT` under the audit-trail policy, and
  D-11 records why no history table is required; the two port modules are in
  Hecate's `domain_ports` group with the D-12 negative control recorded; and
  any duplication exception is reasoned and no broader than one file pair.
- Recovery: **code may be reverted freely; the migration may not.** Reverting
  this commit leaves the table in place, unused and harmless, and rows written
  before the revert survive and are picked up on re-apply. Downgrading revision
  `000014` after any checkpoint has been written **destroys reviewer
  decisions**; take a dump of `review_checkpoints` first.
- Remaining gaps: no production caller until 2.6.3; lease reclamation;
  documentation.
- Compatibility decision: none. `CanonicalUnitOfWork` is an
  application-internal, pre-1.0 protocol with one implementer. Widening it and
  updating all implementers in one commit is correct; a transitional narrower
  alias would be compatibility theatre.

### EP-M3 — contract equivalence and sequencing evidence

- Outcome: one scenario set drives both adapters; durability and allocation
  correctness are evidenced against a real PostgreSQL engine, within the limits
  AXIOM-3 imposes.
- Requirements: `ROADMAP-2.6.2` (integration-test half), `API-GENRUN-SEQ`.
- Acceptance evidence: INV-SEQ-1, INV-CKPT-1 through INV-CKPT-5, and
  INV-COMMIT-1 discharged, each with its non-vacuity check. **Recording the
  negative-control transcripts is an acceptance condition, not a note** — they
  are the only thing separating "we have a test" from "we have a test that
  cannot fail".
- Conformance check: suite runtime inside the `Tolerances` figures;
  `max_examples=25` for the sequencing property.
- Recovery: tests are additive; delete the new modules to return to EP-M2.

### EP-M4 — lease reclamation primitive (gated)

- Outcome: one tested method replacing three copies of the same transaction.
  No scheduler.
- Requirements: `EP-4.3.2-DEFER`.
- Acceptance evidence: INV-LEASE-1 discharged over the full state partition
  including the open-checkpoint case; **both duplicated test helpers deleted**
  and re-expressed as calls to the method.
- Conformance check: the method sits on the composite port; the partial index
  is in its **own** revision and mirrors the ORM exactly; no worker, scheduler,
  or beat entry added.
- Recovery: revert the port method, both implementations, and revision
  `000015`. EP-M3 remains a valid plateau.
- Remaining gaps: nothing schedules the reclamation, and nothing detects a
  stuck run. Both stated explicitly in the developers' guide.
- Gate history: the first `make lint` run on this milestone was **red** at
  `Makefile:145` (`$(DF12_PYLINT)`, `C9105 reexport-by-assignment`), which
  aborted the recipe with C9112, `ambrleaks`, the Skylos dead-code scan, and
  the nose duplication gate unrun — unverified, not passing. Repaired by
  inlining the status into the predicate and dropping the unconsumed constant;
  the predicate is unchanged at `status = 'running'`, checked by exec-ing the
  pre- and post-repair modules side by side against a stubbed enum.

### EP-M5 — documentation and reconciliation

- Outcome: developers' guide, ADR-024, `docs/contents.md`, the design-document
  cross-reference, and the corrected partitioning claim are current. The users'
  guide is deliberately unchanged.
- Acceptance evidence: `make markdownlint` and `make nixie` pass.
- Conformance check: every `Surprises & discoveries` entry reconciled against
  `Conformance basis`; the ADR-015 collision and the `Residual gaps` items
  recorded as roadmap follow-ups rather than silently dropped.
- Recovery: documentation-only; revert freely.

## Concrete steps

Run everything from the repository root.

```bash
git branch --show-current
uv run alembic heads
```

Expected:

```plaintext
20261010_000013 (head)
```

The focused red test after Stage B step 3:

```bash
uv run pytest tests/canonical_storage/test_generation_runs.py -v \
  2>&1 | tee /tmp/red-episodic-$(git branch --show-current).out
```

Expected — the intended failure, not an import error or `IntegrityError`:

```plaintext
E   AttributeError: 'SqlAlchemyGenerationRunStore' object has no attribute 'create_checkpoint'
```

After Stage C step 3:

```bash
make check-migrations 2>&1 | tee /tmp/migrations-episodic-$(git branch --show-current).out
```

Expected:

```plaintext
No schema drift detected.
```

Full gates at every milestone boundary, **sequentially** — this environment
uses build caching and parallel gate runs defeat it:

```bash
make check-fmt && make typecheck && make lint && make check-migrations && make test
```

Prefer delegating that run to the `scrutineer` subagent, which runs the gates
in order, tees each to a log under `/tmp`, and returns a bounded report. When
it reports a failure, read the log it cites rather than re-running the gate.

Commit at each milestone boundary.

## Validation and acceptance

**Red-Green-Refactor evidence.** For EP-M1 through EP-M4, record the red
command and its failure with the reason quoted, the green command and its pass,
and the refactor sequence and its pass.

Do **not** use the `xfail(strict=True)` marker dance. This plan already
mandates observing red before green and recording the transcript; adding and
removing markers is churn on top of a discipline that already works.

**Behavioural evidence.**

```bash
uv run pytest tests/steps/test_generation_run_lifecycle_steps.py -v
```

Expected: the existing scenarios plus the new durability scenario pass. Before
EP-M2 the new one must fail.

**Durability demonstration.** The observable outcome that matters: create a run
and a checkpoint in one unit of work, respond, commit, close, then in a new
unit of work read the checkpoint back with status `responded` and the
reviewer's action intact.

Quality criteria — what "done" means:

- Tests: `make test` passes with no new failures, skips, or `xfail` markers,
  within the `Tolerances` runtime figures.
- Verification: INV-SEQ-1, INV-CKPT-1..5, INV-COMMIT-1, INV-MIG-1, INV-MIG-2
  and (if EP-M4 runs) INV-LEASE-1 discharged, each with its recorded
  non-vacuity check and negative-control transcript. Obligations left
  undischarged must be named in `Residual gaps` with their reason.
- Lint and typecheck: `make check-fmt`, `make lint`, `make typecheck`, and
  `make check-architecture` pass, with Skylos entrypoints in place.
- Migrations: `make check-migrations` clean; a single head; no already-merged
  revision edited.
- Documentation: `make markdownlint` and `make nixie` pass.

## Idempotence and recovery

- `make check-migrations` starts an ephemeral py-pglite instance and leaves no
  state behind.
- The py-pglite fixtures drop and recreate the `public` schema per test
  function, so a failed test cannot poison a later one.
- Each milestone is a separate commit, so `git revert` returns the tree to the
  previous plateau.
- **One destructive step exists**, contrary to the previous draft's blanket
  claim: `alembic downgrade` past revision `000014` drops `review_checkpoints`
  and every reviewer decision in it. Before EP-M2 this is harmless because the
  table is empty; after it, take a dump first. Nothing else in this plan
  touches production data or an external service.

## Artefacts and notes

Record here as work proceeds:

- the red transcript from Stage B step 3;
- the negative-control transcript for INV-SEQ-1 (cross-run predicate removed);
- the two `pg_type` transcripts for INV-MIG-2, one per enum;
- the D-12 negative-control transcript (`ARCH001` on a port importing storage);
- the `make test` baseline and final wall-clock. Historical figures, neither of
  them the Stage A baseline: **130.58 s, 1227 passed, 3 skipped** at `5af0638`,
  and **334.48 s of pytest time, 1725 passed, 1 skipped** on 2026-10-15 under
  host contention. Per-test `migrated_engine` setup was 0.20–0.38 s after a
  ~3.8 s session-scoped start.

### Stage A baseline, measured 2026-10-20 20:24Z

Command, per the `Tolerances` entry:

```bash
make test 2>&1 | tee /tmp/baseline-episodic-2-6-2-repository-contracts-and-alembic-migrations.md.out
```

Raw result:

```plaintext
1 failed, 1723 passed, 1 skipped, 30 warnings, 1 error in 748.53s (0:12:28)
```

**748.53 s is pytest's own figure.** Measured wall clock, including the `build`,
`crosshair`, and `test-workflow-contracts` prerequisites, was **758 s**. The
`Tolerances` growth check reads wall clock, so 758 s is the referent.

Two qualifications, both required to read that number honestly.

**The host was not idle.** `nproc` reports **24**, and load average sat between
27 and 67 throughout the run: this session holds the only candidate worktree,
but other repositories (cuprum, dev-env-rocky) were building and testing
concurrently and were correctly left alone. `Tolerances` specifies an
otherwise-idle re-measure; this is therefore a *contended* baseline, and it is
the figure this plan compares against because it is the only one taken on this
revision. The scrutineer independently recorded the start load as 67.19 and the
end load as 27.45.

**Both non-passes are harness timeouts, not defects.** Neither is on a path
this plan touches:

```plaintext
FAILED tests/steps/test_http_service_scaffold_steps.py::test_granian_serves_health_endpoints
  - Failed: Timeout (>180.0s) from pytest-timeout.
ERROR tests/test_env_runtime_wiring.py::test_create_app_from_env_wires_database_readiness_probe[async_dialect_url]
  - Failed: Timeout (>180.0s) from pytest-timeout.
```

Wrapped to the 120-column code-block budget; the text is otherwise verbatim.

Re-run in isolation against the same tree, both pass in **12.55 s, 3 passed**.
They are load artefacts of the 180 s `pytest-timeout`, which is the same
shared-host contention failure mode recorded in the `Tolerances` runtime entry.
**Not verified:** the full `make test` was not re-run a second time, so this
inference rests on the isolated re-run and on neither target being touched by
this plan, not on a repeated green suite run. Baseline status for the purposes
of this plan is **1723 passed, 1 skipped, 0 failures attributable to this
slice**.

Contention-adjusted wall-clock, stated so the 15% growth check has a usable
referent: the two timeouts contribute 360 s of pure waiting and would otherwise
cost ~12.55 s, so the run represents roughly **410 s** of real work. Both
figures are recorded; the comparison at EP-M5 will be made against a
like-for-like re-measurement under comparable load, not against a figure this
plan has quietly adjusted in its own favour.

One admission observation worth carrying forward: `build-limits-status` was
healthy (exit 0, `capacity 4, held 4`) at both ends of the run, with ~305
waiting requests held entirely by Rust crates in other agents' worktrees and
none from this repository. No gate here compiles Rust, so compile admission
never gated this baseline — but a Python-only gate run is not evidence that
admission is idle.

Per-test `migrated_engine` setup, from `--durations=0` on
`tests/canonical_storage/test_generation_runs.py` (10 passed, 6.78 s total):
**0.22–0.44 s** per function after a **3.39 s** session-scoped py-pglite start.
Both are inside the `Tolerances` figures (0.5 s per test; ~3.8 s session
start), so no escalation.

Stage A sweep results, all re-confirmed against this revision rather than
carried forward from the plan:

- `uv run alembic heads` reports the single head `20261010_000013`, as
  expected; the revision counter is authoritative and `000014`/`000015` remain
  free.
- `ls docs/adr/` ends at `adr-023`, so **ADR-024 is free**.
- The Hecate blind spot D-12 addresses is still present:
  `rg -n "generation_run_ports|generation_run_errors" pyproject.toml` matches
  neither module inside `[tool.hecate.groups]`.
- No SQL checkpoint adapter exists; `SqlAlchemyWorkflowCheckpointStore` is the
  different orchestration concept; the composite `GenerationRunPort` is
  implemented only by `InMemoryGenerationRunStore`.
- `tests/canonical_storage/test_generation_runs.py` is already the SQL contract
  suite (368 lines, against a 400-line `max-module-lines` ceiling), and
  `tests/features/generation_run_lifecycle.feature` already covers checkpoint
  approve and respond-twice in memory — both as the plan states.

One constraint discovered during the sweep and not stated in the plan: the
400-line ceiling leaves **32 lines** of headroom in
`tests/canonical_storage/test_generation_runs.py`, which is the file Stage B
step 3 adds the SQL parameterization to. The scenario module therefore has to
carry the assertions, and the SQL parameterization has to be a thin driver.

### Stage B red evidence, measured 2026-10-20 23:20Z

Stage B's closing condition is that every new test fails for the intended
reason. The full set, run together:

```bash
uv run pytest tests/test_generation_checkpoint_port_contract.py \
  tests/canonical_storage/test_generation_run_checkpoint_contract.py \
  tests/canonical_storage/test_review_checkpoint_migration.py \
  tests/canonical_storage/test_review_checkpoints.py \
  tests/steps/test_generation_run_lifecycle_steps.py \
  -q -p no:randomly --timeout=120 \
  2>&1 | tee /tmp/RED-stage-b-full-2-6-2-repository-contracts-and-alembic-migrations.md.out
```

```plaintext
36 failed, 24 passed, 1 warning in 12.45s
```

Every failure falls into one of four intended classes. Counted, not sampled:

- **31 ×**
  `AttributeError: 'SqlAlchemyGenerationRunStore' object has no attribute 'create_checkpoint'`
  (also `respond_to_checkpoint`, `time_out_checkpoint`, `cancel_checkpoint`).
  This is the INV-CKPT-1 red the plan names by name.
- **1 ×** `AssertionError: checkpoint sub-port` — the composite does not yet
  satisfy `GenerationCheckpointPort`.
- **3 ×** a missing `review_checkpoints` relation:
  `AssertionError: the migration must create the review_checkpoints table`,
  `AssertionError: the re-upgrade must recreate both enum types`, and
  `psycopg.errors.UndefinedTable: relation "review_checkpoints" does not exist`.
  These are the INV-MIG-2 and INV-CKPT-3 reds.
- **4 ×** `Failed: DID NOT RAISE` — three `CheckpointAlreadyTerminal` and one
  `CheckpointAlreadyExists`, all from the in-memory driver. These are
  INV-CKPT-5's "neither adapter checks either today", surfacing one stage
  earlier than the plan sequenced them; recorded as an observation.

No import error, no fixture typo, and no foreign-key violation appears in the
set. The SQL driver's own transcript, taken separately, is **23 failed in 9.49
s**.

The one non-vacuity obligation Stage B cannot discharge is INV-MIG-2's: the
downgrade test passes today because there is nothing to drop. That is a Stage C
obligation and is recorded as such.

### D-12 negative-control transcript, measured 2026-10-21 02:05Z

Stage C step 11 requires proof that adding the two port modules to
`domain_ports` actually brought them *under* the gate, rather than leaving them
ungrouped as before while the suite merely stayed green. The control is to
introduce the exact violation the gate is supposed to catch — a port module
importing a storage adapter — and confirm `ARCH001` fires.

Injected into `episodic/canonical/generation_run_ports.py`, immediately after
its existing `import typing as typ` line:

```python
import episodic.canonical.storage  # NEGATIVE CONTROL - temporary
```

```plaintext
$ make check-architecture
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools \
  /home/leynos/.local/bin/uv run hecate check
ARCH001: episodic.canonical.generation_run_ports:18 imports forbidden module
  episodic.canonical.storage (domain_ports -> outbound_adapter)
make: *** [Makefile:203: check-architecture] Error 1
GATE_EXIT=2
```

The verdict named the injected line (18) and the correct group pair, so the
control is specific rather than incidental. The injection was then removed
verbatim and the gate re-run:

```plaintext
$ make check-architecture
hecate: architecture check passed
GATE_EXIT=0
```

Both halves matter: the control shows the module is now checked, and the clean
re-run shows Stage C's own edits introduce no violation. Before D-12 the same
injection would have produced no finding at all, because `checker.py` skips any
edge whose endpoint is ungrouped — which is exactly why the blind spot survived
until this slice.

The `pyproject.toml` half of D-12 sits in the EP-M2 commit, with the two
prefixes placed alphabetically between `generation_quality` and
`history_protocols`. `composition_root` is the only group ordered before
`domain_ports` that could capture them, and it matches only
`episodic.api.runtime` and `episodic.worker.runtime`, so no first-match
misrouting is possible.

### Negative-control transcripts, measured 2026-10-21 05:05Z

The four controls the Verification plan requires as acceptance evidence. A
green suite does not discharge any of them: each asks whether a *specific*
assertion is load-bearing, which only the corresponding break can answer. All
four were run against frozen candidate `60f8f740`, with the break applied,
observed, and then reverted; the reverted files are byte-identical to the commit
(`git hash-object` re-checked, `git status --porcelain` empty).

#### INV-MIG-2 — each enum drop fails independently

Revision `20261020_000014` drops two native enums. Removing *either*
`.drop(bind, checkfirst=True)` call alone must fail
`test_downgrade_removes_table_and_both_enums`, or the test only proves that
*something* was dropped.

```plaintext
# status enum drop removed
1 failed, 3 passed
AssertionError: downgrade must drop both enum types

# action enum drop removed, status drop restored
1 failed, 3 passed
AssertionError: downgrade must drop both enum types
```

Both halves fail independently, so the obligation is non-vacuous: neither drop
is redundant, and the test discriminates each one separately.

#### INV-SEQ-1 — the per-run predicate in the `MAX(seq)` subquery

`append_event` allocates its sequence with
`SELECT max(seq) FROM generation_events WHERE generation_run_id = :run_id`.
Dropping the `generation_run_id` predicate (leaving a bare
`SELECT max(seq) FROM generation_events`) must break the cross-run case.

```plaintext
$ uv run pytest tests/canonical_storage/test_sql_generation_run_property_contract.py -p no:randomly -q
2 failed, 2 passed, 1 warning in 8.09s
FAILED test_sql_event_batches_are_gap_free_and_isolated
       - hypothesis.errors.FlakyFailure: Inconsistent results from replaying a test ...
FAILED test_sql_pages_match_creation_and_cursor_reference_slices
       - AssertionError: (GenerationEvent(id=UUID('01a15c52-148b-70c6-a25d-efe5e4d29...
```

The predicate is what keeps two runs' sequence spaces separate. Note the
control is deliberately **not** "remove `lock=True`": that variant provably
cannot reproduce, because `py-pglite`'s single WebAssembly backend serializes
every session, so no concurrent writer can ever be admitted to race. Removing a
predicate that the *serial* path evaluates is observable; removing a lock the
serial path never contends is not.

#### INV-CKPT-3 — options ordering and the scalar-over-array read

Two independent breaks, one per fidelity claim.

**(a) map `options` through `set()`.** Restores a tuple, but in hash order:

```plaintext
$ uv run pytest tests/canonical_storage/test_review_checkpoints.py -p no:randomly -q
1 failed, 4 passed, 1 warning in 3.37s
FAILED test_options_keep_their_order_across_a_fresh_unit_of_work
       - AssertionError: option order: ('request_changes', 'edit', 'approve')
```

The declared order `("edit", "approve", "request_changes")` comes back
permuted, so the ordering assertion — the reason the fixture options are
deliberately non-alphabetical — is exactly what catches it.

**(b) write `'"approve"'::jsonb` into `options`.** The CHECK constraint
`ck_review_checkpoints_options_array` makes that write unreachable through
normal SQL, so the control drops the constraint first and then performs it,
which is what makes this a control on the *read* path rather than on the
constraint. The read must fail loudly:

```plaintext
STORED_SCALAR='approve' python_type=str
1 passed, 1 warning in 2.96s
```

The stored value really is a Python `str`, and `_options_to_tuple` raises
`TypeError: checkpoint options must be a JSON array.` on it instead of
iterating it into seven single-character options. The sequencing matters: had
the mapper only checked `isinstance(raw, list)` without the guard, or iterated
a bare `raw`, this would have silently produced
`('a', 'p', 'p', 'r', 'o', 'v', 'e')` — a checkpoint with seven one-letter
choices that no other test would notice.

#### INV-CKPT-2 — the compare-and-set predicate, and a correction of record

**The plan's stated route for this control does not work, and the reason is a
real property of the design.** The Verification plan says to "widen the
compare-and-set predicate to `WHERE id = :id` and confirm every terminal case
then fails", and asserts that "the `WHERE status = 'created'` clause is
exercised by mutating stored state between calls, sequentially, which
`py-pglite` supports". Both sentences are **false as written**, and the control
was run before they were corrected:

```plaintext
$ # predicate widened to WHERE id = :id in _resolve
$ uv run pytest tests/test_generation_checkpoint_port_contract.py \
    tests/canonical_storage/test_generation_run_checkpoint_contract.py -q -p no:randomly
23 passed
```

The control did not fire, and this is not a gap in the test. In `_resolve` the
adapter calls `transition(checkpoint_from_record(record))`, and
`Checkpoint.respond`/`time_out`/`cancel` each call `_raise_if_terminal()`
*inside* that call — **before** `_resolve` builds the `UPDATE`. So on the
terminal cases the domain guard rejects the transition first, the statement is
never issued, and no predicate can be what refuses it. Two read-only probes
confirmed the mechanism across the whole suite:

```plaintext
# /tmp/sdlc-2-6-2-negctl/probe_cas_plugin.py — every UPDATE on review_checkpoints
total_update_statements_issued=14

# /tmp/sdlc-2-6-2-negctl/probe_layer.py — which layer refuses
CAS_RESOLVE_ENTERED: 27
DOMAIN_GUARD_RAISED CheckpointAlreadyTerminal: 10
LOST_RACE_ENTERED: 0
```

Fourteen `UPDATE` statements were issued for exactly the fourteen *successful*
transitions the suite performs (nine terminal-case setups, three transition
tests, one payload test, one duplicate test). Not one came from a refused
transition. `LOST_RACE_ENTERED: 0` is the decisive line: the `rowcount == 0`
branch is never entered, so the widened predicate has nothing to change. The 27
resolves reconcile as 3 + 1 + 9 + 9 + 1 + 3 + 1 across the scenario groups.

**The predicate is nevertheless load-bearing**, and the route that shows it is
one the plan did not anticipate: a caller holding a *stale pre-terminal* copy
of the record. Then the domain guard passes, the `UPDATE` is genuinely issued,
and `rowcount == 0` is the only thing refusing the transition. This is the
losing-writer path D-10 chose compare-and-set to make observable, reached by
giving one reader a stale view rather than by driving two live sessions — which
`py-pglite`'s single backend forbids, and which the plan's phrase "mutating
stored state between calls" describes but does not achieve. Two `monkeypatch`
sub-routes were needed to construct the stale reader: `Checkpoint` construction
rather than `dataclasses.replace` (it is not a dataclass), and a module-level
capture of the real `checkpoint_from_record` before stubbing (calling
`store_module.checkpoint_from_record` from inside the stub recurses).

With the row already terminal in `responded` and the reader still seeing
`created`:

```plaintext
# unmodified code, stale-writer route
CAS_RESOLVE_ENTERED: 1
LOST_RACE_ENTERED: 1
1 passed

# widened predicate, same route
LOST_RACE_ENTERED: 0        # absent — the branch is no longer reachable
Failed: DID NOT RAISE CheckpointAlreadyTerminal
```

So the control **does** fire on the predicate, and the row is silently
overwritten with a second transition when the predicate is widened. The design
is sound; only the plan's stated non-vacuity route was wrong, and the two
sentences quoted above have been corrected in the Verification plan to describe
the stale-writer route and to record why the sequential-mutation route cannot
reach the statement.

## Interfaces and dependencies

No new external dependency.

In `episodic/canonical/storage/models_base.py`:

```python
REVIEW_CHECKPOINT_STATUS = sa.Enum(
    CheckpointStatus,
    name="review_checkpoint_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
REVIEW_CHECKPOINT_ACTION = sa.Enum(
    CheckpointAction,
    name="review_checkpoint_action",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
```

`ReviewCheckpointRecord` on `__tablename__ = "review_checkpoints"`.
`updated_at` is storage-only, for operational triage, mirroring
`WorkflowCheckpointRecord`. Note its `onupdate` is a *client-side* SQLAlchemy
default, so any raw-SQL update leaves it stale and `compare_metadata` will not
notice; set it explicitly in any bulk statement.

| Column              | Type                            | Nullable | Notes                                                                                                                                                      |
| ------------------- | ------------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                | `postgresql.UUID(as_uuid=True)` | no       | Primary key, client-assigned UUIDv7                                                                                                                        |
| `generation_run_id` | `postgresql.UUID(as_uuid=True)` | no       | FK to `generation_runs.id`, `ondelete="RESTRICT"` per ADR-018's audit-trail deletion policy; **not** `CASCADE`                                             |
| `node`              | `sa.String(160)`                | no       | Orchestration node that raised the checkpoint                                                                                                              |
| `prompt`            | `sa.Text`                       | no       | Reviewer-facing prompt                                                                                                                                     |
| `options`           | `postgresql.JSONB`              | no       | Ordered JSON array of option strings; see the CHECK below                                                                                                  |
| `status`            | `REVIEW_CHECKPOINT_STATUS`      | no       | Not individually indexed; see the composite indexes below                                                                                                  |
| `response_action`   | `REVIEW_CHECKPOINT_ACTION`      | yes      | Set only when responded                                                                                                                                    |
| `response_payload`  | `postgresql.JSONB`              | no       | `server_default=sa.text("'{}'::jsonb")`; the domain type is non-optional `JsonMapping`, so a nullable column would admit two encodings of one domain value |
| `resolved_at`       | `sa.DateTime(timezone=True)`    | yes      | Instant the checkpoint left `created`, by response, time-out, or cancellation (D-8)                                                                        |
| `responded_by`      | `sa.String(240)`                | yes      | Reviewer identity                                                                                                                                          |
| `created_at`        | `sa.DateTime(timezone=True)`    | no       | `server_default=sa.func.now()`; the mapper writes the domain value explicitly                                                                              |
| `updated_at`        | `sa.DateTime(timezone=True)`    | no       | `server_default=sa.func.now()`, `onupdate=sa.func.now()`                                                                                                   |

Table 1: Columns of the `review_checkpoints` table.

```python
__table_args__ = (
    sa.CheckConstraint(
        "jsonb_typeof(options) = 'array' AND jsonb_array_length(options) > 0",
        name="ck_review_checkpoints_options_array",
    ),
    sa.CheckConstraint(
        "status <> 'responded' OR ("
        " response_action IS NOT NULL"
        " AND responded_by IS NOT NULL"
        " AND resolved_at IS NOT NULL)",
        name="ck_review_checkpoints_responded_fields",
    ),
    sa.Index(
        "ix_review_checkpoints_run_status",
        "generation_run_id",
        "status",
    ),
    sa.Index(
        "ix_review_checkpoints_open",
        "generation_run_id",
        postgresql_where=sa.text("status = 'created'"),
    ),
)
```

A standalone index on `status` is deliberately omitted: it is a four-value
enum, terminal rows accumulate monotonically, and PostgreSQL would seq-scan
past it for anything but a tiny table. The composite serves per-run listing and
the partial index stays small forever.

`GenerationCheckpointPort` gains one method, because otherwise nothing can
discover an open checkpoint — `get_checkpoint` needs an identifier the caller
must already hold, which leaves the durability claim half-delivered:

```python
async def list_checkpoints(
    self,
    run_id: uuid.UUID,
    *,
    status: CheckpointStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[Checkpoint, ...]:
    """List a run's checkpoints, newest-created last."""
    raise NotImplementedError
```

In `episodic/canonical/storage/review_checkpoint_mappers.py`:

```python
def checkpoint_from_record(record: ReviewCheckpointRecord) -> Checkpoint: ...
def checkpoint_to_record(checkpoint: Checkpoint) -> ReviewCheckpointRecord: ...
def apply_checkpoint_to_record(
    record: ReviewCheckpointRecord,
    checkpoint: Checkpoint,
) -> None: ...
```

In `episodic/canonical/storage/review_checkpoints.py`:

```python
class SqlAlchemyReviewCheckpointStore:
    """PostgreSQL adapter for the review-checkpoint port."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        runtime: GenerationRunStorageRuntime | None = None,
        metrics: MetricsPort | None = None,
    ) -> None: ...
```

In `episodic/canonical/storage/generation_run_port_adapter.py`:

```python
class SqlAlchemyGenerationRunPortAdapter:
    """Compose the run/event and review-checkpoint stores into one port."""

    def __init__(
        self,
        runs: SqlAlchemyGenerationRunStore,
        checkpoints: SqlAlchemyReviewCheckpointStore,
    ) -> None: ...
```

In `episodic/canonical/unit_of_work_protocols.py`:

```python
generation_runs: GenerationRunPort
```

Metrics to emit through the existing `MetricsPort`, following
`SqlAlchemyWorkflowCheckpointStore` and the launcher:

| Metric                                      | Detects                                               |
| ------------------------------------------- | ----------------------------------------------------- |
| `review_checkpoint_created_total`           | Checkpoints created                                   |
| `review_checkpoint_resolved_total{action}`  | Loss — created without a matching terminal transition |
| `review_checkpoint_open_gauge`              | Stuck reviews, before a reviewer complains            |
| `review_checkpoint_terminal_conflict_total` | Two reviewers racing, or a client retry storm         |

Table 2: Metrics emitted by the review-checkpoint store.

## Revision note

2026-10-18 (fourth revision) — Rebased onto `main` at `468923ed` and reconciled
against the tree, which had moved 77 commits since `5af0638`. The previously
pending PR 277 and PR 278 have both merged, so the `Pending pull requests`
section becomes `Changes on main since the first draft` and Risk 8 (about
implementing ahead of them) is retired. Two reservations this plan held were
taken in the meantime: migration `000013` (now the pricing-snapshot constraint
rename) and ADR-020 (now one of four new ADRs). The revisions become `000014`
and `000015`, with the date prefix left to the day they are written, and the
ADR becomes **ADR-024**. The domain module split means the frozen surface now
lives in `domain_generation.py` and `domain_enums.py` behind the `domain.py`
façade. New constraints cover the nose duplication gate, named Ruff and Pylint
suppressions, and Pylint's new reach into `tests/`. The absolute 165 s runtime
ceiling is withdrawn in favour of a relative one against a fresh Stage A
baseline, because the suite has grown from 1227 to 1725 tests. One new finding:
**Hecate does not classify `generation_run_ports` or `generation_run_errors`**,
so the hexagonal constraint this plan relied on was unenforced for its own
files. The new Risk 8 and D-12 put both modules into `domain_ports` in EP-M2,
with a negative control. The Skylos guidance is corrected so the checkpoint
store does not inherit a false entrypoint reason.

2026-08-23 (third revision) — Reconciled against two open pull requests. PR 278
takes ADR-018 and ADR-019, so this plan's ADR becomes **020**; more
substantially, its ADR-018 is now the governing record for versioning,
concurrency, and deletion policy, and this plan conforms to it in three places.
**D-10 replaces `SELECT ... FOR UPDATE` on the checkpoint row with
compare-and-set**, the shape ADR-018 names for concurrent writers racing on one
mutable row — which also converts an obligation that py-pglite cannot verify
into one it can. The foreign key becomes `ON DELETE RESTRICT` under ADR-018's
audit-trail policy, and **D-11** records why a review checkpoint is not a
versioned aggregate and needs no history table. PR 277 edits the four files
this plan changes most and establishes that persisted rows survive between
Hypothesis examples, which matters at `max_examples=25`; it also fixes
`uow.py`'s runtime-evaluated annotations, a convention any new import there
must follow. Both are now stated as dependencies, with a risk entry for
implementing ahead of them.

2026-08-23 (second revision) — Revised after a six-lens design review. The
substantive changes:

- **AXIOM-3 was false and is rewritten.** Two independent probes showed
  py-pglite serializes *all* transactions globally, including unrelated
  sessions. The previous draft's flagship obligation, INV-SEQ-1's concurrency
  claim, was unfalsifiable in the harness that would run it, and its negative
  control provably could not fire. INV-SEQ-1 is scoped to what is observable
  and the concurrency claim moves to `Residual gaps`.
- **D-3's rationale was wrong and is rebuilt.** The API requires *prefix
  stability*, not gaplessness; the true argument for row locking is that
  allocation order equals commit order. All five sequencing alternatives are
  now recorded with verdicts, `BIGSERIAL` as *incorrect* rather than inelegant,
  and the per-run counter column as the identified strict improvement, deferred.
- **D-2 reverses the mixin decision** in favour of composition, and now answers
  the question the previous draft never asked: whether a checkpoint table is
  needed at all.
- **D-7 renames the table** to `review_checkpoints`, because ADR-007 is titled
  "Durable generation checkpoints" and the previous name walked into the exact
  confusion Risk 1 predicts.
- **The Purpose section no longer overclaims.** Nothing creates a checkpoint in
  production today, so nothing is being lost; this is an enabling slice with
  zero consumers. Consequently the users' guide is deliberately left unchanged.
- **New risks and obligations** for the silent no-commit window, the reaper
  killing runs awaiting review, editing an applied revision, and the shared
  creation-precondition blind spot.
- **Test strategy trimmed and re-aimed**: plain scenario functions rather than
  an abstract base class; folded into the existing SQL suite and feature file
  rather than duplicating them; the syrupy snapshot and the `xfail` dance
  dropped; `max_examples` raised from 5–6 to 25 on measured cost.
- **Tolerances re-based on measurement** — 130.58 s / 1227 tests, 0.20–0.38 s
  per database test — and the scope tolerance raised to match the enumerated
  file count, which the previous figure would have breached by construction.

2026-08-23 (first revision) — Rewritten from a draft authored against a tree
that predated commit `5af0638` (roadmap 4.3.2), which asserted that no durable
generation-run persistence existed and targeted a migration head three
revisions stale.
