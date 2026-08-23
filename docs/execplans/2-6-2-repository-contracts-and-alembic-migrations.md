# Implement generation-run repository contracts and Alembic migrations (2.6.2)

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & discoveries`, `Decision log`,
`Outcomes & retrospective`, `Conformance basis`, and `Verification plan` must
be kept up to date as work proceeds.

Status: DRAFT

## Purpose / big picture

A *generation run* is the record of one attempt to turn an ingested source
bundle into a podcast script. It owns an append-only *event log* (a numbered
stream of things that happened during the run) and a set of *checkpoints*
(pauses where a human reviewer is asked to approve, request changes, or edit
before the run continues).

Roadmap item 2.6.1 defined the domain entities and the port protocols for all
three concepts. Roadmap item 4.3.2 then landed durable PostgreSQL persistence
for *runs and events only*, as a deliberately narrow vertical slice. Reviewer
checkpoints are still held in `InMemoryGenerationRunStore`, a process-local
dictionary: **today, if the API process restarts, every pending reviewer
checkpoint is silently lost.** No table exists for them, and no adapter in the
tree implements the composite `GenerationRunPort`.

This slice closes that gap. After this change a developer can do the following
and watch it work:

1. Run `make check-migrations` and see no schema drift, with the new
   `generation_checkpoints` table present in both the SQLAlchemy models and the
   migration history.
2. Open a `SqlAlchemyUnitOfWork`, create a run, append events, create a
   checkpoint, respond to it, and `commit()`. Then open a *fresh* unit of work
   in a *fresh process* and read the same run, its ordered event log, and its
   responded checkpoint back out of PostgreSQL.
3. Run `make test` and see one shared port-contract suite pass against **both**
   the in-memory adapter and the PostgreSQL adapter, proving the two are
   behaviourally interchangeable.
4. See a Hypothesis property test prove, against a real PostgreSQL engine, that
   concurrently appended events receive contiguous, strictly increasing
   sequence numbers starting at 1, and that `list_events(after_seq=...)` pages
   them in ascending order under the documented half-open contract.

This unblocks 2.6.3 (REST endpoints for generation runs), whose
`POST /v1/generation-runs/{run_id}/checkpoint` endpoint cannot be built on an
in-memory store.

## Signposts: documentation and skills

Read these before and during implementation. They are the source of truth for
the conventions this plan must follow. Paths are repository-relative.

Skills to load at session start:

- `leta` — semantic code navigation. Use `leta show <symbol>` instead of
  reading files, `leta refs <symbol>` instead of grepping for usages, and
  `leta implementations <protocol>` to find adapters. Add the workspace once
  with `leta workspace add .`.
- `hexagonal-architecture` — architectural scope. The rule that matters here:
  domain and ports must not import adapters. Everything added by this plan under
  `episodic/canonical/storage/` is an *outbound (driven) adapter*.
- `python-router`, then `python-testing` and `python-types-and-apis` as needed.
- `hypothesis` — for the event-ordering property tests in Milestone EP-M3.
- `execplans` — the rules this document itself follows.
- `vidai-mock` — **not used by this slice.** This plan touches persistence
  only; no inference call is made or mocked. It is named here because the
  phase-wide instruction references it, and to record explicitly that it was
  considered and found inapplicable.

Repository documentation:

- `AGENTS.md` — normative rules on code style, the 400-line file limit,
  NumPy-style docstrings, en-GB-oxendict spelling, quality gates, and the
  abstraction/port/helper sweep policy.
- `docs/episodic-podcast-generation-system-design.md`, section
  "Content Generation Orchestrator" — the requirement that the orchestrator
  "provides checkpointing for resumable workflows, enabling long-running
  editorial review periods without state loss". That requirement is what this
  slice actually discharges.
- `docs/episodic-tui-api-design.md`, section "Generation runs" — the
  authoritative shape of `GenerationRun`, `GenerationEvent`, and `Checkpoint`,
  the `after_seq` replay contract, and the pagination envelope
  (`1 <= limit <= 100`, `offset >= 0`).
- `docs/async-sqlalchemy-with-pg-and-falcon.md` — session and engine
  conventions: `expire_on_commit=False`, `autoflush=False`, explicit `flush()`,
  and `IntegrityError` translation. Note that its testing section
  (savepoint-based rollback) is **superseded** in this repository by the
  py-pglite fixtures below; defer to the project-specific document.
- `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` — the fixture stack.
  Use `session_factory` for repository, service, and unit-of-work tests;
  `pglite_session` only for direct ORM assertions.
- `docs/testing-async-falcon-endpoints.md` — relevant only if a later revision
  extends this slice to API-level assertions. It is not exercised here.
- `docs/agentic-systems-with-langgraph-and-celery.md` — background reading on
  orchestration. **Caution:** its "Persistence and Checkpointing" section
  recommends a Redis-backed LangGraph checkpointer. That is *not* what this
  repository does; durable orchestration checkpoints are PostgreSQL-backed per
  ADR-007. Do not let that document steer this slice towards Redis.
- `docs/developers-guide.md`, sections "Database migrations", "Database
  testing with py-pglite", "Canonical content persistence", "Generation-run
  domain ports", and "Manual recovery of expired generation-run leases".
- `docs/adr/adr-015-generation-run-port-split.md` — why the port is split into
  `GenerationRunRepository`, `GenerationEventLog`, and
  `GenerationCheckpointPort`, and why the user-facing `Checkpoint` is a
  different concept from the orchestration `WorkflowCheckpoint`.
- `docs/adr/adr-007-durable-generation-checkpoints.md` — the *orchestration*
  checkpoint. Read it to avoid conflating the two.
- `docs/documentation-style-guide.md` — 80-column prose wrap, 120-column code
  wrap, en-GB-oxendict spelling, Oxford comma, sentence-case headings, ADR
  naming and template.
- `docs/execplans/4-3-2-no-qa-generation-runs-and-tei-p5-retrieval.md` — the
  plan that landed the run/event half of this roadmap item and explicitly
  deferred checkpoints and lease recovery here.
- `docs/execplans/2-6-1-generation-run-port-and-domain-model.md` — the
  predecessor that defined the ports this slice implements.

## Constraints

Hard invariants. Violating one requires escalation, not a workaround.

- **Do not change the 2.6.1 domain surface.** `episodic/canonical/domain.py`
  (the `GenerationRun`, `GenerationEvent`, `Checkpoint`, `CheckpointResponse`
  entities and the `GenerationRunStatus`, `CheckpointStatus`,
  `CheckpointAction` enums) is frozen for this slice. The new adapter conforms
  to those types; it does not reshape them.
- **Do not weaken the existing port protocols.** Methods may be *added* to
  `episodic/canonical/generation_run_ports.py` (roadmap 2.6.2 explicitly covers
  "define repository interfaces"), but no existing signature may change and no
  existing method may be removed.
- **Hexagonal dependency rule.** New modules under
  `episodic/canonical/storage/` may import domain types, port protocols, and
  domain errors. Domain and port modules must not import storage.
  `make check-architecture` (Hecate) enforces this and must pass.
- **No schema drift.** `make check-migrations` must report no difference
  between `Base.metadata` and the migration history. Every table, column,
  constraint, index, and enum must exist identically in both.
- **Single migration head.** The new revision must chain off the current head
  `20260624_000012` (`add_ingestion_job_owner`). Confirm the head with
  `uv run alembic heads` before writing the file — the `down_revision` chain,
  not the filename date, is authoritative, and existing filenames are *not* in
  strict date order.
- **Name collision avoidance.** The user-facing checkpoint table and its enums
  must not collide with the orchestration `workflow_checkpoints` table or the
  `workflow_checkpoint_status` enum. Use `generation_checkpoints`,
  `generation_checkpoint_status`, and `generation_checkpoint_action`.
- **Storage conventions.** Timestamps are `sa.DateTime(timezone=True)`. UUID
  primary keys are `postgresql.UUID(as_uuid=True)`, client-assigned UUIDv7 via
  `uuid.uuid7()`; do not add server-side UUID defaults. Structured payloads use
  `postgresql.JSONB`. Python enums map to native PostgreSQL enums declared once
  in `episodic/canonical/storage/models_base.py` with
  `values_callable=lambda enum_cls: [item.value for item in enum_cls]`.
- **File size.** No code file exceeds 400 lines (`AGENTS.md`).
  `episodic/canonical/storage/generation_runs.py` is already 367 lines, so
  checkpoint persistence must live in a new module, not be appended to it.
- **Repositories do not own the transaction.** Adapters `flush()`; only
  `SqlAlchemyUnitOfWork.commit()` commits. Do not add `commit()` calls inside
  an adapter.
- **No compatibility shims.** These are private, pre-1.0, application-internal
  interfaces with no external consumers. When a port widens, update the
  protocol, both adapters, and every caller in one commit. Do not add aliases,
  facades, or deprecated entrypoints.

## Tolerances (exception triggers)

Stop and escalate rather than improvising when any of these is reached.

- **Scope:** more than 18 files changed, or more than 1400 net added lines
  across production code and tests.
- **Interface:** any change to an *existing* signature in
  `episodic/canonical/domain.py` or
  `episodic/canonical/generation_run_ports.py`.
- **Dependencies:** any new entry in `pyproject.toml` dependency groups. This
  slice needs none.
- **Migration graph:** if `uv run alembic heads` reports more than one head at
  any point.
- **Iterations:** if a single failing gate is not green after 4 fix attempts.
- **Runtime:** if `make test` wall-clock time grows by more than 25%. The
  py-pglite fixtures re-apply every migration per test function, so each added
  database test has a real cost, and `pytest-timeout` is set to 180 seconds.
- **Ambiguity:** if Milestone EP-M4 (lease reclamation) turns out to require a
  scheduler, worker, or Celery beat entry, stop — that is orchestration work,
  not a repository contract, and belongs to a separate roadmap item.

## Risks

- **Risk:** Reviewers conflate the user-facing `Checkpoint` with the
  orchestration `WorkflowCheckpoint`, producing a duplicate or wrongly-named
  table. Severity: high. Likelihood: medium. Mitigation: distinct table and
  enum names are a hard constraint above; ADR-015 and ADR-007 are signposted;
  Milestone EP-M1 adds an explicit assertion that both tables coexist after
  migration.

- **Risk:** The gap-free per-run sequence invariant breaks under genuine
  concurrent writers, because `MAX(seq) + 1` is not atomic on its own.
  Severity: high. Likelihood: medium. Mitigation: keep the existing pessimistic
  pattern — lock the run row with `SELECT ... FOR UPDATE` *before* computing
  the next sequence — and retain `UNIQUE (generation_run_id, seq)` as defence
  in depth. Milestone EP-M3 proves the invariant with a Hypothesis property
  test that interleaves appends, and includes a seeded-fault negative control.

- **Risk:** Adding database-backed contract tests inflates suite runtime past
  the 180-second `pytest-timeout`, because `migrated_engine` re-applies the
  whole migration chain per test function. Severity: medium. Likelihood:
  medium. Mitigation: keep `max_examples` at 5–6 for database-backed Hypothesis
  tests (the existing convention), set `deadline=None`, and use
  `suppress_health_check=[HealthCheck.function_scoped_fixture]`. Measure suite
  runtime before and after; the tolerance above is the trigger.

- **Risk:** Widening `CanonicalUnitOfWork.generation_runs` from
  `GenerationRunEventStore` to `GenerationRunPort` breaks an unrelated caller
  or a test double that only implements the narrower protocol. Severity:
  medium. Likelihood: medium. Mitigation: before editing, run
  `leta refs CanonicalUnitOfWork` and
  `leta implementations GenerationRunEventStore` to enumerate every implementer;
  `make typecheck` will catch the rest. Widening a *supplied* attribute is
  safe for consumers and only obliges implementers, of which there are few.

- **Risk:** The migration is written but never exercised in the reverse
  direction, so `downgrade()` is broken when someone needs it. Severity:
  medium. Likelihood: high (this is the usual failure mode). Mitigation: EP-M1
  acceptance requires an explicit upgrade → downgrade → upgrade cycle, asserted
  by a test, not just by eye.

- **Risk:** Native PostgreSQL enums are painful to alter later; adding a
  checkpoint-status value in a future slice requires `ALTER TYPE`. Severity:
  low. Likelihood: medium. Mitigation: accepted deliberately for consistency
  with every other enum in this schema. Recorded in `Decision log`.

- **Risk:** py-pglite's PostgreSQL is not perfectly faithful to a production
  server for `FOR UPDATE` semantics or enum handling. Severity: medium.
  Likelihood: low. Mitigation: py-pglite runs a genuine PostgreSQL build; it is
  already the basis of the existing claim-race tests in
  `tests/canonical_storage/test_generation_run_claims.py`, which exercise the
  same locking primitives. Recorded as an axiom in `Verification plan`.

## Progress

- [ ] EP-M0 Stage A: orientation and repository sweep (no code changes).
- [ ] EP-M1: `generation_checkpoints` table, ORM model, and reversible
      Alembic migration.
- [ ] EP-M2: `SqlAlchemyGenerationCheckpointMixin`, composite
      `GenerationRunPort` implementation, and unit-of-work wiring.
- [ ] EP-M3: shared port-contract suite across both adapters, plus
      event-ordering and checkpoint-durability integration and property tests.
- [ ] EP-M4: lease-reclamation repository primitive (gated; see Tolerances).
- [ ] EP-M5: documentation, ADR, and roadmap reconciliation.

Record a timestamp against each item as it completes, in the form
`- [x] (2026-08-23 14:05Z) EP-M1 ...`.

## Surprises & discoveries

- Observation: roadmap 2.6.2 is materially pre-built. Durable persistence for
  `GenerationRun` and `GenerationEvent`, the `20260624_000010` migration, and
  Hypothesis event-ordering property tests all already exist. Evidence:
  `episodic/canonical/storage/generation_runs.py` (367 lines),
  `episodic/canonical/storage/generation_run_models.py`,
  `alembic/versions/20260624_000010_add_generation_run_tables.py`,
  `tests/canonical_storage/test_sql_generation_run_property_contract.py`. All
  landed in commit `5af0638` under
  `docs/execplans/4-3-2-no-qa-generation-runs-and-tei-p5-retrieval.md`, whose
  scope statement says it implements "the subset of durable generation-run
  persistence and REST endpoints that the no-QA slice needs" and leaves
  "human-review checkpoint persistence (2.6.2)" and "an automated stuck-run
  recovery worker (2.6.2)" out of scope. Impact: this plan is scoped to the
  *remaining* gap, not to redelivering what exists. See `Decision log` entry
  D-1.

- Observation: the port protocols named by the roadmap bullet ("define
  repository interfaces for generation-run aggregates") are already fully
  defined and were delivered by 2.6.1. Evidence:
  `episodic/canonical/generation_run_ports.py` declares
  `GenerationRunRepository`, `GenerationEventLog`, `GenerationRunEventStore`,
  `GenerationCheckpointPort`, and the composite `GenerationRunPort`, all
  `@typ.runtime_checkable`. Impact: the interface half of the bullet is
  discharged by *implementing* the composite port against SQL and by proving
  contract equivalence across adapters, not by declaring new protocols. One
  method is added in EP-M4.

- Observation: the contract-test file already anticipates a second adapter.
  Evidence: the module docstring of
  `tests/test_generation_run_port_contract.py` reads "Use the `store` fixture
  plus `make_generation_run()` and `make_checkpoint()` when adding scenarios
  for another implementation." Impact: EP-M3 extracts those scenarios into a
  shared, adapter-agnostic base rather than duplicating them.

Append further observations here as work proceeds.

## Decision log

- **D-1. Scope this slice to the genuine remaining gap.**
  Rationale: run and event persistence, the migration, and event-ordering
  property tests already exist (see `Surprises & discoveries`). Redelivering
  them would be waste and would churn a working, tested adapter. The gap is
  checkpoint persistence, composite-port implementation, cross-adapter contract
  equivalence, and the lease-recovery primitive that 4.3.2 deferred here by
  name. Date/Author: 2026-08-23, planning agent.

- **D-2. Mirror the in-memory adapter's shape: a checkpoint mixin, not a
  separate store.** Rationale: `InMemoryGenerationRunStore` gains checkpoint
  behaviour by mixing in `InMemoryGenerationCheckpointMixin`. Mirroring that on
  the SQL side keeps the two adapters structurally symmetric, lets one contract
  suite drive both, and yields a single object satisfying the composite
  `GenerationRunPort` — so `uow.generation_runs` stays one attribute. A separate
  `uow.generation_checkpoints` attribute was considered and rejected: it would
  make the two adapters asymmetric and leave the composite port with no
  production implementation. Alternative rejected: appending the methods to
  `episodic/canonical/storage/generation_runs.py`, which is already 367 lines
  and would breach the 400-line limit. Date/Author: 2026-08-23, planning agent.

- **D-3. Keep pessimistic row locking for sequence allocation; do not switch
  to a PostgreSQL sequence or to optimistic retry.** Rationale: the API
  contract in `docs/episodic-tui-api-design.md` lets clients replay from
  `after_seq`, which requires a *gapless* per-run stream. Prior art is
  consistent on this point: PostgreSQL `BIGSERIAL`/identity sequences are
  monotonic but **not** gapless, because a number consumed by a rolled-back
  transaction is lost. Gapless per-stream numbering therefore requires either
  serializing writers or an optimistic append that retries on unique-constraint
  violation. The existing adapter already serializes by taking
  `SELECT ... FOR UPDATE` on the run row before computing `MAX(seq) + 1`, which
  is correct and is already covered by the claim-race tests. Retaining it
  avoids rewriting a working, tested path. `UNIQUE (generation_run_id, seq)`
  stays as defence in depth so a bug cannot silently corrupt a stream.
  Date/Author: 2026-08-23, planning agent.

- **D-4. Store `Checkpoint.options` as `JSONB`, not `ARRAY(TEXT)`.**
  Rationale: `postgresql.ARRAY` is used nowhere in this repository, whereas
  `JSONB` is the established convention for every structured column. JSONB
  preserves array order, which is the only property `options` needs — it is a
  presentation-ordered list of reviewer choices, never queried element-wise.
  Consistency wins over marginal type precision. Date/Author: 2026-08-23,
  planning agent.

- **D-5. Native PostgreSQL enums for checkpoint status and action.**
  Rationale: every other enum in this schema is a native PostgreSQL enum
  declared in `models_base.py`. A `VARCHAR + CHECK` column would be easier to
  extend but would be the only one of its kind. The cost is that adding a
  status value later needs `ALTER TYPE ... ADD VALUE` in a migration; that is
  accepted and recorded under `Risks`. Date/Author: 2026-08-23, planning agent.

- **D-6. Include the lease-reclamation *repository primitive*; exclude the
  reaper *worker*.** Rationale: 4.3.2 deferred "an automated stuck-run recovery
  worker" to 2.6.2 by name, and `docs/developers-guide.md` currently documents
  a manual SQL procedure as the stand-in. The persistence half of that — one
  atomic query that fails runs whose lease has expired, appending the
  corresponding `run.failed` event in the same transaction — is a repository
  contract and belongs here. The scheduling half (who calls it, how often,
  under what Celery beat entry) is orchestration and belongs to a later roadmap
  item. EP-M4 is gated on this boundary holding; see `Tolerances`. Date/Author:
  2026-08-23, planning agent.

Append further decisions here, including any decision to escalate.

## Outcomes & retrospective

To be completed at each milestone boundary and at completion. Before setting
this plan to `COMPLETE`, reconcile every implementation discovery against the
artefacts named in `Conformance basis`, and confirm that `docs/roadmap.md` item
2.6.2 has been ticked by the implementor.

## Context and orientation

Assume no prior knowledge of this repository.

**What the project is.** Episodic generates podcast scripts from ingested
source material. It is a Python 3.14 application using Falcon for HTTP,
SQLAlchemy 2.x with `asyncio` over PostgreSQL for persistence, Alembic for
migrations, and `uv` for dependency and task management. It follows hexagonal
architecture: a pure domain, port protocols the domain declares, and adapters
that implement them.

**Where things live.**

- `episodic/canonical/domain.py` — frozen dataclasses for the domain
  entities, including `GenerationRun`, `GenerationEvent`, `Checkpoint`,
  `CheckpointResponse`, and their enums. `Checkpoint` carries the domain
  transitions `respond()`, `time_out()`, and `cancel()`; each calls
  `_raise_if_terminal()` and returns a *new* frozen instance via
  `dataclasses.replace`. All three raise `CheckpointAlreadyTerminal` if the
  checkpoint has already left the `created` state.
- `episodic/canonical/generation_run_ports.py` — the port protocols.
  `GenerationCheckpointPort` declares `create_checkpoint`, `get_checkpoint`,
  `respond_to_checkpoint`, `time_out_checkpoint`, and `cancel_checkpoint`.
  `GenerationRunPort` is the composite of all three sub-protocols.
- `episodic/canonical/generation_run_errors.py` — `GenerationRunError` and its
  subclasses `RunNotFound`, `RunAlreadyTerminal`, `StaleEventSequence`,
  `CheckpointNotFound`, `CheckpointAlreadyTerminal`.
- `episodic/canonical/adapters/generation_runs.py` —
  `InMemoryGenerationRunStore`, the reference adapter. It implements the full
  composite port by mixing in `InMemoryGenerationCheckpointMixin` from
  `episodic/canonical/adapters/generation_checkpoints.py`.
- `episodic/canonical/storage/models_base.py` — the SQLAlchemy
  `Base(orm.DeclarativeBase)` and the shared native-enum declarations
  (`GENERATION_RUN_STATUS`, `QUALITY_MODE`, `QA_STATUS`, and others).
- `episodic/canonical/storage/generation_run_models.py` —
  `GenerationRunRecord` and `GenerationEventRecord`.
- `episodic/canonical/storage/generation_runs.py` —
  `SqlAlchemyGenerationRunStore`. Implements `GenerationRunRepository` and
  `GenerationEventLog` only. Takes an `AsyncSession` plus an optional
  `GenerationRunStorageRuntime` (an injectable clock and UUID factory).
- `episodic/canonical/storage/generation_run_mappers.py` — pure functions
  mapping records to and from domain entities. Adapters never build domain
  dataclasses inline; they call these.
- `episodic/canonical/storage/uow.py` — `SqlAlchemyUnitOfWork`. Its
  `__aenter__` instantiates every repository from one shared `AsyncSession`.
- `episodic/canonical/unit_of_work_protocols.py` — `CanonicalUnitOfWork`, the
  protocol the unit of work satisfies. It currently declares
  `generation_runs: GenerationRunEventStore`.
- `alembic/versions/` — migrations, named `YYYYMMDD_NNNNNN_description.py`,
  chained linearly by `down_revision`. Current head: `20260624_000012`.
- `tests/` — top-level `test_*.py` are unit tests;
  `tests/canonical_storage/` holds PostgreSQL-backed integration tests;
  `tests/features/*.feature` with `tests/steps/test_*_steps.py` hold
  behavioural (pytest-bdd) tests.
- `tests/fixtures/database.py` — the py-pglite fixture stack, registered
  globally via `pytest_plugins` in `tests/conftest.py`. The chain is
  `pglite_sqlalchemy_manager` (session-scoped) → `pglite_engine` →
  `migrated_engine` (drops and recreates the `public` schema, then applies the
  full Alembic chain, **per test function**) → `session_factory` and
  `pglite_session`.

**The specific gap.** `SqlAlchemyGenerationRunStore` has no `create_checkpoint`,
`get_checkpoint`, `respond_to_checkpoint`, `time_out_checkpoint`, or
`cancel_checkpoint`. There is no `generation_checkpoints` table.
`tests/test_generation_checkpoint_port_contract.py` therefore runs against the
in-memory store only. `uow.generation_runs` is typed as the narrower
`GenerationRunEventStore`, and no object in the repository implements the
composite `GenerationRunPort` other than a throwaway no-op stub used for
type-checking.

**Terms used in this plan.**

- *Port* — a Protocol the domain declares and adapters implement.
- *Adapter* — an implementation of a port that touches the outside world.
- *Aggregate* — an entity cluster with one transactional boundary. Here the
  aggregate root is `GenerationRun`; events and checkpoints belong to it.
- *Gapless sequence* — a per-run event numbering with no missing values:
  after N successful appends the set of sequence numbers is exactly
  `{1, ..., N}`.
- *Half-open paging* — `list_events(after_seq=s)` returns events with
  `seq > s`, excluding `s` itself.
- *Lease* — `generation_runs.lease_expires_at`, the deadline by which the
  worker that claimed a run must finish it.
- *Drift* — a difference between the ORM metadata and the migration history,
  detected by `make check-migrations`.

## Conformance basis

There is no formal Terms of Reference artefact in this repository; the roadmap
and design documents serve that role. Upstream items traced by this plan:

- `ROADMAP-2.6.2` — `docs/roadmap.md`, lines 319–321: "Implement repository
  contracts and Alembic migrations. Define repository interfaces for
  generation-run aggregates. Add integration tests validating event ordering."
- `DESIGN-ORCH-CKPT` — `docs/episodic-podcast-generation-system-design.md`,
  section "Content Generation Orchestrator": "Provides checkpointing for
  resumable workflows, enabling long-running editorial review periods without
  state loss."
- `API-GENRUN-CKPT` — `docs/episodic-tui-api-design.md`, section "Generation
  runs": the `Checkpoint` data shape and
  `POST /v1/generation-runs/{run_id}/checkpoint`.
- `API-GENRUN-SEQ` — same document: "Each event carries a monotonically
  increasing `seq` number for ordering and replay", together with the
  `resume_from` replay semantics that require gaplessness.
- `ADR-015` — `docs/adr/adr-015-generation-run-port-split.md`: the port split
  and the `Checkpoint` / `WorkflowCheckpoint` separation.
- `EP-4.3.2-DEFER` —
  `docs/execplans/4-3-2-no-qa-generation-runs-and-tei-p5-retrieval.md`: "Out of
  scope and left to later tasks: human-review checkpoint persistence (2.6.2) …
  and an automated stuck-run recovery worker (2.6.2)."

Trace links from upstream item, through milestone, to acceptance evidence:

```plaintext
ROADMAP-2.6.2  -> EP-M1 -> make check-migrations reports no drift
ROADMAP-2.6.2  -> EP-M3 -> tests/canonical_storage/test_sql_generation_run_contract.py
API-GENRUN-SEQ -> EP-M3 -> tests/canonical_storage/test_sql_generation_run_property_contract.py::test_sql_event_sequences_are_gap_free
DESIGN-ORCH-CKPT -> EP-M1 -> alembic/versions/20260823_000013_add_generation_checkpoints.py
DESIGN-ORCH-CKPT -> EP-M2 -> episodic/canonical/storage/generation_checkpoints.py
API-GENRUN-CKPT  -> EP-M2 -> uow.generation_runs satisfies GenerationRunPort
API-GENRUN-CKPT  -> EP-M3 -> tests/features/durable_generation_checkpoints.feature
ADR-015          -> EP-M5 -> docs/adr/adr-018-generation-checkpoint-persistence.md
EP-4.3.2-DEFER   -> EP-M4 -> tests/canonical_storage/test_generation_run_lease_reclamation.py
```

A new ADR is warranted for the checkpoint-persistence decision. The highest
existing ADR number is 017, so the new one is **018**. Note in passing that
three files already share the number 015
(`adr-015-cost-accounting-ports-and-pricing-engine.md`,
`adr-015-upload-and-idempotency-ports.md`,
`adr-015-generation-run-port-split.md`). Renumbering them is **out of scope**
for this slice; record it as a follow-up rather than fixing it here.

## Verification plan

Verification is co-designed with the implementation. Each obligation below
names the method, the artefact, the evidence, and the non-vacuity check that
must fail if the implementation is wrong.

### Axioms (assumed, not verified)

- **AXIOM-1.** PostgreSQL `SELECT ... FOR UPDATE` under `READ COMMITTED` blocks
  a
  second transaction attempting to lock the same row until the first commits or
  rolls back. This is the basis of gapless sequence allocation. Not verified
  here; it is documented PostgreSQL behaviour.
- **AXIOM-2.** Alembic's `alembic.autogenerate.compare_metadata` detects
  differences in tables, columns, types, constraints, and enums between a live
  schema and `Base.metadata`. Exercised, not proven, by
  `tests/features/schema_migrations.feature`.
- **AXIOM-3.** py-pglite runs a genuine PostgreSQL build whose transactional,
  locking, and native-enum semantics match the deployment target. Partially
  evidenced by the existing claim-race tests, which already depend on
  `FOR UPDATE` behaving correctly under py-pglite.
- **AXIOM-4.** `uuid.uuid7()` from the Python 3.14 standard library returns
  unique, time-ordered identifiers.
- **AXIOM-5.** SQLAlchemy's `postgresql.JSONB` round-trips any JSON-compatible
  mapping or list without reordering array elements.

Do not attempt to verify the internals of SQLAlchemy, Alembic, or PostgreSQL.
Do verify this repository's *use* of them, which is what every obligation below
does.

### INV-SEQ-1 — per-run event sequences are gapless and start at 1

- Obligation: for any run `r`, after `N` successful `append_event` calls the
  persisted sequence numbers for `r` are exactly `{1, ..., N}`, each appearing
  once.
- Method: Hypothesis property test against a real PostgreSQL engine, with
  interleaved concurrent appends driven by `asyncio.gather`.
- Rationale: the property quantifies over event counts, kinds, and
  interleavings. Examples cannot cover the orderings that matter; a property
  test can. A formal proof is disproportionate, and the interesting failure
  mode is an interaction with PostgreSQL locking that only a real engine
  exhibits.
- Domain: 1–8 events per run, arbitrary event kinds drawn from a bounded
  alphabet, both sequential and `gather`-interleaved append schedules.
- Artefact:
  `tests/canonical_storage/test_sql_generation_run_property_contract.py`
  (extend the existing module).
- Evidence: run the property module and expect it to pass with
  `max_examples=6`, `deadline=None`, and
  `suppress_health_check=[HealthCheck.function_scoped_fixture]`:

```bash
uv run pytest \
  tests/canonical_storage/test_sql_generation_run_property_contract.py -v
```

- Non-vacuity: the generator must actually produce multi-event runs — assert
  `len(events) >= 2` for at least one example and use `hypothesis.event()` to
  classify runs by event count, then inspect the classification summary.
  Negative control: temporarily remove the `lock=True` argument from
  `_require_mutable_run` in `episodic/canonical/storage/generation_runs.py` and
  confirm the interleaved case fails with a duplicate or missing sequence
  number. Restore it and record the observed failure in `Artefacts and notes`.
  If the fault does not reproduce, the test is not exercising concurrency and
  must be strengthened before it is trusted.

### INV-SEQ-2 — half-open paging returns an ascending contiguous window

- Obligation: `list_events(run_id, after_seq=s, limit=k)` returns events with
  `seq > s`, in ascending `seq` order, at most `k` of them, and forming a
  contiguous prefix of the remaining stream. Supplying both `after_seq` and a
  non-zero `offset` raises `ValueError`.
- Method: Hypothesis property test plus parameterized boundary tests.
- Rationale: the ordering and contiguity claims range over `(s, k)` pairs, so
  a property test fits; the mutual-exclusion rule is a finite partition best
  pinned by explicit parameterized cases, including `s = 0`, `s = N`, and
  `s > N`.
- Domain: `s` in `[0, N + 1]`, `k` in `[1, 100]` per the documented pagination
  envelope.
- Artefact:
  `tests/canonical_storage/test_sql_generation_run_property_contract.py`.
- Evidence: as above.
- Non-vacuity: classify examples by whether the window is truncated by `limit`
  and confirm both truncated and untruncated cases occur; a run of examples
  that never truncates would leave `limit` untested. Negative control: change
  `>` to `>=` in `_minimum_event_sequence` and confirm the half-open assertion
  fails.

### INV-SEQ-3 — cross-run isolation

- Obligation: appending to run A never alters run B's sequence numbering, and
  `list_events(B)` never returns A's events.
- Method: property test with two runs appended to in an interleaved schedule.
- Rationale: cheap to state, and the plausible failure (a `MAX(seq)` query
  missing its `WHERE generation_run_id = ...` predicate) is exactly the kind of
  bug a shared-table event log invites.
- Artefact:
  `tests/canonical_storage/test_sql_generation_run_property_contract.py` (an
  isolation case already exists; extend it to cover checkpoint reads too).
- Non-vacuity: assert both runs receive at least one event in every example.
  Negative control: drop the run-id predicate from the `MAX(seq)` subquery and
  confirm failure.

### INV-CKPT-1 — SQL checkpoint transitions match the domain transitions

- Obligation: `respond_to_checkpoint`, `time_out_checkpoint`, and
  `cancel_checkpoint` persist exactly the entity returned by the corresponding
  domain method (`Checkpoint.respond`, `.time_out`, `.cancel`). The adapter
  must not reimplement the transition rules.
- Method: shared port-contract suite executed against both adapters, plus a
  parameterized test asserting the persisted row equals
  `domain_checkpoint.respond(response)` field for field.
- Rationale: the risk is drift between two implementations of the same rules.
  Running one suite against both adapters is the direct check.
- Artefact: `tests/generation_run_contract_scenarios.py` (shared, not
  collected), driven by `tests/test_generation_run_port_contract.py`
  (in-memory) and `tests/canonical_storage/test_sql_generation_run_contract.py`
  (SQL).
- Evidence: run both parameterizations and expect the same scenario list to
  pass under each:

```bash
uv run pytest tests/test_generation_run_port_contract.py \
  tests/canonical_storage/test_sql_generation_run_contract.py -v
```

- Non-vacuity: the suite must be seen failing against a deliberately
  incomplete SQL adapter first — this is the red stage of EP-M2. Record the
  failure transcript. A suite that passes on first run against an unwritten
  adapter is measuring nothing.

### INV-CKPT-2 — terminal checkpoints reject further transitions

- Obligation: any transition applied to a checkpoint whose status is
  `responded`, `timed_out`, or `cancelled` raises `CheckpointAlreadyTerminal`
  and leaves the persisted row unchanged.
- Method: parameterized test over the cross product of
  `{responded, timed_out, cancelled}` starting states and
  `{respond, time_out, cancel}` transitions — nine finite cases, so enumeration
  is exhaustive and a property test would add nothing.
- Artefact: the shared contract scenarios module.
- Non-vacuity: after each expected exception, re-read the row from a *fresh*
  unit of work and assert the status is unchanged. Without that re-read the
  test would pass even if the adapter wrote the mutation and then raised.

### INV-CKPT-3 — checkpoints round-trip through PostgreSQL exactly

- Obligation: a checkpoint written and committed, then read in a fresh unit of
  work, is equal to the original — including `options` tuple ordering,
  `response_payload` JSONB contents, and timezone-aware timestamps.
- Method: integration test using two sequential unit-of-work scopes over one
  `session_factory`, plus a syrupy snapshot of the serialized checkpoint to
  catch silent shape changes.
- Rationale: `options` is a `tuple[str, ...]` in the domain and a JSONB array
  in storage; the mapper must restore tuple-ness and order. Timestamps must
  survive as `tzinfo`-aware.
- Artefact: `tests/canonical_storage/test_generation_checkpoints.py` with
  `tests/canonical_storage/__snapshots__/test_generation_checkpoints.ambr`.
- Non-vacuity: use an `options` value whose order is not alphabetical (for
  example `("edit", "approve", "request_changes")`) so a sorting bug is
  visible, and a `response_payload` containing a nested mapping and a list.
  Negative control: map `options` through `set()` in the mapper and confirm the
  ordering assertion fails.

### INV-CKPT-4 — a checkpoint cannot reference a non-existent run

- Obligation: `create_checkpoint` for an unknown `generation_run_id` raises
  `RunNotFound`, matching in-memory behaviour, and no row is written.
- Method: parameterized test; the adapter checks the precondition explicitly
  and the foreign key enforces it as defence in depth.
- Artefact: the shared contract scenarios module.
- Non-vacuity: assert both that `RunNotFound` is raised *and* that a
  subsequent `SELECT count(*)` on `generation_checkpoints` returns zero. A test
  asserting only the exception would pass even if an `IntegrityError` were
  being mistranslated after a partial write.

### INV-MIG-1 — no schema drift

- Obligation: after the new migration, `compare_metadata` reports no
  difference between the live schema and `Base.metadata`.
- Method: the existing repository drift check.
- Artefact: `episodic/canonical/storage/migration_check.py`, driven by
  `tests/features/schema_migrations.feature`.
- Evidence: `make check-migrations`. Expected output: no drift reported,
  non-zero exit only on failure.
- Non-vacuity: already provided by the second scenario in that feature file
  ("Drift detected when models diverge from migrations"), which adds an
  unmigrated table and asserts drift *is* reported. That scenario is the
  standing negative control; confirm it still passes.

### INV-MIG-2 — the migration is reversible

- Obligation: `upgrade` → `downgrade` → `upgrade` leaves the schema identical
  to a single `upgrade`, and the intermediate `downgrade` removes the table and
  both new enums without orphaning either.
- Method: integration test driving Alembic programmatically against a
  py-pglite engine.
- Rationale: `downgrade()` is almost never exercised and native PostgreSQL
  enums are the usual thing left behind, because dropping a table does not drop
  its enum type.
- Artefact: `tests/canonical_storage/test_generation_checkpoint_migration.py`.
- Evidence: upgrade to head, downgrade one revision, assert
  `generation_checkpoints` is absent *and* that
  `SELECT 1 FROM pg_type WHERE typname = 'generation_checkpoint_status'`
  returns no row, then upgrade again and assert no drift.
- Non-vacuity: the `pg_type` assertion is the point of the test. Omit the
  explicit `.drop(bind, checkfirst=True)` calls from `downgrade()` and the test
  must fail; verify that it does before trusting it.

### INV-LEASE-1 — lease reclamation is selective and idempotent (EP-M4)

- Obligation: the reclamation query transitions a run to `failed` **only** if
  its status is `running` and `lease_expires_at` is non-null and at or before
  the supplied instant. For each reclaimed run it appends exactly one
  `run.failed` event, in the same transaction, at the next sequence number.
  Running it twice reclaims nothing the second time.
- Method: parameterized tests over the state partition
  (`pending`, `running` with no lease, `running` with a future lease, `running`
  with an expired lease, each terminal status), plus an idempotence test that
  invokes it twice.
- Rationale: the partition is finite and small, and each cell is a distinct
  correctness claim about the `WHERE` clause. This is exactly the case for
  parameterized tests rather than a property test.
- Artefact: `tests/canonical_storage/test_generation_run_lease_reclamation.py`.
- Non-vacuity: the partition must include at least one run that *is* reclaimed
  and at least one of each kind that is *not*; assert the exact set of
  reclaimed run identifiers, not merely a count. Negative control: drop the
  `lease_expires_at IS NOT NULL` predicate and confirm that the "running with
  no lease" case then fails.

### Residual gaps

- Behavioural equivalence between the in-memory and SQL adapters is claimed
  **only under a single writer per run**. The in-memory adapter serializes with
  an in-process `asyncio.Lock`, which no cross-connection adapter can
  reproduce. Under genuine multi-process contention the SQL adapter relies on
  AXIOM-1. This limit is stated here rather than hidden, and it matches the
  system design's "one graph runner owns mutation for a run" assumption.
- No verification is planned for behaviour under PostgreSQL `SERIALIZABLE`
  isolation; the application runs at the default `READ COMMITTED`.

## Plan of work

### Stage A — understand and propose (no code changes)

Load the `leta`, `hexagonal-architecture`, and `python-router` skills, then run
`leta workspace add .`.

Perform the abstraction sweep that `AGENTS.md` requires before adding any port,
adapter, or helper:

```bash
leta grep "Checkpoint" -k class -d
leta implementations GenerationCheckpointPort
leta refs GenerationRunEventStore
leta refs CanonicalUnitOfWork
```

Confirm from that output that (a) no SQL checkpoint adapter exists, (b) the
only implementers of `GenerationRunEventStore` are the in-memory store and
`SqlAlchemyGenerationRunStore`, and (c) `SqlAlchemyWorkflowCheckpointStore` is
a *different* concept that must not be reused. Confirm the migration head:

```bash
uv run alembic heads
```

Expected: a single head, `20260624_000012 (head)`. If more than one head is
reported, stop and escalate per `Tolerances`.

Stage A ends when the sweep confirms the gap. Make no code changes.

### Stage B — red tests

Write the failing tests before any production code, in this order.

1. Extract the adapter-agnostic scenarios currently in
   `tests/test_generation_run_port_contract.py` and
   `tests/test_generation_checkpoint_port_contract.py` into a new shared module
   `tests/generation_run_contract_scenarios.py`. The leading name has no
   `test_` prefix, so pytest will not collect it directly — this matches the
   repository's existing convention for shared step and support modules
   (`tests/steps/source_intake_support.py`,
   `tests/canonical_storage/_generation_run_support.py`). Express the scenarios
   as a base class with an abstract `store` fixture.
2. Re-point `tests/test_generation_run_port_contract.py` and
   `tests/test_generation_checkpoint_port_contract.py` at that base class,
   supplying `InMemoryGenerationRunStore`. Run them; they must still pass. This
   is a pure refactor and is the safety net for step 3.
3. Add `tests/canonical_storage/test_sql_generation_run_contract.py`,
   supplying a `SqlAlchemyUnitOfWork`-backed store via `session_factory`. Run
   it. It **must fail** with `AttributeError` on `create_checkpoint`, because
   the SQL adapter has no checkpoint methods. Record that transcript — it is
   the red evidence for INV-CKPT-1.
4. Add the migration reversibility test
   (`tests/canonical_storage/test_generation_checkpoint_migration.py`) and the
   round-trip test (`tests/canonical_storage/test_generation_checkpoints.py`).
   Both must fail because the table does not exist.
5. Add the behavioural specification. Create
   `tests/features/durable_generation_checkpoints.feature`:

```gherkin
Feature: Durable generation-run checkpoints

  Reviewer checkpoints must survive a process restart so that a long
  editorial review does not lose state.

  Scenario: A responded checkpoint survives a new unit of work
    Given a generation run persisted in PostgreSQL
    And a checkpoint created against that run
    When the reviewer responds with action "approve"
    And the unit of work is committed and closed
    Then reading the checkpoint in a new unit of work reports status "responded"
    And the recorded reviewer action is "approve"

  Scenario: A terminal checkpoint rejects a second response
    Given a generation run persisted in PostgreSQL
    And a checkpoint created against that run
    When the reviewer responds with action "approve"
    And the reviewer responds with action "edit"
    Then the second response is rejected as already terminal
    And reading the checkpoint in a new unit of work reports status "responded"

  Scenario: A checkpoint cannot be created for an unknown run
    Given no generation run exists for a freshly generated identifier
    When a checkpoint is created against that identifier
    Then the checkpoint creation is rejected as run not found
    And no checkpoint rows are persisted
```

   Add `tests/steps/test_durable_generation_checkpoints_steps.py` using the
   repository's `@scenario`-decorator style (the codebase uses `@scenario`
   exclusively; `scenarios()` appears nowhere) and `parsers.parse` for
   placeholders. Follow `tests/steps/test_schema_migrations_steps.py` for the
   async-step pattern with the shared `_function_scoped_runner` fixture.

Stage B ends when every new test fails for the intended reason — a missing
table or a missing method, not an import error or a fixture typo. Do not
proceed while any failure is incidental.

### Stage C — implementation

Implement in the order below, re-running the focused failing test after each
step.

1. **Enums.** In `episodic/canonical/storage/models_base.py`, add
   `GENERATION_CHECKPOINT_STATUS` and `GENERATION_CHECKPOINT_ACTION` alongside
   the existing declarations, using the same `values_callable` idiom.
2. **ORM model.** Add
   `episodic/canonical/storage/generation_checkpoint_models.py` with
   `GenerationCheckpointRecord`. Re-export it from
   `episodic/canonical/storage/models.py` (the aggregator) and from
   `episodic/canonical/storage/__init__.py`.
3. **Migration.** Add
   `alembic/versions/20260823_000013_add_generation_checkpoints.py`, chained off
   `20260624_000012`. Follow the structure of
   `20260624_000010_add_generation_run_tables.py` exactly: a module docstring,
   a private `_enum(name, *values)` helper returning
   `postgresql.ENUM(*values, name=name, create_type=False)`, private
   `_create_enums` / `_drop_enums` / `_create_*_table` / `_drop_*_table`
   helpers, and `upgrade()` / `downgrade()` composed from them. Create the
   enums with `.create(op.get_bind(), checkfirst=True)` before the table and
   drop them after the table in `downgrade()`. Run `make check-migrations`.
4. **Mapper.** Add
   `episodic/canonical/storage/generation_checkpoint_mappers.py` with
   `checkpoint_from_record` and `checkpoint_to_record`. `options` maps to a
   JSON list on write and back to a `tuple[str, ...]` on read, preserving order.
5. **Adapter mixin.** Add
   `episodic/canonical/storage/generation_checkpoints.py` with
   `SqlAlchemyGenerationCheckpointMixin`, deliberately mirroring the structure
   of `episodic/canonical/adapters/generation_checkpoints.py`. It must:
   - Delegate every state change to the domain transition
     (`checkpoint.respond(response)`, `.time_out(at)`, `.cancel(at)`) and
     persist the returned entity. Do not reimplement the rules.
   - Let `CheckpointAlreadyTerminal` propagate from the domain unchanged.
   - Raise `RunNotFound` when the parent run is absent and
     `CheckpointNotFound` when the checkpoint is absent.
   - Lock the checkpoint row with `with_for_update()` before applying a
     transition, so a concurrent responder loses cleanly.
   - Emit the same structured log events as the in-memory mixin, via
     `episodic.orchestration._types._log_event`.
   - `flush()` but never `commit()`.
6. **Compose.** Make `SqlAlchemyGenerationRunStore` inherit
   `SqlAlchemyGenerationCheckpointMixin`. The class then satisfies the composite
   `GenerationRunPort`.
7. **Widen the unit of work.** Change
   `episodic/canonical/unit_of_work_protocols.py` so
   `generation_runs: GenerationRunPort`. Update the import. Run
   `make typecheck` and fix every implementer the checker names, in the same
   commit — no shims.

Stage C ends when the contract suite passes against both adapters and
`make check-migrations` is clean.

### Stage D — lease reclamation (EP-M4, gated)

Only start this stage if Stage C is fully green. Re-read `Decision log` D-6 and
the matching entry in `Tolerances` first: if the work starts to require a
scheduler, a Celery beat entry, or a long-running worker, **stop and
escalate**. The deliverable is a repository method, nothing more.

1. Add `fail_expired_leases` to `GenerationRunRepository` in
   `episodic/canonical/generation_run_ports.py`, returning the tuple of runs it
   reclaimed:

```python
async def fail_expired_leases(
    self,
    *,
    now: dt.datetime,
    limit: int = 100,
) -> tuple[GenerationRun, ...]:
    """Fail runs whose execution lease has expired."""
    raise NotImplementedError
```

1. Implement it in both adapters. In the SQL adapter, select qualifying runs
   `FOR UPDATE SKIP LOCKED`, append one `run.failed` event per run at the next
   sequence number with `error_category="launcher.lease_expired"`, and update
   the run to `failed` — all in the caller's transaction.
2. Add the supporting partial index to the migration from EP-M1:
   `ix_generation_runs_expired_lease` on `(lease_expires_at)` with
   `postgresql_where=sa.text("status = 'running'")`. Mirror it exactly in the
   ORM `__table_args__` or `make check-migrations` will report drift.
3. Replace the manual SQL procedure in `docs/developers-guide.md` §"Manual
   recovery of expired generation-run leases" with a description of the new
   method, and state plainly that no scheduler invokes it yet.

### Stage E — documentation and reconciliation

1. `docs/developers-guide.md` §"Generation-run domain ports": describe the SQL
   checkpoint adapter, the composite-port implementation, and the widened
   `CanonicalUnitOfWork.generation_runs` type.
2. `docs/users-guide.md` §"Generation runs and review checkpoints": the
   sentence "this release establishes the domain model and in-memory reference
   port used by those later endpoints" is now wrong for checkpoints. Correct it
   to say that runs, event logs, and reviewer checkpoints are durably stored in
   PostgreSQL and survive a restart, while noting that the public HTTP
   endpoints remain planned. Durability is a user-visible guarantee even
   without a new endpoint.
3. Add `docs/adr/adr-018-generation-checkpoint-persistence.md`. Follow the
   shape of `adr-015-generation-run-port-split.md` (Status, Context, Decision,
   Consequences with Positive/Negative/Neutral, References) rather than the
   longer literal template in the style guide; that variant is established
   house practice for narrow decisions. Cover D-2, D-3, D-4, and D-5. Add the
   entry to `docs/contents.md` and reference the ADR from
   `docs/episodic-podcast-generation-system-design.md`.
4. Reconcile the roadmap. `docs/roadmap.md` item 2.6.2 should be ticked by the
   implementor on completion. Add a one-line note under it recording that run
   and event persistence landed earlier under 4.3.2, so the history is legible.
5. Run `make fmt`, then `make markdownlint` and `make nixie`.

Note the recorded interaction: `make fmt` can introduce MD013 (line-length)
violations on long inline code spans. If `make markdownlint` fails after
`make fmt`, wrap or shorten the offending span rather than reverting the format.

## Milestones and plateaus

Each milestone ends in a coherent, validated repository state.

### EP-M1 — checkpoint table and reversible migration

- Outcome: `generation_checkpoints` exists in the ORM metadata and in the
  migration history, with both new enums. No adapter uses it yet, which is
  coherent: the schema simply leads the code.
- Requirements: `DESIGN-ORCH-CKPT`, `ROADMAP-2.6.2` (migration half).
- Acceptance evidence: `make check-migrations` reports no drift;
  `tests/canonical_storage/test_generation_checkpoint_migration.py` passes,
  including the `pg_type` assertion after `downgrade()`.
- Conformance check: single migration head; no collision with
  `workflow_checkpoints`; enum naming follows `models_base.py`; no persisted
  format changed for any existing table.
- Recovery: `uv run alembic downgrade -1`, delete the revision file, re-run
  `make check-migrations`.
- Remaining gaps: no adapter, no wiring.
- Compatibility decision: none required. The table is new; no deployed data
  depends on it.

### EP-M2 — SQL checkpoint adapter and composite port

- Outcome: `SqlAlchemyGenerationRunStore` satisfies `GenerationRunPort`;
  `uow.generation_runs` is typed and wired accordingly. Reviewer checkpoints
  are durable.
- Requirements: `API-GENRUN-CKPT`, `ADR-015`.
- Acceptance evidence: the shared contract suite passes against both adapters;
  `tests/features/durable_generation_checkpoints.feature` passes; a checkpoint
  created and responded to in one unit of work reads back correctly in a second.
- Conformance check: dependency rule intact (`make check-architecture`); no
  existing port signature changed; every file under 400 lines; no new
  dependency.
- Recovery: the mixin is additive; revert the composition line in
  `SqlAlchemyGenerationRunStore` and the protocol widening to return to EP-M1.
- Remaining gaps: lease reclamation; documentation.
- Compatibility decision: none. `CanonicalUnitOfWork` is an
  application-internal, pre-1.0 protocol with no external implementers.
  Widening it and updating all implementers in one commit is correct; a
  transitional narrower alias would be compatibility theatre.

### EP-M3 — contract equivalence and ordering evidence

- Outcome: one scenario list drives both adapters; event ordering and
  checkpoint durability are proven against a real PostgreSQL engine.
- Requirements: `ROADMAP-2.6.2` (integration-test half), `API-GENRUN-SEQ`.
- Acceptance evidence: INV-SEQ-1, INV-SEQ-2, INV-SEQ-3, INV-CKPT-1 through
  INV-CKPT-4 discharged, each with its recorded non-vacuity check.
- Conformance check: suite runtime within the 25% tolerance; database-backed
  Hypothesis tests keep `max_examples` at 5–6.
- Recovery: tests are additive; delete the new modules to return to EP-M2.
- Remaining gaps: lease reclamation; documentation.

### EP-M4 — lease reclamation primitive (gated)

- Outcome: a repository method that atomically fails expired-lease runs and
  records the corresponding event. No scheduler.
- Requirements: `EP-4.3.2-DEFER`.
- Acceptance evidence: INV-LEASE-1 discharged over the full state partition,
  with the exact reclaimed-identifier assertion.
- Conformance check: the port gained one method and both adapters implement
  it; the partial index matches between ORM and migration; no worker,
  scheduler, or beat entry was added.
- Recovery: revert the port method, both implementations, and the index.
  EP-M3 remains a valid plateau.
- Remaining gaps: nothing schedules the reclamation. State this explicitly in
  the developers' guide.

### EP-M5 — documentation and reconciliation

- Outcome: developers' guide, users' guide, ADR-018, `docs/contents.md`, and
  the design-document cross-reference are current.
- Acceptance evidence: `make markdownlint` and `make nixie` pass; the
  users'-guide passage no longer claims checkpoints are in-memory.
- Conformance check: every discovery in `Surprises & discoveries` is
  reconciled against `Conformance basis`; the ADR-015 numbering collision is
  recorded as a follow-up, not silently fixed.
- Recovery: documentation-only; revert freely.

## Concrete steps

Run everything from the repository root.

Confirm the starting state:

```bash
git branch --show-current
uv run alembic heads
```

Expected:

```plaintext
20260624_000012 (head)
```

Run the focused red test after Stage B step 3:

```bash
uv run pytest tests/canonical_storage/test_sql_generation_run_contract.py -v \
  2>&1 | tee /tmp/red-episodic-$(git branch --show-current).out
```

Expected — the intended failure, not an import error:

```plaintext
E   AttributeError: 'SqlAlchemyGenerationRunStore' object has no attribute 'create_checkpoint'
```

After Stage C step 3, check the migration in both directions:

```bash
make check-migrations 2>&1 | tee /tmp/migrations-episodic-$(git branch --show-current).out
```

Expected:

```plaintext
No schema drift detected.
```

Run the full gates at every milestone boundary, **sequentially** — this
environment uses build caching and parallel gate runs defeat it:

```bash
make check-fmt && make typecheck && make lint && make check-migrations && make test
```

Prefer delegating that full run to the `scrutineer` subagent, which runs the
gates in order, tees each to a log under `/tmp`, and returns a bounded report.
When it reports a failure, read the log it cites rather than re-running the
gate; re-run only after applying a fix.

Commit at each milestone boundary with a descriptive message, so the work can
be bisected:

```bash
git add -A && git commit
```

## Validation and acceptance

Acceptance is behavioural. A reader must be able to run these and see the
stated result.

**Red-Green-Refactor evidence.** For each of EP-M1 through EP-M4, record:

- the red command and its failure, with the failure reason quoted;
- the green command and its pass after the minimal implementation;
- the refactor command sequence and its pass after cleanup.

Where a test would otherwise pass trivially before the implementation exists,
mark it `@pytest.mark.xfail(strict=True, reason="...")` until the red failure
is observed, then remove the marker as part of the green step. Do not leave
`xfail` markers in the final tree.

**Behavioural evidence.** Run the BDD scenarios:

```bash
uv run pytest tests/steps/test_durable_generation_checkpoints_steps.py -v
```

Expected: three scenarios pass. Before EP-M2 they must fail.

**Durability demonstration.** The observable outcome that matters: create a run
and a checkpoint in one unit of work, commit, close it, then in a new unit of
work read the checkpoint back with status `responded` and the reviewer's action
intact. This is scenario 1 of the feature file above, and it is what "without
state loss" in the system design means in practice.

Quality criteria — what "done" means:

- Tests: `make test` passes with no new failures, skips, or `xfail` markers,
  and within the 25% runtime tolerance.
- Verification: INV-SEQ-1 through INV-LEASE-1 discharged, each with its
  recorded non-vacuity check and negative control. Any obligation left
  undischarged must be named here with its reason.
- Lint and typecheck: `make check-fmt`, `make lint`, `make typecheck`, and
  `make check-architecture` all pass. Investigate every Skylos dead-code
  finding; when one is a false positive, prefer a typed entry-point rule in
  `[tool.skylos.dead_code]` naming the verified runtime caller, with
  `type = "method"` for methods.
- Migrations: `make check-migrations` reports no drift; a single head.
- Documentation: `make markdownlint` and `make nixie` pass.
- Performance: no benchmark threshold applies to this slice; the only budget
  is suite runtime.

## Idempotence and recovery

Every step is re-runnable.

- `make check-migrations` starts an ephemeral py-pglite instance and leaves no
  state behind.
- The py-pglite test fixtures drop and recreate the `public` schema per test
  function, so a failed test cannot poison a later one.
- `uv run alembic downgrade -1` reverses EP-M1. The reversibility test exists
  precisely so this is trustworthy rather than hopeful.
- Each milestone is a separate commit, so `git revert` returns the tree to the
  previous plateau without manual unpicking.
- Nothing in this plan touches production data or any external service. There
  is no destructive step and no backup is required.

## Artefacts and notes

Record here, as work proceeds:

- the red transcript from Stage B step 3 (the `AttributeError` proving the SQL
  adapter lacks checkpoint methods);
- the seeded-fault transcript for INV-SEQ-1, showing the property test
  detecting a duplicate sequence number once row locking is removed;
- the `downgrade()` transcript showing `generation_checkpoint_status` removed
  from `pg_type`;
- `make test` wall-clock time before and after, for the runtime tolerance.

## Interfaces and dependencies

No new external dependency. Everything below already exists in the tree.

In `episodic/canonical/storage/models_base.py`, add:

```python
GENERATION_CHECKPOINT_STATUS = sa.Enum(
    CheckpointStatus,
    name="generation_checkpoint_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
GENERATION_CHECKPOINT_ACTION = sa.Enum(
    CheckpointAction,
    name="generation_checkpoint_action",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
```

In `episodic/canonical/storage/generation_checkpoint_models.py`, define
`GenerationCheckpointRecord` on `__tablename__ = "generation_checkpoints"` with
these columns. `updated_at` is storage-only and has no domain counterpart; it
exists for operational triage, mirroring `WorkflowCheckpointRecord`.

| Column              | Type                            | Nullable | Notes                                                     |
| ------------------- | ------------------------------- | -------- | --------------------------------------------------------- |
| `id`                | `postgresql.UUID(as_uuid=True)` | no       | Primary key, client-assigned UUIDv7                       |
| `generation_run_id` | `postgresql.UUID(as_uuid=True)` | no       | FK to `generation_runs.id`, `ondelete="CASCADE"`, indexed |
| `node`              | `sa.String(160)`                | no       | Orchestration node that raised the checkpoint             |
| `prompt`            | `sa.Text`                       | no       | Reviewer-facing prompt                                    |
| `options`           | `postgresql.JSONB`              | no       | Ordered JSON array of option strings                      |
| `status`            | `GENERATION_CHECKPOINT_STATUS`  | no       | Indexed                                                   |
| `response_action`   | `GENERATION_CHECKPOINT_ACTION`  | yes      | Set only when responded                                   |
| `response_payload`  | `postgresql.JSONB`              | yes      | Reviewer notes or patch                                   |
| `responded_at`      | `sa.DateTime(timezone=True)`    | yes      | Also set on time-out and cancel                           |
| `responded_by`      | `sa.String(240)`                | yes      | Reviewer identity                                         |
| `created_at`        | `sa.DateTime(timezone=True)`    | no       | `server_default=sa.func.now()`                            |
| `updated_at`        | `sa.DateTime(timezone=True)`    | no       | `server_default=sa.func.now()`, `onupdate=sa.func.now()`  |

Table 1: Columns of the `generation_checkpoints` table.

In `episodic/canonical/storage/generation_checkpoint_mappers.py`, define:

```python
def checkpoint_from_record(record: GenerationCheckpointRecord) -> Checkpoint:
    """Map a checkpoint record to a domain entity."""


def checkpoint_to_record(checkpoint: Checkpoint) -> GenerationCheckpointRecord:
    """Map a checkpoint domain entity to a SQLAlchemy record."""
```

In `episodic/canonical/storage/generation_checkpoints.py`, define
`SqlAlchemyGenerationCheckpointMixin` providing exactly the
`GenerationCheckpointPort` surface:

```python
class SqlAlchemyGenerationCheckpointMixin:
    """Durable checkpoint operations for the generation-run adapter."""

    _session: AsyncSession
    _runtime: GenerationRunStorageRuntime

    async def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint: ...

    async def get_checkpoint(
        self, checkpoint_id: uuid.UUID
    ) -> Checkpoint | None: ...

    async def respond_to_checkpoint(
        self, checkpoint_id: uuid.UUID, *, response: CheckpointResponse
    ) -> Checkpoint: ...

    async def time_out_checkpoint(
        self, checkpoint_id: uuid.UUID, *, at: dt.datetime
    ) -> Checkpoint: ...

    async def cancel_checkpoint(
        self, checkpoint_id: uuid.UUID, *, at: dt.datetime
    ) -> Checkpoint: ...
```

In `episodic/canonical/storage/generation_runs.py`, change the class
declaration to compose the mixin:

```python
class SqlAlchemyGenerationRunStore(SqlAlchemyGenerationCheckpointMixin):
    """PostgreSQL adapter satisfying the composite generation-run port."""
```

In `episodic/canonical/unit_of_work_protocols.py`, widen the declared type:

```python
generation_runs: GenerationRunPort
```

At the end of EP-M2 the following must hold, and is worth asserting directly in
a test:

```python
assert isinstance(uow.generation_runs, GenerationRunPort)
```

The protocols are `@typ.runtime_checkable`, so this check is meaningful for
method presence, though not for signatures — `make typecheck` covers those.

## Revision note

2026-08-23 — Rewritten from the previous draft. The earlier version was
authored against a tree that predated commit `5af0638` (roadmap 4.3.2) and
asserted that "there is no durable persistence for generation runs", which is
no longer true: runs, events, the `20260624_000010` migration, and event-
ordering property tests all already exist. It also targeted head
`20260601_000009`, three revisions stale. This revision re-scopes the plan to
the genuine remaining gap — reviewer-checkpoint persistence, a composite-port
implementation, cross-adapter contract equivalence, and the lease-reclamation
primitive that 4.3.2 deferred here by name — and adds the `Conformance basis`
and `Verification plan` sections the ExecPlan format requires. Remaining work
is unchanged in kind but substantially smaller in volume than the previous
draft implied.
