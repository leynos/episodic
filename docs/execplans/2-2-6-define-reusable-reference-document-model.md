# Define reusable reference-document model and align profile/template contracts

This Execution Plan (ExecPlan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

No `PLANS.md` file is present in the repository root.

Status: COMPLETE

## Purpose and big picture

This implementation establishes canonical, reusable reference documents as a
first-class model independent of ingestion-job scope. It introduces three
domain entities, `ReferenceDocument`, `ReferenceDocumentRevision`, and
`ReferenceBinding`, with repository contracts and storage adapters that support
series-aligned host and guest profile documents.

The change also brings existing 2.2.8 profile/template functionality into line
with this model by making profile/template brief and contract surfaces aware of
reference bindings rather than assuming all contextual content lives only in
`SeriesProfile.configuration` or ingestion-scoped `SourceDocument` records.

Success is observable when:

1. New domain entities, ports, and SQLAlchemy repository adapters are
   implemented and covered by unit and behavioural tests.
2. A new ER diagram for reusable reference documents is approved and checked
   into `docs/episodic-podcast-generation-system-design.md`.
3. Glossary entries exist for all three entities in the design documentation.
4. Repository contract and API contract acceptance criteria are documented in
   the design docs.
5. Existing 2.2.8 behaviour (profile/template history and structured brief
   retrieval) remains green and is aligned with the new reference model.
6. Required gates pass:
   `make check-fmt`, `make typecheck`, `make lint`, and `make test`.
7. The roadmap item `2.2.6` is marked done only after all acceptance criteria
   and gates pass.

## Constraints

- Preserve hexagonal architecture invariants:
  - Domain owns ports and remains framework-free.
  - Adapters implement ports and do not call each other directly.
  - Dependency direction remains inward.
- Keep 2.2.7 scope out of this implementation: no new public REST endpoints
  for reference documents are required here; only model/repository contracts
  and API acceptance criteria documentation are in scope.
- Keep 2.2.9 scope out of this implementation: full runtime binding resolution
  for ingestion execution can be staged later, but this milestone must provide
  the reusable data model and contract hooks required by 2.2.9.
- Maintain existing behaviour for current ingestion flows and profile/template
  APIs unless explicitly changed by new, documented acceptance criteria.
- Follow test-first workflow:
  - add or update tests first,
  - verify failing state,
  - implement changes,
  - verify passing state.
- No new third-party dependencies.
- Documentation updates are mandatory in:
  - `docs/episodic-podcast-generation-system-design.md`
  - `docs/users-guide.md`
  - `docs/developers-guide.md`
  - `docs/roadmap.md`

## Tolerances (exception triggers)

- Scope: stop and escalate if implementation exceeds 22 files or 1700 net
  lines.
- Interface: stop and escalate if existing public API response fields must be
  removed or renamed incompatibly.
- Data migration: stop and escalate if migration requires destructive rewrite
  of existing profile/template history tables rather than additive migration.
- Ambiguity: stop and escalate if host/guest profile ownership semantics are
  unclear (series-level only vs. mixed ownership) after schema spike.
- Iterations: stop and escalate after 3 unsuccessful attempts to stabilize the
  same failing test cluster.

## Risks

- Risk: Overlap between 2.2.6 and already-implemented 2.2.8 could create
  duplicate history/version semantics. Severity: high. Likelihood: medium.
  Mitigation: keep `SeriesProfile`/`EpisodeTemplate` revisions intact, add
  reference-document revisions as a separate concern, and align brief/service
  contracts through explicit binding fields.

- Risk: `ReferenceBinding` target cardinality could drift into ambiguous
  multi-target rows. Severity: high. Likelihood: medium. Mitigation: encode
  invariant in domain and DB constraints so each binding targets exactly one
  context kind (`series_profile`, `episode_template`, or `ingestion_job`) with
  optional `effective_from_episode_id`.

- Risk: Existing profile/template tests may pass while silently ignoring new
  reference semantics. Severity: medium. Likelihood: medium. Mitigation: update
  2.2.8 unit and BDD tests to assert aligned contract behaviour explicitly.

- Risk: Missing glossary location in docs can cause acceptance ambiguity.
  Severity: medium. Likelihood: high. Mitigation: add an explicit glossary
  subsection in the system design document and reference it from developers
  guide.

## Progress

- [x] (2026-02-28 15:04Z) Drafted ExecPlan for roadmap item 2.2.6 with
  explicit 2.2.8 alignment scope.
- [x] (2026-02-28 15:08Z) Stage A complete: added fail-first unit and BDD
  coverage for reusable reference model behaviour and 2.2.8 brief alignment.
- [x] (2026-02-28 15:14Z) Stage B complete: added `ReferenceDocument`,
  `ReferenceDocumentRevision`, `ReferenceBinding`, enums, and repository port
  contracts in canonical domain/ports.
- [x] (2026-02-28 15:18Z) Stage C complete: added SQLAlchemy tables, mappers,
  repositories, unit-of-work wiring, and additive migration
  `20260228_000004_add_reference_document_model.py`.
- [x] (2026-02-28 15:22Z) Stage D complete: aligned profile/template brief
  shaping with reference bindings while preserving existing brief keys.
- [x] (2026-02-28 15:26Z) Stage E complete: updated system design glossary and
  acceptance criteria, developers/users guides, and marked roadmap 2.2.6 done.
- [x] (2026-02-28 15:30Z) Stage F complete: required quality gates and markdown
  gates executed with passing logs.

## Surprises & discoveries

- Observation: roadmap item 2.2.8 is already marked done even though it lists
  2.2.6 as a dependency. Evidence: `docs/roadmap.md` shows `[x] 2.2.8` and
  `[ ] 2.2.6`. Impact: this plan must explicitly retrofit 2.2.8 contracts to
  the new reusable model without regressing existing API behaviour.

- Observation: the codebase currently contains no
  `ReferenceDocument`/`ReferenceDocumentRevision`/`ReferenceBinding` domain or
  repository types. Evidence: repository-wide search in `episodic/` and
  `tests/`. Impact: model, ports, storage, migration, and tests are all net-new.

- Observation: no dedicated glossary document exists under `docs/`.
  Evidence: `rg -n "Glossary|glossary" docs`. Impact: glossary acceptance
  should be satisfied by a new glossary section in the system design document.

- Observation: creating `ReferenceBinding` rows in the same transaction as new
  `ReferenceDocumentRevision` rows can fail on FK enforcement if the session
  has not flushed pending revisions yet. Evidence: early storage/BDD runs
  raised FK violations in
  `reference_document_bindings.reference_document_revision_id`. Impact: tests
  and implementation paths that add dependent bindings in the same UoW need
  explicit `await uow.flush()` between revision and binding adds.

## Decision log

- Decision: implement 2.2.6 as additive domain/storage contracts plus
  documentation acceptance criteria, not as endpoint delivery. Rationale:
  roadmap separates endpoint delivery into 2.2.7; this milestone must provide
  the model foundation. Date/Author: 2026-02-28 / Codex.

- Decision: align 2.2.8 by updating profile/template contract surfaces to
  expose reference-binding-aware structured brief metadata without removing
  existing fields. Rationale: preserves backward compatibility while bringing
  the implemented feature into line with the new model. Date/Author: 2026-02-28
  / Codex.

- Decision: treat host and guest profiles as reference-document kinds that are
  series-aligned, with revision applicability controlled by
  `effective_from_episode_id`. Rationale: this matches roadmap and design text,
  and avoids episode-bound duplication for recurring hosts/guests. Date/Author:
  2026-02-28 / Codex.

## Outcomes & retrospective

2.2.6 implementation is complete.

Delivered outcomes:

- Added reusable canonical model contracts:
  - domain entities and enums in `episodic/canonical/domain.py`,
  - repository protocols and UoW contract additions in
    `episodic/canonical/ports.py`.
- Added persistence implementation:
  - ORM records in `episodic/canonical/storage/models.py`,
  - mapper support in `episodic/canonical/storage/mappers.py`,
  - repositories in `episodic/canonical/storage/repositories.py`,
  - UoW wiring in `episodic/canonical/storage/uow.py`,
  - exports in `episodic/canonical/storage/__init__.py`,
  - additive migration
    `alembic/versions/20260228_000004_add_reference_document_model.py`.
- Aligned 2.2.8 brief contract with reusable reference bindings in
  `episodic/canonical/profile_templates/brief.py`.
- Added/updated tests:
  - unit: `tests/test_reference_document_models.py`,
  - storage integration: `tests/canonical_storage/test_reference_documents.py`,
  - behaviour: `tests/features/reference_document_model.feature`,
    `tests/steps/test_reference_document_model_steps.py`,
  - 2.2.8 alignment updates:
    `tests/test_profile_template_api.py`,
    `tests/steps/test_profile_template_api_steps.py`.
- Updated documentation:
  - system design glossary, ER model, and acceptance criteria in
    `docs/episodic-podcast-generation-system-design.md`,
  - internal contract guidance in `docs/developers-guide.md`,
  - user-facing behaviour notes in `docs/users-guide.md`,
  - roadmap progress in `docs/roadmap.md` (`2.2.6` now `[x]`).

Retrospective notes:

- Additive migration and port-first modeling kept hexagonal boundaries intact
  and avoided endpoint-scope creep into 2.2.7.
- `uow.flush()` sequencing for dependent binding inserts is a practical
  invariant worth keeping explicit in storage-focused tests.
- Brief payload extension with `reference_documents` preserved compatibility by
  retaining existing keys and adding deterministic empty-list defaults.

## Context and orientation

Current implementation baseline:

- `episodic/canonical/domain.py` contains `SeriesProfile`,
  `EpisodeTemplate`, and history-entry entities, but no reusable reference
  document entities.
- `episodic/canonical/ports.py` defines repositories and unit-of-work members
  for ingestion, profile/template, and history concerns only.
- `episodic/canonical/storage/models.py` has no reference-document tables.
- `episodic/canonical/profile_templates/` implements the 2.2.8 profile/template
  service and brief payload assembly.
- `episodic/api/` exposes profile/template endpoints that rely on the
  profile-template service contracts.

Documentation baseline:

- `docs/episodic-podcast-generation-system-design.md` describes reusable
  reference entities as planned, with a planned ER diagram, but code contracts
  are not implemented.
- `docs/users-guide.md` and `docs/developers-guide.md` currently describe
  profile/template behaviour without a finalized reusable reference model.
- `docs/roadmap.md` leaves 2.2.6 open and marks 2.2.8 complete.

## Plan of work

### Stage A: lock requirements with failing tests first

Add tests that encode intended model and compatibility behaviour before
production edits:

- Unit tests:
  - `tests/test_reference_document_models.py`
  - `tests/canonical_storage/test_reference_documents.py`
  - `tests/test_profile_template_service.py` (alignment assertions)
- Behaviour tests (`pytest-bdd`):
  - `tests/features/reference_document_model.feature`
  - `tests/steps/test_reference_document_model_steps.py`
  - update `tests/features/profile_template_api.feature` for aligned brief
    behaviour if contract shape changes.

Go/no-go: proceed only after new/updated tests fail for missing model and
alignment behaviour.

### Stage B: define domain and port contracts

Implement domain models and protocol contracts independent of ingestion-job
scope:

- Update `episodic/canonical/domain.py` with:
  - `ReferenceDocument`
  - `ReferenceDocumentRevision`
  - `ReferenceBinding`
  - supporting enums/value constraints for kind/state/target-kind.
- Update `episodic/canonical/ports.py` with repositories for:
  - reference documents,
  - document revisions,
  - bindings.
- Extend `CanonicalUnitOfWork` with these repositories.

Go/no-go: domain/port unit tests pass and type checking remains green.

### Stage C: implement persistence and migration

Add ORM records, mappers, repositories, UoW wiring, and migration:

- `episodic/canonical/storage/models.py`
- `episodic/canonical/storage/mappers.py`
- `episodic/canonical/storage/repositories.py`
- `episodic/canonical/storage/uow.py`
- `episodic/canonical/storage/__init__.py`
- new Alembic revision in `alembic/versions/`.

Migration must be additive and preserve existing 2.2.8 and ingestion data.

Go/no-go: targeted storage tests and migration tests pass.

### Stage D: align existing 2.2.8 functionality

Bring profile/template services and brief contracts into alignment with the new
reference model:

- Update `episodic/canonical/profile_templates/brief.py` and related typed
  service modules to include reference-binding-aware structured context in
  brief payload assembly (without breaking existing keys).
- Update API serialization/adapters if payload shape changes:
  - `episodic/api/serializers.py`
  - `episodic/api/resources/series_profiles.py`
  - `episodic/api/handlers.py`
- Update unit and BDD tests for the aligned behaviour.

Go/no-go: all existing 2.2.8 tests still pass, and new alignment assertions
pass.

### Stage E: documentation and acceptance criteria completion

Update docs to satisfy the roadmap finish line:

- `docs/episodic-podcast-generation-system-design.md`:
  - finalized reusable reference ER diagram,
  - glossary entries for the three entities,
  - repository contract acceptance criteria,
  - API contract acceptance criteria for upcoming 2.2.7 work.
- `docs/users-guide.md`: user-visible behaviour and expectations for reusable
  references in profile/template workflows.
- `docs/developers-guide.md`: internal contract and implementation guidance.
- `docs/roadmap.md`: mark `2.2.6` done after all criteria and gates pass.

### Stage F: quality gates and evidence capture

Run full required gates and archive logs.

Go/no-go: no completion without green gates.

## Concrete steps

Run from repository root.

1. Baseline and fail-first:

   ```shell
   git status --short
   set -o pipefail; uv run pytest -v tests/test_reference_document_models.py \
     tests/canonical_storage/test_reference_documents.py \
     tests/steps/test_reference_document_model_steps.py \
     2>&1 | tee /tmp/impl-2-2-6-red.log
   ```

2. Implement stages B-D, then targeted green:

   ```shell
   set -o pipefail; uv run pytest -v tests/test_reference_document_models.py \
     tests/canonical_storage/test_reference_documents.py \
     tests/test_profile_template_service.py \
     tests/test_profile_template_api.py \
     tests/steps/test_reference_document_model_steps.py \
     tests/steps/test_profile_template_api_steps.py \
     2>&1 | tee /tmp/impl-2-2-6-targeted-green.log
   ```

3. Run mandatory project gates:

   ```shell
   set -o pipefail; make check-fmt 2>&1 | tee /tmp/impl-2-2-6-make-check-fmt.log
   set -o pipefail; make typecheck 2>&1 | tee /tmp/impl-2-2-6-make-typecheck.log
   set -o pipefail; make lint 2>&1 | tee /tmp/impl-2-2-6-make-lint.log
   set -o pipefail; make test 2>&1 | tee /tmp/impl-2-2-6-make-test.log
   ```

4. Run markdown gates after docs edits:

   ```shell
   set -o pipefail; PATH=/root/.bun/bin:$PATH make markdownlint 2>&1 | tee /tmp/impl-2-2-6-make-markdownlint.log
   set -o pipefail; make nixie 2>&1 | tee /tmp/impl-2-2-6-make-nixie.log
   ```

Expected success indicators:

- Targeted tests pass after implementation.
- `make check-fmt`, `make typecheck`, `make lint`, and `make test` exit 0.
- Markdown/diagram validation exits 0 for updated docs.

## Validation and acceptance

Functional acceptance:

- Reference-document entities can be created, versioned, and bound via
  repository contracts without ingestion-job coupling.
- Series-aligned host/guest profile documents are representable through
  `ReferenceDocument` kind semantics and binding applicability fields.
- 2.2.8 profile/template workflows remain functional and expose aligned
  contract behaviour where required.

Documentation acceptance:

- Approved ER diagram is present in system design docs.
- Glossary entries exist for:
  - `ReferenceDocument`
  - `ReferenceDocumentRevision`
  - `ReferenceBinding`
- Repository and API contract acceptance criteria are explicitly documented.

Quality acceptance:

- Unit tests (`pytest`) cover all new model/port/storage logic.
- Behaviour tests (`pytest-bdd`) cover end-to-end expected behaviour.
- All required make gates are green.
- Roadmap entry `2.2.6` is checked only after all above pass.

## Idempotence and recovery

- All implementation steps are additive and re-runnable.
- If migration or tests fail, fix forward; do not delete migration history.
- If docs formatting touches unrelated files, revert unrelated diffs and rerun
  markdown gates.
- If alignment changes risk breaking existing API consumers, keep backward
  compatible fields and document deprecation path instead of removing keys.

## Artifacts and notes

Capture and keep concise evidence:

- `git diff -- episodic/canonical docs tests alembic/versions`
- `/tmp/impl-2-2-6-red.log`
- `/tmp/impl-2-2-6-targeted-green.log`
- `/tmp/impl-2-2-6-make-check-fmt.log`
- `/tmp/impl-2-2-6-make-typecheck.log`
- `/tmp/impl-2-2-6-make-lint.log`
- `/tmp/impl-2-2-6-make-test.log`
- `/tmp/impl-2-2-6-make-markdownlint.log`
- `/tmp/impl-2-2-6-make-nixie.log`

## Interfaces and dependencies

Add and wire new canonical ports (names are stable targets for implementation):

```python
class ReferenceDocumentRepository(Protocol):
    async def add(self, document: ReferenceDocument) -> None: ...
    async def get(self, document_id: uuid.UUID) -> ReferenceDocument | None: ...
    async def list_for_series(
        self, series_profile_id: uuid.UUID
    ) -> Sequence[ReferenceDocument]: ...

class ReferenceDocumentRevisionRepository(Protocol):
    async def add(self, revision: ReferenceDocumentRevision) -> None: ...
    async def list_for_document(
        self, document_id: uuid.UUID
    ) -> list[ReferenceDocumentRevision]: ...
    async def get(self, revision_id: uuid.UUID) -> ReferenceDocumentRevision | None: ...

class ReferenceBindingRepository(Protocol):
    async def add(self, binding: ReferenceBinding) -> None: ...
    async def list_for_target(
        self, *, target_kind: str, target_id: uuid.UUID
    ) -> list[ReferenceBinding]: ...
```

These are implemented in SQLAlchemy adapters and exposed through
`CanonicalUnitOfWork` without introducing new dependencies.

## Revision note

Initial draft created to implement roadmap item 2.2.6 with explicit 2.2.8
alignment, mandatory test strategy, and documentation finish-line criteria.

Updated 2026-02-28: execution completed, progress and outcomes recorded, and
gate evidence captured.
