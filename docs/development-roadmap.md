# Development Roadmap

This roadmap sequences the work to deliver the episodic podcast generation
platform. Each phase represents a deployable increment with clear exit criteria
that align with the system design. Dates are placeholders; refine when team
capacity is known.

## Phase 0 - Platform Foundations

### Phase 0 Objectives

- Provision shared infrastructure required by all later phases.
- Establish continuous delivery pipelines and baseline observability.

### Phase 0 Key Activities

- Bootstrap the Kubernetes control plane, Postgres cluster, Redis cache, and
  object storage buckets for audio assets.
- Configure secret management (SOPS + age) and environment promotion strategy.
- Create the GitOps repository, Argo CD projects, and deployment templates for
  core services.
- Instrument clusterwide logging, metrics, and tracing with Grafana, Loki, and
  Tempo; define alert routing rules.
- Document access controls, networking policies, and disaster recovery
  expectations.

### Phase 0 Exit Criteria

- Sandbox environment accepts deployments for the `ingestion`, `orchestrator`,
  and `audio` services via GitOps.
- Platform runbook published covering provisioning, credentials, and restore
  procedures.

## Phase 1 - Canonical Content Foundation

### Phase 1 Objectives

- Land the TEI-oriented domain model and ingestion stack.
- Persist canonical artefacts with auditable provenance.

### Phase 1 Key Activities

- Design the relational schema covering TEI headers, canonical episodes,
  ingestion jobs, source documents, series profiles, and approval states.
- Introduce migration tooling with Alembic, wired into CI to block divergent
  schemas.
- Implement the repository and unit-of-work layers over Postgres with
  integration tests.
- Build the multi-source ingestion service that normalises inputs, applies
  source weighting heuristics, and resolves conflicts into canonical TEI.
- Capture provenance metadata automatically in TEI headers, including source
  priorities, ingestion timestamps, and reviewer identities.
- Define series profile and episode template models, REST endpoints, and change
  history so downstream generators can retrieve structured briefs.

### Phase 1 Exit Criteria

- Canonical TEI documents persist with full provenance after ingesting at least
  three heterogeneous source types.
- Series profiles and episode templates retrievable via the public API with
  optimistic locking and history tracking.

## Phase 2 - Intelligent Content Generation and QA

### Phase 2 Objectives

- Orchestrate LLM-based draft generation, enrichment, and multi-layer review.
- Automate compliance checks against brand and regulatory guidance.

### Phase 2 Key Activities

- Implement the `LLMPort` adapter with retry, token budgeting, and guardrail
  prompts aligned to content templates.
- Extend Bromide and Chiltern services to score factuality, tone, and style,
  emitting structured findings.
- Add automated brand-guideline evaluation: lint textual output, validate tone,
  vocabulary, and forbidden topics, and record pass/fail outcomes.
- Enrich TEI bodies with show notes, chapter markers, guest bios, and sponsor
  reads sourced from template expansions.
- Persist QA artefacts, including review comments, rubric scores, and
  compliance results, linked to the canonical episode.
- Expose generation and QA state via the API and CLI, including filtering by
  brand compliance status.

### Phase 2 Exit Criteria

- Generated scripts achieve defined Bromide/Chiltern thresholds and pass brand
  guideline checks before entering approval.
- QA dashboards surface per-episode compliance, reviewer comments, and ageing
  tasks.

## Phase 3 - Audio Synthesis and Delivery

### Phase 3 Objectives

- Produce production-ready audio with narration, music, and compliance-checked
  levels.
- Provide reliable preview and delivery workflows.

### Phase 3 Key Activities

- Implement the `TTSPort` adapter with configurable voice personas and retry
  semantics.
- Integrate background music and sound effect stems: manage asset catalogues,
  select beds per template, and schedule mixes relative to script beats.
- Build the mixing engine to combine narration and stems, applying ducking,
  fades, and scene transitions.
- Enforce loudness normalisation to -16 LUFS +/- 1 LU and peak limiting across
  stereo channels.
- Generate shareable previews via the `PreviewPublisherPort`, storing artefacts
  in object storage with signed URLs.
- Publish final masters to CDN endpoints and optional RSS feeds.

### Phase 3 Exit Criteria

- End-to-end render produces master files with embedded chapter markers and
  balanced stems for flagship shows.
- QA automation rejects mixes that violate loudness or clipping thresholds.

## Phase 4 - Client and Interface Experience

### Phase 4 Objectives

- Deliver API-first access backed by approval workflows and client tooling.
- Enable editorial collaboration and notifications.

### Phase 4 Key Activities

- Finalise REST and GraphQL surfaces, including pagination, filtering, and role
  enforcement for all previous phase artefacts.
- Implement the editorial approval state machine with configurable stages,
  SLA timers, and audit logging.
- Integrate notification channels (email, Slack, webhook) for approvals,
  rejections, and automated compliance alerts.
- Extend the CLI client to support approval actions, diff viewing, and audio
  preview downloads.
- Ship the initial web console for managing series profiles, templates, and
  approval queues.

### Phase 4 Exit Criteria

- Editorial teams complete end-to-end approvals via API, CLI, and web console.
- Audit trails capture every approval transition with user identity and
  timestamp.

## Phase 5 - Security, Compliance, and Operations

### Phase 5 Objectives

- Harden the platform and automate ongoing operations.

### Phase 5 Key Activities

- Implement fine-grained RBAC, tenancy isolation, and secrets rotation across
  all services.
- Add runtime security scanning, dependency auditing, and policy-as-code
  enforcement inside CI/CD.
- Roll out GitOps-driven disaster recovery drills, backup verification, and
  incident runbooks.
- Expand observability with synthetic monitoring and customer-facing SLIs/SLAs.
- Certify compliance checkpoints (SOC 2 readiness, GDPR DPIA) and integrate
  automated evidence collection.

### Phase 5 Exit Criteria

- Security posture reviewed quarterly with no critical findings outstanding.
- Automated operations dashboards report green for deployment, backups, and
  latency SLOs.
