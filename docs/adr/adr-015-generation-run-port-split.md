# ADR-015: Generation-run port split

## Status

Accepted, 2026-06-04.

## Context

Roadmap item `2.6.1` introduces user-facing generation runs: the resource a
future Terminal User Interface (TUI) or REST client will create when asking
Episodic to turn ingested source material into a TEI P5 script. The TUI design
document originally described a single `GenerationRunPort` interface covering
run state, event appends, and human review checkpoints.

Those operations have different consistency needs. Run state updates belong to
the aggregate root, event appends require per-run sequence allocation, and
checkpoint responses must enforce terminal lifecycle transitions.

## Decision

Split the port surface into three cohesive protocols in
`episodic.canonical.generation_run_ports`:

- `GenerationRunRepository` for run creation, lookup, listing, and lifecycle
  updates.
- `GenerationEventLog` for append-only event storage with adapter-allocated
  `EventSeq` values.
- `GenerationCheckpointPort` for creating human review checkpoints and
  recording reviewer responses.

Expose `GenerationRunPort` as a composite protocol that inherits the three
sub-ports. The composite keeps the design-document language stable while
allowing later SQL and REST work to test or replace each responsibility
independently.

## Consequences

### Positive

- Event sequence allocation is owned by the adapter, not the caller.
- Tests can fake only the sub-port they exercise.
- The later SQL adapter can use different locking and uniqueness strategies for
  run state, events, and checkpoints.

### Negative

- The port surface has more names to document than the original monolithic
  interface.

### Neutral

- `episodic.canonical.domain.Checkpoint` is a user-facing review checkpoint.
  It remains distinct from `episodic.orchestration.WorkflowCheckpoint`, which
  stores internal LangGraph suspend/resume state.

## References

See the roadmap item[^1], the TUI API design[^2], and the durable orchestration
checkpoint ADR.[^3]

[^1]: Roadmap item `2.6.1` in `docs/roadmap.md`
[^2]: TUI API design: `docs/episodic-tui-api-design.md`
[^3]: Durable orchestration checkpoint ADR:
  `docs/adr/adr-007-durable-generation-checkpoints.md`
