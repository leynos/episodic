# Development roadmap

This roadmap sequences the work to deliver the episodic podcast generation
platform. Each phase represents a deployable increment with clear exit criteria
that align with the system design.

## 1. Platform foundations

### 1.1. Objectives

- [ ] 1.1.1. Provision shared infrastructure required by all later phases.
- [ ] 1.1.2. Establish continuous delivery pipelines and baseline observability.

### 1.2. Key activities

- [ ] 1.2.1. Bootstrap the Kubernetes control plane, CloudNativePG Postgres
  cluster, Valkey cache (Redis-compatible), RabbitMQ operator, and object
  storage buckets for audio assets.
- [ ] 1.2.2. Configure secret management (SOPS + age) and environment promotion
  strategy.
- [ ] 1.2.3. Create the GitOps repository via the bootstrap script, then
  configure FluxCD sources and deployment templates for core services.
- [ ] 1.2.4. Define the hexagonal architecture boundaries and port contracts
  across services. See `docs/episodic-podcast-generation-system-design.md`.
- [ ] 1.2.5. Scaffold Falcon 4.2.x HTTP services running on Granian with
  baseline routing, health checks, and dependency injection hooks.
- [ ] 1.2.6. Scaffold Celery workers with RabbitMQ queues, exchanges, and
  routing keys for background tasks.
- [ ] 1.2.7. Deploy Traefik ingress and cert-manager with Let's Encrypt issuers.
- [ ] 1.2.8. Instrument clusterwide logging, metrics, and tracing with
  Prometheus, Loki, and Tempo; define alert routing rules.
- [ ] 1.2.9. Document access controls, networking policies, and disaster
  recovery expectations.
- [ ] 1.2.10. Publish the infrastructure design document covering DOKS, GitOps,
  secrets, and observability baselines. See `docs/infrastructure-design.md`.
- [ ] 1.2.11. Implement architectural enforcement checks for hexagonal
  boundaries (lint rules and architecture tests). See
  `docs/episodic-podcast-generation-system-design.md`.

### 1.3. Exit criteria

- [ ] 1.3.1. Sandbox environment accepts deployments for the `ingestion`,
  `orchestrator`, and `audio` services via GitOps.
- [ ] 1.3.2. Platform runbook published covering provisioning, credentials, and
  restore procedures.
- [ ] 1.3.3. Infrastructure design document approved and referenced by Phase 0
  work.
- [ ] 1.3.4. CI gates include enforced hexagonal boundary checks.

## 2. Canonical content foundation

### 2.1. Objectives

- [ ] 2.1.1. Land the TEI-oriented domain model and ingestion stack.
- [ ] 2.1.2. Persist canonical artefacts with auditable provenance.

### 2.2. Key activities

- [x] 2.2.1. Design the relational schema covering TEI headers, canonical
  episodes, ingestion jobs, source documents, series profiles, and approval
  states.
- [x] 2.2.2. Introduce migration tooling with Alembic, wired into Continuous
  Integration (CI) to block divergent schemas.
- [x] 2.2.3. Implement the repository and unit-of-work layers over Postgres with
  integration tests.
- [x] 2.2.4. Build the multi-source ingestion service that normalizes inputs,
  applies source weighting heuristics, and resolves conflicts into canonical
  TEI.
- [x] 2.2.5. Capture provenance metadata automatically in TEI headers,
  including source priorities, ingestion timestamps, and reviewer identities;
  validated by integration and BDD tests that assert persisted TEI header
  provenance fields and ordering.
- [x] 2.2.6. Define the reusable reference-document model (`ReferenceDocument`,
  `ReferenceDocumentRevision`, and `ReferenceBinding`) and repository contracts
  independent of ingestion-job scope, including series-aligned host and guest
  profile documents. Finish line: approved ER diagram, glossary entries for all
  three entities, and documented repository plus API contract acceptance
  criteria.
- [x] 2.2.7. Define REST endpoints for reusable reference documents
  (`ReferenceDocument`, `ReferenceDocumentRevision`, and `ReferenceBinding`)
  with optimistic locking, change history retrieval, and series-aligned host
  and guest profile access. Acceptance criteria: published API specification;
  implemented endpoints for create/get/list/update plus revision-binding
  workflows; optimistic-locking behaviour validated; change-history retrieval
  tests passing; and host/guest profile access tests passing for series-aligned
  documents. Dependencies: 2.2.6 approved model definitions, authn/authz
  policies, database schema and migrations, migration plan for existing
  reusable documents, and client SDK contract updates. Sequencing: database
  schema and migrations -> optimistic-locking semantics -> endpoint
  implementation -> change-history retrieval -> host/guest profile access
  paths. Scope: API and repository behaviour only for supported fields and
  operations, paginated response sizes as defined in the API spec, and no
  production SLA tuning in this phase.
- [x] 2.2.8. Define series profile and episode template models, REST endpoints,
  and change history, so downstream generators can retrieve structured briefs.
  Acceptance criteria: documented models, published REST API specification, and
  versioned change-history format. Dependencies: 2.2.6 approved model
  definitions; downstream input for 2.2.9 binding resolution.
- [ ] 2.2.9. Implement reference-binding resolution so ingestion runs, series
  profiles, and episode templates can reuse pinned document revisions while
  preserving provenance snapshots in ingestion records, with
  `effective_from_episode_id` support for revisions that apply from a specific
  episode onwards. Prerequisite: 2.2.6 model definitions approved. Scope:
  repository and API behaviour only.

### 2.3. Exit criteria

- [ ] 2.3.1. Canonical TEI documents persist with full provenance after
  ingesting at least three heterogeneous source types.
- [ ] 2.3.2. Series profiles, episode templates, and reusable reference
  documents are retrievable via the public API with optimistic locking and
  change history, including series-aligned host and guest profiles.
- [ ] 2.3.3. Ingestion workflows can resolve reusable reference bindings and
  snapshot pinned revisions into per-job provenance records, honouring
  `effective_from_episode_id` semantics.

## 3. Intelligent content generation and QA

### 3.1. Objectives

- [ ] 3.1.1. Orchestrate LLM-based draft generation, enrichment, and
  multi-layer review.
- [ ] 3.1.2. Automate compliance checks against brand and regulatory guidance.

### 3.2. Key activities

- [x] 3.2.1. Implement the `LLMPort` adapter with retry, token budgeting, and
  guardrail prompts aligned to content templates.
- [ ] 3.2.2. Extend Bromide and Chiltern services to score factuality, tone,
  and style, exposing OpenAPI + SLA4OAI (Service Level Agreements for OpenAPI)
  pricing plans (`info.x-sla`) and returning structured findings plus usage
  metrics per call.
- [ ] 3.2.3. Add automated brand-guideline evaluation: lint textual output,
  validate tone, vocabulary, and forbidden topics, and record pass/fail
  outcomes.
- [ ] 3.2.4. Enrich TEI bodies with show notes, chapter markers, guest bios, and
  sponsor reads sourced from template expansions.
- [ ] 3.2.5. Persist QA artefacts, including review comments, rubric scores,
  and compliance results, linked to the canonical episode.
- [ ] 3.2.6. Expose generation and QA state via the API and CLI, including
  filtering by brand compliance status.
- [ ] 3.2.15. Define `GenerationRunPort` and implement the generation-run
  domain model (`GenerationRun`, `GenerationEvent`, `Checkpoint`) with
  repository contracts and Alembic migrations. Acceptance criteria: frozen
  dataclasses with UUIDv7 identifiers; append-only event log with monotonic
  sequence numbers; checkpoint lifecycle (created, responded); repository
  integration tests passing. Dependencies: 3.2.8 LangGraph orchestration and
  idempotency keys. Scope: domain model, ports, and repository layer only. See
  `docs/episodic-tui-api-design.md`.
- [ ] 3.2.16. Implement REST endpoints for generation runs
  (`/v1/episodes/{episode_id}/generation-runs`, `/v1/generation-runs/{run_id}`,
  `/v1/generation-runs/{run_id}/events`,
  `/v1/generation-runs/{run_id}/checkpoint`) with idempotency-key support,
  paginated event log retrieval, and checkpoint submission. Acceptance
  criteria: published endpoint specification; create, get, list, and checkpoint
  operations validated; pagination and error contracts consistent with existing
  canonical endpoints; hexagonal boundary tests passing. Dependencies: 3.2.15
  domain model; existing pagination and error-mapping helpers. Scope: API and
  repository behaviour only.
- [ ] 3.2.17. Define `ScriptProjectionPort` and implement structured
  script projection read and patch operations
  (`/v1/episodes/{episode_id}/script`). The projection translates canonical TEI
  into a segment-and-speaker-turn JSON structure and applies patches back to
  TEI with optimistic version locking. Acceptance criteria: GET returns
  versioned projection; PATCH applies domain patches with `expected_version`
  enforcement; round-trip projection-to-TEI fidelity validated. Dependencies:
  2.2.1 TEI schema; TEI serialization library. Scope: domain model, port,
  adapter, and endpoint implementation.
- [ ] 3.2.7. Implement structured-output planning and tool-calling execution
  with model tiering for cost control.
- [ ] 3.2.8. Add LangGraph suspend-and-resume orchestration, idempotency keys,
  and Celery queue routing for I/O-bound and CPU-bound workloads.
- [ ] 3.2.9. Instrument cost accounting with per-call usage metering, pinned
  SLA4OAI pricing snapshots for helper services, hierarchical ledger entries,
  and aggregated run totals.
- [ ] 3.2.10. Extend architecture enforcement to LangGraph nodes and Celery
  tasks, ensuring port-only dependencies and checkpoint payload boundaries.
- [ ] 3.2.11. Add `PricingCataloguePort` adapter with SLA discovery via OpenAPI,
  schema validation, caching (TTL/ETag), and snapshot persistence.
- [ ] 3.2.12. Add `PricingEngine` with a concurrency-safe `MeteringPort` to
  price individual calls deterministically when quotas and overages apply.
- [ ] 3.2.13. Extend `CostLedgerPort` storage to record helper service call line
  items, including operation identifiers, usage metrics, plan IDs, and SLA
  snapshot IDs.
- [ ] 3.2.14. Extend `BudgetPort` APIs to reserve estimated spend for helper
  calls and then commit/release against actuals (reserve → commit → release)
  keyed by idempotency key.

### 3.3. Exit criteria

- [ ] 3.3.1. Generated scripts achieve defined Bromide/Chiltern thresholds and
  pass brand guideline checks before entering approval.
- [ ] 3.3.2. QA dashboards surface per-episode compliance, reviewer comments,
  and ageing tasks.
- [ ] 3.3.3. LangGraph workflows resume from suspended tasks with idempotency
  keys and validated queue routing profiles.
- [ ] 3.3.4. Cost ledger reports per-episode spend and budget breaches using
  pinned pricing snapshots and hierarchical line items for LLM, TTS, and helper
  calls.
- [ ] 3.3.5. Generation runs, event logs, and checkpoints are accessible via
  REST endpoints with pagination and optimistic concurrency, and structured
  script projections support round-trip editing without direct TEI XML
  manipulation.

## 4. Audio synthesis and delivery

### 4.1. Objectives

- [ ] 4.1.1. Produce production-ready audio with narration, music, and
  compliance-checked levels.
- [ ] 4.1.2. Provide reliable preview and delivery workflows.

### 4.2. Key activities

- [ ] 4.2.1. Implement the `TTSPort` adapter with configurable voice personas
  and retry semantics.
- [ ] 4.2.2. Integrate background music and sound effect stems: manage asset
  catalogues, select beds per template, and schedule mixes relative to script
  beats.
- [ ] 4.2.3. Build the mixing engine to combine narration and stems, applying
  ducking, fades, and scene transitions.
- [ ] 4.2.4. Enforce loudness normalization to -16 LUFS +/- 1 LU and peak
  limiting across stereo channels.
- [ ] 4.2.5. Generate shareable previews via the `PreviewPublisherPort`,
  storing artefacts in object storage with signed URLs.
- [ ] 4.2.6. Publish final masters to CDN endpoints and optional RSS feeds.
- [ ] 4.2.7. Define `AudioRunPort` and implement the audio-run domain model
  (`AudioRun`, `PreviewAsset`, `StemAsset`, `AudioFeedback`) with repository
  contracts and Alembic migrations. Acceptance criteria: frozen dataclasses
  with UUIDv7 identifiers; preview assets linked to audio runs with signed
  storage URIs; stem assets linked to episodes with type classification
  (narration, music, sfx, ambience); feedback records capturing segment-level
  actions (approve, reject, regen_segment); repository integration tests
  passing. Dependencies: 4.2.1 TTS adapter; 4.2.5 preview publisher. Scope:
  domain model, ports, and repository layer only. See
  `docs/episodic-tui-api-design.md`.
- [ ] 4.2.8. Implement REST endpoints for audio runs, previews, stems, and
  feedback (`/v1/episodes/{episode_id}/audio-runs`,
  `/v1/audio-runs/{audio_run_id}`, `/v1/audio-runs/{audio_run_id}/previews`,
  `/v1/audio-runs/{audio_run_id}/feedback`, `/v1/episodes/{episode_id}/stems`)
  with idempotency-key support for run creation and multipart or
  upload-reference stem attachment. Acceptance criteria: published endpoint
  specification; create, get, list, and feedback operations validated; preview
  assets return signed download URLs; pagination and error contracts consistent
  with existing canonical endpoints; hexagonal boundary tests passing.
  Dependencies: 4.2.7 domain model. Scope: API and repository behaviour only.
- [ ] 4.2.9. Define `VoicePreviewPort` and implement voice preview synthesis
  endpoints (`/v1/voice-previews`, `/v1/voice-previews/{preview_id}`) for rapid
  persona and pronunciation testing, separate from episode audio runs.
  Acceptance criteria: POST accepts text and voice persona configuration,
  returns preview identifier; GET returns status and signed audio URL;
  synthesis does not create or modify episode state; idempotency-key support
  validated. Dependencies: 4.2.1 TTS adapter. Scope: domain model, port,
  adapter, and endpoint implementation.
- [ ] 4.2.10. Define `ExportJobPort` and implement export job endpoints
  (`/v1/episodes/{episode_id}/exports`, `/v1/exports/{export_id}`) supporting
  master audio, stems bundle, TEI bundle, and combined stems-plus-TEI bundle
  export types. Acceptance criteria: POST creates export job with format
  options and idempotency key; GET returns job status with download URLs and
  manifest hash; export artefacts stored in object storage with signed URLs;
  hexagonal boundary tests passing. Dependencies: 4.2.3 mixing engine; 4.2.4
  loudness normalization. Scope: domain model, port, adapter, and endpoint
  implementation.

### 4.3. Exit criteria

- [ ] 4.3.1. End-to-end render produces master files with embedded chapter
  markers and balanced stems for flagship shows.
- [ ] 4.3.2. QA automation rejects mixes that violate loudness or clipping
  thresholds.
- [ ] 4.3.3. Audio runs, previews, stems, and feedback are accessible via
  REST endpoints with pagination, signed download URLs, and segment-level
  feedback driving partial regeneration.
- [ ] 4.3.4. Voice preview synthesis operates independently of episode
  audio runs, with endpoints for persona testing and pronunciation verification.
- [ ] 4.3.5. Export jobs produce downloadable master audio or stems-plus-TEI
  bundles with manifest hashes and signed URLs.

## 5. Client and interface experience

### 5.1. Objectives

- [ ] 5.1.1. Deliver API-first access backed by approval workflows and client
  tooling.
- [ ] 5.1.2. Enable editorial collaboration and notifications.
- [ ] 5.1.3. Provide realtime event streaming for agentic generation and audio
  synthesis workflows.

### 5.2. Key activities

- [ ] 5.2.1. Finalise REST and GraphQL surfaces, including pagination,
  filtering, and role enforcement for all previous phase artefacts.
- [ ] 5.2.2. Implement the editorial approval state machine with configurable
  stages, SLA timers, and audit logging.
- [ ] 5.2.3. Integrate notification channels (email, Slack, webhook) for
  approvals, rejections, and automated compliance alerts.
- [ ] 5.2.4. Extend the CLI client to support approval actions, diff viewing,
  and audio preview downloads.
- [ ] 5.2.5. Ship the initial web console for managing series profiles,
  templates, and approval queues.
- [ ] 5.2.6. Publish the TUI API design document
  (`docs/episodic-tui-api-design.md`) covering REST endpoint specifications,
  WebSocket message schemas, authentication contract, error and pagination
  conventions, and hexagonal architecture alignment for all TUI-facing API
  surfaces. Acceptance criteria: design document approved; OpenAPI
  specification generated from endpoint definitions; AsyncAPI specification
  generated from WebSocket message schemas; contract review completed with TUI
  repository maintainers.
- [ ] 5.2.7. Implement episode REST endpoints
  (`/v1/episodes`, `/v1/episodes/{episode_id}`,
  `/v1/episodes/{episode_id}/tei`, `/v1/episodes/{episode_id}/approval-events`)
  with lifecycle filtering, TEI envelope responses, optimistic version locking
  on TEI updates, and approval event submission. Acceptance criteria: published
  endpoint specification; create, get, list, and patch operations validated;
  TEI fetch returns versioned envelope with content hash; approval events
  preserve audit trail; pagination and error contracts consistent with existing
  canonical endpoints; hexagonal boundary tests passing. Dependencies: 2.2.1
  relational schema; 5.2.2 approval state machine. Scope: API and repository
  behaviour only.
- [ ] 5.2.8. Implement ingestion job and source REST endpoints
  (`/v1/ingestion-jobs`, `/v1/ingestion-jobs/{job_id}`,
  `/v1/ingestion-jobs/{job_id}/sources`) with series-scoped filtering,
  upload-reference or URI-based source attachment, and job status polling.
  Acceptance criteria: published endpoint specification; create, get, list, and
  source-attach operations validated; job status reflects ingestion service
  state; pagination and error contracts consistent with existing canonical
  endpoints; hexagonal boundary tests passing. Dependencies: 2.2.4 ingestion
  service; 5.2.9 upload endpoints. Scope: API and repository behaviour only.
- [ ] 5.2.9. Define `UploadPort` and implement file upload endpoints
  (`/v1/uploads`, `/v1/uploads/init`) supporting both direct multipart upload
  and pre-signed object storage flows. Acceptance criteria: multipart POST
  returns upload identifier and content hash; init POST returns pre-signed PUT
  URL for direct-to-storage upload; content-type allowlist enforced; maximum
  file size validated; hexagonal boundary tests passing. Dependencies: object
  storage infrastructure. Scope: domain model, port, adapter, and endpoint
  implementation.
- [ ] 5.2.10. Define `RunEventBusPort` and implement WebSocket event
  streaming via Falcon-Pachinko (`/ws/runs/{run_id}`) with `msgspec`
  tagged-union message dispatch, room-based broadcast keyed by `run_id`, and
  `client.hello` authentication. Acceptance criteria: published AsyncAPI
  specification; `client.hello`, `run.subscribe`, `run.ack`, and
  `checkpoint.submit` client messages handled; `server.welcome`, `run.event`,
  `run.checkpoint`, `run.complete`, and `server.error` server messages sent;
  authentication timeout enforced; hexagonal boundary tests passing.
  Dependencies: 3.2.15 generation-run domain model; Falcon-Pachinko router and
  connection manager. Scope: WebSocket resource, port, adapter, and schema
  implementation.
- [ ] 5.2.11. Implement WebSocket backpressure and reconnection
  semantics: acknowledgement-gated outbound buffering with bounded ring buffer
  per run subscription, event compaction for high-frequency events under
  acknowledgement lag, and sequence-based replay on reconnection with REST
  fallback when buffer is exhausted. Acceptance criteria: `run.ack` advances
  buffer cursor; backpressure close code (4000) sent when client falls behind;
  `resume_from` in `client.hello` replays buffered events; `resume_unavailable`
  error directs client to REST event log; integration tests covering
  reconnection scenarios. Dependencies: 5.2.10 WebSocket streaming. Scope:
  WebSocket resource and connection manager behaviour.
- [ ] 5.2.12. Introduce `/v1` API version prefix for all new TUI-facing
  endpoints while preserving existing unversioned routes during the transition
  period. Acceptance criteria: all new endpoints accessible under `/v1`;
  existing unversioned endpoints continue to function; version routing
  documented in the developers' guide. Dependencies: existing Falcon app
  wiring. Scope: routing configuration only.

### 5.3. Exit criteria

- [ ] 5.3.1. Editorial teams complete end-to-end approvals via API, CLI, and
  web console.
- [ ] 5.3.2. Audit trails capture every approval transition with user identity
  and timestamp.
- [ ] 5.3.3. All TUI-facing REST endpoints are accessible under the `/v1`
  prefix with consistent pagination, error contracts, optimistic concurrency,
  and idempotency-key support.
- [ ] 5.3.4. WebSocket event streaming delivers realtime generation and audio
  run events with backpressure control, sequence-based reconnection, and REST
  fallback for event log retrieval.
- [ ] 5.3.5. OpenAPI and AsyncAPI specifications are published and validated
  against the implemented endpoints and message schemas.

## 6. Security, compliance, and operations

### 6.1. Objectives

- [ ] 6.1.1. Harden the platform and automate ongoing operations.

### 6.2. Key activities

- [ ] 6.2.1. Implement fine-grained RBAC, tenancy isolation, and secrets
  rotation across all services.
- [ ] 6.2.2. Add runtime security scanning, dependency auditing, and
  policy-as-code enforcement inside CI/CD.
- [ ] 6.2.3. Roll out GitOps-driven disaster recovery drills, backup
  verification, and incident runbooks.
- [ ] 6.2.4. Expand observability with synthetic monitoring and
  customer-facing SLIs/SLAs.
- [ ] 6.2.5. Certify compliance checkpoints (SOC 2 readiness, GDPR DPIA) and
  integrate automated evidence collection.
- [ ] 6.2.6. Implement budget enforcement services with per-user and
  per-organization caps, including alerting on budget overruns.
- [ ] 6.2.7. Deliver cost dashboards showing token usage, per-task spend, and
  budget breach trends for operators.

### 6.3. Exit criteria

- [ ] 6.3.1. Security posture reviewed quarterly with no critical findings
  outstanding.
- [ ] 6.3.2. Automated operations dashboards report green for deployment,
  backups, and latency SLOs.
- [ ] 6.3.3. Cost dashboards report per-organization spend, and budget breach
  alerts are routed to on-call responders.
