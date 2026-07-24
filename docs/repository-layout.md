# Repository layout

This document explains the major paths in the Episodic repository. It is the
canonical location for tree and path-responsibility guidance; maintainer
workflows belong in the [developers' guide](developers-guide.md), and product
or architecture rationale belongs in the design documents.

## Top-level tree

The following tree is an orientation sketch, not a complete file listing.

```plaintext
.
├── .github/
├── .rules/
├── alembic/
├── docs/
│   ├── adr/
│   └── execplans/
├── episodic/
│   ├── api/
│   ├── canonical/
│   ├── generation/
│   ├── llm/
│   ├── orchestration/
│   ├── qa/
│   └── worker/
├── infra/
│   ├── clusters/
│   ├── gitops-template/
│   └── modules/
├── tests/
│   ├── canonical_storage/
│   ├── features/
│   ├── fixtures/
│   └── steps/
├── AGENTS.md
├── Makefile
├── README.md
└── pyproject.toml
```

_Figure 1: Simplified repository tree for contributor orientation._

## Path responsibilities

| Path             | Responsibility                                                                             |
| ---------------- | ------------------------------------------------------------------------------------------ |
| `.github/`       | Continuous Integration (CI), release, dependency, and infrastructure workflow definitions. |
| `.rules/`        | Python-specific local coding rules referenced by `AGENTS.md`.                              |
| `alembic/`       | Database migration environment and versioned schema migrations.                            |
| `docs/`          | Long-lived project documentation, design material, guides, plans, and decision records.    |
| `episodic/`      | Python package source for the Episodic application and domain logic.                       |
| `infra/`         | Infrastructure-as-code modules, cluster configuration, and GitOps templates.               |
| `tests/`         | Unit, behavioural, integration, fixture, and snapshot test assets.                         |
| `AGENTS.md`      | Repository-local agent and contributor operating instructions.                             |
| `Makefile`       | Canonical local quality-gate and development commands.                                     |
| `README.md`      | Public project overview, setup pointer, and high-level documentation entrypoint.           |
| `pyproject.toml` | Python package metadata, dependencies, and tool configuration.                             |

_Table 1: Top-level path responsibilities._

## Source package layout

The `episodic/` package is grouped by feature and boundary:

- `episodic/api/` contains the Falcon HTTP application, request handlers,
  serializers, resource wiring, and runtime dependencies.
- `episodic/canonical/` contains canonical domain models, ports, storage
  adapters, pagination, ingestion services, profile templates, and reference
  document functionality.
- `episodic/generation/` contains generation services for show notes, chapter
  markers, guest biographies, draft scripts, generation-run launching, and
  Text Encoding Initiative (TEI) payloads.
- `episodic/llm/` contains large language model ports and OpenAI adapter code.
- `episodic/orchestration/` contains workflow state, checkpoint payloads,
  suspend-and-resume support, and executor integration.
- `episodic/qa/` contains quality-assurance evaluators and related support
  code.
- `episodic/worker/` contains Celery worker entrypoints and task wiring.

Domain logic should remain behind ports and adapters rather than reaching
directly across infrastructure boundaries. Architecture enforcement lives in
the codebase and is described in
[ADR 014](adr/adr-014-hexagonal-architecture-enforcement.md).

## Documentation layout

The `docs/` directory is the project knowledge base:

- `docs/contents.md` indexes the documentation set.
- `docs/users-guide.md` records user-facing behaviour.
- `docs/developers-guide.md` records maintainer-facing operating guidance.
- `docs/documentation-style-guide.md` defines documentation conventions.
- `docs/roadmap.md` tracks delivery phases, tasks, and acceptance criteria.
- `docs/*-design.md` files explain system, subsystem, and infrastructure
  design.
- `docs/adr/` contains accepted architectural decision records.
- `docs/execplans/` contains execution plans for non-trivial implementation
  work.

The historical `docs/adr-001-pedante-evaluator-contract.md` file remains at the
top level of `docs/`; new ADRs should use the `docs/adr/` directory unless a
migration explicitly changes the existing convention.

## Test layout

The `tests/` directory mirrors the system's test surfaces:

- `tests/features/` stores behavioural feature files.
- `tests/steps/` stores pytest-bdd step implementations.
- `tests/steps/no_qa_generation_slice_support.py` owns the live Vidai Mock and
  application-stack support for the source-to-script behavioural slice.
- `tests/fixtures/` stores shared fixture data and architecture-check fixtures.
- `tests/canonical_storage/` stores persistence-focused tests for canonical
  storage behaviour.
- `tests/__snapshots__/` and nested `__snapshots__/` directories contain
  snapshot expectations managed by the test suite.

Generated caches and virtual environments, including `.venv/`, `.uv-cache/`,
`.ruff_cache/`, and pytest caches, are local artefacts and are not part of the
authoritative repository structure.

## Infrastructure layout

The `infra/` directory separates deployable environments from reusable
infrastructure modules:

- `infra/clusters/` contains environment-specific cluster configuration for
  sandbox, staging, and production.
- `infra/gitops-template/` contains FluxCD-oriented GitOps repository
  templates.
- `infra/modules/` contains reusable OpenTofu or Terraform modules for Digital
  Ocean Kubernetes Service (DOKS), CloudNativePG, FluxCD, observability,
  RabbitMQ, Traefik, Valkey, Vault, External Secrets Operator, and certificate
  management concerns.

Infrastructure changes should keep environment-specific configuration outwith
reusable modules unless a value is genuinely cluster-specific.
