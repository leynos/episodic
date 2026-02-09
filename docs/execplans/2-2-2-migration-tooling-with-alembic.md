# Introduce migration tooling with Alembic, wired into CI to block divergent schemas

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

Status: COMPLETE

## Purpose and big picture

After this change, the CI pipeline will automatically detect and block any pull
request where ORM model changes are not accompanied by corresponding Alembic
migrations. Developers will have a local `make check-migrations` target that
compares the current SQLAlchemy model metadata against the state produced by
applying all Alembic migrations, reporting any differences (schema drift). This
prevents schema divergence between code and database, catching errors before
they reach staging or production.

Success is observable when:

1. Running `make check-migrations` on a clean tree exits with code 0 and
   prints a confirmation message.
2. If a developer adds a column to an ORM model without a migration, running
   `make check-migrations` exits non-zero and names the missing change.
3. The CI workflow in `.github/workflows/ci.yml` includes the migration drift
   check and would fail a PR that introduces model-migration divergence.
4. Unit and behavioural tests validate both the happy path (no drift) and the
   detection path (drift present).
5. The developers' guide documents the workflow for creating migrations and
   using the drift check.

## Constraints

- The migration check module must reside within the storage adapter layer
  (`episodic/canonical/storage/`) per the hexagonal architecture. It must not
  import from or depend on domain logic, inbound adapters, or orchestration
  modules.
- All existing tests must continue to pass. No regressions in `make test`,
  `make lint`, `make check-fmt`, or `make typecheck`.
- No new external dependencies may be added. The implementation must use only
  `alembic` (already `>=1.13,<2.0`), `sqlalchemy` (already `>=2.0.34,<3.0.0`),
  and `py-pglite[asyncpg]` (already a dev dependency).
- The `alembic/env.py` async configuration and the existing migration file
  `alembic/versions/20260203_000001_create_canonical_schema.py` must not be
  modified.
- Logging must use `femtologging` via the existing `episodic.logging` wrapper
  (import `get_logger` from `episodic.logging`, emit via `log_info`,
  `log_warning`, `log_error`).
- Follow the commit message format in `AGENTS.md`: imperative mood, subject
  no more than 50 characters, body wrapped at 72 characters, Markdown
  formatting.

## Tolerances (exception triggers)

- Scope: if implementation requires changes to more than 12 files or 600 lines
  of code (net), stop and escalate.
- Interface: if the `episodic.canonical.storage` public API (`__init__.py`
  `__all__`) must change beyond adding the new module's exports, stop and
  escalate.
- Dependencies: if a new external dependency is required, stop and escalate.
- Iterations: if tests still fail after 3 attempts at fixing, stop and
  escalate.
- Ambiguity: if `alembic.autogenerate.compare_metadata()` produces false
  positives for enum types or index names that cannot be resolved with a
  straightforward `include_object` filter, stop and escalate.

## Risks

- Risk: `alembic.autogenerate.compare_metadata()` may report false positives
  for PostgreSQL ENUM types defined via `sa.Enum(PythonEnum, ...)`, since
  autogenerate sometimes struggles with enum comparison. Severity: medium.
  Likelihood: medium. Mitigation: Test the comparison output against the
  existing models and migration first. If false positives appear, add an
  `include_object` filter callback that excludes known-safe differences.
  Document any filters in the Decision Log.

- Risk: The Makefile target `check-migrations` depends on py-pglite, which
  requires Node.js 18+. If CI or local environments lack Node.js, the check
  will fail. Severity: low. Likelihood: low. Mitigation: CI already runs tests
  that use py-pglite successfully. Document the Node.js requirement in the
  developers' guide.

- Risk: `compare_metadata()` may detect index name differences between
  autogenerate-inferred names and explicitly named indexes in the migration.
  Severity: low. Likelihood: low. Mitigation: Inspect the comparison output
  during implementation and filter if needed.

## Progress

- [x] (2026-02-09 00:00Z) Stage A: Write BDD feature file and step stubs.
- [x] (2026-02-09 00:00Z) Stage B: Write unit tests for schema drift
  detection.
- [x] (2026-02-09 00:00Z) Stage C: Implement the `migration_check` module.
- [x] (2026-02-09 00:00Z) Stage D: Add Makefile target and CI integration.
- [x] (2026-02-09 00:00Z) Stage E: Update documentation (developers' guide,
  system design doc, roadmap, users' guide).
- [x] (2026-02-09 00:00Z) Stage F: Run all quality gates and capture logs.

## Surprises & Discoveries

- Observation: The initial migration created explicit indexes
  (`ix_episodes_series_profile_id`, `ix_ingestion_jobs_series_profile_id`,
  `ix_source_documents_ingestion_job_id`, `ix_approval_events_episode_id`) on
  foreign key columns, but the ORM models did not declare `index=True` on those
  columns. `compare_metadata()` reported these as `remove_index` diffs (false
  positives from the drift check perspective). Evidence: First test run showed
  4 `remove_index` differences. Impact: Added `index=True` to the four FK
  columns in `episodic/canonical/storage/models.py` to align models with the
  migration. This is the correct fix since models should be the source of truth.

## Decision Log

- Decision: Use `alembic.autogenerate.compare_metadata()` programmatically
  rather than the `alembic check` CLI command. Rationale: The `alembic check`
  CLI invokes the full Alembic environment (`env.py`), which is configured for
  async SQLAlchemy and requires `DATABASE_URL` to be set. A programmatic
  approach reuses the existing py-pglite engine and `_apply_migrations`
  patterns from `tests/conftest.py`, is fully testable, and gives control over
  output format and false-positive filtering. The `compare_metadata` function
  is the same API that `alembic check` uses internally. Date/Author:
  2026-02-09, plan phase.

- Decision: Place the `migration_check` module at
  `episodic/canonical/storage/migration_check.py` rather than in a separate
  `scripts/` directory. Rationale: Schema drift detection is an infrastructure
  concern within the storage adapter layer. Placing it alongside the ORM models
  and repositories keeps the hexagonal architecture boundaries clean. The
  module can be invoked via
  `uv run python -m episodic.canonical.storage.migration_check` from the
  Makefile. Date/Author: 2026-02-09, plan phase.

- Decision: Reuse the `_alembic_config` and `_apply_migrations` patterns from
  `tests/conftest.py` rather than duplicating configuration logic. Rationale:
  The test fixtures already solve the problem of configuring Alembic with a
  py-pglite engine URL and applying migrations. Extracting the shared logic
  into a helper or importing directly from conftest avoids duplication.
  However, since importing from `tests/conftest.py` in production code is not
  appropriate, the migration check module will contain its own minimal versions
  of these helpers (following the same pattern). Date/Author: 2026-02-09, plan
  phase.

- Decision: Fix missing `index=True` declarations in ORM models rather than
  adding an `include_object` filter to suppress `remove_index` diffs.
  Rationale: The ORM models should be the authoritative schema description.
  Adding `index=True` to four FK columns aligns models with the migration and
  is the correct resolution. Filtering would mask genuine drift. Date/Author:
  2026-02-09, implementation phase.

## Outcomes & Retrospective

All stages completed successfully. The schema drift detection module
(`episodic/canonical/storage/migration_check.py`) is implemented, tested with
both unit and BDD tests, wired into the Makefile as `make check-migrations`,
and integrated into the CI pipeline. Documentation updates cover the
developers' guide, system design doc, users' guide, and roadmap.

The main surprise was that the existing ORM models were missing `index=True`
declarations for four FK columns that had explicit indexes in the migration.
This was resolved by adding the missing `index=True` flags rather than
filtering the diffs, since models should be the authoritative schema
description.

All quality gates pass: `make check-fmt`, `make lint`, `make typecheck`,
`make test` (17 passed, 2 skipped), `make check-migrations` (no drift),
`make markdownlint` (0 errors).

## Context and orientation

The Episodic project is a podcast generation platform following hexagonal
architecture. The codebase lives at `/home/user/project/`. Key locations:

- `episodic/canonical/storage/models.py` — SQLAlchemy ORM models defining
  `Base(DeclarativeBase)` and six record classes (`SeriesProfileRecord`,
  `TeiHeaderRecord`, `EpisodeRecord`, `IngestionJobRecord`,
  `SourceDocumentRecord`, `ApprovalEventRecord`). `Base.metadata` is the
  canonical model metadata used by Alembic.
- `episodic/canonical/storage/__init__.py` — Re-exports `Base` and all record
  classes, plus repository and unit-of-work classes.
- `alembic/env.py` — Async Alembic environment using `Base.metadata` as
  `target_metadata`. Supports online/offline modes and accepts a `connection`
  attribute for test injection.
- `alembic/versions/20260203_000001_create_canonical_schema.py` — The single
  existing migration creating 6 tables and 3 enums.
- `alembic.ini` — Root-level Alembic config; `sqlalchemy.url` is empty (set
  via `DATABASE_URL` env var or programmatically).
- `tests/conftest.py` — Pytest fixtures providing `pglite_engine` (py-pglite
  AsyncEngine), `migrated_engine` (engine with migrations applied),
  `session_factory`, and `pglite_session`. Contains `_alembic_config()` and
  `_apply_migrations()` helpers.
- `Makefile` — Build and quality targets. Existing targets include `build`,
  `test`, `lint`, `check-fmt`, `typecheck`, `markdownlint`, `nixie`.
- `.github/workflows/ci.yml` — CI pipeline running all quality gates on push
  to `main` and on PRs.
- `docs/developers-guide.md` — Developer documentation; already has a
  "Database migrations" section.
- `docs/episodic-podcast-generation-system-design.md` — System design doc with
  a "Change Management and Migrations" section at lines 1182-1187.
- `docs/roadmap.md` — Item 2.2.2 (line 62-63) is the target for this work.
- `episodic/logging.py` — Wrapper around `femtologging` exporting `get_logger`,
  `log_info`, `log_warning`, `log_error`.

The term "schema drift" means a difference between what the ORM models declare
(via `Base.metadata`) and what the database would look like after applying all
Alembic migrations. Detecting drift tells us whether a developer has changed
models without creating a corresponding migration (or vice versa).

The function `alembic.autogenerate.compare_metadata(context, metadata)` accepts
a `MigrationContext` (configured with a database connection where migrations
have been applied) and a `MetaData` object (the ORM models), and returns a list
of `MigrateOperation` objects describing the differences. An empty list means
no drift.

## Plan of work

The work proceeds in six stages, each ending with validation.

### Stage A: BDD feature file and step definitions

Create `tests/features/schema_migrations.feature` with two scenarios:

1. "No drift when models match migrations" — the happy path verifying that the
   current ORM models and migration history are in sync.
2. "Drift detected when models diverge from migrations" — verifying that adding
   an unmigrated table to `Base.metadata` is caught.

Create `tests/steps/test_schema_migrations_steps.py` with step definitions
following the exact patterns from
`tests/steps/test_canonical_ingestion_steps.py`: using
`_function_scoped_runner` for async steps, `migrated_engine` fixture for the
database, and the `_run_async_step` helper pattern.

For the drift scenario, the step "Given the ORM models include a table not
covered by migrations" will dynamically add a temporary `Table` object to
`Base.metadata` within the step, and remove it in a finally block after the
assertion.

### Stage B: Unit tests for schema drift detection

Create `tests/test_migration_check.py` with two async tests:

1. `test_no_drift_when_models_match_migrations` — uses the `migrated_engine`
   fixture, calls `detect_schema_drift(engine)`, asserts the result is an empty
   list.
2. `test_drift_detected_for_unmigrated_table` — uses the `migrated_engine`
   fixture, temporarily adds a `Table` to `Base.metadata`, calls
   `detect_schema_drift(engine)`, asserts the result is non-empty, and removes
   the temporary table in a finally block.

Both tests reuse the existing `migrated_engine` fixture from
`tests/conftest.py` which provides a py-pglite engine with all migrations
applied.

### Stage C: Implement the migration check module

Create `episodic/canonical/storage/migration_check.py` with:

1. `detect_schema_drift(engine: AsyncEngine) -> list[tuple[Any, ...]]` — the
   core function. It opens an async connection, calls `connection.run_sync()`
   with a synchronous helper that creates a `MigrationContext` from the
   connection, calls `compare_metadata(context, Base.metadata)`, and returns
   the list of differences.

2. `async def check_migrations_cli() -> int` — the CLI entrypoint. It creates
   a py-pglite instance (using `PGliteConfig` and `PGliteManager`), creates an
   async engine, applies all migrations (following the same pattern as
   `tests/conftest.py`), calls `detect_schema_drift()`, prints results, and
   returns exit code 0 or 1.

3. A `if __name__ == "__main__"` guard that calls `sys.exit(asyncio.run(
   check_migrations_cli()))`.

The module uses `femtologging` via `episodic.logging` for status messages.

Update `episodic/canonical/storage/__init__.py` to add `detect_schema_drift` to
`__all__` and the imports.

### Stage D: Makefile target and CI integration

Add to `Makefile`:

    check-migrations: build uv $(VENV_TOOLS) ## Check for schema drift between models and migrations
    	$(UV_ENV) uv run python -m episodic.canonical.storage.migration_check

Add `check-migrations` to the `.PHONY` line.

Add to `.github/workflows/ci.yml` a new step after "Install code" and before
"Run ruff":

    - name: Check migration drift
      run: make check-migrations

### Stage E: Documentation updates

Update `docs/developers-guide.md` to expand the "Database migrations" section
with:

- How to create a new migration after changing ORM models:
  `alembic revision --autogenerate -m "description"`.
- The naming convention: `YYYYMMDD_NNNNNN_short_description.py`.
- How `make check-migrations` works: starts an ephemeral Postgres via
  py-pglite, applies all migrations, compares the result against ORM model
  metadata, and fails if differences exist.
- The developer workflow: change models, generate migration, run
  `make check-migrations` locally, then commit both.
- CI enforcement: PRs that diverge are blocked.

Update `docs/episodic-podcast-generation-system-design.md` to expand the
"Change Management and Migrations" section (lines 1182-1187) with a paragraph
explaining the CI drift detection mechanism using
`alembic.autogenerate.compare_metadata()` against an ephemeral py-pglite
database.

Update `docs/users-guide.md` to add a brief note under the "Content Creation"
section mentioning that database schema integrity is automatically validated in
CI to ensure data reliability for canonical content.

Update `docs/roadmap.md` to mark item 2.2.2 as done: change `- [ ] 2.2.2.` to
`- [x] 2.2.2.`.

### Stage F: Quality gates

Run all required quality gates and capture logs:

    set -o pipefail
    timeout 300 make fmt 2>&1 | tee /tmp/make-fmt.log

    set -o pipefail
    timeout 300 make check-fmt 2>&1 | tee /tmp/make-check-fmt.log

    set -o pipefail
    timeout 300 make typecheck 2>&1 | tee /tmp/make-typecheck.log

    set -o pipefail
    timeout 300 make lint 2>&1 | tee /tmp/make-lint.log

    set -o pipefail
    timeout 300 make test 2>&1 | tee /tmp/make-test.log

    set -o pipefail
    timeout 300 make check-migrations 2>&1 | tee /tmp/make-check-migrations.log

    set -o pipefail
    timeout 300 make markdownlint 2>&1 | tee /tmp/make-markdownlint.log

## Concrete steps

### Step 1: Create the BDD feature file

Create `tests/features/schema_migrations.feature`:

    Feature: Schema migration drift detection

      Scenario: No drift when models match migrations
        Given all Alembic migrations have been applied
        When the schema drift check runs
        Then no drift is detected

      Scenario: Drift detected when models diverge from migrations
        Given all Alembic migrations have been applied
        And an unmigrated table has been added to the ORM metadata
        When the schema drift check runs
        Then schema drift is reported

### Step 2: Create the BDD step definitions

Create `tests/steps/test_schema_migrations_steps.py` following the pattern in
`tests/steps/test_canonical_ingestion_steps.py`. Use `_function_scoped_runner`
and `migrated_engine` fixtures. Import `detect_schema_drift` from
`episodic.canonical.storage.migration_check`.

For "an unmigrated table has been added to the ORM metadata", use
`sa.Table("_test_drift_table", Base.metadata, sa.Column("id", sa.Integer, primary_key=True))`
 and store the table reference in a context dict so it can be removed from
`Base.metadata` after the scenario.

### Step 3: Create the unit test file

Create `tests/test_migration_check.py` with two `@pytest.mark.asyncio` tests
following the pattern in `tests/test_canonical_storage.py`.

### Step 4: Implement the migration check module

Create `episodic/canonical/storage/migration_check.py`. The core function:

    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from episodic.canonical.storage.models import Base

    def _compare(connection, metadata):
        context = MigrationContext.configure(connection)
        return compare_metadata(context, metadata)

    async def detect_schema_drift(engine):
        async with engine.connect() as connection:
            return await connection.run_sync(_compare, Base.metadata)

The CLI entrypoint `check_migrations_cli()`:

    from py_pglite import PGliteConfig, PGliteManager
    from sqlalchemy.ext.asyncio import create_async_engine
    from alembic import command
    from alembic.config import Config

    async def check_migrations_cli():
        # Create ephemeral Postgres, apply migrations, check drift
        …
        diffs = await detect_schema_drift(engine)
        if diffs:
            log_error(logger, "Schema drift detected: %s", …)
            return 1
        log_info(logger, "No schema drift detected.")
        return 0

### Step 5: Update storage `__init__.py`

Add `detect_schema_drift` to imports and `__all__`.

### Step 6: Add Makefile target

Add `check-migrations` target and update `.PHONY`.

### Step 7: Update CI workflow

Add migration check step to `.github/workflows/ci.yml`.

### Step 8: Update documentation

Edit `docs/developers-guide.md`,
`docs/episodic-podcast-generation-system- design.md`, `docs/users-guide.md`,
and `docs/roadmap.md` as described in Stage E.

### Step 9: Run quality gates

Execute all commands from Stage F and verify all pass.

## Validation and acceptance

Acceptance requires all of the following:

- `make check-migrations` exits 0 on the current codebase (models match
  migrations).
- Unit test `test_no_drift_when_models_match_migrations` passes.
- Unit test `test_drift_detected_for_unmigrated_table` passes (verifying the
  check catches real drift).
- BDD scenario "No drift when models match migrations" passes.
- BDD scenario "Drift detected when models diverge from migrations" passes.
- `.github/workflows/ci.yml` includes the `make check-migrations` step.
- `docs/developers-guide.md` documents the migration creation workflow, the
  drift check, and the CI enforcement.
- `docs/episodic-podcast-generation-system-design.md` records the drift
  detection design decision.
- `docs/roadmap.md` marks 2.2.2 as done.
- `make check-fmt` passes.
- `make typecheck` passes.
- `make lint` passes.
- `make test` passes (all existing and new tests).

Quality method:

    set -o pipefail; timeout 300 make check-fmt 2>&1 | tee /tmp/make-check-fmt.log
    set -o pipefail; timeout 300 make typecheck 2>&1 | tee /tmp/make-typecheck.log
    set -o pipefail; timeout 300 make lint 2>&1 | tee /tmp/make-lint.log
    set -o pipefail; timeout 300 make test 2>&1 | tee /tmp/make-test.log
    set -o pipefail; timeout 300 make check-migrations 2>&1 | tee /tmp/make-check-migrations.log

## Idempotence and recovery

All steps are re-runnable. The py-pglite database is ephemeral (created in a
temporary directory and discarded after the check). If the migration check
fails, the developer creates or corrects the migration and reruns
`make check-migrations`. No persistent state is modified by the check itself.

If tests fail, fix the issue and rerun the relevant `make` target. Log files in
`/tmp` are overwritten on each run.

## Artifacts and notes

- `/tmp/make-check-fmt.log` — formatting check output.
- `/tmp/make-typecheck.log` — type check output.
- `/tmp/make-lint.log` — lint output.
- `/tmp/make-test.log` — test output.
- `/tmp/make-check-migrations.log` — migration drift check output.
- `/tmp/make-markdownlint.log` — Markdown lint output.

## Interfaces and dependencies

New module `episodic/canonical/storage/migration_check.py` exports:

    async def detect_schema_drift(
        engine: AsyncEngine,
    ) -> list[tuple[Any, …]]

This function accepts an async SQLAlchemy engine where Alembic migrations have
already been applied. It returns a list of differences between the migrated
database schema and the ORM model metadata (`Base.metadata`). An empty list
means no drift.

The module also provides:

    async def check_migrations_cli() -> int

This is the CLI entrypoint that creates an ephemeral py-pglite database,
applies migrations, runs drift detection, and returns an exit code.

Existing dependencies used (no new additions):

- `alembic.autogenerate.compare_metadata` — core comparison API.
- `alembic.migration.MigrationContext` — configures the comparison context.
- `alembic.config.Config` and `alembic.command.upgrade` — for applying
  migrations.
- `py_pglite.PGliteConfig` and `py_pglite.PGliteManager` — ephemeral
  Postgres.
- `sqlalchemy.ext.asyncio.create_async_engine` and `AsyncEngine` — async
  engine.
- `episodic.canonical.storage.models.Base` — ORM model metadata.
- `episodic.logging` — `get_logger`, `log_info`, `log_error`.

## Revision note

Initial plan created on 2026-02-09 to scope the Alembic migration tooling and
CI drift detection for roadmap item 2.2.2.

Revised on 2026-02-09 to capture implementation, index drift fix for four FK
columns in ORM models, and completed quality gate results.
