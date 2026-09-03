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
  domain ports", and "Manual recovery of expired generation-run leases".
- `docs/adr/adr-015-generation-run-port-split.md` — why the port is split, and
  why the user-facing `Checkpoint` differs from `WorkflowCheckpoint`.
- `docs/adr/adr-018-explicit-versioning-and-history-strategy.md` (arriving
  with pull request PR 278) — the governing record for versioning, concurrency
  shapes, immutability, and deletion policy. Read it before writing the
  adapter; it decides D-10 and the foreign-key policy.
- `docs/alpha-test-4-3-2-setup-notes.md` (arriving with pull request PR 277) —
  the end-to-end alpha run of the 4.3.2 slice, including where repository
  documentation was wrong.
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

## Pending pull requests this plan depends on

Two open pull requests touch this plan's surface. Both should land **before**
implementation starts; if either is abandoned, the noted items must be
revisited.

**PR 278 — "Record the versioning strategy and adopt episode TEI revision
history (2.8)"** (`versioning-adr-episode-tei-history`, documentation only).

- It takes **ADR-018 and ADR-019**, so this plan's new ADR is **ADR-020**.
- Its `docs/adr/adr-018-explicit-versioning-and-history-strategy.md` becomes
  the **governing record for versioning, concurrency shapes, immutability, and
  deletion policy**. It is now an upstream item in `Conformance basis`, and
  three decisions here changed to conform: D-10 (compare-and-set rather than
  row locking), the `ON DELETE RESTRICT` foreign key in Table 1, and D-11 (why
  a review checkpoint is not a versioned aggregate).
- It adds **roadmap step 2.8** (episode TEI revision history), so follow-ups
  from this plan must not claim that number.
- It edits `docs/contents.md`, `docs/roadmap.md`,
  `docs/episodic-podcast-generation-system-design.md`, and
  `docs/episodic-tui-api-design.md` — all four of which EP-M5 also edits.

**PR 277 — "Harden the no-QA generation slice from local alpha testing
(4.3.2)"** (`4-3-2-...-alpha-feedback`, code and documentation).

- It edits `episodic/canonical/storage/uow.py`,
  `episodic/canonical/generation_run_ports.py`,
  `tests/canonical_storage/test_generation_runs.py`, and
  `tests/canonical_storage/test_sql_generation_run_property_contract.py` —
  **the four files this plan changes most**. Expect conflicts; rebase first.
- It moves `uow.py`'s imports **out of** `if typ.TYPE_CHECKING:` with
  `# noqa: TC00x` markers, because `mock.create_autospec` evaluates method
  annotations at runtime. Any import this plan adds there must follow that
  convention or it reintroduces the `NameError` PR 277 fixes.
- It adds a `Raises / RunNotFound` section to `count_events` in
  `generation_run_ports.py` — the precedent Stage C step 7 generalizes, and
  evidence that the port file is where contracts are expected to live.
- It establishes that **persisted rows survive between Hypothesis examples**,
  and scopes an idempotency key per example with `uuid.uuid7()` accordingly.
  See the runtime entry in `Tolerances`.
- It changes `make skylos-allow` to take `SKYLOS_CLI` and
  `$(call cli_value,NAME)`, and pins the Skylos interpreter to Python 3.14.
- Its `make test` baseline is **1237 passed, 3 skipped**, against 1227 on
  `main`. Re-measure after rebasing rather than trusting either figure.

## Constraints

Hard invariants. Violating one requires escalation, not a workaround.

- **Do not change the 2.6.1 domain surface.** `episodic/canonical/domain.py`
  (the `GenerationRun`, `GenerationEvent`, `Checkpoint`, `CheckpointResponse`
  entities and the `GenerationRunStatus`, `CheckpointStatus`,
  `CheckpointAction` enums) is frozen for this slice.
- **Do not weaken the existing port protocols.** Methods may be *added* to
  `episodic/canonical/generation_run_ports.py` — roadmap 2.6.2 explicitly
  covers "define repository interfaces" — but no existing signature may change.
- **Hexagonal dependency rule.** New storage modules may import domain types,
  ports, and domain errors. Domain and ports must not import storage.
  `make check-architecture` (Hecate) enforces this and must pass.
- **No schema drift.** `make check-migrations` must report no difference
  between `Base.metadata` and the migration history.
- **Single migration head.** New revisions chain off the current head
  `20260624_000012` (`add_ingestion_job_owner`). Confirm with
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
  `episodic/canonical/storage/generation_runs.py` is 367 lines and
  `episodic/canonical/adapters/generation_runs.py` is 399, so neither can
  absorb new methods.
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
  `episodic/canonical/domain.py` or
  `episodic/canonical/generation_run_ports.py`.
- **Dependencies:** any new entry in `pyproject.toml` dependency groups. This
  slice needs none.
- **Migration graph:** if `uv run alembic heads` reports more than one head, or
  if any already-merged revision file would need editing.
- **Iterations:** if a single failing gate is not green after 4 fix attempts.
- **Runtime:** if per-test `migrated_engine` setup exceeds 0.5 s, or if total
  `make test` wall-clock exceeds 165 s. The measured baseline at commit
  `5af0638` is **130.58 s for 1227 passed, 3 skipped** with
  `PYTEST_XDIST_WORKERS=1`; PR 277 reports **1237 passed, 3 skipped**, so
  re-measure after rebasing, and per-test `migrated_engine` setup is
  **0.20–0.38 s** after the one-off session-scoped py-pglite start (~3.8 s).
  Note that Hypothesis examples do **not** re-run migrations — the fixture is
  function-scoped and shared across every example, which is precisely why
  `suppress_health_check=[HealthCheck.function_scoped_fixture]` is required.
  The corollary, established by pull request PR 277, is that **persisted rows
  survive between examples**: the session factory outlives them. Every
  database-backed property test must scope its own data per example —
  `make_generation_run()` already does so via UUIDv7, but any shared
  idempotency key, actor, or fixture row must be suffixed per example.
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
  ADR-018 so the next author does not invent it under pressure.

- **Risk 8: this plan is implemented before PR 277 and PR 278 land, and diverges
  from both.** Severity: medium. Likelihood: medium. Evidence: PR 277 edits the
  four files this plan changes most, and PR 278 takes ADR-018/019 and sets the
  concurrency and deletion policy this plan now conforms to. Implementing first
  means conflicts in `uow.py`, `generation_run_ports.py`, and two test modules,
  plus an ADR number clash. Mitigation: the `Pending pull requests` section
  states the dependency; Stage A confirms both have merged before any code is
  written; if either is abandoned, revisit D-10, D-11, the foreign-key policy,
  and the ADR number.

- **Risk 9: the shared contract suite certifies a shared blind spot as
  correct.** Severity: medium. Likelihood: medium. Evidence: neither adapter
  checks that `create_checkpoint` targets a non-terminal run, nor that a
  created checkpoint starts in `created`. Both share the hole, so
  "behaviourally interchangeable" would be proven true and still wrong.
  Mitigation: INV-CKPT-5 closes it in both adapters in one commit.

## Progress

- [ ] EP-M0 Stage A: orientation, production **and test** sweep (no changes).
- [ ] EP-M1: `review_checkpoints` table, ORM model, reversible migration.
- [ ] EP-M2: `SqlAlchemyReviewCheckpointStore`, composite port adapter,
      unit-of-work wiring, commit-safety warning.
- [ ] EP-M3: shared checkpoint contract scenarios across both adapters, plus
      durability and sequencing evidence.
- [ ] EP-M4: lease-reclamation primitive (gated; see Tolerances and Risk 3).
- [ ] EP-M5: documentation, ADR-018, and roadmap reconciliation.

Record a timestamp against each item as it completes, in the form
`- [x] (2026-08-23 14:05Z) EP-M1 ...`.

## Surprises & discoveries

- **Observation: roadmap 2.6.2 is materially pre-built.** Durable persistence
  for `GenerationRun` and `GenerationEvent`, the `20260624_000010` migration,
  and sequencing property tests all already exist. Evidence:
  `episodic/canonical/storage/generation_runs.py` (367 lines),
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

- **Observation: widening `CanonicalUnitOfWork.generation_runs` is lower risk
  than the previous draft rated it.** Exactly one class declares the attribute:
  `SqlAlchemyUnitOfWork`, an explicit protocol subclass, so `make typecheck`
  checks the assignment directly. Every other unit-of-work double in the tree
  is a structural stub reached through `typ.cast` and none declares
  `generation_runs`. The one additional implementer to update is
  `NoopGenerationRunPort` in
  `tests/test_generation_run_port_contract_support.py`.

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
  documented accurately in Risk 7 and the downgrade recipe goes in ADR-018.
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
  recorded follow-up. Document the mapping explicitly in ADR-018 so the
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
  add the forward implication as a CHECK, and record in ADR-018 that the
  converse is deliberately not enforced, with a follow-up to tighten the domain
  validator and add the reverse constraint together. Date/Author: 2026-08-23,
  planning agent.

- **D-10. Use compare-and-set for checkpoint transitions, not row locking.**
  Rationale: pull request PR 278's ADR-018 records the project's versioning and
  concurrency strategy and names two shapes, warning that "applying the wrong
  one produces either lost updates or spurious conflicts". For "concurrent
  writers racing on one mutable row" — which is exactly a checkpoint transition
  — the named house shape is **compare-and-set with a typed domain error**, not
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

- `episodic/canonical/domain.py` — frozen dataclasses for the domain entities.
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
- `episodic/canonical/adapters/generation_runs.py` (399 lines) —
  `InMemoryGenerationRunStore`, the reference adapter, which gains checkpoint
  behaviour from `InMemoryGenerationCheckpointMixin` in
  `episodic/canonical/adapters/generation_checkpoints.py`.
- `episodic/canonical/storage/models_base.py` — the SQLAlchemy `Base` and the
  shared native-enum declarations.
- `episodic/canonical/storage/generation_run_models.py` —
  `GenerationRunRecord` and `GenerationEventRecord`.
- `episodic/canonical/storage/generation_runs.py` (367 lines) —
  `SqlAlchemyGenerationRunStore`, implementing `GenerationRunRepository` and
  `GenerationEventLog` only.
- `episodic/canonical/storage/generation_run_mappers.py` — pure record/domain
  mapping functions. Adapters never build domain dataclasses inline.
- `episodic/canonical/storage/uow.py` — `SqlAlchemyUnitOfWork`, whose
  `__aenter__` instantiates every repository from one shared `AsyncSession`.
- `episodic/canonical/unit_of_work_protocols.py` — `CanonicalUnitOfWork`,
  currently declaring `generation_runs: GenerationRunEventStore`.
- `alembic/versions/` — migrations named `YYYYMMDD_NNNNNN_description.py`,
  chained linearly by `down_revision`. Current head: `20260624_000012`.
- `tests/` — top-level `test_*.py` are unit tests; `tests/canonical_storage/`
  holds PostgreSQL-backed integration tests; `tests/features/*.feature` with
  `tests/steps/test_*_steps.py` hold behavioural tests.
- `tests/fixtures/database.py` — the py-pglite fixture stack. The chain is
  `pglite_sqlalchemy_manager` (session-scoped) → `pglite_engine` →
  `migrated_engine` (drops and recreates the `public` schema, then applies the
  full Alembic chain, per test function) → `session_factory` and
  `pglite_session`.

**The specific gap.** `SqlAlchemyGenerationRunStore` has no checkpoint methods.
There is no checkpoint table.
`tests/test_generation_checkpoint_port_contract.py` runs against the in-memory
store only. `uow.generation_runs` is typed as the narrower
`GenerationRunEventStore`, and nothing in the repository implements the
composite `GenerationRunPort` except a no-op stub used for type-checking.

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

- `ROADMAP-2.6.2` — `docs/roadmap.md`, lines 319–321: "Implement repository
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
- `ADR-018` — `docs/adr/adr-018-explicit-versioning-and-history-strategy.md`,
  arriving with pull request PR 278: the governing record for versioning,
  concurrency shapes, immutability, and deletion policy. Three clauses bind
  this slice. "Applying the wrong [concurrency shape] produces either lost
  updates or spurious conflicts" — see D-10. "Deletion policy protects the
  audit trail", with `ON DELETE RESTRICT` for references to the immutable
  records that explain durable state — see the foreign key in Table 1. "New
  versioned aggregates must follow this pattern" — see D-11 for why a review
  checkpoint is not one.
- `EP-4.3.2-DEFER` — "Out of scope and left to later tasks: human-review
  checkpoint persistence (2.6.2) … and an automated stuck-run recovery worker
  (2.6.2)."

Trace links from upstream item, through milestone, to acceptance evidence:

```plaintext
ROADMAP-2.6.2    -> EP-M1 -> make check-migrations reports no drift
ROADMAP-2.6.2    -> EP-M3 -> tests/canonical_storage/test_generation_runs.py
API-GENRUN-SEQ   -> EP-M3 -> test_sql_generation_run_property_contract.py
DESIGN-ORCH-CKPT -> EP-M1 -> alembic/versions/20260823_000013_add_review_checkpoints.py
DESIGN-ORCH-CKPT -> EP-M2 -> episodic/canonical/storage/review_checkpoints.py
API-GENRUN-CKPT  -> EP-M2 -> uow.generation_runs satisfies GenerationRunPort
API-GENRUN-CKPT  -> EP-M3 -> tests/features/generation_run_lifecycle.feature
ADR-015          -> EP-M5 -> docs/adr/adr-020-review-checkpoint-persistence.md
ADR-018          -> EP-M2 -> compare-and-set transitions; ON DELETE RESTRICT
EP-4.3.2-DEFER   -> EP-M4 -> tests/canonical_storage/test_generation_run_lease_reclamation.py
```

When an artefact is renamed or folded into an existing module, update this
table in the same commit; a stale trace table is worse than none.

A new ADR is warranted. Pull request PR 278 introduces ADR-018 and ADR-019, so
the next free number is **020**. Separately, three files already share 015
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
  py-pglite, and a control that cannot fire is worse than none.

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
  `WHERE id = :id` and confirm every terminal case then fails.
- This obligation is *verifiable* precisely because D-10 chose compare-and-set:
  the `WHERE status = 'created'` clause is exercised by mutating stored state
  between calls, sequentially, which py-pglite supports. Had the adapter relied
  on `FOR UPDATE`, the losing-writer path would have been unobservable for the
  same reason INV-SEQ-1's concurrency claim is.

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
  fails loudly rather than yielding seven single-character options.
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
  independently before trusting it.

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

Expected: a single head, `20260624_000012 (head)`. More than one head means
stop and escalate.

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
   `alembic/versions/20260823_000013_add_review_checkpoints.py`, chained off
   `20260624_000012`. Follow `20260624_000010_add_generation_run_tables.py`
   exactly: module docstring, a private `_enum(name, *values)` helper returning
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
   Import discipline: pull request PR 277 moved `uow.py`'s imports **out of**
   `if typ.TYPE_CHECKING:` with `# noqa: TC00x` markers, because
   `mock.create_autospec` evaluates method annotations at runtime and deferred
   imports raise `NameError`. Any import added here must follow that
   convention, or the latent bug PR 277 fixed comes straight back.
9. **Commit safety.** In `SqlAlchemyUnitOfWork.__aexit__`, when `exc is None`
   and the session has pending state
   (`session.new or session.dirty or session.deleted`), emit a `warning` before
   closing. One branch; it converts the most likely durability bug in the next
   slice from invisible to greppable (Risk 4, INV-COMMIT-1).
10. **Skylos.** Pre-write the `[[tool.skylos.dead_code.entrypoints]]` entries;
    the gate scans `alembic episodic openai_test_types.py` and tests do not
    count as callers. Two certain hits: the migration's `_drop_enums` and
    `_drop_*_table` helpers (precedent: the `20260624_000010` entries already
    in `pyproject.toml`), and `SqlAlchemyReviewCheckpointStore`, which has no
    production caller until 2.6.3 (precedent: the `InMemoryGenerationRunStore`
    class entrypoint). Give each a reason naming the verified future caller;
    for the checkpoint store the honest reason is "no runtime caller until
    roadmap 2.6.3".

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
4. Add the revision `20260823_000014_add_expired_lease_index.py` for the
   partial index `ix_generation_runs_expired_lease` on `(lease_expires_at)` with
   `postgresql_where=sa.text("status = 'running'")`, mirrored exactly in the
   ORM `__table_args__`. **Its own revision** — never edit `000013`, which
   EP-M1 already applied (Risk 6). Follow
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
3. Add `docs/adr/adr-020-review-checkpoint-persistence.md` — **020**, because
   pull request PR 278 takes 018 and 019 — following the shape of
   `adr-015-generation-run-port-split.md` (Status, Context, Decision,
   Consequences with Positive/Negative/Neutral, References) rather than the
   style guide's literal template — every ADR from 010 to 017 does the same, so
   this is house practice, not a deviation. Cover **D-2 and D-3** as decisions;
   D-4, D-5, D-7, D-8, and D-9 belong in one Consequences paragraph each, since
   "use JSONB like everywhere else" is a convention application, not a
   decision. Include: the `ALTER TYPE` downgrade recipe from Risk 7; the
   `Checkpoint` / `review_checkpoints` naming asymmetry from D-7; the D-9
   half-constraint and why; that a returned entity is provisional until its
   unit of work commits; and that the aggregate's deletion policy is `RESTRICT`
   under ADR-018's audit-trail policy, and D-11's reasoning that a review
   checkpoint is not a versioned aggregate and so needs no history table. Add to
   `docs/contents.md` **after** ADR-019's entry, and reference from the design
   document. Rebase on PR 278 first: it edits `docs/contents.md`,
   `docs/roadmap.md`, the design document, and the TUI API document, all of
   which this milestone also edits.
4. Correct `docs/episodic-tui-api-design.md`: it states event logs are
   "partitioned by `generation_run_id` for efficient range queries". They are
   not, and should not be — `generation_run_id` is a UUID, so that means hash
   partitioning, which buys nothing when every query is already
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
  D-11 records why no history table is required.
- Recovery: **code may be reverted freely; the migration may not.** Reverting
  this commit leaves the table in place, unused and harmless, and rows written
  before the revert survive and are picked up on re-apply. Downgrading
  `20260823_000013` after any checkpoint has been written **destroys reviewer
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
  `000014`. EP-M3 remains a valid plateau.
- Remaining gaps: nothing schedules the reclamation, and nothing detects a
  stuck run. Both stated explicitly in the developers' guide.

### EP-M5 — documentation and reconciliation

- Outcome: developers' guide, ADR-018, `docs/contents.md`, the design-document
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
20260624_000012 (head)
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
  claim: `alembic downgrade` past `20260823_000013` drops `review_checkpoints`
  and every reviewer decision in it. Before EP-M2 this is harmless because the
  table is empty; after it, take a dump first. Nothing else in this plan
  touches production data or an external service.

## Artefacts and notes

Record here as work proceeds:

- the red transcript from Stage B step 3;
- the negative-control transcript for INV-SEQ-1 (cross-run predicate removed);
- the two `pg_type` transcripts for INV-MIG-2, one per enum;
- the `make test` baseline and final wall-clock. The baseline at commit
  `5af0638` is **130.58 s, 1227 passed, 3 skipped**, with per-test
  `migrated_engine` setup of 0.20–0.38 s after a ~3.8 s session-scoped start.

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
