# Episodic Podcast Generation System Design

## Overview

The episodic podcast generation platform automates the production of scripted,
branded audio shows. It ingests heterogeneous source documents, synthesises
canonical TEI content, applies layered quality assurance, and renders broadcast
quality audio with background music before exposing approvals and delivery
channels.

## Goals

- Maintain a canonical, auditable TEI corpus for each series and episode.
- Enable configurable generation that respects show templates and brand tone.
- Provide multi-stage human-in-the-loop approvals with clear accountability.
- Deliver mastered audio assets together with previews and machine-readable
  metadata.
- Operate on cloud-native infrastructure with automation, observability, and
  compliance controls.

## Non-Goals

- Building a generic content management system outside the podcast domain.
- Supporting real-time streaming or live recording use cases.
- Implementing on-premises deployments beyond documented infrastructure
  blueprints.

## Personas and Actors

- **Editorial producers** curate source material, trigger generation, and
  approve episodes.
- **Compliance reviewers** verify brand and regulatory adherence.
- **Audio engineers** tune voice configurations, music beds, and stem mixes.
- **Developers and operators** maintain services, pipelines, and infrastructure.
- **Integration clients** consume the API, CLI, or web console to orchestrate
  workflows programmatically.

## Architectural Summary

The system follows a hexagonal architecture: domain services expose ports, and
adapters integrate external capabilities such as LLMs, TTS vendors, and
storage. Services communicate through asynchronous events (Kafka) and
synchronous gRPC or REST calls. Persistent state lives in Postgres with Alembic
migrations. Object storage holds binary assets. GitOps drives deployments into
Kubernetes across sandbox, staging, and production environments.

## Technology Choices

### LangGraph for Agentic Feedback Loops

LangGraph has been selected as the framework for implementing agentic feedback
loops throughout the content generation and audio synthesis workflows. This
decision enables:

- **State-driven iterative refinement**: Agent graphs maintain state across
  generation cycles, incorporating QA findings, brand compliance scores, and
  editorial feedback to progressively improve script quality.
- **Contextual audio optimisation**: Audio synthesis agents learn from previous
  renders, adjusting mixing parameters, voice characteristics, and music
  selection based on content type and producer approvals.
- **Observable decision pathways**: LangGraph's state graph structure provides
  clear audit trails showing how content evolved through each iteration and
  which factors influenced final decisions.
- **Scalable multi-agent coordination**: Separate agent graphs can handle
  different aspects (narrative flow, technical audio quality, brand compliance)
  while sharing state and converging on optimal outcomes.

The framework's integration with existing LLM adapters through LangChain
provides seamless extensibility while maintaining the hexagonal architecture
principles through dedicated agent ports.

## Component Responsibilities

### Canonical Content Platform

- Defines TEI-based domain entities for episodes, series profiles, and
  templates.
- Hosts the Postgres schema, repositories, and unit-of-work abstractions.
- Generates TEI header provenance automatically, including ingested sources,
  weighting decisions, and reviewer metadata.

### Multi-source Ingestion Service

- Accepts RSS feeds, briefs, transcripts, press releases, and research notes.
- Applies document classifiers, quality scores, and weighting heuristics to
  establish priority when sources conflict.
- Normalises inputs into TEI fragments, merging them into canonical episodes
  while recording provenance and retaining source attachments.
- Exposes ingestion job status via API endpoints and emits events for downstream
  processing.

### Series Profile and Template Service

- Stores show-level configuration: tone descriptors, recurring segments, and
  sponsor requirements.
- Manages episode templates describing segment ordering, timing, and audio bed
  preferences.
- Provides change history and optimistic locking so editorial teams can iterate
  safely.
- Supplies templated prompts and metadata to generation and audio pipelines.

### Content Generation Orchestrator

- Coordinates `LLMPort` adapters with retry discipline, token budgeting, and
  guardrails per template.
- Employs LangGraph-based agentic feedback loops for iterative script refinement,
  integrating QA scores, brand guideline adherence, and narrative flow metrics.
- Produces structured drafts, show notes, chapter markers, and sponsorship copy.
- Persists generation runs alongside prompts, responses, and cost telemetry.
- Surfaces retryable failure modes and exposes override hooks for human edits.
- Maintains agent state graphs tracking revision history, quality improvements,
  and convergence criteria across generation cycles.

### Quality Assurance Stack

- Bromide evaluates factual accuracy, voice consistency, and bias mitigation.
- Chiltern rates narrative flow, pacing, and call-to-action placement.
- Brand guideline checks enforce vocabulary, tone, and forbidden topic rules.
- QA results drive automated gating and raise review tasks when thresholds fail.

### Editorial Approval Service

- Implements the configurable approval state machine with stage SLAs.
- Logs reviewer decisions, comments, and attachments per transition.
- Issues notifications via email, Slack, and webhooks to keep stakeholders
  informed.
- Integrates with the CLI and web console so approvals can be performed
  consistently across surfaces.

### Audio Synthesis Pipeline

- Uses `TTSPort` to request narration voiceovers with persona controls and
  resilience to latency, quota, and failure scenarios.
- Employs LangGraph agents to optimise audio synthesis parameters based on
  content type, voice characteristics, and quality metrics from previous
  renders.
- Constructs timelines combining narration, background music, and sound effect
  stems drawn from managed catalogues.
- Executes automated mixing: ducking, crossfades, EQ presets, and loudness
  normalisation to -16 LUFS +/- 1 LU.
- Utilises agentic feedback loops to learn optimal mixing parameters, music
  bed selection criteria, and timing adjustments from producer approvals
  and listener analytics.
- Publishes previews through `PreviewPublisherPort` and delivers masters to CDN
  storage with chapter metadata embedded.

### Client Experience Layer

- REST and GraphQL APIs expose domain resources with RBAC enforcement.
- CLI client provides ergonomics for ingest, generate, QA review, and approval
  commands.
- Web console surfaces dashboards, approval queues, and configuration editors.

### Observability and Operations Platform

- Collects structured logs, metrics, and traces (Grafana, Loki, Tempo, and
  OpenTelemetry).
- Defines SLIs for ingestion latency, generation success, audio throughput, and
  approval turnaround.
- Automates rollbacks, blue/green deployments, and incident response runbooks.

### Security and Compliance Controls

- Enforces fine-grained RBAC, tenancy isolation, and audited secret rotations.
- Performs dependency and container scanning in CI, plus runtime policy checks.
- Tracks GDPR data processing records and supports SOC 2 evidence collection.

## Data Model and Storage

- `series_profiles` captures show metadata, tone attributes, default voices, and
  sponsor obligations.
- `episode_templates` stores segment layouts, prompt scaffolds, and music bed
  preferences linked to series profiles.
- `source_documents` records ingestion jobs, document types, weighting factors,
  and original files in object storage.
- `episodes` holds canonical TEI, generation status, QA verdicts, and approval
  pointers.
- `qa_findings` and `brand_compliance_results` record scores, rule breaches, and
  remediation guidance.
- `approval_events` maintains the approval state machine history with actor and
  timestamp.
- Alembic migrations version schema changes; migrations run in CI and during
  deployments to guarantee consistency.

## Core Workflows

### Multi-source Ingestion and Prioritisation

1. Producer submits new sources through the API or scheduled connectors.
2. Ingestion service classifies documents, computes freshness and reliability
   scores, and applies weighting heuristics defined per series.
3. Conflicts resolve using the weighting matrix; rejected content is retained
   for audit.
4. Normalised TEI fragments merge into the canonical episode; provenance is
   logged and downstream events trigger generation.

### Episode Generation and Enrichment

1. Orchestrator loads the latest series profile and episode template to derive
   prompt scaffolds.
2. LangGraph agents coordinate `LLMPort` adapters, invoking selected models
   while maintaining state graphs for iterative refinement.
3. Generated artefacts persist alongside confidence scores and content hashes;
   agent states track revision history and improvement metrics.
4. Agents analyse preliminary QA findings to trigger targeted regeneration
   cycles, focusing on identified weaknesses in narrative flow or brand compliance.
5. Convergence criteria determine when content meets quality thresholds;
   divergent cases escalate to human editors with detailed agent decision logs.
6. Editors receive drafts in the console or CLI for optional redlines before
   final QA approval.

### QA, Compliance, and Approvals

1. Bromide and Chiltern analyse drafts, producing structured findings and
   severity levels.
2. Brand guideline checks run lexicon scans, sentiment analysis, and sponsor
   requirement validation.
3. Failures create remediation tasks; success transitions the episode into the
   approval state machine.
4. Reviewers complete approvals within SLA windows; every decision emits audit
   events and optional notifications.

### Audio Synthesis and Distribution

1. Approved scripts flow into the audio pipeline, which requests narration from
   the `TTSPort` under guidance from LangGraph audio optimisation agents.
2. Agents analyse script content, previous render metrics, and series profile
   to determine optimal voice parameters, pacing, and emotional tone.
3. Music supervisor rules, enhanced by agent learning, choose background beds
   and stings based on template cues plus historical approval data.
4. Mixer combines narration and stems, applying agent-optimised parameters for
   ducking curves, crossfade timing, and EQ presets learned from producer feedback.
5. Mastering agents verify loudness normalisation targets (-16 LUFS +/- 1 LU)
   and iterate on compression settings when thresholds aren't met.
6. Previews publish via signed URLs; masters replicate to CDN and RSS
   integrations with metadata for chapters and sponsors.
7. Distribution agents monitor listener analytics and feed engagement metrics
   back to optimise future audio synthesis decisions.

### Change Management and Migrations

1. Schema updates originate as Alembic migrations committed with code changes.
2. CI validates migrations against an ephemeral Postgres instance.
3. Deployments apply migrations through GitOps jobs with automated rollback if
   checks fail.

## Operational Considerations

- **Infrastructure:** Kubernetes clusters span sandbox, staging, and production;
  supporting services include Postgres, Redis, and object storage. Terraform
  codifies provisioning and aligns with the Phase 0 roadmap milestone.
- **Deployment:** GitOps (Argo CD) manages environment parity, progressive
  delivery, and secrets injected via SOPS and age.
- **Observability:** Metrics power SLO dashboards; tracing correlates ingestion
  to audio rendering; alerting integrates with Slack and PagerDuty.
- **Resilience:** Services use idempotent operations, retries with backoff, and
  dead-letter queues for failed messages; disaster recovery rehearsals validate
  backups and restore paths.

## Roadmap Alignment

- Phase 0 establishes the infrastructure blueprint described in Operational
  Considerations.
- Phase 1 implements the canonical content platform, ingestion service, and
  series/template storage defined above.
- Phase 2 delivers the content generation orchestrator, QA stack, and brand
  compliance automation.
- Phase 3 realises the audio synthesis pipeline, including music integration and
  preview delivery.
- Phase 4 activates the client experience layer and editorial approval service.
- Phase 5 rounds out security, compliance, and operational automation in line
  with the specified controls.
