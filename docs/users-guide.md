# Episodic User's Guide

Welcome to the Episodic user's guide! This document will help you get started
with creating AI-powered podcasts once the platform is ready.

## 🚧 Current Status

**This guide is under construction.** Episodic is in active early development
(Phase 1 of 6), and most features described here are planned but not yet
implemented.

See [`roadmap.md`](roadmap.md) for the current development status and timeline.

## What You'll Find Here (Eventually)

This guide will cover:

### Getting Started

- Installing and configuring the Episodic CLI
- Starting the Falcon HTTP service through Granian
- Checking `/health/live` and `/health/ready` during deployments
- Setting up your first podcast series
- Creating series profiles and episode templates
- Understanding the workflow from source documents to finished audio

### Content Creation

- Uploading and ingesting source documents
- Working with TEI (Text Encoding Initiative) canonical content
- Tracking ingestion jobs, source weighting decisions, and provenance metadata
- Configuring content weighting and conflict resolution
- Managing episode metadata and show notes. Show-notes generation runs
  automatically as part of the episode-generation pipeline, with no separate
  manual step. A Large Language Model (LLM) analyses the canonical TEI script
  to extract key topics, short summaries, and, where inferable, timestamps and
  source locators. The output is written back into the canonical TEI body as a
  `<div type="notes">` containing one `<item>` per topic, where each item
  carries a `<label>`, inline summary text, and optional `@n` (ISO 8601
  duration timestamp) and `@corresp` (source locator) attributes.
  `ShowNotesGeneratorConfig` controls the model, token budget, and system
  prompt, and an optional `template_structure` mapping can be passed to
  `build_prompt(...)` to guide extraction against a known episode template.
  Current orchestration uses a separate structured-planning pass before the
  show-notes tool runs, so a higher-capability planning model can choose the
  work and a cheaper execution model can generate the note payload. If either
  stage returns malformed structured JSON, the run fails fast with a
  deterministic validation error instead of silently publishing partial
  metadata.
- Database schema integrity is validated automatically in CI so that canonical
  content storage remains consistent across releases
- Repository and transactional integrity are validated by integration tests
  running against a real PostgreSQL engine, covering persistence round-trips,
  rollback behaviour, and constraint enforcement
- Multi-source ingestion normalizes heterogeneous sources (transcripts,
  briefs, Really Simple Syndication (RSS) feeds, press releases, and research
  notes) into canonical TEI episodes. Source weighting heuristics automatically
  compute priority scores based on quality, freshness, and reliability.
  Conflicts between competing sources are resolved using a weighting matrix,
  with all source material retained for audit regardless of whether it was
  preferred or rejected. Weighting coefficients are configurable per series
  profile. TEI headers automatically capture provenance metadata including
  source priorities, ingestion timestamps, and reviewer identities. Source
  normalisation fan-out now uses metadata-aware asyncio task creation, so
  custom event-loop task factories can receive operation metadata
  (`operation_name`, `correlation_id`, `priority_hint`) for diagnostics.
  Storage identifiers generated during canonical ingestion use time-ordered
  UUIDv7 values for improved chronological locality.
- Large canonical TEI XML payloads are compressed with standard-library
  Zstandard in persistence storage while API and domain read paths continue to
  return plain text transparently.
- Creating and updating series profiles via the API with optimistic locking
  (`expected_revision`)
- Creating and updating episode templates linked to series profiles
- Retrieving change history for series profiles and episode templates
- Fetching structured brief payloads for downstream generators through
  `GET /series-profiles/{profile_id}/brief`
- Managing reusable reference documents (including series-aligned host and
  guest profiles) through pinned revision bindings used by structured briefs
- Resolving the exact reference bindings for a target episode through
  `GET /series-profiles/{profile_id}/resolved-bindings`
- Rendering deterministic prompt scaffolds from structured briefs for
  downstream Large Language Model (LLM) adapters, including interpolation audit
  metadata and optional escaping policies
- Persisting `guardrails` on series profiles and episode templates so
  generation requests carry stable editorial instructions as system prompts

### Reusable Reference Documents

Reusable reference-document workflows currently support:

- Creating and listing reusable documents per series profile at
  `POST /series-profiles/{profile_id}/reference-documents` and
  `GET /series-profiles/{profile_id}/reference-documents`.
- Updating reusable documents with optimistic locking using
  `expected_lock_version` at
  `PATCH /series-profiles/{profile_id}/reference-documents/{document_id}`.
  Stale updates return `409 Conflict`.
- Creating and listing immutable document revisions at
  `POST /series-profiles/{profile_id}/reference-documents/{document_id}/revisions`
   and
  `GET /series-profiles/{profile_id}/reference-documents/{document_id}/revisions`.
- Creating, listing, and fetching target bindings at `POST /reference-bindings`,
  `GET /reference-bindings`, and `GET /reference-bindings/{binding_id}`.
- Series-aligned access behaviour for host and guest profile documents:
  cross-series profile paths do not expose documents owned by another series.
- Requesting `GET /series-profiles/{profile_id}/brief?episode_id=...` to apply
  `effective_from_episode_id` precedence for series-level bindings while still
  including any selected template bindings. Add optional `template_id=...` to
  restrict the template section selection to one episode template.
- Requesting
  `GET /series-profiles/{profile_id}/resolved-bindings?episode_id=...` to
  inspect the resolved binding, document, and revision payloads for one episode
  context without fetching the full structured brief. Add optional
  `template_id=...` to restrict template-scoped bindings to one episode
  template.
- Ingestion runs snapshot the resolved reusable reference revisions as
  provenance-backed `source_documents`, so audit trails record the exact
  reference revisions consumed for that episode build.

### HTTP service health and runtime

The canonical-content HTTP service now runs as a Falcon ASGI application under
Granian.

Start the service with:

```shell
granian episodic.api.runtime:create_app_from_env --interface asgi --factory
```

Required environment:

- `DATABASE_URL` must point at the canonical Postgres database before the
  service starts. The runtime accepts a plain Postgres URL such as
  `postgresql://...` and normalizes it to the supported async driver
  automatically. Driver-qualified URLs such as `postgresql+asyncpg://...` and
  `postgresql+psycopg://...` are also accepted.

Health endpoints:

- `GET /health/live` reports whether the Falcon application booted
  successfully.
- `GET /health/ready` reports whether the configured infrastructural readiness
  probes are passing. The current probe checks database connectivity.
- `GET /health/ready` returns `503 Service Unavailable` when a readiness probe
  fails, so deployment platforms can keep traffic away from an unhealthy
  instance.

### Worker runtime

The background-worker scaffold now exists for operators who need to stand up
Celery alongside the Falcon service.

Start a CPU-focused worker with:

```shell
celery --app episodic.worker.runtime:create_celery_app_from_env worker --pool prefork --queues episodic.cpu
```

and an I/O-focused worker with:

```shell
celery --app episodic.worker.runtime:create_celery_app_from_env worker --pool gevent --queues episodic.io
```

Required environment:

- `EPISODIC_CELERY_BROKER_URL` must point at RabbitMQ using AMQP.
- `EPISODIC_CELERY_RESULT_BACKEND` is optional for the current scaffold.
- `EPISODIC_CELERY_IO_POOL` and `EPISODIC_CELERY_CPU_POOL` override the
  default pool choices (`gevent` for I/O work and `prefork` for CPU work).
- `EPISODIC_CELERY_IO_CONCURRENCY` controls I/O worker concurrency, and
  `EPISODIC_CELERY_CPU_CONCURRENCY` controls CPU worker concurrency. The
  runtime only applies the documented defaults when these variables are unset,
  so set them explicitly when tuning worker counts.

Optional interpreter-pool flags:

- `EPISODIC_USE_INTERPRETER_POOL=1` enables interpreter-pool execution for
  selected CPU-heavy pure-Python workloads. This is separate from the Celery
  CPU worker's default `prefork` pool and is not consumed by the runtime config
  loader.
- `EPISODIC_INTERPRETER_POOL_MIN_ITEMS` tunes the minimum batch size before
  interpreter-pool dispatch activates.
- `EPISODIC_INTERPRETER_POOL_MAX_WORKERS` caps the interpreter-pool worker
  count when that path is enabled.

Current queue model:

- `episodic.tasks` topic exchange
- `episodic.io` queue for I/O-bound workloads
- `episodic.cpu` queue for CPU-bound workloads

The current scaffold provides representative diagnostic tasks so routing and
runtime wiring can be verified before later roadmap items add workflow-specific
jobs.

### Quality & Compliance

- Setting up brand guidelines and compliance rules
- Configuring multi-layer quality assurance (QA) checks
- Generated scripts now pass through the internal Pedante factuality evaluator
  before editorial approval. Pedante inspects claim-level support against the
  canonical TEI script and cited source packets, then records structured
  findings for unsupported claims and likely inaccuracies together with
  normalized usage metrics for cost accounting.
- Pedante currently operates as an internal authoring-loop check rather than a
  public API feature. Its outputs are therefore visible in internal workflows
  first, with broader generation-run and QA artefact APIs planned in later
  roadmap items.
- Using the editorial approval workflow
- Reviewing approval states and audit history for canonical episodes
- Reviewing and approving generated content

### Audio Production

- Selecting voice personas and TTS settings
- Choosing background music and sound effects
- Understanding the mixing and mastering process
- Previewing and downloading final episodes

### Cost Management

- Understanding token usage and metering
- OpenAI adapter payloads are validated with explicit type guards, and malformed
  responses fail with deterministic validation errors before orchestration
  consumes generated content or usage metadata
- OpenAI-compatible generation requests now enforce token budgets before and
  after provider calls, and persisted profile/template `guardrails` shape the
  outbound system prompt used for generation
- Setting budget limits per user or organization
- Monitoring spend and usage dashboards
- Optimizing costs with model tiering

### Advanced Topics

- Customizing LangGraph workflows
- Integrating with external systems via API
- Managing multi-tenant deployments
- Enabling optional interpreter-pool execution for CPU-heavy pure-Python tasks
  by setting `EPISODIC_USE_INTERPRETER_POOL=1`. This is separate from the
  Celery CPU worker's default `prefork` pool and is intended for selected
  pure-Python workloads inside repository adapters. Tune dispatch thresholds
  with `EPISODIC_INTERPRETER_POOL_MIN_ITEMS` and worker count with
  `EPISODIC_INTERPRETER_POOL_MAX_WORKERS`.
- Troubleshooting common issues

## In the Meantime

While we're building out the platform, you can:

1. **Explore the architecture**: Read
   [`episodic-podcast-generation-system-design.md`](episodic-podcast-generation-system-design.md)
    to understand how Episodic works under the hood.

2. **Check the roadmap**: See [`roadmap.md`](roadmap.md) to track development
   progress and see what's coming next.

3. **Review the infrastructure**: Learn about the Kubernetes-based deployment in
   [`infrastructure-design.md`](infrastructure-design.md).

4. **Contribute**: If you're interested in contributing, check out
   [`../AGENTS.md`](../AGENTS.md) for guidelines and code quality standards.

## Questions or Feedback?

This project is developed by **df12 Productions**. Visit
[https://df12.studio](https://df12.studio) for more information.

______________________________________________________________________

_This guide will be updated as features are implemented. Check back regularly
for the latest information!_
