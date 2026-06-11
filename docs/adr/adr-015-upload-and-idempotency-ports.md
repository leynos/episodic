# ADR-015: Upload and idempotency ports

## Status

Accepted for roadmap item `4.3.1`.

## Context

ADR 009 defines the source-to-script REST vertical slice. The first delivery
task needs a small intake path before generation exists: clients upload a
source document, create an ingestion job, attach the uploaded or URI-backed
source, and bind presenter profiles through existing reusable reference
documents.

The implementation must preserve the hexagonal boundary in ADR 014. Upload
bytes and retryable `POST` requests are side effects, so the domain layer needs
ports for object storage and idempotency without importing Falcon, SQLAlchemy,
or any cloud provider Software Development Kit (SDK).

## Decision

Introduce two driven ports under `episodic.canonical.*`:

- `ObjectStorePort` stores opaque byte streams by server-generated keys. The
  first adapter is a local filesystem adapter. Client filenames never become
  storage paths, and the port rejects absolute paths, leading slashes, and `..`
  components before an adapter touches the filesystem.
- `IdempotencyStore` records retryable side-effecting `POST` requests by
  `(principal_id, operation, idempotency_key)`, where `operation` is a stable
  adapter-defined domain operation string such as `upload.create` or
  `ingestion_job.create`. The backing SQL table enforces that tuple with a
  unique constraint. `acquire` returns one of the domain-only outcomes
  `Acquired(record_id: UUID)`, `Replay(serialised_outcome: bytes)`,
  `Conflict(record_id: UUID)`, or `InFlight(record_id: UUID)`. `complete`
  accepts `(record_id: UUID, serialised_outcome: bytes)` and stores only the
  opaque bytes and expiry timestamp. The HTTP adapter is responsible for
  serialising status, body, and headers before completion and deserialising
  them when replaying.

The intake slice also introduces:

- `Upload`, a metadata record for uploaded bytes.
- `IngestionJobSource`, a pre-generation source attachment that references
  either an upload or a remote source Uniform Resource Identifier (URI).
- `IdempotencyRecord`, the stored request hash and opaque replay payload. Its
  domain fields are `id`, `principal_id`, `operation`, `idempotency_key`,
  `body_hash`, `state`, `serialised_outcome: bytes | None`, `expires_at`,
  `created_at`, and `updated_at`. The adapter layer selects the codec used for
  `serialised_outcome`.
- `IngestionJob.intake_state`, an orthogonal state for REST intake progress.

The `idempotency_records` table stores the same domain vocabulary:

```sql
CREATE TABLE idempotency_records (
  id UUID PRIMARY KEY,
  principal_id TEXT,
  operation TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  body_hash TEXT NOT NULL,
  state TEXT NOT NULL,
  serialised_outcome BYTEA,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  UNIQUE (principal_id, operation, idempotency_key)
);
```

The existing `SourceDocument` entity remains post-merge provenance. Reusing it
for pre-generation attachment would mix the queue of proposed inputs with the
canonical episode provenance that ingestion creates after merging.

`POST /v1/uploads` is the only upload creation route in this slice.
`POST /v1/uploads/init` and `PUT /v1/uploads/{upload_id}/bytes` are deferred
until an S3-compatible or resumable upload adapter has a concrete consumer.

## Request hashes

JSON request hashes use canonical UTF-8 JSON with stable key ordering and no
insignificant whitespace. Multipart upload hashes are derived from the streamed
body hash and the metadata fields that affect the created upload.

For `POST /v1/uploads`, the metadata allowlist is:

```plaintext
content_type
declared_sha256
declared_size
```

The worked vector below is normative for tests. With body bytes `hello\n`,
`body_sha256` is:

```plaintext
5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03
```

With metadata:

```json
{"content_type":"text/plain","declared_sha256":null,"declared_size":6}
```

the canonical metadata bytes are exactly:

```plaintext
{"content_type":"text/plain","declared_sha256":null,"declared_size":6}
```

The multipart request fingerprint is SHA-256 over:

```plaintext
5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03:{"content_type":"text/plain","declared_sha256":null,"declared_size":6}
```

which yields:

```plaintext
sha256:f03f8d4c738536bcd1c13cc34d6816f8ea0672c3e2d47c2cbbaf5c8ecbda5e2c
```

## Observability contract

The intake adapters must emit metrics, traces, and structured logs at the
storage and idempotency boundaries. Metrics use bounded-cardinality labels
only; do not label metrics with upload ids, idempotency keys, object-store
keys, filenames, source URIs, document hashes, or principal ids.

Required metrics:

- `source_intake_upload_requests_total{operation,outcome,content_type_family}`:
  counter for upload requests. `content_type_family` is one of `pdf`, `docx`,
  `text`, `markdown`, `html`, or `other`.
- `source_intake_upload_duration_seconds{operation,outcome}`: histogram covering
  request receipt through upload row persistence.
- `source_intake_upload_bytes{content_type_family,outcome}`: histogram of
  accepted and rejected upload byte counts.
- `source_intake_upload_errors_total{operation,error_code}`: counter for
  documented intake error-code outcomes.
- `source_intake_object_store_operations_total{operation,outcome,error_class}`:
  counter for object-store `put`, `open`, and `delete` operations. The
  `error_class` label is a stable adapter-defined category such as `permission`,
  `not_found`, `io`, or `none`.
- `source_intake_object_store_operation_duration_seconds{operation,outcome}`:
  histogram around each storage-port call.
- `source_intake_idempotency_outcomes_total{operation,outcome}`: counter for
  `acquired`, `replay`, `conflict`, `in_flight`, and `complete_failed`.
- `source_intake_orphan_uploads_total{state}` and
  `source_intake_stuck_idempotency_records_total{state}`: counters incremented
  by manual or automated recovery sweeps.
- `source_intake_stream_errors_total{operation,error_class}`: counter for failed
  multipart reads, client disconnects, payload-limit aborts, and hash
  mismatches.

Required trace spans:

- `source_intake.upload.register` wraps metadata validation, stream hashing,
  object-store write, upload-row persistence, and idempotency completion.
- `source_intake.object_store.put`, `source_intake.object_store.open`, and
  `source_intake.object_store.delete` wrap the storage adapter boundary.
- `source_intake.idempotency.acquire` and
  `source_intake.idempotency.complete` wrap idempotency-store calls.
- `source_intake.ingestion_job.create` and
  `source_intake.ingestion_job.attach_source` wrap job and source-attachment
  service operations.

Span attributes are limited to `operation`, `outcome`, `error_code`,
`content_type_family`, `upload_state`, `intake_state`, and `target_kind`.
Correlation to a specific request belongs in logs and trace context, not in
metric labels.

Required alerts:

- Page when `source_intake_upload_errors_total` exceeds 5 percent of upload
  requests over 15 minutes, excluding `unsupported_content_type` and
  `payload_too_large`.
- Page when any object-store operation failure rate exceeds 1 percent over
  10 minutes or any `permission` error is observed.
- Page when a recovery sweep reports non-zero pending or failed uploads older
  than one hour.
- Page when a recovery sweep reports in-flight idempotency records older than
  15 minutes.
- Warn when `payload_too_large` or `unsupported_content_type` exceeds 20
  occurrences in five minutes for one operation.

Structured log levels are fixed as follows:

- `INFO`: successful upload registration, idempotency replay, ingestion-job
  creation, source attachment, and `awaiting_sources → ready_for_generation`
  transitions.
- `WARN`: client-correctable validation failures, idempotency conflicts,
  in-flight duplicate requests, hash or size mismatches, and recovery sweeps
  that find orphan uploads or stale idempotency records.
- `ERROR`: object-store failures, database transaction failures, stream read
  failures after request acceptance, and idempotency completion failures that
  may make a committed side effect non-replayable.

## Consequences

### Positive

- Upload storage and idempotency are replaceable adapters behind domain ports.
- Retried `POST` requests can be replayed or rejected consistently before a
  client creates duplicate resources.
- Intake status can move to `ready_for_generation` without changing the
  existing ingestion merge lifecycle.
- The filesystem adapter keeps local development and Continuous Integration
  (CI) self-contained.

### Negative

- The local filesystem adapter can leave orphan blobs if a database transaction
  fails after bytes are written. Operators must sweep stale `pending` or
  `failed` upload rows until an automated recovery worker lands.
- Idempotency records grow linearly with side-effecting requests. A purge job
  is deferred, so operators need a manual retention recipe.
- Trusting declared content types is weaker than magic-byte sniffing. Sniffing
  is deferred because it would require a new runtime dependency.

### Neutral

- S3-compatible pre-signed uploads, resumable uploads, and Vidai Mock inference
  fixtures belong to later roadmap items. The intake slice has no inference
  call and does not need a mock inference service.

## References

ADR 009 defines the source-to-script REST slice.[^1] ADR 014 defines the
architecture boundary that these ports preserve.[^2] The system design records
the current table relationships.[^3]

[^1]: [ADR 009: Source-to-script REST vertical slice](adr-009-source-to-script-rest-vertical-slice.md)
[^2]: [ADR 014: Hexagonal architecture enforcement](adr-014-hexagonal-architecture-enforcement.md)
[^3]: [Episodic podcast generation system design](../episodic-podcast-generation-system-design.md)
