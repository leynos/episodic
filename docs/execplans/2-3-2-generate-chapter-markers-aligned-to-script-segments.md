# Generate chapter markers aligned to script segments

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: COMPLETE

## Purpose and big picture

Roadmap item 2.3.2 asks Episodic to generate chapter markers aligned to script
segments and to include timing metadata compatible with podcast players. After
this change, a generation service can read a canonical Text Encoding Initiative
(TEI) podcast script, identify boundaries where segment transitions occur, ask
the configured Large Language Model (LLM) to title and summarize those
chapters, and enrich the TEI body with structured chapter metadata.

Success is observable when a caller can pass TEI XML containing ordered script
segments to a new chapter-marker generator, receive typed chapter entries with
monotonic ISO 8601 start times, and emit TEI containing a single
`<div type="chapters">` metadata block. The implementation must be validated
with unit tests, property tests, and Behaviour-Driven Development (BDD) tests
using Vidai Mock. It must also update the user and developer documentation, add
an Architecture Decision Record (ADR) for the TEI representation, and mark
roadmap item 2.3.2 as done only after all quality gates pass.

## Constraints

- Preserve hexagonal architecture boundaries. Domain and generation policy
  logic must depend on the existing `LLMPort` contract and TEI helpers only. It
  must not import Falcon, SQLAlchemy, Celery, LangGraph, or concrete HTTP
  client adapters.
- Keep chapter markers inside the canonical TEI document. Prompt JSON is
  allowed only as a projection of TEI-backed content, not as a second canonical
  content model.
- Place content-enrichment code in `episodic/generation/`, following the
  existing show-notes boundary. Do not place chapter generation in
  `episodic/qa/`, because QA modules critique content rather than enrich it.
- Use `LLMPort.generate(LLMRequest) -> LLMResponse` for inference. Do not add a
  second LLM abstraction and do not bypass the existing OpenAI-compatible
  adapter.
- Keep public signatures in `episodic/llm/ports.py`,
  `episodic/canonical/domain.py`, and `episodic/canonical/ports.py` stable
  unless the implementer stops and escalates.
- Timing metadata must use integer-only ISO 8601-style `PT#H#M#S` durations
  such as `PT0S`, `PT5M30S`, and `PT1H2M3S`. Internally, validation may convert
  durations to seconds, but the public DTO and TEI representation must preserve
  those duration strings.
- Chapter starts must be ordered, non-negative, and aligned to segment
  transitions. Duplicate, descending, or negative starts are invalid.
- Use Vidai Mock for behavioural testing of inference services.
- Use `pytest` for unit tests, `pytest-bdd` for behavioural tests, and
  `hypothesis` for range-based invariants such as timing monotonicity and
  duration round-tripping.
- Follow the documentation style guide in
  `docs/documentation-style-guide.md`: British English with Oxford spelling,
  sentence-case headings, Markdown paragraphs wrapped at 80 columns, and code
  blocks wrapped at 120 columns.
- Keep Markdown-only changes gated by `make markdownlint` and `make nixie`.
  Code changes must additionally pass `make check-fmt`, `make typecheck`,
  `make lint`, and `make test`.

## Tolerances

- Scope tolerance: stop and escalate if implementation requires changes to more
  than 20 files or 1400 net new lines before a working vertical slice exists.
- Interface tolerance: stop and escalate if any public API signature in
  `LLMPort`, `LLMRequest`, `LLMResponse`, or existing canonical domain entities
  must change.
- Dependency tolerance: stop and escalate if a new runtime dependency is
  required. A new test-only dependency also requires escalation unless
  `hypothesis` is already present in the project configuration.
- TEI tooling tolerance: stop and escalate if `tei_rapporteur` cannot parse,
  validate, and re-emit the chosen chapter-marker representation without
  changing its dependency pin.
- Ambiguity tolerance: stop and escalate if the project has no settled segment
  representation and two plausible interpretations would produce incompatible
  chapter locators or timing rules.
- Test iteration tolerance: stop and escalate after three failed attempts to
  fix the same test cluster.
- End-to-end tolerance: add an end-to-end test only if the change affects an
  externally observable workflow, integration contract, persistence, command
  line behaviour, network boundary, user interface flow, or system-level
  behaviour. If no such surface exists yet, document that no end-to-end test is
  warranted for this milestone.

## Risks

- Risk: the existing TEI scripts may not have a dedicated segment element or
  consistent segment locator convention. Severity: medium. Likelihood: medium.
  Mitigation: inspect existing TEI fixtures and `tei_rapporteur` payload
  support first. If no segment type is established, define the smallest local
  convention in an ADR and keep the generator accepting explicit segment
  metadata as an optional prompt input.

- Risk: podcast players use several chapter formats, including MP4 chapter
  atoms, ID3 chapters, and sidecar JSON. This milestone can overreach if it
  tries to generate every downstream format. Severity: medium. Likelihood:
  medium. Mitigation: store canonical chapter metadata in TEI with integer-only
  ISO 8601-style starts and optional durations. Leave audio-file embedding to
  the later audio synthesis pipeline, where mastering can project TEI chapters
  into player-specific formats.

- Risk: LLM-generated timestamps may drift from the source segment order.
  Severity: medium. Likelihood: medium. Mitigation: validate LLM output
  strictly, reject non-monotonic starts, and use property tests for timing
  invariants.

- Risk: Vidai Mock behavioural tests can become brittle if they assert exact
  prompt wording. Severity: low. Likelihood: medium. Mitigation: assert
  structural facts about the outbound request, such as the presence of TEI XML,
  segment identifiers, and chapter schema instructions.

- Risk: chapter markers overlap with show notes, because the user guide
  currently describes show notes as including chapter markers. Severity: low.
  Likelihood: high. Mitigation: document the distinction: show notes are topic
  summaries, while chapter markers are navigational playback boundaries.

## Progress

- [x] (2026-05-08 00:00Z) Drafted this ExecPlan from roadmap item 2.3.2,
  existing show-notes implementation, and the named design documents.
- [x] (2026-05-08 00:00Z) User approved implementation by asking to proceed
  with the planned functionality.
- [x] (2026-05-08 00:00Z) Stage A: inspected current TEI segment conventions
  and documented representation gaps.
- [x] (2026-05-08 00:00Z) Stage B: wrote fail-first unit, property, and BDD
  tests; the first focused run failed because the chapter-marker module and
  exports did not exist.
- [x] (2026-05-08 00:00Z) Stage C: implemented
  `episodic/generation/chapter_markers.py` and package exports.
- [x] (2026-05-08 00:00Z) Stage D: added Vidai Mock behavioural coverage and
  verified it in the focused suite.
- [x] (2026-05-08 00:00Z) Stage E: updated ADR, system design, developer's
  guide, user's guide, and roadmap.
- [x] (2026-05-08 00:00Z) Stage F: ran all required gates sequentially on the
  final tree. `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie` passed.
- [x] (2026-05-10 00:00Z) Addressed review follow-ups for idempotent empty
  chapter enrichment, optional-field type validation, stronger prompt and TEI
  tests, syrupy XML snapshots, BDD TEI enrichment, process-cleanup reuse,
  README and guide signposting, and chapter-generator usage documentation.
- [x] (2026-05-10 00:00Z) Addressed follow-up review comments for validating
  generated chapter starts and locators against explicit segment metadata,
  clarifying the integer-only duration subset, covering omitted prompt segment
  metadata and malformed response payloads, and sharing TEI payload helpers
  with show-notes enrichment.
- [x] (2026-05-10 00:00Z) Addressed post-rebase review findings for
  user-facing configuration accuracy, generic execplan paths, ADR footnote
  formatting, stronger empty-result assertions, complete TEI replacement
  snapshots, and chapter-marker concurrency/cancellation coverage.

## Surprises & discoveries

- Observation: profile-template and API fixtures store segment structure as
  JSON-like metadata such as `{"segments": ["intro", "main", "outro"]}`, while
  current TEI fixtures mostly use paragraphs and optional `xml:id` values
  rather than a dedicated segment element. Evidence:
  `tests/test_profile_template_service.py`,
  `tests/test_profile_template_api.py`, and `tests/test_show_notes.py`. Impact:
  the chapter generator will accept explicit `segment_structure` metadata and
  will use `tei_locator`/`@corresp` to align generated chapters back to segment
  transitions without requiring a new TEI segment element.

- Observation: the show-notes TEI representation already proves that
  `tei_rapporteur` preserves `<div type="...">`, `<list>`, `<item>`, `<label>`,
  `@n`, and `@corresp`. Evidence: `episodic/generation/show_notes.py` and
  `docs/adr/adr-004-show-notes-tei-representation.md`. Impact: chapter markers
  can reuse the same canonical container pattern with `div_type="chapters"` and
  avoid dependency or parser changes.

- Observation: `tei_rapporteur` does not preserve attempted `dur` payload
  metadata on `<item>`, and it rejects list items with empty inline content.
  Evidence: focused test run logged in
  `/tmp/test-episodic-2-3-2-chapter-markers-focused.out`. Impact: canonical TEI
  stores the required player timing in `@n` and source alignment in `@corresp`.
  Optional `duration` and `end` remain DTO fields for LLM validation but are
  not emitted into TEI until the TEI tooling exposes a supported attribute.
  When no summary exists, TEI inline content falls back to the chapter title so
  the document remains valid.

- Observation: the original empty-result path returned the input TEI before
  removing an existing chapter block. Evidence: review feedback requested
  `test_enrich_tei_with_empty_result_removes_existing_chapters`. Impact:
  `enrich_tei_with_chapter_markers(...)` now always parses and filters existing
  canonical chapter blocks. It appends a new block only when chapters are
  present, and returns the original TEI only when there was nothing to remove.

- Observation: `generate(...)` previously validated monotonic starts but not
  alignment to supplied segment-transition starts. Evidence: review feedback
  supplied a counterexample with segment starts at `PT0S` and `PT5M30S` and LLM
  output at `PT1S` and `PT2M`. Impact: generated chapters are now checked
  against explicit segment starts before returning, and locators must resolve
  to the same supplied transition start.

- Observation: the chapter-marker parser intentionally accepts only
  integer-only `PT#H#M#S` durations, while earlier wording said generic ISO
  8601 durations. Evidence: review feedback noted rejected valid ISO 8601 forms
  such as fractional seconds and day-based durations. Impact: prompts, errors,
  and documentation now describe the supported ISO 8601-style subset instead of
  implying full ISO 8601 duration support.

## Decision log

- Decision: model chapter markers as content enrichment in
  `episodic/generation/`, not as QA or persistence infrastructure. Rationale:
  roadmap 2.3 is content enrichment and TEI body generation. The existing
  show-notes service already establishes `episodic/generation/` as the home for
  enrichment services that use `LLMPort` and emit TEI metadata. Date/Author:
  2026-05-08 / ExecPlan.

- Decision: store canonical chapter timing in TEI as integer-only
  ISO 8601-style `PT#H#M#S` durations rather than player-specific chapter
  payloads. Rationale: TEI remains the canonical authoring model.
  Player-specific projections belong to the audio mastering pipeline, while
  this task only needs portable timing metadata for later podcast-player
  compatibility. Date/Author: 2026-05-08 / ExecPlan.

- Decision: require property tests for timing rules.
  Rationale: chapter timing introduces invariants over arbitrary ordered and
  unordered inputs. Unit examples are not enough to prove monotonicity,
  non-negative starts, and duration formatting across a useful input range.
  Date/Author: 2026-05-08 / ExecPlan.

- Decision: align chapters through explicit `segment_structure` metadata and
  optional TEI locators rather than inventing a dedicated TEI segment element
  in this milestone. Rationale: existing code consistently treats segment
  layouts as template structure metadata, while current TEI examples do not
  establish a separate segment element convention. The generator can therefore
  align chapter boundaries to segment transitions without widening the
  canonical TEI model. Date/Author: 2026-05-08 / Implementation.

- Decision: emit only `@n` and `@corresp` timing/alignment attributes in the
  canonical TEI chapter block for this milestone. Rationale: `@n` carries the
  required ISO 8601 chapter start time, which is the player-compatible boundary
  needed by roadmap item 2.3.2. `tei_rapporteur` drops an attempted `dur`
  payload field, so forcing unsupported optional duration metadata into TEI
  would create false persistence expectations. Date/Author: 2026-05-08 /
  Implementation.

- Decision: keep observability lightweight by logging bounded lifecycle events
  and parser failures from the chapter-marker service, without adding a metrics
  or tracing dependency in this milestone. Rationale: the repository has a
  logging facade but no local metrics/tracing port for generation services yet.
  Adding only bounded log messages avoids sensitive TEI or prompt leakage and
  stays within the no-new-dependency constraint. Date/Author: 2026-05-10 /
  Review follow-up.

## Outcomes & retrospective

The implementation delivered a chapter-marker enrichment service, tests,
documentation, ADR, and roadmap update. The feature keeps inference behind the
existing `LLMPort`, stores canonical chapter starts as integer-only ISO
8601-style durations in TEI `@n`, and validates ordering and supplied segment
alignment before enrichment.

Validation on the final tree passed:

- `make check-fmt`
- `make typecheck`
- `make lint`
- `make test` with 475 passed and 3 skipped
- `make markdownlint`
- `make nixie`

Review follow-up validation started with focused chapter-marker coverage:

```bash
uv run pytest tests/test_chapter_markers.py \
  tests/steps/test_chapter_markers_steps.py --snapshot-update
```

It passed with 36 tests and generated two syrupy snapshots. The full gate
sequence was then rerun on the review follow-up tree and passed:

- `make check-fmt`
- `make typecheck`
- `make lint`
- `make test` with 475 passed and 3 skipped
- `make markdownlint`
- `make nixie`

Segment-alignment review follow-up validation added explicit checks that LLM
chapter starts and locators match supplied segment metadata. Focused validation
passed:

```bash
uv run pytest tests/test_chapter_markers.py tests/test_show_notes.py
```

Post-rebase review follow-up validation added focused chapter-marker tests,
generated one additional syrupy snapshot, and reran the full gate sequence. The
first `make test` run hit a transient timeout in an unrelated profile-template
service fixture; the exact timed-out test passed when rerun alone, and the full
`make test` rerun then passed with 488 tests and 3 skipped.

The full gate sequence was then rerun on the segment-alignment follow-up tree.
An initial `make test` run hit a transient async fixture timeout in
`tests/test_profile_template_service.py::TestEpisodeTemplateService::test_update_episode_template_revision_conflict_raises`;
 that single test passed when rerun directly. A subsequent full `make test` run
passed with 485 tests and 3 skipped. Final validation passed:

- `make check-fmt`
- `make typecheck`
- `make lint`
- `make test` with 485 passed and 3 skipped
- `make markdownlint`
- `make nixie`

## Context and orientation

The relevant roadmap entry is in `docs/roadmap.md` under "2.3. Content
enrichment and TEI body generation". Item 2.3.1, show-notes generation, is
already complete and provides the closest implementation pattern. The current
show-notes service lives in `episodic/generation/show_notes.py`, exports
dataclasses and a generator through `episodic/generation/__init__.py`, uses
`LLMPort` from `episodic/llm/ports.py`, and enriches TEI via `tei_rapporteur`.

The design document `docs/episodic-podcast-generation-system-design.md` says
the Content Generation Orchestrator produces structured drafts, show notes,
chapter markers, and sponsorship copy. It also states that show notes already
use a composable `LLMPort`-backed enrichment service. Chapter markers should
follow that shape so future LangGraph orchestration can call the service
without depending on adapter details.

The terms used in this plan are:

- Text Encoding Initiative (TEI): the XML-based canonical document model for
  scripts and generated metadata.
- Segment: a coherent part of a script, such as an introduction, interview
  section, sponsor break, or conclusion. The implementation must align chapter
  boundaries to transitions between these segments.
- Chapter marker: a navigational playback boundary with a title, start time,
  optional end time or duration, optional summary, and optional source locator.
- Supported duration: an integer-only ISO 8601-style `PT#H#M#S` text format
  for elapsed time, such as `PT45S` or `PT7M30S`. Days and fractional units are
  outside this milestone's parser.
- Vidai Mock: the local LLM provider simulator used by behavioural tests.

## Plan of work

Stage A is discovery. Inspect `episodic/generation/show_notes.py`,
`tests/test_show_notes.py`, `tests/features/show_notes.feature`,
`tests/steps/test_show_notes_steps.py`,
`docs/adr/adr-004-show-notes-tei-representation.md`, and representative TEI
fixtures in tests. Confirm how script segments are represented today. If there
is no segment convention, choose a narrow one for this feature and record it in
a new ADR before implementing code. A likely canonical shape is a TEI
`<div type="chapters">` metadata block containing one `<list>` of `<item>`
children, where each item uses `<label>` for the chapter title, inline text for
the summary, `@n` for the start time, and `@corresp` for the source segment
locator. If end time or duration is required, prefer an attribute already
supported by `tei_rapporteur`; otherwise stop and document the tooling gap
before changing dependencies.

Stage B is fail-first tests. Add `tests/test_chapter_markers.py` for unit tests
covering `ChapterMarker`, `ChapterMarkersResult`,
`ChapterMarkersGeneratorConfig`, strict JSON response parsing, prompt
construction, empty results, malformed LLM responses, TEI escaping, replacement
of an existing chapters div, and validation of invalid timing. Add Hypothesis
tests in the same file, or in a focused
`tests/test_chapter_marker_properties.py` if the file becomes too large, for
non-negative and monotonic timing invariants. Add
`tests/features/chapter_markers.feature` and
`tests/steps/test_chapter_markers_steps.py` for the Vidai Mock scenario.

Stage C is implementation. Add `episodic/generation/chapter_markers.py` with
frozen dataclasses using `slots=True`:

```python
@dc.dataclass(frozen=True, slots=True)
class ChapterMarker:
    title: str
    start: str
    summary: str = ""
    end: str | None = None
    duration: str | None = None
    tei_locator: str | None = None
```

The exact field names may change during Stage A if repository conventions point
to a better shape, but the service must expose the same core facts: title,
start time, optional end or duration, optional summary, and optional TEI
locator. Implement `ChapterMarkersGenerator` with the same contract shape as
`ShowNotesGenerator`: `build_prompt(...)`, `_result_from_response(...)`, and an
async `generate(...)` method that sends an `LLMRequest` through `LLMPort`.
Implement an `enrich_tei_with_chapter_markers(...)` helper that parses TEI,
removes any existing canonical chapters div, appends the new chapters div, and
emits valid TEI XML.

Stage D is behavioural validation. Configure a temporary Vidai Mock provider
inside the BDD step file, start it on an ephemeral localhost port, and call the
real `OpenAICompatibleLLMAdapter` against it. Assert that the resulting chapter
markers contain expected titles and ISO 8601 starts, and that the captured
outbound request includes the TEI script plus segment information. Keep prompt
assertions structural.

Stage E is documentation. Add a new ADR, likely
`docs/adr/adr-006-chapter-marker-tei-representation.md`, unless ADR 005 is
already taken by the current branch. Update
`docs/episodic-podcast-generation-system-design.md` to mention the chapter
marker service next to show notes. Update `docs/developers-guide.md` with the
new module, DTOs, error handling, and test locations. Update
`docs/users-guide.md` to separate show notes from chapter markers and describe
the timing rules visible to users. When the feature is complete and all gates
pass, mark roadmap item 2.3.2 as `[x]` in `docs/roadmap.md`.

Stage F is validation and commit. Run all required gates sequentially with
`tee` logs under `/tmp`. If formatting changes are needed, run `make fmt`, then
repeat `make check-fmt`. After gates pass, commit the feature with an
imperative commit message using the repository's commit-message rules.

## Concrete steps

Work from the repository root:

```plaintext
<episodic repository root>
```

First confirm the branch is not the main branch:

```bash
git branch --show-current
```

Expected output for this plan draft:

```plaintext
feat/chapter-marker-plan
```

Use Leta for code navigation when looking for definitions and references:

```bash
leta workspace add <episodic repository root>
leta show ShowNotesGenerator
leta refs ShowNotesGenerator
```

Run the fail-first tests after Stage B. They should fail because the feature is
not implemented yet:

```bash
log=/tmp/test-episodic-$(git branch --show-current).out
make test 2>&1 | tee "$log"
```

After implementation, run these gates sequentially:

```bash
log=/tmp/check-fmt-episodic-$(git branch --show-current).out
make check-fmt 2>&1 | tee "$log"
```

```bash
log=/tmp/typecheck-episodic-$(git branch --show-current).out
make typecheck 2>&1 | tee "$log"
```

```bash
log=/tmp/lint-episodic-$(git branch --show-current).out
make lint 2>&1 | tee "$log"
```

```bash
log=/tmp/test-episodic-$(git branch --show-current).out
make test 2>&1 | tee "$log"
```

Because this feature changes Markdown documentation, also run:

```bash
log=/tmp/markdownlint-episodic-$(git branch --show-current).out
make markdownlint 2>&1 | tee "$log"
```

```bash
log=/tmp/nixie-episodic-$(git branch --show-current).out
make nixie 2>&1 | tee "$log"
```

If `make check-fmt` fails only because files need formatting, run:

```bash
log=/tmp/fmt-episodic-$(git branch --show-current).out
make fmt 2>&1 | tee "$log"
```

Then repeat `make check-fmt`.

## Validation and acceptance

The feature is accepted when all of the following are true:

- Unit tests prove that chapter marker DTOs reject blank titles, invalid ISO
  8601 start times, negative starts, duplicate or descending starts, malformed
  LLM response payloads, invalid optional fields, and malformed TEI input.
- Property tests prove that arbitrary generated ordered timings survive
  validation and TEI enrichment, while unordered or duplicate timings are
  rejected.
- Behavioural tests using Vidai Mock prove that the generator can call an
  OpenAI-compatible mock endpoint, parse deterministic chapter JSON, and send a
  prompt containing the TEI script and segment metadata.
- TEI enrichment emits a parseable and valid document containing exactly one
  `<div type="chapters">` block and one item per generated chapter.
- Documentation explains the user-visible timing behaviour and the
  maintainer-facing generation boundary.
- `docs/roadmap.md` marks item 2.3.2 as done after implementation, validation,
  and documentation are complete.
- `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie` all pass sequentially.

No end-to-end test is required if the implementation remains a standalone
generation service with no new external API, persistence contract, command-line
behaviour, network boundary, or user interface flow. If the implementation
wires chapter markers into an externally observable workflow, add an end-to-end
test for that workflow before marking the roadmap item done.

## Idempotence and recovery

The implementation steps are additive and can be repeated. TEI enrichment must
be idempotent for the canonical chapter container: running enrichment twice
with the same result should leave one `<div type="chapters">` block, not append
duplicates. Tests should cover this directly.

If a validation gate fails, inspect the corresponding `/tmp` log, make the
smallest relevant fix, and rerun only the failed gate first. Once the failed
gate passes, rerun the full ordered gate sequence. Do not delete unrelated
files or revert changes made by others. If a change conflicts with uncommitted
work in the same file, inspect the file and preserve unrelated edits.

If Vidai Mock is missing from `PATH`, skip only the Vidai Mock behavioural test
with a clear `pytest.skip(...)` message, matching the existing show-notes
behavioural test pattern. Do not replace Vidai Mock with a different inference
harness.

## Artifacts and notes

The closest existing implementation artefacts are:

- `episodic/generation/show_notes.py`
- `tests/test_show_notes.py`
- `tests/features/show_notes.feature`
- `tests/steps/test_show_notes_steps.py`
- `docs/adr/adr-004-show-notes-tei-representation.md`
- `docs/execplans/2-3-1-generate-show-notes-from-template-expansions.md`

The expected TEI shape must be finalized during Stage A. The starting proposal
is:

```xml
<div type="chapters">
  <list>
    <item n="PT5M30S" corresp="#seg-main">
      <label>Main discussion</label>
      The hosts move from setup into the central interview.
    </item>
  </list>
</div>
```

This is intentionally parallel to show notes. The `@n` attribute stores the
chapter start time as an integer-only ISO 8601-style duration, and `@corresp`
points back to the source segment or transition. If `tei_rapporteur` cannot
preserve this shape, document the failure in `Surprises & Discoveries`, record
a decision, and stop before changing the dependency pin.

## Interfaces and dependencies

Use the existing dependencies and interfaces:

- `episodic.llm.LLMPort`
- `episodic.llm.LLMRequest`
- `episodic.llm.LLMResponse`
- `episodic.llm.LLMUsage`
- `episodic.llm.LLMTokenBudget`
- `episodic.llm.LLMProviderOperation`
- `tei_rapporteur.parse_xml(...)`
- `tei_rapporteur.to_dict(...)`
- `tei_rapporteur.from_dict(...)`
- `tei_rapporteur.emit_xml(...)`

At the end of implementation, `episodic/generation/__init__.py` should export
the new public generation types and helpers, mirroring the show-notes exports.
The likely exported names are:

- `ChapterMarker`
- `ChapterMarkersResult`
- `ChapterMarkersGeneratorConfig`
- `ChapterMarkersGenerator`
- `ChapterMarkersResponseFormatError`
- `enrich_tei_with_chapter_markers`

The generator should expose this usage pattern:

```python
generator = ChapterMarkersGenerator(llm=llm_port, config=config)
result = await generator.generate(
    script_tei_xml,
    segment_structure={
        "segments": [
            {"id": "seg-intro", "title": "Introduction", "start": "PT0S"},
            {"id": "seg-main", "title": "Main discussion", "start": "PT5M30S"},
        ]
    },
)
enriched_xml = enrich_tei_with_chapter_markers(script_tei_xml, result)
```

Revision note: initial draft created on 2026-05-08 from roadmap item 2.3.2, the
completed show-notes plan and implementation, and the current architecture
guidance. It establishes implementation stages, validation gates, and the
proposed TEI representation for review before code work begins.
