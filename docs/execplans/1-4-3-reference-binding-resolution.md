# Implement reference-binding resolution

This Execution Plan (ExecPlan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

No `PLANS.md` file is present in the repository root.

Status: DRAFT

## Purpose and big picture

This change delivers roadmap item `1.4.3` by implementing reference-binding
resolution, the mechanism that determines which pinned
`ReferenceDocumentRevision` applies to a given consuming context (ingestion
run, series profile, or episode template) and preserves provenance snapshots in
ingestion records.

After implementation, the system will:

1. Resolve which reference-document revision applies to a given episode when
   multiple `ReferenceBinding` rows exist with different
   `effective_from_episode_id` values on a series-profile target. The
   resolution algorithm selects the binding whose `effective_from_episode_id`
   is closest to (but not after) the target episode, falling back to bindings
   with no `effective_from_episode_id` (meaning "applies to all episodes").
2. Enable ingestion runs to snapshot resolved reference-document revisions as
   `source_documents` records, creating a provenance trail that links each
   ingestion job to the exact reference content it consumed.
3. Expose resolution behaviour through the existing
   `GET /series-profiles/{profile_id}/brief` endpoint, which will accept an
   optional `episode_id` query parameter to control which episode context
   drives `effective_from_episode_id` precedence.
4. Expose a new dedicated resolution endpoint
   `GET /series-profiles/{profile_id}/resolved-bindings` that returns the
   resolved set of bindings for a profile/template/episode combination without
   the full brief payload.

Success is observable when:

1. The binding resolution algorithm correctly selects the most specific
   applicable binding per reference-document kind for a given episode context.
2. Bindings without `effective_from_episode_id` act as defaults when no
   episode-specific binding exists.
3. Ingestion records include `source_documents` rows with
   `reference_document_revision_id` populated, preserving the exact revision
   consumed.
4. The brief endpoint applies resolution when `episode_id` is provided.
5. Unit tests, integration tests, and behavioural tests (pytest-bdd) validate
   resolution precedence, provenance snapshotting, and API behaviour.
6. Documentation is updated in
   `docs/episodic-podcast-generation-system-design.md`,
   `docs/users-guide.md`, and `docs/developers-guide.md`.
7. An Architectural Decision Record (ADR) documents the resolution algorithm
   design.
8. `docs/roadmap.md` marks item `1.4.3` done after all required gates are
   green.
9. Required quality gates pass: `make check-fmt`, `make typecheck`,
   `make lint`, `make test`.

## Constraints

- Preserve hexagonal architecture invariants from the `hexagonal-architecture`
  skill:
  - Domain and service layers remain framework-agnostic.
  - Ports are owned by the domain/application layer.
  - Falcon and SQLAlchemy details remain in adapters.
  - Adapters do not call each other directly.
- Keep `1.4.3` scoped to repository and API behaviour only, as stated in the
  roadmap. No production Service-Level Agreement (SLA) tuning, no Celery worker
  integration, and no LangGraph pipeline changes are in scope.
- Preserve existing `ReferenceBinding` domain invariants:
  - Exactly one target identifier populated per binding.
  - `target_kind` matches the populated target field.
  - `effective_from_episode_id` only valid for `series_profile` bindings.
- Preserve existing API contracts: all current endpoints must continue to
  behave identically. The brief endpoint gains optional `episode_id` query
  parameter behaviour; omitting it preserves current behaviour (all bindings
  returned without resolution filtering).
- Use test-first workflow for all functionality in scope: write/modify tests
  first, run tests to confirm failure, implement code, rerun tests to confirm
  pass.
- Maintain existing asynchronous Falcon + SQLAlchemy patterns from:
  - `docs/async-sqlalchemy-with-pg-and-falcon.md`
  - `docs/testing-async-falcon-endpoints.md`
  - `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`
- Migrations must be additive and compatible with existing canonical data.
- Vidai Mock is not required for this task: no LLM inference services are
  exercised by reference-binding resolution. The roadmap instruction to "use
  Vidai Mock for behavioural testing of inference services" applies to tasks
  that interact with the LLM port, which this task does not.

## Tolerances (exception triggers)

- Scope: stop and escalate if implementation exceeds 20 files or 1500 net
  lines of code.
- Public contract: stop and escalate if existing endpoint contracts (other than
  the additive `episode_id` query parameter on the brief endpoint) must change
  incompatibly.
- Dependencies: stop and escalate if implementing `1.4.3` requires introducing
  new external runtime dependencies beyond what is already in `pyproject.toml`.
- Migration safety: stop and escalate if the migration plan requires
  destructive rewriting of existing `source_documents` records.
- Iterations: stop and escalate after 3 failed attempts on the same failing
  test cluster.
- Ambiguity: stop and escalate when multiple valid resolution algorithm
  designs remain and would produce materially different consumer behaviour.

## Risks

- Risk: The `source_documents` table does not currently have a
  `reference_document_revision_id` column, though the Entity-Relationship (ER)
  diagram in the system design document shows one. Adding it requires an
  Alembic migration. Severity: medium. Likelihood: high. Mitigation: add a
  nullable `reference_document_revision_id` foreign key column via an additive
  migration. Existing rows retain `NULL`. New provenance snapshots populate the
  column.

- Risk: The resolution algorithm for `effective_from_episode_id` requires
  episode ordering semantics. Episodes must have a stable ordering (by
  `created_at` or sequence number) to determine "closest but not after".
  Severity: medium. Likelihood: medium. Mitigation: use episode `created_at` as
  the ordering dimension. If episodes have explicit sequence numbers, prefer
  those. Investigate the `episodes` table schema to confirm available ordering
  fields before implementing.

- Risk: The brief endpoint currently returns all bindings without resolution.
  Changing this default behaviour could break existing consumers. Severity:
  high. Likelihood: medium. Mitigation: resolution filtering is only applied
  when `episode_id` is explicitly provided. When omitted, the brief continues
  to return all bindings (preserving backward compatibility).

- Risk: Adding `reference_document_revision_id` to `SourceDocument` and
  `SourceDocumentInput` domain entities changes their shape. Severity: medium.
  Likelihood: high. Mitigation: use optional (nullable) field with default
  `None` to avoid breaking existing ingestion pathways that do not resolve
  bindings.

## Progress

- [ ] Initial ExecPlan draft completed.
- [ ] Stage A: codebase investigation and algorithm design.
- [ ] Stage B: migration and domain model updates.
- [ ] Stage C: resolution service implementation with fail-first tests.
- [ ] Stage D: API endpoint updates and integration tests.
- [ ] Stage E: provenance snapshotting in ingestion records.
- [ ] Stage F: behavioural tests (pytest-bdd).
- [ ] Stage G: documentation, ADR, and roadmap completion.

## Surprises and discoveries

(None yet. This section will be updated as implementation proceeds.)

## Decision log

(No decisions recorded yet. This section will be updated as implementation
proceeds.)

## Outcomes and retrospective

(Not yet complete. This section will be populated at major milestones and on
completion.)

## Context and orientation

This section describes the current state of the codebase relevant to
reference-binding resolution. All paths are repository-relative.

### Domain model (`episodic/canonical/domain.py`)

Three domain entities are already defined:

- `ReferenceDocument` (line 148): stable identity with
  `owner_series_profile_id`,
  `kind` (one of `style_guide`, `host_profile`, `guest_profile`,
  `research_brief`), `lifecycle_state`, `metadata`, and `lock_version`.
- `ReferenceDocumentRevision` (line 168): immutable content snapshot with
  `reference_document_id`, `content` (JSON mapping), `content_hash`, `author`,
  and `change_note`.
- `ReferenceBinding` (line 187): associates a revision with exactly one target
  (series profile, episode template, or ingestion job) via three nullable
  target identifier fields plus `target_kind` and optional
  `effective_from_episode_id`.

The `SourceDocument` domain entity (line 134) currently has `ingestion_job_id`,
`source_type`, `source_uri`, `weight`, `content_hash`, and `metadata` but no
`reference_document_revision_id`.

The `SourceDocumentInput` (line 264) is the input payload for creating source
documents during ingestion. It similarly lacks a
`reference_document_revision_id`.

### Port contracts (`episodic/canonical/ports.py`)

Repository protocols for all three reference entities are complete:

- `ReferenceDocumentRepository`: `add`, `get`, `list_for_series`, `list_by_ids`,
  `update`, `update_with_optimistic_lock`.
- `ReferenceDocumentRevisionRepository`: `add`, `get`, `list_for_document`,
  `list_by_ids`, `get_latest_for_document`.
- `ReferenceBindingRepository`: `add`, `get`, `list_for_target`.

The `SourceDocumentRepository` (line 251) exposes `add` and `list_for_job` only.

The `CanonicalUnitOfWork` (line 530) wires all twelve repository members.

### Service layer (`episodic/canonical/reference_documents/`)

A complete Create/Read/Update/Delete (CRUD) service layer exists across four
modules:

- `documents.py`: create, get, list, update with optimistic locking.
- `revisions.py`: create, get, list revisions.
- `bindings.py`: create, get, list bindings with full target alignment
  validation.
- `helpers.py`: shared parsing, validation, and error extraction utilities.

There is no resolution service yet. Resolution (determining which binding
"wins" for a given episode context) is the core deliverable of this plan.

### Brief assembly (`episodic/canonical/profile_templates/brief.py`)

`build_series_brief` (line 268) assembles a structured brief payload with keys
`series_profile`, `episode_templates`, and `reference_documents`. The reference
documents section is populated by `_load_reference_documents_for_brief`, which
loads all bindings for the series profile and each template without filtering
or precedence logic. Every binding is included regardless of
`effective_from_episode_id`.

### Storage layer

- ORM models in `episodic/canonical/storage/reference_models.py` implement
  all three reference entities with partial unique indexes on bindings.
- `SourceDocumentRecord` in `episodic/canonical/storage/models.py` (line 344)
  maps to the `source_documents` table but has no
  `reference_document_revision_id` column.
- Repository implementations in
  `episodic/canonical/storage/reference_repositories.py` implement all port
  methods.

### Ingestion pipeline (`episodic/canonical/ingestion_service.py`)

The `ingest_multi_source` function normalizes, weights, resolves conflicts, and
persists source documents via `ingest_sources`. It does not resolve reference
bindings or snapshot revision content. The `IngestionRequest` (line 275 of
`domain.py`) carries `tei_xml`, `sources` (list of `SourceDocumentInput`), and
`requested_by`.

### API layer

All reference-document endpoints are wired in `episodic/api/app.py`:

- Document CRUD under `/series-profiles/{profile_id}/reference-documents/...`
- Revision operations under `.../revisions`
- Binding operations at `/reference-bindings/...`
- Brief endpoint at `/series-profiles/{profile_id}/brief`

### Test coverage

Extensive test coverage exists for CRUD operations, optimistic locking,
validation, alignment, and conflict handling. Behavioural tests exist in
`tests/features/reference_document_api.feature` and
`tests/features/reference_document_model.feature`. No tests currently cover
binding resolution logic.

## Plan of work

### Stage A: investigation and algorithm design

Investigate the `episodes` table to confirm ordering semantics (presence of
`created_at`, sequence number, or other ordering field). Investigate the
existing `list_for_target` repository method to determine if it supports
ordering by `effective_from_episode_id`. Document the resolution algorithm in
an ADR.

The resolution algorithm works as follows:

1. Collect all bindings for a given target (series profile or episode template).
2. Group bindings by their parent `ReferenceDocument` (via
   `reference_document_revision_id` to `ReferenceDocumentRevision` to
   `ReferenceDocument`).
3. For each document, resolve which binding applies:
   - If the consuming context includes an episode identifier, select the
     binding whose `effective_from_episode_id` is the latest one that is on or
     before the target episode (by episode ordering). This means the binding
     "took effect" for that episode and has not been superseded.
   - If no episode-specific binding matches, fall back to bindings with
     `effective_from_episode_id = NULL` (the default/catch-all binding).
   - If no binding applies at all for a given document, that document is
     excluded from the resolved set.
4. For episode-template bindings, `effective_from_episode_id` is not supported
   (enforced by domain invariant), so all template bindings are included
   directly.
5. Merge the resolved series-profile bindings with the template bindings.

The resolution function must not duplicate bindings: if the same revision is
bound to both the series profile and a template, both bindings appear (they
represent different target contexts).

Go/no-go: the ADR is written and committed, episode ordering semantics are
confirmed, and the algorithm design is unambiguous.

### Stage B: migration and domain model updates

Add a nullable `reference_document_revision_id` column to the
`source_documents` table via an additive Alembic migration. Update the
`SourceDocumentRecord` ORM model and the `SourceDocument` domain entity with an
optional `reference_document_revision_id: uuid.UUID | None` field defaulting to
`None`. Update `SourceDocumentInput` similarly.

Files expected to change:

- `alembic/versions/<new_revision>_add_reference_revision_to_source_documents.py`
  (new).
- `episodic/canonical/storage/models.py` (`SourceDocumentRecord`).
- `episodic/canonical/domain.py` (`SourceDocument`, `SourceDocumentInput`).

Go/no-go: the migration runs cleanly, existing tests pass unchanged, and the
new column is visible in the ORM model.

### Stage C: resolution service implementation with fail-first tests

Write failing unit tests for the resolution algorithm first, then implement the
resolution service.

New test files:

- `tests/test_binding_resolution.py`: unit tests for resolution logic covering:
  - Single binding, no `effective_from_episode_id` (default applies).
  - Multiple bindings for the same document with different
    `effective_from_episode_id` values; correct one selected for a given
    episode.
  - Binding with `effective_from_episode_id` that is after the target episode
    is excluded.
  - No applicable binding for a document results in exclusion.
  - Template bindings are included directly without episode filtering.
  - Mixed series-profile and template bindings are merged correctly.
  - Empty binding set produces empty resolution.

New service module:

- `episodic/canonical/reference_documents/resolution.py`: the resolution
  service function `resolve_bindings` that accepts a unit of work, a series
  profile identifier, an optional template identifier, and an optional episode
  identifier, and returns a list of `ResolvedBinding` result objects.

New types:

- `ResolvedBinding` dataclass in
  `episodic/canonical/reference_documents/types.py`: contains the binding,
  revision, and document entities that comprise a resolved binding.

Update the service package re-exports in
`episodic/canonical/reference_documents/services.py`.

Go/no-go: all resolution unit tests pass, and existing tests remain green.

### Stage D: API endpoint updates and integration tests

Update the brief endpoint to support resolution:

- The `SeriesProfileBriefResource.on_get` handler in
  `episodic/api/resources/series_profiles.py` accepts an optional `episode_id`
  query parameter.
- When `episode_id` is provided, `build_series_brief` delegates to the
  resolution service to filter bindings by episode precedence.
- When `episode_id` is omitted, the brief returns all bindings as before
  (backward compatible).

Add a new resolution endpoint:

- `GET /series-profiles/{profile_id}/resolved-bindings` accepts required
  `episode_id` query parameter and optional `template_id`.
- Returns the resolved set of bindings as a JSON array.
- Implement in a new resource class in
  `episodic/api/resources/reference_bindings.py` or a new file
  `episodic/api/resources/resolved_bindings.py`.
- Wire the route in `episodic/api/app.py`.

New and updated test files:

- `tests/test_binding_resolution_api.py`: integration tests for the resolution
  endpoint and the brief endpoint with `episode_id`.

Add a serializer for `ResolvedBinding` in `episodic/api/serializers.py`.

Go/no-go: all API integration tests pass, existing API tests remain green.

### Stage E: provenance snapshotting in ingestion records

Enable ingestion workflows to snapshot resolved reference-document revisions as
`source_documents` rows:

- Add a new service function `snapshot_resolved_bindings` in
  `episodic/canonical/reference_documents/resolution.py` that takes a unit of
  work, a list of `ResolvedBinding` objects, and an ingestion job identifier,
  and creates `SourceDocument` records with the
  `reference_document_revision_id` populated.
- The `source_type` for these snapshots is `"reference_document"`.
- The `source_uri` is derived from the reference document's identity (for
  example, `ref://{document_id}/revisions/{revision_id}`).
- The `content_hash` is the revision's `content_hash`.
- The `metadata` includes the binding target context and
  `effective_from_episode_id` for provenance.

Write failing tests first in `tests/test_binding_resolution.py` or a dedicated
`tests/test_provenance_snapshot.py`, then implement.

Update ports if needed: `SourceDocumentRepository.add` already supports
persisting `SourceDocument` entities. The domain entity change from Stage B
ensures the `reference_document_revision_id` field is carried through.

Go/no-go: provenance snapshot tests pass, and snapshotted source documents are
retrievable via `list_for_job`.

### Stage F: behavioural tests (pytest-bdd)

Write behavioural tests in Gherkin that validate end-to-end resolution
workflows from a user perspective:

- `tests/features/binding_resolution.feature`: scenarios covering:
  - An editorial team binds a style guide revision to a series profile and
    retrieves it via the brief endpoint.
  - The team adds a new revision with `effective_from_episode_id` pointing to a
    future episode. Retrieving the brief for an earlier episode returns the
    original binding; retrieving for the future episode returns the new
    binding.
  - The team creates an ingestion run and verifies that resolved bindings are
    snapshotted as source documents.
  - The team retrieves resolved bindings via the dedicated endpoint.

- `tests/steps/test_binding_resolution_steps.py`: step implementations using
  `httpx.AsyncClient` with `ASGITransport` for API testing.

Go/no-go: all behavioural tests pass.

### Stage G: documentation, ADR, and roadmap completion

Update documentation to reflect binding resolution behaviour:

- `docs/episodic-podcast-generation-system-design.md`:
  - Add a section on binding resolution algorithm and precedence rules.
  - Add the resolved-bindings endpoint to the API specification.
  - Update the brief endpoint specification to document `episode_id`.
- `docs/users-guide.md`:
  - Document how to use `episode_id` on the brief endpoint.
  - Document the resolved-bindings endpoint.
  - Document provenance snapshots in ingestion records.
- `docs/developers-guide.md`:
  - Document the resolution service module and its interface.
  - Document the provenance snapshot mechanism.
  - Document the `reference_document_revision_id` field on source documents.
- Write an ADR documenting the resolution algorithm design decision:
  - Create `docs/adr/` directory if it does not exist.
  - Create `docs/adr/adr-001-reference-binding-resolution-algorithm.md`.
  - Record the context, options considered (simple latest-binding-wins versus
    episode-anchored precedence), and rationale for the chosen approach.
- `docs/roadmap.md`: mark item `1.4.3` done after all acceptance criteria and
  validation gates pass.
- Update `docs/contents.md` if it exists, to reference the new ADR.

Go/no-go: documentation accurately reflects implemented behaviour, and all
markdown and documentation gates are green.

## Concrete steps

Run all commands from the repository root.

1. Baseline and discovery:

   ```shell
   set -o pipefail
   git status --short 2>&1 | tee /tmp/impl-1-4-3-git-status.log
   ```

2. Investigate episode ordering:

   ```shell
   set -o pipefail
   rg -n "class CanonicalEpisode|class EpisodeRecord" \
     episodic/canonical/domain.py episodic/canonical/storage/models.py \
     2>&1 | tee /tmp/impl-1-4-3-episode-schema.log
   ```

3. Test-first red phase (after writing failing tests):

   ```shell
   set -o pipefail
   uv run pytest -v tests/test_binding_resolution.py \
     2>&1 | tee /tmp/impl-1-4-3-red-resolution.log
   set -o pipefail
   uv run pytest -v tests/test_binding_resolution_api.py \
     2>&1 | tee /tmp/impl-1-4-3-red-api.log
   set -o pipefail
   uv run pytest -v tests/steps/test_binding_resolution_steps.py \
     2>&1 | tee /tmp/impl-1-4-3-red-bdd.log
   ```

4. Stage-by-stage targeted green checks:

   ```shell
   set -o pipefail
   uv run pytest -v tests/test_binding_resolution.py \
     2>&1 | tee /tmp/impl-1-4-3-green-resolution.log
   set -o pipefail
   uv run pytest -v tests/test_binding_resolution_api.py \
     2>&1 | tee /tmp/impl-1-4-3-green-api.log
   set -o pipefail
   uv run pytest -v tests/steps/test_binding_resolution_steps.py \
     2>&1 | tee /tmp/impl-1-4-3-green-bdd.log
   ```

5. Final required quality gates:

   ```shell
   set -o pipefail
   make check-fmt 2>&1 | tee /tmp/impl-1-4-3-make-check-fmt.log
   set -o pipefail
   make typecheck 2>&1 | tee /tmp/impl-1-4-3-make-typecheck.log
   set -o pipefail
   make lint 2>&1 | tee /tmp/impl-1-4-3-make-lint.log
   set -o pipefail
   make test 2>&1 | tee /tmp/impl-1-4-3-make-test.log
   ```

6. Markdown and documentation gates:

   ```shell
   set -o pipefail
   make fmt 2>&1 | tee /tmp/impl-1-4-3-make-fmt.log
   set -o pipefail
   PATH=/root/.bun/bin:$PATH make markdownlint \
     2>&1 | tee /tmp/impl-1-4-3-make-markdownlint.log
   set -o pipefail
   make nixie 2>&1 | tee /tmp/impl-1-4-3-make-nixie.log
   ```

Expected success indicators:

- New tests fail before implementation and pass after implementation.
- Resolution endpoint returns the correct binding for a given episode context.
- Brief endpoint with `episode_id` returns filtered bindings.
- Provenance snapshot creates `source_documents` rows with
  `reference_document_revision_id` populated.
- All required make gates exit with status `0`.

## Validation and acceptance

Acceptance criteria for this milestone are complete only when all items below
are true:

- Resolution algorithm correctly selects the most specific applicable binding
  per reference document for a given episode context.
- Bindings without `effective_from_episode_id` act as defaults.
- `source_documents` rows include `reference_document_revision_id` when
  created from resolved bindings.
- The brief endpoint accepts `episode_id` and returns resolved bindings.
- The resolved-bindings endpoint returns the correct resolved set.
- Backward compatibility is preserved: the brief endpoint without `episode_id`
  behaves identically to the current implementation.
- Unit tests cover resolution precedence, edge cases, and provenance
  snapshotting.
- Behavioural tests cover end-to-end editorial workflows.
- An ADR documents the resolution algorithm design.
- User and developer documentation is updated.
- Roadmap entry `1.4.3` is marked done.
- Required quality gates pass:
  - `make check-fmt`
  - `make typecheck`
  - `make lint`
  - `make test`
  - `PATH=/root/.bun/bin:$PATH make markdownlint`
  - `make nixie`

## Idempotence and recovery

- All steps are designed to be re-runnable.
- The Alembic migration is additive (nullable column with no default
  constraint) and safely rerun on clean test databases.
- If a stage fails, fix forward and rerun only the stage-local checks first,
  then rerun final full gates.
- Keep `/tmp/impl-1-4-3-*.log` as the evidence trail for red/green and final
  gate status.
- If scope or dependency tolerances are exceeded, stop and update this ExecPlan
  before continuing.

## Artifacts and notes

Expected evidence artifacts:

- `/tmp/impl-1-4-3-git-status.log`
- `/tmp/impl-1-4-3-episode-schema.log`
- `/tmp/impl-1-4-3-red-resolution.log`
- `/tmp/impl-1-4-3-red-api.log`
- `/tmp/impl-1-4-3-red-bdd.log`
- `/tmp/impl-1-4-3-green-resolution.log`
- `/tmp/impl-1-4-3-green-api.log`
- `/tmp/impl-1-4-3-green-bdd.log`
- `/tmp/impl-1-4-3-make-check-fmt.log`
- `/tmp/impl-1-4-3-make-typecheck.log`
- `/tmp/impl-1-4-3-make-lint.log`
- `/tmp/impl-1-4-3-make-test.log`
- `/tmp/impl-1-4-3-make-fmt.log`
- `/tmp/impl-1-4-3-make-markdownlint.log`
- `/tmp/impl-1-4-3-make-nixie.log`

## Interfaces and dependencies

### Resolution service interface

In `episodic/canonical/reference_documents/resolution.py`, define:

```python
@dc.dataclass(frozen=True, slots=True)
class ResolvedBinding:
    """A resolved binding triple: binding, revision, and document."""

    binding: ReferenceBinding
    revision: ReferenceDocumentRevision
    document: ReferenceDocument


async def resolve_bindings(
    uow: CanonicalUnitOfWork,
    *,
    series_profile_id: uuid.UUID,
    template_id: uuid.UUID | None = None,
    episode_id: uuid.UUID | None = None,
) -> list[ResolvedBinding]:
    """Resolve reference bindings for a series profile context.

    When episode_id is provided, series-profile bindings are
    filtered by effective_from_episode_id precedence. When
    omitted, all bindings are returned (backward compatible).
    """
    ...


async def snapshot_resolved_bindings(
    uow: CanonicalUnitOfWork,
    *,
    resolved: list[ResolvedBinding],
    ingestion_job_id: uuid.UUID,
    canonical_episode_id: uuid.UUID | None = None,
) -> list[SourceDocument]:
    """Snapshot resolved bindings as source_documents rows."""
    ...
```

### Domain model updates

In `episodic/canonical/domain.py`, the `SourceDocument` and
`SourceDocumentInput` dataclasses gain:

```python
reference_document_revision_id: uuid.UUID | None = None
```

### ORM model update

In `episodic/canonical/storage/models.py`, `SourceDocumentRecord` gains:

```python
reference_document_revision_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
    postgresql.UUID(as_uuid=True),
    sa.ForeignKey("reference_document_revisions.id"),
    nullable=True,
    index=True,
)
```

### API endpoint

New route in `episodic/api/app.py`:

```python
app.add_route(
    "/series-profiles/{profile_id}/resolved-bindings",
    ResolvedBindingsResource(uow_factory),
)
```

### Dependencies

No new external dependencies. All implementation uses existing packages:
Falcon, SQLAlchemy, pytest, pytest-bdd, httpx.

## Revision note

- 2026-03-22: Initial draft created for roadmap item `1.4.3` with required
  sequencing, test strategy, documentation updates, ADR, and quality-gate
  commands.
