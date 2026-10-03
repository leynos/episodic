# ADR-022: Orchestration architecture enforcement

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

For structured generation orchestration, the decision is to use dedicated
Hecate groups and structural checkpoint payload tests rather than a single
broad orchestration group or a review-only convention. This provides
deterministic import-boundary enforcement, with more detailed `pyproject.toml`
group ordering and additional fixture maintenance as accepted trade-offs.

The accepted groups are:

- `orchestration_nodes` for `episodic.orchestration._graph_nodes`,
  `episodic.orchestration._graph_protocols`,
  `episodic.orchestration._graph_state`, and `episodic.orchestration._usage`,
  allowed to depend on the `orchestration_checkpoint` DTO group and domain
  ports only.
- `orchestration` for graph builders, planning orchestration, tool execution
  policy, and `episodic.orchestration.langgraph_costs`, which records provider
  costs for the direct generation path. It may depend on application services,
  checkpoint DTOs, and `orchestration_nodes`, but not inbound or outbound
  adapters.
- `orchestration_tasks` for `episodic.worker.tasks`, allowed to depend on
  `application` and `domain_ports`; `episodic.worker.workloads.WorkloadClass`
  belongs to `domain_ports`.
- `orchestration_checkpoint` for `episodic.orchestration._dto`,
  `episodic.orchestration._action_result_dto`,
  `episodic.orchestration._result_dto`,
  `episodic.orchestration._checkpoint_payload`,
  `episodic.orchestration._checkpoint_dto`, and
  `episodic.orchestration._payload_dto` checkpoint DTO and payload
  serialization modules, allowed to depend on itself and domain-port value
  types only.

`episodic.orchestration._types` is classified as `domain_ports` so
`orchestration_nodes` and `orchestration_checkpoint` can import its
provider-neutral `ActionKind` and `ModelTier` enums under the existing
domain-port allowance. Orchestration logging call sites import `log_event`
directly from `episodic.logging`.

`episodic.worker.workloads.WorkloadClass` is the canonical domain-port-like
worker contract, so task modules can describe workload routing without
importing the Celery runtime. `episodic.worker.topology.WorkloadClass` remains
an explicit compatibility alias only.

## Consequences

### Positive

- `make lint` rejects adapter imports from LangGraph nodes, Celery tasks, and
  checkpoint payload modules before review.
- The node/builder split keeps node functions small and easy to audit.
- Checkpoint payload DTOs are guarded by both Hecate and structural tests that
  inspect field annotations.

### Negative

- Hecate group ordering now matters more. The dedicated
  `orchestration_nodes` prefix must stay before the broader `orchestration` and
  adapter prefixes.
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
