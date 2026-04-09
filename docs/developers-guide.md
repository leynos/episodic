# Episodic developers' guide

This guide documents internal development practices for Episodic. Follow the
documentation style guide in `docs/documentation-style-guide.md` when updating
this file.

Accepted design decisions relevant to current implementation work:

- [`adr-001-reference-binding-resolution-algorithm.md`](adr/adr-001-reference-binding-resolution-algorithm.md)
- [`adr-002-http-service-composition-root.md`](adr/adr-002-http-service-composition-root.md)
- [`adr-003-celery-worker-scaffold.md`](adr/adr-003-celery-worker-scaffold.md)
- [`episodic-podcast-generation-system-design.md`](episodic-podcast-generation-system-design.md)

## Local development

- Use `uv` to manage the virtual environment and dependencies.
- Run `make lint`, `make typecheck`, and `make test` before proposing changes.
- Use the canonical content modules under `episodic/canonical` for schema and
  repository logic.
- The Makefile exports `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` so the
  `tei-rapporteur` bindings build against Python 3.14.

## Falcon HTTP runtime

The canonical HTTP adapter has two layers:

- `episodic/api/app.py` is the pure Falcon route factory.
- `episodic/api/runtime.py` is the Granian composition root that reads
  `DATABASE_URL`, creates the SQLAlchemy session factory, and injects readiness
  probes through `ApiDependencies`. It also normalizes plain `postgresql://...`
  URLs to the supported async dialect and disposes the long-lived async engine
  via Falcon's ASGI shutdown lifecycle.

Run the service locally with:

```shell
granian episodic.api.runtime:create_app_from_env --interface asgi --factory
```

Health contract:

- `GET /health/live` is a process-level liveness check.
- `GET /health/ready` is an infrastructure readiness check. It currently
  verifies database connectivity and returns `503 Service Unavailable` when the
  probe fails.

Testing guidance:

- Use `tests/test_http_service_scaffold.py` for in-memory ASGI coverage of the
  typed dependency contract and health endpoints.
- Use `tests/steps/test_http_service_scaffold_steps.py` and
  `tests/features/http_service_scaffold.feature` for the live Granian process
  path.
- Runtime-process tests should use the dedicated `migrated_database_url`
  fixture rather than sharing a long-lived migrated engine fixture. The full
  engine disposal step is required to keep the py-pglite-backed runtime probe
  responsive.

## Celery worker runtime

The worker scaffold mirrors the Falcon composition-root pattern:

- `episodic/worker/topology.py` defines the canonical exchange, queue, and
  routing-key contract.
- `episodic/worker/tasks.py` holds representative diagnostic tasks together
  with typed payload and dependency seams.
- `episodic/worker/runtime.py` reads environment configuration, exposes worker
  launch profiles, and builds the Celery application.

Run the worker app locally with:

```shell
celery --app episodic.worker.runtime:create_celery_app_from_env worker --pool prefork --queues episodic.cpu
```

and, for the I/O profile:

```shell
celery --app episodic.worker.runtime:create_celery_app_from_env worker --pool gevent --queues episodic.io
```

Required environment:

- `EPISODIC_CELERY_BROKER_URL` must point at RabbitMQ using an AMQP URL such
  as `amqp://guest:guest@localhost:5672//`.
- `EPISODIC_CELERY_RESULT_BACKEND` is optional in this scaffold slice.
- `EPISODIC_CELERY_IO_POOL` and `EPISODIC_CELERY_CPU_POOL` override the
  default pool choices (`gevent` and `prefork` respectively).
- The CPU `prefork` default remains the baseline Celery process-isolation
  path. For CPU-heavy pure-Python workloads inside repository adapters, the
  optional interpreter-pool seam is enabled separately with
  `EPISODIC_USE_INTERPRETER_POOL=1`.
- `EPISODIC_INTERPRETER_POOL_MIN_ITEMS` tunes the minimum batch size before
  interpreter-pool dispatch activates, and
  `EPISODIC_INTERPRETER_POOL_MAX_WORKERS` caps the interpreter-pool size when
  that path is enabled.
- `EPISODIC_CELERY_IO_CONCURRENCY` and `EPISODIC_CELERY_CPU_CONCURRENCY`
  override the default worker-profile concurrency values.
- `EPISODIC_CELERY_ALWAYS_EAGER=true` is for tests and local contract checks
  only, not for deployed workers.

Queue contract:

- Exchange: `episodic.tasks` (`topic`)
- I/O queue: `episodic.io`, routed via `episodic.io.diagnostic`
- CPU queue: `episodic.cpu`, routed via `episodic.cpu.diagnostic`

Testing guidance:

- Use `tests/test_worker_service_scaffold.py` for unit coverage of topology,
  runtime parsing, Celery app assembly, and eager task execution.
- Use `tests/features/worker_service_scaffold.feature` and
  `tests/steps/test_worker_service_scaffold_steps.py` for contract-level
  behavioural coverage.
- This roadmap slice does not yet include a broker-backed RabbitMQ test
  harness. Behavioural tests intentionally validate routing metadata and eager
  execution instead of a live queue round-trip.

When adding new worker tasks:

- Keep the task body single-responsibility and idempotent.
- Add typed payload dataclasses or other narrow data transfer objects (DTOs)
  in `episodic/worker/tasks.py` or a sibling worker-only module.
- Depend on ports or injected callables rather than importing concrete
  adapters directly into task code.
- Extend `SCAFFOLD_TASK_WORKLOADS` and the topology-backed routing metadata so
  the new task's queue assignment remains explicit.

## Database migrations

Database migrations are managed with Alembic. The migration environment lives
under `alembic/`, and migration scripts are stored in `alembic/versions/`.
Schema changes must be expressed as migrations, and tests apply migrations
before executing database-backed scenarios.

### Creating a new migration

After modifying Object-Relational Mapping (ORM) models in
`episodic/canonical/storage/models.py`, generate a migration with Alembic's
autogenerate feature:

```shell
DATABASE_URL=<database-url> alembic revision --autogenerate -m "description"
```

Migration files follow the naming convention
`YYYYMMDD_NNNNNN_short_description.py` (for example
`20260203_000001_create_canonical_schema.py`).

### Schema drift detection

The `make check-migrations` target detects drift between the ORM models and the
applied migration history. It starts an ephemeral Postgres via py-pglite,
applies all Alembic migrations, and uses
`alembic.autogenerate.compare_metadata()` to compare the migrated schema
against `Base.metadata`. If they differ, the check exits non-zero and reports
the discrepancies.

Run it locally before committing model changes:

```shell
make check-migrations
```

### Continuous integration enforcement

The Continuous Integration (CI) pipeline (`.github/workflows/ci.yml`) runs
`make check-migrations` on every push to `main` and on every pull request. A
pull request that modifies Object-Relational Mapping (ORM) models without an
accompanying Alembic migration will be blocked.

### Developer workflow

1. Modify ORM models in `episodic/canonical/storage/models.py`.
2. Generate a migration: `alembic revision --autogenerate -m "description"`.
3. Run `make check-migrations` to verify the models and migrations are in sync.
4. Run `make test` to confirm existing tests still pass.
5. Commit both the model changes and the new migration together.

## Database testing with py-pglite

Tests that touch the database use py-pglite to run an in-process PostgreSQL
instance. The fixtures in `tests/conftest.py` implement the approach described
in `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.

Key expectations:

- Node.js 18+ is required because py-pglite runs a WebAssembly-based Postgres
  runtime.
- Tests run against Postgres semantics, not SQLite.
- The shared fixture stack is fully asynchronous:
  - `_pglite_sqlalchemy_manager(tmp_path)` starts
    `SQLAlchemyAsyncPGliteManager`, waits for the helper-managed engine to
    accept connections, and shuts the manager down after the test.
  - `pglite_sqlalchemy_manager` is the public function-scoped manager fixture.
  - `pglite_engine` yields the helper-managed `AsyncEngine`.
  - `migrated_engine` applies Alembic migrations to that engine.
  - `session_factory` returns `async_sessionmaker[AsyncSession]` with
    `expire_on_commit=False`.
  - `pglite_session` yields a ready-to-use `AsyncSession`.
- Because the stack depends on pytest's function-scoped `tmp_path`, each
  database-backed test gets an isolated ephemeral database by default.
- Most database-backed tests should use `session_factory` or `pglite_session`.
  Use `pglite_engine` only for lower-level engine assertions, and use
  `pglite_sqlalchemy_manager` only when a test genuinely needs direct manager
  access.
- Keep direct driver tests narrowly scoped. Do not introduce a parallel
  `asyncpg` fixture stack or bespoke connection bootstrap unless py-pglite's
  async-driver compatibility has been verified for the current dependency set.
  In this repository, the helper-managed async SQLAlchemy engine is the source
  of truth; raw driver wiring is an implementation detail, not a public test
  pattern.
- Use `pytest.mark.asyncio` and `@pytest_asyncio.fixture` for asynchronous
  database tests. Synchronous Falcon API tests should use
  `canonical_api_client`, which is already wired to `SqlAlchemyUnitOfWork`
  backed by the shared `session_factory`.
- `make test` uses `PYTEST_XDIST_WORKERS=1` by default to avoid py-pglite
  cross-worker process termination. Override with
  `PYTEST_XDIST_WORKERS=<n> make test` when debugging worker-count behaviour.
- `EPISODIC_TEST_DB=sqlite` disables the py-pglite fixtures (tests that depend
  on them will be skipped).
- If a non-SQLite backend is requested while py-pglite is unavailable, the
  fixtures raise a clear error instead of silently skipping tests.
- `make check-migrations` uses the same database technology, but a separate
  bootstrap path. `episodic/canonical/storage/migration_check.py` starts a
  plain `PGliteManager`, creates an async SQLAlchemy engine from
  `config.get_connection_string()`, applies Alembic migrations, and compares
  the migrated schema against `Base.metadata`.

## Canonical content persistence

Canonical content persistence follows the hexagonal architecture guidance:

- `episodic/canonical/ports.py` defines repository and unit-of-work interfaces.
- `episodic/canonical/storage/` implements SQLAlchemy adapters and keeps
  persistence concerns out of the domain layer.
- `episodic/canonical/services.py` orchestrates ingestion workflows using the
  ports.
- `CanonicalUnitOfWork.flush()` is available when dependent records must be
  persisted before creating related rows (for example, approval events that
  reference newly created episodes).

### Repository usage

Each repository provides `add()` to persist a domain entity and `get()` (or
`get_by_slug()`, `list_for_job()`, `list_for_episode()`) to retrieve persisted
entities. Repositories translate between frozen domain dataclasses and
SQLAlchemy ORM records via mapper functions in
`episodic/canonical/storage/mappers.py`. Access repositories through the
unit-of-work rather than constructing them directly:

```python
async with SqlAlchemyUnitOfWork(session_factory) as uow:
    await uow.series_profiles.add(profile)
    await uow.commit()

    fetched = await uow.series_profiles.get(profile.id)
```

### Unit-of-work transaction semantics

The `SqlAlchemyUnitOfWork` manages transaction boundaries:

- `commit()` persists all pending changes to the database.
- `rollback()` discards all uncommitted changes within the current session.
- `flush()` writes pending changes to the database without committing, useful
  when dependent records require foreign-key references to exist within the
  same transaction.
- When the context manager exits with an unhandled exception, the unit of work
  rolls back automatically.

Database-level constraints (unique slugs, foreign keys, and CHECK constraints
such as the weight bound on source documents) are enforced by Postgres and
raise `sqlalchemy.exc.IntegrityError` on violation.

### TEI payload compression

Canonical TEI payload storage now supports transparent Zstandard compression
for large XML values:

- `tei_headers.raw_xml_zstd` stores compressed header XML.
- `episodes.tei_xml_zstd` stores compressed episode XML.
- `tei_headers.raw_xml` and `episodes.tei_xml` remain the backward-compatible
  legacy text columns for older rows and small payloads.

Compression is applied in repository write paths when the UTF-8 payload size is
at least 1024 bytes and only when compression reduces size. Repository read
paths always return plain `str` values to domain callers by decoding compressed
payloads automatically.

## Series profile and episode template APIs

Series profile and episode template workflows are implemented as a driving
adapter (`episodic/api/app.py`) over domain services in
`episodic/canonical/profile_templates.py`.

### Endpoints

- `POST /series-profiles`
- `GET /series-profiles`
- `GET /series-profiles/{profile_id}`
- `PATCH /series-profiles/{profile_id}`
- `GET /series-profiles/{profile_id}/history`
- `GET /series-profiles/{profile_id}/brief`
- `GET /series-profiles/{profile_id}/resolved-bindings`
- `POST /episode-templates`
- `GET /episode-templates`
- `GET /episode-templates/{template_id}`
- `PATCH /episode-templates/{template_id}`
- `GET /episode-templates/{template_id}/history`

### Optimistic locking and history

- Updates require `expected_revision`.
- If `expected_revision` does not match the latest persisted revision, the API
  returns `409 Conflict`.
- History is append-only and immutable:
  - `series_profile_history` stores profile snapshots per revision.
  - `episode_template_history` stores template snapshots per revision.

### Structured brief payloads

`GET /series-profiles/{profile_id}/brief` returns a stable payload containing:

- `series_profile`: profile metadata, configuration, persisted `guardrails`,
  and current revision.
- `episode_templates`: one template when `template_id` is provided, or all
  templates for the series profile when omitted.
- `reference_documents`: reusable reference bindings resolved for the selected
  series profile and template context.

The brief endpoint accepts optional query parameters:

- `template_id`: restricts the template section to one episode template.
- `episode_id`: applies `effective_from_episode_id` precedence to
  series-profile bindings before the `reference_documents` payload is
  serialized. Omitting it preserves the legacy behaviour of returning all
  matching bindings.

`GET /series-profiles/{profile_id}/resolved-bindings` returns the resolved
binding set directly. It requires `episode_id`, accepts optional `template_id`,
and responds with `items`, where each item includes serialized `binding`,
`document`, and `revision` payloads.

### Reusable reference-document APIs

Reusable reference-document workflows are implemented as Falcon resources in:

- `episodic/api/resources/reference_documents.py`
- `episodic/api/resources/reference_bindings.py`

Route wiring lives in `episodic/api/app.py`, and service orchestration is
implemented in `episodic/canonical/reference_documents/services.py`.

See also:
[`docs/reference-binding-resolution.md`](reference-binding-resolution.md) for
the episode-aware resolver, provenance snapshot APIs, and endpoint-specific
binding-resolution behavior.

Supported endpoints:

- `POST /series-profiles/{profile_id}/reference-documents`
- `GET /series-profiles/{profile_id}/reference-documents`
- `GET /series-profiles/{profile_id}/reference-documents/{document_id}`
- `PATCH /series-profiles/{profile_id}/reference-documents/{document_id}`
- `POST /series-profiles/{profile_id}/reference-documents/{document_id}/revisions`
- `GET /series-profiles/{profile_id}/reference-documents/{document_id}/revisions`
- `GET /reference-document-revisions/{revision_id}`
- `POST /reference-bindings`
- `GET /reference-bindings`
- `GET /reference-bindings/{binding_id}`

Implementation notes:

- Mutable `ReferenceDocument` updates use optimistic locking via
  `expected_lock_version`. Conflicts return `409 Conflict`.
- List endpoints for documents, revisions, and bindings use a shared pagination
  contract (`limit`, `offset`) with default `limit=20`, max `limit=100`, and
  default `offset=0`.
- Series alignment is enforced in service-layer ownership checks for host and
  guest documents. Cross-series access is treated as `404 Not Found` for
  profile-scoped routes.
- Inbound adapters map typed reusable-reference service errors to Falcon HTTP
  errors through local `_map_reference_error(...)` helpers.

### Reusable reference-document repositories

The canonical unit of work now exposes reusable reference repositories
independent of ingestion-job scope:

- `reference_documents`
- `reference_document_revisions`
- `reference_bindings`

These repositories are implemented in
`episodic/canonical/storage/reference_repositories.py` and enforce these
invariants:

- A binding targets exactly one context kind (`series_profile`,
  `episode_template`, or `ingestion_job`).
- `effective_from_episode_id` is only valid for `series_profile` bindings.
- Host and guest profiles are represented through
  `ReferenceDocumentKind.HOST_PROFILE` and
  `ReferenceDocumentKind.GUEST_PROFILE`.

For profile/template brief assembly, `build_series_brief(...)` resolves
reference bindings from the selected profile and template contexts and emits
serialized `reference_documents` payload entries with pinned revision metadata.
When an episode context is present, the same resolution algorithm is exposed
through `ResolvedBindingsResource` and reused by ingestion to snapshot the
resolved reference revisions into provenance `source_documents`.

### Prompt scaffolding for generators

Use the canonical prompt helpers to build deterministic generation scaffolds
from structured briefs:

- `build_series_brief_prompt(...)` in `episodic.canonical` loads a structured
  brief and returns a rendered prompt payload.
- `build_series_guardrail_prompt(...)` in `episodic.canonical` loads the same
  structured brief and renders persisted profile/template `guardrails` into a
  provider-neutral system prompt.
- `episodic.canonical.prompts` exposes:
  - `build_series_brief_template(...)` to construct a Python 3.14 template
    string (`t"..."`) representation.
  - `build_series_guardrail_template(...)` to construct the persisted
    guardrail scaffold from the same brief payload.
  - `render_template(...)` to render prompt text while preserving static and
    interpolation metadata for audit trails.
  - `render_series_brief_prompt(...)` as the standard convenience renderer for
    brief payloads.
  - `render_series_guardrail_prompt(...)` as the standard convenience renderer
    for guardrail/system prompt payloads.

The renderer accepts an optional interpolation escape callback, so adapters can
apply policy-specific sanitization (for example, XML/HTML escaping) without
changing canonical prompt assembly rules.

## Quality-assurance evaluators

Pedante is implemented in the `episodic/qa/` package.

### Package structure

- `episodic/qa/pedante.py` defines the Pedante request and result contract, the
  support-level taxonomy, strict JSON parsing, and the `PedanteEvaluator` that
  calls the existing `LLMPort`.
- `episodic/qa/langgraph.py` provides the minimal LangGraph seam for Pedante.
  This graph is intentionally narrow: it runs the evaluator and routes to
  `pass` or `refine` based on typed findings.

### Contract rules

- Treat `PedanteEvaluationRequest.script_tei_xml` as the canonical script input
  and keep TEI P5 as the authoring-loop data spine.
- Use JSON only as a prompt-facing or transport-facing projection of that
  TEI-backed content, not as a second canonical document model.
- Keep orchestration code dependent on ports and domain contracts only.
  LangGraph state should hold orchestration metadata and evaluator results, not
  the sole canonical copy of editorial data.

### Testing the evaluator

- Unit tests live in `tests/test_pedante.py`.
- LangGraph seam tests live in `tests/test_pedante_langgraph.py`.
- Behavioural coverage lives in `tests/features/pedante.feature` and
  `tests/steps/test_pedante_steps.py`.
- Pedante behavioural tests use Vidai Mock. When configuring custom templates,
  `response_template` paths are resolved relative to the template root. For
  example, use `pedante/response.json.j2`, not
  `templates/pedante/response.json.j2`.

## Content generation services

Content-enrichment services that sit on the generation side of the authoring
loop live in `episodic/generation/`. This package is separate from
`episodic/qa/`: it creates or enriches content, whereas QA modules score or
critique draft output.

### Show-notes generation

- `episodic/generation/show_notes.py` defines the `ShowNotesGenerator`,
  `ShowNotesEntry`, `ShowNotesResult`, `ShowNotesGeneratorConfig`, and
  `enrich_tei_with_show_notes(...)` helper.
- `ShowNotesEntry` is an immutable dataclass with constructor-time
  validation:

  Table: `ShowNotesEntry` fields.

  | Field | Type | Constraints |
  | --- | --- | --- |
  | `topic` | `str` | Non-empty; whitespace-only values raise `ValueError` |
  | `summary` | `str` | Non-empty; whitespace-only values raise `ValueError` |
  | `timestamp` | `str \| None` | Optional; when present must match ISO 8601 duration pattern (for example, `"PT5M"`) |
  | `tei_locator` | `str \| None` | Optional; blank strings are normalized to `None` at construction |

- `ShowNotesResult` is an immutable dataclass:

  Table: `ShowNotesResult` fields.

  | Field | Type | Notes |
  | --- | --- | --- |
  | `entries` | `tuple[ShowNotesEntry, ...]` | Ordered sequence of parsed show-notes entries |
  | `usage` | `LLMUsage` | Normalized token-usage counters from the provider response |
  | `model` | `str` | Model identifier echoed from the provider response (default `""`) |
  | `provider_response_id` | `str` | Provider-assigned response identifier (default `""`) |
  | `finish_reason` | `str \| None` | Provider finish reason, for example `"stop"` (default `None`) |

- `ShowNotesGeneratorConfig` is a dataclass:

  Table: `ShowNotesGeneratorConfig` fields.

  | Field | Type | Notes |
  | --- | --- | --- |
  | `model` | `str` | Model identifier to pass in the LLM request |
  | `provider_operation` | `LLMProviderOperation \| str` | Defaults to `LLMProviderOperation.CHAT_COMPLETIONS` |
  | `token_budget` | `LLMTokenBudget \| None` | Optional token-budget constraints forwarded to `LLMPort` |
  | `system_prompt` | `str` | System instruction sent alongside the user prompt; defaults to the built-in show-notes extraction prompt |

Standalone usage pattern:

```python
import asyncio
from episodic.generation import (
    ShowNotesGenerator,
    ShowNotesGeneratorConfig,
    ShowNotesResponseFormatError,
    enrich_tei_with_show_notes,
)
from episodic.llm.ports import LLMTokenBudget

config = ShowNotesGeneratorConfig(
    model="gpt-4o-mini",
    token_budget=LLMTokenBudget(
        max_input_tokens=4096,
        max_output_tokens=1024,
        max_total_tokens=5120,
    ),
)


async def enrich(llm_port, script_tei_xml: str) -> str:
    generator = ShowNotesGenerator(llm=llm_port, config=config)
    try:
        result = await generator.generate(script_tei_xml)
    except ShowNotesResponseFormatError as exc:
        # handle malformed LLM response
        raise
    return enrich_tei_with_show_notes(script_tei_xml, result)
```

- `ShowNotesGenerator` depends only on `LLMPort` and the normalized LLM
  request/response contract. Keep it free of HTTP, Falcon, Celery, and
  LangGraph dependencies.
- `ShowNotesGenerator.build_prompt(...)` accepts a TEI script payload and an
  optional `template_structure` mapping. `generate(...)` sends that prompt
  through `LLMPort` and strictly parses JSON output into typed entries.
- `enrich_tei_with_show_notes(...)` inserts a `<div type="notes">` element
  into the TEI body using the representation defined by
  [`adr-003-show-notes-tei-representation.md`](adr/adr-003-show-notes-tei-representation.md):
  `<list>` contains one `<item>` per note, `<label>` carries the topic, the
  summary is inline text, `@n` stores an optional timestamp, and `@corresp`
  stores an optional source locator.
- `ShowNotesResponseFormatError` is a `ValueError` subclass raised by
  `ShowNotesGenerator` whenever the LLM response cannot be parsed into a valid
  `ShowNotesResult`. Callers should catch this exception to handle malformed
  or unexpected LLM output gracefully. It is raised when the response text is
  not valid JSON; when the top-level JSON object does not contain an `entries`
  list; when an entry in `entries` is not a JSON object; when a required field
  (`topic` or `summary`) is absent, empty, or not a string; when an optional
  field (`timestamp` or `tei_locator`) is present but is not a string or null;
  and when a `timestamp` value does not match the ISO 8601 duration format.

### Testing content generation services

- Unit coverage for show notes lives in `tests/test_show_notes.py`.
- Behavioural coverage lives in `tests/features/show_notes.feature` and
  `tests/steps/test_show_notes_steps.py`.
- The behavioural scenario uses Vidai Mock in the same style as Pedante. When
  writing provider fixtures, keep the prompt assertions structural and the
  response template minimal so prompt wording can evolve without making the
  scenario brittle.

## LLM adapter boundary

`episodic.llm` now owns a richer outbound contract:

- `LLMRequest` carries the prompt text, optional system prompt, target model,
  provider operation (`chat_completions` or `responses`), and token budget.
- `OpenAICompatibleLLMAdapter` implements `LLMPort` over explicit
  OpenAI-compatible HTTP calls, so OpenRouter-style chat completions and OpenAI
  Responses stay behind the same port.
- Token budgets are enforced twice: a pre-flight estimate rejects obviously
  impossible requests, and normalized provider usage is checked again after the
  response returns.
- Persisted `guardrails` belong to canonical profile/template state and are
  composed before the adapter call, not inside the vendor transport layer.

## Multi-source ingestion

The multi-source ingestion service normalizes heterogeneous source documents,
applies source weighting heuristics, resolves conflicts, and merges the result
into a canonical TEI episode. The service is implemented as an orchestrator
(`ingest_multi_source`) that composes around the existing low-level
`ingest_sources` persistence function.

### Port protocols

Three Protocol-based interfaces in `episodic/canonical/ingestion_ports.py`
define the pipeline extension points:

- `SourceNormalizer` — converts a `RawSourceInput` into a `NormalizedSource`
  containing a TEI XML fragment and quality, freshness, and reliability scores.
- `WeightingStrategy` — computes a `WeightingResult` for each normalized
  source using series-level configuration coefficients.
- `ConflictResolver` — produces a `ConflictOutcome` that selects preferred
  sources, rejects lower-weighted alternatives, and merges the canonical TEI.

### Reference adapters

Reference implementations in `episodic/canonical/adapters/` are suitable for
testing and initial deployments:

- `InMemorySourceNormalizer` — assigns quality, freshness, and reliability
  scores based on source type defaults. Known types and their defaults:
  - `transcript`: quality=0.9, freshness=0.8, reliability=0.9
  - `brief`: quality=0.8, freshness=0.7, reliability=0.8
  - `rss`: quality=0.6, freshness=1.0, reliability=0.5
  - `press_release`: quality=0.7, freshness=0.6, reliability=0.7
  - `research_notes`: quality=0.5, freshness=0.5, reliability=0.6
  - Unknown types receive mid-range fallback scores (0.5 each).
- `DefaultWeightingStrategy` — computes a weighted average using
  coefficients from the series configuration or defaults. The configuration
  dictionary may contain a `"weighting"` key with `"quality_coefficient"`
  (default 0.5), `"freshness_coefficient"` (default 0.3), and
  `"reliability_coefficient"` (default 0.2).
- `HighestWeightConflictResolver` — selects the highest-weighted source as
  canonical; all others are rejected with provenance preserved.

### Orchestration flow

```python
from episodic.canonical.adapters import (
    DefaultWeightingStrategy,
    HighestWeightConflictResolver,
    InMemorySourceNormalizer,
)
from episodic.canonical.ingestion import MultiSourceRequest, RawSourceInput
from episodic.canonical.ingestion_service import (
    IngestionPipeline,
    ingest_multi_source,
)

pipeline = IngestionPipeline(
    normalizer=InMemorySourceNormalizer(),
    weighting=DefaultWeightingStrategy(),
    resolver=HighestWeightConflictResolver(),
)
request = MultiSourceRequest(
    raw_sources=[...],
    series_slug="my-series",
    requested_by="user@example.com",
)
async with SqlAlchemyUnitOfWork(session_factory) as uow:
    episode = await ingest_multi_source(uow, profile, request, pipeline)
```

### TEI header provenance metadata

TEI header provenance is built in `episodic/canonical/provenance.py` and
applied by `ingest_sources` in `episodic/canonical/services.py`.

- `build_tei_header_provenance()` generates a stable provenance payload with
  capture context, source priorities, ingestion timestamp, and reviewer
  identities.
- `merge_tei_header_provenance()` attaches that payload under the
  `episodic_provenance` key in the parsed TEI header dictionary.
- Source priorities are sorted by descending weight, preserving source input
  order for ties.
- `capture_context` currently uses `source_ingestion`; `script_generation` is
  reserved for future generation workflows and must reuse the same builder.

### Implementing custom adapters

To implement a custom adapter, create a class that satisfies the corresponding
protocol. For example, a custom normalizer for RSS feeds:

```python
class RssNormalizer:
    async def normalize(self, raw_source: RawSourceInput) -> NormalizedSource:
        # Parse RSS XML, extract title and content, build TEI fragment.
        ...
```

The adapter can then be passed to `IngestionPipeline` in place of the reference
normalizer.

## Logging

Structured logging uses femtologging v0.1.0-style logger methods. Import
`get_logger` (or `getLogger` when matching stdlib naming) from
`episodic.logging`, then emit via `logger.info(...)`, `logger.warning(...)`,
`logger.error(...)`, or `logger.exception(...)`.

Keep `episodic.logging.configure_logging(...)` as the local configuration seam.
The legacy `log_info`, `log_warning`, and `log_error` helpers remain available
for compatibility, but new code should prefer calling the logger methods
directly. Femtologging still expects pre-formatted messages rather than stdlib
`logger.info("%s", value)` lazy formatting, so build the final string before
calling the method.
