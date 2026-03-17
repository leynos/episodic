# Development roadmap

This roadmap sequences the work to deliver the episodic podcast generation
platform. Each phase represents a deployable increment that aligns with the
system design. Phases are strategic milestones explaining why the work matters;
steps are workstreams describing what will be built; tasks are execution units
specifying how each piece gets done.

## 1. Canonical content foundation

This phase lands the Text Encoding Initiative (TEI) oriented domain model,
multi-source ingestion stack, and reusable reference-document system. Success
is observable when canonical TEI documents persist with full provenance after
ingesting heterogeneous sources, and series profiles, episode templates, and
reference documents are retrievable via the public Application Programming
Interface (API) with optimistic locking and change history. See
[Episodic Podcast System Design](episodic-podcast-generation-system-design.md)
§[Component Responsibilities](episodic-podcast-generation-system-design.md#component-responsibilities)
and §[Data Model and Storage](episodic-podcast-generation-system-design.md#data-model-and-storage)
for design context.

### 1.1. Relational schema and persistence layer

Design and implement the database schema and data access patterns. Completion
enables persistent storage of all canonical entities.

- [x] 1.1.1. Design the relational schema covering core entities.
  - Define TEI headers, canonical episodes, and approval states.
  - Define ingestion jobs and source documents.
  - Define series profiles and episode templates.
  - See `docs/episodic-podcast-generation-system-design.md` §Canonical content
    schema decisions.
- [x] 1.1.2. Introduce migration tooling with Alembic.
  - Configure Alembic for version-controlled schema migrations.
  - Wire migration checks into CI to block divergent schemas.
- [x] 1.1.3. Implement the repository and unit-of-work layers.
  - Define repository interfaces for each aggregate root.
  - Implement Postgres-backed repositories with SQLAlchemy.
  - Add integration tests validating transactional boundaries.
  - See `docs/episodic-podcast-generation-system-design.md` §Repository and
    unit-of-work implementation.

### 1.2. Multi-source ingestion service

Build the ingestion pipeline that normalizes heterogeneous inputs into
canonical TEI. Completion enables content acquisition from diverse sources.

- [x] 1.2.1. Build the multi-source ingestion service.
  - Accept Really Simple Syndication (RSS) feeds, briefs, transcripts, press
    releases, and research notes.
  - Apply document classifiers and quality scores.
  - See `docs/episodic-podcast-generation-system-design.md` §Multi-source
    Ingestion Service.
- [x] 1.2.2. Implement source weighting heuristics and conflict resolution.
  - Define priority rules when sources conflict.
  - Normalize inputs into TEI fragments and merge into canonical episodes.
- [x] 1.2.3. Capture provenance metadata automatically in TEI headers.
  - Record source priorities, ingestion timestamps, and reviewer identities.
  - Validate with integration and Behaviour-Driven Development (BDD) tests.
  - See `docs/episodic-podcast-generation-system-design.md` §Multi-source
    ingestion service implementation.

### 1.3. Reusable reference documents

Define and implement the reference-document model for reusable content across
series and episodes. Completion enables shared style guides, character
profiles, and research briefs.

- [x] 1.3.1. Define the reusable reference-document model.
  - Define `ReferenceDocument`, `ReferenceDocumentRevision`, and
    `ReferenceBinding` entities.
  - Define repository contracts independent of ingestion-job scope.
  - Include series-aligned host and guest profile documents.
  - See `docs/episodic-podcast-generation-system-design.md` §Reusable
    reference-document model.
- [x] 1.3.2. Publish approved Entity-Relationship (ER) diagram and glossary.
  - Document all three entities with field definitions.
  - Obtain stakeholder approval for model definitions.
  - See `docs/episodic-podcast-generation-system-design.md`
    §Reference-document glossary.
- [x] 1.3.3. Document repository and API contract acceptance criteria.
  - Define repository method signatures and behaviours.
  - Define API endpoint contracts for reference operations.
  - See `docs/episodic-podcast-generation-system-design.md` §Reusable
    reference repository contract acceptance criteria.
- [x] 1.3.4. Implement Representational State Transfer (REST) endpoints for
  reusable reference documents. Requires 1.3.1.
  - Implement create, get, list, and update for `ReferenceDocument`.
  - Implement revision and binding workflows.
  - Implement optimistic locking and change history retrieval.
  - Implement series-aligned host and guest profile access.
  - See `docs/episodic-podcast-generation-system-design.md` §Reusable
    reference REST API specification.

### 1.4. Series profiles, episode templates, and binding resolution

Define configuration entities and implement binding resolution for reusable
content. Completion enables downstream generators to retrieve structured briefs.

- [x] 1.4.1. Define series profile and episode template models.
  - Define fields for tone descriptors, segment ordering, and audio
    preferences.
  - Define change history and versioning semantics.
  - See `docs/episodic-podcast-generation-system-design.md` §Series Profile
    and Template Service.
- [x] 1.4.2. Implement REST endpoints for series profiles and episode
  templates.
  - Implement create, get, list, and update operations.
  - Implement change history retrieval.
  - Publish REST API specification.
  - See `docs/episodic-podcast-generation-system-design.md` §Profile/template
    REST API specification.
- [ ] 1.4.3. Implement reference-binding resolution. Requires 1.3.1.
  - Enable ingestion runs, profiles, and templates to reuse pinned revisions.
  - Preserve provenance snapshots in ingestion records.
  - Support `effective_from_episode_id` for revisions applying from specific
    episodes onwards.
  - Scope: repository and API behaviour only.

### 1.5. Service scaffolding and hexagonal boundaries

Scaffold the application services with consistent architecture patterns.
Completion enables feature development within enforced boundaries.

- [x] 1.5.1. Scaffold Falcon 4.2.x HTTP services running on Granian.
  - Configure baseline routing and health check endpoints.
  - Wire dependency injection hooks for port adapters.
  - Note: Falcon 4.2.x is operational; Granian runtime integration pending.
  - See `docs/episodic-podcast-generation-system-design.md` §Architectural
    Summary.
- [ ] 1.5.2. Scaffold Celery workers with RabbitMQ integration.
  - Define queue bindings and routing keys for task dispatch.
  - Configure concurrency pools for I/O-bound and CPU-bound workloads.
  - See `docs/episodic-podcast-generation-system-design.md` §Architectural
    Summary.
- [x] 1.5.3. Define hexagonal architecture boundaries and port contracts.
  - Document domain, port, and adapter responsibilities.
  - Define allowed dependency directions between layers.
  - See `docs/episodic-podcast-generation-system-design.md` §Hexagonal
    architecture enforcement.
- [ ] 1.5.4. Implement architectural enforcement checks for hexagonal
  boundaries.
  - Add lint rules to flag forbidden import directions.
  - Add architecture tests to validate port contract adherence.
  - Gate CI pipelines on enforcement check pass.
  - Note: Ruff linting configured; dedicated architecture tests pending.

## 2. Intelligent content generation and quality assurance (QA)

This phase orchestrates Large Language Model (LLM) based draft generation,
enrichment, and multi-layer review. It automates compliance checks against
brand and regulatory guidance, instruments cost accounting, and exposes
generation runs via the API. Success is observable when generated scripts
achieve defined quality thresholds, pass brand guideline checks, and cost
ledgers report per-episode spend with budget breach alerts. See
`docs/episodic-podcast-generation-system-design.md` §Content Generation
Orchestrator and §Quality Assurance Stack for design context.

### 2.1. LLM adapter and guardrails

Implement the inference boundary with retry semantics, token budgeting, and
content guardrails. Completion enables controlled LLM invocation from
orchestration code.

- [x] 2.1.1. Implement the `LLMPort` adapter with retry and token budgeting.
  - Define retry policy for transient provider failures.
  - Enforce token budgets pre-flight and post-call.
  - Return provider-agnostic usage metadata.
  - See `docs/episodic-podcast-generation-system-design.md` §Content
    Generation Orchestrator.
- [x] 2.1.2. Implement guardrail prompts aligned to content templates.
  - Derive guardrail text from series profile and episode template inputs.
  - Include guardrails in outbound LLM requests.
  - Validate guardrail placement with behavioural tests.

### 2.2. QA services

Extend quality evaluation services to score content and enforce brand
compliance. Completion enables automated quality gating before editorial
approval.

- [ ] 2.2.1. Extend Bromide service to score factuality and accuracy.
  - Expose OpenAPI specification with SLA4OAI (Service Level Agreements for
    OpenAPI) pricing plans.
  - Return structured findings and usage metrics per call.
- [ ] 2.2.2. Extend Chiltern service to score tone and style.
  - Expose OpenAPI specification with SLA4OAI pricing plans.
  - Return structured findings and usage metrics per call.
- [ ] 2.2.3. Add automated brand-guideline evaluation.
  - Lint textual output for vocabulary and forbidden topics.
  - Validate tone against brand tone descriptors.
  - Record pass/fail outcomes linked to the canonical episode.
- [ ] 2.2.4. Persist QA artefacts linked to canonical episodes.
  - Store review comments, rubric scores, and compliance results.
  - Enable retrieval via API and CLI filtered by compliance status.

### 2.3. Content enrichment and TEI body generation

Enrich canonical TEI bodies with structured metadata sourced from templates.
Completion enables rich episode content with chapter markers and guest details.

- [ ] 2.3.1. Generate show notes from template expansions.
  - Extract key topics and timestamps from generated content.
  - Format as structured metadata within TEI body.
- [ ] 2.3.2. Generate chapter markers aligned to script segments.
  - Define chapter boundaries based on segment transitions.
  - Include timing metadata for podcast player compatibility.
- [ ] 2.3.3. Generate guest bios from reference document bindings.
  - Retrieve guest profile reference documents.
  - Format biographical summaries within TEI body.
- [ ] 2.3.4. Generate sponsor reads from template-defined placements.
  - Retrieve sponsor content from template configuration.
  - Insert at defined segment positions.

### 2.4. LangGraph orchestration and cost accounting

Implement resumable orchestration with idempotency, queue routing, and cost
metering. Completion enables reliable, auditable generation workflows.

- [ ] 2.4.1. Implement structured-output planning and tool-calling execution.
  - Define model tiering for cost control.
  - Implement tool-calling patterns for enrichment steps.
- [ ] 2.4.2. Add LangGraph suspend-and-resume orchestration. Requires 2.1.1.
  - Implement checkpoint persistence for resumable workflows.
  - Define idempotency keys for each workflow step.
  - See `docs/episodic-podcast-generation-system-design.md` §LangGraph
    Integration Principles.
- [ ] 2.4.3. Configure Celery queue routing for workload isolation.
  - Route I/O-bound tasks to high-concurrency pools.
  - Route CPU-bound tasks to prefork pools.
- [ ] 2.4.4. Instrument cost accounting with per-call usage metering.
  - Record token counts and model identifiers per LLM call.
  - Pin SLA4OAI pricing snapshots for helper services.
  - Aggregate run totals with hierarchical ledger entries.
  - See `docs/episodic-podcast-generation-system-design.md` §Cost accounting
    and budget enforcement.
- [ ] 2.4.5. Extend architecture enforcement to orchestration code.
  - Validate LangGraph nodes depend on ports only.
  - Validate Celery tasks depend on ports only.
  - Audit checkpoint payload boundaries.

### 2.5. Pricing catalogue and budget enforcement

Implement pricing discovery, metering, and budget reservation. Completion
enables cost control and budget breach prevention.

- [ ] 2.5.1. Add `PricingCataloguePort` adapter with SLA discovery.
  - Fetch pricing plans via OpenAPI SLA4OAI extensions.
  - Validate schema and cache with Time-to-Live (TTL) and ETag support.
  - Persist pricing snapshots for historical reference.
- [ ] 2.5.2. Add `PricingEngine` with concurrency-safe metering.
  - Implement `MeteringPort` for usage recording.
  - Price individual calls deterministically with quota and overage handling.
- [ ] 2.5.3. Extend `CostLedgerPort` storage for helper service calls.
  - Record operation identifiers and usage metrics.
  - Record plan identifiers and SLA snapshot identifiers.
- [ ] 2.5.4. Extend `BudgetPort` APIs for reservation workflow.
  - Reserve estimated spend for helper calls before invocation.
  - Commit actual spend on success.
  - Release reservation on failure or timeout.
  - Key reservations by idempotency key.

### 2.6. Generation runs and checkpoints

Define the generation-run domain model and implement API endpoints. Completion
enables real-time visibility into generation progress.

- [ ] 2.6.1. Define `GenerationRunPort` and implement domain model.
  Requires 2.4.2.
  - Define `GenerationRun`, `GenerationEvent`, and `Checkpoint` entities.
  - Use frozen dataclasses with UUIDv7 identifiers.
  - Implement append-only event log with monotonic sequence numbers.
  - Define checkpoint lifecycle (created, responded).
  - See `docs/episodic-tui-api-design.md` §Generation runs.
- [ ] 2.6.2. Implement repository contracts and Alembic migrations.
  - Define repository interfaces for generation-run aggregates.
  - Add integration tests validating event ordering.
- [ ] 2.6.3. Implement REST endpoints for generation runs. Requires 2.6.1.
  - Implement `/v1/episodes/{episode_id}/generation-runs` (POST, GET).
  - Implement `/v1/generation-runs/{run_id}` (GET).
  - Implement `/v1/generation-runs/{run_id}/events` (GET) with pagination.
  - Implement `/v1/generation-runs/{run_id}/checkpoint` (POST) for checkpoint
    submission.
  - Enforce idempotency-key support for run creation.
  - Validate hexagonal boundary tests passing.
  - See `docs/episodic-tui-api-design.md` §Generation runs.

### 2.7. Script projection and editing

Implement structured script projection for editing without direct TEI
manipulation. Completion enables user-friendly script review and patching.

- [ ] 2.7.1. Define `ScriptProjectionPort` and projection schema.
  - Translate canonical TEI into segment-and-speaker-turn JSON structure.
  - Define versioning for optimistic locking.
- [ ] 2.7.2. Implement script projection read endpoint.
  - Implement `/v1/episodes/{episode_id}/script` (GET).
  - Return versioned projection with segment and turn structure.
  - See `docs/episodic-tui-api-design.md` §Script projection and editing.
- [ ] 2.7.3. Implement script projection patch endpoint. Requires 2.7.2.
  - Implement `/v1/episodes/{episode_id}/script` (PATCH).
  - Apply domain patches with `expected_version` enforcement.
  - Validate round-trip projection-to-TEI fidelity.

## 3. Audio synthesis and delivery

This phase produces production-ready audio with narration, music, and
compliance-checked levels, and provides reliable preview and delivery
workflows. Success is observable when end-to-end renders produce master files
with embedded chapter markers, quality automation rejects mixes violating
loudness thresholds, and audio runs are accessible via REST endpoints with
signed download URLs. See `docs/episodic-podcast-generation-system-design.md`
§Audio Synthesis Pipeline for design context.

### 3.1. Text-to-speech (TTS) adapter

Implement the TTS inference boundary with voice persona configuration and retry
semantics. Completion enables speech synthesis from script content.

- [ ] 3.1.1. Implement the `TTSPort` adapter with retry semantics.
  - Define retry policy for transient provider failures.
  - Return provider-agnostic audio segments with metadata.
- [ ] 3.1.2. Implement configurable voice persona support.
  - Define voice persona configuration schema.
  - Map personas to provider-specific voice identifiers.
  - Support per-speaker voice assignment.

### 3.2. Mixing engine and loudness compliance

Build the audio mixing engine with stem management and loudness normalization.
Completion enables broadcast-quality audio production.

- [ ] 3.2.1. Integrate background music and sound effect stem management.
  - Define asset catalogue schema for music beds and effects.
  - Implement bed selection based on template configuration.
  - Schedule mixes relative to script beats and segment transitions.
- [ ] 3.2.2. Build the mixing engine for narration and stem combination.
  - Implement ducking for voice-over-music transitions.
  - Implement fades and scene transitions.
  - Support stem isolation for post-production flexibility.
- [ ] 3.2.3. Enforce loudness normalization to broadcast standards.
  - Target -16 Loudness Units Full Scale (LUFS) ±1 Loudness Unit (LU)
    integrated loudness per European Broadcasting Union (EBU) R128.
  - Implement peak limiting across stereo channels.
  - Reject mixes violating thresholds with actionable diagnostics.

### 3.3. Audio runs, previews, and feedback

Define the audio-run domain model and implement run lifecycle endpoints.
Completion enables audio workflow tracking and iterative refinement.

- [ ] 3.3.1. Define `AudioRunPort` and implement domain model.
  Requires 3.1.1, 3.2.2.
  - Define `AudioRun`, `PreviewAsset`, `StemAsset`, and `AudioFeedback`
    entities.
  - Use frozen dataclasses with UUIDv7 identifiers.
  - Link preview assets to audio runs with signed storage Uniform Resource
    Identifiers (URIs).
  - Classify stem assets by type (narration, music, sound effects (SFX),
    ambience).
  - Define feedback actions (approve, reject, regenerate segment).
  - See `docs/episodic-tui-api-design.md` §Audio runs, previews, stems, and
    feedback.
- [ ] 3.3.2. Implement repository contracts and Alembic migrations.
  - Define repository interfaces for audio-run aggregates.
  - Add integration tests validating asset linking.
- [ ] 3.3.3. Implement REST endpoints for audio runs. Requires 3.3.1.
  - Implement `/v1/episodes/{episode_id}/audio-runs` (POST, GET).
  - Implement `/v1/audio-runs/{audio_run_id}` (GET).
  - Implement `/v1/audio-runs/{audio_run_id}/previews` (GET) with signed URLs.
  - Implement `/v1/audio-runs/{audio_run_id}/feedback` (POST) for segment-level
    actions.
  - Implement `/v1/episodes/{episode_id}/stems` (GET, POST) with multipart or
    upload-reference attachment.
  - Enforce idempotency-key support for run creation.
  - Validate hexagonal boundary tests passing.
- [ ] 3.3.4. Generate shareable previews via `PreviewPublisherPort`.
  - Store preview artefacts in object storage.
  - Generate signed URLs with configurable expiry.

### 3.4. Voice preview and export jobs

Implement standalone voice preview synthesis and export job workflows.
Completion enables persona testing and deliverable packaging.

- [ ] 3.4.1. Define `VoicePreviewPort` and implement synthesis endpoints.
  Requires 3.1.1.
  - Implement `/v1/voice-previews` (POST) accepting text and voice
    configuration.
  - Implement `/v1/voice-previews/{preview_id}` (GET) returning status and
    signed audio URL.
  - Ensure synthesis does not modify episode state.
  - Enforce idempotency-key support.
  - See `docs/episodic-tui-api-design.md` §Voice previews.
- [ ] 3.4.2. Define `ExportJobPort` and implement export endpoints.
  Requires 3.2.2, 3.2.3.
  - Implement `/v1/episodes/{episode_id}/exports` (POST, GET).
  - Implement `/v1/exports/{export_id}` (GET) returning status and download
    URLs.
  - Support export types: master audio, stems bundle, TEI bundle, combined
    stems-plus-TEI bundle.
  - Include manifest hash for integrity verification.
  - Store export artefacts in object storage with signed URLs.
  - See `docs/episodic-tui-api-design.md` §Export jobs.
- [ ] 3.4.3. Publish final masters to Content Delivery Network (CDN) endpoints.
  - Configure CDN distribution for audio assets.
  - Support optional RSS feed publication.

## 4. Client and interface experience

This phase delivers API-first access backed by approval workflows and client
tooling, enables editorial collaboration and notifications, and provides
real-time event streaming for agentic workflows. Success is observable when
editorial teams complete end-to-end approvals via API, Command-Line Interface
(CLI), and web console, audit trails capture every transition, and WebSocket
streaming delivers real-time events with backpressure control. See
`docs/episodic-tui-api-design.md` for TUI API design context.

### 4.1. REST API surfaces and version prefix

Finalize REST API surfaces with consistent contracts and version routing.
Completion enables stable API consumption by clients.

- [ ] 4.1.1. Introduce `/v1` API version prefix for new endpoints.
  - Route all new TUI-facing endpoints under `/v1`.
  - Preserve existing unversioned routes during transition.
  - Document version routing in the developers' guide.
  - See `docs/episodic-tui-api-design.md` §Proposed REST endpoints.
- [ ] 4.1.2. Finalize REST and GraphQL surfaces for previous phase artefacts.
  - Implement pagination, filtering, and role enforcement.
  - Ensure consistent error contracts across all endpoints.
  - See `docs/episodic-tui-api-design.md` §Error contract.

### 4.2. Episode and approval workflow endpoints

Implement episode lifecycle endpoints and the editorial approval state machine.
Completion enables structured approval workflows with audit trails.

- [ ] 4.2.1. Implement editorial approval state machine. Requires 1.1.1.
  - Define configurable approval stages.
  - Implement Service Level Agreement (SLA) timers for stage transitions.
  - Enable audit logging for all state changes.
- [ ] 4.2.2. Implement episode REST endpoints. Requires 4.2.1.
  - Implement `/v1/episodes` (POST, GET) with lifecycle filtering.
  - Implement `/v1/episodes/{episode_id}` (GET, PATCH).
  - Implement `/v1/episodes/{episode_id}/tei` (GET, PUT) with versioned
    envelope and optimistic locking.
  - Implement `/v1/episodes/{episode_id}/approval-events` (GET, POST) with
    audit preservation.
  - See `docs/episodic-tui-api-design.md` §Episodes and TEI.
- [ ] 4.2.3. Integrate notification channels for approval events.
  - Support email, Slack, and webhook notifications.
  - Trigger on approvals, rejections, and automated compliance alerts.

### 4.3. Ingestion and upload endpoints

Implement ingestion job endpoints and file upload infrastructure. Completion
enables programmatic content submission.

- [ ] 4.3.1. Define `UploadPort` and implement file upload endpoints.
  - Implement `/v1/uploads` (POST) for direct multipart upload.
  - Implement `/v1/uploads/init` (POST) for pre-signed object storage flows.
  - Enforce content-type allowlist and maximum file size.
  - Validate hexagonal boundary tests passing.
  - See `docs/episodic-tui-api-design.md` §Uploads.
- [ ] 4.3.2. Implement ingestion job and source endpoints. Requires 4.3.1.
  - Implement `/v1/ingestion-jobs` (POST, GET) with series-scoped filtering.
  - Implement `/v1/ingestion-jobs/{job_id}` (GET) with status reflection.
  - Implement `/v1/ingestion-jobs/{job_id}/sources` (POST) with upload
    reference or URI attachment.
  - See `docs/episodic-tui-api-design.md` §Ingestion jobs and sources.

### 4.4. WebSocket event streaming

Implement real-time event streaming for generation runs. Completion enables live
workflow observation and checkpoint intervention.

- [ ] 4.4.1. Define `RunEventBusPort` and implement WebSocket streaming for
  generation runs. Requires 2.6.1.
  - Implement `/ws/runs/{run_id}` via Falcon-Pachinko.
  - Use `msgspec` tagged-union message dispatch.
  - Implement room-based broadcast keyed by `run_id`.
  - Handle `client.hello`, `run.subscribe`, `run.ack`, and `checkpoint.submit`
    client messages.
  - Send `server.welcome`, `run.event`, `run.checkpoint`, `run.complete`, and
    `server.error` server messages.
  - Enforce authentication timeout.
  - Publish AsyncAPI specification.
  - Note: Scope covers generation runs only; audio runs use REST polling.
  - See `docs/episodic-tui-api-design.md` §WebSocket API for real-time
    generation events.
- [ ] 4.4.2. Implement WebSocket backpressure and reconnection. Requires 4.4.1.
  - Implement acknowledgement-gated outbound buffering with bounded ring
    buffer.
  - Implement event compaction under acknowledgement lag.
  - Implement sequence-based replay on reconnection.
  - Send backpressure close code (4000) when client falls behind.
  - Provide REST fallback via `resume_unavailable` error.
  - See `docs/episodic-tui-api-design.md` §Backpressure.

### 4.5. CLI and web console

Extend command-line tooling and ship the initial web console. Completion
enables operator and editorial self-service.

- [ ] 4.5.1. Extend CLI client for approval workflows.
  - Support approval actions (submit, approve, reject).
  - Support diff viewing between episode versions.
  - Support audio preview downloads.
- [ ] 4.5.2. Ship initial web console for editorial workflows.
  - Implement series profile and template management views.
  - Implement approval queue dashboard.
  - Implement real-time generation progress view.

### 4.6. API documentation and specifications

Publish OpenAPI and AsyncAPI specifications for all API surfaces. Completion
enables client SDK generation and contract validation.

- [ ] 4.6.1. Publish TUI API design document.
  - Document REST endpoint specifications.
  - Document WebSocket message schemas.
  - Document authentication, error, and pagination conventions.
  - See `docs/episodic-tui-api-design.md`.
- [ ] 4.6.2. Generate OpenAPI specification from endpoint definitions.
  - Validate specification against implemented endpoints.
  - Publish specification for client SDK generation.
- [ ] 4.6.3. Generate AsyncAPI specification from WebSocket schemas.
  - Validate specification against implemented message handlers.
  - Complete contract review with TUI repository maintainers.

## 5. Security, compliance, and operations

This phase hardens the platform, automates ongoing operations, and implements
budget enforcement with cost visibility. Success is observable when the
security posture is reviewed quarterly with no critical findings, automated
dashboards report green for deployments and latency Service Level Objectives
(SLOs), and cost dashboards report per-organization spend with budget breach
alerts. See `docs/infrastructure-design.md` for operational infrastructure
context.

### 5.1. Role-Based Access Control (RBAC), tenancy isolation, and secrets rotation

Implement fine-grained access control, tenant boundaries, and credential
lifecycle management. Completion enables secure multi-tenant operation.

- [ ] 5.1.1. Implement fine-grained RBAC across all services.
  - Define role hierarchy and permission boundaries.
  - Implement RBAC middleware for API endpoints.
  - Add integration tests for permission enforcement.
- [ ] 5.1.2. Implement tenancy isolation for multi-organization support.
  - Define tenant boundaries at data and service levels.
  - Implement tenant context propagation.
  - Validate cross-tenant access prevention.
- [ ] 5.1.3. Implement automated secrets rotation.
  - Define rotation schedule for service credentials.
  - Implement zero-downtime credential rollover.
  - Document emergency rotation procedures.

### 5.2. Runtime security and policy enforcement

Add security scanning, dependency auditing, and policy-as-code controls.
Completion enables proactive vulnerability management.

- [ ] 5.2.1. Add runtime security scanning for container images.
  - Integrate image scanning into CI/CD pipelines.
  - Define vulnerability severity thresholds for deployment gates.
- [ ] 5.2.2. Add dependency auditing with automated alerts.
  - Monitor dependencies for known vulnerabilities.
  - Configure alerting for critical and high severity findings.
- [ ] 5.2.3. Implement policy-as-code enforcement in CI/CD.
  - Define infrastructure and security policies as code.
  - Gate deployments on policy compliance.

### 5.3. Disaster recovery and backup verification

Implement GitOps-driven recovery drills and backup validation. Completion
enables confident incident response.

- [ ] 5.3.1. Roll out GitOps-driven disaster recovery drills.
  - Define drill scenarios and success criteria.
  - Schedule regular drill execution.
  - Document lessons learned and improvement actions.
- [ ] 5.3.2. Implement automated backup verification.
  - Define verification schedule and success criteria.
  - Implement automated restore testing.
  - Alert on verification failures.
- [ ] 5.3.3. Publish incident runbooks.
  - Document common failure scenarios and resolution steps.
  - Define escalation paths and communication templates.

### 5.4. Observability, SLIs, and compliance automation

Expand monitoring with synthetic probes and customer-facing SLIs; automate
compliance evidence collection. Completion enables operational excellence and
audit readiness.

- [ ] 5.4.1. Expand observability with synthetic monitoring.
  - Define synthetic probes for critical user journeys.
  - Configure alerting on probe failures.
- [ ] 5.4.2. Define and instrument customer-facing SLIs and SLAs.
  - Define Service Level Indicators (SLIs) for availability and latency.
  - Implement SLI instrumentation in services.
  - Configure SLO (Service Level Objective) breach alerting.
- [ ] 5.4.3. Certify compliance checkpoints.
  - Conduct SOC 2 Type II readiness assessment.
  - Conduct General Data Protection Regulation (GDPR) Data Protection Impact
    Assessment (DPIA).
  - Document compliance status and remediation plans.
- [ ] 5.4.4. Integrate automated compliance evidence collection.
  - Define evidence collection requirements per framework.
  - Implement automated evidence gathering.
  - Configure evidence retention and access controls.

### 5.5. Budget enforcement and cost dashboards

Implement budget controls and cost visibility for operators. Completion enables
cost management and financial accountability.

- [ ] 5.5.1. Implement budget enforcement services.
  - Define per-user and per-organization budget caps.
  - Implement budget enforcement in request path.
  - Configure alerting on budget threshold approach.
- [ ] 5.5.2. Deliver cost dashboards for operators.
  - Display token usage by model and service.
  - Display per-task and per-episode spend.
  - Display budget breach trends and alerts.
  - Enable drill-down from organization to individual runs.

## 6. Platform foundations

This phase establishes the foundational infrastructure, deployment automation,
and architectural patterns that underpin the platform. Success is observable
when services deploy reliably across environments via GitOps, hexagonal
boundaries enforce clean architecture, and observability instruments all layers
with logging, metrics, and distributed tracing. See
`docs/infrastructure-design.md` and
`docs/episodic-podcast-generation-system-design.md` §Architectural Summary for
design context.

### 6.1. Infrastructure provisioning

Provision the compute, storage, and messaging infrastructure that underpins the
platform. Completion enables service deployments and data persistence.

- [ ] 6.1.1. Bootstrap the Kubernetes control plane on DigitalOcean Kubernetes
  Service (DOKS).
  - Configure node pools for sandbox, staging, and production.
  - Enable cluster autoscaling with defined min/max bounds.
  - See `docs/infrastructure-design.md` §Architecture overview.
- [ ] 6.1.2. Deploy CloudNativePG Postgres cluster with high-availability
  configuration.
  - Configure synchronous replication and automated failover.
  - Define backup schedule and retention policy.
- [ ] 6.1.3. Deploy Valkey cache (Redis-compatible) via the Valkey operator.
  - Configure memory limits and eviction policy.
  - Enable persistence for session and rate-limit data.
- [ ] 6.1.4. Deploy RabbitMQ operator with queue definitions for background
  tasks.
  - Define exchanges and routing keys for Celery workers.
  - Configure message durability and dead-letter handling.
- [ ] 6.1.5. Provision object storage buckets for audio assets and binary
  artefacts.
  - Configure lifecycle policies for temporary uploads.
  - Enable versioning for canonical audio masters.
- [ ] 6.1.6. Deploy Traefik ingress controller and cert-manager with Let's
  Encrypt issuers.
  - Configure TLS termination and automatic certificate renewal.
  - Define ingress routes for HTTP and WebSocket traffic.

### 6.2. GitOps and secrets management

Establish declarative deployment pipelines and secure credential handling.
Completion enables repeatable, auditable deployments across environments.

- [ ] 6.2.1. Create the GitOps repository via the bootstrap script.
  - Generate repository structure with FluxCD sources.
  - Define deployment templates for core services.
  - See `docs/infrastructure-design.md` §GitOps repository model.
- [ ] 6.2.2. Configure FluxCD with Kustomization overlays for environment
  promotion.
  - Define sandbox → staging → production promotion gates.
  - Configure image automation for tagged releases.
- [ ] 6.2.3. Configure secret management using SOPS (Secrets OPerationS) and
  age encryption.
  - Define key distribution and rotation procedures.
  - Document emergency access and recovery steps.
  - See `docs/infrastructure-design.md` §Secrets and identity.

### 6.3. Observability and documentation

Instrument monitoring, logging, and tracing; publish operational documentation.
Completion enables incident response and onboarding.

- [ ] 6.3.1. Instrument clusterwide logging with Loki.
  - Configure log aggregation from all service pods.
  - Define log retention and archival policies.
  - See `docs/infrastructure-design.md` §Observability.
- [ ] 6.3.2. Instrument clusterwide metrics with Prometheus.
  - Configure service discovery for metric scraping.
  - Define alert rules for resource exhaustion and error rates.
- [ ] 6.3.3. Instrument distributed tracing with Tempo.
  - Configure trace propagation across HTTP and message boundaries.
  - Define trace sampling rate and retention policy.
- [ ] 6.3.4. Define alert routing rules for on-call responders.
  - Configure escalation paths and notification channels.
  - Document alert triage procedures.
- [ ] 6.3.5. Document access controls and networking policies.
  - Define network policy rules for pod-to-pod communication.
  - Document role-based access control (RBAC) for cluster operators.
- [ ] 6.3.6. Document disaster recovery expectations and restore procedures.
  - Define Recovery Point Objective (RPO) and Recovery Time Objective (RTO)
    targets.
  - Document backup verification and restore runbook.
- [ ] 6.3.7. Publish the infrastructure design document.
  - Cover DOKS, GitOps, secrets, and observability baselines.
  - Obtain stakeholder approval for infrastructure baseline.
  - See `docs/infrastructure-design.md`.
