# ADR-001: Reference binding resolution algorithm

## Status

Accepted

## Context

The episodic podcast generation system allows editorial teams to bind reference
documents (style guides, host profiles, guest profiles, research briefs) to
series profiles and episode templates. Each binding associates a specific
`ReferenceDocumentRevision` with a target context.

For series-profile bindings, the domain model supports an optional
`effective_from_episode_id` field that enables time-based precedence: a new
binding can be created that "takes effect" starting with a specific episode,
while earlier episodes continue to use the previous binding for that reference
document.

When multiple bindings exist for the same reference document on a series
profile, the system must resolve which binding applies to a given episode
context. This resolution is required for:

1. Assembling the structured brief for LLM workflows (the brief must include
   exactly one revision per reference-document kind).
2. Snapshotting provenance records during ingestion (each ingestion job must
   preserve which revisions it consumed).
3. Exposing resolved bindings via API endpoints for editorial teams and
   pipeline operators.

Without a defined resolution algorithm, the system returns all bindings
regardless of `effective_from_episode_id`, making it impossible for consumers
to determine which revision applies to a specific episode.

### Episode ordering semantics

Episodes have a `created_at` timestamp (stored in both `CanonicalEpisode`
domain entity and `EpisodeRecord` ORM model). This timestamp provides a stable,
monotonic ordering dimension. The resolution algorithm uses `created_at` to
determine episode precedence when comparing `effective_from_episode_id` values.

## Decision

We implement **episode-anchored precedence resolution** with the following
algorithm:

### Resolution algorithm

Given:

- A target series profile (and optionally an episode template)
- A target episode identifier (optional; if omitted, no resolution filtering
  occurs)

The algorithm proceeds as follows:

1. **Collect all bindings** for the series profile and (if provided) the
   episode template.

2. **Group bindings by reference document**. Each binding points to a
   `ReferenceDocumentRevision`, which in turn belongs to a
   `ReferenceDocument`. Group bindings by their parent document identifier.

3. **For each reference document group**, resolve which binding applies:

   a. If **no episode context** is provided, include all bindings in the group
      (backward-compatible behavior: the caller sees all bindings without
      filtering).

   b. If an **episode context** is provided:
      - Fetch the target episode's `created_at` timestamp.
      - For each binding in the group with a non-NULL
        `effective_from_episode_id`, fetch that episode's `created_at`
        timestamp.
      - Select the binding whose `effective_from_episode_id` episode's
        `created_at` is **latest** (most recent) while still being **on or
        before** the target episode's `created_at`. This binding "took effect"
        before or at the target episode and has not been superseded by a later
        binding.
      - If no episode-specific binding matches (all have `created_at` values
        after the target episode), fall back to bindings with
        `effective_from_episode_id = NULL` (the default/catch-all binding).
      - If no binding applies at all (no episode-specific match and no default
        binding), exclude this reference document from the resolved set.

4. **Template bindings** do not support `effective_from_episode_id` (enforced
   by domain invariants). All template bindings are included directly without
   episode filtering.

5. **Merge** the resolved series-profile bindings with the template bindings
   and return the combined set.

### Resolution result

The resolution function returns a list of `ResolvedBinding` objects, each
containing:

- The `ReferenceBinding` entity (with target context and
  `effective_from_episode_id`).
- The `ReferenceDocumentRevision` entity (the content snapshot).
- The `ReferenceDocument` entity (the stable document identity with `kind`,
  `lifecycle_state`, and metadata).

This triple provides consumers with full provenance information for each
resolved binding.

## Rationale

### Why episode-anchored precedence?

Alternative considered: **simple latest-binding-wins**. In this model, the most
recently created binding for a document always applies, regardless of
`effective_from_episode_id`. This is simpler but:

- Ignores the `effective_from_episode_id` field entirely, making it useless.
- Prevents editorial teams from planning ahead (e.g., "starting with episode
  42, use this new style guide revision").
- Breaks provenance when historical episodes are regenerated: a regenerated
  episode from March would incorrectly use a binding created in April.

Episode-anchored precedence respects the temporal context of each episode. An
episode created on 2026-01-15 will always resolve to the binding that was
effective *on that date*, even if the resolution happens months later. This
preserves historical integrity and supports forward-planning workflows.

### Why use `created_at` for ordering?

Episodes lack an explicit sequence number field. The `created_at` timestamp is:

- Present in both the domain entity and ORM model.
- Monotonic within a series (episodes are created over time).
- Immutable after creation (episodes do not change their `created_at` once
  persisted).

Using `created_at` avoids introducing new schema columns and aligns with the
existing temporal semantics of the domain model.

### Why return all bindings when episode context is omitted?

The brief endpoint currently returns all bindings without filtering. Changing
this default behavior would break existing consumers. By making resolution
filtering **opt-in** (only applied when `episode_id` is explicitly provided),
we preserve backward compatibility while enabling new resolution workflows.

### Why include template bindings without filtering?

Template bindings target `EpisodeTemplate` entities, which are reusable
blueprints, not individual episodes. The `effective_from_episode_id` field is
only valid for series-profile bindings (enforced by a domain invariant).
Template bindings represent "apply this revision whenever this template is
used," not "apply starting with episode X." Including template bindings
directly in the resolved set ensures that template-bound reference documents
are always available to the pipeline.

## Consequences

### Positive

- Editorial teams can plan binding changes ahead of time by setting
  `effective_from_episode_id` to a future episode.
- Historical episodes always resolve to the bindings that were effective when
  they were created, preserving provenance integrity.
- The brief endpoint gains episode-aware resolution without breaking existing
  callers.
- Ingestion jobs can snapshot resolved bindings with full provenance
  (reference-document revision, binding context, and effective-from episode).

### Negative

- Resolution requires fetching episode `created_at` timestamps for each binding
  with `effective_from_episode_id`, increasing database load. Mitigation: batch
  episode lookups where possible, and add database indexes on
  `episodes.created_at` if profiling shows this is a bottleneck.
- The algorithm is more complex than latest-binding-wins. Mitigation:
  comprehensive unit tests and behavioral tests document the precedence rules.

### Neutral

- The resolution service is a new module
  (`episodic/canonical/reference_documents/resolution.py`), adding surface area
  to the service layer.
- The `source_documents` table gains a nullable
  `reference_document_revision_id` column, requiring an additive Alembic
  migration.

## Implementation notes

- Resolution logic is encapsulated in a new service function
  `resolve_bindings` that accepts a unit of work, series profile identifier,
  optional template identifier, and optional episode identifier.
- The brief assembly function `build_series_brief` delegates to
  `resolve_bindings` when `episode_id` is provided.
- A new API endpoint `GET /series-profiles/{profile_id}/resolved-bindings`
  exposes resolution without requiring the full brief payload.
- Provenance snapshotting is implemented in a separate service function
  `snapshot_resolved_bindings` that creates `SourceDocument` rows with
  `reference_document_revision_id` populated.

## References

- Roadmap item `1.4.3` (reference-binding resolution)
- Execution plan:
  `docs/execplans/1-4-3-reference-binding-resolution.md`
- Domain model: `episodic/canonical/domain.py`
- Storage model: `episodic/canonical/storage/models.py`
- System design document:
  `docs/episodic-podcast-generation-system-design.md`
