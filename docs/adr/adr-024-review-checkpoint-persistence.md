# ADR-024: Review checkpoint persistence

## Status

Accepted, 2026-10-21.

## Context

Roadmap item `2.6.2` asks for repository contracts and Alembic migrations for
generation-run aggregates. Roadmap item `2.6.1` had already defined
`Checkpoint` as a frozen domain entity and `GenerationCheckpointPort` as its
port (ADR-015), but no adapter persisted one: the only implementation was the
in-memory reference adapter, and the table did not exist.

That gap is load-bearing rather than cosmetic. A human review checkpoint is the
one part of a generation run whose state is produced *outside* the process that
owns the run — a reviewer answers, or declines to answer, possibly hours later
and possibly from a different client. An in-memory checkpoint therefore cannot
answer the question the entity exists to answer. Persisting it needs three
decisions the domain model did not settle: how a checkpoint leaves the
`created` state under concurrent writers, how the database should mirror the
domain's validation, and how the new schema relates to the existing
`generation_runs` and `generation_events` tables.

Two options were considered and rejected. Folding checkpoint state over the
existing append-only event log — `checkpoint.created`, `checkpoint.responded`,
and a projected read model — would have removed the table, both native enums,
and the `downgrade()` debt entirely, and given one source of truth for run
history. It was rejected on three narrow grounds: `get_checkpoint` addresses a
checkpoint by bare identifier with no run id, so the fold would need an
expression or GIN index on `payload->>'checkpoint_id'`, a JSONB indexing
pattern used nowhere in this repository; it partially reverses ADR-015's
separation of `Checkpoint` from `WorkflowCheckpoint` and would therefore need
an ADR *amendment*, not merely a new ADR; and `Checkpoint` is frozen for this
slice. Reusing a mixin over the run store was also rejected — see the second
decision below.

## Decision

### Use compare-and-set for checkpoint transitions, not row locking

`GenerationCheckpointPort`'s transitions (`respond_to_checkpoint`,
`time_out_checkpoint`, `cancel_checkpoint`) write a resolved checkpoint with a
conditional statement:

```sql
UPDATE review_checkpoints SET ... WHERE id = :id AND status = 'created'
```

A `rowcount` other than 1 triggers a re-read that distinguishes the two
possible causes: an absent row raises `CheckpointNotFound`, a present one raises
`CheckpointAlreadyTerminal`.

This follows ADR-018, which records the project's concurrency strategy and
names two shapes while warning that "applying the wrong one produces either
lost updates or spurious conflicts". For concurrent writers racing on one
mutable row — which is exactly a checkpoint transition — the named house shape
is compare-and-set with a typed domain error, not `SELECT ... FOR UPDATE`. The
precedent is `SqlAlchemyEpisodeRepository.update`.

Three reasons, in ascending order of weight. It is the recorded house shape. It
buys nothing the domain does not already give: there is no sequence to allocate
here, and `Checkpoint._raise_if_terminal` already rejects a losing writer that
holds a current view. And decisively, **a compare-and-set predicate is
verifiable under `py-pglite` while lock contention is not**: `py-pglite`
supplies a single WebAssembly PostgreSQL backend, so no second session can be
admitted to contend for a row, and `FOR UPDATE` blocking cannot be observed at
all.

The same reasoning explains why `append_event` keeps `SELECT ... FOR UPDATE` on
the run row. Event append *does* allocate a sequence, and allocation order must
equal commit order for the `after_seq` replay contract's prefix stability to
hold. A checkpoint transition allocates nothing, so the two paths need
different shapes; ADR-018's warning is against applying one shape to the
other's problem, not against having both in one aggregate.

### Compose the SQL stores; do not inherit

The SQL adapter is an instantiable
`SqlAlchemyReviewCheckpointStore(session, *, runtime=None)` plus a thin
`SqlAlchemyGenerationRunPortAdapter` that holds both stores and delegates to
them explicitly. It is deliberately **not** a
`SqlAlchemyGenerationCheckpointMixin`, even though the in-memory adapter is a
mixin.

The in-memory mixin is a legitimate mixin: it shares genuine mutable in-process
state with its host — `_lock`, `_runs`, `_checkpoints` — and reads `self._runs`
*while holding the host's lock*, which cannot be expressed by delegation
without leaking the lock. The SQL equivalent shares only `_session` and
`_runtime`, both constructor-injectable in one line. There is no shared mutable
state and no shared lock, so inheritance buys nothing and costs a bidirectional
coupling: a mixin would need the host's private record lookup to validate the
parent run, which is a base class reaching upward into its subclass. It would
also re-declare `_session` and `_runtime` as bare annotations — a second
declaration site that can silently drift from `__init__`.

`AGENTS.md` says "use functions and composition". Further, ADR-015 argues
against the mixin directly: its stated benefits are that "tests can fake only
the sub-port they exercise" and that "the later SQL adapter can use different
locking and uniqueness strategies for run state, events, and checkpoints". A
non-instantiable mixin denies both, because no SQL object would implement
`GenerationCheckpointPort` alone.

Note that "one attribute on the unit of work" and "one class" are orthogonal: a
composite delegator satisfies `uow.generation_runs: GenerationRunPort` just as
well as a mixin would.

## Consequences

### Positive

- Checkpoint state survives the process that created it, which is the only way
  the port's question can be answered at all.
- The transition predicate is independently testable, because `rowcount == 0`
  is observable by a caller holding a stale view — something lock contention
  could never be under this test harness.
- The reclamation transaction that existed in three places collapses into one
  tested primitive on the composite port.

### Negative

- **`downgrade()` destroys reviewer decisions.** The migration drops
  `review_checkpoints` and both enum types. Downgrading is not a safe recovery
  step once checkpoints exist; it is data loss. The migration docstring says so.
- **Widening either enum later costs more than it looks.**
  `ALTER TYPE … ADD VALUE` *is* transactional on PostgreSQL 12 and later, so
  the upgrade runs inside an ordinary migration. But the new value cannot be
  used in the same transaction that added it, so a widening plus a backfill
  must be **two** migrations; and there is no `DROP VALUE`, so `downgrade()`
  requires a four-statement type swap:

  ```sql
  CREATE TYPE review_checkpoint_status_new AS ENUM (...);
  ALTER TABLE review_checkpoints
    ALTER COLUMN status TYPE review_checkpoint_status_new
    USING status::text::review_checkpoint_status_new;
  DROP TYPE review_checkpoint_status;
  ALTER TYPE review_checkpoint_status_new RENAME TO review_checkpoint_status;
  ```

  Reversibility is a standing criterion for this repository, so any future enum
  widening must carry that recipe. There is no `ALTER TYPE ... ADD VALUE`
  precedent anywhere in `alembic/versions/`.
- **The naming is asymmetric, deliberately.** The table is
  `review_checkpoints`, with enums `review_checkpoint_status` and
  `review_checkpoint_action`, but the entity remains
  `episodic.canonical.domain.Checkpoint` and the port remains
  `GenerationCheckpointPort`. The table name is chosen to avoid a real
  collision: `docs/adr/adr-007-durable-generation-checkpoints.md` is *titled*
  "Durable generation checkpoints" and is entirely about `WorkflowCheckpoint`,
  so a developer grepping for "generation checkpoint" would land on the wrong
  ADR. Renaming the entity and port to `ReviewCheckpoint` and
  `ReviewCheckpointPort` is a recorded follow-up.
- **A returned entity is provisional until its unit of work commits.** The
  adapters return the domain object the transition computed, not a re-read of
  the committed row. A caller that ignores `await uow.commit()` holds a
  correct-looking entity and a database that disagrees with it. The unit of
  work emits a `canonical_unit_of_work.closed_with_uncommitted_changes` warning
  when a live session closes with pending writes, but the warning is a
  diagnostic, not a guarantee.

### Neutral

- **`options` is stored as `JSONB`, with a shape guard.** `postgresql.ARRAY` is
  used nowhere in this repository, and `JSONB` is the established convention
  and preserves array order, which is all `options` needs. But JSONB does not
  enforce element type, and the domain validator will not catch the gap: if the
  column holds the JSON string `"approve"`, a naive `tuple(record.options)`
  yields seven single-character strings, all non-blank, passing every domain
  check silently. So the column carries
  `CHECK (jsonb_typeof(options) = 'array' AND jsonb_array_length(options) > 0)`
  and the record-to-domain mapper validates element types explicitly rather
  than trusting the domain.
- **Status and action are native PostgreSQL enums**, consistent with every
  other enum in this schema. The costs are recorded under Negative above.
- **The timestamp column is `resolved_at`; the domain field is
  `responded_at`.** `Checkpoint.time_out(at)` and `.cancel(at)` both write
  `responded_at=at` while leaving `responded_by` and `response_action` unset.
  The overloading is semantically fine — it is one field, "the instant this
  checkpoint left `created`" — but the name would lie: a database administrator
  reading `responded_at NOT NULL` beside `status = 'timed_out'` would conclude
  the data is corrupt. The mapper is an existing named seam, so bridging costs
  one line each way, and a column name is far more expensive to change later
  than a dataclass field. Renaming `Checkpoint.responded_at` to `resolved_at`
  is a recorded follow-up.
- **Only the forward half of the responded-fields constraint is enforced.**
  `Checkpoint._validate_responded_fields` enforces one direction only: `status`
  is `responded` implies `resolved_at`, `responded_by`, and `response_action`
  are all set. It enforces nothing in reverse, so
  `Checkpoint(status=timed_out, response_action=approve, ...)` is a legal
  domain value. A symmetric CHECK would make the database stricter than the
  domain, and under the shared contract suite that value would round-trip in
  memory and raise `IntegrityError` in SQL — collapsing the interchangeability
  claim on an input the test factories could easily generate. The domain is
  frozen for this slice, so the forward implication is the constraint, and the
  converse is deliberately not enforced. Tightening the domain validator and
  adding the reverse constraint should be done together.
- **Deletion is `RESTRICT`, not `CASCADE`.** The checkpoint's foreign key to
  `generation_runs` is declared `ondelete="RESTRICT"`, so a run that has
  checkpoints cannot be deleted. This is ADR-018's deletion policy for
  audit-bearing rows: the row *is* the audit record of a reviewer's decision.
- **A review checkpoint is not a versioned aggregate and needs no history
  table.** ADR-018 requires new versioned aggregates to follow explicit
  repository writes in one unit of work, typed conflict errors, append-only or
  content-addressed immutability, and pinning at consumption boundaries. A
  review checkpoint is a state machine that transitions from `created` to a
  terminal state exactly once; it has no revision counter, no successive
  versions, and nothing to pin. The response fields are written once and never
  overwritten, so the row is the audit record and a separate
  `review_checkpoint_history` table would duplicate it. The deletion half of
  ADR-018's policy does apply — see the `RESTRICT` consequence above.
- **Nothing schedules lease reclamation.** The composite port gains a
  `fail_expired_leases` primitive, but no worker calls it. Until 2.6.3 supplies
  an entry point, the manual `psql` procedure in the developers' guide remains
  the operative recovery path.

## References

See roadmap item `2.6.2`[^1], the TUI API design[^2], the generation-run port
split ADR[^3], the durable orchestration checkpoint ADR[^4], and the explicit
versioning and history strategy ADR[^5].

[^1]: Roadmap item `2.6.2` in `docs/roadmap.md`
[^2]: TUI API design: `docs/episodic-tui-api-design.md`
[^3]: Generation-run port split:
  `docs/adr/adr-015-generation-run-port-split.md`
[^4]: Durable orchestration checkpoint ADR:
  `docs/adr/adr-007-durable-generation-checkpoints.md`
[^5]: Explicit versioning and history strategy:
  `docs/adr/adr-018-explicit-versioning-and-history-strategy.md`
