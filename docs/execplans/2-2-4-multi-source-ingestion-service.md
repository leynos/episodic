# Build the multi-source ingestion service

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

Status: COMPLETE

## Purpose and big picture

After this change, the Episodic platform can ingest heterogeneous source
documents (transcripts, briefs, press releases, Really Simple Syndication (RSS)
feeds, and research notes), normalize them into Text Encoding Initiative (TEI)
fragments, compute source weights using configurable heuristics, resolve
conflicts between competing sources, and merge the result into a single
canonical TEI episode with full provenance. The existing low-level
`ingest_sources()` persistence function is preserved unchanged; a new
higher-level orchestrator composes around it.

Success is observable when:

1. Running `make test` passes all existing tests plus new unit tests and
   Behaviour-Driven Development (BDD) scenarios covering normalization,
   weighting, conflict resolution, and end-to-end multi-source ingestion.
2. Three new port protocols (`SourceNormaliser`, `WeightingStrategy`,
   `ConflictResolver`) define the extension points for normalization,
   weighting, and conflict resolution.
3. Reference in-memory adapters implement all three ports, sufficient for
   unit and behavioural testing without external dependencies.
4. The `ingest_multi_source()` orchestrator accepts a
   `MultiSourceRequest`, runs the pipeline (normalize → weight → resolve →
   merge), delegates persistence to `ingest_sources()`, and returns the
   persisted `CanonicalEpisode`.
5. Conflict resolution audit data (which sources were preferred, which were
   rejected, and why) is recorded in the approval event payload for downstream
   audit.
6. Documentation reflects the new interfaces, design decisions, and
   user-facing behaviours.
7. The roadmap marks item 2.2.4 as done.

## Constraints

- The existing `ingest_sources()` function in
  `episodic/canonical/services.py` must not be modified. The new orchestrator
  composes around it.
- The existing domain models in `episodic/canonical/domain.py`, ports in
  `episodic/canonical/ports.py`, storage layer in
  `episodic/canonical/storage/`, and TEI parser in `episodic/canonical/tei.py`
  must not be modified unless strictly necessary to support the new
  functionality.
- All existing tests must continue to pass. No regressions in `make test`,
  `make lint`, `make check-fmt`, or `make typecheck`.
- No new external dependencies may be added.
- Follow the hexagonal architecture: domain logic in service/domain modules,
  infrastructure behind port protocols.
- All domain value objects must be frozen dataclasses.
- Logging must use `femtologging` via the existing `episodic.logging` wrapper.
- Follow the commit message format in `AGENTS.md`.
- Documentation must follow `docs/documentation-style-guide.md`: British
  English (Oxford style), sentence case headings, 80-column wrapping, dashes
  for list bullets.
- Tests must follow the established patterns: `pytest.mark.asyncio` for async
  unit tests, `_run_async_step` + `_function_scoped_runner` for BDD steps,
  `session_factory` fixture for database access.

## Tolerances (exception triggers)

- Scope: if implementation requires changes to more than 15 files or 1500
  lines of code (net), stop and escalate.
- Interface: if the existing `CanonicalUnitOfWork` protocol or any existing
  repository protocol must change, stop and escalate.
- Dependencies: if a new external dependency is required, stop and escalate.
- Iterations: if tests still fail after 3 attempts at fixing, stop and
  escalate.
- Production code: if `episodic/canonical/services.py`,
  `episodic/canonical/domain.py`, or `episodic/canonical/ports.py` must be
  modified beyond re-exports, stop and escalate.

## Risks

- Risk: The `tei-rapporteur` library's `Document` constructor and `emit_xml()`
  function may not support constructing TEI documents from arbitrary title and
  content fragments. The conflict resolution merge step needs to produce valid
  TEI XML. Severity: medium. Likelihood: low. Mitigation: Inspect
  `tei_rapporteur.Document()` and `tei_rapporteur.emit_xml()` API surface
  before implementation. If the library cannot construct documents from
  fragments, use string-based TEI XML construction for the merged output,
  validated via `parse_tei_header()`.

- Risk: The weighting heuristic configuration schema embedded in
  `SeriesProfile.configuration` (a `JsonMapping`) is not formally defined. The
  weighting strategy must extract configuration from this untyped dictionary.
  Severity: low. Likelihood: low. Mitigation: Define a clear schema for the
  weighting configuration keys the strategy expects, document it, and validate
  defensively at runtime.

- Risk: BDD step definitions may conflict with existing step definitions if
  step text overlaps with `tests/steps/test_canonical_ingestion_steps.py`.
  Severity: low. Likelihood: low. Mitigation: Use distinct step text that does
  not overlap with the canonical ingestion steps.

## Progress

- [x] Stage A: Write the ExecPlan document.
- [x] Stage B: Define domain value objects and port protocols.
- [x] Stage C: Implement reference adapters.
- [x] Stage D: Implement the multi-source ingestion orchestrator.
- [x] Stage E: Write unit tests.
- [x] Stage F: Write BDD feature file and step definitions.
- [x] Stage G: Update documentation (system design, developers' guide, users'
  guide, roadmap).
- [x] Stage H: Run all quality gates and capture logs.

## Surprises and discoveries

- The `ingest_multi_source()` orchestrator initially had six parameters (uow,
  series\_profile, request, normaliser, weighting, resolver). The project's
  ruff configuration enforces PLR0913 (max 4 positional parameters) and PLR0917
  (max 4 positional-or-keyword arguments). Resolved by bundling the three
  adapter parameters into an `IngestionPipeline` frozen dataclass.

- The `resolve()` and `compute_weights()` adapter methods triggered PLR6301
  ("method could be a function or static method") because they don't reference
  `self`. However, these methods implement Protocol interfaces that require
  `self`. Resolved with `# noqa: PLR6301` inline comments, which is consistent
  with the Protocol pattern.

- `ruff format` reformatted 4 files after all code was written, indicating
  minor formatting drift from the auto-formatter's expectations. All were
  cosmetic (whitespace/line breaks) with no functional impact.

## Decision log

- Decision: Compose a new `ingest_multi_source()` orchestrator around the
  existing `ingest_sources()` rather than modifying it in place. Rationale:
  `ingest_sources()` is already tested, stable, and serves as the persistence
  boundary. The new orchestrator handles normalization, weighting, and conflict
  resolution as pure domain logic, then delegates persistence. This follows the
  open/closed principle and minimizes blast radius. Date/Author: 2026-02-15,
  plan phase.

- Decision: Define three separate port protocols (`SourceNormaliser`,
  `WeightingStrategy`, `ConflictResolver`) rather than a single monolithic
  ingestion port. Rationale: Each concern (normalization, weighting, conflict
  resolution) is independently swappable and testable. This follows the
  Interface Segregation Principle and mirrors the hexagonal architecture
  pattern established in the codebase. Date/Author: 2026-02-15, plan phase.

- Decision: Provide reference in-memory adapters rather than concrete
  production adapters for all five source types. Rationale: The roadmap item
  focuses on the service layer (normalization pipeline, weighting heuristics,
  conflict resolution). Concrete adapters for RSS parsing, PDF extraction, and
  similar concerns are infrastructure details that belong in later tasks or
  dedicated adapter packages. The reference adapters are sufficient for testing
  the domain logic. Date/Author: 2026-02-15, plan phase.

- Decision: Place new ingestion domain types in
  `episodic/canonical/ingestion.py` and new port protocols in
  `episodic/canonical/ingestion_ports.py` rather than extending the existing
  `domain.py` and `ports.py`. Rationale: The existing files are focused on the
  persistence-layer domain and ports. The new ingestion pipeline introduces
  distinct concerns (normalization, weighting, conflict resolution) that
  warrant separate modules. This follows the "group by feature" guidance in
  `AGENTS.md`. Date/Author: 2026-02-15, plan phase.

- Decision: Record conflict resolution audit data in the `ApprovalEvent`
  payload rather than adding a new database table. Rationale: The
  `ApprovalEvent` entity already stores a JSON payload for audit data, and the
  existing `ingest_sources()` service already records source URIs in the
  initial approval event payload. Extending this payload with conflict
  resolution metadata (preferred sources, rejected sources, resolution
  reasoning) is consistent with the existing pattern and avoids schema
  migration. Date/Author: 2026-02-15, plan phase.

- Decision: Introduce `IngestionPipeline` frozen dataclass to bundle the three
  adapter parameters (`normaliser`, `weighting`, `resolver`) rather than
  passing them as separate positional arguments. Rationale: The project
  enforces PLR0913 (max 4 positional parameters). Bundling the adapters into a
  single pipeline object also makes the API cleaner for callers and follows the
  Parameter Object pattern. Date/Author: 2026-02-15, implementation phase.

## Outcomes and retrospective

Implementation completed on 2026-02-15. All acceptance criteria met.

### Results

- 13 new tests added (11 unit tests + 2 BDD scenarios), all passing.
- Full test suite: 43 passed, 2 skipped (pre-existing skips for
  infrastructure workflows).
- All quality gates pass: `make check-fmt`, `make typecheck`, `make lint`,
  `make test`, `make markdownlint`.
- No existing files modified beyond `episodic/canonical/__init__.py`
  (re-exports) and documentation files.
- No new external dependencies added.
- No tolerance triggers hit.

### What went well

- The composition pattern around `ingest_sources()` worked cleanly. No
  changes to the existing persistence logic were needed.
- The three-port architecture (normaliser, weighting, resolver) made each
  concern independently testable with lightweight unit tests.
- BDD scenarios with distinct step text avoided conflicts with the existing
  canonical ingestion steps.

### What could be improved

- The `IngestionPipeline` dataclass was a late refactor driven by PLR0913.
  Future ExecPlans should account for the project's argument count limits when
  designing function signatures.
- The ExecPlan's interface section still shows the original six-parameter
  signature for `ingest_multi_source()`. The actual implementation uses four
  parameters with an `IngestionPipeline` bundle. Updated in the interfaces
  section below.

## Context and orientation

The Episodic project is a podcast generation platform following hexagonal
architecture. The canonical content layer manages TEI-based episode content.
The relevant files and their roles are:

- `episodic/canonical/domain.py` — Frozen dataclasses for domain entities:
  `SeriesProfile`, `TeiHeader`, `CanonicalEpisode`, `IngestionJob`,
  `SourceDocument`, `ApprovalEvent`, `SourceDocumentInput`, `IngestionRequest`.
  Enums: `EpisodeStatus`, `ApprovalState`, `IngestionStatus`. Type alias:
  `JsonMapping`.
- `episodic/canonical/ports.py` — Protocol interfaces for six repositories
  and the `CanonicalUnitOfWork` boundary.
- `episodic/canonical/services.py` — Domain service `ingest_sources()` that
  parses TEI XML, creates all domain entities, and persists them via the unit
  of work. Helper functions `_create_tei_header()`,
  `_create_canonical_episode()`, `_create_ingestion_job()`,
  `_create_source_documents()`, `_create_initial_approval_event()`.
- `episodic/canonical/tei.py` — `parse_tei_header()` function using
  `tei-rapporteur` to parse and validate TEI XML, returning
  `TeiHeaderPayload(title, payload)`.
- `episodic/canonical/storage/` — SQLAlchemy adapters: ORM models, mappers,
  repositories, and `SqlAlchemyUnitOfWork`.
- `episodic/canonical/__init__.py` — Public API re-exports.
- `episodic/logging.py` — `get_logger()`, `log_info()`, `log_warning()`,
  `log_error()` wrappers around femtologging.
- `tests/conftest.py` — Shared fixtures: `pglite_engine`, `migrated_engine`,
  `session_factory`, `pglite_session`, `_function_scoped_runner`.
- `tests/test_canonical_storage.py` — Unit tests for repositories.
- `tests/test_canonical_tei.py` — Unit tests for TEI parsing.
- `tests/features/canonical_ingestion.feature` — BDD scenario for basic
  ingestion.
- `tests/steps/test_canonical_ingestion_steps.py` — BDD step definitions
  for canonical ingestion. Uses `_run_async_step()` helper, `IngestionContext`
  TypedDict, `_run_episode_assertion()` pattern.

The system design document
(`docs/episodic-podcast-generation-system-design.md`) specifies the
multi-source ingestion service at lines 124–133 and the ingestion workflow at
lines 1127–1135. Key requirements:

- Accepts RSS feeds, briefs, transcripts, press releases, and research notes.
- Applies document classifiers, quality scores, and weighting heuristics.
- Normalizes inputs into TEI fragments and merges into canonical episodes.
- Conflicts resolve using the weighting matrix; rejected content retained for
  audit.
- Records provenance and retains source attachments.

## Plan of work

The work proceeds in eight stages, each ending with validation.

### Stage A: ExecPlan document

Write this document to `docs/execplans/2-2-4-multi-source-ingestion-service.md`.

### Stage B: Domain value objects and port protocols

Create two new modules in `episodic/canonical/`:

**`episodic/canonical/ingestion.py`** — Domain value objects:

- `NormalisedSource` (frozen dataclass): Represents a single source document
  after normalization into a TEI-compatible fragment.
  - `source_input: SourceDocumentInput` — the original source metadata.
  - `title: str` — extracted or inferred title from the source.
  - `tei_fragment: str` — normalized TEI XML fragment for this source.
  - `quality_score: float` — classifier-assigned quality score (0–1).
  - `freshness_score: float` — temporal freshness score (0–1).
  - `reliability_score: float` — source reliability score (0–1).

- `WeightingResult` (frozen dataclass): The computed weight for a single
  normalized source, along with the reasoning.
  - `source: NormalisedSource` — the normalized source.
  - `computed_weight: float` — final weight (0–1) after heuristic application.
  - `factors: JsonMapping` — breakdown of weighting factors for audit.

- `ConflictOutcome` (frozen dataclass): The result of conflict resolution
  across all weighted sources.
  - `merged_tei_xml: str` — the final merged TEI XML.
  - `merged_title: str` — the resolved title.
  - `preferred_sources: list[WeightingResult]` — sources that contributed to
    the canonical output.
  - `rejected_sources: list[WeightingResult]` — sources that were overridden,
    with reasons preserved in `factors`.
  - `resolution_notes: str` — human-readable summary of conflict resolution.

- `MultiSourceRequest` (frozen dataclass): Input payload for multi-source
  ingestion.
  - `raw_sources: list[RawSourceInput]` — heterogeneous source inputs.
  - `series_slug: str` — identifies the target series.
  - `requested_by: str | None` — actor requesting ingestion.

- `RawSourceInput` (frozen dataclass): A single raw source before
  normalization.
  - `source_type: str` — type classifier (e.g. "transcript", "brief", "rss",
    "press_release", "research_notes").
  - `source_uri: str` — URI or path to the source.
  - `content: str` — raw content of the source.
  - `content_hash: str` — hash of the raw content for deduplication.
  - `metadata: JsonMapping` — arbitrary metadata from the source.

**`episodic/canonical/ingestion_ports.py`** — Port protocols:

- `SourceNormaliser` (Protocol): Normalizes a raw source into a TEI fragment
  with quality, freshness, and reliability scores.

      class SourceNormaliser(typ.Protocol):
          async def normalise(
              self,
              raw_source: RawSourceInput,
          ) -> NormalisedSource: …

- `WeightingStrategy` (Protocol): Computes weights for normalized sources
  using series-level configuration.

      class WeightingStrategy(typ.Protocol):
          async def compute_weights(
              self,
              sources: list[NormalisedSource],
              series_configuration: JsonMapping,
          ) -> list[WeightingResult]: …

- `ConflictResolver` (Protocol): Resolves conflicts between weighted sources
  and produces merged canonical TEI.

      class ConflictResolver(typ.Protocol):
          async def resolve(
              self,
              weighted_sources: list[WeightingResult],
          ) -> ConflictOutcome: …

Validation: `make typecheck` and `make lint` pass with the new modules.

### Stage C: Reference adapters

Create `episodic/canonical/adapters/` package with reference implementations:

**`episodic/canonical/adapters/__init__.py`** — Package init with `__all__`
re-exports.

**`episodic/canonical/adapters/normaliser.py`** — `InMemorySourceNormaliser`:

- Wraps raw content in a minimal valid TEI XML structure using
  `tei_rapporteur.Document()` and `tei_rapporteur.emit_xml()`.
- Assigns quality, freshness, and reliability scores based on source type
  defaults (configurable via constructor). Default heuristics:
  - `transcript`: quality=0.9, freshness=0.8, reliability=0.9
  - `brief`: quality=0.8, freshness=0.7, reliability=0.8
  - `rss`: quality=0.6, freshness=1.0, reliability=0.5
  - `press_release`: quality=0.7, freshness=0.6, reliability=0.7
  - `research_notes`: quality=0.5, freshness=0.5, reliability=0.6

**`episodic/canonical/adapters/weighting.py`** — `DefaultWeightingStrategy`:

- Computes weight as a weighted average of quality, freshness, and reliability
  scores, using coefficients from the series configuration (or sensible
  defaults: quality=0.5, freshness=0.3, reliability=0.2).
- Clamps result to [0, 1].
- Records factor breakdown in the `factors` dictionary.

**`episodic/canonical/adapters/resolver.py`** — `HighestWeightConflictResolver`:

- Sorts weighted sources by `computed_weight` descending.
- Selects the highest-weighted source's TEI fragment as the canonical content.
- All other sources are recorded as rejected with their weights and factors
  preserved.
- Generates a `resolution_notes` string summarizing the decision.

Validation: `make typecheck` and `make lint` pass.

### Stage D: Multi-source ingestion orchestrator

Create **`episodic/canonical/ingestion_service.py`**:

- `ingest_multi_source()` async function:
  - Parameters:
    - `uow: CanonicalUnitOfWork`
    - `series_profile: SeriesProfile`
    - `request: MultiSourceRequest`
    - `normaliser: SourceNormaliser`
    - `weighting: WeightingStrategy`
    - `resolver: ConflictResolver`
  - Returns: `CanonicalEpisode`
  - Orchestration:
    1. Normalize each raw source via `normaliser.normalise()`.
    2. Compute weights via `weighting.compute_weights()`.
    3. Resolve conflicts via `resolver.resolve()`.
    4. Build an `IngestionRequest` from the resolved output:
       - `tei_xml` = `conflict_outcome.merged_tei_xml`
       - `sources` = list of `SourceDocumentInput` built from each raw source,
         using the computed weight from `WeightingResult`.
       - `requested_by` = `request.requested_by`
    5. Delegate to `ingest_sources(uow=uow, series_profile=series_profile, request=request)`.
    6. Log the ingestion with source count, conflict resolution summary.
    7. Return the persisted `CanonicalEpisode`.

Update **`episodic/canonical/__init__.py`** to export new public types:
`NormalisedSource`, `WeightingResult`, `ConflictOutcome`, `MultiSourceRequest`,
`RawSourceInput`, `ingest_multi_source`.

Validation: `make typecheck` and `make lint` pass.

### Stage E: Unit tests

Create **`tests/test_ingestion_service.py`** with the following tests:

1. `test_normaliser_produces_valid_tei_fragment` — The
   `InMemorySourceNormaliser` produces a `NormalisedSource` with valid TEI XML
   (parseable by `parse_tei_header()`), correct scores based on source type
   defaults, and matching metadata.

2. `test_normaliser_unknown_source_type_uses_defaults` — An unknown source
   type gets default mid-range scores rather than raising an error.

3. `test_weighting_strategy_computes_weighted_average` — The
   `DefaultWeightingStrategy` computes weights as the weighted average of
   quality, freshness, and reliability scores using default coefficients.
   Verify the computed weight and factors breakdown.

4. `test_weighting_strategy_respects_series_configuration` — When series
   configuration overrides coefficients, the strategy uses those instead of
   defaults.

5. `test_weighting_strategy_clamps_to_unit_interval` — Weights are always
   clamped to [0, 1] even with extreme input scores.

6. `test_conflict_resolver_selects_highest_weight` — The
   `HighestWeightConflictResolver` selects the highest-weighted source as
   preferred and marks all others as rejected.

7. `test_conflict_resolver_single_source_no_conflict` — With a single
   source, it is selected as preferred with no rejections.

8. `test_conflict_resolver_records_resolution_notes` — The resolver produces
   a human-readable `resolution_notes` string summarizing the decision.

9. `test_ingest_multi_source_end_to_end` — Integration test using
   `SqlAlchemyUnitOfWork` and reference adapters. Submits two raw sources,
   verifies:
   - A canonical episode is persisted with the correct title.
   - Source documents are persisted with computed weights (not raw weights).
   - The approval event payload includes conflict resolution metadata.
   - The ingestion job status is COMPLETED.

10. `test_ingest_multi_source_preserves_all_sources` — All submitted sources
    are persisted as `SourceDocument` entities, even those rejected during
    conflict resolution. Validates the "rejected content retained for audit"
    requirement.

11. `test_ingest_multi_source_empty_sources_raises` — Submitting zero raw
    sources raises a `ValueError`.

Validation: `make test` passes all new and existing tests.

### Stage F: BDD feature file and step definitions

Create **`tests/features/multi_source_ingestion.feature`**:

    Feature: Multi-source ingestion

      Scenario: Ingestion normalizes and merges multiple sources
        Given a series profile "tech-weekly" exists for multi-source ingestion
        And a transcript source is available
        And a brief source is available
        When multi-source ingestion processes the sources
        Then a canonical episode is created for "tech-weekly"
        And source documents are persisted with computed weights
        And conflict resolution metadata is recorded in the approval event

      Scenario: Single source ingestion requires no conflict resolution
        Given a series profile "solo-show" exists for multi-source ingestion
        And a single transcript source is available
        When multi-source ingestion processes the sources
        Then a canonical episode is created for "solo-show"
        And the single source is marked as preferred

Create **`tests/steps/test_multi_source_ingestion_steps.py`** with step
definitions following the `_run_async_step` + `_function_scoped_runner` pattern
from `tests/steps/test_canonical_ingestion_steps.py`.

Validation: `make test` passes all BDD scenarios.

### Stage G: Documentation updates

1. **`docs/episodic-podcast-generation-system-design.md`** — Add a subsection
   "Multi-source ingestion service implementation" after the "Repository and
   unit-of-work implementation" section. Document the three-port architecture
   (normalization, weighting, conflict resolution), the composition pattern
   around `ingest_sources()`, the weighting heuristic defaults, and the
   conflict resolution strategy.

2. **`docs/developers-guide.md`** — Add a section "Multi-source ingestion"
   after "Canonical content persistence". Document:
   - The three port protocols and how to implement custom adapters.
   - The `ingest_multi_source()` orchestration flow.
   - The reference adapter defaults and how to override them.
   - Series configuration keys for weighting coefficients.

3. **`docs/users-guide.md`** — Update the "Content Creation" section to note
   that multi-source ingestion normalizes heterogeneous sources, applies
   configurable weighting heuristics, and resolves conflicts automatically
   while retaining all source material for audit.

4. **`docs/roadmap.md`** — Change line 66 from `- [ ] 2.2.4.` to
   `- [x] 2.2.4.`.

Validation: `make markdownlint` and `make nixie` pass.

### Stage H: Quality gates

Run all required quality gates:

    set -o pipefail; timeout 300 make fmt 2>&1 | tee /tmp/make-fmt.log
    set -o pipefail; timeout 300 make check-fmt 2>&1 | tee /tmp/make-check-fmt.log
    set -o pipefail; timeout 300 make typecheck 2>&1 | tee /tmp/make-typecheck.log
    set -o pipefail; timeout 300 make lint 2>&1 | tee /tmp/make-lint.log
    set -o pipefail; timeout 300 make test 2>&1 | tee /tmp/make-test.log
    set -o pipefail; timeout 300 make markdownlint 2>&1 | tee /tmp/make-markdownlint.log

## Concrete steps

### Step 1: Write the ExecPlan

Write this document to `docs/execplans/2-2-4-multi-source-ingestion-service.md`.

### Step 2: Create domain value objects

Create `episodic/canonical/ingestion.py` with the frozen dataclasses
`RawSourceInput`, `NormalisedSource`, `WeightingResult`, `ConflictOutcome`, and
`MultiSourceRequest` as described in Stage B.

### Step 3: Create port protocols

Create `episodic/canonical/ingestion_ports.py` with the protocols
`SourceNormaliser`, `WeightingStrategy`, and `ConflictResolver` as described in
Stage B.

### Step 4: Create the adapters package

Create `episodic/canonical/adapters/__init__.py`,
`episodic/canonical/adapters/normaliser.py`,
`episodic/canonical/adapters/weighting.py`, and
`episodic/canonical/adapters/resolver.py` as described in Stage C.

### Step 5: Create the orchestrator

Create `episodic/canonical/ingestion_service.py` with `ingest_multi_source()`
as described in Stage D.

### Step 6: Update public API

Edit `episodic/canonical/__init__.py` to re-export the new public types and the
orchestrator function.

### Step 7: Write unit tests

Create `tests/test_ingestion_service.py` with the 11 tests described in Stage E.

### Step 8: Write BDD scenarios

Create `tests/features/multi_source_ingestion.feature` and
`tests/steps/test_multi_source_ingestion_steps.py` as described in Stage F.

### Step 9: Update system design document

Edit `docs/episodic-podcast-generation-system-design.md` to add the
multi-source ingestion service implementation subsection.

### Step 10: Update developers' guide

Edit `docs/developers-guide.md` to add the multi-source ingestion section.

### Step 11: Update users' guide

Edit `docs/users-guide.md` to add multi-source ingestion user-facing behaviour.

### Step 12: Update roadmap

Edit `docs/roadmap.md` to mark 2.2.4 as done.

### Step 13: Run formatting

    set -o pipefail; timeout 300 make fmt 2>&1 | tee /tmp/make-fmt.log

### Step 14: Run quality gates

    set -o pipefail; timeout 300 make check-fmt 2>&1 | tee /tmp/make-check-fmt.log
    set -o pipefail; timeout 300 make typecheck 2>&1 | tee /tmp/make-typecheck.log
    set -o pipefail; timeout 300 make lint 2>&1 | tee /tmp/make-lint.log
    set -o pipefail; timeout 300 make test 2>&1 | tee /tmp/make-test.log
    set -o pipefail; timeout 300 make markdownlint 2>&1 | tee /tmp/make-markdownlint.log

## Validation and acceptance

Acceptance requires all of the following:

- `make test` passes all existing and new tests (expected: 11 new unit tests +
  2 new BDD scenarios + all existing tests).
- `make check-fmt` passes.
- `make typecheck` passes.
- `make lint` passes.
- `make markdownlint` passes.
- Three new port protocols (`SourceNormaliser`, `WeightingStrategy`,
  `ConflictResolver`) are defined with full docstrings and type annotations.
- Reference adapters implement all three ports with configurable defaults.
- The `ingest_multi_source()` orchestrator composes normalization → weighting
  → conflict resolution → persistence via `ingest_sources()`.
- All submitted sources are persisted (including rejected ones) for audit.
- Conflict resolution metadata is recorded in the approval event payload.
- System design document records multi-source ingestion implementation
  decisions.
- Developers' guide documents the three port protocols, the orchestration
  flow, and series configuration keys.
- Users' guide notes multi-source ingestion, weighting, and conflict
  resolution behaviour.
- Roadmap marks 2.2.4 as done.

Quality method:

    set -o pipefail; timeout 300 make check-fmt 2>&1 | tee /tmp/make-check-fmt.log
    set -o pipefail; timeout 300 make typecheck 2>&1 | tee /tmp/make-typecheck.log
    set -o pipefail; timeout 300 make lint 2>&1 | tee /tmp/make-lint.log
    set -o pipefail; timeout 300 make test 2>&1 | tee /tmp/make-test.log
    set -o pipefail; timeout 300 make markdownlint 2>&1 | tee /tmp/make-markdownlint.log

## Idempotence and recovery

All steps are re-runnable. Tests use function-scoped py-pglite databases that
are discarded after each test. If tests fail, fix the issue and rerun
`make test`. Log files in `/tmp` are overwritten on each run.

Documentation edits are idempotent and may be repeated safely.

## Artifacts and notes

- `/tmp/make-fmt.log` — formatting output.
- `/tmp/make-check-fmt.log` — formatting check output.
- `/tmp/make-typecheck.log` — type check output.
- `/tmp/make-lint.log` — lint output.
- `/tmp/make-test.log` — test output.
- `/tmp/make-markdownlint.log` — Markdown lint output.

## Interfaces and dependencies

New interfaces introduced:

In `episodic/canonical/ingestion_ports.py`:

    class SourceNormaliser(typ.Protocol):
        async def normalise(
            self,
            raw_source: RawSourceInput,
        ) -> NormalisedSource: …

    class WeightingStrategy(typ.Protocol):
        async def compute_weights(
            self,
            sources: list[NormalisedSource],
            series_configuration: JsonMapping,
        ) -> list[WeightingResult]: …

    class ConflictResolver(typ.Protocol):
        async def resolve(
            self,
            weighted_sources: list[WeightingResult],
        ) -> ConflictOutcome: …

In `episodic/canonical/ingestion_service.py`:

    @dc.dataclass(frozen=True, slots=True)
    class IngestionPipeline:
        normaliser: SourceNormaliser
        weighting: WeightingStrategy
        resolver: ConflictResolver

    async def ingest_multi_source(
        uow: CanonicalUnitOfWork,
        series_profile: SeriesProfile,
        request: MultiSourceRequest,
        pipeline: IngestionPipeline,
    ) -> CanonicalEpisode: …

New domain value objects in `episodic/canonical/ingestion.py`:

    RawSourceInput(source_type, source_uri, content, content_hash, metadata)
    NormalisedSource(source_input, title, tei_fragment, quality_score,
                     freshness_score, reliability_score)
    WeightingResult(source, computed_weight, factors)
    ConflictOutcome(merged_tei_xml, merged_title, preferred_sources,
                    rejected_sources, resolution_notes)
    MultiSourceRequest(raw_sources, series_slug, requested_by)

Reference adapters in `episodic/canonical/adapters/`:

    InMemorySourceNormaliser — normaliser.py
    DefaultWeightingStrategy — weighting.py
    HighestWeightConflictResolver — resolver.py

Existing dependencies used (no new additions):

- `sqlalchemy` (`>=2.0.34,<3.0.0`) — ORM and async engine.
- `tei-rapporteur` — TEI XML construction and parsing.
- `femtologging` — structured logging.
- `py-pglite[asyncpg]` — in-process Postgres for tests.
- `pytest`, `pytest-asyncio`, `pytest-bdd` — test framework.

## Revision note

Initial plan created on 2026-02-15 to scope the multi-source ingestion service
for roadmap item 2.2.4.
