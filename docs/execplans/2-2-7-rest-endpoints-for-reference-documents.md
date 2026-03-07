# Implement REST endpoints for reusable reference documents

This Execution Plan (ExecPlan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

No `PLANS.md` file is present in the repository root.

Status: COMPLETE

## Purpose and big picture

This change delivers roadmap item `2.2.7` by adding a public REST
(Representational State Transfer) API for reusable reference documents. It must
cover three entities already introduced in `2.2.6`: `ReferenceDocument`,
`ReferenceDocumentRevision`, and `ReferenceBinding`.

After implementation, editors and downstream clients can create, read, list,
and update reusable reference documents, manage revision/binding workflows,
retrieve document change history, and access host/guest profile documents in a
series-aligned way.

Success is observable when:

1. A published API specification exists for reusable reference-document
   endpoints, request payloads, pagination, and error contracts.
2. Endpoints for create/get/list/update are implemented for
   `ReferenceDocument`.
3. Revision and binding workflows are implemented via dedicated REST endpoints.
4. Optimistic-locking behaviour is validated through automated tests.
5. Change-history retrieval tests pass.
6. Host/guest profile access tests pass for series-aligned documents.
7. Documentation is updated in:
   - `docs/episodic-podcast-generation-system-design.md`
   - `docs/users-guide.md`
   - `docs/developers-guide.md`
8. `docs/roadmap.md` marks item `2.2.7` done only after all required gates are
   green.
9. Required quality gates pass:
   - `make check-fmt`
   - `make typecheck`
   - `make lint`
   - `make test`

## Constraints

- Preserve hexagonal architecture invariants from the
  `hexagonal-architecture` skill:
  - Domain and service layers remain framework-agnostic.
  - Ports are owned by the domain/application layer.
  - Falcon and SQLAlchemy details remain in adapters.
  - Adapters do not call each other directly.
- Keep `2.2.7` scoped to API and repository behaviour only.
  No production Service Level Agreement (SLA) tuning is in scope.
- Preserve `2.2.6` model intent and existing repository invariants.
- Keep migrations additive and compatible with existing canonical data.
- Treat optimistic locking as mandatory for update operations.
- Use test-first workflow for all functionality in scope:
  - write/modify tests first,
  - run tests to confirm failure,
  - implement code,
  - rerun tests to confirm pass.
- Maintain and extend existing asynchronous Falcon + SQLAlchemy patterns from:
  - `docs/async-sqlalchemy-with-pg-and-falcon.md`
  - `docs/testing-async-falcon-endpoints.md`
  - `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`
- Respect roadmap sequencing exactly:
  - database schema and migrations,
  - optimistic-locking semantics,
  - endpoint implementation,
  - change-history retrieval,
  - host/guest profile access paths.
- Do not mark `2.2.7` done in `docs/roadmap.md` until implementation,
  validation, and documentation updates are complete.

## Tolerances (exception triggers)

- Scope: stop and escalate if implementation exceeds 24 files or 1800 net
  lines.
- Public contract: stop and escalate if existing profile/template endpoint
  contracts must change incompatibly.
- Dependencies: stop and escalate if implementing `2.2.7` requires introducing
  new external runtime dependencies.
- Authn/authz dependency: stop and escalate if required authentication or
  authorization policy interfaces cannot be located or agreed in this
  repository.
- Migration safety: stop and escalate if the migration plan requires
  destructive rewriting of existing reference-document records.
- Iterations: stop and escalate after 3 failed attempts on the same failing
  test cluster.
- Ambiguity: stop and escalate when multiple valid endpoint contract designs
  remain and would produce materially different client Software Development Kit
  (SDK) contracts.

## Risks

- Risk: Optimistic locking for `ReferenceDocument` is not yet represented in
  current persistence schema. Severity: high. Likelihood: high. Mitigation:
  introduce explicit lock token (revision/version column and conflict-safe
  update path), then cover conflict semantics in repository, service, API, and
  behavioural tests.

- Risk: API pagination behaviour may diverge across document, revision, and
  binding list endpoints. Severity: medium. Likelihood: medium. Mitigation:
  define one pagination contract in the published API spec and reuse shared
  parsing/validation helpers.

- Risk: Host/guest profile access can leak cross-series data if ownership
  checks are missing. Severity: high. Likelihood: medium. Mitigation: enforce
  owner-series checks in service/repository filters and add negative tests for
  cross-series access.

- Risk: Existing reusable reference documents may need backfill defaults for
  new lock/version columns. Severity: medium. Likelihood: medium. Mitigation:
  use additive migration defaults, verify migration with fixture data, and
  document backfill expectations.

- Risk: Client SDK updates are a dependency but SDK code is not in this repo.
  Severity: medium. Likelihood: high. Mitigation: publish explicit
  request/response contract in design docs and include payload examples to
  unblock downstream SDK teams.

## Progress

- [x] (2026-03-03 23:21Z) Drafted ExecPlan for roadmap item `2.2.7` in
  `docs/execplans/2-2-7-rest-endpoints-for-reference-documents.md`.
- [x] (2026-03-04 09:05Z) Added fail-first unit, integration, and behavioural
  tests for reusable reference-document endpoints and workflows.
- [x] (2026-03-04 09:37Z) Implemented reusable reference service layer, API
  resources, serializers, route wiring, and storage updates.
- [x] Stage A complete: API specification and fail-first tests drafted.
- [x] Stage B complete: schema/migration updates for locking and workflow
  retrieval support.
- [x] Stage C complete: optimistic-lock semantics implemented and validated.
- [x] Stage D complete: REST endpoints implemented for document/revision/
  binding workflows.
- [x] Stage E complete: change-history retrieval behaviour implemented and
  validated.
- [x] Stage F complete: host/guest profile access paths implemented and
  validated.
- [x] (2026-03-04 16:22Z) Stage G complete: docs updated, roadmap entry marked
  done, and all quality gates green.

## Surprises & discoveries

- Observation: `2.2.6` is complete and already introduced reusable
  reference-document domain models, repositories, and migration
  (`20260228_000004`). Evidence: `docs/roadmap.md`,
  `episodic/canonical/domain.py`,
  `episodic/canonical/storage/reference_repositories.py`,
  `alembic/versions/20260228_000004_add_reference_document_model.py`. Impact:
  `2.2.7` should build on existing model/repository foundations rather than
  reworking them.

- Observation: current API only exposes series-profile and episode-template
  endpoints. Evidence: `episodic/api/app.py`, `episodic/api/resources/`.
  Impact: reusable reference endpoints are net-new inbound adapters.

- Observation: no concrete authn/authz adapter implementation is currently
  visible under `episodic/api` or `episodic/canonical`. Evidence: repository
  search for auth policy symbols. Impact: dependency handling for authn/authz
  needs explicit alignment before implementation proceeds beyond draft.

- Observation: reusable reference repositories support list/get/update today,
  but no service layer or API serializers exist for these entities. Evidence:
  `episodic/canonical/storage/reference_repositories.py` versus
  `episodic/canonical/profile_templates/` service structure. Impact: new
  application services should mirror profile/template patterns.

- Observation: behavioural test collection can fail when runtime evaluation
  resolves type annotations to symbols imported only in `TYPE_CHECKING`.
  Evidence: initial `NameError` raised against `testing.TestClient` annotations
  during `pytest-bdd` collection. Impact: step modules must use postponed
  annotations (or runtime imports) for test-client type hints.

## Decision log

- Decision: implement `2.2.7` as a new service + resource stack parallel to
  profile/template APIs, reusing existing shared handler patterns where
  practical. Rationale: keeps the architecture consistent and minimizes adapter
  drift. Date/Author: 2026-03-03 / Codex.

- Decision: sequence work exactly as required by roadmap dependencies, with
  explicit go/no-go validation at each stage. Rationale: reduces regressions
  and keeps locking semantics and schema changes proven before public endpoint
  wiring. Date/Author: 2026-03-03 / Codex.

- Decision: treat change-history retrieval for reusable references as revision
  history retrieval centred on `ReferenceDocumentRevision` list/get flows.
  Rationale: revision entities are immutable and already modelled as the
  canonical history mechanism for reference content. Date/Author: 2026-03-03 /
  Codex.

- Decision: scope document CRUD and revision-history routes under
  `/series-profiles/{profile_id}` while keeping revision and binding direct
  lookup routes globally addressable. Rationale: series-scoped paths enforce
  owner alignment for host/guest documents, while global lookup routes preserve
  stable identifiers for SDK consumers. Date/Author: 2026-03-04 / Codex.

- Decision: standardize pagination to `limit`/`offset` with defaults
  (`limit=20`, `offset=0`) and maximum `limit=100` across document, revision,
  and binding list routes. Rationale: one envelope contract simplifies clients
  and repository adapter behaviour. Date/Author: 2026-03-04 / Codex.

## Outcomes & retrospective

Implemented outcomes:

- Published reusable reference-document REST API specification in
  `docs/episodic-podcast-generation-system-design.md`, including pagination and
  error contracts.
- Implemented create/get/list/update endpoints for `ReferenceDocument`, plus
  revision and binding workflows.
- Added optimistic-locking support via `lock_version` migration and
  repository-level compare-and-update semantics.
- Added unit, integration, and behavioural tests validating optimistic-lock
  conflicts, revision history retrieval, and host/guest series-aligned access.
- Updated `docs/users-guide.md` and `docs/developers-guide.md` with user-facing
  and internal API behaviour.
- Marked roadmap item `2.2.7` done in `docs/roadmap.md`.
- Passed required quality gates:
  - `make check-fmt`
  - `make typecheck`
  - `make lint`
  - `make test`
  - `PATH=/root/.bun/bin:$PATH make markdownlint`
  - `make nixie`

## Context and orientation

Existing relevant code and docs:

- Domain and repository contracts:
  - `episodic/canonical/domain.py`
  - `episodic/canonical/ports.py`
  - `episodic/canonical/storage/reference_models.py`
  - `episodic/canonical/storage/reference_repositories.py`
  - `episodic/canonical/storage/uow.py`
- Existing API adapter patterns:
  - `episodic/api/app.py`
  - `episodic/api/resources/base.py`
  - `episodic/api/resources/series_profiles.py`
  - `episodic/api/resources/episode_templates.py`
  - `episodic/api/helpers.py`
  - `episodic/api/handlers.py`
  - `episodic/api/serializers.py`
- Existing tests and fixtures:
  - `tests/test_profile_template_api.py`
  - `tests/features/profile_template_api.feature`
  - `tests/steps/test_profile_template_api_steps.py`
  - `tests/canonical_storage/test_reference_documents.py`
  - `tests/conftest.py`
- Existing documentation requirements and acceptance criteria:
  - `docs/roadmap.md` item `2.2.7`
  - `docs/episodic-podcast-generation-system-design.md`
  - `docs/users-guide.md`
  - `docs/developers-guide.md`

## Plan of work

### Stage A: publish API contract and encode fail-first behaviour

Define and publish reusable reference endpoint contracts before implementation.
Update `docs/episodic-podcast-generation-system-design.md` with a dedicated
spec section for these endpoints:

- `POST /series-profiles/{profile_id}/reference-documents`
- `GET /series-profiles/{profile_id}/reference-documents`
- `GET /series-profiles/{profile_id}/reference-documents/{document_id}`
- `PATCH /series-profiles/{profile_id}/reference-documents/{document_id}`
  (optimistic lock)
- `POST /series-profiles/{profile_id}/reference-documents/{document_id}/revisions`
- `GET /series-profiles/{profile_id}/reference-documents/{document_id}/revisions`
- `GET /reference-document-revisions/{revision_id}`
- `POST /reference-bindings`
- `GET /reference-bindings`
- `GET /reference-bindings/{binding_id}`

Define pagination in this spec (for example `limit`/`offset`, default page
size, max page size) and required error status mapping (`400`, `404`, `409`).

Before writing production code, add failing tests:

- Unit tests for service contracts and locking behaviour.
- Integration tests for endpoint contracts and pagination.
- Behavioural tests (`pytest-bdd`) for end-to-end document/revision/binding
  workflows, conflict scenarios, history retrieval, and host/guest access.

Go/no-go: all newly added tests fail for missing functionality, and the API
spec section is committed in draft form.

### Stage B: database schema and migration updates

Implement additive schema updates required for endpoint semantics and
optimistic locking:

- Add lock/version support for mutable `ReferenceDocument` updates.
- Add any supporting indexes needed for paginated list operations and history
  retrieval performance at the repository level.
- Add migration steps for existing reusable documents (default lock value,
  invariant-safe backfill).

Files expected:

- `episodic/canonical/storage/reference_models.py`
- `episodic/canonical/storage/models.py` (if shared constants change)
- `episodic/canonical/storage/reference_document_schema.py`
- `alembic/versions/<new_revision>.py`
- `tests/features/schema_migrations.feature` and/or migration-focused tests.

Go/no-go: migration tests and reference repository integration tests pass after
schema changes.

### Stage C: optimistic-locking semantics in services and repositories

Add reusable reference application services that encapsulate locking and
invariants, similar to `episodic/canonical/profile_templates/services/`.

Planned additions:

- New package for reusable reference services, for example
  `episodic/canonical/reference_documents/`.
- Typed request/data objects for create/update/bind operations.
- Conflict-safe update flow that validates `expected_revision` and raises typed
  conflict errors mapped to HTTP `409`.
- Domain-level checks for host/guest ownership and target-kind constraints.

Go/no-go: unit tests for service-level optimistic locking, invariants, and
cross-series protections pass.

### Stage D: endpoint implementation (document/revision/binding workflows)

Implement Falcon inbound adapters for reusable references.

Planned file changes:

- `episodic/api/resources/reference_documents.py` (new)
- `episodic/api/resources/reference_bindings.py` (new)
- `episodic/api/serializers.py` (new serializers)
- `episodic/api/resources/__init__.py`
- `episodic/api/app.py` (route wiring)

Ensure list endpoints honour the published pagination contract.

Go/no-go: endpoint integration tests for create/get/list/update and
revision-binding workflows pass.

### Stage E: change-history retrieval

Implement and validate history retrieval behaviour for reusable references via
revision endpoints:

- List revisions for one document in stable order.
- Retrieve one revision by identifier.
- Ensure immutable snapshots remain unchanged across document updates.

Go/no-go: change-history retrieval tests (unit + integration + behavioural)
pass.

### Stage F: series-aligned host/guest profile access paths

Validate and enforce host/guest access semantics for series-aligned documents:

- Host and guest kinds are retrievable for owning series.
- Cross-series access is rejected where required by policy or ownership rules.
- Structured brief retrieval remains compatible with reference bindings already
  consumed by profile/template flows.

Go/no-go: host/guest access tests pass, including negative cross-series cases.

### Stage G: documentation, SDK contract notes, and roadmap completion

Complete and align documentation:

- `docs/episodic-podcast-generation-system-design.md`:
  finalize reusable reference REST API specification.
- `docs/users-guide.md`:
  document user-visible workflows for reference documents, revisions, and
  bindings.
- `docs/developers-guide.md`:
  document internal APIs, lock semantics, pagination rules, and testing
  practices.
- `docs/roadmap.md`:
  mark `2.2.7` done after all acceptance criteria and validation gates pass.

Also include explicit payload and pagination contract notes for client SDK
consumers.

Go/no-go: documentation accurately reflects behaviour and all gates are green.

## Concrete steps

Run all commands from the repository root.

1. Baseline and discovery:

```shell
set -o pipefail; git status --short 2>&1 | tee /tmp/impl-2-2-7-git-status.log
set -o pipefail; rg -n "2\.2\.7|reference document" docs/roadmap.md docs/episodic-podcast-generation-system-design.md \
  2>&1 | tee /tmp/impl-2-2-7-roadmap-spec-scan.log
```

1. Test-first red phase (examples; extend with actual new test file names):

```shell
set -o pipefail; uv run pytest -v tests/test_reference_document_roundtrip.py \
  tests/test_reference_document_validation.py tests/test_reference_document_access.py \
  2>&1 | tee /tmp/impl-2-2-7-red-unit-integration.log
set -o pipefail; uv run pytest -v tests/steps/test_reference_document_api_steps.py \
  2>&1 | tee /tmp/impl-2-2-7-red-bdd.log
```

1. Stage-by-stage targeted green checks:

```shell
set -o pipefail; uv run pytest -v tests/canonical_storage/test_reference_documents.py \
  2>&1 | tee /tmp/impl-2-2-7-storage-green.log
set -o pipefail; uv run pytest -v tests/test_reference_document_roundtrip.py \
  tests/test_reference_document_validation.py tests/test_reference_document_access.py \
  2>&1 | tee /tmp/impl-2-2-7-api-green.log
set -o pipefail; uv run pytest -v tests/steps/test_reference_document_api_steps.py \
  2>&1 | tee /tmp/impl-2-2-7-bdd-green.log
```

1. Final required quality gates:

```shell
set -o pipefail; make check-fmt 2>&1 | tee /tmp/impl-2-2-7-make-check-fmt.log
set -o pipefail; make typecheck 2>&1 | tee /tmp/impl-2-2-7-make-typecheck.log
set -o pipefail; make lint 2>&1 | tee /tmp/impl-2-2-7-make-lint.log
set -o pipefail; make test 2>&1 | tee /tmp/impl-2-2-7-make-test.log
```

1. Markdown/documentation gates for doc updates:

```shell
set -o pipefail; PATH=/root/.bun/bin:$PATH make markdownlint 2>&1 | tee /tmp/impl-2-2-7-make-markdownlint.log
set -o pipefail; make nixie 2>&1 | tee /tmp/impl-2-2-7-make-nixie.log
```

Expected success indicators:

- New tests fail before implementation and pass after implementation.
- API endpoints return documented payloads and status codes.
- Optimistic-lock conflicts produce deterministic `409 Conflict` responses.
- History retrieval and host/guest access tests pass.
- All required make gates exit with status `0`.

## Validation and acceptance

Acceptance criteria for this milestone are complete only when all items below
are true:

- API specification is published in design docs.
- `ReferenceDocument` endpoints support create/get/list/update.
- Revision workflows support create/get/list and preserve immutable history.
- Binding workflows support create/get/list with target invariants.
- Optimistic-lock behaviour is validated by tests.
- Change-history retrieval tests pass.
- Host/guest profile access tests pass for series-aligned documents.
- User and developer docs are updated.
- Roadmap entry `2.2.7` is marked done.
- Required quality gates pass:
  - `make check-fmt`
  - `make typecheck`
  - `make lint`
  - `make test`

## Idempotence and recovery

- All steps are designed to be re-runnable.
- Migrations must be additive and safely rerun on clean test databases.
- If a stage fails, fix forward and rerun only the stage-local checks first,
  then rerun final full gates.
- Keep `/tmp/impl-2-2-7-*.log` as the evidence trail for red/green and final
  gate status.
- If scope or dependency tolerances are exceeded, stop and update this ExecPlan
  before continuing.

## Artifacts and notes

Expected evidence artifacts:

- `/tmp/impl-2-2-7-git-status.log`
- `/tmp/impl-2-2-7-roadmap-spec-scan.log`
- `/tmp/impl-2-2-7-red-unit-integration.log`
- `/tmp/impl-2-2-7-red-bdd.log`
- `/tmp/impl-2-2-7-storage-green.log`
- `/tmp/impl-2-2-7-api-green.log`
- `/tmp/impl-2-2-7-bdd-green.log`
- `/tmp/impl-2-2-7-make-check-fmt.log`
- `/tmp/impl-2-2-7-make-typecheck.log`
- `/tmp/impl-2-2-7-make-lint.log`
- `/tmp/impl-2-2-7-make-test.log`
- `/tmp/impl-2-2-7-make-markdownlint.log`
- `/tmp/impl-2-2-7-make-nixie.log`

## Interfaces and dependencies

Planned interfaces and modules (subject to implementation-stage validation):

- New reusable reference service interfaces and typed requests:
  - `create_reference_document`
  - `get_reference_document`
  - `list_reference_documents`
  - `update_reference_document`
  - `create_reference_document_revision`
  - `list_reference_document_revisions`
  - `get_reference_document_revision`
  - `create_reference_binding`
  - `list_reference_bindings`
  - `get_reference_binding`
- API serializers for all three entity payload types.
- Per-resource pagination parsing and reusable-reference error mapping in new
  Falcon resources.
- Dependency assumptions to confirm before implementation:
  - authn/authz policy contract and enforcement hooks,
  - migration plan for existing reusable documents,
  - SDK-facing payload contract publication path.

## Revision note

- 2026-03-03: Initial draft created for roadmap item `2.2.7` with required
  sequencing, test strategy, docs updates, and quality-gate commands.
- 2026-03-04: Updated status to `IN PROGRESS`; recorded implemented service,
  repository, migration, API, and test progress. Stage G remains open pending
  full quality gates and roadmap completion update.
- 2026-03-04: Updated status to `COMPLETE`; confirmed Stage G completion with
  full gate success and roadmap item `2.2.7` marked done.
