# ADR-017: No-QA generation execution and TEI persistence

## Status

Accepted for roadmap item `4.3.2`.

## Context

ADR 009 defines the source-to-script REST vertical slice. Its second task must
turn a ready ingestion job into a durable generation run, execute one draft
without the full quality-assurance (QA) graph, persist validated Text Encoding
Initiative (TEI) P5, and expose polling and download resources.

The broader Celery and LangGraph execution model is not yet ready to own this
slice. The first implementation still needs explicit lifecycle ownership,
recovery hooks, optimistic TEI updates, stable failures, and an upgrade path to
the later iterative workflow.

## Decision

Introduce `GenerationRunLauncher` as the scheduling port and implement
`InProcessGenerationRunLauncher` in the API process. The launcher is a
degenerate task-resume adapter: it accepts a run identifier, claims the pending
run conditionally, opens fresh units of work for background writes, and records
ordered lifecycle events. It bounds concurrency and keeps strong task
references so shutdown can drain or cancel scheduled work. Celery dispatch is
deferred until the worker boundary owns generation-run execution.

The launcher resolves bound host and guest reference-document revisions for the
episode's series and supplies them, together with ingestion sources, to the
`DraftScriptGenerator` port. `LLMDraftScriptGenerator` is the single-pass
implementation. Roadmap item `4.4.1` may replace its one-pass policy with the
full duration-aware and QA-gated graph without changing the run or launcher
ports.

Before a run is created, `materialise_episode_from_ingestion` creates the
canonical episode using the ready ingestion job as both source bundle and
stable episode identifier. Generated TEI is validated before persistence.
Episode updates increment `tei_revision`, retain the writing run identifier,
quality mode, QA status, and content hash, and use optimistic revision checks
to reject concurrent writers.

The first deployment assumes one API worker owns an in-process run. Durable
schema fields record conditional pending-to-running claims, `started_at`,
`lease_expires_at`, and terminal error categories; SQL claim outcomes are also
logged. Lease fields support inspection only: operators may manually mark an
expired run failed, while automatic lease recovery and reassignment remain
roadmap item `2.6.2`.

Admission is bounded before task allocation. The launcher admits at most
`max_concurrency + max_pending_runs` runs (currently four active and sixteen
additional pending by default). When that capacity is exhausted, the API
records a terminal `launcher.overloaded` failure on the already-created run and
returns `503 Service Unavailable`. Shutdown closes admission before it cancels
and drains the strong task registry, so no new work can race with teardown.

Shutdown is serialized across the process boundaries: the launcher is shut down
first, the LLM provider client is closed second, and the database engine is
disposed last. A cancelled task shields its terminal failure write, allowing
the run to receive `run.failed` with `launcher.shutdown` before the database
becomes unavailable. After draining, the launcher applies the same failure
write for tasks cancelled before `_run_task` begins; terminal guards prevent a
duplicate event when cancellation was already handled. A process restart still
loses the in-memory task registry; lease fields support inspection and the
documented privileged manual-failure procedure only. This slice deliberately
provides no automatic reaper, retry, or reassignment of expired runs.

The API command and launcher execution are traced as separate spans. The SQL
store logs claim outcomes, and the test tracer remains injectable through the
same port. Production-wide metrics, lease/recovery metrics, and retry metrics
remain follow-up work; stable failure categories still make persisted outcomes
searchable without putting run identifiers into metric labels.

Each generation run has an authenticated principal owner. Production runtime
configuration requires a bearer credential and principal identifier, and the
API derives the persisted run actor from that trusted principal rather than the
request body. Resource reads authorize against that owner and use the same
not-found response for absent and inaccessible runs, events, ingestion jobs,
and generated TEI.

The claim transaction commits the conditional status transition and
`run.started` event before a fresh read unit of work loads the episode,
source-document metadata, and presenter bindings. That unit of work closes
before upload content is hydrated. The launcher then hydrates bounded source
content from object storage outside the database unit of work, so potentially
slow object-store I/O neither retains the claim lock nor monopolizes a database
connection. The source limits bound count, each uploaded stream, aggregate
input, and normalized text; an overflow produces the stable
`generation.source_limit` terminal category without retaining or emitting
source content.

Generation-run creation accepts only `quality_mode=draft_without_qa` in this
slice. A recognized `qa_gated` request returns `422 Unprocessable Entity`;
malformed or missing required fields return `400 Bad Request`. Episode TEI
returns `404 Not Found` until a generated draft and its provenance metadata
exist.

`GET /v1/episodes/{episode_id}/tei` uses HTTP content negotiation rather than a
separate export resource. The default representation is a JSON envelope.
`Accept: application/tei+xml` returns raw XML with `Content-Disposition`,
`ETag`, and the TEI media type. JSON and XML have representation-specific
ETags; a matching `If-None-Match` returns `304 Not Modified` without a body.
Unsupported media types return `406 Not Acceptable`.

## Consequences

### Positive

- Clients can create, replay, poll, and diagnose durable generation runs.
- The process-local launcher is replaceable without changing HTTP or domain
  contracts.
- Presenter profiles and ingestion sources reach the generator through
  canonical ports rather than transport data.
- Optimistic TEI revisioning prevents silent concurrent overwrites.
- Raw TEI download does not depend on audio or export-job infrastructure.

### Negative

- In-process work is not shared across API replicas and cannot survive process
  loss. Deploy this slice with one owning worker until Celery dispatch lands.
- Automatic stuck-run recovery is not included; operators must use lease,
  status, and event evidence for manual intervention.
- Episode materialization currently reuses the ingestion-job identifier, which
  couples the first generation route to the intake bundle identity.
- No-QA output is explicitly a draft and must not be represented as approved.

## References

- [ADR 007: Durable generation checkpoints](adr-007-durable-generation-checkpoints.md)
- [ADR 009: Source-to-script REST vertical slice](adr-009-source-to-script-rest-vertical-slice.md)
- [ADR 015: Upload and idempotency ports](adr-015-upload-and-idempotency-ports.md)
- [Episodic podcast generation system design](../episodic-podcast-generation-system-design.md)
