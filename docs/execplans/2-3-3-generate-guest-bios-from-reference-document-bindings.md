# Generate guest bios from reference document bindings

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: IN PROGRESS

## Purpose and big picture

Roadmap item 2.3.3 asks the content enrichment system to retrieve guest profile
reference documents and format biographical summaries within the canonical Text
Encoding Initiative (TEI) body. After this change is approved and implemented,
an episode generation workflow can resolve the pinned `guest_profile`
reference-document revisions for a series, template, and episode context,
generate concise guest biographies through the existing Large Language Model
(LLM) port, and insert those biographies into the episode TEI body as
structured metadata.

The observable outcome is a canonical TEI document that contains a
`<div type="guest-bios">` block. That block lists one biography per resolved
guest profile, preserves a reference back to the consumed pinned revision, and
round-trips through `tei_rapporteur` validation. Behavioural tests prove the
service can use Vidai Mock as the inference provider, retrieve guest profiles
through existing binding resolution, and produce deterministic TEI body
enrichment.

This is a pre-implementation plan. Do not implement the feature until this
ExecPlan has been explicitly approved.

## Constraints

- Preserve hexagonal architecture boundaries from the
  `hexagonal-architecture` skill. Domain and generation policy code must not
  import Falcon, SQLAlchemy, Celery, LangGraph, HTTP clients, or storage
  adapter types. Ports stay inward-facing; adapters implement ports.
- Use the `rust-router` family only if implementation work later touches Rust.
  The expected implementation is Python, so no Rust-specific skill is required
  for the planning change.
- Use `leta` for code navigation and symbol-oriented exploration during
  implementation.
- Keep TEI P5 as the canonical content spine. JSON may be used as a prompt or
  LLM response projection, but not as a second canonical biography format.
- Use existing reference-document resolution before adding new repository
  contracts. Start from `resolve_bindings(...)` in
  `episodic/canonical/reference_documents/resolution.py` and filter resolved
  documents whose `ReferenceDocument.kind` is `guest_profile`.
- Use `LLMPort.generate(LLMRequest) -> LLMResponse` for inference. Do not add a
  second inference boundary or bypass `episodic/llm/ports.py`.
- Use Vidai Mock for behavioural inference testing. Behavioural tests must not
  call a live external LLM provider.
- Treat guest biographies as content enrichment, not quality assurance. The
  primary home should be `episodic/generation/`, following
  `episodic/generation/show_notes.py`.
- Preserve the existing show-notes contract in
  `episodic/generation/show_notes.py` and
  `docs/adr/adr-004-show-notes-tei-representation.md`.
- Follow test-first development. Add failing unit and behavioural coverage
  before implementing each material behaviour.
- Update user-facing and internal documentation when behaviour, interfaces, or
  conventions change. At minimum, inspect and update
  `docs/episodic-podcast-generation-system-design.md`, `docs/users-guide.md`,
  and `docs/developers-guide.md`.
- Record durable TEI representation decisions in an Architecture Decision
  Record (ADR), or update the relevant existing ADR if the decision is a direct
  extension of the show-notes representation.
- Run validation sequentially, not in parallel. Required gates are
  `make check-fmt`, `make typecheck`, `make lint`, and `make test`. Because the
  implementation will edit Markdown, also run `make markdownlint` and
  `make nixie`.
- Use `coderabbit review --agent` after each major implementation milestone
  and clear all concerns before moving to the next milestone.
- Commit after each approved, gated change. Use file-based commit messages as
  required by the `commit-message` skill.
- Do not mark roadmap item 2.3.3 done until the implementation, tests,
  documentation, validation gates, and review concerns are complete.

## Tolerances

- Scope tolerance: stop and escalate if the approved implementation needs more
  than 18 files or 1200 net new lines before the first working vertical slice.
- Interface tolerance: stop and escalate before changing public signatures for
  `LLMPort`, `LLMRequest`, `LLMResponse`, `ReferenceDocument`,
  `ReferenceDocumentRevision`, `ReferenceBinding`, or `ResolvedBinding`.
- Persistence tolerance: stop and escalate if guest-bio generation requires a
  schema migration. The expected path consumes existing reference-document and
  binding tables.
- TEI tolerance: stop and escalate if `tei_rapporteur` cannot round-trip the
  chosen `<div type="guest-bios">` representation without a dependency update.
- Inference tolerance: stop and escalate if deterministic Vidai Mock coverage
  cannot exercise the generation path without real network LLM access.
- Architecture tolerance: stop and escalate if domain or generation code must
  import adapters to resolve guest profiles.
- Ambiguity tolerance: stop and escalate if product expectations require
  biographies to live in the TEI header personography instead of the TEI body.
  This roadmap item explicitly asks for TEI body formatting, so header-only
  personography is outwith this plan unless approved as additional scope.
- Review tolerance: stop and escalate if CodeRabbit raises a concern that
  contradicts this plan or requires broad redesign.

## Risks

- Risk: TEI offers a rich personography model, including `<person>`,
  `<persName>`, `<occupation>`, `<affiliation>`, and `<note>`, while the
  roadmap asks for TEI body enrichment. Severity: medium. Likelihood: medium.
  Mitigation: use a body `<div type="guest-bios">` for episode-facing
  biographies, and document the choice against TEI prior art rather than
  inventing an opaque custom sidecar.
- Risk: reference documents may contain unstructured prose, structured JSON, or
  mixed metadata depending on how editors authored revisions. Severity: medium.
  Likelihood: high. Mitigation: create a small parser/projection layer that
  extracts display name, role, short facts, and source text defensively, then
  asks the LLM for a constrained biography from that projection.
- Risk: multiple guest profile bindings may resolve for one episode, or none
  may resolve. Severity: medium. Likelihood: high. Mitigation: define stable
  ordering, handle the empty set as a no-op enrichment, and test both cases.
- Risk: biography generation may overstate facts from reference documents.
  Severity: high. Likelihood: medium. Mitigation: prompt for source-grounded
  summaries only, carry reference revision identifiers into the result, and add
  parser tests that reject unsupported free-form response shapes.
- Risk: the existing generation orchestration currently has a
  `GENERATE_SHOW_NOTES` action but not a guest-bio action. Severity: medium.
  Likelihood: high. Mitigation: land the pure generator and TEI enrichment
  first, then extend the orchestration DTO, planner, executor, and LangGraph
  wiring in a separate milestone within the same approved feature.
- Risk: end-to-end scope may expand into CLI or worker behaviour even though no
  feature-specific CLI exists. Severity: medium. Likelihood: medium.
  Mitigation: treat API and orchestration contracts as the externally
  observable system boundaries for this task unless a CLI is added by separate
  approval.

## Progress

- [x] 2026-05-10: Loaded `execplans`, `hexagonal-architecture`,
  `firecrawl-mcp`, `leta`, `vidai-mock`, `pr-creation`, `en-gb-oxendict-style`,
  and `commit-message` skill guidance.
- [x] 2026-05-10: Used a Wyvern agent team for read-only planning research
  across design anchors, implementation shape, and test/documentation
  obligations.
- [x] 2026-05-10: Used Firecrawl to inspect official TEI prior art for
  representing people and biographical details.
- [x] 2026-05-10: Renamed the local branch to
  `2-3-3-generate-guest-bios-from-reference-document-bindings`.
- [x] 2026-05-10: Drafted this pre-implementation ExecPlan.
- [x] 2026-05-14: Received explicit approval to proceed with implementation
  of the planned functionality.
- [x] 2026-05-14: Re-read this ExecPlan, branch state, AGENTS.md, and the
  `execplans`, `leta`, and `hexagonal-architecture` skill guidance before
  starting implementation.
- [x] 2026-05-14: Added `tests/test_guest_bios.py` fail-first coverage for
  strict response parsing, canonical `<div type="guest-bios">` enrichment,
  replacement of existing guest-bio blocks, and empty-result no-op behaviour.
- [x] 2026-05-14: Implemented the initial
  `episodic/generation/guest_bios.py` generator DTOs, strict response parser,
  prompt builder, and TEI enrichment helper. Focused test command
  `uv run pytest tests/test_guest_bios.py -q` now passes with 5 tests.
- [x] 2026-05-14: Added
  `docs/adr/adr-007-guest-bios-tei-representation.md` to record the
  `<div type="guest-bios"><list><item corresp="...">` representation.
- [x] 2026-05-14: Ran `coderabbit review --agent` for milestone 1. It raised
  a missing expected-revision parser test and an ADR footnote wrapping concern;
  both were accepted as valid and fixed before committing.
- [x] 2026-05-14: Re-ran `coderabbit review --agent` after fixes. It raised
  two narrow `noqa: TRY004` justification concerns in the TEI payload helpers
  and one remaining ADR wrapping concern; all were fixed. A final review pass
  completed with zero findings.
- [x] Implement milestone 1: representation decision and
  fail-first unit tests.
- [x] 2026-05-14: Added `project_guest_bio_sources(...)` to filter resolved
  bindings to `ReferenceDocumentKind.GUEST_PROFILE` and project pinned
  revisions into `GuestBioSource` records. Added unit coverage for projection,
  prompt construction, and async `LLMPort` invocation.
- [x] 2026-05-14: Added `tests/test_guest_bios_properties.py` with Hypothesis
  coverage for parseable guest-bio TEI, entry ordering, duplicate replacement,
  empty-result no-op behaviour, and blank biography rejection. Hypothesis found
  brittle raw XML assertions around entity escaping; the tests now inspect
  parsed `tei_rapporteur` payloads.
- [x] 2026-05-14: Ran focused validation for milestone 2/3 with `set -o
  pipefail`, including
  `uv run pytest tests/test_guest_bios.py tests/test_guest_bios_properties.py -q`,
  `make check-fmt`, `make typecheck`, `make lint`, `make markdownlint`, and
  `make nixie`. Ran `coderabbit review --agent`; it completed with zero
  findings.
- [x] Implement milestone 2: guest profile projection and
  generator service.
- [x] Implement milestone 3: TEI body enrichment.
- [ ] Implement milestone 4: binding retrieval and
  orchestration integration.
- [ ] Implement milestone 5: behavioural, property, and
  end-to-end validation.
- [ ] Implement milestone 6: documentation, roadmap completion,
  full validation, CodeRabbit review, commit, push, and PR update.

## Surprises & discoveries

### TEI personography is richer than the roadmap target

Firecrawl research against the official TEI P5 guidelines found that `<person>`
can describe identifiable people and can contain person-related children such
as `<persName>`, `<occupation>`, `<affiliation>`, and `<note>`. That model is
suitable for a formal personography or participant description, but the roadmap
item asks for biographical summaries "within TEI body".

The implementation should therefore define an episode-body enrichment block
instead of moving the feature entirely into the TEI header. The ADR should
acknowledge the TEI personography option and explain why the body
representation is the accepted shape for episode-facing generated bios.

### Existing show-notes enrichment is the closest local pattern

`episodic/generation/show_notes.py` already implements the pattern this task
needs: typed result DTOs, strict JSON response parsing, `LLMPort` use, and TEI
body mutation through `tei_rapporteur`. The guest-bio implementation should
follow that shape rather than creating a new generation framework.

### Binding resolution already exists

`resolve_bindings(...)` in
`episodic/canonical/reference_documents/resolution.py` already resolves series
and template bindings with episode-aware precedence. The guest-bio feature
should consume that service and filter the resolved set to
`ReferenceDocumentKind.GUEST_PROFILE`.

### `tei-rapporteur` now supports the target body shape

The branch already pins `tei-rapporteur` to
`89fc86ef3952ecfde0bb7f653cde217e2651b895`. A smoke probe before implementation
confirmed that a `div type="guest-bios"` containing a list item with `@corresp`
can be emitted, parsed, and emitted again through `tei_rapporteur`. The
implementation can therefore proceed without changing the canonical TEI
parser/emitter dependency.

## Decision log

- Decision: represent guest biographies in the TEI body as a
  `<div type="guest-bios">` containing a `<list>` of `<item>` entries unless
  the representation prototype fails. Rationale: this follows ADR 004's
  accepted `<div type="..."><list><item>...</item></list></div>` enrichment
  convention and satisfies the roadmap requirement to format biographies inside
  the TEI body. Date/Author: 2026-05-10 / ExecPlan draft.
- Decision: carry the source reference-document revision through generated
  biography results and TEI output using TEI linking attributes already
  supported by the local body model, preferring `@corresp` where possible.
  Rationale: provenance matters for generated bios, and the feature must be
  reproducible from pinned reference document revisions. Date/Author:
  2026-05-10 / ExecPlan draft.
- Decision: keep guest-bio generation in `episodic/generation/` and add
  orchestration integration only after the pure generator and TEI enrichment
  work. Rationale: this maintains a small vertical slice and keeps policy logic
  testable without infrastructure. Date/Author: 2026-05-10 / ExecPlan draft.
- Decision: do not mark the roadmap item done in this planning branch.
  Rationale: the user explicitly requires plan approval before implementation,
  so roadmap completion belongs to the future implementation branch state.
  Date/Author: 2026-05-10 / ExecPlan draft.
- Decision: implementation can use `@corresp` on each guest-bio `<item>` to
  link to the pinned reference-document revision. Rationale: the updated
  `tei-rapporteur` dependency exposes `Item.corresp` as a pointer list and the
  smoke probe confirmed round-trip support for external revision identifiers.
  Date/Author: 2026-05-14 / Implementation.

## Implementation plan after approval

### Milestone 1: decide and test the TEI representation

Read `docs/adr/adr-004-show-notes-tei-representation.md`,
`docs/episodic-podcast-generation-system-design.md`, and the relevant
`tei_rapporteur` body payload expectations. Add a new ADR, expected to be
`docs/adr/adr-007-guest-bios-tei-representation.md`, unless the repository has
renumbered ADRs by then.

Write fail-first unit tests in a new `tests/test_guest_bios.py` covering the
target body shape:

```xml
<div type="guest-bios">
  <list>
    <item corresp="#ref-revision-id">
      <label>Guest name</label>
      Guest biography text.
    </item>
  </list>
</div>
```

The tests must verify that the enriched TEI parses through `tei_rapporteur`,
validates, replaces an existing `guest-bios` block rather than duplicating it,
and returns the original TEI unchanged when there are no biographies.

Run the focused unit test and confirm it fails for the expected missing
implementation:

```bash
uv run pytest tests/test_guest_bios.py -q
```

### Milestone 2: implement the guest-bio generator service

Create `episodic/generation/guest_bios.py` following the structure of
`episodic/generation/show_notes.py`. Define frozen dataclasses with
`slots=True`, expected to include:

- `GuestBioSource`, carrying guest display name, optional role, pinned
  reference document identifier, pinned revision identifier, and source content.
- `GuestBioEntry`, carrying display name, biography text, source revision
  identifier, optional role, optional TEI locator, and normalized LLM metadata
  where needed.
- `GuestBiosResult`, carrying a tuple of entries plus `LLMUsage`, model,
  provider response identifier, and finish reason.
- `GuestBiosGeneratorConfig`, mirroring `ShowNotesGeneratorConfig`.
- `GuestBiosResponseFormatError`, raised for malformed LLM output.

Implement strict JSON parsing. The LLM response should be constrained to a
single object with a `guests` list, where each item has at least
`display_name`, `bio`, and `reference_document_revision_id`. Reject missing,
blank, duplicate, or unknown revision identifiers, so the generator cannot
silently invent guests.

Use `LLMPort` only. Build prompts from a projection of TEI script context,
episode template structure, and resolved guest profile content. Keep the prompt
source-grounded: the model may summarize supplied profile facts, but must not
add unsupported claims.

Run focused tests:

```bash
uv run pytest tests/test_guest_bios.py -q
```

### Milestone 3: enrich the TEI body

In `episodic/generation/guest_bios.py`, implement
`enrich_tei_with_guest_bios(tei_xml, result) -> str`. Follow
`enrich_tei_with_show_notes(...)` for parser and emitter use. The helper should
remove any existing canonical guest-bios block, append a fresh block when the
result contains entries, preserve unrelated body blocks, and let malformed TEI
raise a clear `ValueError`.

If `tei_rapporteur` does not support an attribute needed for source revision
linkage, stop under the TEI tolerance and document the options before changing
the dependency.

Add property tests in `tests/test_guest_bios_properties.py` for invariants over
entry order, non-empty biography text, duplicate replacement, empty-result
no-op behaviour, and round-trip parseability across generated guest names and
biographies.

Run focused tests:

```bash
uv run pytest tests/test_guest_bios.py tests/test_guest_bios_properties.py -q
```

### Milestone 4: retrieve guest profiles from reference bindings

Add an application service in the generation layer, or a small orchestration
helper if that better matches the existing package shape, that accepts a
`CanonicalUnitOfWork`, `series_profile_id`, `episode_id`, optional
`template_id`, and TEI script XML. It should call `resolve_bindings(...)`,
filter to `ReferenceDocumentKind.GUEST_PROFILE`, project each resolved binding
into `GuestBioSource`, then call `GuestBiosGenerator`.

Keep the binding resolution contract in
`episodic/canonical/reference_documents/resolution.py` unchanged unless tests
prove it cannot support the guest-bio use case. If changes are required, add or
update tests in:

- `tests/test_binding_resolution.py`
- `tests/test_binding_resolution_validation.py`
- `tests/test_binding_resolution_api.py`
- `tests/features/binding_resolution.feature`
- `tests/steps/test_binding_resolution_steps.py`

Run focused tests:

```bash
uv run pytest tests/test_guest_bios.py tests/test_binding_resolution.py -q
```

### Milestone 5: wire orchestration and behavioural coverage

Extend the structured generation orchestration so guest-bio enrichment is a
first-class planned action alongside show notes. Inspect and update:

- `episodic/orchestration/_types.py`
- `episodic/orchestration/_dto.py`
- `episodic/orchestration/_protocols.py`
- `episodic/orchestration/generation.py`
- `episodic/orchestration/langgraph.py`
- a new executor modelled on
  `episodic/orchestration/_show_notes_executor.py`

Add `pytest-bdd` behavioural coverage in:

- `tests/features/guest_bios.feature`
- `tests/steps/test_guest_bios_steps.py`

The core scenario should start Vidai Mock, create or project guest profile
bindings, run guest-bio generation, and assert that the prompt includes the
pinned guest profile content and that the enriched TEI contains
`<div type="guest-bios">`.

Add orchestration tests near:

- `tests/test_generation_orchestration_langgraph.py`
- `tests/test_generation_orchestration_snapshots.py`
- `tests/test_orchestration_orchestrator.py`
- `tests/features/generation_orchestration.feature`
- `tests/steps/test_generation_orchestration_steps.py`

End-to-end tests are required if the change alters an externally observable
API, worker, or process boundary. If implementation only adds an in-process
generation action and existing API contracts remain unchanged, record that no
new process-level end-to-end test is required. If an endpoint or worker task is
added, include endpoint or worker-system tests following
`tests/test_http_service_scaffold.py` and
`tests/steps/test_http_service_scaffold_steps.py`.

Run focused behavioural tests:

```bash
uv run pytest tests/steps/test_guest_bios_steps.py -q
uv run pytest tests/steps/test_generation_orchestration_steps.py -q
```

Run CodeRabbit review for the milestone and resolve every concern before
continuing:

```bash
coderabbit review --agent
```

### Milestone 6: update documentation and roadmap

Update `docs/episodic-podcast-generation-system-design.md` under the Content
Generation Orchestrator and canonical content schema areas to describe
guest-bio enrichment, reference-document retrieval, and the accepted TEI body
shape.

Update `docs/users-guide.md` to explain what users can expect from generated
guest biographies and how guest profile reference documents affect output.

Update `docs/developers-guide.md` with internal conventions for guest-bio
generation, Vidai Mock behavioural tests, and TEI body enrichment.

Update any component architecture documentation that receives a new internal
interface. If implementation changes binding-resolution semantics, update
`docs/reference-binding-resolution.md` and
`docs/adr/adr-001-reference-binding-resolution-algorithm.md`.

Mark roadmap item 2.3.3 in `docs/roadmap.md` as done only after the feature is
implemented, validated, reviewed, and committed.

Run documentation gates:

```bash
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-2-3-3-generate-guest-bios-from-reference-document-bindings.out
make nixie 2>&1 | tee /tmp/nixie-episodic-2-3-3-generate-guest-bios-from-reference-document-bindings.out
```

### Milestone 7: run full validation, commit, push, and update the PR

Run all required gates sequentially:

```bash
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-2-3-3-generate-guest-bios-from-reference-document-bindings.out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-2-3-3-generate-guest-bios-from-reference-document-bindings.out
make lint 2>&1 | tee /tmp/lint-episodic-2-3-3-generate-guest-bios-from-reference-document-bindings.out
make test 2>&1 | tee /tmp/test-episodic-2-3-3-generate-guest-bios-from-reference-document-bindings.out
```

Review the log tails after each command if the environment truncates output. Do
not commit failing gates.

Commit with a file-based message. Push to
`origin/2-3-3-generate-guest-bios-from-reference-document-bindings`. Update the
draft pull request description so it links this ExecPlan and distinguishes
between the approved plan and the implementation work that landed.

## Validation plan

The planning branch itself must pass documentation and requested repository
gates before it is committed:

```bash
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-2-3-3-generate-guest-bios-from-reference-document-bindings-plan.out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-2-3-3-generate-guest-bios-from-reference-document-bindings-plan.out
make lint 2>&1 | tee /tmp/lint-episodic-2-3-3-generate-guest-bios-from-reference-document-bindings-plan.out
make test 2>&1 | tee /tmp/test-episodic-2-3-3-generate-guest-bios-from-reference-document-bindings-plan.out
make markdownlint 2>&1 \
  | tee /tmp/markdownlint-episodic-2-3-3-generate-guest-bios-from-reference-document-bindings-plan.out
make nixie 2>&1 | tee /tmp/nixie-episodic-2-3-3-generate-guest-bios-from-reference-document-bindings-plan.out
```

The future implementation must additionally include focused fail-first tests:

- Unit tests for guest-bio DTO validation, strict response parsing, TEI
  enrichment, and binding-to-source projection.
- Behavioural tests with `pytest-bdd` and Vidai Mock proving inference-backed
  biography generation.
- Property tests with Hypothesis for representation invariants.
- End-to-end tests only where the implementation changes an externally
  observable API, worker, persistence, command-line, or network boundary.

## Outcomes & retrospective

This section is intentionally empty while the plan is in draft. During
implementation, record what changed, what was validated, any deviations from
the plan, and lessons that should influence later roadmap items 2.3.4 and
content-generation orchestration work.
