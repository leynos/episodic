# Relational schema design plan

This ExecPlan is a living document. The sections `Progress`,
`Surprises and discoveries`, `Decision log`, and `Outcomes and retrospective`
must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

## Purpose and big picture

The goal is to design the SQLAlchemy and Postgres relational schema for the
canonical content foundation. The schema must cover TEI headers and
provenance, canonical episodes, ingestion jobs, source documents, series
profiles, and approval state tracking while respecting hexagonal architecture
boundaries. Deliverables include SQLAlchemy models, Alembic migrations, and
tests that validate constraints and behaviour, plus documentation updates for
users and developers. The outcome should enable auditable ingestion and
approval workflows with clear provenance, optimistic locking, and stable
interfaces for downstream services.

## Progress

- [x] (2026-02-02 00:00Z) Draft initial ExecPlan.

## Surprises and discoveries

- Observation: `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md`, and
  `docs/testing-sqlalchemy-with-py-pglite.md` are not present in `docs/`.
  Evidence: `ls docs` returned no matches.
- Observation: `docs/developers-guide.md` is not present in `docs/`.
  Evidence: `ls docs` returned no matches.

## Decision log

- None yet.

## Outcomes and retrospective

- Pending.

## Context and orientation

Key references:

- `docs/episodic-podcast-generation-system-design.md` for canonical content
  requirements, data model baseline, and hexagonal guardrails.
- `docs/roadmap.md` for Phase 2 task 2.2.1 scope and completion criteria.
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` for boundary
  expectations.
- `docs/users-guide.md` for end-user behaviour updates.
- `docs/execplans/langgraph-design-enhancements.md` for ExecPlan structure.

Term definitions used in this plan:

- TEI header: The metadata and provenance block attached to TEI documents.
- Canonical episode: The merged, source-weighted TEI document for an episode.
- Ingestion job: A batch record describing a source import and its outcomes.
- Approval state: The current editorial decision and its audit trail.

## Plan of work

First, inventory the existing data model guidance and enumerate the required
entities, relationships, and provenance fields for the canonical content
foundation. Next, draft a relational schema specification and translate it
into SQLAlchemy models and Alembic migrations, ensuring hexagonal layering
keeps domain entities independent of persistence adapters. Then add unit tests
and behavioural tests that validate the schema, repository behaviour, and
approval state transitions. Finally, update design, user, and developer
documentation, mark the roadmap item complete, and run quality gates.

## Concrete steps

1. Locate and review the current data model guidance, TEI provenance
   requirements, and approval workflow expectations.

   ```plaintext
   rg -n "Data Model and Storage" docs/episodic-podcast-generation-system-design.md
   rg -n "series_profiles|episodes|source_documents|approval" docs/episodic-podcast-generation-system-design.md
   rg -n "ingestion" docs/episodic-podcast-generation-system-design.md
   rg -n "canonical" docs/episodic-podcast-generation-system-design.md
   ```

2. Draft the relational schema specification covering TEI headers, canonical
   episodes, ingestion jobs, source documents, series profiles, and approval
   states. Define primary keys, foreign keys, unique constraints, enums, JSONB
   fields, and required indices. Record design decisions in
   `docs/episodic-podcast-generation-system-design.md` and the Decision log.

3. Define the module layout to keep hexagonal boundaries intact: domain models
   and repository interfaces in the core, SQLAlchemy models and migrations in
   outbound adapters, and TEI parsing or normalisation behind ports. Confirm
   `tei-rapporteur` usage for TEI header parsing and `femtologging` usage for
   structured logging across ingestion and persistence workflows.

4. Implement SQLAlchemy models and Alembic migrations for the schema. Add
   idempotency keys, optimistic locking fields, and provenance fields aligned
   with the TEI header and ingestion requirements.

5. Implement unit tests with pytest to validate table constraints, repository
   behaviour, and TEI provenance capture. Add behavioural tests with
   pytest-bdd that cover ingestion job creation, source document tracking,
   canonical episode updates, and approval state transitions.

6. Update documentation:

   - `docs/episodic-podcast-generation-system-design.md` with schema and
     design decisions.
   - `docs/users-guide.md` with new canonical content and approval behaviour
     descriptions.
   - `docs/developers-guide.md` with repository interfaces, migration
     workflow, and testing guidance (create this document if it does not
     exist).

7. Mark `docs/roadmap.md` task 2.2.1 as done once schema design, tests, and
   documentation updates land.

8. Run formatting, linting, type checks, and tests with logs captured.

   ```plaintext
   set -o pipefail
   timeout 300 make check-fmt 2>&1 | tee /tmp/make-check-fmt.log
   timeout 300 make typecheck 2>&1 | tee /tmp/make-typecheck.log
   timeout 300 make lint 2>&1 | tee /tmp/make-lint.log
   timeout 300 make test 2>&1 | tee /tmp/make-test.log
   timeout 300 make markdownlint 2>&1 | tee /tmp/make-markdownlint.log
   timeout 300 make nixie 2>&1 | tee /tmp/make-nixie.log
   ```

## Validation and acceptance

Acceptance requires all of the following:

- A schema specification and SQLAlchemy models that cover TEI headers,
  canonical episodes, ingestion jobs, source documents, series profiles, and
  approval states with explicit constraints and indices.
- Alembic migrations that reproduce the schema in Postgres.
- Unit tests (pytest) and behavioural tests (pytest-bdd) that validate the new
  schema, repository behaviour, and approval transitions.
- `docs/episodic-podcast-generation-system-design.md` updated with design
  decisions, tables, and an updated entity relationship diagram.
- `docs/users-guide.md` and `docs/developers-guide.md` updated to reflect the
  new behaviour and interfaces.
- `docs/roadmap.md` marks task 2.2.1 as done after completion.
- `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie` succeed with logs captured.

## Idempotence and recovery

Schema design, migrations, and documentation edits are repeatable. If any
quality gate fails, fix the reported issue, re-run the failed `make` target,
and keep the latest log output under `/tmp`. If formatting is required, run
`make fmt` before re-running `make check-fmt`.

## Artifacts and notes

- `/tmp/make-check-fmt.log` records formatting verification output.
- `/tmp/make-typecheck.log` records type check output.
- `/tmp/make-lint.log` records lint output.
- `/tmp/make-test.log` records pytest output.
- `/tmp/make-markdownlint.log` records Markdown lint output.
- `/tmp/make-nixie.log` records Mermaid validation output.

## Interfaces and dependencies

Document and implement the following interfaces and dependencies:

- Repository ports for series profiles, canonical episodes, ingestion jobs,
  source documents, and approval events.
- Unit-of-work coordination for schema mutations and audit logging.
- TEI parsing and normalisation behind a port that uses `tei-rapporteur`.
- Structured logging via `femtologging` in ingestion, persistence, and
  migration workflows.
- SQLAlchemy async sessions and Alembic migrations isolated in outbound
  adapters, keeping domain entities and services framework-agnostic.

## Revision note

Initial plan created on 2026-02-02.
