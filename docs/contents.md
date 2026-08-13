# Documentation contents

This index lists the documentation set for Episodic. Start here when choosing
the source of truth for product behaviour, architecture, maintenance practice,
or delivery planning.

## Orientation

- [Documentation contents](contents.md) - this index for the documentation set.
- [Repository layout](repository-layout.md) - explains the repository tree,
  ownership boundaries, and path conventions.
- [Documentation style guide](documentation-style-guide.md) - defines the
  writing, formatting, and document-type conventions for project documentation.
- [Users' guide](users-guide.md) - describes supported user-facing behaviour
  and externally visible workflows.
- [Developers' guide](developers-guide.md) - gives maintainer-facing build,
  test, lint, extension, and contribution guidance.
- [Roadmap](roadmap.md) - tracks phased delivery work, dependencies, and
  acceptance criteria.

## Product and system design

- [Episodic podcast generation system design](episodic-podcast-generation-system-design.md)
  - primary product and architecture design for the podcast generation system.
- [Episodic TUI API design](episodic-tui-api-design.md) - design notes for the
  terminal user interface and API interaction model.
- [Infrastructure design](infrastructure-design.md) - Kubernetes, GitOps,
  observability, and operational infrastructure design.
- [Reference binding resolution](reference-binding-resolution.md) - reference
  binding model and resolution behaviour.
- [LangGraph and Celery in hexagonal architecture](langgraph-and-celery-in-hexagonal-architecture.md)
  - integration guidance for orchestration and worker boundaries.

## User and integration guides

- [Femtologging users' guide](femtologging-users-guide.md) - integration
  guidance for the femtologging dependency.
- [TEI Rapporteur users' guide](tei-rapporteur-users-guide.md) - integration
  guidance for Text Encoding Initiative (TEI) payload handling.
- [Async SQLAlchemy with PostgreSQL and Falcon](async-sqlalchemy-with-pg-and-falcon.md)
  - reference for asynchronous persistence and HTTP service integration.
- [Testing async Falcon endpoints](testing-async-falcon-endpoints.md) -
  practical guidance for endpoint tests.
- [Testing SQLAlchemy with pytest and py-pglite](testing-sqlalchemy-with-pytest-and-py-pglite.md)
  - persistence testing guidance.
- [Local validation of GitHub Actions with act and pytest](local-validation-of-github-actions-with-act-and-pytest.md)
  - local continuous integration validation workflow.
- [Scripting standards](scripting-standards.md) - conventions for helper
  scripts and command execution.

## Architecture and engineering references

- [Agentic systems with LangGraph and Celery](agentic-systems-with-langgraph-and-celery.md)
  - background reference for agentic workflow orchestration.
- [Cost management in LangGraph agentic systems](cost-management-in-langgraph-agentic-systems.md)
  - cost-control patterns for agentic workflows.
- [Complexity antipatterns and refactoring strategies](complexity-antipatterns-and-refactoring-strategies.md)
  - maintainability guidance for refactoring decisions.
- [Reliable testing in Rust via dependency injection](reliable-testing-in-rust-via-dependency-injection.md)
  - reference material for Rust dependency-injection testing.
- [Rust doctest dry guide](rust-doctest-dry-guide.md) - Rust documentation-test
  maintenance guidance.
- [Rust testing with rstest fixtures](rust-testing-with-rstest-fixtures.md) -
  Rust fixture-based testing guidance.

## Decision records

- [ADR 001: Pedante evaluator contract](adr-001-pedante-evaluator-contract.md)
  - evaluator contract decision retained at the historical top-level ADR path.
- [ADR 001: Reference binding resolution algorithm](adr/adr-001-reference-binding-resolution-algorithm.md)
  - accepted reference binding resolution algorithm.
- [ADR 002: HTTP service composition root](adr/adr-002-http-service-composition-root.md)
  - HTTP service composition boundary.
- [ADR 003: Celery worker scaffold](adr/adr-003-celery-worker-scaffold.md) -
  worker process scaffold decision.
- [ADR 004: Show notes TEI representation](adr/adr-004-show-notes-tei-representation.md)
  - show notes representation in TEI.
- [ADR 005: Structured planning and tool execution](adr/adr-005-structured-planning-and-tool-execution.md)
  - structured planning and tool execution model.
- [ADR 006: Chrono spoken text semantics](adr/adr-006-chrono-spoken-text-semantics.md)
  - spoken-text runtime estimation semantics.
- [ADR 007: Durable generation checkpoints](adr/adr-007-durable-generation-checkpoints.md)
  - durable checkpointing model for generation workflows.
- [ADR 008: Chapter marker TEI representation](adr/adr-008-chapter-marker-tei-representation.md)
  - chapter marker representation in TEI.
- [ADR 009: Source-to-script REST vertical slice](adr/adr-009-source-to-script-rest-vertical-slice.md)
  - REST vertical slice scope for source-to-script work.
- [ADR 010: Guest bios TEI representation](adr/adr-010-guest-bios-tei-representation.md)
  - guest biography representation in TEI.
- [ADR 011: TTS capability negotiation](adr/adr-011-tts-capability-negotiation.md)
  - text-to-speech capability negotiation model.
- [ADR 012: Pronunciation repository](adr/adr-012-pronunciation-repository.md)
  - pronunciation repository decision.
- [ADR 013: Speech synthesis adapters](adr/adr-013-speech-synthesis-adapters.md)
  - speech synthesis adapter boundaries.
- [ADR 014: Hexagonal architecture enforcement](adr/adr-014-hexagonal-architecture-enforcement.md)
  - import-boundary enforcement model.
- [ADR 015: Upload and idempotency ports](adr/adr-015-upload-and-idempotency-ports.md)
  - source-intake upload storage and idempotency port decisions.
- [ADR 016: Orchestration architecture enforcement](adr/adr-016-orchestration-architecture-enforcement.md)
  - LangGraph node, Celery task, and checkpoint payload enforcement decisions.

## Execution plans

- [Reference binding resolution](execplans/1-4-3-reference-binding-resolution.md)
  - implementation plan for roadmap task 1.4.3.
- [Scaffold Falcon HTTP services on Granian](execplans/1-5-1-scaffold-falcon-http-services-on-granian.md)
  - implementation plan for roadmap task 1.5.1.
- [Scaffold Celery workers with RabbitMQ integration](execplans/1-5-2-scaffold-celery-workers-with-rabbit-mq-integration.md)
  - implementation plan for roadmap task 1.5.2.
- [Architectural enforcement for hexagonal boundaries](execplans/1-5-4-architectural-enforcement-for-hexagonal-boundaries.md)
  - implementation plan for roadmap task 1.5.4.
- [Pedante factuality and accuracy evaluator](execplans/2-2-1-pedante-factuality-and-accuracy-evaluator.md)
  - evaluator implementation plan.
- [Relational schema design](execplans/2-2-1-relational-schema-design.md) -
  storage schema implementation plan.
- [Migration tooling with Alembic](execplans/2-2-2-migration-tooling-with-alembic.md)
  - migration tooling plan.
- [Repository and unit of work layers](execplans/2-2-3-repository-and-unit-of-work-layers.md)
  - persistence boundary implementation plan.
- [Multi-source ingestion service](execplans/2-2-4-multi-source-ingestion-service.md)
  - ingestion service implementation plan.
- [Capture provenance metadata](execplans/2-2-5-capture-provenance-metadata.md)
  - provenance implementation plan.
- [Chrono runtime estimator](execplans/2-2-6-chrono-runtime-estimator.md) -
  runtime estimation implementation plan.
- [Define reusable reference document model](execplans/2-2-6-define-reusable-reference-document-model.md)
  - reference document model plan.
- [Reusable reference document repository docs](execplans/2-2-6-reusable-reference-document-repository-docs.md)
  - reference repository documentation plan.
- [Series profile and episode template models](execplans/2-2-6-series-profile-and-episode-template-models.md)
  - profile and template model plan.
- [REST endpoints for reference documents](execplans/2-2-7-rest-endpoints-for-reference-documents.md)
  - reference document API plan.
- [Generate show notes from template expansions](execplans/2-3-1-generate-show-notes-from-template-expansions.md)
  - show notes generation plan.
- [Generate chapter markers aligned to script segments](execplans/2-3-2-generate-chapter-markers-aligned-to-script-segments.md)
  - chapter marker generation plan.
- [Generate guest bios from reference document bindings](execplans/2-3-3-generate-guest-bios-from-reference-document-bindings.md)
  - guest biography generation plan.
- [Structured output planning and tool-calling execution](execplans/2-4-1-structured-output-planning-and-tool-calling-execution.md)
  - planning and tool execution implementation plan.
- [Add LangGraph suspend and resume orchestration](execplans/2-4-2-add-lang-graph-suspend-and-resume-orchestration.md)
  - orchestration checkpoint plan.
- [Configure Celery queue routing](execplans/2-4-3-configure-celery-queue-routing.md)
  - worker routing plan.
- [Extend architecture enforcement to orchestration code](execplans/2-4-5-extend-architecture-enforcement-to-orchestration-code.md)
  - orchestration architecture enforcement plan.
- [LLM port adapter](execplans/3-2-1-llm-port-adapter.md) - large language
  model adapter plan.
- [Introduce v1 target API prefix](execplans/4-1-1-introduce-v1-target-api-prefix.md)
  - REST API versioning plan.
- [Finalize REST surfaces](execplans/4-1-2-finalize-rest-surfaces.md) - REST
  surface hardening plan.
- [Adopt Hecate](execplans/adopt-hecate.md) - architecture enforcement
  adoption plan.
- [Femtologging April 2026 migration](execplans/femtologging-april-2026-migration.md)
  - femtologging migration plan.
- [LangGraph design enhancements](execplans/langgraph-design-enhancements.md)
  - orchestration design enhancement plan.
- [Roadmap normalization](execplans/roadmap-normalization.md) - roadmap
  structure normalization plan.
- [Update to TEI Rapporteur with type hints](execplans/update-to-tei-rapporteur-with-type-hints.md)
  - dependency update plan.
- [Upgrade Python to 3.14: compression zstd](execplans/upgrade-python-to-3-14-adopt-compression-zstd.md)
  - Python 3.14 compression adoption plan.
- [Upgrade Python to 3.14: concurrent interpreters](execplans/upgrade-python-to-3-14-adopt-concurrent-interpreters.md)
  - Python 3.14 concurrent interpreter adoption plan.
- [Upgrade Python to 3.14: custom task factory support](execplans/upgrade-python-to-3-14-adopt-custom-task-factory-support.md)
  - Python 3.14 task-factory adoption plan.
- [Upgrade Python to 3.14: lazy annotations](execplans/upgrade-python-to-3-14-lazy-annotations.md)
  - Python 3.14 lazy annotation adoption plan.
- [Upgrade Python to 3.14: template strings in prompts](execplans/upgrade-python-to-3-14-template-strings-in-prompts.md)
  - Python 3.14 template string adoption plan.
- [Upgrade Python to 3.14: type guards in OpenAI client](execplans/upgrade-python-to-3-14-type-guards-in-openai-client.md)
  - Python 3.14 type guard adoption plan.
- [Upgrade Python to 3.14: UUID7 for storage IDs](execplans/upgrade-python-to-3-14-uuid7-for-storage-ids.md)
  - Python 3.14 UUID7 adoption plan.
