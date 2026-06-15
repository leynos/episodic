# 2.6.2: Repository contracts and Alembic migrations

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises &
Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be
kept up to date as work proceeds.

Status: DRAFT

## Purpose and big picture

This plan delivers the persistent storage layer for generation runs:
Alembic schema migrations for the generation-run aggregate, repository
interfaces that define the contract for accessing generation runs and
their associated events, and integration tests that validate event
ordering and the correctness of the persistence model.

After completing this work, the following will be observable:

- `alembic` migrations define the `generation_runs` and
  `generation_events` tables with proper indexes, constraints, and
  event-log semantics.
- Repository protocol interfaces (`GenerationRunRepository`,
  `GenerationEventRepository`) are defined in
  `episodic/generation/ports.py`.
- SQLAlchemy-backed repository implementations exist in
  `episodic/generation/storage/repositories.py`.
- Integration tests in `tests/generation/storage/test_generation_run_repositories.py`
  validate that:
  - events are persisted in monotonic sequence-number order.
  - generation runs can be retrieved by ID and episode ID.
  - event ordering is preserved across concurrent writes (via unique
    constraint on sequence number within a run).
  - runs transition through expected lifecycle states (created, responded).
- All gates pass: `make check-fmt`, `make typecheck`, `make lint`, and
  `make test`.

## Constraints

Hard invariants that must not be violated:

- The generation-run domain model (dataclasses for `GenerationRun`,
  `GenerationEvent`, `Checkpoint`) must be defined in 2.6.1 before this
  work begins. If the domain model is not yet finalized, escalate and
  wait.
- SQLAlchemy ORM mappers must not be embedded in domain dataclasses.
  Domain entities remain pure Python dataclasses with no ORM decorators.
- The schema migration must use Alembic with the same revision naming
  scheme as prior migrations (`YYYYMMDD_0000N_description`). The prior
  revision is `20260508_000008`.
- Event log tables must use append-only semantics: no updates to
  existing events after creation, only inserts.
- Repository interfaces must be protocols (runtime-checkable using
  `typing.Protocol`) and must reside in `episodic/generation/ports.py`.
- All repositories must participate in the hexagonal architecture and
  depend on domain entities and ports only; they must not import from
  inbound adapters (API, worker).
- Integration tests must hit a real PostgreSQL database, not mocked
  repositories. The test suite must configure `pytest-asyncio` with the
  project's existing test database fixture.
- Idempotency keys must be unique per run-creation request; duplicate
  creation requests with the same idempotency key must return the same
  generation run without creating a duplicate.
- All existing tests must continue to pass. No breaking changes to
  existing domain entities, repositories, or API contracts.

## Tolerances (exception triggers)

Thresholds that trigger escalation when breached:

- **Scope**: If implementation requires changes to more than 15 Python
  files or more than 1500 lines of net new code (excluding test fixtures
  and generated migration boilerplate), stop and escalate. The current
  estimate is ~10 files and ~1000 LOC.
- **Interface**: If the generated-run domain model needs significant
  revision after investigation, stop and escalate. The domain model
  should be locked for this phase.
- **Dependencies**: If new external dependencies beyond SQLAlchemy,
  Alembic, and Pydantic are required, stop and escalate.
- **Database**: If the PostgreSQL schema changes require data
  transformation or reordering of existing rows, stop and escalate.
  Append-only event logs must only add new tables, never modify
  existing ones.
- **Test iterations**: If tests still fail after 3 attempts to fix the
  repository or migration logic, stop and escalate.
- **Ambiguity**: If multiple valid interpretations exist for lifecycle
  state transitions or event ordering semantics, stop and present
  options with trade-offs.

## Risks

Known uncertainties that might affect the plan:

- **Risk**: The domain model for `GenerationRun`, `GenerationEvent`, and
  `Checkpoint` (from 2.6.1) may not yet be defined or finalized.
  Severity: medium. Likelihood: medium. Mitigation: Verify that 2.6.1
  is complete before starting this plan. If not, escalate and wait.

- **Risk**: Event ordering constraints in PostgreSQL may require
  non-obvious schema choices (e.g., composite unique keys on run_id and
  sequence_number). Severity: low. Likelihood: medium. Mitigation:
  Prototype the constraint in the migration and validate with
  integration tests before finalizing.

- **Risk**: Alembic migration naming and down-migration logic must be
  correct to avoid schema divergence in CI and local environments.
  Severity: medium. Likelihood: low. Mitigation: Follow the established
  naming scheme from prior migrations. Test down-migrations in the test
  suite.

- **Risk**: Concurrent event writes to the same generation run may
  violate sequence-number uniqueness if transaction isolation is not
  properly configured. Severity: medium. Likelihood: medium. Mitigation:
  Use database-level constraints (unique indexes) rather than
  application-level checks. Add integration tests that simulate
  concurrent writes.

- **Risk**: The repository implementation may leak SQLAlchemy ORM
  details into the domain layer, violating hexagonal architecture.
  Severity: high. Likelihood: medium. Mitigation: Keep mappers isolated
  in a separate `storage` submodule. Use explicit conversion from ORM
  models to domain dataclasses. Run `make check-architecture` to
  validate boundaries.

- **Risk**: The initial idempotency-key implementation may not handle
  race conditions correctly (e.g., duplicate requests arriving
  simultaneously). Severity: medium. Likelihood: low. Mitigation: Use
  database-level unique constraints on idempotency keys. Add
  integration tests for concurrent creation requests.

## Progress

Use a list with checkboxes to summarise granular steps. This section
reflects the actual current state of the work.

- [ ] (pending) Stage A: Verify 2.6.1 domain model is defined and
  finalized.
- [ ] (pending) Stage B: Define repository protocols in
  `episodic/generation/ports.py`.
- [ ] (pending) Stage C: Draft Alembic migration for `generation_runs`
  and `generation_events` tables.
- [ ] (pending) Stage D: Implement SQLAlchemy ORM models in
  `episodic/generation/storage/models.py`.
- [ ] (pending) Stage E: Implement repository classes in
  `episodic/generation/storage/repositories.py`.
- [ ] (pending) Stage F: Write integration tests for repositories and
  event ordering.
- [ ] (pending) Stage G: Validate all gates pass and finalize
  documentation.
- [ ] (pending) Stage H: Final review and approval before marking
  complete.

## Surprises & discoveries

Unexpected findings during implementation that were not anticipated as
risks. This section will be populated as work proceeds.

(To be filled during implementation.)

## Decision log

Record every significant decision made while working on the plan.

(Decisions will be recorded here as work proceeds.)

## Outcomes & retrospective

Summarize outcomes, gaps, and lessons learned. This section will be
populated upon completion.

(To be filled at the end of the work.)

---

## Context and orientation

The episodic podcast generation system uses a hexagonal architecture
with strict boundary enforcement. Domain logic resides in pure Python
dataclasses without ORM decorators. SQLAlchemy ORM models and
repositories are isolated in adapter submodules (`episodic/*/storage/`).

Key files and modules:

- **Domain**: `episodic/canonical/domain.py` contains the canonical
  content entities. The generation-run domain model should be defined in
  `episodic/generation/domain.py` (to be verified as part of 2.6.1).
- **Ports**: `episodic/canonical/entity_protocols.py` and
  `episodic/canonical/unit_of_work_protocols.py` define repository
  protocols. Generation-run protocols should live in
  `episodic/generation/ports.py`.
- **Storage adapters**: `episodic/canonical/storage/` contains
  SQLAlchemy models, mappers, and repositories. The generation-run
  storage adapter should follow the same structure in
  `episodic/generation/storage/`.
- **Migrations**: `alembic/versions/` contains all schema migrations,
  with the latest being `20260508_000008_add_workflow_checkpoints.py`.
  New migrations must follow the naming scheme
  `YYYYMMDD_0000N_description.py`.
- **Tests**: `tests/canonical/storage/` and `tests/integration/`
  contain examples of integration test patterns with async SQLAlchemy
  and pytest fixtures.

Hexagonal boundaries are enforced by:

- `episodic/architecture/checker.py` validates that domain modules do
  not import from adapters.
- `make check-architecture` runs the checker as part of `make lint`.
- Architecture tests in `tests/architecture/` verify the allowed
  dependency graph.

The project uses:

- **Test framework**: pytest with `pytest-asyncio` for async test
  fixtures.
- **ORM**: SQLAlchemy 2.x with async drivers (psycopg 3).
- **Migrations**: Alembic with inline table creation (no autogenerate).
- **Typing**: Pydantic V2 for structured types, `typing.Protocol` for
  interfaces.
- **Snapshot testing**: syrupy for output validation.

## Plan of work

The work proceeds in 8 stages, with explicit go/no-go validation after
each.

### Stage A: Verify domain model

**Objective**: Confirm that 2.6.1 (Define GenerationRunPort and
implement domain model) is complete and the domain entities are locked
for implementation.

**What to do**: Inspect `episodic/generation/domain.py` to verify it
contains:

- `GenerationRun` dataclass with fields: `id` (UUIDv7), `episode_id`,
  `created_at`, `updated_at`, `status` (enum: created, responded).
- `GenerationEvent` dataclass with fields: `id` (UUIDv7), `run_id`,
  `sequence_number` (monotonic integer), `type` (enum), `payload`
  (JSON), `created_at`.
- `Checkpoint` dataclass with fields: `id` (UUIDv7), `run_id`, `status`
  (enum: created, responded), `responded_at` (optional), `payload`
  (JSON).

If the domain model does not exist or is incomplete, **escalate and wait
for 2.6.1 to be completed**.

If the domain model exists and is frozen, proceed to Stage B.

**Go/no-go validation**: Confirm the domain model is present and
immutable (no further changes expected).

### Stage B: Define repository protocols

**Objective**: Define the port interfaces that repository implementations
must satisfy.

**What to do**: Create or update `episodic/generation/ports.py` to
define:

```python
@typing.runtime_checkable
class GenerationRunRepository(typing.Protocol):
    """Repository for querying and persisting generation runs."""

    async def add(self, run: GenerationRun) -> None:
        """Create a new generation run."""
        raise NotImplementedError

    async def by_id(self, run_id: UUID) -> GenerationRun | None:
        """Retrieve a generation run by ID."""
        raise NotImplementedError

    async def by_episode_id(
        self, episode_id: UUID, limit: int = 100
    ) -> list[GenerationRun]:
        """List all generation runs for an episode."""
        raise NotImplementedError

    async def by_idempotency_key(
        self, idempotency_key: str
    ) -> GenerationRun | None:
        """Retrieve the generation run associated with an idempotency key."""
        raise NotImplementedError
```

**Go/no-go validation**: Run `make typecheck` to ensure the protocols are
correctly typed. Ensure no import errors.

### Stage C: Draft Alembic migration

**Objective**: Design the PostgreSQL schema for generation runs and
events, then draft the Alembic migration.

**Schema design**: The schema implements append-only event log semantics:

```sql
CREATE TABLE generation_runs (
    id UUID PRIMARY KEY,
    episode_id UUID NOT NULL REFERENCES episodes(id),
    idempotency_key VARCHAR(512) UNIQUE,
    status VARCHAR(32) NOT NULL DEFAULT 'created',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_generation_runs_episode_id
  ON generation_runs(episode_id);

CREATE TABLE generation_events (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES generation_runs(id),
    sequence_number INTEGER NOT NULL,
    type VARCHAR(120) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE(run_id, sequence_number)
);

CREATE INDEX ix_generation_events_run_id
  ON generation_events(run_id);
```

**What to do**: Create a new file
`alembic/versions/20260615_000009_add_generation_runs.py` following the
pattern from `20260508_000008_add_workflow_checkpoints.py`:

- Define an `upgrade()` function that creates the tables and indexes.
- Define a `downgrade()` function that drops tables and indexes in
  reverse order.
- Use `op.create_table()` for table creation.
- Use `op.create_index()` for index creation.
- Ensure the revision and down_revision fields are correct.

Do not yet apply the migration. The migration will be tested in Stage F.

**Go/no-go validation**: Run `make check-fmt` and `make lint` on the
migration file. Ensure no syntax errors and the Alembic version string
is correctly formatted.

### Stage D: Implement SQLAlchemy ORM models

**Objective**: Create ORM models that map to the schema but do not leak
into the domain layer.

**What to do**: Create or update
`episodic/generation/storage/models.py`. Keep mappers simple: only
convert between ORM and domain types. Do not embed business logic in
models.

**Go/no-go validation**: Run `make typecheck` to ensure the models are
correctly typed. Verify no import cycles.

### Stage E: Implement repository classes

**Objective**: Create repository implementations that satisfy the
protocol and use the ORM models.

**What to do**: Create or update
`episodic/generation/storage/repositories.py`. Repositories are concrete
implementations; they do not inherit from the protocol. They satisfy the
protocol structurally (duck typing).

**Go/no-go validation**: Run `make typecheck` and `make lint`. Verify
no import cycles or violations of hexagonal boundaries with
`make check-architecture`.

### Stage F: Write integration tests

**Objective**: Create integration tests that validate the repositories
and event-ordering semantics.

**What to do**: Create or update
`tests/generation/storage/test_generation_run_repositories.py`. Add
tests for:

- Generation runs can be created and retrieved
- Duplicate run IDs are rejected
- Events preserve sequence order on append
- Duplicate sequence numbers within a run are rejected
- Runs can be listed by episode ID

Use `pytest.mark.asyncio` for async test fixtures.

**Go/no-go validation**: Run
`make test -- tests/generation/storage/test_generation_run_repositories.py`
and ensure all tests pass.

### Stage G: Validate all gates

**Objective**: Ensure all code quality checks pass and update
developers' and users' guides as needed.

**What to do**:

Run all code gates in sequence:

```bash
make check-fmt && make typecheck && make lint && \
  make check-architecture && make test
```

All must pass. If any fail, fix the issues and re-run.

Then:

1. Update `docs/developers-guide.md` to document the generation-run
   repository pattern.

2. Commit changes with a clear message.

**Go/no-go validation**: All gates must pass. Documentation must be
updated. Commit must be clean and well-formed.

### Stage H: Final review and approval

**Objective**: Obtain stakeholder approval before marking the milestone
as complete.

**What to do**:

1. Create a draft pull request with:
   - Title: "(2.6.2) Implement generation-run repository contracts and
     Alembic migrations"
   - Body summarizing the work and linking to this ExecPlan.
   - Reference to relevant ADRs or design documents.

2. Request review from team members and stakeholders.

3. Incorporate feedback and iterate until approval.

4. Merge the PR and mark the milestone as complete.

**Go/no-go validation**: PR approval from designated reviewers. All
conversations resolved.

---

## Revision note

(To be updated as plan is revised. Currently at initial DRAFT version.)
