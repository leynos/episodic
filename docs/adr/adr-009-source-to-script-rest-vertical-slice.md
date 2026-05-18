# Architectural decision record (ADR) 009: Source-to-script REST vertical slice

## Status

Accepted. On 2026-05-14, the project adopted a two-task vertical slice for
source upload, presenter-profile intake, draft script generation, and Text
Encoding Initiative (TEI) P5 retrieval through the Application Programming
Interface (API).

## Date

2026-05-14.

## Context and problem statement

Episodic has implemented much of the canonical content foundation: series
profiles, episode templates, reusable reference documents, reference bindings,
structured briefs, and internal ingestion and generation services. The missing
product slice is still fragmented across roadmap items for uploads, ingestion
jobs, generation runs, episode endpoints, and export jobs.

The next useful integration milestone is narrower than the full editorial
workflow. An API client must be able to upload a show source document, such as
a research paper, provide presenter profiles, request script generation without
running the full quality assurance (QA) loop, and retrieve the resulting TEI-P5
XML. This must be available through resource-oriented JSON/Representational
State Transfer (REST) operations, with long-running work exposed as pollable
resources rather than hidden synchronous commands.

The repository is still pre-v0.1.0, so the design does not need to preserve the
existing unversioned API surface. The implementation should converge on the
target `/v1` contract instead of carrying compatibility obligations that do not
yet exist.

## Decision drivers

- Deliver one narrow, usable client workflow instead of implementing upload,
  ingestion, generation, and export layers independently.
- Preserve TEI-P5 as the canonical episode artefact while allowing JSON
  control-plane operations around uploads, jobs, and run status.
- Keep presenter profiles aligned with the existing reusable reference-document
  model rather than creating a separate presenter table or endpoint family.
- Make no-QA script generation explicit and auditable rather than an implicit
  shortcut around the generation graph.
- Use standard REST resource semantics, idempotency keys for retryable
  side-effecting requests, and pollable long-running operation resources.
- Avoid pre-v0.1.0 compatibility weight by making `/v1` the implementation
  target for the vertical slice.

## Requirements

### Functional requirements

- Clients can upload one or more source documents and attach them to an
  ingestion job for a series or target episode.
- Clients can create presenter profiles as reusable host or guest profile
  reference documents, create immutable revisions, and bind those revisions to
  the generation context.
- Clients can create a generation run for an episode with an explicit quality
  mode that bypasses full QA for this vertical slice.
- Clients can poll ingestion and generation resources until the generated
  script is persisted to the canonical episode TEI.
- Clients can retrieve the final TEI-P5 XML as a downloadable REST artefact,
  and can retrieve JSON metadata containing the content hash and revision.

### Technical requirements

- Control-plane requests and status responses use JSON over REST.
- TEI download uses the registered `application/tei+xml` media type from
  [RFC 6129][^1].
- Side-effecting `POST` requests that create uploads, ingestion jobs, source
  attachments, and generation runs accept `Idempotency-Key`.
- Long-running ingestion and generation operations return pollable resources
  with `202 Accepted`, `Location`, and `Retry-After` semantics where the work
  cannot complete in the initial request.
- The implementation respects the hexagonal boundary rules in
  [ADR 006][^2] and the resumable workflow rules in [ADR 007][^3].

## Options considered

### Option A: Keep upload, ingestion, generation, and export tasks separate

This matches the current roadmap shape. It is straightforward to assign, but
does not produce the requested end-to-end client workflow until several
horizontal slices are all complete.

### Option B: Define a two-task vertical slice

This groups the minimum intake path into one task and the minimum generation
plus TEI retrieval path into a second task. It keeps the work review-sized
while making the dependency between source intake and script generation
explicit.

### Option C: Add a single compound "source to TEI" task

This would describe the user journey directly, but it would be too large for a
normal review. It would also mix object upload, ingestion status, presenter
profiles, generation-run semantics, and TEI retrieval into one change.

| Topic        | Option A             | Option B                | Option C           |
| ------------ | -------------------- | ----------------------- | ------------------ |
| Value        | Arrives late         | Arrives after two tasks | Oversized task     |
| Review size  | Small but fragmented | Review-sized            | Too large          |
| Dependencies | Spread across phases | Explicit                | Hidden inside task |
| Roadmap fit  | Existing structure   | Best fit                | Poor fit           |

_Table 1: Comparison of vertical-slice task boundaries._

## Decision outcome

Choose Option B. The roadmap will represent the source-to-script API as two
vertical-slice tasks:

1. Implement source and presenter-profile intake for script generation.
2. Implement no-QA generation runs and TEI-P5 retrieval.

The first task owns upload resources, ingestion-job source attachment, and
presenter-profile use through existing reusable reference-document semantics.
The second task depends on the first task and owns the generation-run contract,
the explicit no-QA quality mode, run polling, and TEI retrieval.

The target API is `/v1`. Existing unversioned routes do not need preservation
when the vertical slice is implemented because the project has not reached
v0.1.0.

## API contract decisions

- Presenter profiles remain reusable reference documents. Host presenters use
  `kind=host_profile`; guest presenters use `kind=guest_profile`. The API
  design may describe these as presenter profiles for user comprehension, but
  the canonical data model remains the reusable reference-document model.
- Generation-run creation accepts `quality_mode`. The first implemented value
  for this slice is `draft_without_qa`; later full editorial workflows may add
  or promote `qa_gated` without changing the run resource shape.
- A `draft_without_qa` run must record that QA was skipped, the actor that
  requested the bypass, and a rationale string supplied by the client. The
  resulting TEI is a draft artefact until a later approval workflow marks it
  otherwise.
- `GET /v1/episodes/{episode_id}/tei` returns a JSON envelope by default,
  including episode id, TEI header id, TEI XML, content hash, version, and the
  generation run that last wrote the script.
- `GET /v1/episodes/{episode_id}/tei` with
  `Accept: application/tei+xml` returns the XML representation directly with
  `Content-Disposition: attachment`, so clients can download a TEI-P5 file
  without a separate export-job dependency.
- Export jobs remain available for later bundled deliverables, but a TEI file
  download must not require the audio/export pipeline.

## Architectural rationale

The decision follows resource-oriented REST guidance[^6] by modelling uploads,
ingestion jobs, generation runs, and TEI documents as resources rather than as
command endpoints. It follows common long-running operation practice[^7] by
turning asynchronous work into pollable resources. It also follows idempotent
request practice[^8] by making client-provided idempotency keys part of
side-effecting `POST` requests.

Keeping TEI retrieval on the episode resource avoids coupling the first script
generation slice to export jobs. The JSON envelope supports clients that need
metadata and hashes, while the `application/tei+xml` representation supports
the literal file-download case defined by TEI media-type prior art.

## Known risks and limitations

- No-QA generation can create plausible but unchecked scripts. The API must
  mark these runs and TEI revisions as draft output, with QA explicitly skipped.
- The first slice does not replace later QA artefact persistence, approval
  workflows, audio generation, or export bundles.
- Presenter terminology may drift from the canonical `host_profile` and
  `guest_profile` document kinds. Documentation must use "presenter profile" as
  a user-facing umbrella while retaining the canonical kinds in schemas.
- Direct TEI download may need additional authorization controls before
  multi-tenant production use because source documents and presenter profiles
  can contain confidential or copyrighted material.

## References

See also the system design[^4] and TUI API design.[^5]

[^1]: [RFC 6129: The `application/tei+xml` media type](https://datatracker.ietf.org/doc/html/rfc6129)
[^2]: [ADR 006: Hexagonal architecture enforcement](adr-006-hexagonal-architecture-enforcement.md)
[^3]: [ADR 007: Durable generation checkpoints](adr-007-durable-generation-checkpoints.md)
[^4]: [Episodic podcast generation system design](../episodic-podcast-generation-system-design.md)
[^5]: [Episodic TUI API design](../episodic-tui-api-design.md)
[^6]: [Microsoft REST API design best practices](https://learn.microsoft.com/en-us/azure/architecture/best-practices/api-design)
[^7]: [Microsoft Fabric long-running operation pattern](https://learn.microsoft.com/en-us/rest/api/fabric/articles/long-running-operation)
[^8]: [Stripe idempotent request guidance](https://docs.stripe.com/api/idempotent_requests)
