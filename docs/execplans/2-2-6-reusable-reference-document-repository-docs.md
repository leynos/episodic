# Plan documentation updates for a reusable reference-document repository

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`, and
`Outcomes & Retrospective` must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

Status: COMPLETE

## Purpose and big picture

After this documentation-only change, the system design and roadmap will
describe two distinct persistence concerns clearly:

- ingestion-bound source documents used by a single ingestion job, and
- reusable reference documents managed as a standalone library.

Success is observable when readers can answer three questions without reading
code: what `SourceDocumentRepository` currently does, what reusable
reference-document repository capability is missing, and how the roadmap now
sequences this new capability.

## Constraints

- This plan covers documentation only. No Python source files, migrations, or
  runtime behaviour may be changed.
- The design document must describe current behaviour accurately and label the
  reusable repository as planned capability, not implemented capability.
- The roadmap must preserve phase structure and numbering conventions while
  adding measurable tasks.
- Documentation must follow `docs/documentation-style-guide.md`, including
  sentence case headings, British English, and 80-column wrapping.
- Validation must use Makefile targets and pass Markdown gates:
  `make fmt`, `make markdownlint`, and `make nixie`.

## Tolerances (exception triggers)

- Scope: if the documentation update requires editing more than 3 files, stop
  and escalate.
- Interface claims: if wording would imply new APIs are implemented in code,
  stop and escalate.
- Roadmap reshaping: if accommodating this work requires a new phase instead of
  updates inside Phase 2, stop and escalate.
- Validation: if any Markdown gate still fails after 2 fix attempts, stop and
  escalate with failure output.

## Risks

- Risk: readers may confuse ingestion source records with reusable references if
  both are described as "source documents". Severity: high. Likelihood: medium.
  Mitigation: add explicit terminology boundaries and a short comparison in the
  design document.

- Risk: roadmap granularity may remain too vague for execution.
  Severity: medium. Likelihood: medium. Mitigation: define roadmap tasks with
  concrete outcomes and exit criteria, rather than broad intentions.

- Risk: schema diagrams may drift from textual descriptions when new repository
  concepts are documented. Severity: medium. Likelihood: low. Mitigation:
  update both descriptive sections and relevant Mermaid diagrams in the same
  edit set.

## Progress

- [x] (2026-02-17 16:00Z) Draft ExecPlan created with repository sketch and
  documentation update plan.
- [x] (2026-02-17 16:09Z) Stage A: Confirmed design-document insertion points
  and terminology boundaries (`SourceDocument` vs `ReferenceDocument`).
- [x] (2026-02-17 16:10Z) Stage B: Updated
  `docs/episodic-podcast-generation-system-design.md`.
- [x] (2026-02-17 16:11Z) Stage C: Updated `docs/roadmap.md` with explicit
  reusable-reference work items and revised exit criteria.
- [x] (2026-02-17 16:13Z) Stage D: Ran formatting and Markdown validation
  gates with captured logs.
- [x] (2026-02-18 11:21Z) Stage E: Extended the model and roadmap for
  series-aligned host and guest profiles, including `effective_from_episode_id`
  revision semantics.
- [x] (2026-02-18 11:22Z) Stage F: Replaced the reusable-reference ER diagram
  with a detailed field-level model covering host/guest profiles and revision
  applicability anchors.

## Surprises & discoveries

- Observation: the repository exposes no MCP resources in this session, so
  project memory retrieval via `qdrant-find` is unavailable here. Evidence:
  `list_mcp_resources` and `list_mcp_resource_templates` both returned empty
  lists. Impact: the plan relies on local repository sources only.

- Observation: `EpisodeTemplateRepository` is not present in current source,
  even though templates appear in design and roadmap text. Evidence:
  repository-wide search for `EpisodeTemplateRepository` returned no matches.
  Impact: design updates must distinguish implemented repositories from planned
  repositories.

## Decision log

- Decision: keep this work documentation-only and avoid proposing immediate code
  interfaces in production modules. Rationale: user request scopes the task to
  planning and document updates. Date/Author: 2026-02-17 / Codex.

- Decision: document a reusable reference-document repository as a capability
  separate from `SourceDocumentRepository`. Rationale: current repository
  contract (`add`, `list_for_job`) and domain model (`ingestion_job_id`) are
  ingestion-scoped, so reuse requirements are not met by extension of existing
  wording alone. Date/Author: 2026-02-17 / Codex.

- Decision: align roadmap changes within Phase 2 instead of introducing a new
  phase. Rationale: reusable reference materials are foundational to canonical
  content and template/profile workflows already scoped to Phase 2.
  Date/Author: 2026-02-17 / Codex.

- Decision: model host and guest profiles as series-aligned reference
  documents, with optional episode-anchored revision applicability. Rationale:
  hosts may not appear in every episode and guests may recur across multiple
  episodes, so episode ownership is the wrong primary scope. A binding-level
  `effective_from_episode_id` allows deterministic "from this episode onward"
  behaviour without breaking series-level reuse. Date/Author: 2026-02-18 /
  Codex.

- Decision: document the reusable-reference schema using a full field-level ER
  diagram instead of relationship-only edges. Rationale: the requested update
  requires explicit columns (including `effective_from_episode_id` and snapshot
  linkage fields) so implementers can interpret binding and provenance
  semantics unambiguously. Date/Author: 2026-02-18 / Codex.

## Outcomes & retrospective

The documentation-only implementation completed successfully.

Changes delivered:

- Updated `docs/episodic-podcast-generation-system-design.md` to:
  - distinguish current ingestion-bound `SourceDocumentRepository` behaviour
    from planned reusable reference-document capabilities,
  - add reusable reference data-model entities
    (`reference_documents`, `reference_document_revisions`,
    `reference_document_bindings`),
  - introduce a dedicated planned-model Mermaid diagram, and
  - align component and roadmap-alignment narrative with reusable reference
    storage.
- Updated `docs/roadmap.md` to:
  - split reusable reference-document work into explicit Phase 2 activities
    (2.2.6 through 2.2.8), and
  - expand Phase 2 exit criteria to require API retrieval of reusable
    references and ingestion snapshot behaviour.
- Applied a follow-up documentation revision to:
  - classify host and guest profiles as series-aligned reference documents,
  - define `effective_from_episode_id` binding semantics for revisions that
    apply from a given episode onwards, and
  - align roadmap activities and exit criteria with those semantics.
- Added a detailed reusable-reference ER diagram in
  `docs/episodic-podcast-generation-system-design.md` with explicit entities,
  fields, and relationships for:
  - series, episodes, templates, and ingestion jobs,
  - host/guest profile representation as `REFERENCE_DOCUMENTS.kind`, and
  - revision snapshot flow into ingestion-bound `SOURCE_DOCUMENTS`.

Validation evidence:

- `make fmt` passed (`/tmp/execplan-refdocs-diagram-make-fmt.log`).
- `make markdownlint` passed
  (`/tmp/execplan-refdocs-diagram-markdownlint.log`).
- `make nixie` passed (`/tmp/execplan-refdocs-diagram-nixie.log`), with Mermaid
  diagrams validated.

## Context and orientation

Current implemented persistence in `episodic/canonical/ports.py`,
`episodic/canonical/domain.py`, and
`episodic/canonical/storage/repositories.py` defines `SourceDocumentRepository`
with only `add(document)` and `list_for_job(job_id)`, and `SourceDocument`
entities keyed by `ingestion_job_id`. This model is tightly coupled to
ingestion runs.

Current design text in `docs/episodic-podcast-generation-system-design.md`
describes `source_documents` as ingestion artefacts and lists six implemented
repository protocols. It also references series profiles and episode templates,
but does not define an independent reusable reference-document repository or
episode-template repository contract.

Current roadmap text in `docs/roadmap.md` includes:

- 2.2.4 ingestion normalisation and conflict resolution, and
- 2.2.6 reusable reference-document models and repository contracts.

It does not explicitly include a reusable reference-document repository layer
or reuse workflows across ingestion jobs.

### Reusable repository sketch (for documentation)

The design update should sketch a standalone reference library with three
concepts:

- `ReferenceDocument`: stable identity, owning scope (global or series-level),
  document kind (style guide, character profile, research brief, and similar),
  lifecycle state, and metadata.
- `ReferenceDocumentRevision`: immutable versioned content for each document,
  including content hash, author, change note, and created timestamp.
- `ReferenceBinding`: explicit linkage that applies one or more document
  revisions to a target context (series profile, template, or ingestion job
  seed set), preserving reproducibility.

This sketch keeps ingestion provenance intact: ingestion jobs may snapshot the
selected reference revisions into `source_documents` for TEI provenance, while
the reusable library remains managed independently.

## Plan of work

Stage A clarifies language and insertion points before editing: review the
existing "Data model and storage", "Canonical content schema decisions",
"Repository and unit-of-work implementation", and roadmap Phase 2 sections.
Confirm final terms (`SourceDocument` versus `ReferenceDocument`) and where to
place a short comparison.

Stage B updates `docs/episodic-podcast-generation-system-design.md`: add a
subsection that explicitly states current ingestion-bound behaviour and
introduces the planned reusable repository model, including the three-concept
sketch above. Update affected table lists and Mermaid relationships so they
represent reusable references and their relationship to ingestion provenance.
Ensure repository implementation text clearly separates implemented
repositories from planned ones.

Stage C updates `docs/roadmap.md`: refine Phase 2 tasks to include reusable
reference-document capability as a first-class deliverable. Either expand item
2.2.6 or split it into atomic items that cover repository model definition, API
retrieval semantics, version history, and ingestion linkage. Update exit
criteria so completion is measurable, for example retrieving versioned
reference documents independently of ingestion jobs.

Stage D runs documentation validation: format, lint, and diagram checks; then
review diffs for clarity and consistency with design intent.

## Concrete steps

Run from repository root:

    git status --short
    rg -n "SourceDocumentRepository|source_documents|episode_templates|2\\.2\\.6|2\\.3\\.2" \
      docs/episodic-podcast-generation-system-design.md \
      docs/roadmap.md

Edit files:

- `docs/episodic-podcast-generation-system-design.md`
- `docs/roadmap.md`

Run validation with captured logs:

    set -o pipefail; make fmt 2>&1 | tee /tmp/execplan-refdocs-make-fmt.log
    set -o pipefail; make markdownlint 2>&1 | tee /tmp/execplan-refdocs-markdownlint.log
    set -o pipefail; make nixie 2>&1 | tee /tmp/execplan-refdocs-make-nixie.log

Expected success indicators:

- `make fmt` exits 0.
- `make markdownlint` exits 0 with no lint violations.
- `make nixie` exits 0 with Mermaid validation passing.

## Validation and acceptance

Acceptance is documentation behaviour, not runtime behaviour.

- A reader can identify, from the design document alone, why
  `SourceDocumentRepository` is ingestion-bound and insufficient for reusable
  references.
- A reader can find a concrete sketch of the reusable repository model
  (`ReferenceDocument`, `ReferenceDocumentRevision`, `ReferenceBinding`) and
  understand how it interoperates with ingestion provenance.
- Roadmap Phase 2 includes explicit, measurable tasks and exit criteria for
  reusable reference-document management across multiple ingestion jobs.
- Markdown quality gates pass via Makefile targets.

## Idempotence and recovery

- All documentation edits are idempotent and can be re-applied safely.
- If a Markdown gate fails, rerun only the failed command after targeted edits.
- If terminology drifts during drafting, revert only the affected hunks and
  re-apply wording aligned to the comparison rule: ingestion-bound
  `SourceDocument` versus reusable `ReferenceDocument`.

## Artifacts and notes

During implementation, capture concise evidence here:

- `git diff -- docs/episodic-podcast-generation-system-design.md docs/roadmap.md`
- Exit summaries from:
  - `/tmp/execplan-refdocs-diagram-make-fmt.log`
  - `/tmp/execplan-refdocs-diagram-markdownlint.log`
  - `/tmp/execplan-refdocs-diagram-nixie.log`

## Interfaces and dependencies

This is a documentation-only plan. No code interfaces are added in this change.
The design text should, however, define the intended repository
responsibilities for future implementation:

- Store and retrieve reusable reference documents independently of ingestion.
- Track immutable revisions with explicit version identifiers.
- Resolve applicable reference revisions for a series, template, or ingestion
  run while preserving provenance traceability.

No new dependencies are required.

## Revision note

Extended the completed plan with series-aligned host/guest profile semantics
and `effective_from_episode_id` applicability rules, then updated the design
document, roadmap, and reusable-reference ER diagram accordingly.
