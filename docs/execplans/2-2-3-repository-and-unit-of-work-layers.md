# Implement the repository and unit-of-work layers over Postgres with integration tests

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

Status: COMPLETE

## Purpose and big picture

After this change, the canonical persistence layer has comprehensive
integration tests covering every repository, the unit-of-work transaction
lifecycle, and database-level constraint enforcement. Developers can trust that
the repository and unit-of-work (UoW) abstractions behave correctly under both
happy-path and error conditions, and that the Postgres adapter layer faithfully
implements the Protocol-based port contracts.

Success is observable when:

1. Running `make test` passes all existing tests plus 8 new unit tests and 3
   new Behaviour-Driven Development (BDD) scenarios.
2. Each repository type (SeriesProfile, TeiHeader, Episode, IngestionJob,
   SourceDocument, ApprovalEvent) has at least one isolated round-trip test
   validating add-then-get persistence.
3. Unit-of-work rollback behaviour is proven: explicit `rollback()` calls and
   unhandled exceptions both discard uncommitted changes.
4. Database-level constraints (unique slugs, foreign-key integrity, weight
   CHECK constraint) are validated under test.
5. Empty-result paths (fetching a non-existent entity, listing events for an
   absent episode) return `None` or `[]` respectively.
6. The system design document records the repository and UoW implementation
   decisions.
7. The developers' guide documents repository usage patterns and UoW
   transaction semantics.
8. The roadmap marks item 2.2.3 as done.

## Constraints

- No changes to existing production code. The repository, UoW, domain, model,
  mapper, and service modules (`episodic/canonical/ports.py`,
  `episodic/canonical/storage/repositories.py`,
  `episodic/canonical/storage/uow.py`, `episodic/canonical/domain.py`,
  `episodic/canonical/storage/models.py`,
  `episodic/canonical/storage/mappers.py`, `episodic/canonical/services.py`)
  must not be modified. The implementation is complete; this plan adds tests
  and documentation only.
- All existing tests must continue to pass. No regressions in `make test`,
  `make lint`, `make check-fmt`, or `make typecheck`.
- No new external dependencies may be added.
- New tests must follow the established patterns in
  `tests/test_canonical_storage.py` and
  `tests/steps/test_canonical_ingestion_steps.py`.
- Logging must use `femtologging` via the existing `episodic.logging` wrapper
  if any new production code were to be added (not expected for this plan).
- Follow the commit message format in `AGENTS.md`: imperative mood, subject no
  more than 50 characters, body wrapped at 72 characters, Markdown formatting.
- Documentation must follow the style guide in
  `docs/documentation-style-guide.md`: British English (Oxford style), sentence
  case headings, 80-column wrapping, dashes for list bullets.

## Tolerances (exception triggers)

- Scope: if implementation requires changes to more than 10 files or 500 lines
  of code (net), stop and escalate.
- Interface: if the `episodic.canonical.storage` public API (`__init__.py`
  `__all__`) must change, stop and escalate.
- Dependencies: if a new external dependency is required, stop and escalate.
- Iterations: if tests still fail after 3 attempts at fixing, stop and
  escalate.
- Production code: if any production module listed under Constraints must be
  modified to make tests pass, stop and escalate.

## Risks

- Risk: `IntegrityError` match patterns in `pytest.raises` may not match the
  exact error text produced by py-pglite's asyncpg driver for CHECK constraint
  and foreign-key violations. Severity: low. Likelihood: low. Mitigation: The
  existing test at `tests/test_canonical_storage.py:131` uses
  `match=r"unique|UNIQUE|duplicate"` as a precedent. Use similarly broad
  patterns (`check|CHECK|ck_source_documents_weight` for CHECK constraints,
  `foreign key|FOREIGN KEY|violates` for FK constraints). Adjust if the first
  test run reveals different error text.

- Risk: BDD step definitions may conflict with existing step definitions if
  step text overlaps with `tests/steps/test_canonical_ingestion_steps.py`.
  Severity: low. Likelihood: low. Mitigation: Use distinct step text that does
  not overlap with the canonical ingestion steps.

## Progress

- [x] (2026-02-11 01:00Z) Stage A: Write the ExecPlan document.
- [x] (2026-02-11 01:00Z) Stage B: Add unit tests for coverage gaps.
- [x] (2026-02-11 01:00Z) Stage C: Add BDD feature file and step definitions.
- [x] (2026-02-11 01:00Z) Stage D: Update documentation (design doc,
  developers' guide, users' guide, roadmap).
- [x] (2026-02-11 01:00Z) Stage E: Run all quality gates and capture logs.

## Surprises & discoveries

- Observation: Tests that add child entities (episodes, ingestion jobs) in the
  same UoW commit as their parent entities (series profiles, TEI headers) fail
  with foreign-key violations when `autoflush=False` is configured on the
  session factory. SQLAlchemy does not guarantee INSERT ordering within a
  single flush, so parent rows may not be visible when child INSERTs execute.
  Evidence: `test_ingestion_job_round_trip` and the BDD "weight constraint"
  scenario both failed with `ForeignKeyViolation` until parent entities were
  committed in a separate UoW before adding children. Impact: Tests that build
  entity dependency graphs must commit parent entities before adding children,
  or use `flush()` to enforce ordering within a single transaction (as the
  existing `ingest_sources` service does).

- Observation: The ruff lint rule PT012 rejects `pytest.raises()` blocks
  containing multiple statements. The initial
  `test_uow_rolls_back_on_exception` test wrapped the entire UoW context
  (including `add()` and `raise`) inside `pytest.raises(RuntimeError)`, which
  triggered PT012. Evidence: `make lint` failed with PT012 on the first run.
  Impact: Refactored the test to extract the UoW logic into a helper coroutine,
  with `pytest.raises` wrapping only the call to that coroutine.

- Observation: The `make test` target uses `pytest -n auto` which spawns 8
  parallel workers, each starting its own py-pglite Postgres instance. This
  overwhelms the environment and causes intermittent `PGlite process died` and
  `connection refused` errors. This is a pre-existing issue affecting all
  py-pglite-backed tests, not specific to the new tests. Evidence: Running only
  the pre-existing tests with `-n auto` also produced errors. All 28 tests pass
  reliably with `-n 1`. Impact: No action taken in this plan. The flakiness
  should be addressed in a future task by limiting parallelism for py-pglite
  tests or using session-scoped fixtures.

## Decision log

- Decision: Focus this plan on closing test coverage and documentation gaps
  rather than modifying production code. Rationale: The repository and
  unit-of-work implementation was delivered as part of roadmap items 2.2.1 and
  2.2.2. All six repository classes, the `SqlAlchemyUnitOfWork`, port
  protocols, domain entities, ORM models, mappers, and the `ingest_sources`
  domain service are fully implemented and functional. Three unit tests and one
  BDD scenario already exist. What remained was comprehensive integration tests
  and documentation to satisfy the "with integration tests" requirement of
  2.2.3. Date/Author: 2026-02-11, plan phase.

- Decision: Add eight targeted unit tests rather than restructuring existing
  tests. Rationale: The existing three tests cover persistence with header
  linkage, unique slug constraint, and getter/list methods. The gaps are
  rollback semantics, constraint enforcement (weight CHECK and FK), individual
  repository round-trips (TeiHeader, IngestionJob), and empty-result paths.
  Eight focused tests close all gaps without redundancy. Date/Author:
  2026-02-11, plan phase.

- Decision: Add three BDD scenarios in a separate feature file rather than
  extending the existing `canonical_ingestion.feature`. Rationale: The existing
  BDD feature tests the ingestion workflow end-to-end. The new scenarios test
  repository and UoW semantics directly (round-trip persistence, rollback
  behaviour, constraint enforcement). These are distinct behavioural concerns
  and belong in their own feature file. Date/Author: 2026-02-11, plan phase.

- Decision: Commit parent entities in a separate UoW before adding child
  entities in tests, rather than using `flush()` within a single UoW.
  Rationale: With `autoflush=False` on the session factory, SQLAlchemy does not
  guarantee INSERT ordering within a single flush. Parent FK references must be
  visible before child rows are inserted. Splitting into separate commits is
  the simplest and most reliable approach for tests, consistent with the
  existing `test_can_persist_episode_with_header` pattern. Date/Author:
  2026-02-11, implementation phase.

## Outcomes & retrospective

All stages completed successfully. The canonical persistence layer now has
comprehensive integration tests covering every repository, the unit-of-work
transaction lifecycle, and database-level constraint enforcement.

Files created (3):

- `docs/execplans/2-2-3-repository-and-unit-of-work-layers.md` -- this
  ExecPlan.
- `tests/features/canonical_repositories.feature` -- 3 BDD scenarios.
- `tests/steps/test_canonical_repositories_steps.py` -- BDD step definitions.

Files modified (5):

- `tests/test_canonical_storage.py` -- 8 new unit tests added.
- `docs/episodic-podcast-generation-system-design.md` -- repository and UoW
  implementation subsection added.
- `docs/developers-guide.md` -- repository usage patterns and UoW transaction
  semantics documented.
- `docs/users-guide.md` -- repository integrity validation bullet added.
- `docs/roadmap.md` -- item 2.2.3 marked as done.

Quality gate results:

- `make check-fmt` -- passed.
- `make typecheck` -- passed (ty 0.0.16, all checks passed).
- `make lint` -- passed (ruff, all checks passed).
- `make test` (with `-n 1`) -- 28 passed, 2 skipped.
- `make check-migrations` -- passed (no schema drift).

The main surprise was the FK ordering issue: tests that add parent and child
entities in the same UoW commit fail when `autoflush=False` because SQLAlchemy
does not guarantee INSERT ordering. The fix was to commit parent entities
separately before adding children, consistent with how the existing
`ingest_sources` service uses `flush()` for the same purpose.

## Context and orientation

The Episodic project is a podcast generation platform following hexagonal
architecture. The canonical content persistence layer is the outbound adapter
that stores domain entities in Postgres via SQLAlchemy. The relevant files and
their roles are:

- `episodic/canonical/ports.py` -- Protocol-based interfaces defining six
  repository contracts (`SeriesProfileRepository`, `TeiHeaderRepository`,
  `EpisodeRepository`, `IngestionJobRepository`, `SourceDocumentRepository`,
  `ApprovalEventRepository`) and the `CanonicalUnitOfWork` boundary with
  `commit()`, `flush()`, and `rollback()` methods.
- `episodic/canonical/storage/repositories.py` -- SQLAlchemy implementations of
  all six repositories. Each extends `_RepositoryBase` (which provides a shared
  `_get_one_or_none` helper) and the corresponding Protocol. Repositories
  translate between domain entities and ORM records.
- `episodic/canonical/storage/uow.py` -- `SqlAlchemyUnitOfWork` implementation.
  Creates a fresh `AsyncSession` on `__aenter__`, instantiates all six
  repositories bound to that session, rolls back on exception in `__aexit__`,
  and delegates `commit()`, `flush()`, and `rollback()` to the session.
- `episodic/canonical/domain.py` -- Frozen dataclasses (`SeriesProfile`,
  `TeiHeader`, `CanonicalEpisode`, `IngestionJob`, `SourceDocument`,
  `ApprovalEvent`) and enums (`EpisodeStatus`, `ApprovalState`,
  `IngestionStatus`).
- `episodic/canonical/storage/models.py` -- SQLAlchemy ORM models
  (`SeriesProfileRecord`, `TeiHeaderRecord`, `EpisodeRecord`,
  `IngestionJobRecord`, `SourceDocumentRecord`, `ApprovalEventRecord`) with
  `Base(DeclarativeBase)`. Notable constraints: unique slug on
  `series_profiles`, CHECK constraint `ck_source_documents_weight` enforcing
  `weight >= 0 AND weight <= 1`, foreign keys from episodes to series profiles
  and TEI headers, from source documents to ingestion jobs and episodes, and
  from approval events to episodes.
- `episodic/canonical/storage/mappers.py` -- Functions that convert ORM records
  to domain entities (for example, `_series_profile_from_record`).
- `episodic/canonical/services.py` -- Domain service `ingest_sources()` that
  orchestrates creating TEI headers, episodes, ingestion jobs, source
  documents, and approval events within a UoW transaction.
- `tests/test_canonical_storage.py` -- Existing unit tests: slug uniqueness,
  episode persistence with header linkage, getter and list round-trips.
- `tests/features/canonical_ingestion.feature` -- Existing BDD scenario
  exercising the full ingestion workflow.
- `tests/steps/test_canonical_ingestion_steps.py` -- Step definitions for the
  ingestion scenario, following the `_run_async_step` pattern with
  `_function_scoped_runner`.
- `tests/conftest.py` -- Shared fixtures: `pglite_engine` (py-pglite
  AsyncEngine), `migrated_engine` (engine with Alembic migrations applied),
  `session_factory` (async_sessionmaker), `pglite_session`, and
  `_function_scoped_runner` (asyncio.Runner for sync BDD steps).

Test isolation: `pglite_engine` depends on `tmp_path` which is function-scoped,
so each test function receives a separate in-process Postgres database. This
ensures test independence.

## Plan of work

The work proceeds in five stages, each ending with validation.

### Stage A: ExecPlan document

Write this document to
`docs/execplans/2-2-3-repository-and-unit-of-work-layers.md`.

### Stage B: Unit tests for coverage gaps

Modify `tests/test_canonical_storage.py` to add eight new tests. All tests use
the existing `session_factory` fixture (which provides an async_sessionmaker
bound to a migrated py-pglite engine) and the `SqlAlchemyUnitOfWork` class.

The eight tests and the gaps they close:

1. `test_get_returns_none_for_missing_entity` -- calls
   `uow.series_profiles.get(uuid.uuid4())` and asserts `None`. Validates the
   `_get_one_or_none` helper for the absent case.

2. `test_uow_rollback_discards_uncommitted_changes` -- adds a `SeriesProfile`,
   calls `uow.rollback()`, then opens a new UoW and verifies the profile is
   absent. Validates explicit rollback.

3. `test_uow_rolls_back_on_exception` -- adds a `SeriesProfile` inside a UoW
   context, raises `RuntimeError`, then verifies the profile is absent.
   Validates the `__aexit__` rollback path.

4. `test_source_document_weight_check_constraint` -- sets up the full entity
   graph (series, header, episode, job) using `_episode_fixture`, then adds a
   `SourceDocument` with `weight=1.5` and expects `IntegrityError` on commit.
   Validates the `ck_source_documents_weight` CHECK constraint.

5. `test_approval_event_fk_constraint` -- adds an `ApprovalEvent` with a
   random (non-existent) `episode_id` and expects `IntegrityError` on commit.
   Validates foreign-key enforcement.

6. `test_tei_header_round_trip` -- adds a `TeiHeader` via the repository,
   commits, fetches by ID, and verifies title, payload, and raw_xml match.
   Isolated round-trip for `SqlAlchemyTeiHeaderRepository`.

7. `test_ingestion_job_round_trip` -- sets up series, header, episode
   dependencies, adds an `IngestionJob`, commits, fetches by ID, and verifies
   id and status match. Isolated round-trip for
   `SqlAlchemyIngestionJobRepository`.

8. `test_list_for_episode_returns_empty_for_unknown` -- calls
   `uow.approval_events.list_for_episode(uuid.uuid4())` and asserts the result
   is `[]`. Validates the list path for the empty case.

Validation: run `make test` and confirm all 8 new tests plus all existing tests
pass.

### Stage C: BDD feature file and step definitions

Create `tests/features/canonical_repositories.feature` with three scenarios:

1. "Repository round-trip persists and retrieves a series profile" -- adds a
   series profile, fetches it by identifier, and verifies the match.

2. "Rolled-back changes are not persisted" -- adds a series profile but rolls
   back the transaction, then verifies the profile is absent.

3. "Weight constraint rejects out-of-range values" -- sets up the entity
   dependency graph, adds a source document with `weight=1.5`, and verifies an
   integrity error on commit.

Create `tests/steps/test_canonical_repositories_steps.py` with step definitions
following the pattern from `tests/steps/test_canonical_ingestion_steps.py`.

Validation: run `make test` and confirm all 3 new BDD scenarios pass.

### Stage D: Documentation updates

1. `docs/episodic-podcast-generation-system-design.md` -- add a subsection
   "Repository and unit-of-work implementation" after the canonical content
   schema decisions section (after line 897, before the Change Management
   section), documenting that the repository and UoW layers are implemented as
   async SQLAlchemy adapters satisfying Protocol-based ports, with integration
   tests run against in-process Postgres via py-pglite.

2. `docs/developers-guide.md` -- expand the "Canonical content persistence"
   section (currently lines 80-91) with repository usage patterns, UoW
   transaction semantics (commit, rollback, flush, exception handling), and a
   code example.

3. `docs/users-guide.md` -- add a bullet under the "Content Creation" section
   noting that repository and transactional integrity are validated in the test
   suite.

4. `docs/roadmap.md` -- change line 64 from `- [ ] 2.2.3.` to `- [x] 2.2.3.`

Validation: run `make markdownlint` and confirm no errors.

### Stage E: Quality gates

Run all required quality gates:

    set -o pipefail; timeout 300 make fmt 2>&1 | tee /tmp/make-fmt.log
    set -o pipefail; timeout 300 make check-fmt 2>&1 | tee /tmp/make-check-fmt.log
    set -o pipefail; timeout 300 make typecheck 2>&1 | tee /tmp/make-typecheck.log
    set -o pipefail; timeout 300 make lint 2>&1 | tee /tmp/make-lint.log
    set -o pipefail; timeout 300 make test 2>&1 | tee /tmp/make-test.log
    set -o pipefail; timeout 300 make check-migrations 2>&1 | tee /tmp/make-check-migrations.log

## Concrete steps

### Step 1: Write the ExecPlan

Write this document to
`docs/execplans/2-2-3-repository-and-unit-of-work-layers.md`.

### Step 2: Add unit tests

Edit `tests/test_canonical_storage.py` and append the eight test functions
described in Stage B. Each test is a standalone `@pytest.mark.asyncio` async
function that receives `session_factory` as a parameter.

### Step 3: Create the BDD feature file

Create `tests/features/canonical_repositories.feature` with the three scenarios
described in Stage C.

### Step 4: Create the BDD step definitions

Create `tests/steps/test_canonical_repositories_steps.py` with step definitions
for the three scenarios. Follow the `_run_async_step` +
`_function_scoped_runner` pattern from
`tests/steps/test_canonical_ingestion_steps.py`.

### Step 5: Update system design document

Edit `docs/episodic-podcast-generation-system-design.md` to add the
repository/UoW implementation subsection after line 897.

### Step 6: Update developers' guide

Edit `docs/developers-guide.md` to expand the "Canonical content persistence"
section.

### Step 7: Update users' guide

Edit `docs/users-guide.md` to add a bullet about repository integrity
validation.

### Step 8: Update roadmap

Edit `docs/roadmap.md` to mark 2.2.3 as done.

### Step 9: Run formatting

    set -o pipefail; timeout 300 make fmt 2>&1 | tee /tmp/make-fmt.log

### Step 10: Run quality gates

    set -o pipefail; timeout 300 make check-fmt 2>&1 | tee /tmp/make-check-fmt.log
    set -o pipefail; timeout 300 make typecheck 2>&1 | tee /tmp/make-typecheck.log
    set -o pipefail; timeout 300 make lint 2>&1 | tee /tmp/make-lint.log
    set -o pipefail; timeout 300 make test 2>&1 | tee /tmp/make-test.log
    set -o pipefail; timeout 300 make check-migrations 2>&1 | tee /tmp/make-check-migrations.log

## Validation and acceptance

Acceptance requires all of the following:

- `make test` passes all existing and new tests (expected: 8 new unit tests +
  3 new BDD scenarios + all existing tests).
- `make check-fmt` passes.
- `make typecheck` passes.
- `make lint` passes.
- `make check-migrations` passes (no schema drift; no model changes in this
  plan).
- Unit tests cover: rollback semantics (explicit and exception-triggered),
  constraint enforcement (unique slug already covered, weight CHECK, FK),
  individual repository round-trips (TeiHeader, IngestionJob), and empty-result
  paths.
- BDD scenarios cover: repository persistence round-trip, rollback behaviour,
  weight constraint enforcement.
- `docs/episodic-podcast-generation-system-design.md` documents the repository
  and UoW implementation decisions.
- `docs/developers-guide.md` documents repository usage patterns and UoW
  transaction semantics.
- `docs/users-guide.md` notes repository integrity validation.
- `docs/roadmap.md` marks 2.2.3 as done.

Quality method:

    set -o pipefail; timeout 300 make check-fmt 2>&1 | tee /tmp/make-check-fmt.log
    set -o pipefail; timeout 300 make typecheck 2>&1 | tee /tmp/make-typecheck.log
    set -o pipefail; timeout 300 make lint 2>&1 | tee /tmp/make-lint.log
    set -o pipefail; timeout 300 make test 2>&1 | tee /tmp/make-test.log
    set -o pipefail; timeout 300 make check-migrations 2>&1 | tee /tmp/make-check-migrations.log

## Idempotence and recovery

All steps are re-runnable. Tests use function-scoped py-pglite databases that
are discarded after each test. If tests fail, fix the issue and rerun
`make test`. Log files in `/tmp` are overwritten on each run.

Documentation edits are idempotent and may be repeated safely.

## Artifacts and notes

- `/tmp/make-fmt.log` -- formatting output.
- `/tmp/make-check-fmt.log` -- formatting check output.
- `/tmp/make-typecheck.log` -- type check output.
- `/tmp/make-lint.log` -- lint output.
- `/tmp/make-test.log` -- test output.
- `/tmp/make-check-migrations.log` -- migration drift check output.

## Interfaces and dependencies

No new interfaces or dependencies are introduced. This plan adds tests and
documentation for the existing interfaces:

- `episodic.canonical.ports.CanonicalUnitOfWork` -- Protocol defining
  `commit()`, `flush()`, `rollback()`, `__aenter__()`, `__aexit__()`, and six
  repository attributes.
- `episodic.canonical.ports.SeriesProfileRepository` -- Protocol with `add()`,
  `get()`, `get_by_slug()`.
- `episodic.canonical.ports.TeiHeaderRepository` -- Protocol with `add()`,
  `get()`.
- `episodic.canonical.ports.EpisodeRepository` -- Protocol with `add()`,
  `get()`.
- `episodic.canonical.ports.IngestionJobRepository` -- Protocol with `add()`,
  `get()`.
- `episodic.canonical.ports.SourceDocumentRepository` -- Protocol with `add()`,
  `list_for_job()`.
- `episodic.canonical.ports.ApprovalEventRepository` -- Protocol with `add()`,
  `list_for_episode()`.
- `episodic.canonical.storage.SqlAlchemyUnitOfWork` -- Concrete adapter
  implementing `CanonicalUnitOfWork` over async SQLAlchemy sessions.

Existing dependencies used (no new additions):

- `sqlalchemy` (`>=2.0.34,<3.0.0`) -- ORM and async engine.
- `py-pglite[asyncpg]` -- In-process Postgres for tests.
- `pytest`, `pytest-asyncio`, `pytest-bdd` -- Test framework.

## Revision note

Initial plan created on 2026-02-11 to scope the integration tests and
documentation for roadmap item 2.2.3.

Revised on 2026-02-11 to capture implementation outcomes, FK ordering surprise,
PT012 lint fix, py-pglite parallelism flakiness, and completed quality gate
results.
