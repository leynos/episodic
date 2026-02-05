# Relational schema design plan

This ExecPlan is a living document. The sections `Progress`,
`Surprises and discoveries`, `Decision log`, and `Outcomes and retrospective`
must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

## Purpose and big picture

The outcome is a SQLAlchemy and Postgres relational schema that supports TEI
(Text Encoding Initiative) headers, canonical episodes, ingestion jobs, source
documents, series profiles, and approval state transitions. The work includes
SQLAlchemy models, migrations, repository ports, and tests, plus documentation
updates for design decisions, user-facing behaviour, and developer guidance.
Success is observable when the schema is implemented, unit and behavioural
tests pass, and the roadmap entry for 2.2.1 is marked done.

## Progress

- [x] (2026-02-02 00:00Z) Drafted initial ExecPlan for schema design.
- [x] (2026-02-03 00:00Z) Added py-pglite test scaffolding references and
  linked the new testing guidance.
- [x] (2026-02-03 00:00Z) Implemented canonical schema models, Alembic
  migrations, and py-pglite fixtures.
- [x] (2026-02-03 00:00Z) Added unit and behavioural tests for ingestion
  workflows and repository constraints.
- [x] (2026-02-03 00:00Z) Updated system design, users' guide, and developer
  guide documentation for the canonical schema.
- [x] (2026-02-03 00:00Z) Added unit-of-work flush support to preserve
  foreign-key ordering during ingestion and validated async py-pglite tests.

## Surprises and discoveries

- Observation: The async SQLAlchemy and py-pglite testing guides are now
  available in `docs/` after importing them from the ghillie repository.
- Observation: py-pglite requires Node.js 18+ for the embedded Postgres
  WebAssembly (WASM) runtime, so tests depend on Node availability.

## Decision log

- Decision: Treat the relational schema as an outbound adapter within the
  hexagonal architecture, exposing repository and unit-of-work ports to the
  domain layer. Rationale: Keeps domain logic isolated from SQLAlchemy details.
  Date/Author: 2026-02-02, Codex.
- Decision: Document schema design decisions in
  `docs/episodic-podcast-generation-system-design.md` alongside the existing
  data model section. Rationale: The system design document is the canonical
  architecture reference. Date/Author: 2026-02-02, Codex.
- Decision: Adopt the py-pglite testing approach for database-backed tests and
  document the scaffolding in `tests/conftest.py` alongside the new guidance
  docs. Rationale: Aligns unit and behavioural tests with the documented
  in-process Postgres strategy. Date/Author: 2026-02-03, Codex.
- Decision: Introduce `CanonicalUnitOfWork.flush()` to persist dependent
  records before creating approval events in a single transaction. Rationale:
  Approval events and episodes share foreign-key constraints without ORM
  relationships; flushing preserves ordering. Date/Author: 2026-02-03, Codex.

## Outcomes and retrospective

Canonical content schema models, migrations, and py-pglite-backed tests were
implemented alongside documentation updates for design decisions and developer
practice. Validation confirmed formatting, linting, and tests passed with the
new fixtures after adding unit-of-work flushes for ingestion ordering.

## Context and orientation

Key references:

- `docs/roadmap.md` defines Phase 2.2.1 and the canonical content foundation.
- `docs/episodic-podcast-generation-system-design.md` lists the intended data
  model entities, including `series_profiles`, `episodes`, `source_documents`,
  and `approval_events`.
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` clarifies boundary
  rules for ports and adapters.
- `docs/agentic-systems-with-langgraph-and-celery.md` provides orchestration
  context for ingestion jobs and background workflows.
- `docs/async-sqlalchemy-with-pg-and-falcon.md` defines async SQLAlchemy
  engine, session, and middleware practices for Falcon.
- `docs/testing-async-falcon-endpoints.md` captures the async Falcon endpoint
  testing approach.
- `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` defines the py-pglite
  fixtures and migration strategy for Postgres-backed tests.
- `docs/users-guide.md` requires updates for user-visible behaviours.
- `docs/developers-guide.md` must be created or updated to document internal
  interfaces and practices.
- `tei-rapporteur` user guide (external) for TEI header parsing and validation.
- `femtologging` user guide (external) for logging conventions.

## Plan of work

First, inspect the existing design document, roadmap, and codebase to align the
schema with the documented data model, hexagonal boundaries, and any existing
domain terminology. Capture missing documentation references and resolve where
to place new developer guidance if `docs/developers-guide.md` does not exist.

Next, design the relational schema to cover TEI headers, canonical episodes,
ingestion jobs, source documents, series profiles, and approval state history.
Define the cardinality, constraints, indexes, and status enumerations. Decide
how to store TEI header data (raw XML versus structured JSONB), and how to
represent provenance, versioning, and approval transitions. Record each design
decision in the system design document.

Then, implement the SQLAlchemy models, repository ports, and Alembic migration
for the schema, keeping the adapter layer isolated from domain logic. Wire
logging via `femtologging` in repository and migration entry points. Add tests
with `pytest` for model constraints and repository behaviour, plus `pytest-bdd`
scenarios that exercise ingestion jobs, source document association, canonical
episode creation, and approval state transitions using the py-pglite fixtures
from `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.

Finally, update documentation to reflect user-facing behaviours and developer
interfaces, and mark the roadmap entry as done once the schema is implemented
and validated. Run all required quality gates and capture logs under `/tmp`.

## Concrete steps

1. Locate schema-related guidance in the design document and roadmap.

   ```plaintext
   rg -n "Data Model and Storage" docs/episodic-podcast-generation-system-design.md
   rg -n "series_profiles|episodes|source_documents|approval_events" \
     docs/episodic-podcast-generation-system-design.md
   rg -n "2.2.1" docs/roadmap.md
   ```

2. Locate or create internal documentation targets for developer guidance.

   ```plaintext
   rg -n "developers-guide" docs
   ```

3. Review external library guides for TEI parsing and logging conventions, and
   summarize integration points in the design document. Review the async
   SQLAlchemy and py-pglite testing guides, and align the test scaffolding with
   the documented fixtures.

4. Draft the relational schema design, covering:
   - TEI header storage strategy (raw XML, JSONB, or both) and provenance
     metadata fields.
   - Canonical episode tables, links to series profiles, and TEI header
     references.
   - Ingestion jobs, source documents, and weighting metadata with audit
     timestamps.
   - Approval state history and current approval status.
   - Constraints, indexes, and status enumerations.

5. Implement SQLAlchemy models, repository ports, and an Alembic migration for
   the schema. Add `femtologging` integration in adapter entry points and
   define ports for repository access in line with hexagonal boundaries.

6. Add tests:
   - Unit tests for SQLAlchemy models, constraints, and repository operations.
   - Behavioural tests using `pytest-bdd` that exercise ingestion, canonical
     episode creation, and approval transitions end-to-end.
   - Use py-pglite fixtures and migration setup as documented in
     `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.

7. Update documentation:
   - `docs/episodic-podcast-generation-system-design.md` with schema decisions.
   - `docs/users-guide.md` with user-visible behaviour for ingestion and
     approval workflows.
   - `docs/developers-guide.md` with internal repository, migration, and
     logging practices.
   - `docs/roadmap.md` mark 2.2.1 as done once implementation passes tests.

8. Run formatting and validation for documentation changes.

   ```plaintext
   set -o pipefail
   timeout 300 make fmt 2>&1 | tee /tmp/make-fmt.log

   set -o pipefail
   timeout 300 make markdownlint 2>&1 | tee /tmp/make-markdownlint.log

   set -o pipefail
   timeout 300 make nixie 2>&1 | tee /tmp/make-nixie.log
   ```

9. Run code quality gates and tests.

   ```plaintext
   set -o pipefail
   timeout 300 make check-fmt 2>&1 | tee /tmp/make-check-fmt.log

   set -o pipefail
   timeout 300 make typecheck 2>&1 | tee /tmp/make-typecheck.log

   set -o pipefail
   timeout 300 make lint 2>&1 | tee /tmp/make-lint.log

   set -o pipefail
   timeout 300 make test 2>&1 | tee /tmp/make-test.log
   ```

## Validation and acceptance

Acceptance requires all of the following:

- SQLAlchemy models and migrations cover TEI headers, canonical episodes,
  ingestion jobs, source documents, series profiles, and approval states with
  documented constraints and indexes.
- Repository ports and unit-of-work abstractions are defined in the domain
  boundary and implemented in the adapter layer.
- Unit tests validate model constraints and repository operations.
- Behavioural tests validate ingestion, canonical episode creation, and
  approval transitions using `pytest-bdd`.
- Test scaffolding uses the py-pglite fixtures documented in
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.
- Documentation updates include schema decisions, user-facing behaviour, and
  developer practices, aligned with the documentation style guide.
- `docs/roadmap.md` marks 2.2.1 as done after validation.
- `make fmt`, `make markdownlint`, `make nixie`, `make check-fmt`,
  `make typecheck`, `make lint`, and `make test` complete successfully with
  logs captured under `/tmp`.

## Idempotence and recovery

Schema and documentation edits are repeatable. If migrations or tests fail,
revert or adjust the migration and rerun the failing `make` targets using the
same `set -o pipefail` and `tee` pattern. The log files in `/tmp` capture the
latest failure context and may be overwritten safely.

## Artifacts and notes

- `/tmp/make-fmt.log` records formatting output.
- `/tmp/make-markdownlint.log` records Markdown lint results.
- `/tmp/make-nixie.log` records Mermaid validation output.
- `/tmp/make-check-fmt.log` records formatting checks.
- `/tmp/make-typecheck.log` records typecheck output.
- `/tmp/make-lint.log` records lint output.
- `/tmp/make-test.log` records test output.

## Interfaces and dependencies

Document or introduce the following interfaces and dependencies:

- Repository ports for `SeriesProfile`, `Episode`, `TeiHeader`, `IngestionJob`,
  `SourceDocument`, and `ApprovalState` aggregates.
- Unit-of-work boundary for transactional writes.
- `tei-rapporteur` for TEI header parsing and validation.
- `femtologging` for structured logging in adapters.
- SQLAlchemy 2.x async engine, Alembic migrations, and Postgres driver.
- py-pglite (`py-pglite[asyncpg]`) for Postgres-backed tests, plus Node.js
  18+ for the WASM runtime as documented.
- `pytest`, `pytest-asyncio`, and `pytest-bdd` for unit and behavioural tests.

## Revision note

Initial plan created on 2026-02-02 to scope the relational schema design,
implementation, and validation steps for roadmap item 2.2.1.

Revised on 2026-02-03 to align test scaffolding and validation steps with the
py-pglite testing guidance.

Revised on 2026-02-03 to capture canonical schema implementation details and
updated documentation.
