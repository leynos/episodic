# ADR-016: No-QA generation execution and TEI persistence

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
degenerate task-resume adapter: it accepts a run identifier, claims the
pending run conditionally, opens fresh units of work for background writes,
and records ordered lifecycle events. It bounds concurrency and keeps strong
task references so shutdown can drain or cancel scheduled work. Celery
dispatch is deferred until the worker boundary owns generation-run execution.

The launcher resolves bound host and guest reference-document revisions for
the episode's series and supplies them, together with ingestion sources, to the
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
schema hooks make this limitation observable: conditional pending-to-running
claims, `started_at`, `lease_expires_at`, terminal error category, and a
stuck-run gauge. Operators may inspect expired leases and manually mark a run
failed; automatic recovery and reassignment remain roadmap item `2.6.2`.

Generation-run creation accepts only `quality_mode=draft_without_qa` in this
slice. A recognized `qa_gated` request returns `422 Unprocessable Entity`;
malformed or missing required fields return `400 Bad Request`. Episode TEI
returns `404 Not Found` until a generated draft and its provenance metadata
exist.

`GET /v1/episodes/{episode_id}/tei` uses HTTP content negotiation rather than
a separate export resource. The default representation is a JSON envelope.
`Accept: application/tei+xml` returns raw XML with `Content-Disposition`,
`ETag`, and the TEI media type. Unsupported media types return `406 Not
Acceptable`.

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
- Automatic stuck-run recovery is not included; operators must use lease and
  metric evidence for manual intervention.
- Episode materialization currently reuses the ingestion-job identifier, which
  couples the first generation route to the intake bundle identity.
- No-QA output is explicitly a draft and must not be represented as approved.

## References

- [ADR 007: Durable generation checkpoints](adr-007-durable-generation-checkpoints.md)
- [ADR 009: Source-to-script REST vertical slice](adr-009-source-to-script-rest-vertical-slice.md)
- [ADR 015: Upload and idempotency ports](adr-015-upload-and-idempotency-ports.md)
- [Episodic podcast generation system design](../episodic-podcast-generation-system-design.md)
