# ADR-018: Explicit repository-written versioning and history strategy

## Status

Accepted on 2026-08-23. This retrospective record establishes explicit,
repository-written versioning, named concurrency shapes, immutable history,
and version pinning at consumption boundaries. It consolidates decisions taken
piecemeal across roadmap items `1.4.1`, `2.2.6`, `2.2.8`, `2.4.4`, `2.6.1`,
and `4.3.2` so the versioning approach exists as one recorded decision rather
than an unstated convention.

## Date

2026-08-23

## Context and Problem Statement

Episodic versions several kinds of state: series profiles and episode
templates, reusable reference documents, canonical episode TEI, pricing rate
cards, and suspended workflow checkpoints. Each mechanism was introduced by a
separate ExecPlan and, in some cases, a separate ADR fragment, but no single
record states the shared strategy or the alternatives it displaces. The
absence became visible when the question "are we using
`sqlalchemy-continuum`?" could only be answered by exhaustive search.

The evidence base for this record is the ExecPlan decision logs
([2.2.6 profile and template models](../execplans/2-2-6-series-profile-and-episode-template-models.md),
[2.2.6 reference-document model](../execplans/2-2-6-define-reusable-reference-document-model.md),
[2.4.4 cost accounting](../execplans/2-4-4-cost-accounting-and-usage-metering.md),
[4.3.2 no-QA generation](../execplans/4-3-2-no-qa-generation-runs-and-tei-p5-retrieval.md)),
the migrations that introduced the schemas (`20260220_000002`,
`20260624_000011`), and the ADR fragments that already cover individual
mechanisms ([ADR-001](adr-001-reference-binding-resolution-algorithm.md),
[ADR-007](adr-007-durable-generation-checkpoints.md),
[ADR-015](adr-015-cost-accounting-ports-and-pricing-engine.md),
[ADR-017](adr-017-no-qa-generation-run-execution-and-tei-persistence.md)).

## Decision

Versioning is hand-rolled per aggregate using explicit repository writes. No
object-relational mapping (ORM) versioning library
(`sqlalchemy-continuum`, `sqlalchemy-history`), database trigger, or temporal
table is used anywhere. The strategy decomposes into two distinct
concurrency-control shapes and three shared invariants.

### Two concurrency-control shapes

**History-insert arbitration for profile and template writers.**
`SeriesProfileRecord` and `EpisodeTemplateRecord` do not carry a
`lock_version`. Their repositories read the latest history revision, update
the parent, and use the unique `(parent_id, revision)` history-row insert to
arbitrate concurrent writers. A losing insert is translated to a typed domain
conflict rather than silently overwriting history.

**Compare-and-set for concurrent writers racing on one mutable row.**
Canonical episodes carry `tei_revision` with a positive-integer check
constraint. Updates are conditional (`UPDATE … WHERE revision = expected`) and
a stale expectation raises a typed domain error (`RevisionConflictError`,
`EpisodeRevisionConflictError`) rather than overwriting silently.

**Insert-once-then-reuse for duplicate deliveries of one logical operation.**
Workflow checkpoints and the source-intake idempotency store insert under a
deterministic key and let the database unique constraint arbitrate: on
conflict, the first row is loaded and reused. Generation-run events are
append-only and allocate a fresh sequence entry; duplicate-event idempotency
is future work. This is idempotency, not optimistic locking, and the shapes are
deliberately not conflated.

### Three shared invariants

**History is written explicitly, in the same unit of work.** Where change
history is retained (`series_profile_history`, `episode_template_history`),
the repository writes the immutable history row alongside the parent update
within one transaction — with an explicit `flush()` where the history row's
foreign key requires the parent first. Nothing is captured by session event
listeners; the domain can see and test every write.

**Immutable content is content-addressed or append-only, not
permission-protected.** Reference-document revisions deduplicate on
`(document_id, content_hash)`; pricing snapshots are content-hashed documents
whose hash collisions raise `PricingSnapshotCollisionError`; history tables
are insert-only with `(parent_id, revision)` uniqueness. Immutability is a
schema property the application enforces, not a database privilege.

**Deletion policy protects the audit trail.** References from durable records
to the immutable documents that explain them use `ON DELETE RESTRICT`
(cost-ledger rows to pricing snapshots), while parent roll-up references use
`ON DELETE SET NULL`, so pruning cannot destroy the explanation for persisted
history.

### Consumers pin versions rather than resolving "latest"

Where downstream state depends on versioned inputs, the consumed version is
pinned at consumption time: reference bindings pin one document revision
(ADR-001 explicitly rejected latest-binding-wins because it breaks provenance
for regenerated episodes), and generation runs pin one pricing snapshot per
provider operation before recording costs (ADR-015), so suspended and resumed
work reprices identically.

## Rationale

- The hexagonal architecture rule that adapters perform explicit writes the
  domain can reason about is incompatible with listener-driven versioning,
  which mutates state outside any port contract.
- The stack is `AsyncSession` throughout; ORM versioning libraries have
  historically had weak or absent async support.
- Versioning needs differ per aggregate: profiles and templates need
  retrievable change history, reference documents need immutable snapshots,
  episodes (currently) need only conflict detection, and cost records need
  append-only provenance. A uniform library would version everything the same
  way; the per-aggregate approach lets each mechanism carry exactly the
  semantics its consumers require.
- Typed conflict errors at the repository boundary
  (`is_revision_conflict_integrity_error` and its siblings) give API layers
  deterministic conflict responses instead of leaked driver exceptions.

The recurring cost is acknowledged: each new versioned aggregate writes its
own history rows, constraints, and conflict translation. That cost buys
auditability, testability without ORM instrumentation, and freedom to vary
semantics per aggregate.

## Consequences

- New versioned aggregates must follow this pattern: explicit repository
  writes in one unit of work, typed conflict errors, append-only or
  content-addressed immutability, and pinning at consumption boundaries.
  Introducing an ORM versioning library or trigger-based auditing requires a
  superseding ADR.
- Canonical episode TEI currently retains only the latest revision;
  `tei_revision` provides conflict detection without retrievable history.
  [ADR-019](adr-019-episode-tei-revision-history.md) closes that gap using
  the history-table shape this record establishes.
- The two concurrency shapes (compare-and-set versus insert-once-then-reuse)
  should be named in reviews; applying the wrong one produces either lost
  updates or spurious conflicts.

## References

- [ADR-001: Reference binding resolution algorithm](adr-001-reference-binding-resolution-algorithm.md)
- [ADR-007: Durable generation checkpoints](adr-007-durable-generation-checkpoints.md)
- [ADR-015: Cost accounting ports and pricing engine](adr-015-cost-accounting-ports-and-pricing-engine.md)
- [ADR-017: No-QA generation execution and TEI persistence](adr-017-no-qa-generation-run-execution-and-tei-persistence.md)
- Migrations `20260220_000002_add_profile_template_history_schema.py` and
  `20260624_000011_add_episode_tei_revisioning.py`
- [System design: canonical content schema](../episodic-podcast-generation-system-design.md)
