# ADR 028: Generation-run REST completion

## Status

Proposed for roadmap item `2.6.3`; pending implementation review.

## Context

Roadmap item `2.6.3` requires episode-scoped run creation and listing, run
retrieval, paginated event retrieval and review-checkpoint submission. The
existing API already creates the first run from a ready ingestion job and
supports owner-scoped run and event reads. The API design's proposed POST route
is ingestion-job-scoped, while the roadmap also requires an episode-scoped
POST. These routes represent separate workflows: initial episode
materialization and regeneration of an existing episode.

The existing generation-run port and SQL adapter support episode listing,
checkpoint retrieval and compare-and-set response transitions. REST integration
must preserve their hexagonal boundary, authenticated ownership, durable
idempotency and atomic persistence behaviour.

## Proposed decision

### Keep initial creation and episode regeneration distinct

Keep `POST /v1/ingestion-jobs/{ingestion_job_id}/generation-runs` for initial
materialization. Add `POST /v1/episodes/{episode_id}/generation-runs` for
regeneration after an episode has a successful generation run. The new request
uses the source bundle pinned on that successful run; it does not rematerialize
the episode or accept an actor or source bundle from the request body. The
authenticated principal supplies the actor. Runs without a successful prior
generation remain on the initial ingestion workflow until another contract is
designed.

The episode collection read authorizes access through the existence of at least
one run for that episode owned by the authenticated principal. This includes
pending and failed initial runs, whose episode pointer may not yet have been
written by successful TEI persistence. An authorized collection with no runs
matching its optional status filter returns an empty page. Authorization,
episode, and status predicates apply in storage before both pagination and
counting. Results retain the existing `(created_at, id)` order. `total` is an
observation from the current read; offset pages and count are not promised to
share a snapshot while run statuses change.

### Scope idempotency to the episode regeneration operation

Use `generation_run.episode_create` as the operation identity. The HTTP request
fingerprint includes the target episode identifier and every accepted semantic
request field. Scope the durable idempotency key with a bounded digest of the
operation, episode identifier, and raw key; keep the principal as the separate
uniqueness component. This leaves the existing initial-creation key scope
unchanged. Persist a server-owned creation-scope and target marker in run
configuration. On durable-key reuse, compare that marker, target episode,
principal, and every accepted semantic input before reusing the run; a digest
that happens to equal a key supplied on the initial-creation route must not
replay the wrong resource.

Initial creation must also reject a run carrying the episode-creation marker
while preserving existing initial-route replay. Resolve durable-key reuse
before checking whether the episode still has a successful source run, so a
retry retains its original pinned source. The repository's unique constraint
remains the race arbiter for simultaneous creation attempts. The marker is
server-owned metadata: exclude it from HTTP configuration serialization and
provider prompt inputs.

Reject canonical request bodies larger than 16 KiB before any side effect. For
24 hours, identical requests replay the stored HTTP response and a changed
fingerprint conflicts. After that response window, the durable run may be
returned with its current serialized snapshot rather than the original response
snapshot. Durable reuse for the same principal, operation, episode, and key
must compare every stored client input before returning the run. The first
run's source bundle remains pinned even if episode history changes. A reused
pending run may be offered to the existing launcher, whose claim transition
prevents duplicate execution. A reused running or terminal run is not
relaunched.

### Submit review responses as one atomic application operation

The application operation authorizes the parent run and verifies that the
checkpoint's `generation_run_id` matches it. It accepts only a valid
`CheckpointAction` that is listed in the checkpoint's options. The
authenticated principal and server clock supply responder and response time;
clients cannot supply those fields.

Within one unit of work, append `checkpoint.responded` first, then apply the
checkpoint's existing compare-and-set response transition, and commit both
writes together. Event append takes the parent-run lock before the checkpoint
transition. The locked run read must refresh any already-loaded identity-map
value before checking terminal status. A failed transition or commit leaves
neither the response nor its event durable. A terminal run or checkpoint
returns a conflict; a missing or mismatched child checkpoint is concealed as
not found. Success returns the resolved checkpoint after commit. Submitted
notes or patch data are recorded as review payload; they do not execute a TEI
patch or resume a workflow.

Verification must include a targeted real-PostgreSQL test for the new
parent-lock and checkpoint compare-and-set interaction. Py-PGlite remains
useful for sequential persistence, rollback and validation, but cannot
establish lock contention or concurrent writer ordering. Run the focused
PostgreSQL test with the `slow` marker and isolated database specified by
verification obligation V4 in the execution plan. The broader concurrency tier
remains roadmap item `2.6.7`.

## Alternatives considered

- Replacing the ingestion-job POST with the episode POST was rejected because
  initial creation must materialize an episode from a ready ingestion job.
- Calling one Falcon resource from the other was rejected because it couples
  inbound adapters and obscures their distinct creation policies.
- Committing the checkpoint response separately from its event was rejected
  because either write could then persist without the other.

HTTP adapters parse and validate transport data, serialize responses, and own
idempotent HTTP response storage. Framework-free application services own the
creation and checkpoint policies and depend on domain ports and a unit of work.
Verify that the application module is included in Hecate's existing
architecture classification; change its configuration only if it is not already
covered.

## Consequences

### Positive

- The two POST routes describe different workflows without route aliases or
  cross-calls between Falcon resources.
- The collection exposes initial progress even before TEI persistence sets the
  episode's last successful run pointer.
- Run filtering cannot leak another principal's rows through page contents or
  totals.
- Checkpoint state and its event are durable together, with the existing
  checkpoint compare-and-set contract retained.

### Negative

- Episode-scoped regeneration is limited to episodes with a successful prior
  run. Supporting episodes whose initial generation failed needs an explicit
  source-selection contract.
- Status-filtered totals and offset pages are observational under changing run
  state rather than snapshot-consistent.
- A targeted real-PostgreSQL test is required for the new lock protocol;
  Py-PGlite cannot prove lock contention or concurrent writer ordering. The
  broader roadmap item `2.6.7` concurrency tier remains deferred.
- Existing checkpoint storage metrics may count attempted transitions before
  the encompassing unit of work commits. Request tracing must report success
  only after commit; changing metric commit semantics is outside this proposal.

## References

- [Roadmap item 2.6.3](../roadmap.md)
- [Generation-run REST contract](../episodic-tui-api-design.md#generation-runs)
- [No-QA generation-run execution](adr-017-no-qa-generation-run-execution-and-tei-persistence.md)
- [Review-checkpoint persistence](adr-024-review-checkpoint-persistence.md)
- [Hexagonal architecture enforcement](adr-014-hexagonal-architecture-enforcement.md)
- [REST endpoint execution plan](../execplans/2-6-3-rest-endpoints-for-generation-runs.md)
