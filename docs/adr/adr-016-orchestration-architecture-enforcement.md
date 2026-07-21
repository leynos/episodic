# ADR-016: Orchestration architecture enforcement

## Status

Accepted, 2026-06-26. LangGraph node modules, Celery task modules, and
orchestration checkpoint payload modules are enforced as dedicated Hecate
groups.

## Date

2026-06-26.

## Context and problem statement

ADR-014 introduced Hecate as the import-boundary checker for the core hexagonal
architecture. That policy covered domain, application, adapter, and
composition-root modules, but roadmap item `2.4.5` still needed deeper
orchestration-specific checks.

The risk was concentrated in three places:

- LangGraph nodes could become convenient places to import storage, HTTP, or
  vendor Software Development Kit (SDK) adapters directly.
- Celery task modules could bypass worker composition roots and instantiate
  concrete infrastructure.
- Durable checkpoint payload DTOs could accrete canonical Object-Relational
  Mapping (ORM) entities, provider SDK responses, or other non-JSON state.

## Decision drivers

- Preserve ports as the integration boundary for orchestration code.
- Keep LangGraph framework mechanics out of node functions.
- Keep Celery task modules independent of concrete worker runtime wiring.
- Keep checkpoint payloads provider-neutral and JSON-shaped.
- Make the policy visible in deterministic tests rather than relying only on
  review discipline.

## Decision outcome

In the context of structured generation orchestration, facing boundary creep in
LangGraph nodes, Celery tasks, and durable checkpoint payloads, we decided for
dedicated Hecate groups plus structural checkpoint payload tests, and against a
single broad orchestration group or review-only convention, to achieve
deterministic import-boundary enforcement, accepting a more detailed
`pyproject.toml` group ordering and additional fixture maintenance.

The accepted groups are:

- `orchestration_nodes` for `episodic.orchestration._graph_nodes`, allowed to
  depend on orchestration DTOs and domain ports only.
- `orchestration` for graph builders, planning orchestration, and tool
  execution policy, allowed to depend on application services and checkpoint
  DTOs but not adapters.
- `orchestration_tasks` for `episodic.worker.tasks`, allowed to depend on
  domain services, domain ports, and `episodic.worker.topology.WorkloadClass`.
- `orchestration_checkpoint` for checkpoint DTO and payload serialization
  modules, allowed to depend on itself and domain-port value types only.

`episodic.worker.topology.WorkloadClass` is treated as a domain-port-like
worker contract so task modules can describe workload routing without importing
the Celery runtime.

## Consequences

### Positive

- `make lint` rejects adapter imports from LangGraph nodes, Celery tasks, and
  checkpoint payload modules before review.
- The node/builder split keeps node functions small and easy to audit.
- Checkpoint payload DTOs are guarded by both Hecate and structural tests that
  inspect field annotations.

### Negative

- Hecate group ordering now matters more. Specific orchestration prefixes must
  stay before broader orchestration and adapter prefixes.
- New orchestration fixtures must mirror production module prefixes closely or
  they will not exercise the intended group.

### Neutral

- This decision does not change the public generation orchestration API.
- Durable checkpoint storage remains an outbound adapter that implements
  `CheckpointPort`; it may import checkpoint DTOs to satisfy that port.

## References

See ADR-014 for the base Hecate adoption decision.[^1] See the orchestration
enforcement ExecPlan for the implementation milestones and validation
history.[^2]

[^1]: Hexagonal architecture enforcement:
  `docs/adr/adr-014-hexagonal-architecture-enforcement.md`
[^2]: Orchestration enforcement ExecPlan:
  `docs/execplans/2-4-5-extend-architecture-enforcement-to-orchestration-code.md`
