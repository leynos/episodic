# Episodic developers' guide

This guide documents internal development practices for Episodic. Follow the
documentation style guide in `docs/documentation-style-guide.md` when updating
this file.

Accepted design decisions relevant to current implementation work:

- [`adr-001-reference-binding-resolution-algorithm.md`](adr/adr-001-reference-binding-resolution-algorithm.md)
- [`adr-002-http-service-composition-root.md`](adr/adr-002-http-service-composition-root.md)
- [`adr-003-celery-worker-scaffold.md`](adr/adr-003-celery-worker-scaffold.md)
- [`adr-004-show-notes-tei-representation.md`](adr/adr-004-show-notes-tei-representation.md)
- [`adr-005-structured-planning-and-tool-execution.md`](adr/adr-005-structured-planning-and-tool-execution.md)
- [`adr-006-chrono-spoken-text-semantics.md`](adr/adr-006-chrono-spoken-text-semantics.md)
- [`adr-007-durable-generation-checkpoints.md`](adr/adr-007-durable-generation-checkpoints.md)
- [`adr-008-chapter-marker-tei-representation.md`](adr/adr-008-chapter-marker-tei-representation.md)
- [`adr-009-source-to-script-rest-vertical-slice.md`](adr/adr-009-source-to-script-rest-vertical-slice.md)
- [`adr-010-guest-bios-tei-representation.md`](adr/adr-010-guest-bios-tei-representation.md)
- [`adr-011-tts-capability-negotiation.md`](adr/adr-011-tts-capability-negotiation.md)
- [`adr-012-pronunciation-repository.md`](adr/adr-012-pronunciation-repository.md)
- [`adr-013-speech-synthesis-adapters.md`](adr/adr-013-speech-synthesis-adapters.md)
- [`adr-014-hexagonal-architecture-enforcement.md`](adr/adr-014-hexagonal-architecture-enforcement.md)
- [`episodic-podcast-generation-system-design.md`](episodic-podcast-generation-system-design.md)

## Local development

- Use `uv` to manage the virtual environment and dependencies.
- Run `make lint`, `make typecheck`, and `make test` before proposing changes.
- Use the canonical content modules under `episodic/canonical` for schema and
  repository logic.
- The Makefile exports `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` so the
  `tei-rapporteur` bindings build against Python 3.14.
- The build backend is `uv_build` (`>=0.11.7,<0.12.0`), declared in the
  `[build-system]` table of `pyproject.toml`.

The `Makefile` prepends `$(HOME)/.local/bin` and `$(HOME)/.bun/bin` to `PATH`
so that tools installed via `uv` and Bun are discoverable by all Make targets
without requiring manual shell `PATH` configuration.

## Linting

Run the full lint gate with:

```shell
make lint
```

The target runs the Hecate architecture import-boundary checker, Ruff, and a
focused Pylint 4 pass. The Pylint pass is invoked through
`uv tool run --python pypy` with the pinned `pylint-pypy-shim` wrapper from
[github.com/leynos/pylint-pypy-shim](https://github.com/leynos/pylint-pypy-shim).
That wrapper installs the PyPy-specific Astroid compatibility patch before
delegating to Pylint.

Pylint's message selection is allow-listed in `pyproject.toml` with
`disable = ["all"]` and explicit `enable` entries for the logging, match,
refactoring, standard-library, and modified-iteration checks this repository
cares about. Keep rule rationale comments beside those entries, so future lint
changes explain why a rule is enabled, instead of only recording its name.

The wrapper disables Pylint's `syntax-error` message for this pass because the
managed PyPy runtime currently parses Python 3.11 syntax while the project
targets Python 3.14. Files that PyPy-backed Pylint cannot parse are reported by
the wrapper and skipped, which keeps parse incompatibilities visible without
hiding other diagnostics from files that PyPy can analyse.

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

Versioned API routing:

- `/v1` is the target prefix for client-facing canonical API resources,
  including series-profile, episode-template, reusable-reference, and
  binding-resolution routes.
- Existing unversioned canonical routes are pre-v0.1.0 implementation details.
  They are not compatibility aliases and should return Falcon's normal
  `404 Not Found` response.
- Health checks remain root-level operator endpoints at `/health/live` and
  `/health/ready`.
- New terminal user interface (TUI)-facing and vertical-slice REST endpoints
  must be registered under `/v1`.
- The routing decision follows
  [`adr-009-source-to-script-rest-vertical-slice.md`](adr/adr-009-source-to-script-rest-vertical-slice.md)
  and [`episodic-tui-api-design.md`](episodic-tui-api-design.md).

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
- `EPISODIC_CELERY_IO_CONCURRENCY` and `EPISODIC_CELERY_CPU_CONCURRENCY`
  override the default worker-profile concurrency values.
- `EPISODIC_CELERY_ALWAYS_EAGER=true` is for tests and local contract checks
  only, not for deployed workers.

Optional interpreter-pool flags:

- `EPISODIC_USE_INTERPRETER_POOL=1` enables the interpreter-pool seam for
  CPU-heavy pure-Python workloads inside repository adapters.
- `EPISODIC_INTERPRETER_POOL_MIN_ITEMS` tunes the minimum batch size before
  interpreter-pool dispatch activates after the seam is enabled.
- `EPISODIC_INTERPRETER_POOL_MAX_WORKERS` caps the interpreter-pool size when
  that seam is enabled.
- `create_celery_app_from_env()` and `load_runtime_config()` do not consume
  these flags directly; enable the interpreter-pool explicitly with
  `EPISODIC_USE_INTERPRETER_POOL=1`, then use the other two variables as the
  tuning thresholds for that path.

Queue contract:

- Exchange: `episodic.tasks` (`topic`)
- I/O queue: `episodic.io`, routed via `episodic.io.diagnostic`
- CPU queue: `episodic.cpu`, routed via `episodic.cpu.diagnostic`

### Python dependencies

The following packages were added to `pyproject.toml` as part of this scaffold
and must be present in the virtual environment:

| Package    | Constraint     | Purpose                                                                                                   |
| ---------- | -------------- | --------------------------------------------------------------------------------------------------------- |
| `celery`   | `>=5.5,<6.0`   | Distributed task queue framework; provides the `Celery` app, worker process, and task-dispatch machinery. |
| `kombu`    | `>=5.5,<6.0`   | AMQP messaging library used by Celery; defines `Exchange`, `Queue`, and the RabbitMQ connection layer.    |
| `gevent`   | `>=24.0,<26.0` | Coroutine-based concurrency pool; default pool for I/O-bound workers (`episodic.io` queue).               |
| `eventlet` | `>=0.39,<0.41` | Alternative green-thread pool; available as an opt-in via `EPISODIC_CELERY_IO_POOL=eventlet`.             |

After pulling this change, run:

```shell
uv sync
```

to install the new dependencies into the project virtual environment.

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
- Extend `SCAFFOLD_TASK_WORKLOADS` and the topology-backed routing metadata, so
  the new task's queue assignment remains explicit.
- For CPU-bound tasks on `episodic.cpu` that can split pure-Python inner work
  into independent items, build the task-level executor from the environment:

  ```python
  import os

  from episodic.concurrent_interpreters import (
      build_cpu_task_executor_from_environment,
  )

  executor = build_cpu_task_executor_from_environment(os.environ)
  try:
      results = await executor.map_ordered(pure_python_fn, items)
  finally:
      shutdown = getattr(executor, "shutdown", None)
      if shutdown is not None:
          shutdown()
  ```

  `EPISODIC_USE_INTERPRETER_POOL=1` enables `InterpreterPoolCpuTaskExecutor`
  when the runtime supports interpreter pools, and
  `EPISODIC_INTERPRETER_POOL_MAX_WORKERS` caps its worker count. Keep
  `EPISODIC_INTERPRETER_POOL_MIN_ITEMS` as task-level fan-out policy, not
  Celery pool configuration. The task-level owner is responsible for executor
  lifetime and cleanup; inline executors do not need shutdown, while
  interpreter-pool executors must be shut down when their fan-out operation or
  explicit worker-scoped owner is finished.
- Export CPU-task executor metrics through `CpuTaskExecutorMetricsPort`; it
  extends the shared `BoundedValueMetricsPort` in `episodic/metrics_ports.py`
  for executor selection, interpreter-pool lifecycle, map item count, and
  shutdown-latency collection. Keep labels bounded to low-cardinality outcome
  and reason values. Wire production backends through
  `DefaultWeightingStrategy(metrics=...)` or by calling
  `build_cpu_task_executor_from_environment(..., metrics=...)` directly at the
  composition root.

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
`alembic.autogenerate.compare_metadata()` to compare the migrated schema against
`Base.metadata`. If they differ, the check exits non-zero and reports the
discrepancies.

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
  bootstrap path. `episodic/canonical/storage/migration_check.py` starts a plain
  `PGliteManager`, creates an async SQLAlchemy engine from
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
such as the weight bound on source documents) are enforced by Postgres and raise
`sqlalchemy.exc.IntegrityError` on violation.

### Architecture enforcement

Run the architecture checker directly when changing package boundaries:

```shell
make check-architecture
```

`make lint` runs this architecture gate before Ruff and Pylint. Hecate reads
`[tool.hecate]` from `pyproject.toml` and reports diagnostics as `ARCH001` with
the importer, imported module, and dependency direction.

The enforced groups are:

- `domain_ports`: canonical domain types, canonical ports, ingestion ports,
  canonical constraint names, and LLM ports.
- `application`: canonical services, profile/template workflows,
  reference-document workflows, and generation services.
- `inbound_adapter`: Falcon API modules and worker task/topology seams.
- `outbound_adapter`: SQLAlchemy storage, canonical ingestion adapters, and
  OpenAI-compatible LLM adapters.
- `composition_root`: modules that wire concrete adapters, currently
  `episodic.api.runtime` and `episodic.worker.runtime`.

When adding a new port or adapter, update `[tool.hecate]` in `pyproject.toml`
in the same change as the package. Keep composition-root prefixes before
broader adapter prefixes because Hecate uses first-match group ordering. Add or
adjust fixture coverage in `tests/fixtures/architecture/` and run:

```shell
uv run pytest -q tests/test_architecture_enforcement.py \
  tests/steps/test_architecture_enforcement_steps.py
```

Port contract coverage lives in `tests/test_port_contracts.py`. Future
behavioural tests that exercise real `LLMPort` inference paths should use Vidai
Mock; structural conformance tests do not need an inference server.

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

- `POST /v1/series-profiles`
- `GET /v1/series-profiles`
- `GET /v1/series-profiles/{profile_id}`
- `PATCH /v1/series-profiles/{profile_id}`
- `GET /v1/series-profiles/{profile_id}/history`
- `GET /v1/series-profiles/{profile_id}/brief`
- `GET /v1/series-profiles/{profile_id}/resolved-bindings`
- `POST /v1/episode-templates`
- `GET /v1/episode-templates`
- `GET /v1/episode-templates/{template_id}`
- `PATCH /v1/episode-templates/{template_id}`
- `GET /v1/episode-templates/{template_id}/history`

### Optimistic locking and history

- Updates require `expected_revision`.
- If `expected_revision` does not match the latest persisted revision, the API
  returns `409 Conflict`.
- History is append-only and immutable:
  - `series_profile_history` stores profile snapshots per revision.
  - `episode_template_history` stores template snapshots per revision.

### Structured brief payloads

`GET /v1/series-profiles/{profile_id}/brief` returns a stable payload
containing:

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

`GET /v1/series-profiles/{profile_id}/resolved-bindings` returns the resolved
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

- `POST /v1/series-profiles/{profile_id}/reference-documents`
- `GET /v1/series-profiles/{profile_id}/reference-documents`
- `GET /v1/series-profiles/{profile_id}/reference-documents/{document_id}`
- `PATCH /v1/series-profiles/{profile_id}/reference-documents/{document_id}`
- `POST /v1/series-profiles/{profile_id}/reference-documents/{document_id}/revisions`
- `GET /v1/series-profiles/{profile_id}/reference-documents/{document_id}/revisions`
- `GET /v1/reference-document-revisions/{revision_id}`
- `POST /v1/reference-bindings`
- `GET /v1/reference-bindings`
- `GET /v1/reference-bindings/{binding_id}`

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

Pedante and Chrono are implemented in the `episodic/qa/` package.

### Pedante package structure

- `episodic/qa/pedante.py` contains `PedanteEvaluator`, typed request/result
  objects, and strict response parsing for evaluator output.
- `episodic/qa/langgraph.py` contains the in-process LangGraph path for the
  Pedante evaluate-and-route flow.

### Chrono package structure

- `episodic/qa/chrono.py` contains `ChronoRuntimeEstimator`, typed
  request/result objects, estimator metadata, the deterministic local
  spoken-runtime heuristic, `ChronoMetricsPort`, and `ChronoClockPort`.
  `ChronoMetricsPort` extends the shared `BoundedMetricsPort` in
  `episodic/metrics_ports.py`. The module delegates TEI P5 parsing and
  spoken-text extraction to `tei-rapporteur`; it must not add a separate XML
  parser or local TEI traversal path.
- `episodic/qa/chrono_langgraph.py` contains the in-process LangGraph seam for
  running Chrono as a QA graph node without attaching Large Language Model
  (LLM) usage metadata.

### Pedante maintainer rules

- Treat `PedanteEvaluationRequest.script_tei_xml` as the canonical script input
  and keep TEI P5 as the authoring-loop data spine.
- Use JSON only as a prompt-facing or transport-facing projection of that
  TEI-backed content, not as a second canonical document model.
- Keep Pedante dependent on evaluator contracts and LLM ports only. LangGraph
  state should hold evaluator metadata and results, not the sole canonical copy
  of editorial data.

### Chrono maintainer rules

- Keep Chrono local and deterministic. The domain module must not import
  Falcon, SQLAlchemy, Celery, Vidai Mock, HTTP adapters, or LLM ports. Its
  first heuristic receives spoken prose from `tei-rapporteur`, counts simple
  word tokens, estimates duration at 150 words per minute, and rounds up to
  whole seconds.
- Preserve Chrono metadata whenever results cross an orchestration boundary:
  estimator name, estimator version, input character count, spoken word count,
  and words-per-minute setting are the comparison baseline for later
  implementations.
- Wire Chrono operational metrics through `ChronoMetricsPort` and measure
  latency through `ChronoClockPort`. Keep labels bounded to outcome and error
  class, and record estimator latency without including script text or other
  high-cardinality payload data. Keep the deterministic spoken-runtime
  calculation free of logging, metrics, and wall-clock reads; those side
  effects belong at the estimator orchestration boundary.
- Keep Chrono's numeric duration arithmetic in small pure helpers. The
  `_compute_estimated_seconds(...)` helper carries Python Enhancement Proposal
  (PEP) 316 contracts verified by CrossHair. Run `make crosshair` after
  changing the word-count, words-per-minute, or ceiling-rounding policy. Kani
  and Verus are Rust verification tools and are not applicable to this Python
  module.

### Testing the evaluator

- Unit tests live in `tests/test_pedante.py`.
- LangGraph seam tests live in `tests/test_pedante_langgraph.py`.
- Behavioural coverage lives in `tests/features/pedante.feature` and
  `tests/steps/test_pedante_steps.py`.
- Pedante behavioural tests use Vidai Mock. When configuring custom templates,
  `response_template` paths are resolved relative to the template root. For
  example, use `pedante/response.json.j2`, not
  `templates/pedante/response.json.j2`.
- Chrono unit tests live in `tests/test_chrono.py`. Its property tests live in
  `tests/test_chrono_properties.py`, its graph seam tests live in
  `tests/test_chrono_langgraph.py`, and its behavioural scenario lives in
  `tests/features/chrono.feature` with steps in
  `tests/steps/test_chrono_steps.py`.
- Chrono contract tests live in `tests/test_chrono_contracts.py`. They pin the
  public estimator behaviour backed by `_compute_estimated_seconds(...)` so the
  CrossHair gate has property-test coverage beside symbolic verification. The
  same module includes the `pytest.mark.crosshair` subprocess gate for
  `crosshair check --analysis_kind=PEP316 episodic/qa/chrono.py`.
- Chrono behavioural tests do not launch Vidai Mock because Chrono has no
  inference-service boundary in roadmap item `2.2.6`.

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

  | Field         | Type          | Constraints                                                                         |
  | ------------- | ------------- | ----------------------------------------------------------------------------------- |
  | `topic`       | `str`         | Non-empty; whitespace-only values raise `ValueError`                                |
  | `summary`     | `str`         | Non-empty; whitespace-only values raise `ValueError`                                |
  | `timestamp`   | `str or None` | Optional; when present must match ISO 8601 duration pattern (for example, `"PT5M"`) |
  | `tei_locator` | `str or None` | Optional; blank strings are normalized to `None` at construction                    |

- `ShowNotesResult` is an immutable dataclass:

  Table: `ShowNotesResult` fields.

  | Field                  | Type                         | Notes                                                             |
  | ---------------------- | ---------------------------- | ----------------------------------------------------------------- |
  | `entries`              | `tuple[ShowNotesEntry, ...]` | Ordered sequence of parsed show-notes entries                     |
  | `usage`                | `LLMUsage`                   | Normalized token-usage counters from the provider response        |
  | `model`                | `str`                        | Model identifier echoed from the provider response (default `""`) |
  | `provider_response_id` | `str`                        | Provider-assigned response identifier (default `""`)              |
  | `finish_reason`        | `str or None`                | Provider finish reason, for example `"stop"` (default `None`)     |

- `ShowNotesGeneratorConfig` is a dataclass:

  Table: `ShowNotesGeneratorConfig` fields.

  | Field                | Type                          | Notes                                                                                                    |
  | -------------------- | ----------------------------- | -------------------------------------------------------------------------------------------------------- |
  | `model`              | `str`                         | Model identifier to pass in the LLM request                                                              |
  | `provider_operation` | `LLMProviderOperation or str` | Defaults to `LLMProviderOperation.CHAT_COMPLETIONS`                                                      |
  | `token_budget`       | `LLMTokenBudget or None`      | Optional token-budget constraints forwarded to `LLMPort`                                                 |
  | `system_prompt`      | `str`                         | System instruction sent alongside the user prompt; defaults to the built-in show-notes extraction prompt |

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
  [`adr-004-show-notes-tei-representation.md`](adr/adr-004-show-notes-tei-representation.md):
  `<list>` contains one `<item>` per note, `<label>` carries the topic, the
  summary is inline text, `@n` stores an optional timestamp, and `@corresp`
  stores an optional source locator.
- `ShowNotesResponseFormatError` is a `ValueError` subclass raised by
  `ShowNotesGenerator` whenever the LLM response cannot be parsed into a valid
  `ShowNotesResult`. Callers should catch this exception to handle malformed or
  unexpected LLM output gracefully. It is raised when the response text is not
  valid JSON; when the top-level JSON object does not contain an `entries`
  list; when an entry in `entries` is not a JSON object; when a required field
  (`topic` or `summary`) is absent, empty, or not a string; when an optional
  field (`timestamp` or `tei_locator`) is present but is not a string or null;
  and when a `timestamp` value does not match the ISO 8601 duration format.
- `ChapterMarkersGenerator` follows the same boundary in
  `episodic/generation/chapter_markers.py`. It depends only on `LLMPort` and
  accepts a TEI script plus optional `segment_structure` metadata describing
  segment starts and identifiers.
- `ChapterMarker` carries a title, required `start` time, optional summary,
  optional `end`, optional `duration`, and optional `tei_locator`. Start, end,
  and duration values must be non-negative integer-only ISO 8601-style
  `PT#H#M#S` durations. Days and fractional units are not accepted. A
  `ChapterMarkersResult` rejects duplicate or descending starts, and
  `ChapterMarkersGenerator.generate(...)` rejects outputs that do not align to
  explicit starts and locators in supplied `segment_structure` metadata.
- `enrich_tei_with_chapter_markers(...)` inserts a
  `<div type="chapters">` element into the TEI body using the representation
  defined by
  [`adr-008-chapter-marker-tei-representation.md`](adr/adr-008-chapter-marker-tei-representation.md).
  The `<list>` contains one `<item>` per chapter, `<label>` carries the title,
  `@n` stores the required start time, and `@corresp` stores an optional source
  locator. Optional DTO `end` and `duration` values are validated but not
  emitted into TEI until the TEI tooling exposes supported attributes.
- `ChapterMarkersResponseFormatError` is a `ValueError` subclass raised when
  the LLM response is not valid JSON, when the top-level object does not
  contain a `chapters` list, when a chapter entry is not an object, when
  required fields are absent or blank, when optional fields are not strings or
  null, or when timing values fail validation.

Standalone chapter-marker usage pattern:

```python
from episodic.generation import (
    ChapterMarkersGenerator,
    ChapterMarkersGeneratorConfig,
    ChapterMarkersResponseFormatError,
    enrich_tei_with_chapter_markers,
)
from episodic.llm.ports import LLMTokenBudget

chapter_config = ChapterMarkersGeneratorConfig(
    model="gpt-4o-mini",
    token_budget=LLMTokenBudget(
        max_input_tokens=4096,
        max_output_tokens=1024,
        max_total_tokens=5120,
    ),
)


async def enrich_with_chapters(llm_port, script_tei_xml: str) -> str:
    generator = ChapterMarkersGenerator(llm=llm_port, config=chapter_config)
    try:
        result = await generator.generate(
            script_tei_xml,
            segment_structure={
                "segments": [
                    {"id": "seg-intro", "title": "Introduction", "start": "PT0S"},
                    {"id": "seg-main", "title": "Main", "start": "PT5M30S"},
                ]
            },
        )
    except ChapterMarkersResponseFormatError:
        # handle malformed LLM response
        raise
    return enrich_tei_with_chapter_markers(script_tei_xml, result)
```

- `GuestBiosGenerator` follows the same boundary rules. It depends only on
  `LLMPort`, resolved reference-document projections, and canonical TEI XML.
  Keep reference-document retrieval outside the generator itself unless using
  the application helper `generate_guest_bios_from_reference_bindings(...)`,
  which composes around a `CanonicalUnitOfWork` and the existing binding
  resolver.
- `project_guest_bio_sources(...)` filters resolved bindings to
  `ReferenceDocumentKind.GUEST_PROFILE`. Do not broaden this function to use
  host profiles, style guides, or research briefs; those documents may
  influence other generation steps, but they are not biography subjects.
- `enrich_tei_with_guest_bios(...)` inserts one canonical
  `<div type="guest-bios">` block into the TEI body. Each `<item>` contains a
  `<label>` with the guest display name, inline biography text, and `@corresp`
  pointing at the pinned reference-document revision. The representation is
  defined by
  [`adr-010-guest-bios-tei-representation.md`](adr/adr-010-guest-bios-tei-representation.md).
- `GuestBiosResponseFormatError` is raised when the provider response is not a
  JSON object with a `guests` list, when required fields are missing or blank,
  when a revision identifier is unknown, or when the response duplicates a
  source revision. Treat this as malformed model output and surface it without
  silently dropping guests.

### Testing content generation services

- Unit coverage for show notes lives in `tests/test_show_notes.py`.
- Behavioural coverage lives in `tests/features/show_notes.feature` and
  `tests/steps/test_show_notes_steps.py`.
- Unit and property coverage for chapter markers lives in
  `tests/test_chapter_markers.py`.
- Behavioural coverage lives in `tests/features/chapter_markers.feature` and
  `tests/steps/test_chapter_markers_steps.py`.
- Unit and property coverage for guest biographies lives in
  `tests/test_guest_bios.py`, `tests/test_guest_bios_properties.py`, and
  `tests/test_guest_bios_executor.py`.
- Guest-bio behavioural coverage lives in
  `tests/features/guest_bios.feature` and
  `tests/steps/test_guest_bios_steps.py`.
- The behavioural scenarios use Vidai Mock in the same style as Pedante. When
  writing provider fixtures, keep the prompt assertions structural and the
  response template minimal so prompt wording can evolve without making the
  scenario brittle. Guest-bio scenarios should assert that pinned guest profile
  content reaches the provider request and that the enriched TEI contains the
  canonical `guest-bios` block.

## Structured generation orchestration

Roadmap item `2.4.1` introduces a dedicated orchestration package in
`episodic/orchestration/`.

### Package structure

- `episodic/orchestration/_dto.py` contains the orchestration DTOs and shared
  checkpoint DTOs.
- `episodic/orchestration/_protocols.py` contains the planner, executor,
  checkpoint, and resume ports that keep graph policy independent of storage,
  queue, and provider adapters.
- `episodic/orchestration/generation.py` implements and exports
  `StructuredGenerationPlanner`, `StructuredPlanningOrchestrator`, and the
  orchestration result builder. It also re-exports the orchestration ports and
  checkpoint DTOs.
- `episodic/orchestration/_show_notes_executor.py` contains the concrete
  `ShowNotesToolExecutor` implementation.
- `episodic/orchestration/_guest_bios_executor.py` contains the concrete
  `GuestBiosToolExecutor` implementation. It resolves the request's
  `series_profile_id`, optional `episode_id`, and optional `template_id`
  through the configured binding resolver before invoking the generation helper.
- `episodic/orchestration/langgraph.py` contains the in-process LangGraph path
  used for `plan -> execute -> finish` and the checkpointing path that pauses
  after planning.
- `episodic/orchestration/checkpoints.py` contains the in-memory checkpoint
  adapter used by fast tests.
- `episodic/canonical/storage/workflow_checkpoints.py` contains the SQLAlchemy
  adapter for durable checkpoint persistence.

`build_generation_orchestration_graph(...)` accepts an optional
`finish_callback: Callable[[GenerationOrchestrationResult], None]` for
observability and test event recording. The hook fires only on the direct
`plan -> execute -> finish` path, after finish-node aggregation has produced
the domain result and before the graph returns. It is not invoked on the
checkpoint suspend path. Callback exceptions are logged without replacing the
already computed graph result. The graph does not serialize concurrent
invocations of a shared callback; callbacks that mutate shared state must
provide their own synchronization.

`GenerationGraphState` is part of the public orchestration API for callers that
invoke the LangGraph graph directly. Treat it as the framework state carrier
for graph nodes rather than as a domain DTO exposed through hooks.

`resume_generation_orchestration(...)` is the public API for completing a
checkpointed run. Pass the same `CheckpointPort` used by the suspend path, a
`TaskResumePort` that returns the externally completed action result, and a
`ResumeWorkflowCommand` naming the checkpoint. The helper reloads the persisted
planner result, combines it with the resumed action result, marks the
checkpoint resumed, and returns the final `GenerationOrchestrationResult`. It
raises `ValueError` for unknown checkpoints and `TypeError` for malformed
stored planner-result payloads.

### Checkpoint atomicity and observability

Durable checkpoint suspend uses `CheckpointPort.save_or_reuse(...)` as the
atomic idempotency boundary. Callers do not perform a pre-save lookup. They
construct a fresh `WorkflowCheckpoint`, call `save_or_reuse(...)`, and treat
the returned checkpoint identifier as authoritative. The SQLAlchemy adapter
inserts inside a nested savepoint and relies on the `idempotency_key`
uniqueness constraint for first-write-wins convergence. Concurrent suspend
attempts for the same workflow step therefore either persist the first
checkpoint or reuse the checkpoint that already owns the idempotency key.

`mark_resumed(...)` participates in the caller's unit of work. A committed unit
of work records the checkpoint as `resumed`; a rolled-back unit leaves the
checkpoint `suspended`, so the recovery path is non-destructive. Any retry
after a resume-side partial failure depends on the concrete `TaskResumePort`
adapter treating duplicate resume commands idempotently.

Checkpoint storage metrics use the shared `MetricsPort` contract from
`episodic.observability` and must keep labels bounded. The SQLAlchemy adapter
emits:

- `workflow_checkpoint.save_or_reuse.operations` with `outcome` values
  `persisted`, `reused`, or `recovery_failure`.
- `workflow_checkpoint.save_or_reuse.idempotency_conflicts` with `outcome` set
  to `conflict`.
- `workflow_checkpoint.save_or_reuse.latency_ms` with the same `outcome` labels
  as the save operation counter.
- `workflow_checkpoint.mark_resumed.operations` and
  `workflow_checkpoint.mark_resumed.latency_ms` with `outcome` values `marked`
  or `unknown_checkpoint`.
- `workflow_checkpoint.recovery_failures` with `operation=save_or_reuse` and
  `reason=conflict_missing_checkpoint`.

Production alerting should page on any non-zero
`workflow_checkpoint.recovery_failures{reason="conflict_missing_checkpoint"}`
event, because it means duplicate-key convergence failed after the database
reported an idempotency conflict. Trend
`workflow_checkpoint.save_or_reuse.idempotency_conflicts` and save latency for
load and retry pressure, but do not label checkpoint metrics with workflow ids,
checkpoint ids, or idempotency keys.

### Maintainer rules

- Keep the planner strict: parse model output into typed DTOs immediately and
  raise deterministic validation errors for malformed JSON.
- Keep model-tier selection in `GenerationOrchestrationConfig`; do not couple
  this slice to pricing-ledger or budget-reservation persistence.
- Keep LangGraph nodes dependent on ports and orchestration DTOs only. Tool
  implementations may call generation services, but the graph should see only
  `ToolExecutorPort`.
- Persist suspend state through `CheckpointPort` and resume external task
  results through `TaskResumePort`. Do not import SQLAlchemy, Celery, Falcon,
  or provider adapters into graph nodes.
- Build idempotency keys by constructing a `WorkflowStepIdentity` containing
  the workflow id, workflow type, step name, and action id, then passing that
  identity plus a separate `attempt` retry count to
  `build_workflow_step_idempotency_key(...)`.
- In-memory checkpoints are for tests only. They use an injected clock and an
  `asyncio.Lock` to model first-write-wins idempotency, but they do not evict
  entries or coordinate across processes.
- Durable checkpoints rely on the `workflow_checkpoints.idempotency_key`
  uniqueness constraint. The SQLAlchemy adapter attempts the insert first and
  falls back to loading the existing row only when the database reports a
  duplicate key.
- Treat `ShowNotesToolExecutor` and `GuestBiosToolExecutor` as tool adapters,
  not as special cases that other orchestration code may import around. Use
  `RoutingToolExecutor` when one orchestration run needs to dispatch multiple
  action kinds.

### Testing the orchestration slice

- Unit coverage for DTO validation, planner behaviour, orchestration dispatch,
  show-notes execution, guest-bio execution, and properties lives in the focused
  `tests/test_orchestration_*.py`, `tests/test_show_notes_executor.py`, and
  `tests/test_guest_bios_executor.py` modules.
- Issue `#72` property coverage lives in
  `tests/test_orchestration_properties.py` and the focused sibling modules for
  config/model-tier boundaries, planner format errors, and LangGraph invariants.
- `tests/test_generation_orchestration_snapshots.py` pins planner format-error
  messages and orchestration artefacts with Syrupy snapshots.
- LangGraph seam coverage lives in
  `tests/test_generation_orchestration_langgraph.py`.
- Behavioural coverage lives in
  `tests/features/generation_orchestration.feature` and
  `tests/steps/test_generation_orchestration_steps.py`.
- The orchestration behaviour scenario uses Vidai Mock to return two distinct
  responses from one OpenAI-compatible endpoint: the first for structured
  planning, and the second for the show-notes tool call. Keep that fixture
  model-driven so prompt wording can evolve without breaking the scenario.
- Durable checkpoint coverage lives in
  `tests/canonical_storage/test_workflow_checkpoints.py` and uses py-pglite via
  the migrated SQLAlchemy fixtures.

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
  `"reliability_coefficient"` (default 0.2). Pass optional `metrics=` when
  constructing the strategy so production deployments can wire
  `CpuTaskExecutorMetricsPort` through to the environment-built executor.
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

### LogLevel

`episodic.logging.LogLevel` is a `StrEnum` with the following members:

Table: Log levels used by the application

| Value      | Notes                                                       |
| ---------- | ----------------------------------------------------------- |
| `TRACE`    | Verbose trace-level output                                  |
| `DEBUG`    | Debug-level output                                          |
| `INFO`     | Informational output (default)                              |
| `WARNING`  | Warning output                                              |
| `WARN`     | Deprecated alias for `WARNING`; raises `DeprecationWarning` |
| `ERROR`    | Error output                                                |
| `CRITICAL` | Critical error output                                       |

### configure_logging

```python
def configure_logging(
    level: str | None,
    *,
    force: bool = False,
) -> tuple[LogLevel, bool]: ...
```

`level` is matched case-insensitively against `LogLevel` members. Returns a
`tuple[LogLevel, bool]` — the normalized effective level and a flag that is
`True` when the default (`INFO`) was substituted because the input was absent
or unrecognized. The first element is always a `LogLevel` member; because
`LogLevel` is a `StrEnum`, those values are also `str` instances. Passing
`"WARN"` (any case) normalizes to `WARNING` and emits a `DeprecationWarning`.
The `force` parameter is forwarded directly to `femtologging.basicConfig`.

### Internal protocol interfaces

Two private Protocol types define the logger surface consumed by helper
functions:

- `_SupportsConvenienceLog` — objects exposing the three stdlib-style
  convenience methods:

  ```python
  def info(
      self,
      message: str,
      /,
      *,
      exc_info: object | None = None,
      stack_info: bool = False,
  ) -> None: ...


  def warning(
      self,
      message: str,
      /,
      *,
      exc_info: object | None = None,
      stack_info: bool = False,
  ) -> None: ...


  def error(
      self,
      message: str,
      /,
      *,
      exc_info: object | None = None,
      stack_info: bool = False,
  ) -> None: ...
  ```

- `_SupportsLogMethod` — objects exposing the generic stdlib-style entry
  point:

  ```python
  def log(
      self,
      level: int | LogLevel,
      message: str,
      /,
      *,
      exc_info: object | None = None,
      stack_info: bool = False,
  ) -> None: ...
  ```

  `level` accepts an `int | LogLevel` value.

In every signature, the message (and `level` plus message for `log`) are
positional-only before `/`, and `exc_info` and `stack_info` are keyword-only
after `*`. Adapter authors must implement the full surface — including the
`exc_info` and `stack_info` keyword-only parameters — for the helpers to call
them correctly.

Custom logger adapters passed to `log_info`, `log_warning`, or `log_error` must
satisfy `_SupportsConvenienceLog`. Code that calls `log_at_level` must satisfy
`_SupportsLogMethod`.

## Asyncio task utilities

`episodic.asyncio_tasks` provides `create_task` and `create_task_in_group` as
thin wrappers around `asyncio.TaskGroup.create_task`. Both helpers accept an
optional set of extra keyword arguments that are validated by the internal
`_validate_task_create_kwargs` helper before being forwarded to the underlying
task-creation call.

`_validate_task_create_kwargs` accepts a `cabc.Mapping[str, object]` rather
than a concrete `dict[str, object]`, so read-only mappings such as
`types.MappingProxyType` are accepted at runtime. The helper converts the
validated mapping to a plain `dict` before returning a `TaskCreateKwargs`
payload.

Accepted keys are those defined in `TaskCreateKwargs`: `name`, `context`,
`eager_start`, and `metadata` (see `TaskMetadata` for the metadata field
schema). Passing an unrecognized key raises `TypeError`.
