# Implement series profile and episode template models, REST endpoints, and change history

This Execution Plan (ExecPlan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

No `PLANS.md` file is present in the repository root.

Status: COMPLETE

## Purpose and big picture

After this change, downstream generation workflows can retrieve structured
briefs through stable API contracts instead of piecing data together from
ingestion artefacts. Series profiles and episode templates become first-class
versioned resources with change history and optimistic concurrency controls.

Success is observable when:

1. `SeriesProfile` and `EpisodeTemplate` model contracts are implemented with
   versioned change-history records.
2. REST endpoints support create, get, list, and update flows for both
   resources, including change-history retrieval.
3. Downstream-facing brief payloads are retrievable from the API in a stable,
   documented structure.
4. New unit tests (`pytest`) and behavioural tests (`pytest-bdd`) fail before
   implementation and pass after implementation.
5. Documentation is updated in:
   - `docs/episodic-podcast-generation-system-design.md`
   - `docs/users-guide.md`
   - `docs/developers-guide.md`
6. The matching roadmap entry is marked done only after all quality gates pass.
7. Required gates pass:
   `make check-fmt`, `make typecheck`, `make lint`, and `make test`.

## Constraints

- Preserve hexagonal architecture invariants from the
  `hexagonal-architecture` skill:
  - Dependency direction points inward.
  - Domain owns port contracts.
  - Domain models must not import Falcon, SQLAlchemy, or Alembic symbols.
  - Adapters do not call each other directly.
- Keep existing canonical ingestion behaviour unchanged.
- Do not break existing repository contracts unless replacement is additive and
  covered by migration plus tests.
- Persist change-history entries as immutable records (append-only history).
- Use test-first workflow for this feature:
  - Add or update tests first.
  - Confirm failing state.
  - Implement feature.
  - Confirm passing state.
- Keep API and persistence semantics aligned with:
  - `docs/episodic-podcast-generation-system-design.md`
  - `docs/async-sqlalchemy-with-pg-and-falcon.md`
  - `docs/testing-async-falcon-endpoints.md`
  - `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`
  - `docs/agentic-systems-with-langgraph-and-celery.md`

## Tolerances (exception triggers)

- Scope: stop and escalate if implementation exceeds 20 files or 1400 net
  lines.
- Interface: stop and escalate if existing public dataclass fields must be
  changed incompatibly.
- Dependencies: stop and escalate if adding Falcon or related HTTP libraries
  requires replacing the current testing harness rather than extending it.
- Migrations: stop and escalate if migration rollback cannot preserve data.
- Iterations: stop and escalate after 3 unsuccessful attempts to fix the same
  failing test group.
- Ambiguity: stop and escalate if roadmap numbering or acceptance wording
  conflicts with implementation scope.

## Risks

- Risk: roadmap numbering mismatch could cause completion updates to touch the
  wrong checklist item. Severity: medium. Likelihood: medium. Mitigation:
  reference the exact checklist text when marking done.

- Risk: Falcon endpoint scaffolding is not yet present in code, increasing
  initial implementation surface. Severity: high. Likelihood: high. Mitigation:
  stage endpoint scaffolding behind focused failing tests and keep wiring
  minimal.

- Risk: optimistic locking semantics may diverge between storage and API.
  Severity: high. Likelihood: medium. Mitigation: define one version token
  contract (for example `version` or `etag`) in domain/service first, then
  assert it in unit, integration, and BDD tests.

- Risk: dependency on reusable reference-document work may be incomplete at
  implementation time. Severity: medium. Likelihood: medium. Mitigation: keep
  series profile and template histories self-contained, with explicit extension
  points for reference bindings.

## Progress

- [x] (2026-02-20 20:04Z) Drafted ExecPlan with file-level implementation and
  validation strategy.
- [x] (2026-02-20 22:19Z) Stage A completed: added failing unit/API/BDD tests.
- [x] (2026-02-20 22:25Z) Stage B completed: added persistence models,
  repositories, unit-of-work wiring, and Alembic migration.
- [x] (2026-02-20 22:27Z) Stage C completed: added profile/template domain
  services with revision-based optimistic locking and structured briefs.
- [x] (2026-02-20 22:28Z) Stage D completed: added Falcon REST adapters and
  API test fixtures.
- [x] (2026-02-20 22:30Z) Stage E completed: updated design, user, developer,
  and roadmap docs.
- [x] (2026-02-20 23:34Z) Stage F completed: all required quality gates passed
  with evidence logs in `/tmp/impl-2-2-8-make-*-final.log`.

## Surprises & discoveries

- Observation: no MCP resources or templates are available in this environment,
  so project-memory retrieval via `qdrant-find` is unavailable in-session.
  Evidence: `list_mcp_resources` and `list_mcp_resource_templates` both
  returned empty lists. Impact: this plan is based on repository state and
  checked-in documentation.

- Observation: as of 2026-02-20, `docs/roadmap.md` tracks this capability under
  item `2.2.8`, while this ExecPlan filename was requested as `2-2-6`.
  Evidence: `docs/roadmap.md` section `2.2 Key activities`. Impact:
  implementation must mark the matching text entry done rather than relying
  only on numeric labels.

- Observation: creating history entries in the same transaction as new profile
  and template rows requires explicit `flush()` before history insertion in
  this schema. Evidence: foreign-key violations from `series_profile_history`
  and `episode_template_history` inserts before parent row flush. Impact:
  service flow now persists parent row, flushes, then writes history.

## Decision log

- Decision: keep this ExecPlan aligned to the requested filename
  `docs/execplans/2-2-6-series-profile-and-episode-template-models.md` while
  grounding completion against the current roadmap text. Rationale: preserves
  requested artifact naming without risking checklist drift. Date/Author:
  2026-02-20 / Codex.

- Decision: treat REST endpoints as inbound adapters over domain services, not
  as direct SQLAlchemy handlers. Rationale: preserves hexagonal boundaries and
  keeps endpoint tests focused on API contract and orchestration. Date/Author:
  2026-02-20 / Codex.

- Decision: set `make test` to default `PYTEST_XDIST_WORKERS=1` so py-pglite
  backed tests run deterministically under xdist without cross-worker process
  termination. Rationale: py-pglite startup kills existing managed processes,
  which can terminate sibling workers and produce non-deterministic failures.
  Date/Author: 2026-02-20 / Codex.

## Outcomes & retrospective

Delivered outcomes:

- Implemented `EpisodeTemplate`, `SeriesProfileHistoryEntry`, and
  `EpisodeTemplateHistoryEntry` domain models.
- Added repository ports and SQLAlchemy adapters for templates and immutable
  change-history tables.
- Added migration
  `alembic/versions/20260220_000002_add_profile_template_history_schema.py`.
- Added profile/template services with revision-based optimistic locking and
  structured-brief assembly.
- Added Falcon ASGI endpoints in `episodic/api/app.py` for create/get/list/
  update/history and brief retrieval.
- Added unit tests, endpoint integration tests, and pytest-bdd behavioural
  tests for the new API surface.
- Updated
  `docs/episodic-podcast-generation-system-design.md`, `docs/users-guide.md`,
  `docs/developers-guide.md`, and marked roadmap entry `2.2.8` done.

Residual work:

- Reference-binding resolution and reusable reference-document integration
  remains in roadmap item `2.2.9`.

## Context and orientation

Current repository state relevant to this task:

- Existing domain and storage include `SeriesProfile` but no implemented
  `EpisodeTemplate` model or repository:
  - `episodic/canonical/domain.py`
  - `episodic/canonical/ports.py`
  - `episodic/canonical/storage/models.py`
  - `episodic/canonical/storage/repositories.py`
  - `episodic/canonical/storage/uow.py`
- Existing migration baseline has no `episode_templates` table:
  - `alembic/versions/20260203_000001_create_canonical_schema.py`
- BDD currently covers repository and ingestion behaviours, not REST API
  surfaces:
  - `tests/features/canonical_repositories.feature`
  - `tests/features/canonical_ingestion.feature`
- Design docs define planned template/profile behaviour and change-history
  expectations, but implementation is incomplete:
  - `docs/episodic-podcast-generation-system-design.md`
  - `docs/roadmap.md`

## Plan of work

### Stage A: define contracts through failing tests first

Add tests that define desired behaviour before production changes.

- Add unit tests for domain and service contracts:
  - `tests/test_series_profile_template_models.py`
  - `tests/test_series_profile_template_services.py`
- Add behavioural tests for REST scenarios:
  - `tests/features/series_profile_template_api.feature`
  - `tests/steps/test_series_profile_template_api_steps.py`
- Add endpoint integration tests if needed for lower-level HTTP assertions:
  - `tests/test_series_profile_template_api.py`

Go/no-go: proceed only after new tests fail for missing model, history, and API
behaviour.

### Stage B: implement persistence model and migration layer

Implement storage and migration support for templates and history.

- Extend domain entities in `episodic/canonical/domain.py` with:
  - `EpisodeTemplate`
  - history entry entities for profile and template revisions
- Extend ports in `episodic/canonical/ports.py` with:
  - `EpisodeTemplateRepository`
  - change-history repository contracts
- Add ORM records and constraints in
  `episodic/canonical/storage/models.py`.
- Add mapper and repository adapters in:
  - `episodic/canonical/storage/mappers.py`
  - `episodic/canonical/storage/repositories.py`
  - `episodic/canonical/storage/uow.py`
- Create Alembic migration under `alembic/versions/` for new tables, indexes,
  and optimistic-lock fields.

Go/no-go: targeted storage tests must pass before API work begins.

### Stage C: implement application services for structured briefs and history

Implement orchestration logic independent of HTTP and SQLAlchemy details.

- Add service module(s), for example:
  - `episodic/canonical/profile_template_service.py`
- Expose use cases:
  - create series profile and template
  - update with optimistic locking
  - list/get change history
  - retrieve structured brief payload for downstream generators
- Keep all external dependencies behind ports.

Go/no-go: unit tests for use-case behaviour and optimistic-lock failures pass.

### Stage D: implement Falcon REST inbound adapters

Introduce API surface as a driving adapter over Stage C services.

- Add Falcon app factory and resources in new API adapter modules, for example:
  - `episodic/http/app.py`
  - `episodic/http/resources/series_profiles.py`
  - `episodic/http/resources/episode_templates.py`
- Define routes for:
  - `POST /series-profiles`
  - `GET /series-profiles/{id}`
  - `PATCH /series-profiles/{id}`
  - `GET /series-profiles/{id}/history`
  - `POST /episode-templates`
  - `GET /episode-templates/{id}`
  - `PATCH /episode-templates/{id}`
  - `GET /episode-templates/{id}/history`
  - `GET /series-profiles/{id}/brief`
- Map optimistic-lock failures to `409 Conflict` and missing resources to
  `404 Not Found`.

Go/no-go: pytest-bdd scenarios and endpoint integration tests pass.

### Stage E: documentation and roadmap updates

Record externally visible behaviour and internal practices.

- Update design decisions and contracts in
  `docs/episodic-podcast-generation-system-design.md`.
- Update end-user behaviour in `docs/users-guide.md`.
- Update developer-facing interfaces and practices in
  `docs/developers-guide.md`.
- Mark the relevant roadmap checklist entry done in `docs/roadmap.md` only
  after implementation and quality gates succeed.

### Stage F: full validation and evidence capture

Run all required quality gates with logs captured via `tee` and
`set -o pipefail`.

Go/no-go: do not complete the feature if any required gate fails.

## Concrete steps

Run from repository root.

1. Baseline and test-first checks:

       git status --short
       rg -n "series profile|episode template|change history|2\\.2\\." docs/roadmap.md docs/episodic-podcast-generation-system-design.md

2. Add or update tests first, then run targeted failures:

       set -o pipefail; uv run pytest -v tests/test_series_profile_template_models.py 2>&1 | tee /tmp/series-template-unit-pre.log
       set -o pipefail; uv run pytest -v tests/steps/test_series_profile_template_api_steps.py 2>&1 | tee /tmp/series-template-bdd-pre.log

3. Implement production changes, then run targeted passes:

       set -o pipefail; uv run pytest -v \
         tests/test_series_profile_template_models.py \
         tests/test_series_profile_template_services.py \
         tests/test_series_profile_template_api.py \
         2>&1 | tee /tmp/series-template-targeted.log
       set -o pipefail; uv run pytest -v tests/steps/test_series_profile_template_api_steps.py 2>&1 | tee /tmp/series-template-bdd.log

4. Run required final gates:

       set -o pipefail; make check-fmt 2>&1 | tee /tmp/series-template-make-check-fmt.log
       set -o pipefail; make typecheck 2>&1 | tee /tmp/series-template-make-typecheck.log
       set -o pipefail; make lint 2>&1 | tee /tmp/series-template-make-lint.log
       set -o pipefail; make test 2>&1 | tee /tmp/series-template-make-test.log

5. Final verification and roadmap completion:

       rg -n "2\\.2\\.[0-9].*series profile and episode template models|2\\.2\\.[0-9].*Define series profile" docs/roadmap.md
       git diff -- docs/roadmap.md docs/users-guide.md docs/developers-guide.md docs/episodic-podcast-generation-system-design.md

Expected success indicators:

- New unit and behavioural tests demonstrate failing-before and passing-after.
- API responses return stable structured brief payloads and history lists.
- Required gates return exit code 0.

## Validation and acceptance

Acceptance requires all of the following:

- Models:
  - Series profile and episode template entities exist with explicit version
    fields and immutable history records.
- API:
  - Endpoints for create/get/list/update/history exist and are exercised in
    pytest and pytest-bdd coverage.
  - Optimistic locking conflicts are deterministic (`409 Conflict` behaviour).
- Structured brief retrieval:
  - Downstream generator input payload is retrievable from REST API and includes
    series plus template sections.
- Docs:
  - Design decisions captured in
    `docs/episodic-podcast-generation-system-design.md`.
  - User-facing behaviour documented in `docs/users-guide.md`.
  - Developer interfaces and practices documented in
    `docs/developers-guide.md`.
- Roadmap:
  - Matching checklist entry is marked done in `docs/roadmap.md`.
- Gates:
  - `make check-fmt` passes.
  - `make typecheck` passes.
  - `make lint` passes.
  - `make test` passes.

## Idempotence and recovery

- Migration generation should be repeatable while developing; if multiple
  drafts are created, keep only the final Alembic revision in the branch.
- Tests and gates are safe to rerun; each run should overwrite log files in
  `/tmp` to avoid stale evidence.
- If a migration or contract direction is found to be wrong mid-implementation,
  stop, log the issue in `Decision Log`, and re-baseline from failing tests
  before resuming.

## Artifacts and notes

When implementation starts, capture concise excerpts from:

- `/tmp/series-template-unit-pre.log`
- `/tmp/series-template-bdd-pre.log`
- `/tmp/series-template-targeted.log`
- `/tmp/series-template-bdd.log`
- `/tmp/series-template-make-check-fmt.log`
- `/tmp/series-template-make-typecheck.log`
- `/tmp/series-template-make-lint.log`
- `/tmp/series-template-make-test.log`

## Interfaces and dependencies

Planned interface additions (names may be adjusted during implementation, but
domain-first layering is required):

- Domain entities in `episodic/canonical/domain.py`:
  - `EpisodeTemplate`
  - `SeriesProfileHistoryEntry`
  - `EpisodeTemplateHistoryEntry`
- Port interfaces in `episodic/canonical/ports.py`:
  - `EpisodeTemplateRepository`
  - `SeriesProfileHistoryRepository`
  - `EpisodeTemplateHistoryRepository`
  - `CanonicalUnitOfWork` extension exposing the new repositories.
- Application service contract in a dedicated module:
  - create/update/get/list/history operations for both resources
  - structured brief assembly function for downstream generators
- API adapter contracts:
  - Falcon request/response schemas mapped to domain DTOs without leaking
    storage-layer records.

## Revision note

- 2026-02-20: Initial draft created for requested implementation planning scope.
- 2026-02-20: Updated to reflect implementation progress, discovered FK-flush
  ordering requirement, and completion status.
