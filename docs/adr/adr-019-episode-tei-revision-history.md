# ADR-019: Retrievable episode TEI revision history

## Status

Accepted on 2026-08-23 for roadmap step `2.8`. This decision adopts
append-only, retrievable episode TEI history with same-transaction writes,
revision-aware reads, and restore-as-forward-write semantics.

## Date

2026-08-23

## Context and Problem Statement

Canonical episodes version their TEI P5 document with an optimistic
`tei_revision` counter and a `tei_content_hash`
([ADR-017](adr-017-no-qa-generation-run-execution-and-tei-persistence.md)).
This detects concurrent writers but retains only the latest document: each
successful write overwrites `episodes.tei_xml` and its `episodes.tei_xml_zstd`
companion, and the superseded revision is unrecoverable.

Three planned capabilities need more than conflict detection:

- The iterative refinement loop (roadmap `4.4`) produces several drafts per
  run. Its metadata persists a generation hash and a prior-draft *summary*,
  which explains why a redraft happened but cannot reproduce the superseded
  draft for comparison.
- Script projection editing (roadmap `2.7`) applies user patches to the TEI.
  The TUI/API design's security considerations require preserving "approval
  events, run events, and user edits as immutable history"; without retained
  revisions, a user edit destroys the pre-edit document.
- Editorial collaboration and approval workflows need to answer "what changed
  between revision N and N+1" and to restore a prior revision after a
  mistaken approval or a destructive edit.

The repository already has an established shape for retained history:
`series_profile_history` and `episode_template_history` are append-only rows
written by the repository in the same unit of work as the parent update, with
`(parent_id, revision)` uniqueness and typed conflict translation
([ADR-018](adr-018-explicit-versioning-and-history-strategy.md)).

## Decision

Extend the explicit history-table pattern to episode TEI.

### Schema

Add an `episode_tei_history` table:

- `id` (UUIDv7 primary key);
- `episode_id` (foreign key to `episodes`, `ON DELETE RESTRICT`);
- `tei_revision` (positive integer; unique on
  `(episode_id, tei_revision)`);
- `tei_xml` (text) and `tei_xml_zstd` (nullable bytea), mirroring the
  episode's own storage columns so large documents can be compressed;
- `tei_content_hash` (the `sha256:`-prefixed hash of the stored revision);
- `quality_mode`, `qa_status`, and `last_generation_run_id` as recorded at
  the time of the write, so each revision carries its provenance;
- `recorded_at` (timestamptz) and `actor` (text, nullable) identifying the
  writing run or editing principal.

### Write path

`SqlAlchemyEpisodeRepository.update_tei` writes the history row for the *new*
revision in the same unit of work as the optimistic episode update, after the
compare-and-set succeeds. Episode creation writes the revision-1 history row.
Every persisted revision is retained, including intermediate drafts from
refinement iterations; the history table is the durable record of what each
`tei_revision` value contained. A `(episode_id, tei_revision)` uniqueness
violation translates to the existing revision-conflict error family.

### Read path

- `GET /v1/episodes/{episode_id}/tei/history` lists revision metadata
  (revision, content hash, QA status, run identifier, actor, timestamp) with
  pagination, mirroring the profile/template history endpoints.
- `GET /v1/episodes/{episode_id}/tei?revision=N` returns the stored document
  for one revision with `Accept: application/tei+xml`, defaulting to the
  current revision when the parameter is absent. The response envelope's
  `version` field remains the episode's current `tei_revision`, so the
  optimistic-update contract from ADR-017 is unchanged.

### Restore

Restoring an earlier revision is a normal forward write: the client submits
the historical document through the existing update path with the current
`expected_revision`, producing a new revision whose history row records the
restore. History rows are never mutated or re-pointed.

### Verification requirements

The implementation must add Hypothesis properties covering arbitrary TEI write
sequences, a concurrent race with exactly one winning writer, atomicity of the
same-transaction history write, append-only history rows, and
restore-as-forward-write transitions.

### Retention

Revisions are retained indefinitely in the first implementation. Compression
via the `zstd` column reduces the storage used by each full-document revision,
but does not bound total history storage. Global history storage and each
episode's history size must be monitored. At 80% of provisioned storage or
2 GiB for one episode, operations must open a review to decide whether archival
or retention is needed through a superseding ADR. No deletion policy is adopted
by this decision.

## Rationale

- Reusing the profile/template history shape keeps one versioning idiom
  across the schema (ADR-018) and reuses the existing conflict-translation
  helpers and repository tests as templates.
- Writing history in the same transaction as the parent update makes the
  history table exactly as trustworthy as `tei_revision` itself: a revision
  number can never exist without its document, and a document can never be
  recorded for a revision that lost its compare-and-set race.
- Full-document rows were chosen over diffs: TEI documents are modest (tens
  of kilobytes), zstd compresses them well, and reconstructing a revision
  from a diff chain would put correctness of the audit trail at the mercy of
  every intermediate row.
- Restore-as-forward-write preserves the single monotonic revision sequence,
  keeps optimistic locking sound, and leaves an explicit record that a
  restore happened.

## Consequences

- Every TEI write gains one insert; the write path stays single-transaction.
  Storage grows with revision count. Compression reduces the size of each
  revision but does not provide a total-storage bound; the monitoring triggers
  above initiate an operational review without authorizing deletion.
- Roadmap `4.4.4`'s iteration metadata can reference history rows by
  `(episode_id, tei_revision)` instead of persisting draft summaries alone,
  and diffing two drafts becomes a read-side concern.
- Script projection editing (`2.7.3`) satisfies the immutable-history
  security requirement without additional machinery.
- The episode GET surface gains a revision parameter, and the TUI/API and
  system designs document the planned history read and restore paths.

## References

- [ADR-017: No-QA generation execution and TEI persistence](adr-017-no-qa-generation-run-execution-and-tei-persistence.md)
- [ADR-018: Explicit repository-written versioning and history strategy](adr-018-explicit-versioning-and-history-strategy.md)
- Migration `20260220_000002_add_profile_template_history_schema.py` (the
  pattern being extended)
- [TUI/API design: security considerations](../episodic-tui-api-design.md)
- Roadmap items `2.7`, `2.8`, and `4.4.4`
