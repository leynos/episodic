# Generate show notes from template expansions

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: IN_PROGRESS

## Purpose and big picture

Roadmap item 2.3.1 asks the system to generate show notes from template
expansions. After this change, the Content Generation Orchestrator can invoke a
large language model (LLM) via the existing `LLMPort` contract to extract key
topics and timestamps from generated podcast script content, then format the
results as structured metadata within a canonical Text Encoding Initiative
(TEI) body.

Success is observable in six ways:

1. A new `ShowNotesGenerator` service in `episodic/generation/show_notes.py`
   accepts a TEI script body (as XML text) and an episode template, calls the
   LLM through `LLMPort`, and returns a typed `ShowNotesResult` containing
   structured topic entries with optional timestamp metadata.
2. A new `ShowNotesEntry` frozen dataclass captures each show-note item: topic
   title, summary, optional timestamp (as an ISO 8601 duration), and optional
   TEI locator pointing back into the source script.
3. A TEI body enrichment helper formats `ShowNotesResult` into a TEI `<div>`
   element suitable for embedding as structured metadata within the canonical
   episode TEI body. The enriched TEI passes `tei_rapporteur` validation.
4. Unit tests (`pytest`) cover data transfer object (DTO) validation, JSON
   response parsing, edge cases (empty scripts, LLM refusals), and TEI
   enrichment output.
5. Behavioural tests (`pytest-bdd`) using Vidai Mock prove that one show-notes
   generation call drives a deterministic LLM interaction and returns a valid
   `ShowNotesResult` with correctly structured TEI output.
6. The required validation commands pass sequentially:
   `make check-fmt`, `make typecheck`, `make lint`, `make test`,
   `PATH=/root/.bun/bin:$PATH make markdownlint`, and `make nixie`.

The change fits into the broader Content Generation Orchestrator described in
the system design document. The orchestrator's Generate node "invoke[s]
`LLMPort` to produce draft content, show notes, and enrichments." This plan
implements the show-notes portion of that responsibility as a standalone,
testable service that a future LangGraph node can compose.

## Constraints

- Preserve hexagonal architecture boundaries. The new show-notes service must
  depend only on domain types and ports (`LLMPort`, domain dataclasses). It
  must not import Falcon, SQLAlchemy, Celery, LangGraph, or HTTP client modules.
- Keep TEI P5 as the canonical data spine. Show notes are expressed as TEI
  `<div type="notes">` elements, not as a competing JSON schema. Any JSON
  representation used for LLM prompt construction is a projection of the
  TEI-backed content model.
- Use `LLMPort.generate(LLMRequest) -> LLMResponse` for all model calls. Do
  not introduce a new LLM contract or bypass the existing adapter boundary.
- Keep the `episodic/qa/` package boundary intact. Show notes generation is
  content enrichment, not quality assurance. Place the new code under
  `episodic/generation/`, a new package for content generation services.
- Do not modify existing public interfaces in `episodic/canonical/domain.py`,
  `episodic/canonical/ports.py`, or `episodic/llm/ports.py` without escalation.
- Follow the repository's lint, type-checking, and formatting rules. Use
  `import typing as typ` (not `from typing import ...` except for
  `TYPE_CHECKING` with `# noqa: ICN003`). Use frozen dataclasses with
  `slots=True` for data transfer objects (DTOs). Use `type` aliases
  (Python 3.14 style) for type definitions.
- Follow the documentation style guide in `docs/documentation-style-guide.md`:
  British English (Oxford style), sentence-case headings, 80-column wrapping
  for prose, 120 columns for code, expand acronyms on first use.
- Test-support modules under `tests/` must use `test_*` naming to satisfy Ruff
  test-file exemptions.
- Vidai Mock remains the only behavioural inference harness.
- Record any new durable representation decision in an Architecture Decision
  Record (ADR).

## Tolerances (exception triggers)

- Scope tolerance: stop and escalate if implementation requires changes to more
  than 18 files or 1200 net new lines before a working vertical slice exists.
- Interface tolerance: stop and escalate if implementing show notes requires
  modifying the public signatures of `LLMPort`, `LLMRequest`, `LLMResponse`, or
  any existing domain entity.
- Dependency tolerance: stop and escalate if a new runtime dependency is
  required beyond what is already in `pyproject.toml`.
- TEI tooling tolerance: stop and escalate if the installed `tei_rapporteur`
  Python surface cannot validate show-notes TEI output without changing the
  dependency pin.
- Iteration tolerance: stop and escalate after three failed attempts to settle
  the same test cluster or behaviour scenario.
- Ambiguity tolerance: stop and escalate if the TEI representation of show
  notes has multiple plausible structures and the choice would affect later
  enrichment tasks (2.3.2 chapter markers, 2.3.3 guest bios, 2.3.4 sponsor
  reads).

## Risks

- Risk: **MITIGATED** — `tei_rapporteur` at commit `ad7642f` did not support
  `<div>`, `<list>`, `<item>`, or `<label>` elements. Commit `ffb25c6` added
  full Rust core, parser, emitter, PyO3 projection, and JSON schema support for
  these elements, and commit `016ef253` added complete documentation. The
  `pyproject.toml` pin has been updated to `016ef253`; existing episodic tests
  pass (continuous integration (CI) gate logs capture validation results). The
  upstream library now
  includes Python `msgspec` struct support:
  `BodyBlock = Paragraph | Utterance | DivBlock`,
  `DivContent = Paragraph | Utterance | ListBlock`, and `Event` includes
  `DivEvent`. The ODD and Relax NG schemas were also updated in the same
  release: CI now runs `jing` validation against a `div-list` fixture without
  skipping, confirming that external XML validation accepts `<div>`, `<list>`,
  `<item>`, and `<label>` elements. One structural constraint applies: `<list>`
  is only permitted as a child of `<div>`, not as a direct child of `<body>`.
  All previously identified gaps are now resolved. Severity: low (residual,
  structural constraint only). Likelihood: low. Mitigation: none required.

- Risk: the LLM response format for show notes may be difficult to parse
  reliably, especially for timestamp extraction. Severity: medium. Likelihood:
  low. Mitigation: use the same strict JSON parsing pattern established by
  Pedante (`_decode_object`, `_require_non_empty_string`, `_coerce_enum`), and
  make timestamps optional with a clear "no timestamp available" sentinel.

- Risk: show-notes generation depends on having generated script content, but
  no generation pipeline exists yet (roadmap 2.4). The service must work
  standalone with test fixtures representing plausible script content.
  Severity: low. Likelihood: certain. Mitigation: design the service to accept
  a TEI XML string and optional template metadata, making it composable into
  future orchestration without coupling to unbuilt infrastructure.

- Risk: Vidai Mock behavioural tests may be fragile if the show-notes prompt
  format changes during development. Severity: low. Likelihood: medium.
  Mitigation: keep the Vidai Mock response template minimal and assert on
  result structure rather than exact prompt text.

- Risk: the `episodic/generation/` package is new and may conflict with
  naming expectations for later generation orchestration code. Severity: low.
  Likelihood: low. Mitigation: keep the package narrowly scoped to content
  enrichment services and document the intended boundary in the developer's
  guide.

## Progress

- [x] Stage A: research and propose (no code changes).
- [x] Stage B: prototype TEI enrichment and validate with `tei_rapporteur`.
- [x] Stage C: implement data transfer objects (DTOs) and strict JSON response
  parsing with fail-first unit tests.
- [x] Stage D: implement show-notes generator service with LLM prompt
  construction.
- [x] Stage E: implement TEI body enrichment and round-trip validation.
- [x] Stage F: implement Vidai Mock behavioural tests.
- [x] Stage G: write ADR, update design document, user's guide, and
  developer's guide.
- [x] Stage H: run the full validation gates and update roadmap.

## Surprises & discoveries

### `tei_rapporteur` support for show-notes TEI blocks (2026-04-03 / 2026-04-10)

Early investigation found that `tei_rapporteur` could not safely round-trip
`<div type="notes">` structures. That gap is now closed by upstream work in
[PR #56](https://github.com/leynos/tei-rapporteur/pull/56), with the current
dependency pin landing on commit
[`016ef253`](https://github.com/leynos/tei-rapporteur/commit/016ef253b768c98d7d3664074928d70273eb3793).

The Episodic branch relies on the following upstream contract only:

- `parse_xml(...)`, `to_dict(...)`, `from_dict(...)`, and `emit_xml(...)`
  preserve `<div>`, `<list>`, `<item>`, and `<label>` structures in the body.
- `<list>` remains nested under `<div>`, not directly under `<body>`.
- Relax NG validation accepts the enriched show-notes shape, so continuous
  integration (CI) can validate emitted TEI without special-casing the notes
  block.

This plan deliberately avoids duplicating upstream parser internals or schema
implementation details. If future upstream regressions appear, start with PR
`#56` and the pinned commit above before extending this plan.

## Decision log

- Decision: place show-notes generation in a new `episodic/generation/`
  package rather than in `episodic/qa/` or `episodic/canonical/`. Rationale:
  show notes are content enrichment, not quality assurance or canonical
  persistence. The `qa/` package is scoped to evaluators (Pedante, Bromide,
  Chiltern, Anthem, Caesura, Chrono). The `canonical/` package owns
  persistence, domain entities, and ingestion. Generation services are a
  distinct concern that the system design assigns to the Content Generation
  Orchestrator. A dedicated `generation/` package keeps concerns separated and
  provides a natural home for future enrichment services (chapter markers,
  guest bios, sponsor reads). Date/Author: 2026-04-02 / ExecPlan.

- Decision: model show-notes entries with optional timestamps rather than
  requiring them. Rationale: generated scripts may not have timing information
  until later in the pipeline (after Chrono estimation or TTS synthesis). The
  show-notes generator extracts what the LLM can infer from the script
  structure. Actual playback timestamps are a concern of 2.3.2 (chapter
  markers) and the audio pipeline. Date/Author: 2026-04-02 / ExecPlan.

- Decision: represent show notes in TEI as a `<div type="notes">` container
  with `<list>` and `<item>` children. Rationale: TEI P5 guidelines use `<div>`
  with a `@type` attribute to denote functional divisions of text. A `<list>`
  of `<item>` elements is the natural TEI idiom for enumerating topics.
  Timestamps and locators attach as attributes on `<item>`. tei-rapporteur
  `ffb25c6` added code support for `<div>`, `<list>`, `<item>`, and `<label>`
  at the Rust core, parser, emitter, and PyO3 projection layers; `016ef253`
  added documentation and Python msgspec struct definitions (`DivBlock`,
  `ListBlock`, `Item`, `Label`). Date/Author: 2026-04-02 / ExecPlan; updated
  2026-04-10.

- Decision: use inline text (not `<p>` elements) for summary content within
  `<item>` elements. Rationale: tei-rapporteur schema expects `<item>` to
  contain optional `<label>` followed by inline content, not block-level
  elements. The structure
  `<item><label>Topic</label>Inline summary text</item>` parses and validates
  correctly, while `<item><label>Topic</label><p>Summary </p></item>` fails
  with "data did not match any variant of untagged enum Inline". This matches
  the TEI P5 Episodic Profile where list items are meant for brief annotations,
  not full paragraphs. Date/Author: 2026-04-12 / Implementation.

### Documentation and tooling status (2026-04-12)

- `qdrant-find`/`qdrant-store` tooling is not exposed in this session, so the
  required project-memory lookup/store protocol could not be executed here.
- Stage G documentation work now exists in-tree:
  - `docs/adr/adr-003-show-notes-tei-representation.md`
  - `docs/episodic-podcast-generation-system-design.md`
  - `docs/users-guide.md`
  - `docs/developers-guide.md`
- The implementation-defined TEI shape supersedes the earlier Stage G draft:
  summaries are inline text inside `<item>`, not nested `<p>` elements.

### Validation-gate results (2026-04-12; refreshed 2026-04-16)

- `make fmt` passed after supplying temporary PATH helpers for `fd` and
  `mdtablefix`, because the repository-local `mdformat-all` wrapper assumes
  those executables are present in the shell environment.
- `make check-fmt` passed.
- `make typecheck` passed, with existing unrelated `redundant-cast` warnings.
- `make lint` passed.
- `make markdownlint` passed.
- `make nixie` passed.
- `make test` now passes on the rebased branch:
  `351 passed, 3 skipped`. The earlier py-pglite / `libpq` blocker was resolved
  during subsequent validation work, so Stage H can now be marked complete.

## Outcomes & retrospective

Stage A completed. Research confirmed that tei-rapporteur at commit `ad7642f`
did not support `<div>`, `<list>`, `<item>`, or `<label>`. The gap was filed
with the maintainer and resolved in commits `ffb25c6` (code) and `016ef253`
(documentation and Python msgspec structs). The dependency pin has been updated
to `016ef253` and the TEI representation strategy is settled:
`<div type="notes"><list><item>` with `<label>` for topic, inline text for
summary, `@n` for timestamp, `@corresp` for locator.

Stages B–E completed (2026-04-12; updated 2026-04-14). Created
`episodic/generation/` package with `ShowNotesGenerator`, DTOs
(`ShowNotesEntry`, `ShowNotesResult`, `ShowNotesGeneratorConfig`), strict JSON
parsing, and
`enrich_tei_with_show_notes` TEI enrichment helper. All 14 unit tests pass. Key
findings:

- tei_rapporteur expects simplified `<fileDesc><title>` structure, not
  `<fileDesc><titleStmt><title>`.
- `<item>` elements contain inline content after `<label>`, not `<p>` block
  elements. Correct structure:
  `<div type="notes"><list><item><label>Topic </label>Inline summary text</item></list></div>`.
- TEI enrichment now uses `tei_rapporteur.parse_xml(...)`,
  `tei_rapporteur.to_dict(...)`, `tei_rapporteur.from_dict(...)`, and
  `tei_rapporteur.emit_xml(...)` to append a structured `div` block instead of
  mutating XML via string concatenation.

Stages F and G completed (2026-04-12). Vidai Mock BDD coverage exists in
`tests/features/show_notes.feature` and `tests/steps/test_show_notes_steps.py`.
Documentation now includes ADR-003 plus design, user, and developer guide
updates.

Stage H completed (2026-04-16). The rebased branch now passes formatting,
linting, type-checking, unit and behavioural tests, Markdown linting, and
Mermaid validation, and roadmap item `2.3.1` is marked done. This ExecPlan is
therefore complete.

Review follow-up on 2026-04-14 tightened two behavioural edges:

- `ShowNotesEntry.timestamp` now rejects non-ISO 8601 duration strings during
  parsed-entry validation, so malformed values such as `5:30` no longer leak
  into `@n` attributes.
- `enrich_tei_with_show_notes(...)` now replaces any existing
  `<div type="notes">` block before inserting the regenerated notes payload, so
  reruns keep a single canonical notes container.

## Context and orientation

The following files and modules are relevant to this plan. Every path is
relative to the repository root.

### Domain layer

- `episodic/canonical/domain.py` — frozen dataclasses for all domain entities:
  `SeriesProfile`, `EpisodeTemplate`, `CanonicalEpisode`, `TeiHeader`,
  `ReferenceDocument`, and their supporting types. The `JsonMapping` type alias
  (`dict[str, object]`) is defined here.
- `episodic/canonical/ports.py` — repository protocols and
  `CanonicalUnitOfWork`. Defines the persistence boundary.
- `episodic/canonical/tei.py` — TEI parsing wrapper around `tei_rapporteur`.
  Provides `parse_tei_header(xml: str) -> TeiHeaderPayload`.

### LLM boundary

- `episodic/llm/ports.py` — defines `LLMPort` (the protocol with
  `generate(request: LLMRequest) -> LLMResponse`), `LLMRequest`, `LLMResponse`,
  `LLMUsage`, `LLMTokenBudget`, and the error hierarchy (`LLMError`,
  `LLMProviderResponseError`, `LLMTransientProviderError`,
  `LLMTokenBudgetExceededError`).
- `episodic/llm/openai_adapter.py` — `OpenAICompatibleLLMAdapter` implements
  `LLMPort` for OpenAI-compatible providers.

### QA evaluators (pattern reference)

- `episodic/qa/pedante.py` — the Pedante factuality evaluator. This is the
  reference pattern for how to structure an LLM-backed service: frozen DTO
  dataclasses, strict JSON parsing helpers, a config dataclass, and an
  evaluator class that composes `LLMPort`. Key helpers to reuse or mirror:
  `_decode_object`, `_require_non_empty_string`, `_require_list`,
  `_coerce_enum`, `_coerce_string_tuple`.
- `episodic/qa/langgraph.py` — the minimal LangGraph seam for Pedante. Shows
  the pattern of a `Protocol` port, a graph state dataclass, a node function, a
  routing function, and a `build_*_graph(...)` factory.
- `episodic/qa/__init__.py` — public exports for the QA package.

### Template and brief system

- `episodic/canonical/prompts.py` — Python 3.14 template string rendering with
  interpolation audit metadata. Provides `render_template(...)`,
  `build_series_brief_template(...)`, and `render_series_brief_prompt(...)`.
- `episodic/canonical/profile_templates/brief.py` — assembles structured
  briefs from series profiles, episode templates, and reference bindings.

### TEI library

- `docs/tei-rapporteur-users-guide.md` — documents the TEI body model, Python
  bindings (`msgspec.Struct` classes), validation, and citation metadata. The
  body model supports paragraphs (`<p>`), utterances (`<u>`) with optional
  speaker attribution, thematic divisions (`<div>`) with a required `@type`
  attribute, lists (`<list>` permitted only as children of `<div>`), list items
  (`<item>`) with optional `@n`, `@corresp`, and `@xml:id` attributes, item
  labels (`<label>`), inline emphasis (`<hi>`), and pause cues (`<pause/>`).
  Stand-off overlays use `<standOff>` with `<spanGrp>` and `<span>`.

### Testing infrastructure

- `tests/conftest.py` — global fixtures including py-pglite database, Falcon
  test client, OpenAI adapter factories, and request/response builders.
- `tests/features/pedante.feature` — BDD feature file for Pedante (pattern
  reference).
- `tests/steps/test_pedante_steps.py` — BDD step implementations for Pedante
  using Vidai Mock. Key patterns: `PedanteBDDContext` dataclass for shared
  state, `_find_free_port()`, `_write_provider_config(...)`,
  `_write_response_template(...)`, `_start_vidaimock_process(...)`,
  `_await_port_ready(...)`, `_run_async_step(...)`.

### Existing documentation

- `docs/episodic-podcast-generation-system-design.md` — system architecture.
  The Content Generation Orchestrator section (line 164) states the
  orchestrator "produces structured drafts, show notes, chapter markers, and
  sponsorship copy." The Content Generation Graph (line 432) specifies the
  Generate node "invoke[s] `LLMPort` to produce draft content, show notes, and
  enrichments."
- `docs/users-guide.md` — user-facing guide. Currently mentions "Managing
  episode metadata and show notes" as a planned capability.
- `docs/developers-guide.md` — developer-facing practices. Covers QA
  evaluators, LLM adapter boundary, and testing patterns.
- `docs/roadmap.md` — the roadmap. Item 2.3.1 is unchecked.
- `docs/adr-001-pedante-evaluator-contract.md` — reference for ADR format.

### Terms used in this plan

- Show notes: a structured list of key topics, summaries, and optional
  timestamps extracted from a generated podcast script. Show notes appear in
  podcast feeds and player interfaces to help listeners navigate episodes.
- TEI body enrichment: the process of inserting structured metadata (show
  notes, chapter markers, guest bios) into the TEI `<text><body>` element of a
  canonical episode document.
- Template expansion: the process of rendering an episode template with series
  profile configuration and reference documents to produce the prompt scaffold
  that drives content generation. Show notes generation uses the expanded
  template's structure metadata to understand segment ordering and timing cues.
- `tei_rapporteur`: the Rust-backed Python library that parses, validates, and
  emits TEI P5 XML. It provides `parse_xml(...)`, `emit_xml(...)`,
  `validate()`, and `msgspec.Struct` projections.

## Plan of work

### Stage A: research and propose (no code changes)

Verify that `tei_rapporteur` can parse and validate TEI documents containing
`<div type="notes">` elements with `<list>` and `<item>` children in the body.
Run a quick interactive test using `tei_rapporteur.parse_xml(...)` with a
minimal TEI document that includes a notes division.

If `tei_rapporteur` rejects the enriched body, determine whether the library
supports custom `<div>` types and document the finding. If unsupported, the TEI
enrichment helper will assemble XML text directly using a builder function
rather than the structured `tei_rapporteur` API.

Acceptance for Stage A: the plan is updated with findings about
`tei_rapporteur` body support, and the TEI representation strategy is settled.

### Stage B: prototype TEI enrichment and validate

Create a minimal test in `tests/test_show_notes.py` that:

1. Constructs a simple TEI document with a body containing at least one
   paragraph.
2. Appends a `<div type="notes">` element containing a `<list>` with
   `<item>` entries.
3. Parses the enriched document with `tei_rapporteur.parse_xml(...)` or, if
   Stage A found that unsupported, validates the XML is well-formed.
4. Asserts the round-trip preserves the notes content.

This test starts red (the enrichment helper does not exist yet) and will turn
green in Stage E. The purpose is to nail down the TEI representation before
writing production code.

Acceptance for Stage B: the test exists, runs, and fails with a clear message
about the missing enrichment helper.

### Stage C: implement data transfer objects (DTOs) and strict JSON response parsing

Create the `episodic/generation/` package with the following files:

- `episodic/generation/__init__.py` — public exports.
- `episodic/generation/show_notes.py` — all show-notes types and service logic.

Define the following frozen dataclasses in `show_notes.py`:

```python
@dc.dataclass(frozen=True, slots=True)
class ShowNotesEntry:
    topic: str
    summary: str
    timestamp: str | None = None
    tei_locator: str | None = None
```

The `topic` field is a short heading for the show-note item. The `summary`
field is a one-to-three sentence description. The `timestamp` field is an
optional ISO 8601 duration string (for example `PT5M30S` for five minutes and
thirty seconds). The `tei_locator` field is an optional XPath or element
identifier pointing into the source script TEI body.

```python
@dc.dataclass(frozen=True, slots=True)
class ShowNotesResult:
    entries: tuple[ShowNotesEntry, ...]
    usage: LLMUsage
    model: str = ""
    provider_response_id: str = ""
    finish_reason: str | None = None
```

```python
@dc.dataclass(frozen=True, slots=True)
class ShowNotesGeneratorConfig:
    model: str
    provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )
    token_budget: LLMTokenBudget | None = None
    system_prompt: str = _DEFAULT_SYSTEM_PROMPT
```

```python
class ShowNotesResponseFormatError(ValueError):
    """Raised when the LLM response cannot be parsed into ShowNotesResult."""
```

Add strict JSON parsing helpers following the Pedante pattern:

- `_parse_entry(raw: dict[str, object]) -> ShowNotesEntry` — validates and
  extracts a single entry from a parsed JSON object.
- `_result_from_response(response: LLMResponse) -> ShowNotesResult` — parses
  the `response.text` as JSON, validates the top-level structure, and builds
  the typed result.

Write unit tests in `tests/test_show_notes.py` (extending from Stage B):

- Test `ShowNotesEntry` field validation (non-empty `topic` and `summary`).
- Test `ShowNotesResult` construction and `entries` tuple type.
- Test `_parse_entry` with valid input, missing fields, and empty strings.
- Test `_result_from_response` with a well-formed JSON response and with
  malformed responses (missing `entries` key, non-list entries, invalid entry
  shape).
- Test `ShowNotesResponseFormatError` is raised for unparseable responses.

Acceptance for Stage C:

- DTOs are defined and exported from `episodic/generation/__init__.py`.
- Unit tests for parsing pass.
- `make check-fmt`, `make typecheck`, and `make lint` pass.

### Stage D: implement show-notes generator service

Add the `ShowNotesGenerator` class to `episodic/generation/show_notes.py`:

```python
@dc.dataclass(slots=True)
class ShowNotesGenerator:
    llm: LLMPort
    config: ShowNotesGeneratorConfig

    @staticmethod
    def build_prompt(
        script_tei_xml: str,
        *,
        template_structure: JsonMapping | None = None,
    ) -> str:
        """Build the user prompt for show-notes extraction."""

    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: JsonMapping | None = None,
    ) -> ShowNotesResult:
        """Generate show notes from a TEI script body."""
```

The `build_prompt(...)` static method constructs a JSON-formatted prompt that
includes the TEI script body (or a projection of it) and optional template
structure metadata. The prompt instructs the model to extract key topics and
optional timestamps, and to return a JSON object with an `entries` array.

The `generate(...)` method builds the prompt, constructs an `LLMRequest` with
the configured model, system prompt, provider operation, and token budget,
calls `self.llm.generate(request)`, and parses the response via
`_result_from_response(...)`.

The default system prompt should read:

```plaintext
The assistant acts as a podcast show-notes generator. Given a TEI P5 podcast
script, extract the key topics discussed in the episode. For each topic,
provide a short heading and a one-to-three sentence summary. If the script
contains timing cues or segment markers, include an approximate timestamp as
an ISO 8601 duration (e.g. PT5M30S). Return JSON only with key "entries".
Each entry must include "topic" and "summary". Optional fields:
"timestamp" and "tei_locator".
```

Write unit tests:

- Test `build_prompt(...)` includes the TEI XML and template structure.
- Test `generate(...)` with a mock `LLMPort` returning a valid JSON response.
- Test `generate(...)` raises `ShowNotesResponseFormatError` when the LLM
  returns unparseable content.
- Test `generate(...)` raises `LLMProviderResponseError` when the LLM call
  fails.

Acceptance for Stage D:

- `ShowNotesGenerator` is functional with a mock `LLMPort`.
- All unit tests pass.
- `make check-fmt`, `make typecheck`, and `make lint` pass.

### Stage E: implement TEI body enrichment and round-trip validation

Add a TEI body enrichment helper to `episodic/generation/show_notes.py`:

```python
def enrich_tei_with_show_notes(
    tei_xml: str,
    result: ShowNotesResult,
) -> str:
    """Insert show-notes metadata into a TEI document body.

    Returns the enriched TEI XML as a string.
    """
```

This function parses the input TEI XML, constructs a `<div type="notes">`
element containing a `<list>` with `<item>` entries derived from
`result.entries`, replaces any existing notes division in the TEI body, and
emits the enriched document as XML text.

Each `<item>` element contains:

- A `<label>` child with the `topic` text.
- Inline text nodes containing the `summary` text after the `<label>`.
- An optional `@n` attribute with the `timestamp` value.
- An optional `@corresp` attribute with the `tei_locator` value.

Use the `tei_rapporteur` API via msgspec structs (`DivBlock`, `ListBlock`,
`Item`, `Label`) or `to_dict`/`from_dict` and `emit_xml` to produce the
structure. The Rust core, parser, and emitter at `ffb25c6` fully support
`<div>`, `<list>`, `<item>`, and `<label>`; commit `016ef253` adds complete
documentation and Python msgspec struct definitions.

**CI validation note:** `make nixie` runs full TEI body validation including
`div-list` fixture checks. The upstream Relax NG schema now accepts `<div>`,
`<list>`, `<item>`, and `<label>` elements, so enriched TEI documents pass
external validation without skipping.

Write and update unit tests:

- The Stage B prototype test should now pass.
- Test `enrich_tei_with_show_notes(...)` with a minimal TEI document and a
  `ShowNotesResult` containing two entries (one with timestamp, one without).
- Test that the enriched XML is well-formed and passes `tei_rapporteur`
  validation (or XML well-formedness validation if `tei_rapporteur` does not
  support the notes division).
- Test with an empty `ShowNotesResult` (no entries): the function should
  return the original TEI unchanged.
- Test with a `ShowNotesResult` whose entries contain XML-unsafe characters
  (ampersands, angle brackets) to verify proper escaping.

Acceptance for Stage E:

- TEI enrichment produces valid TEI XML.
- All unit tests pass.
- `make check-fmt`, `make typecheck`, `make lint`, and `make test` pass.

### Stage F: implement Vidai Mock behavioural tests

Create the BDD feature file `tests/features/show_notes.feature`:

```gherkin
Feature: Show notes generation from template expansions

  Scenario: Show notes generator extracts topics from a TEI script
    via a live Vidai Mock server
    Given a Vidai Mock show-notes server is running
    And a TEI script body is prepared for show-notes extraction
    When the show-notes generator processes the script
    Then the generator returns structured show-notes entries
    And the show-notes prompt includes the TEI script body
```

Create the step implementation file `tests/steps/test_show_notes_steps.py`:

- Define `ShowNotesBDDContext` (mirroring `PedanteBDDContext`):
  `process`, `base_url`, `script_tei_xml`, `template_structure`, `result`,
  `prompt_text`.
- Implement the `Given` steps to start Vidai Mock with a show-notes-specific
  provider configuration and response template.
- The response template returns a JSON response with a plausible `entries`
  array.
- Implement the `When` step to create an `OpenAICompatibleLLMAdapter`, build
  a `ShowNotesGenerator`, and call `generate(...)`.
- Implement the `Then` steps to assert result structure, entry count, and
  prompt content.

The Vidai Mock setup follows the Pedante pattern:

- `_write_provider_config(...)` writes a YAML provider matching
  `/v1/chat/completions`.
- `_write_response_template(...)` writes a Jinja2 template under
  `templates/show_notes/response.json.j2` with double-encoded JSON assistant
  content.
- `_start_vidaimock_process(...)` starts the server and waits for readiness.

Acceptance for Stage F:

- The BDD scenario passes.
- `make test` passes with all existing and new tests.

### Stage G: write ADR, update documentation

#### ADR

Write `docs/adr/adr-003-show-notes-tei-representation.md` documenting the
chosen TEI representation for show notes:

- Context: roadmap 2.3.1 requires show notes as structured metadata within TEI
  body.
- Decision: use `<div type="notes"><list><item>` with `<label>` for topic and
  inline summary text. Timestamps attach as `@n` attributes; script locators
  attach as `@corresp` attributes.
- Consequences: later enrichment tasks (2.3.2, 2.3.3, 2.3.4) should use the
  same `<div type="...">` pattern for their respective metadata types,
  establishing a consistent TEI enrichment convention.

#### Design document

Update `docs/episodic-podcast-generation-system-design.md`:

- In the Content Generation Orchestrator section, add a paragraph describing
  show-notes generation as a composable enrichment service behind `LLMPort`.
- Reference the new ADR.

#### User's guide

Update `docs/users-guide.md`:

- Under the "Content Creation" section, expand the "Managing episode metadata
  and show notes" bullet to describe what show notes contain (topics,
  summaries, optional timestamps) and how they are embedded in TEI body.

#### Developer's guide

Update `docs/developers-guide.md`:

- Add a new section "Content generation services" after "Quality-assurance
  evaluators" that documents:
  - The `episodic/generation/` package and its scope.
  - `ShowNotesGenerator` usage pattern (config, LLM port injection, calling
    `generate(...)`).
  - TEI enrichment via `enrich_tei_with_show_notes(...)`.
  - Testing with Vidai Mock (show-notes BDD scenario).

Acceptance for Stage G:

- ADR exists and follows the repository's ADR format.
- Documentation updates pass `make markdownlint` and `make nixie`.

### Stage H: run the full validation gates and update roadmap

Run the required gates sequentially and capture logs with `tee`. Do not run
`make test` and `make typecheck` in parallel, because this repository rebuilds
`.venv` inside those Make targets.

Use this exact pattern from the repository root:

```plaintext
set -o pipefail
make fmt 2>&1 | tee /tmp/show-notes-make-fmt.log
```

```plaintext
set -o pipefail
make check-fmt 2>&1 | tee /tmp/show-notes-make-check-fmt.log
```

```plaintext
set -o pipefail
make typecheck 2>&1 | tee /tmp/show-notes-make-typecheck.log
```

```plaintext
set -o pipefail
make lint 2>&1 | tee /tmp/show-notes-make-lint.log
```

```plaintext
set -o pipefail
make test 2>&1 | tee /tmp/show-notes-make-test.log
```

```plaintext
set -o pipefail
PATH=/root/.bun/bin:$PATH make markdownlint 2>&1 | tee /tmp/show-notes-make-markdownlint.log
```

```plaintext
set -o pipefail
make nixie 2>&1 | tee /tmp/show-notes-make-nixie.log
```

Mark roadmap item 2.3.1 as done in `docs/roadmap.md`.

Only after all gates pass should this ExecPlan be marked `COMPLETE`.

## Concrete implementation steps

### Step 1: create the generation package

```plaintext
mkdir -p episodic/generation
touch episodic/generation/__init__.py
```

### Step 2: create the show-notes module

Create `episodic/generation/show_notes.py` with:

- Imports: `dataclasses`, `json`, `re`, `typing`, `tei_rapporteur`, and
  `episodic.llm` (for `LLMPort`, `LLMRequest`, `LLMResponse`, `LLMUsage`,
  `LLMTokenBudget`, `LLMProviderOperation`).
- DTO definitions: `ShowNotesEntry`, `ShowNotesResult`,
  `ShowNotesGeneratorConfig`, `ShowNotesResponseFormatError`.
- Parsing helpers: `_decode_object`, `_require_non_empty_string`,
  `_require_list`, `_parse_entry`, `_result_from_response`.
- Service class: `ShowNotesGenerator` with `build_prompt(...)` and
  `generate(...)`.
- TEI helper: `enrich_tei_with_show_notes(...)`, which parses via
  `tei_rapporteur.parse_xml(...)`, updates the body payload via
  `tei_rapporteur.to_dict(...)` / `tei_rapporteur.from_dict(...)`, and
  serializes via `tei_rapporteur.emit_xml(...)`.

### Step 3: create the package exports

Update `episodic/generation/__init__.py` to export: `ShowNotesEntry`,
`ShowNotesResult`, `ShowNotesGenerator`, `ShowNotesGeneratorConfig`,
`ShowNotesResponseFormatError`, `enrich_tei_with_show_notes`.

### Step 4: write unit tests

Create `tests/test_show_notes.py` covering:

- DTO construction and field validation.
- JSON parsing: valid, malformed, edge cases.
- Prompt construction: TEI XML inclusion, template structure inclusion.
- Generator service: mock LLMPort, success and failure paths.
- TEI enrichment: valid output, empty results, XML-unsafe characters,
  round-trip validation.

### Step 5: write BDD feature and steps

Create `tests/features/show_notes.feature` and
`tests/steps/test_show_notes_steps.py` following the Pedante pattern.

### Step 6: write ADR

Create `docs/adr/adr-003-show-notes-tei-representation.md`.

### Step 7: update documentation

Update `docs/episodic-podcast-generation-system-design.md`,
`docs/users-guide.md`, and `docs/developers-guide.md`.

### Step 8: update roadmap

Mark `2.3.1` as done in `docs/roadmap.md`.

### Step 9: run validation gates

Run the full Stage H gate sequence.

## Validation and acceptance

Quality criteria (what "done" means):

- `ShowNotesGenerator.generate(...)` accepts a TEI XML string and optional
  template structure, calls `LLMPort.generate(...)`, and returns a typed
  `ShowNotesResult` with validated entries.
- `enrich_tei_with_show_notes(...)` inserts a `<div type="notes">` element
  into a TEI document body and returns valid TEI XML.
- Unit tests cover DTO validation, JSON parsing, prompt construction, service
  orchestration, and TEI enrichment.
- One BDD scenario proves end-to-end show-notes generation via Vidai Mock.
- An ADR documents the TEI representation decision.
- Design document, user's guide, and developer's guide are updated.
- Roadmap item 2.3.1 is marked done.
- All validation gates pass: `make check-fmt`, `make typecheck`, `make lint`,
  `make test`, `make markdownlint`, `make nixie`.

Quality method (how to check):

Run the Stage H gate sequence. All commands must exit zero.

## Idempotence and recovery

All steps are additive and re-runnable. The new `episodic/generation/` package
does not modify existing code. If a stage fails:

1. Fix the immediate failure.
2. Rerun the targeted tests for that stage.
3. Rerun the full Stage H gate sequence before closing the work.

If TEI enrichment via `tei_rapporteur` proves infeasible, the fallback is to
use `xml.etree.ElementTree` for XML manipulation and validate well-formedness
with `ET.fromstring(...)`. Document the gap in the ADR and in the decision log.

## Artefacts and notes

Expected validation logs:

- `/tmp/show-notes-make-fmt.log`
- `/tmp/show-notes-make-check-fmt.log`
- `/tmp/show-notes-make-typecheck.log`
- `/tmp/show-notes-make-lint.log`
- `/tmp/show-notes-make-test.log`
- `/tmp/show-notes-make-markdownlint.log`
- `/tmp/show-notes-make-nixie.log`

Expected long-lived project artefacts:

- `episodic/generation/__init__.py`
- `episodic/generation/show_notes.py`
- `tests/test_show_notes.py`
- `tests/features/show_notes.feature`
- `tests/steps/test_show_notes_steps.py`
- `docs/adr/adr-003-show-notes-tei-representation.md`
- updated `docs/episodic-podcast-generation-system-design.md`
- updated `docs/users-guide.md`
- updated `docs/developers-guide.md`
- updated `docs/roadmap.md`

Expected test output after completion:

```plaintext
make test
...
N passed, 2 skipped
```

Where N is the current passing count plus the new show-notes tests.

## Interfaces and dependencies

### New types in `episodic/generation/show_notes.py`

```python
import dataclasses as dc
import typing as typ

from episodic.llm.ports import (
    LLMPort,
    LLMProviderOperation,
    LLMRequest,
    LLMResponse,
    LLMTokenBudget,
    LLMUsage,
)

type JsonMapping = dict[str, object]


@dc.dataclass(frozen=True, slots=True)
class ShowNotesEntry:
    topic: str
    summary: str
    timestamp: str | None = None
    tei_locator: str | None = None


@dc.dataclass(frozen=True, slots=True)
class ShowNotesResult:
    entries: tuple[ShowNotesEntry, ...]
    usage: LLMUsage
    model: str = ""
    provider_response_id: str = ""
    finish_reason: str | None = None


@dc.dataclass(frozen=True, slots=True)
class ShowNotesGeneratorConfig:
    model: str
    provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )
    token_budget: LLMTokenBudget | None = None
    system_prompt: str = _DEFAULT_SYSTEM_PROMPT


class ShowNotesResponseFormatError(ValueError):
    """Raised when the LLM response cannot be parsed."""


@dc.dataclass(slots=True)
class ShowNotesGenerator:
    llm: LLMPort
    config: ShowNotesGeneratorConfig

    @staticmethod
    def build_prompt(
        script_tei_xml: str,
        *,
        template_structure: JsonMapping | None = None,
    ) -> str: ...

    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: JsonMapping | None = None,
    ) -> ShowNotesResult: ...


def enrich_tei_with_show_notes(
    tei_xml: str,
    result: ShowNotesResult,
) -> str: ...
```

### Runtime dependencies

No new runtime dependencies are required. The implementation uses:

- `dataclasses` (stdlib)
- `json` (stdlib)
- `xml.etree.ElementTree` (stdlib)
- `episodic.llm.ports` (existing)
- `tei_rapporteur` (existing, for validation)

### Test dependencies

- `pytest` (existing)
- `pytest-bdd` (existing)
- `pytest-asyncio` (existing)
- Vidai Mock binary at `/root/.local/bin/vidaimock` or on `PATH` (existing)
