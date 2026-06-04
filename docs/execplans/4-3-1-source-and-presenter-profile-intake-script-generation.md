# Source and presenter-profile intake for script generation

This Execution Plan (ExecPlan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`,
and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: DRAFT

## Purpose and big picture

This change delivers roadmap item `4.3.1`, the first half of the
source-to-script vertical slice defined in
[ADR 009](../adr/adr-009-source-to-script-rest-vertical-slice.md). After this
change, an integration client can drive the narrow intake workflow that ADR 009
calls out: upload one binary source document, create or reuse an ingestion job
attached to a series profile, attach the upload or a remote source Uniform
Resource Identifier (URI) to that job, bind reusable host and guest profile
reference-document revisions for the run, and poll the job until the source
context is ready for downstream draft script generation. Roadmap item `4.3.2`
will pick up the no-Quality-Assurance (QA) generation run and the Text Encoding
Initiative Profile 5 (TEI-P5) retrieval that close the vertical slice.

The slice is deliberately small. It introduces only the Representational State
Transfer (REST) intake surface, the two new domain ports the slice needs (an
object-store port for upload bytes and an idempotency-store port for retryable
POST requests), pre-generation source-attachment persistence, and a local
filesystem adapter sufficient for development and Continuous Integration (CI).
It deliberately defers Simple Storage Service (S3)-compatible pre-signed
adapters, magic-byte content sniffing, distributed background workers, and any
generation-run plumbing. Each deferred concern is recorded in `Risks` with the
follow-up roadmap item that should own it.

Success is observable when:

1. A client can `POST /v1/uploads` with `multipart/form-data` containing a
   research-paper Portable Document Format (PDF) byte stream, an
   `Idempotency-Key` Hypertext Transfer Protocol (HTTP) header, and metadata,
   and receive `201 Created` with body
   `{"id": "<uuid>", "content_hash": "sha256:<hex>", "size_bytes": <int>,`
   `"content_type": "application/pdf", "storage_key": "<opaque>", ...}`. A
   second identical request with the same key returns the same `201` response
   verbatim; a request with the same key and a different body returns `409`
   with body `{"code": "idempotency_conflict", ...}`.
2. A client can `POST /v1/ingestion-jobs` with
   `{"series_profile_id": "<uuid>", "target_episode_id": null}` and an
   `Idempotency-Key`, and receive `201 Created` with body
   `{"id": "<uuid>", "series_profile_id": "<uuid>", "target_episode_id": null,`
   `"intake_state": "awaiting_sources", "created_at": "...", ...}`.
3. A client can `POST /v1/ingestion-jobs/{job_id}/sources` with body
   `{"type": "upload", "upload_id": "<uuid>", "source_type": "research_paper",`
   `"weight": 1.0, "metadata": {"language": "en"}}` and an `Idempotency-Key`,
   and receive `201 Created` with the new source-attachment resource. The same
   endpoint accepts `{"type": "source_uri", "source_uri": "https://...", ...}`
   as a substitute for the upload variant and rejects payloads with an unknown
   `type` or with `type`-incompatible fields with `422`.
4. `GET /v1/ingestion-jobs/{job_id}` returns the current job status envelope
   containing `intake_state` and a `next_poll_after_seconds` body field for
   non-terminal states (clients should treat the field as advisory). The
   polling client observes `intake_state` advancing through
   `awaiting_sources → ready_for_generation` once at least one source is
   attached. The terminal state is sticky: a second `pending → ready` transition
   is impossible because the application-service `UPDATE` is conditional on the
   current state.
5. `GET /v1/series-profiles/{profile_id}/reference-documents?kind=host_profile`
   and the equivalent `kind=guest_profile` query continue to work unchanged,
   and `POST /v1/reference-bindings` lets a client pin a host or guest profile
   revision to the ingestion job's target context.
6. The full intake gate sequence — `make check-fmt`, `make markdownlint`,
   `make nixie`, `make build`, `make lint` (which includes
   `make check-architecture`), `make typecheck`, `make test` (which already
   invokes `make crosshair` as a dependency in the Makefile), and
   `make check-migrations` — all succeed.
7. `coderabbit review --agent` reports no unresolved actionable concerns at
   each milestone closure.
8. `docs/users-guide.md` describes the intake workflow for an integration
   client, `docs/developers-guide.md` documents the intake conventions
   (Idempotency-Key contract, error codes, source-attachment payload
   discriminator, canonical body-hash recipe, operator recovery recipe), and
   `docs/episodic-podcast-generation-system-design.md` is updated where the
   physical schema or port surface changes. A new
   `docs/adr/adr-015-upload-and-idempotency-ports.md` records the
   object-store-port plus idempotency-store-port design choices.
9. `docs/roadmap.md` marks item `4.3.1` done only after every gate above is
   green.

## Constraints

These invariants must hold throughout implementation. They are not
suggestions; violation requires escalation, not workarounds.

- The hexagonal boundary defined in
  [ADR 014](../adr/adr-014-hexagonal-architecture-enforcement.md) and enforced
  by Hecate in `pyproject.toml` `[tool.hecate]` is non-negotiable. All new port
  protocols live under `episodic.canonical.*` modules that belong to the
  `domain_ports` Hecate group. All new SQLAlchemy mappers, repositories, and
  filesystem code live under `episodic.canonical.storage.*` (the
  `outbound_adapter` group). All new Falcon resources and helpers live under
  `episodic.api.*` (the `inbound_adapter` group). The only allowed
  cross-adapter wiring sits in `episodic.api.runtime` and
  `episodic.worker.runtime` (the `composition_root` group). New Hecate
  prefixes must be added when new modules are introduced under
  `episodic.canonical.*` so the rule set keeps full coverage.
- Domain entities must be frozen dataclasses with `slots=True` where the rest
  of the codebase uses that convention. Repository protocols use
  `typ.Protocol` and live in dedicated `*_protocols.py` (or equivalent)
  modules within the `domain_ports` group.
- Logging must use `episodic.logging.get_logger` (a `femtologging` wrapper).
  Logs that record idempotency outcomes, source-attachment decisions, and job
  transitions must carry correlation identifiers (request id), `Idempotency-Key`,
  ingestion-job id, series-profile id, and the principal id supplied by the
  authorization middleware.
- All side-effecting `POST` requests in scope (`/v1/uploads`,
  `/v1/ingestion-jobs`, `/v1/ingestion-jobs/{job_id}/sources`) must accept
  `Idempotency-Key`. The store enforces the contract from ADR 009
  §"Idempotency implementation contract": one accepted request per key,
  identical body returns the stored response, different body returns `409`. A
  SQL unique constraint on `(principal_id, route, idempotency_key)` is
  required. The middleware order in `episodic.api.app.create_app` is
  authorization first, idempotency second: the idempotency cache key includes
  the authenticated principal id, so authorization must run before the
  idempotency middleware can compute the composite key.
- The request-body hash is SHA-256 over the canonical request bytes per ADR 009
  §"Request-body hash". For JSON bodies, canonical UTF-8 JSON with stable
  object-key ordering and no insignificant whitespace (the helper
  `canonical_json_bytes` in `episodic/canonical/idempotency_service.py` is
  the only authoritative implementation). For multipart bodies, the hash is
  `SHA-256(body_bytes) || ":" || canonical_json_bytes(allowlisted_metadata)`,
  where `body_bytes` is the streamed binary part and the allowlisted metadata
  fields per route are fixed in the same module
  (`MULTIPART_BODY_HASH_METADATA: dict[str, tuple[str, ...]]`). ADR 015 must
  contain a worked example vector that integration tests assert against.
- Error responses must use the established envelope from
  `docs/episodic-tui-api-design.md` §"Error contract" and the helpers in
  `episodic/api/errors.py`: `{"code": "...", "message": "...", "details": {...}}`.
  The new error codes introduced by this slice and their HTTP statuses are
  fixed in ADR 015 and documented in `docs/developers-guide.md`:

  | Error code                  | HTTP status | Used when                                                       |
  | --------------------------- | ----------- | --------------------------------------------------------------- |
  | `idempotency_conflict`      | 409         | Same key, different request-body hash.                          |
  | `idempotency_in_progress`   | 409         | Same key, identical body, first request still in flight.        |
  | `upload_not_found`          | 404         | Referenced `upload_id` does not exist.                          |
  | `upload_not_ready`          | 409         | Referenced `upload_id` is not yet in `ready` state.             |
  | `upload_hash_mismatch`      | 400         | Server-computed SHA-256 differs from the client-declared value. |
  | `upload_size_mismatch`      | 400         | Server-observed byte count differs from the declared size.      |
  | `unsupported_content_type`  | 415         | Declared `content_type` outside the allowlist.                  |
  | `payload_too_large`         | 413         | Streamed body exceeds the configured cap.                       |
  | `source_payload_invalid`    | 422         | Source-attachment payload fails discriminator validation.       |
  | `ingestion_job_not_found`   | 404         | Referenced `job_id` does not exist.                             |
  | `series_profile_not_found`  | 404         | Referenced `series_profile_id` does not exist.                  |

- Public REST routes must use the `/v1` prefix introduced by roadmap item
  `4.1.1`. Unversioned routes are not created for any new endpoint.
- All database changes must ship as Alembic migrations under
  `alembic/versions/` with `make check-migrations` clean.
- The default object-storage root is a configurable filesystem directory.
  Tests use a temporary directory fixture; runtime defaults are read from
  configuration through `ApiDependencies` so production deployments can swap
  in a different backend without code changes.
- No new external runtime dependencies may be added beyond what already ships
  in `pyproject.toml` unless documented and justified in `Decision Log` and
  explicitly approved through escalation. `python-magic` and any
  S3-compatible client library are out of scope for this slice.
- All Python source must satisfy `ruff format --check`, `ruff check`, and
  `ty check` cleanly. Pylint runs under `make lint` and must not regress.
- Public-facing prose is British English with Oxford spelling per
  `docs/documentation-style-guide.md`.

## Tolerances (exception triggers)

Stop and escalate when:

- Scope: implementation requires net changes to more than 25 production files
  or more than 2500 lines of code (LoC) across the slice.
- Interface: a public API contract from ADR 009 or
  `docs/episodic-tui-api-design.md` §"Source-to-script vertical slice" must
  change, including any HTTP status code, header name, error code, or JSON
  field name.
- Dependencies: a new entry in `pyproject.toml` `[project] dependencies` or
  `[dependency-groups] dev` is required.
- Iterations: tests for any single milestone still fail after three
  consecutive `make test` cycles.
- Hexagonal boundary: an import would cross a forbidden direction (for
  example, `episodic.canonical.domain` importing from
  `episodic.canonical.storage`) and the only obvious fix is to suppress
  `hecate check`.
- Database: the new schema would force a backfill of existing production
  data or break a previously published migration.
- Ambiguity: ADR 009, `docs/episodic-tui-api-design.md`, and the existing
  reference-document model disagree on field naming or behaviour.

## Risks

Known uncertainties identified upfront:

- Risk: The existing `SourceDocument` domain entity is ingestion-scoped and
  always carries `ingestion_job_id`, but it is created today by the multi-source
  pipeline once the merged canonical episode is known. Reusing the same record
  for pre-generation attachment would blur the two lifecycles and quietly
  invert invariants in `episodic/canonical/services.py::ingest_sources`.
  Severity: medium. Likelihood: high if we cut corners.
  Mitigation: introduce a separate `IngestionJobSource` entity for
  pre-generation attachments (the queue of inputs) and keep the existing
  `SourceDocument` entity strictly for post-merge provenance. A follow-up
  roadmap item can fold the two together once the generation slice (4.3.2)
  consumes both.
- Risk: ADR 009 mandates content-type allowlists and content hashes, but does
  not pin server-side magic-byte sniffing. Trusting the client `Content-Type`
  alone is a known weak point.
  Severity: medium. Likelihood: medium.
  Mitigation: enforce a strict allowlist (`application/pdf`,
  `application/vnd.openxmlformats-officedocument.wordprocessingml.document`,
  `text/plain`, `text/markdown`, `text/html`) and a 50 MB default size cap;
  verify the client-declared `sha256` (when present) by streaming hash during
  ingest; reject mismatches with `400`. Schedule server-side magic-byte
  sniffing as a follow-up under roadmap item `5.1` ("Establish role-based
  access control and tenancy"), where multi-tenant hardening lands.
- Risk: The existing `IngestionJob.status` field is consumed by the
  multi-source merge pipeline in
  `episodic/canonical/services.py::ingest_sources`, which writes
  `IngestionStatus.COMPLETED` at the end of the merge. Adding a new value
  `READY_FOR_GENERATION` to the same enum would silently invert the merge
  pipeline's "pending → running → completed" lifecycle assumption and risks
  drift between the intake and merge surfaces.
  Severity: high. Likelihood: high if unaddressed.
  Mitigation: add a new orthogonal column `IngestionJob.intake_state:
  IntakeState` (separate `StrEnum` in `episodic/canonical/domain.py` with
  values `awaiting_sources`, `ready_for_generation`, `cancelled`) and leave
  the existing `status` field alone. The intake REST surface reads and writes
  only `intake_state`. The merge pipeline continues to read and write only
  `status`. ADR 015 records this split. The two fields converge in roadmap
  item `4.3.2` when the generation orchestrator unifies them.
- Risk: Orphan filesystem blobs. The single-shot `POST /v1/uploads`
  streams bytes to disk before the `Upload` row is committed; a database
  rollback after the bytes land leaves a blob with no row to garbage-collect
  it. The two-step path is already two-phase by construction, so this risk
  affects only the multipart path.
  Severity: medium. Likelihood: low per request, high cumulatively.
  Mitigation: implement the multipart path as two phases inside the
  application service. First commit inserts an `Upload` in `pending` state
  with a reserved `storage_key`. The bytes then stream into that key via
  `ObjectStorePort.put`. The second commit transitions the row to `ready`
  with the server-computed `content_hash`. If the second commit fails, the
  row remains in `pending` and the operator-recovery recipe in
  `docs/developers-guide.md` (added in Milestone D7) describes the sweep:
  list `Upload` rows older than the configured retention with state in
  (`pending`, `failed`) and call `ObjectStorePort.delete` for each. The
  sweeper itself is out of scope for the slice and tracked under roadmap
  item `5.1` ("Role-based access control and tenancy hardening").
- Risk: Idempotency-record retention cost. At sustained throughput, the
  `idempotency_records` table grows at one row per side-effecting `POST`
  per `Idempotency-Key`. With a 24-hour retention and even modest stored
  response bodies, the table grows fastest of any in the slice.
  Severity: medium. Likelihood: medium.
  Mitigation: cap the stored response body at 64 kilobytes (KB) (responses
  larger than that are uncommon for the slice's endpoints; the cap is
  enforced by `IdempotencyStore.complete`). Add an Alembic-shipped index
  on `expires_at` so a future purge job can scan efficiently. The purge job
  itself is deferred to roadmap item `5.1`; the operator-recovery recipe in
  `docs/developers-guide.md` includes a manual `DELETE … WHERE expires_at <
  NOW()` recipe so production can drain the table without code changes.
- Risk: Idempotency-Key storage with a strict unique constraint can collide
  with parallel test execution under `pytest-xdist` if tests reuse keys.
  Severity: low. Likelihood: medium.
  Mitigation: composite cache key `(principal_id, route, idempotency_key)`;
  test helpers generate fresh `uuid4` keys per request; py-pglite isolates
  databases per worker.
- Risk: Object-storage filesystem adapter must not expose path traversal or
  permit symlink escape.
  Severity: high. Likelihood: low.
  Mitigation: server-generated `uuid4` storage keys, never trust client
  filenames for paths, store under a dedicated root configured by operator,
  refuse non-relative or `..` keys at the port boundary.
- Risk: ADR 009 requires Hypothesis property tests for the idempotency state
  machine. Hypothesis under `pytest-xdist` can produce flakes when the
  database is shared.
  Severity: low. Likelihood: medium.
  Mitigation: scope idempotency property tests to a per-test py-pglite
  database fixture; pin `Hypothesis` settings with a deterministic
  `derandomize` profile for CI per existing repo convention.
- Risk: The user prompt for this slice notes that Vidai Mock should cover
  inference services, but the slice itself does not call inference services
  — generation lives in roadmap item `4.3.2`. Pulling Vidai Mock fixtures
  into the slice would introduce a Mock-server scaffold with no consumer.
  Severity: low. Likelihood: certain (no inference path exists in the
  slice).
  Mitigation: document in `Decision Log` that Vidai Mock applies only once
  ingestion adapters add an inference-backed normalizer or the generation
  orchestrator lands. For 4.3.1 the required behavioural coverage uses
  `pytest-bdd` and `py-pglite` alone. Roadmap item `4.3.2` owns the Vidai
  Mock scaffold for the generation run.
- Risk: Two concurrent source-attachment requests for the same job both
  observe `intake_state = awaiting_sources` and both attempt the transition
  to `ready_for_generation`. The transition must be at-most-once because
  downstream consumers in `4.3.2` listen for the transition.
  Severity: low. Likelihood: medium.
  Mitigation: the application service performs a conditional UPDATE
  inside the same transaction as the source-row insert: `UPDATE
  ingestion_jobs SET intake_state = 'ready_for_generation' WHERE id = :id
  AND intake_state = 'awaiting_sources'`. Only the first concurrent
  transaction's UPDATE matches; the second is a no-op. Document the
  guarantee in ADR 015 and assert it in a property test.

## Progress

Use this section as the authoritative status of the work. Update with
timestamps as milestones land.

- [ ] Milestone D1 — Documentation, ADR, and schema sketch. Produce ADR 015,
  update `docs/episodic-podcast-generation-system-design.md` with the new
  intake schema, draft the new error-code table for
  `docs/developers-guide.md`, and add a stub `docs/users-guide.md` section.
- [ ] Milestone D2 — Domain ports and entities. Add `Upload`,
  `IngestionJobSource`, `IdempotencyRecord`, `UploadRepository`,
  `IngestionJobSourceRepository`, `IdempotencyStore`, `ObjectStorePort`, and
  the helper services that compute and verify canonical request hashes.
  Extend `IngestionJobRepository` with `list_paged` and `update_status`.
- [ ] Milestone D3 — Outbound adapters. Add SQLAlchemy mappers, models, and
  repositories for the new entities. Add a `FilesystemObjectStore` adapter.
  Add Alembic migrations. Wire the new repositories into
  `SqlAlchemyUnitOfWork`. Add Hecate prefixes.
- [ ] Milestone D4 — Application services. Implement
  `register_upload`, `initialize_upload`, `finalize_upload_bytes`,
  `create_ingestion_job`, `attach_source_to_ingestion_job`,
  `get_ingestion_job_status`, and the supporting transactional flows.
- [ ] Milestone D5 — Inbound adapters and HTTP wiring. Add Falcon resources
  `UploadsResource`, `UploadResource`, `IngestionJobsResource`,
  `IngestionJobResource`, `IngestionJobSourcesResource`, an
  `IdempotencyMiddleware`, and helpers for multipart parsing, content-type
  allowlists, and size limits. Register the routes in `episodic/api/app.py`
  (with the authorization middleware registered before the idempotency
  middleware) and update `ApiDependencies` with the new configuration
  handles. The `POST /v1/uploads/init` and `PUT /v1/uploads/{id}/bytes`
  routes are explicitly out of scope for this slice (see Decision Log
  "Two-step upload deferred"); roadmap item `5.1` or a dedicated S3-adapter
  item picks them up.
- [ ] Milestone D6 — Tests. Add unit tests for ports, mappers, hash
  computation, and idempotency body-hash comparison. Add a behavioural
  feature `tests/features/source_intake.feature` with steps in
  `tests/steps/test_source_intake_steps.py`. Add a syrupy snapshot test for
  the canonical JSON envelopes. Add Hypothesis property tests for the
  idempotency state machine.
- [ ] Milestone D7 — Documentation final pass and roadmap toggle. Finalise
  `docs/users-guide.md` and `docs/developers-guide.md` updates, refresh the
  contents index, and mark `4.3.1` done in `docs/roadmap.md`.

Update each milestone with completion timestamps and any partial-progress
notes. Use the form `[x] (YYYY-MM-DDTHH:MMZ) <note>`.

## Surprises & discoveries

Record observations during implementation that were not anticipated as risks.
Each entry should follow the form:

- Observation: the unexpected finding.
  Evidence: how you know.
  Impact: how it affects this plan or future work.

## Decision log

Record significant decisions made while implementing the plan. Each entry
should follow the form:

- Decision: the choice taken.
  Rationale: why this choice over alternatives.
  Date/Author: timestamp and who decided.

Seed entries (DRAFT):

- Decision: Introduce a new `IngestionJobSource` entity for pre-generation
  attachments rather than reusing the existing `SourceDocument` entity.
  Rationale: `SourceDocument` is created during merge and ties to a
  canonical episode; mixing pre-generation attachments into the same table
  would invert the invariant in `episodic/canonical/services.py::ingest_sources`
  and complicate generation kick-off in roadmap item `4.3.2`. Keeping the
  two entities separate preserves the existing post-merge provenance
  semantics and gives the slice a clean intake table.
  Date/Author: drafted with the ExecPlan; revisit after Decision Log review
  in roadmap item `4.3.2`.
- Decision: Local filesystem adapter only for the slice's object store.
  Rationale: ADR 009 does not require S3 or pre-signed Uniform Resource
  Locator (URL) semantics for the intake slice. Keeping the adapter local
  removes a new external dependency, removes IAM/credentials concerns from
  the slice, and keeps `make test` self-contained. ADR 015 records the
  `ObjectStorePort` interface so a future S3 adapter is a drop-in.
  Date/Author: drafted with the ExecPlan.
- Decision: Two-step upload deferred. The slice ships only
  `POST /v1/uploads` (multipart); `POST /v1/uploads/init` and `PUT
  /v1/uploads/{upload_id}/bytes` are out of scope.
  Rationale: the init flow exists primarily to mirror an S3-style adapter
  that the same plan defers. Shipping the init contract before its real
  consumer exists locks in a wire format with no integration partner and
  roughly doubles the inbound-adapter surface, snapshot tests, and BDD
  scenarios. The multipart path is sufficient to demonstrate the intake
  workflow; the init path lands when the S3 adapter does.
  Date/Author: drafted with the ExecPlan.
- Decision: Add a new `IngestionJob.intake_state` column rather than
  overloading the existing `IngestionStatus` enum.
  Rationale: the existing `status` field is owned by the multi-source
  merge pipeline (`pending → running → completed/failed`). Adding
  `READY_FOR_GENERATION` to that enum would invert the merge pipeline's
  lifecycle assumption. A separate orthogonal column keeps the intake and
  merge surfaces decoupled and lets roadmap item `4.3.2` decide how to
  unify them.
  Date/Author: drafted with the ExecPlan.
- Decision: Source-attachment payload uses an explicit `type`
  discriminator (`{"type": "upload", "upload_id": "..."}` or `{"type":
  "source_uri", "source_uri": "..."}`).
  Rationale: the domain entity already carries `attachment_kind`; the wire
  format should mirror it. An explicit discriminator parses cleanly with
  JSON-Schema-style union validation and avoids the subtle client bugs
  that "implicit-key" payload unions encourage.
  Date/Author: drafted with the ExecPlan.
- Decision: Idempotency middleware sits after the authorization middleware,
  not before it.
  Rationale: the idempotency cache key is composite
  `(principal_id, route, key)`. Computing it before authorization runs
  would either drop `principal_id` (allowing cross-tenant cache reads) or
  require the middleware to look up the principal itself, duplicating
  authorization logic. The authorization re-check on a replayed request is
  cheap and is the correct trust boundary.
  Date/Author: drafted with the ExecPlan in response to the Logisphere
  design-review finding R2.
- Decision: Multipart bodies for `POST /v1/uploads` are hashed by the
  application service as `SHA-256(body_bytes) || ":" ||
  canonical_json_bytes(allowlisted_metadata)`, with the allowlisted metadata
  fields per route fixed in
  `episodic.canonical.idempotency_service.MULTIPART_BODY_HASH_METADATA`.
  Rationale: two implementations of "the canonical multipart body hash"
  inevitably diverge; pinning the algorithm in one constant and a worked
  example vector in ADR 015 ensures replay semantics survive code changes.
  Date/Author: drafted with the ExecPlan in response to the Logisphere
  design-review finding Y4.
- Decision: Implement content-type allowlist and client-declared SHA-256
  verification only; defer server-side magic-byte sniffing.
  Rationale: ADR 009 does not require sniffing; adding `python-magic` is a
  new external dependency and would breach the "no new deps" constraint.
  Sniffing belongs in roadmap item `5.1` ("Role-based access control and
  tenancy") where multi-tenant hardening lands.
  Date/Author: drafted with the ExecPlan.
- Decision: Vidai Mock coverage is deferred to roadmap item `4.3.2`.
  Rationale: the intake slice does not call inference services. Adding a
  Vidai Mock scaffold now would create unused fixtures. `4.3.2` introduces
  the generation orchestrator, which is the natural seam.
  Date/Author: drafted with the ExecPlan.

## Outcomes & retrospective

Summarise outcomes, gaps, and lessons after the final milestone. Compare the
result against the success criteria above. Note what would be done
differently next time. Update this section at the close-out commit.

## Context and orientation

This section assumes the reader has only the current working tree.

### Repository layout that matters here

- `episodic/api/` is the Falcon Asynchronous Server Gateway Interface (ASGI)
  inbound adapter. `episodic/api/app.py` builds the ASGI app via
  `create_app(dependencies: ApiDependencies)` and registers every `/v1` route.
  `episodic/api/dependencies.py` defines the `ApiDependencies` dataclass that
  carries the unit-of-work factory, readiness probes, shutdown hooks,
  authorization port, and (after this slice) the upload-related configuration.
  `episodic/api/resources/` holds the per-resource Falcon classes; the
  reference-document resource at
  `episodic/api/resources/reference_documents.py` is the canonical pattern to
  copy for the new resources. `episodic/api/errors.py` defines the unified
  error envelope and `episodic/api/helpers.py` defines the parsing utilities
  (`parse_uuid`, `parse_pagination`, `require_payload_dict`,
  `parse_enum_param`).
- `episodic/canonical/` is the domain plus driven-port layer.
  `episodic/canonical/domain.py` holds the canonical entities, including the
  existing `IngestionJob`, `SourceDocument`, `ReferenceDocumentKind` (with
  `HOST_PROFILE` and `GUEST_PROFILE` already defined), and
  `ReferenceBindingTargetKind` (which already includes `INGESTION_JOB`).
  `episodic/canonical/entity_protocols.py` and
  `episodic/canonical/unit_of_work_protocols.py` define the repository and
  unit-of-work protocols. `episodic/canonical/services.py` is the existing
  application service for post-merge persistence (`ingest_sources`).
  `episodic/canonical/ingestion_service.py` orchestrates multi-source
  ingestion through the multi-source pipeline; do not modify it for this
  slice.
- `episodic/canonical/storage/` is the SQLAlchemy outbound adapter.
  `entity_models.py` and `entity_mappers.py` already cover the existing
  `IngestionJob` and `SourceDocument`. `repositories.py` exposes
  `SqlAlchemyIngestionJobRepository` and `SqlAlchemySourceDocumentRepository`.
  `uow.py` is the canonical `SqlAlchemyUnitOfWork`.
- `alembic/versions/` holds the migration history. New tables require an
  Alembic migration and `make check-migrations` must be clean.
- `tests/` is split into `tests/test_*.py` (unit tests),
  `tests/features/*.feature` (BDD), `tests/steps/test_*_steps.py` (BDD step
  modules), `tests/fixtures/*.py` (shared fixtures including
  `tests/fixtures/api.py` for the Falcon test client and
  `tests/fixtures/database.py` for py-pglite session factories), and
  `tests/__snapshots__/` (syrupy ambits).
- The Hecate architectural enforcement configuration lives at
  `pyproject.toml` `[tool.hecate]` and must be extended whenever new modules
  appear under `episodic.canonical.*` or `episodic.api.*`.

### Concepts (defined the first time used)

- **Idempotency-Key.** A client-supplied HTTP header that names a request so
  the server can deduplicate retries. The contract in this slice follows the
  Internet Engineering Task Force (IETF)
  `draft-ietf-httpapi-idempotency-key-header` and ADR 009.
- **Request-body fingerprint.** A SHA-256 hash over the canonical request
  bytes. JSON requests are canonicalised by sorting keys and removing
  whitespace; multipart requests hash the body bytes and the metadata fields
  that change the side effect.
- **Two-step upload (deferred).** A future `POST /v1/uploads/init` would
  return an opaque `put_url`; the client would then `PUT` the body bytes
  to that URL. The shape mirrors the IETF resumable-uploads draft and tus
  version 1.0.0 without committing to chunked semantics. This slice
  defers the endpoint pair to roadmap item `5.1` or a dedicated
  S3-adapter item; the `ObjectStorePort` interface keeps the door open.
- **Source attachment.** A row in the new `ingestion_job_sources` table
  binding either an `Upload` (by `upload_id`) or a remote `source_uri` to an
  `IngestionJob`. This is distinct from the existing post-merge
  `source_documents` table.
- **Presenter profile.** ADR 009 defines a presenter profile as a reusable
  `ReferenceDocument` of kind `host_profile` or `guest_profile`. Existing
  endpoints at `/v1/series-profiles/{profile_id}/reference-documents` and
  `/v1/reference-bindings` already serve this contract; the slice does not
  add new presenter-profile endpoints.
- **Ready-for-generation.** A terminal status the ingestion job reaches once
  at least one source attachment exists and the run can proceed to
  generation. Roadmap item `4.3.2` is the consumer.

## Plan of work

The plan is staged so each stage ends with a fully testable repository state.

### Stage A — Design and documentation prep (Milestone D1)

No production code changes in this stage. The aim is to publish the design
contract that the rest of the milestones implement against.

1. Author `docs/adr/adr-015-upload-and-idempotency-ports.md` following the
   documentation style guide ADR template. The ADR records two driven-port
   design decisions:
   - `ObjectStorePort`: a minimal interface exposing `put`, `open`, and
     `delete`. The first adapter is a filesystem implementation. The port
     forbids client-controlled paths. Full signatures appear in
     §"Interfaces and dependencies".
   - `IdempotencyStorePort`: an `acquire` method returning a discriminated
     union of `Acquired`, `Replay`, `Conflict`, and `InFlight`, backed by a
     unique SQL constraint. The store persists the stored response payload,
     status, headers, and expiry. The default retention is 24 hours,
     configurable per route.
   The ADR also records the decision to introduce a new
   `IngestionJobSource` entity and to defer S3, magic-byte sniffing, and
   Vidai Mock to later items.
2. Update `docs/episodic-podcast-generation-system-design.md` §"Reference
   schema" entity-relationship diagram and §"Source-to-script vertical
   slice" with the new `uploads`, `ingestion_job_sources`, and
   `idempotency_records` tables. Use Mermaid as the rest of the document
   does; `make nixie` must validate.
3. Draft the new error code table in `docs/developers-guide.md` (final wording
   lands in Milestone D7 once the codes ship). Reserve the codes listed in
   `Constraints` above.
4. Add a stub `docs/users-guide.md` section "Source-to-script intake" with a
   "Coming soon" notice; the final user-guide prose lands in Milestone D7.
5. Cross-link the new ADR from
   `docs/episodic-podcast-generation-system-design.md` and from the index in
   `docs/contents.md`.

Stage A acceptance: `make markdownlint`, `make nixie`, and `make check-fmt`
all clean.

### Stage B — Domain ports and entities (Milestone D2)

Each addition lives in the `domain_ports` Hecate group and may not import
from `episodic.canonical.storage` or `episodic.api`.

1. Create `episodic/canonical/uploads.py` with frozen `Upload` and
   `UploadInitRequest` dataclasses. `Upload` carries `id: uuid.UUID`,
   `owner_principal_id: str | None`, `content_type: str`, `declared_size: int`,
   `actual_size: int | None`, `declared_sha256: str | None`,
   `content_hash: str | None`, `storage_key: str`, `state: UploadState`,
   `metadata: JsonMapping`, `created_at: dt.datetime`,
   `updated_at: dt.datetime`. `UploadState` is a `StrEnum` of `pending` (init
   issued, awaiting bytes), `ready` (bytes received and hashed), `failed`,
   `expired`.
2. Create `episodic/canonical/ingestion_sources.py` with a frozen
   `IngestionJobSource` dataclass. Fields: `id: uuid.UUID`,
   `ingestion_job_id: uuid.UUID`, `attachment_kind: AttachmentKind` (`upload`
   or `source_uri`), `upload_id: uuid.UUID | None`, `source_uri: str | None`,
   `source_type: str`, `weight: float`, `metadata: JsonMapping`,
   `created_at: dt.datetime`. Validate via `__post_init__` that exactly one
   of `upload_id` or `source_uri` is populated and that the populated value
   matches `attachment_kind`.
3. Create `episodic/canonical/idempotency.py` with a frozen
   `IdempotencyRecord` dataclass: `id: uuid.UUID`,
   `principal_id: str | None`, `route: str`, `key: str`, `body_hash: str`,
   `state: IdempotencyState` (`in_flight`, `completed`),
   `response_status: int | None`, `response_body: JsonMapping | None`,
   `response_headers: JsonMapping | None`, `expires_at: dt.datetime`,
   `created_at: dt.datetime`, `updated_at: dt.datetime`. Also define a
   tagged-union outcome type `IdempotencyOutcome` =
   `Acquired | Replay | Conflict | InFlight` for the `acquire` call.
4. Create `episodic/canonical/upload_protocols.py` with three Protocol
   classes: `UploadRepository` (`add`, `get`, `mark_ready`, `mark_failed`),
   `IngestionJobSourceRepository` (`add`, `get`, `list_for_job_paged`,
   `count_for_job`), and `IdempotencyStore` (`acquire`, `complete`,
   `lookup`). Each method is `async`.
5. Extend `episodic/canonical/entity_protocols.py::IngestionJobRepository`
   with `list_paged(series_profile_id: uuid.UUID | None,
   intake_state: IntakeState | None, *, limit: int, offset: int) ->
   Sequence[IngestionJob]`, `count(series_profile_id, intake_state)`, and
   `transition_intake_state(job_id, *, from_state: IntakeState, to_state:
   IntakeState) -> bool`. The transition method returns `True` only when the
   conditional UPDATE matched, so callers can detect concurrent transitions.
6. Add a new `IntakeState` `StrEnum` to `episodic/canonical/domain.py` with
   values `AWAITING_SOURCES = "awaiting_sources"`, `READY_FOR_GENERATION =
   "ready_for_generation"`, and `CANCELLED = "cancelled"`. Add a new column
   `IngestionJob.intake_state: IntakeState` (default `AWAITING_SOURCES`) to
   the existing dataclass. **Do not extend `IngestionStatus`.** The merge
   pipeline (`episodic/canonical/services.py::ingest_sources`) continues to
   read and write only `status`; the intake REST surface reads and writes
   only `intake_state`. ADR 015 records the split. Roadmap item `4.3.2`
   owns the eventual unification.
7. Define an `ObjectStorePort` Protocol in
   `episodic/canonical/object_store.py`. The full signatures appear in
   §"Interfaces and dependencies"; in short, an async `put`, an
   `open` context manager, and a `delete`, all returning domain types.
   The port forbids `..`, leading slashes, and absolute paths in `key` at
   the port boundary so adapters can rely on sanitised input.
8. Add the new ports to `episodic/canonical/unit_of_work_protocols.py` so the
   unit-of-work exposes them, and update the `domain_ports` group in
   `pyproject.toml` `[tool.hecate]` to include
   `episodic.canonical.uploads`, `episodic.canonical.ingestion_sources`,
   `episodic.canonical.idempotency`, `episodic.canonical.upload_protocols`,
   and `episodic.canonical.object_store`. The companion application-service
   modules (`episodic.canonical.upload_service`,
   `episodic.canonical.ingestion_job_service`,
   `episodic.canonical.idempotency_service`) are added to the `application`
   group in Stage D step 5 below; the new storage modules are added to the
   `outbound_adapter` group in Stage C step 8.

Stage B acceptance: `make check-fmt`, `make lint` (Hecate clean), and
`make typecheck` all pass with the new modules in place.

### Stage C — Outbound adapters (Milestone D3)

These additions sit in the `outbound_adapter` Hecate group.

1. Add SQLAlchemy models under `episodic/canonical/storage/`:
   - `uploads.py` — `UploadRecord` with primary key, owner principal,
     content type, declared size, actual size, declared sha256, content hash,
     storage key, state, metadata JSON, timestamps. Unique index on
     `content_hash` is *not* enforced (different uploads may share bytes).
   - `ingestion_sources.py` — `IngestionJobSourceRecord` with foreign keys
     to `ingestion_jobs.id` and `uploads.id`. Database-level check
     constraint that exactly one of `upload_id`, `source_uri` is non-null.
   - `idempotency.py` — `IdempotencyRecord` with composite unique index on
     `(principal_id, route, key)` and a `body_hash` column. JSON columns for
     stored response body and headers. A monotonically advancing
     `expires_at` column for retention.
2. Add mappers (`*_mappers.py`) following the convention in
   `episodic/canonical/storage/entity_mappers.py`. Each mapper exposes the
   familiar `_X_from_record` / `_X_to_record` private helpers.
3. Add repositories under `episodic/canonical/storage/repositories.py` or
   new sibling modules: `SqlAlchemyUploadRepository`,
   `SqlAlchemyIngestionJobSourceRepository`, and
   `SqlAlchemyIdempotencyStore`. The idempotency store uses
   `INSERT … ON CONFLICT DO NOTHING` to guarantee first-writer-wins
   semantics; the `acquire` method returns the discriminated outcome union
   from Stage B.
4. Extend `SqlAlchemyIngestionJobRepository` with `list_paged`, `count`, and
   `update_status` to satisfy the protocol extension.
5. Add `episodic/canonical/storage/filesystem_object_store.py` implementing
   `ObjectStorePort` on a configurable root directory. The adapter reads in
   fixed-size chunks (64 KB; pin as `_OBJECT_STORE_READ_CHUNK_BYTES`),
   streams each chunk to a temporary file under `{root}/_tmp/`, updates the
   SHA-256 hasher and the running byte count as it goes, and raises
   `PayloadTooLargeError` *before* writing a chunk that would push the count
   past the cap. On completion the adapter atomically renames the temporary
   file into `{root}/{key}`. Defence in depth on the path: after sanitising
   `key`, the adapter joins the path, calls `pathlib.Path.resolve()`, and
   asserts `os.path.commonpath([resolved, root_resolved]) == root_resolved`
   so symlink escape is blocked even if a previous deploy left a malicious
   link inside the root.
6. Add an Alembic migration under `alembic/versions/` that creates the three
   new tables (`uploads`, `ingestion_job_sources`, `idempotency_records`),
   adds the new `intake_state` column to `ingestion_jobs` (with default
   `'awaiting_sources'` and a `NOT NULL` constraint backfilled to that
   default), adds a `CHECK` constraint enforcing the
   `(upload_id IS NULL) <> (source_uri IS NULL)` invariant on
   `ingestion_job_sources`, and adds these indexes:
   - `ingestion_jobs(series_profile_id, intake_state, created_at DESC)` for
     the listing query.
   - `idempotency_records(expires_at)` for the eventual purge job.
   - `idempotency_records(principal_id, route, key) UNIQUE` for the
     first-writer-wins enforcement.
   - `uploads(state, created_at)` for the eventual orphan-blob sweeper.
   - `ingestion_job_sources(ingestion_job_id, created_at)` for the per-job
     listing query.
   `make check-migrations` must succeed after the migration is generated
   and the models updated.
7. Extend `SqlAlchemyUnitOfWork.__aenter__` to bind the new repositories,
   and add an `object_store` attribute populated from a port supplied via
   `ApiDependencies` (the UoW does not construct the adapter; the
   composition root does). The idempotency store is part of the UoW so it
   participates in the same SQL transaction as the resource being created.
8. Update the `outbound_adapter` group in `pyproject.toml` `[tool.hecate]`
   to include the new modules
   (`episodic.canonical.storage.uploads`,
   `episodic.canonical.storage.ingestion_sources`,
   `episodic.canonical.storage.idempotency`,
   `episodic.canonical.storage.filesystem_object_store`).

Stage C acceptance: `make build`, `make lint` (architecture clean),
`make typecheck`, `make check-migrations`, and the existing test suite stay
green.

### Stage D — Application services (Milestone D4)

Application services live in the `application` Hecate group (existing
`episodic.canonical.services` family). They depend only on `domain_ports`.

1. Add `episodic/canonical/upload_service.py` exposing pure async
   functions:
   - `register_upload(uow, *, content_type, declared_size, declared_sha256,
     stream, object_store) -> Upload`
     handles the single-shot multipart path as a two-phase write:
     1. Phase one: inside a UoW transaction, insert an `Upload` row in
        `pending` state with a server-generated `storage_key`. Commit.
     2. Phase two: stream bytes through `object_store.put` (which enforces
        size cap and computes SHA-256 on the way). Verify the
        client-declared SHA-256 if supplied; verify the byte count matches
        `declared_size`.
     3. Phase three: in a new UoW transaction, call `mark_ready` with the
        observed `content_hash` and `actual_size`.
     A failure between phases one and three leaves an `Upload` row in
     `pending` state and possibly a blob on disk; both are reclaimed by
     the operator-recovery recipe documented in `docs/developers-guide.md`.
     Enforces the size cap, content-type allowlist, and (when present)
     declared-SHA-256 verification.
2. Add `episodic/canonical/ingestion_job_service.py` exposing:
   - `create_ingestion_job(uow, *, series_profile_id, target_episode_id,
     requested_by) -> IngestionJob`. Validates the series profile exists,
     defaults `status = IngestionStatus.PENDING`,
     `intake_state = IntakeState.AWAITING_SOURCES`, persists, and returns
     the entity.
   - `attach_source_to_ingestion_job(uow, *, job_id, attachment) ->
     IngestionJobSource`. `attachment` is a discriminated value object
     (`UploadAttachment` or `SourceUriAttachment`). The service:
     1. Loads the job and (for `UploadAttachment`) validates the upload is
        in `ready` state.
     2. Inserts the `IngestionJobSource` row.
     3. Calls
        `uow.ingestion_jobs.transition_intake_state(job_id,
        from_state=IntakeState.AWAITING_SOURCES,
        to_state=IntakeState.READY_FOR_GENERATION)`.
        The conditional UPDATE returns `True` only for the first concurrent
        request that observes `AWAITING_SOURCES`; subsequent attachments
        return `False` and the service treats that as a no-op (the
        transition is at-most-once).
     4. Commits the UoW.
   - `list_ingestion_jobs_paged(uow, *, series_profile_id, intake_state,
     limit, offset)` and `get_ingestion_job_with_sources(uow, *, job_id)`.
3. Add `episodic/canonical/idempotency_service.py` with helpers that compute
   the canonical request fingerprint:
   - `canonical_json_bytes(payload: JsonMapping) -> bytes` enforces sorted
     keys, UTF-8, no insignificant whitespace.
   - `MULTIPART_BODY_HASH_METADATA: dict[str, tuple[str, ...]]` fixes the
     per-route allowlist of metadata fields that participate in the
     multipart body hash (initially `{"POST /v1/uploads": ("content_type",
     "declared_size", "declared_sha256")}`).
   - `multipart_request_hash(route, *, body_sha256: str, metadata:
     JsonMapping) -> str` returns
     `sha256(body_sha256 + ":" + canonical_json_bytes(filtered_metadata))`
     where `filtered_metadata` retains only the route's allowlisted fields.
     The function accepts the streamed body's SHA-256 rather than the bytes
     themselves so the streaming hash computed during upload is the same
     value used for the body fingerprint.
   - `acquire_or_replay(store, *, principal, route, key, body_hash, work:
     cabc.Callable[..., Awaitable[StoredResponse]]) -> IdempotencyOutcome`
     is the orchestration wrapper that resources call from the inbound
     adapter.
4. Where the new domain transitions require cross-repository commits
   (source attachment + intake-state transition + idempotency record), wrap
   them in the existing `CanonicalUnitOfWork` and commit once. The
   two-phase blob write for `register_upload` is the only flow that spans
   more than one transaction; that flow is documented as "eventually
   consistent on the blob" in ADR 015.
5. Update the `application` Hecate group in `pyproject.toml` `[tool.hecate]`
   to include
   `episodic.canonical.upload_service`,
   `episodic.canonical.ingestion_job_service`, and
   `episodic.canonical.idempotency_service`.

Stage D acceptance: `make check-fmt`, `make lint`, `make typecheck`, and
`make test` (existing tests) stay green. New unit tests for the application
services are added in Milestone D6 but stub fixtures can land here so the
services compile.

### Stage E — Inbound adapters and HTTP wiring (Milestone D5)

These additions live under `episodic.api.*` and may import from
`application` and `domain_ports`.

1. Add `episodic/api/idempotency.py`. Define an
   `IdempotencyMiddleware` that, on requests matching the configured
   idempotent routes, reads the `Idempotency-Key` header, computes the
   request-body hash, attempts `acquire_or_replay`, and short-circuits the
   response with a replayed payload when the outcome is `Replay` or
   `InFlight`. On `Conflict` it returns `409` with
   `{"code": "idempotency_conflict", ...}`. On `Acquired` it stashes a
   completion callback on the request context that the resource invokes
   after the resource has been created so the stored response can be
   captured.
2. Add `episodic/api/upload_helpers.py` with the multipart parser, the
   content-type allowlist (`UPLOAD_CONTENT_TYPE_ALLOWLIST` constant), the
   maximum-size constant (read from configuration through
   `ApiDependencies`), and a streaming hasher that enforces the size cap
   while computing SHA-256.
3. Add `episodic/api/resources/uploads.py` with `UploadsResource` and
   `UploadResource`. The `UploadsResource.on_post` route accepts multipart
   bodies and returns `201 Created` with the JSON envelope from success
   criterion 1; the `UploadResource.on_get` route returns the metadata
   envelope for an existing upload. Both use the helpers in
   `episodic/api/helpers.py` and the error-mapping helpers in
   `episodic/api/errors.py`. Init and `PUT bytes` resources are *not* added
   in this slice (see Decision Log "Two-step upload deferred").
4. Add `episodic/api/resources/ingestion_jobs.py` with
   `IngestionJobsResource` (`on_post`, `on_get` for list with pagination
   and `status`/`series_profile_id` filters), `IngestionJobResource`
   (`on_get` with `Retry-After` on non-terminal states), and
   `IngestionJobSourcesResource` (`on_post`, `on_get`).
5. Add serializers in `episodic/api/serializers.py` (or sibling module)
   for the new entities, returning the JSON envelopes documented in the
   "Purpose and big picture" success criteria.
6. Wire the new resources into `episodic/api/app.py` at the `/v1/uploads`,
   `/v1/uploads/{upload_id}`, `/v1/ingestion-jobs`,
   `/v1/ingestion-jobs/{job_id}`, and
   `/v1/ingestion-jobs/{job_id}/sources` paths. The middleware order in
   `create_app` is `AuthorizationMiddleware` first, `IdempotencyMiddleware`
   second: the idempotency cache key includes `principal_id`, so the
   authorization middleware must establish the principal before the
   idempotency middleware can compute the composite key. A replayed
   request still passes through `AuthorizationMiddleware` on each retry —
   that re-check is cheap and is the correct trust boundary.
7. Extend `ApiDependencies` with a new `upload_settings: UploadSettings`
   field carrying the object-store port, maximum upload size, allowed
   content types, and idempotency retention. Default values come from the
   composition root; tests override via the existing
   `build_api_dependencies` helper.

Stage E acceptance: `make check-fmt`, `make lint`, and `make typecheck`
pass. The Falcon test client accepts a happy-path request through every
new route. Failing edge-case behaviour is covered in Milestone D6.

### Stage F — Tests (Milestone D6)

Tests are split into the layers defined by the testing strategy in
`hexagonal-architecture` and the conventions in `docs/developers-guide.md`.

1. **Unit tests (`tests/test_*.py`).** Add `tests/test_upload_service.py`,
   `tests/test_ingestion_job_service.py`,
   `tests/test_idempotency_service.py`, and
   `tests/test_filesystem_object_store.py`. These exercise services and
   adapters in isolation with in-memory or temporary-directory fixtures.
   Cover happy paths and unhappy paths:
   - allowlist rejection,
   - size cap enforcement,
   - declared-sha256 mismatch (400),
   - upload state-machine guards (pending → ready, ready → ready rejection,
     pending → failed),
   - source-attachment payload union validation,
   - ingestion-job state transition on first attachment,
   - object-store path-traversal refusal.
2. **Property tests (`tests/test_idempotency_properties.py`).** Use
   `hypothesis[asyncio]` to generate sequences of `(key, body)` pairs and
   assert the ADR 009 invariants: identical bodies for a key never create
   more than one resource; different bodies for a key always return
   `409`. Add a separate property test for the
   `transition_intake_state` at-most-once guarantee: interleave many
   concurrent attach-source operations against the same job and assert
   that exactly one observer sees the `AWAITING_SOURCES →
   READY_FOR_GENERATION` transition. Mark the tests with
   `@pytest.mark.hypothesis` and use the derandomised CI profile defined
   in the existing repo convention.
3. **Behavioural tests (`tests/features/source_intake.feature` and
   `tests/steps/test_source_intake_steps.py`).** Cover the end-to-end
   intake workflow:
   - Scenario: upload PDF, create job, attach upload, bind host and guest
     profile revisions, observe `intake_state = ready_for_generation`.
   - Scenario: duplicate Idempotency-Key with same body returns the same
     response.
   - Scenario: duplicate Idempotency-Key with different body returns
     `409` with `code = idempotency_conflict`.
   - Scenario: source attachment with an unknown `type` discriminator,
     or with `type`-incompatible fields, returns `422` with
     `code = source_payload_invalid`.
   - Scenario: source attachment referencing an upload still in
     `pending` returns `409` with `code = upload_not_ready`.
   - Scenario: source attachment with declared content-type outside the
     allowlist returns `415` with `code = unsupported_content_type`.
   - Scenario: upload body exceeds the configured cap and returns `413`
     with `code = payload_too_large`.
   - Scenario: GET ingestion-jobs filtered by `series_profile_id` and
     `intake_state` and paginated.
   Mirror the conftest registration patterns in
   `tests/steps/test_reference_document_api_steps.py`. Use
   `canonical_api_async_client` so multipart bodies work naturally.
4. **Snapshot tests (`tests/test_source_intake_snapshots.py`).** Use
   `syrupy` to lock in the canonical JSON envelopes for upload, upload-init,
   ingestion-job, ingestion-job-list, and source-attachment responses.
   Snapshot only the deterministic fields; canonicalise UUIDs and
   timestamps in the test serialiser.
5. **Integration tests (`tests/test_source_intake_integration.py`).**
   Drive the py-pglite-backed `canonical_api_client` end to end. Confirm
   migrations are applied and the new tables exist.
6. **Fixtures.** Extend `tests/fixtures/api.py` with an `upload_settings`
   override that points the object store at a `tmp_path` directory. Add
   `tests/fixtures/uploads.py` with helpers that POST a PDF byte stream
   and return an `upload_id`.

Vidai Mock is not used in this milestone (see `Decision Log`). Document the
deferral in the test module docstrings so a future contributor does not add
a Mock-server fixture by reflex.

Stage F acceptance: `make crosshair`, `make test`, and `make check-migrations`
all clean. The behavioural feature `source_intake.feature` enumerates the
slice's user-visible behaviour and runs under `pytest-bdd`.

### Stage G — Documentation final pass and roadmap toggle (Milestone D7)

1. Finalise `docs/users-guide.md` with the integration-client narrative for
   the source-to-script intake workflow, showing the request and response
   bodies for each endpoint.
2. Finalise the error-code table and Idempotency-Key conventions in
   `docs/developers-guide.md`.
3. Refresh the table of contents in `docs/contents.md` to include ADR 015
   and the new sections.
4. Update `docs/episodic-podcast-generation-system-design.md` if any
   adapter-level decision diverged from Stage A; reflect the divergence in
   `Decision Log` and the ADR.
5. Update `docs/roadmap.md` to mark `4.3.1` done.
6. Update the ExecPlan `Status` field to `COMPLETE` and write the
   `Outcomes & retrospective` section.

Stage G acceptance: all `make` gates green; `coderabbit review --agent`
reports no unresolved actionable concerns; the roadmap toggle is part of
the final commit.

## Concrete steps and expected output

Each command should be executed from the repository root. The agent should
`tee` long outputs into `/tmp/$ACTION-episodic-4-3-1-source-and-presenter-profile-intake-script-generation.out`
as the user instructions require.

Initial setup:

```bash
make build 2>&1 | tee /tmp/build-episodic-4-3-1-source-and-presenter-profile-intake-script-generation.out
```

Per-milestone gate sequence (run in order, stop on first failure):

```bash
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-4-3-1-source-and-presenter-profile-intake-script-generation.out
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-4-3-1-source-and-presenter-profile-intake-script-generation.out
make nixie 2>&1 | tee /tmp/nixie-episodic-4-3-1-source-and-presenter-profile-intake-script-generation.out
make lint 2>&1 | tee /tmp/lint-episodic-4-3-1-source-and-presenter-profile-intake-script-generation.out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-4-3-1-source-and-presenter-profile-intake-script-generation.out
make test 2>&1 | tee /tmp/test-episodic-4-3-1-source-and-presenter-profile-intake-script-generation.out
make check-migrations 2>&1 | tee /tmp/check-migrations-episodic-4-3-1-source-and-presenter-profile-intake-script-generation.out
```

After each milestone closure, run `coderabbit review --agent` and resolve
all actionable concerns before the next milestone begins.

A focused smoke test exercising the new routes:

```bash
uv run python - <<'PY'
import asyncio, httpx, uuid, json
from episodic.api import ApiDependencies, create_app
from episodic.canonical.storage import SqlAlchemyUnitOfWork

async def main() -> None:
    # The smoke client expects a running app and migrated database; in
    # practice it is run from inside the integration test harness or
    # against a local dev stack.
    ...

asyncio.run(main())
PY
```

The smoke client is illustrative; for real verification, rely on the
behavioural feature in `tests/features/source_intake.feature`.

## Validation and acceptance

Quality criteria (what "done" means):

- Tests: every assertion in Milestone D6 passes under `make test` with
  `PYTEST_XDIST_WORKERS=2`. The new BDD scenarios appear in the
  `pytest-bdd` discovery output, and the new snapshots are committed under
  `tests/__snapshots__/`.
- Lint/typecheck: `make lint` (Ruff, Pylint, Hecate) and `make typecheck`
  (ty 0.0.32) are clean.
- Migrations: `make check-migrations` reports no drift.
- Documentation: `make markdownlint` and `make nixie` are clean. The
  contents index is up to date. ADR 015 cross-references the source
  documents.
- Security: object-store keys are server-generated UUIDs; no client-supplied
  path enters the filesystem; the content-type allowlist is enforced
  server-side; payload size is capped during the streaming hash; the
  idempotency store enforces first-writer-wins via SQL unique constraint.
- Observability: logs at INFO carry `idempotency_outcome`,
  `idempotency_key`, `route`, `principal_id`, `series_profile_id`,
  `ingestion_job_id`, and `upload_id`. The existing log helpers in
  `episodic.logging` are reused.

Quality method (how we check):

- Manual sequence: run the per-milestone gate sequence above; review
  `git diff --stat origin/main...HEAD` for scope drift against `Tolerances`;
  run `coderabbit review --agent` and address every actionable concern
  before merge.

## Idempotence and recovery

- Re-running `make build` or any Milestone gate is safe; the venv and uv
  cache are reused. The plan does not require any "one-shot" command.
- Re-running the migration suite is safe; Alembic detects already-applied
  revisions.
- The idempotency store is itself idempotent by construction (its whole
  purpose). A worker restart mid-request leaves the `in_flight` record
  visible; a future recovery worker (out of scope for this slice; tracked in
  ADR 009 §"Partial-failure recovery") will reconcile or expire it. Until
  the recovery worker ships, an operator can manually expire stuck records
  via a SQL update; document this in `docs/developers-guide.md`.

## Interfaces and dependencies

Be prescriptive. By the end of Stage E, the following symbols must exist at
the named paths with the listed signatures.

In `episodic/canonical/uploads.py`:

```python
class UploadState(enum.StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


@dc.dataclass(frozen=True, slots=True)
class Upload:
    id: uuid.UUID
    owner_principal_id: str | None
    content_type: str
    declared_size: int
    actual_size: int | None
    declared_sha256: str | None
    content_hash: str | None
    storage_key: str
    state: UploadState
    metadata: JsonMapping
    created_at: dt.datetime
    updated_at: dt.datetime
```

In `episodic/canonical/object_store.py`:

```python
@typ.runtime_checkable
class ObjectStorePort(typ.Protocol):
    async def put(
        self,
        stream: cabc.AsyncIterable[bytes],
        *,
        key: str,
        content_type: str,
    ) -> StoredObject: ...

    def open(
        self, key: str
    ) -> cabc.AsyncContextManager[cabc.AsyncIterable[bytes]]: ...

    async def delete(self, key: str) -> None: ...
```

In `episodic/canonical/upload_protocols.py`:

```python
class UploadRepository(typ.Protocol):
    async def add(self, upload: Upload) -> None: ...
    async def get(self, upload_id: uuid.UUID) -> Upload | None: ...
    async def mark_ready(
        self,
        upload_id: uuid.UUID,
        *,
        actual_size: int,
        content_hash: str,
    ) -> Upload: ...
    async def mark_failed(self, upload_id: uuid.UUID, reason: str) -> Upload: ...


class IngestionJobSourceRepository(typ.Protocol):
    async def add(self, source: IngestionJobSource) -> None: ...
    async def get(self, source_id: uuid.UUID) -> IngestionJobSource | None: ...
    async def list_for_job_paged(
        self,
        job_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> cabc.Sequence[IngestionJobSource]: ...
    async def count_for_job(self, job_id: uuid.UUID) -> int: ...


class IdempotencyStore(typ.Protocol):
    async def acquire(
        self,
        *,
        principal_id: str | None,
        route: str,
        key: str,
        body_hash: str,
        retention_seconds: int,
    ) -> IdempotencyOutcome: ...

    async def complete(
        self,
        record_id: uuid.UUID,
        *,
        response_status: int,
        response_body: JsonMapping,
        response_headers: JsonMapping,
    ) -> None: ...

    async def lookup(
        self,
        *,
        principal_id: str | None,
        route: str,
        key: str,
    ) -> IdempotencyRecord | None: ...
```

In `episodic/api/resources/uploads.py`:

```python
class UploadsResource:
    async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None: ...

class UploadResource:
    async def on_get(
        self, req: falcon.Request, resp: falcon.Response, upload_id: str
    ) -> None: ...
```

In `episodic/api/resources/ingestion_jobs.py`:

```python
class IngestionJobsResource:
    async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None: ...
    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None: ...

class IngestionJobResource:
    async def on_get(
        self, req: falcon.Request, resp: falcon.Response, job_id: str
    ) -> None: ...

class IngestionJobSourcesResource:
    async def on_post(
        self, req: falcon.Request, resp: falcon.Response, job_id: str
    ) -> None: ...
    async def on_get(
        self, req: falcon.Request, resp: falcon.Response, job_id: str
    ) -> None: ...
```

External dependencies used by the slice (all already present):

- `falcon>=4.2,<5.0` for the inbound adapter.
- `sqlalchemy>=2.0.34,<3.0.0` and `asyncpg>=0.20.0` (driver path via
  py-pglite in tests) for persistence.
- `hypothesis[asyncio]>=6,<7` for property tests.
- `py-pglite[async]>=0.5.3,<0.6.0` for in-memory PostgreSQL test fixtures.
- `syrupy>=5,<6` for snapshot tests.
- `pytest-bdd` for behavioural tests.
- `femtologging` via the `episodic.logging` wrapper for structured logs.

## Documentation and skills signposts

When working on this slice, load the following before touching code:

- The `hexagonal-architecture` skill (driving and driven ports, dependency
  rule, testing-strategy matrix).
- The `python-router` skill plus the smaller follow-on skills it routes to:
  - `python-data-shapes` for the new frozen dataclasses and tagged unions.
  - `python-types-and-apis` for `Protocol` design and overload signatures
    in the idempotency outcome union.
  - `python-errors-and-logging` for the new error-code envelope and
    parameterised logging.
  - `python-iterators-and-generators` for streaming hashes and async
    iteration through Falcon's request streams.
  - `python-concurrency` for the unit-of-work transactional boundary.
- The `python-testing`, `python-verification`, and `hypothesis` skills for
  the property tests for the idempotency state machine.
- The `execplans` skill for keeping this document current.
- The `leta` skill for cross-file navigation when modifying the existing
  resources.
- The `commit-message` skill for the per-milestone commits.
- The `en-gb-oxendict` skill for prose.

When in doubt about the documentation style, consult
`docs/documentation-style-guide.md`. When in doubt about the testing
conventions for asynchronous endpoints, consult
`docs/testing-async-falcon-endpoints.md` and
`docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`. When in doubt about
unit-of-work patterns, consult `docs/async-sqlalchemy-with-pg-and-falcon.md`.
For background on the langgraph and celery boundaries that 4.3.2 will
cross, consult
`docs/langgraph-and-celery-in-hexagonal-architecture.md`.

## Artefacts and notes

Significant artefacts produced by the slice:

- `docs/adr/adr-015-upload-and-idempotency-ports.md` records the new
  port designs and the deferred items.
- `tests/features/source_intake.feature` records the user-visible
  behaviour of the slice.
- `tests/__snapshots__/test_source_intake_snapshots.ambr` records the
  canonical JSON envelopes.
- New Alembic migration under `alembic/versions/` records the schema
  change.

## Alternatives considered (Logisphere pre-implementation review)

The community-of-experts review surfaced four alternatives worth recording
so a future reader can understand the negative space around the design:

1. *Single upload endpoint vs init-plus-PUT.* The slice ships only the
   multipart `POST /v1/uploads`. The init/PUT pair lands when an S3 adapter
   that actually consumes the contract lands. The `ObjectStorePort`
   keeps the door open.
2. *`READY_FOR_GENERATION` on the existing enum vs a new `intake_state`
   column vs splitting the entity.* The slice picks the middle option.
   Splitting the entity is reserved for roadmap item `4.3.2` if the
   merge and generation lifecycles diverge further.
3. *Implicit vs explicit type discriminator on source-attachment.* The
   slice ships the explicit form (`"type": "upload"` or `"type":
   "source_uri"`). Implicit discrimination was rejected because the
   domain entity already names the kind and snapshot tests would freeze
   a wire format that is hard to evolve.
4. *Idempotency store as middleware-only vs UoW-resident.* The slice
   makes the store part of the unit-of-work so the stored record commits
   in the same transaction as the created resource, which is the only
   way to honour ADR 009's first-writer-wins guarantee without races.

## Revision history

- (DRAFT, revision 2) Revised in response to the Logisphere community-of-
  experts pre-implementation review. Changes:
  - removed the two-step upload endpoints (`/v1/uploads/init` and
    `PUT /v1/uploads/{id}/bytes`) from scope and recorded the deferral;
  - split intake from merge lifecycle via a new
    `IngestionJob.intake_state` column rather than overloading
    `IngestionStatus`;
  - switched job-polling pacing from a non-idiomatic `Retry-After: 200`
    header to a `next_poll_after_seconds` body field;
  - reordered middleware so authorization runs before idempotency;
  - documented the two-phase blob write for the multipart path and the
    orphan-blob recovery recipe;
  - specified the multipart canonical body-hash algorithm and pinned a
    per-route metadata allowlist;
  - added explicit `type` discriminator to the source-attachment
    payload;
  - named the database indexes required for the polling and listing
    queries;
  - added a risk and operator recipe for `idempotency_records`
    retention;
  - added the conditional UPDATE locking strategy for the
    first-attachment intake transition and a property test asserting
    the at-most-once guarantee;
  - added the `application` and `outbound_adapter` Hecate prefix
    additions;
  - added the error-code-to-HTTP-status table;
  - added defence-in-depth (symlink escape) on the filesystem
    `ObjectStorePort` adapter;
  - clarified the Vidai Mock deferral wording.
- (DRAFT, revision 1) Initial draft authored from ADR 009, the TUI API
  design, the existing Falcon resource layout, the Hecate architectural
  enforcement configuration, the multi-source ingestion model, and a
  survey of prior art on idempotency, resumable uploads, content-hash
  discipline, job-status polling, and source attachment.
