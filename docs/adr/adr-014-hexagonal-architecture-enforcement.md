# ADR-014: Hexagonal architecture enforcement
## Status

Accepted, amended 2026-05-20 to adopt Hecate as the enforcement engine.

## Context

Episodic already documents a hexagonal architecture: canonical domain logic and
ports sit inside the boundary, while Falcon, Celery, SQLAlchemy, and provider
SDK integrations live in adapters. Ruff enforces general import hygiene, but it
does not know the repository's dependency graph. A module can therefore import
in the wrong direction while still satisfying ordinary lint rules.

The immediate need is roadmap item `1.5.4`: enforce the current service
scaffold boundaries. The deeper orchestration-specific checks for LangGraph
nodes, Celery task payloads, and checkpoint state remain roadmap item `2.4.5`.

## Decision

Adopt Hecate as the architecture enforcement engine and configure the Episodic
policy in `[tool.hecate]` in `pyproject.toml`.

Hecate parses Python files with `ast`, classifies imports into explicit module
groups, expands supported package re-exports, and emits stable diagnostics with
a rule identifier, importer, imported module, and dependency direction.
`make check-architecture` runs `hecate check`, `make lint` includes that gate
before Ruff, and CI exposes it through the existing lint workflow. Episodic uses
 `ARCH001` as Hecate's configured rule identifier to preserve diagnostic
continuity from the original checker.

The first enforced groups are:

- `domain_ports`: canonical domain models, canonical ports, ingestion ports,
  canonical constraint names, and LLM ports.
- `application`: canonical application services, profile/template services,
  reference-document services, and generation services.
- `inbound_adapter`: Falcon API modules and worker task/topology seams.
- `outbound_adapter`: SQLAlchemy storage, canonical ingestion adapters, and
  OpenAI-compatible LLM adapters.
- `composition_root`: runtime modules whose job is to wire concrete adapters,
  currently `episodic.api.runtime` and `episodic.worker.runtime`.

Composition roots are deliberate exceptions. They may import concrete inbound
and outbound adapters because their responsibility is dependency wiring. The
exception is modelled as its own group instead of weakening adapter rules.

Port contract tests mark the public protocols used by the enforcement slice as
`@runtime_checkable` and assert that the current concrete adapters satisfy the
published structural surface.

## Consequences

### Positive

- `make lint` now fails on forbidden import directions in the scoped package
  graph.
- `make test` verifies concrete adapter conformance to the public port
  protocols.
- Architecture behaviour is covered by `pytest-bdd` fixture packages, so the
  checker can evolve without rewriting production source during tests.
- CI distinguishes the architecture gate from Ruff, type checking, and tests.

### Negative

- The checker is repository-specific and must be updated when new packages or
  architecture groups are introduced.
- Runtime-checkable protocols prove method and attribute presence, not full
  semantic behaviour. Behavioural adapter tests remain necessary.

### Neutral

- Constraint-name constants used by service-layer conflict handling now live in
  `episodic.canonical.constraints`. SQLAlchemy models import those constants
  rather than owning the only copy.
- `2.4.5` remains responsible for LangGraph-node-specific policies, Celery
  checkpoint payload audits, and deeper orchestration checks.
- Hecate replaces the former repo-local `episodic.architecture` checker. New
  architecture groups are added in `pyproject.toml`; generic checker semantics
  belong upstream in Hecate.

## References

Roadmap items `1.5.4` and `2.4.5` in `docs/roadmap.md`.[^1] Original ExecPlan:
`docs/execplans/1-5-4-architectural-enforcement-for-hexagonal-boundaries.md`.[^2]
Hecate adoption ExecPlan: `docs/execplans/adopt-hecate.md`.[^3] Hecate
configuration: `[tool.hecate]` in `pyproject.toml`.[^4] Tests:
`tests/test_architecture_enforcement.py`, `tests/test_port_contracts.py`,
`tests/features/architecture_enforcement.feature`, and
`tests/steps/test_architecture_enforcement_steps.py`.[^5]

[^1]: Roadmap items `1.5.4` and `2.4.5` in `docs/roadmap.md`
[^2]: ExecPlan:
  `docs/execplans/1-5-4-architectural-enforcement-for-hexagonal-boundaries.md`
[^3]: Hecate adoption ExecPlan: `docs/execplans/adopt-hecate.md`
[^4]: Hecate configuration: `[tool.hecate]` in `pyproject.toml`
[^5]: Tests: `tests/test_architecture_enforcement.py`,
  `tests/test_port_contracts.py`,
  `tests/features/architecture_enforcement.feature`, and
  `tests/steps/test_architecture_enforcement_steps.py`
