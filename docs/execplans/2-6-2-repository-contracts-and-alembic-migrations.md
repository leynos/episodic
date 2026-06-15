# Implement generation-run repository contracts and Alembic migrations (2.6.2)

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: DRAFT (revised after community-of-experts review)

## Purpose / big picture

Roadmap item 2.6.1 defined the user-facing generation-run domain model
(`GenerationRun`, `GenerationEvent`, `Checkpoint`) and its port protocols
(`GenerationRunRepository`, `GenerationEventLog`, `GenerationCheckpointPort`,
and the composite `GenerationRunPort`), together with an in-memory reference
adapter. Those live in `episodic/canonical/domain.py`,
`episodic/canonical/generation_run_ports.py`,
`episodic/canonical/generation_run_errors.py`, and
`episodic/canonical/adapters/generation_runs.py`.

Today there is no durable persistence for generation runs: the only adapter is
the ephemeral, single-process `InMemoryGenerationRunStore`. This slice adds a
PostgreSQL-backed adapter that satisfies the existing composite port, an Alembic
migration that creates the backing tables, and integration tests that prove
event ordering holds against a real PostgreSQL engine.

After this change, a developer can do the following and observe it working:

1. Run `make check-migrations` and see no schema drift between the SQLAlchemy
   models and the migrations (the new `generation_runs`, `generation_events`,
   and `generation_checkpoints` tables are present in both).
2. Open a `SqlAlchemyUnitOfWork`, call `uow.generation_runs.create_run(...)`,
   append events, create and respond to checkpoints, commit, then in a fresh
   unit-of-work read the same run, its ordered event log, and its checkpoints
   back from PostgreSQL.
3. Run `make test` and see the generation-run port-contract suite pass against
   *both* the in-memory adapter and the new PostgreSQL adapter, plus a dedicated
   event-ordering integration suite proving that appended events receive
   contiguous, strictly increasing sequence numbers and that
   `list_events(after_seq=...)` returns them in ascending order with correct
   half-open paging.

This unblocks 2.6.3 (REST endpoints for generation runs), which needs a durable
store behind the API.

## Signposts: documentation and skills

Read these before and during implementation. They are the source of truth for
conventions this plan must follow.

- Architecture scope and layering: the `hexagonal-architecture` skill, plus
  `docs/adr/adr-014-hexagonal-architecture-enforcement.md` and the
  "Hexagonal architecture enforcement" section of
  `docs/episodic-podcast-generation-system-design.md`. Domain and ports must not
  import adapters; the new SQLAlchemy modules are outbound adapters.
- Generation-run port split rationale: `docs/adr/adr-015-generation-run-port-split.md`
  and `docs/execplans/2-6-1-generation-run-port-and-domain-model.md`.
- Async persistence patterns: `docs/async-sqlalchemy-with-pg-and-falcon.md`
  (use `expire_on_commit=False`, explicit `flush`/`commit`, catch
  `IntegrityError` for constraint violations).
- Persistence testing: `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`
  and `docs/developers-guide.md` sections "Canonical content persistence",
  "Database migrations", and "Database testing with py-pglite".
- Orchestration checkpoint context (so the user-facing checkpoint table is not
  confused with the orchestration one):
  `docs/agentic-systems-with-langgraph-and-celery.md` and
  `docs/adr/adr-007-durable-generation-checkpoints.md`.
- REST contract that this store must later serve (for forward compatibility of
  the schema): the "Generation runs" section of `docs/episodic-tui-api-design.md`.
- Code navigation during implementation: use the `leta` skill
  (`leta show`, `leta refs`, `leta grep`) rather than ad-hoc file reading.
- Inference simulation: the `vidai-mock` skill. See the note under
  `Constraints` — this slice does not exercise inference, so vidai-mock is not
  used here; it is signposted because the phase-wide instruction references it.

## Constraints

Hard invariants that must hold throughout implementation. Violation requires
escalation, not a workaround.

- Do not modify the existing public domain or port surface defined in 2.6.1:
  `episodic/canonical/domain.py` (the `GenerationRun`, `GenerationEvent`,
  `Checkpoint`, `CheckpointResponse`, and enum definitions),
  `episodic/canonical/generation_run_ports.py`, and
  `episodic/canonical/generation_run_errors.py`. The new adapter conforms to
  them; it does not change them. Adding new enums to `models_base.py` and new
  modules under `episodic/canonical/storage/` is in scope.
- The PostgreSQL adapter must be behaviourally indistinguishable from
  `InMemoryGenerationRunStore` for every method on the composite
  `GenerationRunPort` *under the single-writer-per-run assumption* (roadmap
  §4.4: "one graph runner owns mutation for a run"). This includes error
  semantics (`RunNotFound`, `RunAlreadyTerminal`, `CheckpointNotFound`,
  `CheckpointAlreadyTerminal`, `StaleEventSequence`), first-write-wins
  idempotency on `create_run`, contiguous per-run event sequences starting at 1,
  and the half-open `(after_seq, ...]` paging contract on `list_events`.
  Equivalence is *not* claimed under genuine concurrent writers to one run: the
  in-memory adapter serialises with an in-process `asyncio.Lock` that no
  cross-connection database adapter can reproduce. Under contention the database
  adapter instead relies on the `UNIQUE(generation_run_id, seq)` constraint plus
  a bounded retry (see `Decision Log`); this divergence is documented in
  `Surprises & Discoveries`, not hidden.
- Hexagonal dependency rule: the new storage modules may import domain types and
  port protocols, but domain/ports must not import storage. `make
  check-architecture` (Hecate) must pass.
- Schema drift is forbidden: `make check-migrations` must report no difference
  between `Base.metadata` and the migrations. Every new table, column,
  constraint, index, and enum must exist identically in both the ORM models and
  the migration.
- The new migration must chain off the current single head revision
  `20260601_000009` (`add_cost_accounting_schema`). It must not create a second
  head. Verify with the revision graph (see `Concrete steps`).
- The user-facing generation checkpoint table must NOT collide with the existing
  orchestration `workflow_checkpoints` table or its `workflow_checkpoint_status`
  enum. Use distinct names (`generation_checkpoints`,
  `generation_checkpoint_status`).
- Timestamps are timezone-aware (`sa.DateTime(timezone=True)`). UUID primary
  keys are client-assigned UUIDv7 (`uuid.uuid7()`), matching every other
  canonical table; do not introduce server-side UUID defaults.
- JSON columns (`budget_snapshot`, `configuration`, event `payload`, checkpoint
  `response_payload`) use `postgresql.JSONB` and must round-trip the
  `JsonMapping = dict[str, object]` domain type, preserving the domain's
  defensive-copy semantics (mappers must deep-copy on the way out so callers
  cannot mutate stored state).
- Python 3.14, SQLAlchemy 2.0.x async, asyncpg, Alembic 1.13.x. All new code
  passes `make check-fmt`, `make typecheck`, `make lint`, and `make test`. No
  file exceeds 400 lines (AGENTS.md); split models/mappers/repositories into
  separate modules as the existing code does.
- vidai-mock is out of scope for this slice. The repository and migration code
  perform no LLM or TTS inference, so there is no inference service to simulate.
  Behavioural inference testing with vidai-mock belongs to slices that drive
  generation (for example 4.3.2 and 4.4.x). This exclusion is recorded as a
  decision rather than silently skipped.

## Tolerances (exception triggers)

- Scope: if implementation requires touching more than ~14 files or more than
  ~900 net new lines (excluding generated migration boilerplate and tests), stop
  and escalate.
- Interface: if satisfying the contract appears to require changing any 2.6.1
  domain/port signature, stop and escalate (the contract is fixed by
  `Constraints`).
- Dependencies: if a new third-party runtime dependency seems required, stop and
  escalate. None is expected; SQLAlchemy, asyncpg, and Alembic are already
  present.
- Event-sequence design: if the chosen `MAX(seq)+1`-under-unique-constraint
  allocation (see `Decision Log`) cannot satisfy the in-memory adapter's
  gap-free, contiguous-from-1 contract under the project's single-writer-per-run
  assumption, stop and escalate before adopting a Postgres global `SEQUENCE`,
  advisory locks, or a run-row counter column.
- Iterations: if the migration-drift check (`make check-migrations`) still fails
  after 3 focused attempts to reconcile models and migration, stop and escalate
  with the diff.
- py-pglite concurrency: if an event-ordering test appears to require *true*
  parallel writers (which py-pglite cannot provide; see `Risks`), stop and
  escalate rather than spinning up an external PostgreSQL in the test suite.
- Ambiguity: if the design docs and the in-memory adapter disagree on any
  observable behaviour, treat the in-memory adapter as the executable
  specification, note the discrepancy in `Surprises & Discoveries`, and continue;
  escalate only if the disagreement is material to the schema.

## Risks

- Risk: py-pglite is a single-connection WASM PostgreSQL build, so it cannot
  execute genuinely concurrent transactions; an "event ordering under
  concurrency" test cannot exercise a real write race in-process.
  Severity: medium. Likelihood: high (confirmed: PGlite is single-connection).
  Mitigation: the design assumes single-writer-per-run ownership (roadmap §4.4
  concurrency model: "one graph runner owns mutation for a run"). Tests validate
  (a) contiguous monotonic sequencing on sequential appends, (b) ascending order
  and half-open paging from `list_events`, and (c) the unique-constraint guard
  by inserting a conflicting `(generation_run_id, seq)` row directly and
  asserting `StaleEventSequence`. True multi-writer stress is documented as
  out of scope for this slice and deferred to a real-PostgreSQL CI tier.
- Risk: a Postgres global `SEQUENCE`/`BIGSERIAL` for event ordering would
  produce gaps (rolled-back transactions burn numbers) and commit-order/visible-
  order skew, breaking the in-memory adapter's gap-free contract.
  Severity: high. Likelihood: high if a sequence were used.
  Mitigation: do not use a global sequence for `seq`. Use a per-run
  application-assigned sequence (`MAX(seq)+1` within the writing transaction)
  guarded by a `UNIQUE(generation_run_id, seq)` constraint, mirroring the
  existing history-table `revision` pattern. See `Decision Log`.
- Risk: "single-writer-per-run" is an orchestration convention, not an invariant
  enforced at this layer; the adapter is also reachable from the future REST
  layer (2.6.3) and from retries. On a genuine race, two appends compute the same
  `MAX(seq)` and one loses on the unique constraint. Surfacing that as a terminal
  `StaleEventSequence` would silently drop a state-transition event from the log.
  Severity: high. Likelihood: low under single-writer, but non-zero.
  Mitigation: `append_event` performs a bounded retry (recompute `MAX(seq)`,
  re-insert; 3 attempts) inside a `session.begin_nested()` savepoint so a
  conflict does not poison the surrounding unit-of-work transaction; only after
  the retry budget is exhausted does it raise `StaleEventSequence`. Each conflict
  is logged and counted via a `generation_event.append.conflicts` signal so
  operators can alert on contention. This mirrors the conflict→recover behaviour
  of `SqlAlchemyWorkflowCheckpointStore`. See `Decision Log`.
- Risk: `list_runs` (especially status-filtered) degrades to a full scan-and-sort
  over an episode's runs if only the `episode_id` foreign-key column is indexed.
  Severity: medium. Likelihood: medium as run counts grow.
  Mitigation: add composite indexes `(episode_id, created_at)` and
  `(episode_id, status, created_at)`; assert ordering determinism with a
  seeded-data test. See `Decision Log`.
- Risk: schema drift between ORM models and the migration silently passes local
  tests but fails CI `make check-migrations`.
  Severity: medium. Likelihood: medium.
  Mitigation: author the migration by hand to match the models exactly, then run
  `make check-migrations` locally before every commit in this slice; the test
  fixtures apply migrations (not `create_all`), so the tables under test are the
  migrated ones.
- Risk: name collision or enum reuse with the orchestration
  `workflow_checkpoints` table.
  Severity: medium. Likelihood: low (mitigated by naming convention in
  `Constraints`).
  Mitigation: distinct table and enum names; assert table names in a test.
- Risk: JSONB round-tripping loses the domain's defensive-copy guarantees,
  letting a caller mutate stored state.
  Severity: low. Likelihood: low.
  Mitigation: mappers deep-copy JSON mappings on read (the domain dataclasses
  also copy in `__post_init__`); a contract test mutates a returned mapping and
  asserts the store is unaffected.

## Progress

- [x] (2026-06-15) Context gathered: storage/repo/UoW/migration/test patterns,
  generation-run domain and ports, design docs, and prior art on Postgres event
  ordering and py-pglite concurrency.
- [ ] Stage A — design review and plan approval (no code).
- [ ] Stage B — red tests: failing port-contract parametrization for the SQL
  adapter, failing event-ordering integration/BDD tests, failing migration-drift
  expectation.
- [ ] Stage C — implementation: enums, ORM models, mappers, SQL adapter, UoW
  wiring, Alembic migration.
- [ ] Stage D — refactor, documentation (ADR 016, design doc, developers' guide,
  users' guide check), roadmap tick, gates green, CodeRabbit clear.

## Surprises & discoveries

- Observation: the Alembic revision graph is a single linear head despite two
  files sharing the numeric suffix `000009`. The chain is
  `…000008 → 20260610_000009 (source_intake) → 20260601_000009 (cost_accounting)`.
  Evidence: `down_revision` of `20260601_000009` is `20260610_000009`; the
  filename date prefixes are not chronologically ordered.
  Impact: the new migration's `down_revision` is `20260601_000009`; allocate the
  next suffix `000010` with today's date prefix, e.g.
  `20260615_000010_add_generation_run_tables`.
- Observation: three ADRs already share the number 015
  (`adr-015-cost-accounting-ports-and-pricing-engine.md`,
  `adr-015-generation-run-port-split.md`,
  `adr-015-upload-and-idempotency-ports.md`).
  Evidence: `ls docs/adr/`.
  Impact: allocate `adr-016-generation-run-persistence.md` for this slice.
- Observation: PGlite (the engine behind py-pglite) is explicitly a
  single-connection database.
  Evidence: pglite.dev documentation ("PGlite is a single-connection database").
  Impact: drives the event-ordering test strategy described under `Risks`. The
  in-process test suite can prove *sequential* contiguity and paging but cannot
  exercise a genuine concurrent-write race; the acceptance criteria are worded
  accordingly, and the bounded-retry conflict path is forced in tests by
  pre-inserting a conflicting row rather than by real parallelism.
- Observation (review-surfaced, to confirm during implementation): the database
  adapter cannot reproduce the in-memory adapter's in-process `asyncio.Lock`
  atomicity across connections. Equivalence therefore holds only under the
  single-writer-per-run assumption; under contention the adapter's observable
  behaviour is "bounded retry, then `StaleEventSequence`", which is strictly more
  resilient than a bare unique-constraint failure but is not identical to the
  in-memory lock. Recorded so the divergence is explicit rather than a latent
  surprise.

## Decision log

- Decision: implement a single composite adapter class
  `SqlAlchemyGenerationRunStore` that satisfies the whole `GenerationRunPort`
  (repository + event log + checkpoint), rather than three separate repository
  classes.
  Rationale: mirrors the in-memory `InMemoryGenerationRunStore` and the
  `SqlAlchemyWorkflowCheckpointStore` "store" precedent; the three sub-ports
  share the same aggregate and session, and 2.6.1 already composes them into one
  port. A single UoW attribute `uow.generation_runs` then exposes the full
  surface.
  Date/Author: 2026-06-15, planning.
- Decision: allocate per-run event sequence numbers with `MAX(seq)+1` computed
  in the writing transaction, stored in a `BIGINT` column guarded by
  `UNIQUE(generation_run_id, seq)` and `CHECK (seq >= 1)`. Wrap the insert in a
  `session.begin_nested()` savepoint and, on a unique-constraint `IntegrityError`
  for that pair, retry (recompute `MAX(seq)`, re-insert) up to 3 attempts before
  raising `StaleEventSequence`; log and count each conflict via a
  `generation_event.append.conflicts` signal.
  Rationale: this reproduces the in-memory adapter's contiguous, gap-free,
  from-1 sequence and matches the established history-table `revision` pattern
  (`UNIQUE(parent_id, revision)` + `CHECK (revision >= 1)`). A global
  `SEQUENCE`/`BIGSERIAL` is rejected because it leaks gaps on rollback and can
  expose commit/visible-order skew (prior art: event-driven.io,
  "How Postgres sequences issues can impact your messaging guarantees"). The
  bounded retry (rather than bare escalation) is the review-mandated correction:
  a losing append under contention is transient, not stale caller data, and must
  not silently drop an event; this mirrors `SqlAlchemyWorkflowCheckpointStore`'s
  conflict→recover behaviour. `BIGINT` (not `INTEGER`) is chosen because an
  append-only machine-written log is effectively unbounded over a run's life and
  the REST `after_seq` cursor inherits the type. A run-row counter column
  (`UPDATE … SET last_seq = last_seq + 1 RETURNING`) and advisory locks were
  considered and rejected: the counter column duplicates state, adds hot-path
  row contention, and diverges from the history pattern; it is recorded below as
  the documented single-round-trip upgrade path should event-append throughput
  ever dominate. Note for ADR-016: because the log is append-only with no
  deletes, `MAX(seq)+1` and `COUNT(*)+1` coincide; a future soft-delete would
  break that equivalence and must reaffirm `MAX+1`.
  Date/Author: 2026-06-15, planning (revised after review).
- Decision: foreign keys `generation_events.generation_run_id` and
  `generation_checkpoints.generation_run_id` use `ON DELETE CASCADE`;
  `generation_runs.episode_id` uses `ON DELETE RESTRICT`.
  Rationale: events and checkpoints are wholly owned by their run, so deleting a
  run removes its children atomically; runs are durable audit records, so an
  episode delete must not silently erase its generation history (it must fail
  loudly until runs are handled deliberately). No delete path exists in this
  slice, but the schema must encode intent now.
  Date/Author: 2026-06-15, planning (added after review).
- Decision: add composite indexes `(episode_id, created_at)` and
  `(episode_id, status, created_at)` on `generation_runs`; rely on the
  `UNIQUE(generation_run_id, seq)` btree for both `MAX(seq)` reverse-scan and
  `list_events` keyset pagination.
  Rationale: `list_runs` orders by creation time per episode and filters by
  status; without these indexes status-filtered pagination scans and sorts all
  of an episode's runs (review finding). The unique index already covers the
  event read paths, so no extra event index is needed.
  Date/Author: 2026-06-15, planning (added after review).
- Decision: `list_runs` orders by `(created_at, id)` and applies `offset`/`limit`
  *after* the optional status filter.
  Rationale: the in-memory adapter orders via `bisect.insort((created_at, id))`
  and skips `offset` matching rows post-filter; the contract test creates runs
  sharing one `created_at`, so a bare `ORDER BY created_at` is nondeterministic
  and would flake. The `id` tie-break (UUIDv7, time-ordered) matches the
  in-memory order.
  Date/Author: 2026-06-15, planning (added after review).
- Decision: give `generation_runs.updated_at` both a client-side
  `onupdate=sa.func.now()` and a database `BEFORE UPDATE` trigger, matching the
  `workflow_checkpoints` precedent.
  Rationale: client-side `onupdate` alone misses raw SQL updates (ops scripts,
  data migrations); the trigger guarantees `updated_at` advances regardless of
  write path. `compare_metadata` does not see triggers, so this does not cause
  drift. A test issues a raw SQL `UPDATE` and asserts `updated_at` advanced.
  Date/Author: 2026-06-15, planning (added after review).
- Decision: the SQL adapter hydrates the full domain `Checkpoint` and invokes
  its `respond`/`time_out`/`cancel` transition methods (which raise
  `CheckpointAlreadyTerminal`) rather than re-implementing terminal logic in SQL;
  it explicitly checks run existence and raises `RunNotFound` rather than relying
  solely on a foreign-key error.
  Rationale: keeps the domain state machine the single source of truth and
  preserves the in-memory adapter's error type/ordering.
  Date/Author: 2026-06-15, planning (added after review).
- Decision: do not add a dedicated `generation_run_persistence.feature` BDD
  scenario for event ordering; cover it with the example-based integration suite.
  Rationale: durable `seq` ordering is engine behaviour, not stakeholder-facing
  product behaviour, and the existing `generation_run_lifecycle.feature` already
  covers the user-facing lifecycle. The roadmap deliverable is "integration tests
  validating event ordering," which the example-based suite satisfies. A BDD
  scenario is added only if it expresses new stakeholder behaviour. This trims
  the file budget (review finding).
  Date/Author: 2026-06-15, planning (added after review).
- Decision: persist `create_run` idempotency via a nullable, unique
  `idempotency_key` column on `generation_runs`; on conflict, return the
  existing run (first-write-wins).
  Rationale: matches the in-memory adapter's first-write-wins behaviour with the
  least machinery and keeps the repository contract self-contained. The generic
  `idempotency_records` table / `SqlAlchemyIdempotencyStore` is rejected here
  because it models API-level replay (principal + operation + body hash +
  serialised outcome), which is a 2.6.3 API concern, not the repository
  contract. Revisit at 2.6.3 if the REST layer needs request-body replay.
  Date/Author: 2026-06-15, planning.
- Decision: name tables `generation_runs`, `generation_events`,
  `generation_checkpoints`; name enums `generation_run_status`,
  `generation_checkpoint_status`, `generation_checkpoint_action`.
  Rationale: avoids collision with orchestration `workflow_checkpoints` /
  `workflow_checkpoint_status`; the `generation_` prefix disambiguates the
  user-facing checkpoint from the LangGraph orchestration checkpoint.
  Date/Author: 2026-06-15, planning.
- Decision: validate the repository contract by parametrizing the existing
  port-contract suite over both adapters, and add a separate DB-only
  event-ordering suite (example-based + BDD).
  Rationale: the contract suite proves behavioural equivalence; the
  event-ordering suite is the roadmap's explicit deliverable ("integration tests
  validating event ordering"). Property tests remain primarily at the in-memory
  level for speed, with a small DB-backed example budget. See
  `Validation and acceptance`.
  Date/Author: 2026-06-15, planning.

## Context and orientation

The reader needs no prior repository knowledge. Orientation by full path:

- Domain (do not change): `episodic/canonical/domain.py` defines frozen
  dataclasses `GenerationRun`, `GenerationEvent`, `Checkpoint`,
  `CheckpointResponse`, and enums `GenerationRunStatus` (members `pending`,
  `running`, `paused`, `succeeded`, `failed`, `cancelled`; `is_terminal()` true
  for the last three), `CheckpointStatus` (`created`, `responded`, `timed_out`,
  `cancelled`; `is_terminal()` true for all but `created`), and `CheckpointAction`
  (`approve`, `request_changes`, `edit`). `JsonMapping = dict[str, object]`.
  `GenerationRun` fields: `id`, `episode_id`, `source_bundle_id`, `actor`,
  `status`, `current_node`, `budget_snapshot`, `configuration`, `created_at`,
  `updated_at`, `started_at`, `ended_at`, `error_message`. `GenerationEvent`
  fields: `id`, `generation_run_id`, `seq` (positive int), `kind`, `payload`,
  `created_at`, `occurred_at`. `Checkpoint` fields: `id`, `generation_run_id`,
  `node`, `prompt`, `options` (non-empty tuple of non-empty strings), `status`,
  `created_at`, `responded_at`, `responded_by`, `response_action`,
  `response_payload`; transition methods `respond`, `time_out`, `cancel` raising
  `CheckpointAlreadyTerminal` on a terminal checkpoint.
- Ports (do not change): `episodic/canonical/generation_run_ports.py` defines
  `GenerationRunRepository`, `GenerationEventLog`, `GenerationCheckpointPort`,
  the composite `GenerationRunPort`, the `EventSeq = NewType("EventSeq", int)`,
  and `event_seq(value)` validator.
- Errors (do not change): `episodic/canonical/generation_run_errors.py`.
- Reference adapter (the executable spec):
  `episodic/canonical/adapters/generation_runs.py`
  (`InMemoryGenerationRunStore`). Note its exact error ordering, idempotency
  log events, sequence allocation (`event_seq(len(events) + 1)`), terminal-run
  guards on `append_event`/`update_run_status`, and `list_events` semantics
  (`RunNotFound` when the run is absent; `(after_seq, ...]` filter; `limit`
  cap). The SQL adapter must match these observable behaviours, including the
  structured `_log_event` calls (reuse the same event names where reasonable).
- Storage layer (extend here):
  - `episodic/canonical/storage/models_base.py` — `Base(orm.DeclarativeBase)`
    and module-level `sa.Enum(...)` declarations. Add the three new enums here.
  - `episodic/canonical/storage/history_models.py` — the pattern to mirror for
    the append-only sequence: `UNIQUE(parent_id, revision)` +
    `CHECK (revision >= 1)`, JSONB snapshot, timezone-aware `created_at` with
    `server_default=sa.func.now()`.
  - `episodic/canonical/storage/workflow_checkpoint_models.py` and
    `workflow_checkpoints.py` — the closest "store" precedent (record + store
    adapter, `updated_at` with `onupdate`, unique idempotency column).
  - `episodic/canonical/storage/repository_base.py` — `_RepositoryBase`
    dataclass holding `_session: AsyncSession` and helpers `_get_one_or_none`,
    `_get_many`, `_list_where`, `_add_record`, `_update_where`.
  - `episodic/canonical/storage/uow.py` — `SqlAlchemyUnitOfWork`; add a
    `generation_runs` attribute wired in `__aenter__`.
  - `episodic/canonical/storage/alembic_helpers.py` — `apply_migrations(engine)`
    used by both the drift check and the test fixtures.
  - `episodic/canonical/storage/migration_check.py` — drift detector behind
    `make check-migrations`.
  - `episodic/canonical/constraints.py` — central constraint-name constants
    (e.g. `UQ_SERIES_PROFILE_HISTORY_REVISION`). Add the new constraint names
    here.
- Migrations: `alembic/versions/`. Mirror
  `20260508_000008_add_workflow_checkpoints.py` for enum-create-then-table style
  and `op.create_index`/`sa.UniqueConstraint`/`sa.CheckConstraint` usage. Head is
  `20260601_000009`.
- Tests:
  - `tests/fixtures/database.py` — py-pglite fixtures: `pglite_engine`,
    `migrated_engine` (drops public schema, runs `apply_migrations`),
    `session_factory` (`async_sessionmaker(..., expire_on_commit=False)`),
    `pglite_session`. Controlled by `EPISODIC_TEST_DB` (default `pglite`).
  - `tests/test_generation_run_port_contract.py` — existing contract suite
    against the in-memory store (fixed clock `NOW`).
  - `tests/test_generation_run_properties.py` — hypothesis properties.
  - `tests/test_generation_run_domain.py` — domain snapshots.
  - `tests/features/generation_run_lifecycle.feature` +
    `tests/steps/test_generation_run_lifecycle_steps.py` — BDD precedent.
  - `tests/steps/test_canonical_repositories_steps.py` — BDD precedent that
    drives `SqlAlchemyUnitOfWork` with `session_factory` and a
    `_function_scoped_runner` asyncio runner.

## Plan of work

Proceed in stages with go/no-go validation at each boundary. Do not start
Stage B until Stage A is approved.

### Stage A — design review and approval (no code)

Confirm the design decisions in `Decision Log` with the community-of-experts
review (already initiated as part of producing this plan) and obtain user
approval of this ExecPlan. Output: an approved plan and, if the review surfaces
changes, a revised `Decision Log`. No code changes.

### Stage B — red tests first (Red)

Write the failing tests before any production code, smallest first, and run each
to confirm it fails for the intended reason.

1. Parametrize the port-contract suite. Refactor
   `tests/test_generation_run_port_contract.py` so its scenarios run against an
   adapter provided by a fixture, then add a second parameter: the
   PostgreSQL-backed adapter. The SQL parameter is skipped automatically when
   py-pglite is unavailable (reuse the `migrated_engine`/`session_factory`
   fixtures, which already self-skip). The SQL adapter parameter yields a thin
   test wrapper that, per call, opens a `SqlAlchemyUnitOfWork`, invokes the store
   method, and commits, so subsequent reads observe prior writes. Inject a fixed
   `time_provider` returning `NOW` so timestamp assertions match the in-memory
   parameter. Before the production adapter exists, the SQL parameter fails at
   import/fixture time — that is the expected red.
2. Add the event-ordering integration suite
   `tests/test_generation_run_store_integration.py` (DB-only) covering, against
   `migrated_engine`:
   - sequential `append_event` calls across one run yield `seq` `1, 2, 3, …`
     contiguous and strictly increasing;
   - `list_events(run_id)` returns events ascending by `seq`;
   - `list_events(run_id, after_seq=event_seq(k))` returns the half-open
     `(k, …]` tail via keyset pagination (`WHERE seq > k ORDER BY seq LIMIT n`);
     `limit` caps the result;
   - `list_runs` ordering is deterministic when several runs share one
     `created_at` (tie-broken by `id`), and status-filtered `offset`/`limit`
     applies after the filter (seed a handful of runs, assert order and paging);
   - appending to a terminal run raises `RunAlreadyTerminal`;
   - `list_events` and `append_event` raise `RunNotFound` for an unknown run;
   - two runs are isolated (sequences restart at 1 per run);
   - conflict-guard test (NOT a concurrency race; labelled as such): directly
     insert a row with a duplicate `(generation_run_id, seq)` to occupy the next
     slot, then assert the adapter's bounded retry advances past it, and that
     exhausting the retry budget surfaces `StaleEventSequence`; assert the
     `generation_event.append.conflicts` signal is emitted;
   - `create_run` idempotency: (a) a repeated `idempotency_key` returns the first
     run and ignores the second (first-write-wins), verified after `commit` in a
     fresh unit-of-work; (b) FORCE the conflict branch by pre-inserting a run
     with a given `idempotency_key`, then calling `create_run` with the same key
     and a different `run.id`, asserting the pre-existing run is returned (this
     exercises the `IntegrityError`→savepoint→re-`SELECT` path that py-pglite's
     single connection would otherwise never trigger);
   - `updated_at` advances on a raw SQL `UPDATE` (proves the DB trigger, not just
     client-side `onupdate`);
   - JSONB round-trip: `budget_snapshot`/`configuration`/`payload` survive a
     write/read cycle, and mutating a returned mapping does not change stored
     state.
3. Add a migration-drift expectation: confirm the existing
   `tests/test_migration_check.py` (or equivalent) covers drift; this suite will
   fail until the migration and models agree. If no such test asserts "no
   drift", add one.

Validation for Stage B: each new test fails for the intended reason
(`ImportError`/`AttributeError` for the missing adapter, or assertion/`no such
table` for the missing migration), proving the red state. Record the exact
failure messages in `Concrete steps`.

### Stage C — implementation (Green)

Make the smallest changes that turn the red tests green.

1. Enums in `episodic/canonical/storage/models_base.py`: add
   `GENERATION_RUN_STATUS`, `GENERATION_CHECKPOINT_STATUS`, and
   `GENERATION_CHECKPOINT_ACTION` `sa.Enum(...)` declarations bound to the domain
   enums `GenerationRunStatus`, `CheckpointStatus`, `CheckpointAction`, using the
   same `values_callable` lambda as the existing enums.
2. ORM models in a new `episodic/canonical/storage/generation_run_models.py`:
   - `GenerationRunRecord` (`__tablename__ = "generation_runs"`): client-assigned
     UUID PK; `episode_id` (UUID, FK to `episodes.id` `ON DELETE RESTRICT`);
     `source_bundle_id` (UUID); `actor` (`String(200)`); `status`
     (`GENERATION_RUN_STATUS`); `current_node` (`String(120)`, nullable);
     `budget_snapshot` and `configuration` (`JSONB`, non-null);
     `created_at`/`updated_at` (timezone-aware, `server_default=now()`,
     `updated_at` with client `onupdate` *and* a DB trigger — see step 7);
     `started_at`/`ended_at` (timezone-aware, nullable); `error_message` (`Text`,
     nullable); `idempotency_key` (`String(512)`, nullable, `unique=True`).
     Table args: composite indexes `(episode_id, created_at)` and
     `(episode_id, status, created_at)` for `list_runs`.
   - `GenerationEventRecord` (`__tablename__ = "generation_events"`): UUID PK;
     `generation_run_id` (UUID, FK to `generation_runs.id` `ON DELETE CASCADE`);
     `seq` (`BigInteger`, non-null — not `Integer`); `kind` (`String(120)`);
     `payload` (`JSONB`); `created_at`/`occurred_at` (timezone-aware); table args
     `UNIQUE(generation_run_id, seq)` and `CHECK (seq >= 1)` (names in
     `constraints.py`). The unique btree backs both the `MAX(seq)` reverse scan
     and `list_events` keyset pagination, so no separate FK index is added.
   - `GenerationCheckpointRecord` (`__tablename__ = "generation_checkpoints"`):
     UUID PK; `generation_run_id` (UUID, FK to `generation_runs.id`
     `ON DELETE CASCADE`, indexed); `node`/`prompt`; `options` (`JSONB`, storing
     the tuple as a list); `status` (`GENERATION_CHECKPOINT_STATUS`);
     `created_at`; `responded_at` (nullable); `responded_by` (`String(200)`,
     nullable); `response_action` (`GENERATION_CHECKPOINT_ACTION`, nullable);
     `response_payload` (`JSONB`, default empty object).
   Keep this module under 400 lines; if needed, split records into two modules.
3. Mappers in `episodic/canonical/storage/generation_run_mappers.py`: pure
   functions `_run_to_record`/`_run_from_record`,
   `_event_to_record`/`_event_from_record`,
   `_checkpoint_to_record`/`_checkpoint_from_record`. Deep-copy JSON mappings on
   read; convert `options` list ↔ tuple; pass enums through directly.
4. Adapter in `episodic/canonical/storage/generation_run_repositories.py`:
   `SqlAlchemyGenerationRunStore(_RepositoryBase)` implementing every
   `GenerationRunPort` method with the same observable behaviour as the in-memory
   store under single-writer-per-run. Accept an optional `time_provider` (default
   UTC now) for deterministic timestamps. Specifics:
   - `append_event`: confirm the run exists (`RunNotFound`) and is non-terminal
     (`RunAlreadyTerminal`); then, inside a `session.begin_nested()` savepoint,
     read `MAX(seq)` for the run, assign `seq = max + 1`, add the record, and
     `flush`. On an `IntegrityError` for the `(generation_run_id, seq)` unique
     constraint, release the savepoint, log/count the conflict
     (`generation_event.append.conflicts`), and retry (recompute `MAX`) up to 3
     attempts; raise `StaleEventSequence` only after the budget is exhausted.
   - `list_runs`: `ORDER BY created_at, id`; apply the optional status filter
     before `offset`/`limit`.
   - `list_events`: keyset pagination `WHERE seq > after_seq ORDER BY seq
     LIMIT limit` (`RunNotFound` when the run is absent).
   - `create_run`: insert; on an `IntegrityError` for the unique
     `idempotency_key`, roll back to a savepoint and `SELECT` the existing run by
     key (first-write-wins). A primary-key conflict with no idempotency key is a
     programming error and is allowed to surface (document this; the contract
     test only asserts keyed first-write-wins).
   - checkpoint transitions (`respond_to_checkpoint`, `time_out_checkpoint`,
     `cancel_checkpoint`): load the row, hydrate the domain `Checkpoint`, invoke
     its `.respond()/.time_out()/.cancel()` method (which raise
     `CheckpointAlreadyTerminal`), and persist the result — do not re-implement
     the terminal check in SQL. `create_checkpoint` checks run existence and
     raises `RunNotFound` rather than relying solely on the FK error.
   Reuse `episodic.orchestration._types._log_event` event names where the
   in-memory store logs, for parity (this private-symbol reuse already has
   precedent in `workflow_checkpoints.py`; a future refactor may promote it to a
   shared logging utility).
5. UoW wiring in `episodic/canonical/storage/uow.py`: import the new store, add
   `self.generation_runs = SqlAlchemyGenerationRunStore(self._session, ...)` in
   `__aenter__`, and document the attribute in the class docstring.
6. Constraint-name constants in `episodic/canonical/constraints.py`:
   `UQ_GENERATION_EVENT_SEQ`, `CK_GENERATION_EVENT_SEQ_POSITIVE`,
   `UQ_GENERATION_RUN_IDEMPOTENCY_KEY` (as needed to keep migration and models in
   sync).
7. Alembic migration
   `alembic/versions/20260615_000010_add_generation_run_tables.py`
   (`revision = "20260615_000010"`, `down_revision = "20260601_000009"`):
   create the three enums (`create_type=False`, `.create(bind, checkfirst=True)`),
   then `op.create_table` for the three tables with columns, constraints, and
   indexes identical to the models — `seq` as `sa.BigInteger`, FKs with the
   `ondelete` clauses from the `Decision Log` (events/checkpoints CASCADE,
   episode RESTRICT), the `UNIQUE(generation_run_id, seq)` and `CHECK (seq >= 1)`
   on events, the `unique` `idempotency_key` on runs, and the composite indexes
   `(episode_id, created_at)` and `(episode_id, status, created_at)` on runs.
   Add the `BEFORE UPDATE` trigger and its function for `generation_runs.updated_at`,
   following the `workflow_checkpoints` precedent verbatim (the trigger keeps the
   timestamp correct for raw SQL updates and is invisible to `compare_metadata`,
   so it does not cause drift). Provide a `downgrade()` that drops the trigger and
   function, then the tables and their indexes, then the enums, in reverse order.

Validation for Stage C: run the focused failing tests from Stage B and confirm
they pass; then `make check-migrations` reports no drift.

### Stage D — refactor, documentation, and cleanup

1. Refactor for clarity and the 400-line limit; ensure mappers/models/adapter
   are cohesive and free of duplication with the in-memory store (extract shared
   pure helpers only if it does not couple the adapter to the in-memory module).
2. Documentation:
   - Add `docs/adr/adr-016-generation-run-persistence.md` recording the table
     schema, the per-run `MAX(seq)+1`-under-unique-constraint event-ordering
     decision with bounded retry (and the global-sequence and counter-column
     rejection rationale), the `BIGINT` seq choice, the FK on-delete semantics,
     the idempotency-key-column decision, and the `generation_checkpoints` naming
     decision. Include a short disambiguation table distinguishing the
     user-facing review checkpoint (`generation_checkpoints`, this slice) from
     the LangGraph orchestration durability checkpoint (`workflow_checkpoints`,
     ADR-007), since "generation checkpoint" is otherwise overloaded across the
     two ADRs. Note that `MAX(seq)+1` and `COUNT(*)+1` coincide only because the
     log is append-only with no deletes. Reference the ADR from
     `docs/episodic-podcast-generation-system-design.md` (Data Model and Storage)
     and add the three tables to that section.
   - Update `docs/developers-guide.md` "Canonical content persistence" with the
     new `uow.generation_runs` store and event-ordering semantics, and
     "Database migrations" / "Database testing with py-pglite" if the testing
     approach gains anything novel (note the single-connection limitation and
     the single-writer-per-run invariant).
   - `docs/users-guide.md`: this slice adds no public API or user-visible
     behaviour (REST endpoints arrive in 2.6.3). Confirm the existing
     "Generation runs and review checkpoints" section remains accurate; if it
     implies durability that did not previously exist, adjust wording. Record in
     `Decision Log` if no change is required.
   - Update `docs/contents.md` index for the new ADR.
3. Mark roadmap item 2.6.2 as done in `docs/roadmap.md` only after all gates and
   the CodeRabbit pass are clear.
4. Run the full gate sequence and a `coderabbit review --agent` pass; clear all
   concerns before declaring the slice complete.
5. File a tracked follow-up issue (do not leave it as a vague "deferred") for a
   true multi-writer concurrency test of `append_event` against a real
   PostgreSQL instance in a dedicated CI tier, since py-pglite's single
   connection cannot exercise it. Link the issue from ADR-016 and from this
   plan's `Risks`.

## Concrete steps

Run all commands from the repository root
`/home/leynos/.lody/repos/github---leynos---episodic/worktrees/dddb44f8-8c58-4e00-bc69-ac97035df7d1`.
Tee long outputs to a per-action log per the global command guidance, e.g.
`make test 2>&1 | tee "/tmp/test-episodic-$(git branch --show-current).out"`.

1. Confirm the single migration head before adding a revision:

   ```bash
   uv run alembic heads
   ```

   Expected: a single head `20260601_000009 (head)`.

2. Stage B red runs (examples; exact node IDs depend on final test names):

   ```bash
   uv run pytest -q tests/test_generation_run_port_contract.py
   uv run pytest -q tests/test_generation_run_store_integration.py
   ```

   Expected before Stage C: collection/setup errors referencing the missing
   `SqlAlchemyGenerationRunStore`, or `ProgrammingError`/"relation
   \"generation_events\" does not exist" against the migrated engine.

3. Stage C green runs: rerun the same nodes and expect passes; then:

   ```bash
   make check-migrations 2>&1 | tee "/tmp/checkmigrations-episodic-$(git branch --show-current).out"
   ```

   Expected: no drift detected (exit 0).

4. Full gate sequence (run sequentially, never in parallel, per global
   guidance):

   ```bash
   make check-fmt 2>&1 | tee "/tmp/checkfmt-episodic-$(git branch --show-current).out"
   make typecheck 2>&1 | tee "/tmp/typecheck-episodic-$(git branch --show-current).out"
   make lint      2>&1 | tee "/tmp/lint-episodic-$(git branch --show-current).out"
   make test      2>&1 | tee "/tmp/test-episodic-$(git branch --show-current).out"
   make markdownlint 2>&1 | tee "/tmp/mdlint-episodic-$(git branch --show-current).out"
   make nixie     2>&1 | tee "/tmp/nixie-episodic-$(git branch --show-current).out"
   ```

   `make lint` includes `check-architecture` (Hecate). `make test` includes the
   migration-applied py-pglite suites.

5. CodeRabbit pass once deterministic gates are green:

   ```bash
   coderabbit review --agent 2>&1 | tee "/tmp/coderabbit-episodic-$(git branch --show-current).out"
   ```

   Clear every concern before moving on.

## Validation and acceptance

Acceptance is behavioural and observable:

1. Port-contract equivalence: the parametrized
   `tests/test_generation_run_port_contract.py` passes for both the in-memory and
   the PostgreSQL adapters. Red before Stage C (SQL parameter errors on the
   missing adapter), green after.
2. Event ordering (sequential): `tests/test_generation_run_store_integration.py`
   passes. The key assertion: appending N events to a run *in sequence* yields
   `seq` values exactly `1..N` contiguous and strictly increasing, and
   `list_events` returns them in ascending order with correct `after_seq`
   half-open keyset paging. This proves sequential contiguity and paging; it does
   NOT prove concurrent-write correctness (py-pglite is single-connection — see
   `Risks` and the tracked follow-up). The conflict-guard test proves the bounded
   retry advances past an occupied slot and that an exhausted budget raises
   `StaleEventSequence`. Red before the migration/adapter exist; green after.
3. No schema drift: `make check-migrations` exits 0.
4. Architecture: `make lint` (Hecate) confirms the new storage modules are
   outbound adapters that import domain/ports but are not imported by them.

Red-Green-Refactor evidence to capture in `Artifacts and notes` as work proceeds:

- Red: the failing command and its message (missing adapter / missing relation).
- Green: the same command passing after the minimal implementation.
- Refactor: gates rerun and still green after cleanup.

Quality criteria ("done"):

- Tests: all new unit, integration, BDD, and property tests pass under
  `make test`; existing suites remain green.
- Lint/typecheck/format: `make check-fmt`, `make typecheck`, `make lint`,
  `make markdownlint`, `make nixie` all pass.
- Migrations: `make check-migrations` reports no drift.
- Review: `coderabbit review --agent` reports no outstanding concerns.

Quality method: the Makefile gates above, run sequentially, plus the CodeRabbit
pass, all after each major milestone (end of Stage C and end of Stage D).

Test-rigour notes (per the task's testing guidance):

- Unit (`pytest`): mappers, sequence allocation, error mapping.
- Behavioural (`pytest-bdd`): durable event-ordering scenario.
- Property (`hypothesis`): the monotonic-contiguous-sequence invariant and
  `list_events` paging round-trip — exercised primarily at the in-memory level
  for speed (extend `tests/test_generation_run_properties.py`), with a small
  DB-backed example budget (low `max_examples`) to confirm the adapter upholds
  the same invariant. This is justified because the change introduces an
  invariant over orderings of appended events.
- Snapshot (`syrupy`): not applicable. This slice adds persistence, not a new
  multivariant serialized output format; the existing domain snapshots in
  `tests/test_generation_run_domain.py` already cover the domain shape. Recorded
  here so the omission is deliberate.
- Property/contract proof tools (`proptest`, `kani`, `verus`): not applicable —
  this is Python, and the relevant invariant is covered by Hypothesis above.
- Inference simulation (`vidai-mock`): not applicable for this slice (no
  inference is performed); see `Constraints`.

## Idempotence and recovery

- The Alembic migration is forward/backward symmetric: `downgrade()` drops the
  three tables, their indexes, and the three enums, returning the schema to head
  `20260601_000009`. Re-running `upgrade()` after a clean `downgrade()` is safe.
- Test fixtures drop and recreate the public schema per run, so tests are
  re-runnable without manual cleanup.
- If `make check-migrations` reports drift, reconcile the migration to the models
  (the models are authoritative for the desired schema) and re-run; do not edit
  the autogenerated comparison.
- Commits are small and per-stage, enabling `git` rollback. Commit only when the
  relevant gates pass.

## Artifacts and notes

Populate during implementation:

- Red/green command transcripts (kept concise; just enough to prove the
  transition).
- The final `alembic heads` output showing a single head after the new revision
  is added.
- The tracked follow-up issue number for the real-PostgreSQL concurrency test.
- (Only if a stakeholder-facing BDD scenario is ultimately warranted) its
  `Feature`/`Scenario` text; by default none is added — see `Decision Log`.

## Interfaces and dependencies

End-state interfaces (stable names and paths):

- `episodic/canonical/storage/generation_run_models.py`:
  `GenerationRunRecord`, `GenerationEventRecord` (with a `BIGINT` `seq` column),
  `GenerationCheckpointRecord` (subclasses of
  `episodic.canonical.storage.models_base.Base`). The 2.6.1 `EventSeq` NewType
  (a Python `int`) is unchanged; only the persisted column widens to `BIGINT`.
- `episodic/canonical/storage/generation_run_mappers.py`: module-private pure
  mapper functions between the records above and the 2.6.1 domain dataclasses.
- `episodic/canonical/storage/generation_run_repositories.py`:

  ```python
  @dc.dataclass(slots=True)
  class SqlAlchemyGenerationRunStore(_RepositoryBase):
      """PostgreSQL-backed composite generation-run port adapter."""

      # Satisfies episodic.canonical.generation_run_ports.GenerationRunPort:
      #   create_run, get_run, list_runs, update_run_status,
      #   append_event, list_events,
      #   create_checkpoint, get_checkpoint, respond_to_checkpoint,
      #   time_out_checkpoint, cancel_checkpoint
  ```

- `episodic/canonical/storage/models_base.py`: new `GENERATION_RUN_STATUS`,
  `GENERATION_CHECKPOINT_STATUS`, `GENERATION_CHECKPOINT_ACTION` enum objects.
- `episodic/canonical/storage/uow.py`: `SqlAlchemyUnitOfWork.generation_runs:
  SqlAlchemyGenerationRunStore`, satisfying `GenerationRunPort`.
- `alembic/versions/20260615_000010_add_generation_run_tables.py`:
  `revision = "20260615_000010"`, `down_revision = "20260601_000009"`.

Dependencies (already present; no new ones expected): SQLAlchemy 2.0.x async,
asyncpg, Alembic 1.13.x, py-pglite (test), pytest-bdd (test), hypothesis (test).

## Revision note

- 2026-06-15 — Revised after a Logisphere community-of-experts design review
  (Telefono, Pandalump, Buzzy Bee, Doggylump, Wafflecat, Dinolump). Verdict:
  proceed with conditions. Changes incorporated:
  - `append_event` now performs a bounded retry inside a `begin_nested()`
    savepoint with a conflict metric, instead of escalating on the first unique
    violation (prevents silently dropped events under contention).
  - `generation_events.seq` widened to `BIGINT`.
  - Added composite indexes `(episode_id, created_at)` and
    `(episode_id, status, created_at)`; specified deterministic `list_runs`
    ordering `(created_at, id)` with post-filter `offset`/`limit`.
  - Specified FK `ON DELETE` semantics (events/checkpoints CASCADE, episode
    RESTRICT) and a DB `updated_at` trigger matching the `workflow_checkpoints`
    precedent.
  - Qualified the behavioural-equivalence constraint to the single-writer case
    and documented the concurrency divergence in `Surprises & Discoveries`;
    reworded the event-ordering acceptance to a sequential claim.
  - Checkpoint transitions hydrate the domain object and reuse its methods;
    `create_checkpoint` checks run existence explicitly.
  - Forced the `create_run` idempotency conflict branch in tests via a
    pre-inserted row (py-pglite would otherwise never trigger it).
  - Dropped the redundant `generation_run_persistence.feature` BDD scenario in
    favour of the example-based integration suite.
  - Added an ADR-016 disambiguation table (`generation_checkpoints` vs
    `workflow_checkpoints`) and the `MAX+1 == COUNT+1` append-only note, and a
    tracked follow-up issue for a real-PostgreSQL concurrency test.
  These refinements affect Stage C (models, adapter, migration) and Stage B/D
  (tests and documentation); the overall scope and tolerances are unchanged.
