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
- [x] 2.2.2. Introduce migration tooling with Alembic, wired into CI to block
  divergent schemas.
- [ ] 2.2.3. Implement the repository and unit-of-work layers over Postgres with
  integration tests.
- [ ] 2.2.4. Build the multi-source ingestion service that normalises inputs,
  applies source weighting heuristics, and resolves conflicts into canonical
  TEI.
- [ ] 2.2.5. Capture provenance metadata automatically in TEI headers,
  including source priorities, ingestion timestamps, and reviewer identities.
- [ ] 2.2.6. Define series profile and episode template models, REST endpoints,
  and change history so downstream generators can retrieve structured briefs.

### 2.3. Exit criteria

- [ ] 2.3.1. Canonical TEI documents persist with full provenance after
  ingesting at least three heterogeneous source types.
- [ ] 2.3.2. Series profiles and episode templates retrievable via the public
  API with optimistic locking and history tracking.

## 3. Intelligent content generation and QA

### 3.1. Objectives

- [ ] 3.1.1. Orchestrate LLM-based draft generation, enrichment, and
  multi-layer review.
- [ ] 3.1.2. Automate compliance checks against brand and regulatory guidance.

### 3.2. Key activities

- [ ] 3.2.1. Implement the `LLMPort` adapter with retry, token budgeting, and
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
- [ ] 4.2.4. Enforce loudness normalisation to -16 LUFS +/- 1 LU and peak
  limiting across stereo channels.
- [ ] 4.2.5. Generate shareable previews via the `PreviewPublisherPort`,
  storing artefacts in object storage with signed URLs.
- [ ] 4.2.6. Publish final masters to CDN endpoints and optional RSS feeds.

### 4.3. Exit criteria

- [ ] 4.3.1. End-to-end render produces master files with embedded chapter
  markers and balanced stems for flagship shows.
- [ ] 4.3.2. QA automation rejects mixes that violate loudness or clipping
  thresholds.

## 5. Client and interface experience

### 5.1. Objectives

- [ ] 5.1.1. Deliver API-first access backed by approval workflows and client
  tooling.
- [ ] 5.1.2. Enable editorial collaboration and notifications.

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

### 5.3. Exit criteria

- [ ] 5.3.1. Editorial teams complete end-to-end approvals via API, CLI, and
  web console.
- [ ] 5.3.2. Audit trails capture every approval transition with user identity
  and timestamp.

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
