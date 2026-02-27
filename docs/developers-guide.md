# Episodic developers' guide

This guide documents internal development practices for Episodic. Follow the
documentation style guide in `docs/documentation-style-guide.md` when updating
this file.

## Local development

- Use `uv` to manage the virtual environment and dependencies.
- Run `make lint`, `make typecheck`, and `make test` before proposing changes.
- Use the canonical content modules under `episodic/canonical` for schema and
  repository logic.
- The Makefile exports `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` so the
  `tei-rapporteur` bindings build against Python 3.14.

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
- Migrations are applied automatically for each test fixture instance.
- `make test` uses `PYTEST_XDIST_WORKERS=1` by default to avoid py-pglite
  cross-worker process termination. Override with
  `PYTEST_XDIST_WORKERS=<n> make test` when debugging worker-count behaviour.
- `EPISODIC_TEST_DB=sqlite` disables the py-pglite fixtures (tests that depend
  on them will be skipped).
- If a non-SQLite backend is requested while py-pglite is unavailable, the
  fixtures raise a clear error instead of silently skipping tests.

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

- `series_profile`: profile metadata, configuration, and current revision.
- `episode_templates`: one template when `template_id` is provided, or all
  templates for the series profile when omitted.

### Prompt scaffolding for generators

Use the canonical prompt helpers to build deterministic generation scaffolds
from structured briefs:

- `build_series_brief_prompt(...)` in `episodic.canonical` loads a structured
  brief and returns a rendered prompt payload.
- `episodic.canonical.prompts` exposes:
  - `build_series_brief_template(...)` to construct a Python 3.14 template
    string (`t"..."`) representation.
  - `render_template(...)` to render prompt text while preserving static and
    interpolation metadata for audit trails.
  - `render_series_brief_prompt(...)` as the standard convenience renderer for
    brief payloads.

The renderer accepts an optional interpolation escape callback, so adapters can
apply policy-specific sanitization (for example, XML/HTML escaping) without
changing canonical prompt assembly rules.

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

Structured logging uses femtologging. Import `get_logger` from
`episodic.logging` and emit messages via `log_info`, `log_warning`, or
`log_error` to keep log levels consistent.
