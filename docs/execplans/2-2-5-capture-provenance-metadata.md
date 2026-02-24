# Capture provenance metadata in Text Encoding Initiative (TEI) headers for ingestion and future script generation

This Execution Plan (ExecPlan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

No `PLANS.md` file is present in the repository root.

Status: COMPLETE

## Purpose and big picture

After this change, every canonical TEI header persisted by ingestion
automatically includes a provenance block with source priorities, ingestion
timestamps, and reviewer identities. The same provenance builder is designed as
shared domain logic so script generation can use it later without redefining
metadata shape.

Success is observable when:

1. Ingestion writes TEI headers whose `payload` includes a stable provenance
   envelope with:
   - `source_priorities` derived from weighted source ordering.
   - `ingestion_timestamp` captured in Coordinated Universal Time (UTC)
     ISO-8601 format.
   - `reviewer_identities` captured from the ingesting actor identity.
2. Multi-source ingestion persists provenance with source priorities that match
   computed weights.
3. Unit tests (pytest) fail before implementation and pass after implementation
   for provenance capture and ordering.
4. Behavior-driven development (BDD) tests (`pytest-bdd`) fail before
   implementation and pass after implementation for user-observable provenance
   behavior.
5. Documentation is updated in:
   - `docs/episodic-podcast-generation-system-design.md`
   - `docs/users-guide.md`
   - `docs/developers-guide.md`
6. `docs/roadmap.md` marks item `2.2.5` as done when implementation is fully
   validated.
7. Quality gates pass: `make check-fmt`, `make typecheck`, `make lint`,
   `make test`.

## Constraints

- Preserve hexagonal architecture boundaries:
  - Domain layer owns provenance schema and merge logic.
  - Storage adapters persist domain outputs but do not invent provenance.
  - No adapter-to-adapter calls.
- Keep existing ingestion behavior unchanged except for adding provenance
  metadata.
- Do not add external dependencies.
- Keep provenance payload serializable to PostgreSQL JSONB (JSONB) and
  backward-compatible with existing `tei_headers.payload` records that lack
  provenance.
- Represent ingestion timestamps in UTC with explicit timezone data.
- Script generation is not implemented in this roadmap item; however, the
  provenance API introduced now must be reusable by script generation later.
- Follow test-first workflow from project guidance:
  - Modify or add tests first.
  - Confirm failures.
  - Implement code.
  - Confirm passes.
- Documentation must follow `docs/documentation-style-guide.md`.

## Tolerances (exception triggers)

- Scope: stop and escalate if implementation needs more than 12 files or 900
  net lines changed.
- Interface: stop and escalate if `IngestionRequest` public fields must change
  incompatibly.
- Persistence schema: stop and escalate if this work requires new database
  columns or table redesign rather than payload enrichment.
- Dependencies: stop and escalate if any new package is required.
- Iterations: stop and escalate after 3 failed fix attempts for the same
  failing test group.
- Ambiguity: stop and escalate if TEI provenance key naming or timestamp format
  is disputed by existing conventions.

## Risks

- Risk: TEI header payload key naming may conflict with future TEI parser
  expectations. Severity: medium Likelihood: low Mitigation: use a dedicated
  extension key (for example `episodic_provenance`) and keep TEI structural
  keys untouched.

- Risk: Source priority ordering could become inconsistent with canonical
  winner selection on equal weights. Severity: medium Likelihood: medium
  Mitigation: preserve source input order for equal-weight ties to match
  conflict-resolution behavior, and test for determinism.

- Risk: Reviewer identities for ingestion are currently a single actor
  (`requested_by`), while the requirement is plural. Severity: low Likelihood:
  high Mitigation: store as a list now, with zero-or-one entries during
  ingestion, and document that script generation will populate multi-reviewer
  sets.

- Risk: Behavioral tests may only verify approval payload today, not TEI
  header payload. Severity: low Likelihood: medium Mitigation: add explicit BDD
  steps that query persisted TEI headers and assert provenance fields.

## Progress

- [x] (2026-02-18 20:40Z) Drafted this Execution Plan (ExecPlan).
- [x] (2026-02-18 21:15Z) Stage A: Baseline and test-first setup completed.
- [x] (2026-02-18 21:18Z) Stage B: Unit tests added and confirmed failing
  pre-change (`ModuleNotFoundError` for provenance module).
- [x] (2026-02-18 21:20Z) Stage C: Behavioral provenance assertions added and
  validated in targeted scenario runs.
- [x] (2026-02-18 21:23Z) Stage D: Shared provenance module implemented and
  ingestion TEI header enrichment wired in `ingest_sources`.
- [x] (2026-02-18 21:28Z) Stage E: Documentation updates completed across
  system design, users' guide, developers' guide, and roadmap.
- [x] (2026-02-18 21:38Z) Stage F: Quality gates executed and passing.
- [x] (2026-02-18 21:28Z) Stage G: Roadmap item `2.2.5` marked done.

## Surprises & discoveries

- Observation: No Qdrant project-memory Model Context Protocol (MCP) endpoints
  are available in this environment, so repository and docs inspection are the
  only context source. Evidence: MCP resource and template listings returned
  empty results. Impact: No long-term memory recall/write can be performed for
  this session.

- Observation: Existing ingestion already captures conflict metadata under
  source-document metadata and source URIs in approval-event payload, but TEI
  header provenance is not yet explicitly captured. Evidence:
  `episodic/canonical/ingestion_service.py` enriches source metadata;
  `episodic/canonical/services.py` initial approval payload contains only
  source URIs. Impact: provenance must be added at TEI-header creation time in
  `ingest_sources`.

## Decision log

- Decision: Keep provenance within `TeiHeader.payload` (JSONB) rather than
  adding new relational columns in this item. Rationale: requirement targets
  TEI headers and existing schema already stores parsed header payload for
  query and reuse; this keeps migration risk low. Date/Author: 2026-02-18 /
  Codex.

- Decision: Introduce a shared provenance builder in canonical domain/service
  code now, with context support for `ingestion` and `script_generation`.
  Rationale: satisfies current ingestion work and enforces reuse when script
  generation is implemented. Date/Author: 2026-02-18 / Codex.

- Decision: Treat reviewer identities as a list even when a single actor is
  present. Rationale: aligns with roadmap wording and avoids future schema
  drift. Date/Author: 2026-02-18 / Codex.

## Outcomes & retrospective

Implementation completed on 2026-02-18.

Key outcomes:

- TEI header payloads now include `episodic_provenance` with
  `source_priorities`, `ingestion_timestamp`, `reviewer_identities`, and
  `capture_context`.
- Provenance generation is centralized in
  `episodic/canonical/provenance.py` and explicitly supports both
  `source_ingestion` and `script_generation` contexts.
- Ingestion now applies provenance automatically via
  `episodic/canonical/services.py`.
- Unit and behavioral provenance tests were added and pass.
- `docs/roadmap.md` item `2.2.5` is marked done.

At completion, this section must report:

- Delivered behavior against Purpose criteria.
- Deviations from planned scope.
- Any tolerance breaches and escalation outcomes.
- Lessons for script-generation provenance reuse.

## Context and orientation

Relevant current implementation and documents:

- `episodic/canonical/services.py`
  - `ingest_sources()` creates `TeiHeader` from parsed TEI.
  - `_create_tei_header()` currently stores parsed payload unchanged.
- `episodic/canonical/ingestion_service.py`
  - Computes weighted sources and passes `IngestionRequest` to
    `ingest_sources()`.
- `episodic/canonical/domain.py`
  - Defines `IngestionRequest`, `SourceDocumentInput`, and `TeiHeader`.
- `episodic/canonical/storage/models.py`
  - `tei_headers.payload` is JSONB, suitable for provenance envelope.
- `tests/test_ingestion_integration.py`
  - Covers end-to-end multi-source ingestion persistence.
- `tests/steps/test_canonical_ingestion_steps.py` and
  `tests/features/canonical_ingestion.feature`
  - Current BDD ingestion behavior.
- `tests/steps/test_multi_source_ingestion_steps.py` and
  `tests/features/multi_source_ingestion.feature`
  - Current BDD multi-source behavior.
- `docs/roadmap.md`
  - Item `2.2.5` is currently unchecked.
- `docs/episodic-podcast-generation-system-design.md`
  - Requires automatic TEI header provenance including weighting and reviewer
    metadata.

## Plan of work

### Stage A: baseline checks and provenance contract definition

Define the provenance contract before code edits. Capture a canonical payload
shape under `TeiHeader.payload` and document its semantics.

Planned contract:

- `episodic_provenance.capture_context`: `"ingestion"` or
  `"script_generation"`.
- `episodic_provenance.ingestion_timestamp`: ISO-8601 UTC timestamp.
- `episodic_provenance.source_priorities`: list ordered by priority with fields
  for source URI, source type, weight, and ordinal rank.
- `episodic_provenance.reviewer_identities`: list of identity strings.

Go/no-go: proceed only after this contract is reflected in tests.

### Stage B: unit tests first

Add and update pytest unit tests before implementation.

- Add a focused test module (for example
  `tests/test_canonical_provenance.py`) for provenance builder logic:
  - Builds payload with required keys.
  - Produces deterministic ordering on tie weights.
  - Accepts both `ingestion` and `script_generation` contexts.
- Extend `tests/test_ingestion_integration.py` to assert persisted
  `tei_headers.payload` contains provenance with:
  - ordered priorities,
  - timestamp presence and parseability,
  - reviewer identities derived from `requested_by`.

Run targeted tests and confirm expected failures before implementation.

Go/no-go: proceed only after failures demonstrate missing behavior.

### Stage C: behavioral tests first

Update pytest-bdd coverage to express user-visible provenance behavior.

- Extend `tests/features/canonical_ingestion.feature` with provenance
  expectations.
- Extend `tests/steps/test_canonical_ingestion_steps.py` with steps that fetch
  the persisted TEI header and assert provenance keys.
- Extend `tests/features/multi_source_ingestion.feature` and
  `tests/steps/test_multi_source_ingestion_steps.py` to assert source-priority
  ordering reflects weighting outcomes.

Run BDD scenarios and confirm they fail before implementation.

Go/no-go: proceed only after BDD failures confirm the gap.

### Stage D: implement provenance capture

Implement minimal production changes to satisfy failing tests.

- Add shared provenance builder logic in canonical domain/service area (for
  example `episodic/canonical/provenance.py`).
- Update `episodic/canonical/services.py` so `_create_tei_header()` (or an
  adjacent helper) merges provenance into the parsed header payload before
  persisting `TeiHeader`.
- Ensure source priorities are computed from `request.sources` weights with
  deterministic rank assignment.
- Populate reviewer identities from `request.requested_by` as a list.
- Keep `raw_xml` behavior unchanged unless tests require explicit provenance
  emission in XML.

Go/no-go: proceed to docs only when all new tests pass.

### Stage E: documentation updates

Update required docs after behavior is implemented.

- `docs/episodic-podcast-generation-system-design.md`
  - Record provenance contract and reusable builder approach.
  - Clarify script-generation integration expectation.
- `docs/users-guide.md`
  - Add user-facing behavior for automatic TEI provenance fields.
- `docs/developers-guide.md`
  - Document internal provenance interface and extension rules.
  - State that script-generation flows must call the shared builder.
- `docs/roadmap.md`
  - Mark `2.2.5` done only after Stage F succeeds.

### Stage F: quality gates and final verification

Run all required gates with `tee` logs and `pipefail`.

- `make check-fmt`
- `make typecheck`
- `make lint`
- `make test`

Also run Markdown gates because documentation changes are in scope.

- `make markdownlint`
- `make nixie`

Go/no-go: only finish when all gates pass.

## Concrete steps

Run from repository root (`/home/user/project`).

1. Baseline repository state and targeted search.

   ```plaintext
   rg -n "2\.2\.5|provenance|tei_headers|ingest_sources" docs episodic tests
   ```

2. Implement test-first changes (unit + BDD), then run targeted failures.

   ```plaintext
   set -o pipefail
   pytest tests/test_ingestion_integration.py -k provenance 2>&1 | tee /tmp/2-2-5-target-unit-before.log

   set -o pipefail
   pytest tests/steps/test_canonical_ingestion_steps.py tests/steps/test_multi_source_ingestion_steps.py \
     -k provenance 2>&1 | tee /tmp/2-2-5-target-bdd-before.log
   ```

3. Implement production provenance logic.

4. Re-run targeted tests to confirm fixes.

   ```plaintext
   set -o pipefail
   pytest tests/test_ingestion_integration.py -k provenance 2>&1 | tee /tmp/2-2-5-target-unit-after.log

   set -o pipefail
   pytest tests/steps/test_canonical_ingestion_steps.py tests/steps/test_multi_source_ingestion_steps.py \
     -k provenance 2>&1 | tee /tmp/2-2-5-target-bdd-after.log
   ```

5. Run full gates.

   ```plaintext
   set -o pipefail
   make check-fmt 2>&1 | tee /tmp/2-2-5-check-fmt.log

   set -o pipefail
   make typecheck 2>&1 | tee /tmp/2-2-5-typecheck.log

   set -o pipefail
   make lint 2>&1 | tee /tmp/2-2-5-lint.log

   set -o pipefail
   make test 2>&1 | tee /tmp/2-2-5-test.log

   set -o pipefail
   make markdownlint 2>&1 | tee /tmp/2-2-5-markdownlint.log

   set -o pipefail
   make nixie 2>&1 | tee /tmp/2-2-5-nixie.log
   ```

6. Update roadmap checkbox for `2.2.5` only after all logs show success.

## Validation and acceptance

Acceptance criteria:

- Persisted TEI headers include provenance metadata automatically for ingestion.
- Provenance contains source priorities, ingestion timestamp, and reviewer
  identities.
- Source priorities are deterministic and test-covered.
- A shared provenance builder supports both `ingestion` and
  `script_generation` contexts (script generation use is documented for future
  implementation).
- Unit tests and behavioral tests for provenance pass.
- `make check-fmt`, `make typecheck`, `make lint`, and `make test` pass.
- Documentation updates are present in system design, users' guide, and
  developers' guide.
- Roadmap item `2.2.5` is marked done.

## Idempotence and recovery

- Test runs and quality gates are safe to repeat.
- If implementation fails, revert only incomplete local edits and rerun the
  targeted failing suite before full gates.
- If full `make test` is noisy, inspect the `/tmp/2-2-5-*.log` files for the
  first failure and fix one class of failure at a time.
- If provenance key naming changes mid-implementation, update all tests and
  docs in the same change to keep consistency.

## Artifacts and notes

Expected log artifacts:

- `/tmp/2-2-5-target-unit-before.log`
- `/tmp/2-2-5-target-bdd-before.log`
- `/tmp/2-2-5-target-unit-after.log`
- `/tmp/2-2-5-target-bdd-after.log`
- `/tmp/2-2-5-check-fmt.log`
- `/tmp/2-2-5-typecheck.log`
- `/tmp/2-2-5-lint.log`
- `/tmp/2-2-5-test.log`
- `/tmp/2-2-5-markdownlint.log`
- `/tmp/2-2-5-nixie.log`

## Interfaces and dependencies

Planned interfaces:

- Shared provenance builder API in canonical domain/service code that accepts:
  - capture context (`ingestion` or `script_generation`),
  - timestamp,
  - source descriptors with weights,
  - reviewer identity list,
  and returns JSON-serializable provenance payload.
- `ingest_sources()` integration point in `episodic/canonical/services.py`.

Dependencies already present and reused:

- Python 3.13 standard library (`datetime`, dataclasses, typing).
- SQLAlchemy async stack and Postgres JSONB persistence.
- pytest and pytest-bdd for unit and behavioral tests.
- Existing Makefile quality gates.

No new dependencies are expected.

## Revision note

Initial draft created on 2026-02-18 for roadmap item `2.2.5`.
