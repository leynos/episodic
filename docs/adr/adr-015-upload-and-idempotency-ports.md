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
  `(principal_id, route, idempotency_key)`. The backing SQL table enforces that
  tuple with a unique constraint. `acquire` returns one of `Acquired`, `Replay`,
  `Conflict`, or `InFlight`; `complete` stores the final status, response
  body, response headers, and expiry timestamp.

The intake slice also introduces:

- `Upload`, a metadata record for uploaded bytes.
- `IngestionJobSource`, a pre-generation source attachment that references
  either an upload or a remote source Uniform Resource Identifier (URI).
- `IdempotencyRecord`, the stored request and replay payload.
- `IngestionJob.intake_state`, an orthogonal state for REST intake progress.

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
