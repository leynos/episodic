# Normalize the development roadmap to Phases / Steps / Tasks structure

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

No `PLANS.md` file is present in the repository root.

Status: DRAFT

## Purpose and big picture

The development roadmap (`docs/roadmap.md`) currently uses an informal
structure with "Objectives", "Key activities", and "Exit Criteria" sections
that do not conform to the Phases / Steps / Tasks hierarchy mandated by
`docs/documentation-style-guide.md`. Many tasks are also "draw the rest of the
owl" placeholders — vague, unmeasurable, and unrealistic as single work units.

After this change:

1. The roadmap uses the canonical three-level hierarchy: Phases (strategic
   milestones), Steps (epics/workstreams), and Tasks (execution units).
2. Every task is atomic, measurable, and scoped to roughly consistent effort.
3. Dependencies and design document references are explicit.
4. Phase and step preambles replace the current "Objectives" and "Exit
   Criteria" sections, providing narrative context without checkbox clutter.
5. The roadmap passes `make markdownlint` and `make nixie` validation.

Success is observable when:

- A reviewer can read any phase, understand why the work matters, see the
  constituent steps, and trace each step to enumerated tasks with clear
  acceptance criteria.
- Cross-phase dependencies are cited using dotted notation (e.g., "Requires
  2.3.1").
- Design document sections are cited where applicable (e.g., "See
  `docs/episodic-podcast-generation-system-design.md` §Component
  Responsibilities").
- The roadmap remains ambitious but every task is realistically achievable in
  isolation.

## Constraints

- The revised roadmap must pass:
  - `PATH=/root/.bun/bin:$PATH make markdownlint`
  - `make nixie`
- The roadmap must not alter the fundamental scope or sequencing of the
  existing six phases. Scope changes require escalation.
- Completed tasks (marked `[x]`) must remain marked as completed with their
  existing descriptions preserved in substance; rewording for clarity is
  permitted.
- The revision is documentation-only. No code changes are in scope.
- British English spelling per `en-GB-oxendict` must be used throughout.
- Paragraphs must wrap at 80 columns; tables and headings must not wrap.

## Tolerances (exception triggers)

- Scope: stop and escalate if the revision requires more than 600 net lines of
  change or produces a document exceeding 800 lines.
- Ambiguity: stop and escalate if a task's intent cannot be determined from the
  current roadmap text and referenced design documents.
- Design gaps: stop and escalate if a task references a design document section
  that does not exist.
- Iterations: stop and escalate after 2 failed `make markdownlint` or
  `make nixie` runs on the same section.

## Risks

- Risk: Some "Key activities" entries are compound and must be decomposed into
  multiple tasks, inflating the task count significantly. Severity: medium.
  Likelihood: high. Mitigation: Decompose only to the level required for
  measurability; avoid over-enumeration by grouping related sub-tasks as bullet
  points under a single checkbox when the sub-tasks share one acceptance
  criterion.

- Risk: Design document section references may be stale or missing for some
  tasks. Severity: medium. Likelihood: medium. Mitigation: Where a design
  document section does not exist, note "Design pending" rather than inventing
  a citation; flag these for follow-up.

- Risk: Converting "Exit Criteria" to preamble prose may lose measurable
  acceptance criteria. Severity: medium. Likelihood: low. Mitigation: Preserve
  measurable criteria as explicit task acceptance criteria or as step-level
  success indicators within the preamble.

## Progress

- [ ] (pending) Stage A: Analyse current structure and identify transformation
  patterns.
- [ ] (pending) Stage B: Draft revised Phase 1 (Platform foundations) as
  exemplar.
- [ ] (pending) Stage C: Apply transformation to Phases 2–6.
- [ ] (pending) Stage D: Add cross-references and design document citations.
- [ ] (pending) Stage E: Validate with markdownlint and nixie; iterate.
- [ ] (pending) Stage F: Final review and commit.

## Surprises & discoveries

(To be populated during implementation.)

## Decision log

(To be populated during implementation.)

## Outcomes & retrospective

(To be populated upon completion.)

## Context and orientation

### Current roadmap structure

The existing `docs/roadmap.md` has six top-level sections numbered 1–6, each
representing a phase:

1. Platform foundations
2. Canonical content foundation
3. Intelligent content generation and QA
4. Audio synthesis and delivery
5. Client and interface experience
6. Security, compliance, and operations

Within each phase, the current structure is:

- `### N.1. Objectives` — bullet-pointed goals with checkboxes.
- `### N.2. Key activities` — numbered checklist items (N.2.1, N.2.2, …).
- `### N.3. Exit criteria` — bullet-pointed completion conditions.

This structure conflates objectives (why) with exit criteria (done-when) and
places all tasks under a single "Key activities" heading without workstream
grouping.

### Target structure per documentation style guide

The style guide (`docs/documentation-style-guide.md` §Roadmap task writing
guidelines) mandates:

- **Phases** (strategic milestones): `## 1. Phase title`
  - Open with a preamble paragraph explaining why the work matters.
- **Steps** (epics/workstreams): `### 1.1. Step title`
  - Open with a preamble paragraph describing the workstream objective.
- **Tasks** (execution units): `- [ ] 1.1.1. Task description`
  - Atomic, measurable, with optional sub-task bullets.
  - Dependencies cited using dotted notation.
  - Design document sections cited where applicable.

### Relevant design documents

- `docs/episodic-podcast-generation-system-design.md` — primary system design.
- `docs/episodic-tui-api-design.md` — TUI API contract (Phases 3 and 5).
- `docs/infrastructure-design.md` — infrastructure design (Phase 1).

### Files to modify

- `docs/roadmap.md` (primary target).

### Files to read for context

- `docs/documentation-style-guide.md` (normative structure).
- `docs/roadmap.md` (current state).
- `docs/episodic-podcast-generation-system-design.md` (design citations).
- `docs/episodic-tui-api-design.md` (TUI API citations).
- `docs/infrastructure-design.md` (infrastructure citations).

## Plan of work

### Stage A: analyse current structure and identify transformation patterns

Read the current roadmap and catalogue:

1. Which "Objectives" entries are strategic (belong in phase preamble) versus
   measurable (belong as task acceptance criteria).
2. Which "Key activities" entries are already atomic tasks versus compound
   items requiring decomposition.
3. Which "Exit criteria" entries are redundant with objectives versus unique
   acceptance criteria.
4. Natural workstream groupings within each phase's activities.

Produce a working transformation map (internal notes, not committed).

### Stage B: draft revised Phase 1 as exemplar

Rewrite Phase 1 (Platform foundations) to the target structure:

1. Convert `1.1. Objectives` and `1.3. Exit criteria` into a phase preamble
   paragraph that explains why the work matters and what success looks like.
2. Identify 2–4 workstreams (Steps) within the current `1.2. Key activities`.
   Candidate groupings:
   - Infrastructure provisioning (Kubernetes, Postgres, Valkey, RabbitMQ,
     object storage).
   - GitOps and secrets management.
   - Service scaffolding (Falcon, Celery, hexagonal boundaries).
   - Observability and documentation.
3. Under each Step, enumerate atomic Tasks with:
   - Dotted numbering (1.1.1, 1.1.2, …).
   - Checkboxes.
   - Dependencies in parentheses where applicable.
   - Design document citations where applicable.
4. Validate Phase 1 in isolation with `make markdownlint` and `make nixie`.

### Stage C: apply transformation to Phases 2–6

Repeat Stage B's process for each remaining phase, preserving completed task
markers (`[x]`). Key considerations:

- **Phase 2 (Canonical content foundation):** Group by domain model, ingestion,
  reference documents, and binding resolution.
- **Phase 3 (Intelligent content generation and QA):** Group by LLM adapter,
  QA services, cost accounting, generation runs, and script projection.
- **Phase 4 (Audio synthesis and delivery):** Group by TTS adapter, mixing
  engine, preview/export, and domain model.
- **Phase 5 (Client and interface experience):** Group by REST API, WebSocket
  streaming, CLI, and web console.
- **Phase 6 (Security, compliance, and operations):** Group by RBAC, runtime
  security, disaster recovery, observability, and cost dashboards.

### Stage D: add cross-references and design document citations

For each task and step, add:

1. Explicit `Requires X.Y.Z` dependencies where sequencing is non-linear.
2. Design document section citations using the pattern:
   `See docs/<filename>.md §<Section Name>.`

Verify that every cited section exists in the referenced document.

### Stage E: validate with markdownlint and nixie; iterate

Run:

```shell
set -o pipefail; make fmt 2>&1 | tee /tmp/roadmap-norm-make-fmt.log
set -o pipefail; PATH=/root/.bun/bin:$PATH make markdownlint 2>&1 | tee /tmp/roadmap-norm-make-markdownlint.log
set -o pipefail; make nixie 2>&1 | tee /tmp/roadmap-norm-make-nixie.log
```

Fix any violations. Iterate until both pass.

### Stage F: final review and commit

1. Re-read the revised roadmap end-to-end for coherence.
2. Confirm all completed tasks remain marked `[x]`.
3. Commit with message:

   ```plaintext
   docs(roadmap): normalize to Phases / Steps / Tasks structure

   - Convert "Objectives" and "Exit Criteria" sections to phase and step
     preamble paragraphs.
   - Group tasks into workstream Steps per documentation style guide.
   - Decompose "draw the rest of the owl" tasks into atomic, measurable units.
   - Add explicit dependencies and design document citations.
   - Validate with markdownlint and nixie.
   ```

## Concrete steps

Run from repository root.

### Discovery and baseline

```shell
wc -l docs/roadmap.md
rg -n "^## |^### " docs/roadmap.md
```

### Transformation (per phase)

Edit `docs/roadmap.md` following the plan of work stages. Use the Read and Edit
tools to make incremental changes.

### Validation

```shell
set -o pipefail; make fmt 2>&1 | tee /tmp/roadmap-norm-make-fmt.log
set -o pipefail; PATH=/root/.bun/bin:$PATH make markdownlint 2>&1 | tee /tmp/roadmap-norm-make-markdownlint.log
set -o pipefail; make nixie 2>&1 | tee /tmp/roadmap-norm-make-nixie.log
```

Expected: both commands exit 0 with no errors.

## Validation and acceptance

Quality criteria:

- The revised roadmap uses `## N. Phase title` for phases.
- Each phase opens with a preamble paragraph (no checkboxes in the preamble).
- Steps use `### N.M. Step title` and open with a preamble paragraph.
- Tasks use `- [ ] N.M.K. Task description` with dotted numbering.
- Dependencies and design citations are present where applicable.
- `make markdownlint` exits 0.
- `make nixie` exits 0.

Quality method:

```shell
PATH=/root/.bun/bin:$PATH make markdownlint && make nixie
```

## Idempotence and recovery

All edits are to a single Markdown file. If a stage fails, revert to the
previous committed state and retry. No destructive operations are involved.

## Artifacts and notes

Evidence artifacts (to be captured during implementation):

- `/tmp/roadmap-norm-make-fmt.log`
- `/tmp/roadmap-norm-make-markdownlint.log`
- `/tmp/roadmap-norm-make-nixie.log`

## Interfaces and dependencies

No code interfaces are involved. The deliverable is a revised Markdown document.

Document dependencies:

- `docs/documentation-style-guide.md` — normative structure requirements.
- `docs/episodic-podcast-generation-system-design.md` — primary design
  citations.
- `docs/episodic-tui-api-design.md` — TUI API citations.
- `docs/infrastructure-design.md` — infrastructure citations.

## Appendix A: Phase-by-phase transformation notes

### Phase 1: Platform foundations

Current "Objectives" (1.1.1, 1.1.2) describe provisioning and CI/CD. These
become the phase preamble.

Current "Key activities" (1.2.1–1.2.11) span:

- Infrastructure provisioning (1.2.1, 1.2.2, 1.2.7).
- GitOps and secrets (1.2.3, 1.2.2).
- Service scaffolding (1.2.4, 1.2.5, 1.2.6, 1.2.11).
- Observability and documentation (1.2.8, 1.2.9, 1.2.10).

Proposed Steps:

- 1.1. Infrastructure provisioning
- 1.2. GitOps and secrets management
- 1.3. Service scaffolding and hexagonal boundaries
- 1.4. Observability, documentation, and access controls

Current "Exit criteria" (1.3.1–1.3.4) become acceptance criteria on specific
tasks or step preambles.

### Phase 2: Canonical content foundation

Current "Objectives" (2.1.1, 2.1.2) describe TEI domain model and auditable
provenance. These become the phase preamble.

Current "Key activities" (2.2.1–2.2.9) span:

- Schema and migration (2.2.1, 2.2.2).
- Repository and unit-of-work (2.2.3).
- Ingestion service (2.2.4, 2.2.5).
- Reference documents (2.2.6, 2.2.7).
- Series profiles and templates (2.2.8).
- Binding resolution (2.2.9).

Proposed Steps:

- 2.1. Relational schema and persistence layer
- 2.2. Multi-source ingestion service
- 2.3. Reusable reference documents
- 2.4. Series profiles, episode templates, and binding resolution

### Phase 3: Intelligent content generation and QA

Current "Objectives" (3.1.1, 3.1.2) describe LLM orchestration and compliance
automation. These become the phase preamble.

Current "Key activities" (3.2.1–3.2.17) span many areas. Some items (e.g.,
3.2.2, 3.2.3, 3.2.4, 3.2.5) are compound and require decomposition.

Proposed Steps:

- 3.1. LLM adapter and guardrails
- 3.2. QA services (Bromide, Chiltern, brand evaluation)
- 3.3. LangGraph orchestration and cost accounting
- 3.4. Generation runs and checkpoints
- 3.5. Script projection and editing

### Phase 4: Audio synthesis and delivery

Current "Objectives" (4.1.1, 4.1.2) describe production audio and delivery
workflows. These become the phase preamble.

Current "Key activities" (4.2.1–4.2.10) span:

- TTS adapter (4.2.1).
- Mixing engine (4.2.2, 4.2.3, 4.2.4).
- Preview and delivery (4.2.5, 4.2.6).
- Domain model and endpoints (4.2.7, 4.2.8, 4.2.9, 4.2.10).

Proposed Steps:

- 4.1. Text-to-speech adapter
- 4.2. Mixing engine and loudness compliance
- 4.3. Audio runs, previews, and feedback
- 4.4. Voice preview and export jobs

### Phase 5: Client and interface experience

Current "Objectives" (5.1.1, 5.1.2, 5.1.3) describe API-first access, editorial
collaboration, and real-time streaming. These become the phase preamble.

Current "Key activities" (5.2.1–5.2.12) span:

- REST and GraphQL surfaces (5.2.1, 5.2.7, 5.2.8, 5.2.9, 5.2.12).
- Approval workflow (5.2.2).
- Notifications (5.2.3).
- CLI and web console (5.2.4, 5.2.5).
- TUI API design (5.2.6).
- WebSocket streaming (5.2.10, 5.2.11).

Proposed Steps:

- 5.1. REST API surfaces and version prefix
- 5.2. Editorial approval workflow and notifications
- 5.3. CLI and web console
- 5.4. WebSocket event streaming

### Phase 6: Security, compliance, and operations

Current "Objectives" (6.1.1) is a single high-level goal. This becomes the
phase preamble.

Current "Key activities" (6.2.1–6.2.7) span:

- RBAC and tenancy (6.2.1).
- Runtime security (6.2.2).
- Disaster recovery (6.2.3).
- Observability (6.2.4).
- Compliance (6.2.5).
- Budget enforcement and dashboards (6.2.6, 6.2.7).

Proposed Steps:

- 6.1. RBAC, tenancy isolation, and secrets rotation
- 6.2. Runtime security and policy enforcement
- 6.3. Disaster recovery and backup verification
- 6.4. Observability, SLIs, and compliance automation
- 6.5. Budget enforcement and cost dashboards

## Revision note

- 2026-03-17: Initial draft created for roadmap normalization task. Plan
  awaiting approval before implementation.
