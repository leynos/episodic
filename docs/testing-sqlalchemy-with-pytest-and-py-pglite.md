# Testing SQLAlchemy with pytest and py-pglite

This guide documents the database-test approach used in this repository. The
source of truth is `tests/conftest.py`; update this document whenever that
fixture stack changes.

## 1. Overview

Episodic tests SQLAlchemy against py-pglite rather than SQLite. That keeps the
test suite aligned with PostgreSQL semantics while still using an ephemeral,
in-process database.

The project depends on:

- `py-pglite[async]` in the development dependency group.
- `asyncpg` in the main dependency set.
- `pytest-asyncio` for asynchronous tests.

In this repository, tests do not normally construct their own async database
URLs or start `PGliteManager` directly. The shared fixture stack in
`tests/conftest.py` owns py-pglite startup, readiness checks, migrations, and
session creation.

## 2. Shared fixture stack

Database-backed tests should build on these fixtures, in this order:

- `_pglite_sqlalchemy_manager(tmp_path)` is an internal async context manager
  that starts `SQLAlchemyAsyncPGliteManager`, waits for the engine to accept
  connections, and stops the manager during teardown.
- `pglite_sqlalchemy_manager` is the public function-scoped manager fixture.
- `pglite_engine` yields the helper-managed SQLAlchemy `AsyncEngine`.
- `migrated_engine` runs Alembic migrations by calling
  `episodic.canonical.storage.alembic_helpers.apply_migrations(...)`.
- `session_factory` returns `async_sessionmaker[AsyncSession]` with
  `expire_on_commit=False`.
- `pglite_session` yields an `AsyncSession` created from that migrated engine.
- `canonical_api_client` builds a Falcon test client whose unit-of-work factory
  uses the shared `session_factory`.

Because the stack depends on pytest's function-scoped `tmp_path`, each
database-backed test gets an isolated ephemeral database by default.

### Preferred fixture choices

- Use `session_factory` for repository, service, and unit-of-work tests.
- Use `pglite_session` for direct ORM-style assertions.
- Use `pglite_engine` for low-level engine or connectivity checks.
- Use `canonical_api_client` for synchronous Falcon endpoint tests.
- Reach for `pglite_sqlalchemy_manager` only when a test genuinely needs the
  py-pglite manager itself.

## 3. Writing asynchronous database tests

Most asynchronous persistence tests should depend on `session_factory` and use
`SqlAlchemyUnitOfWork`:

```python
import typing as typ

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from episodic.canonical.storage import SqlAlchemyUnitOfWork


@pytest.mark.asyncio
async def test_series_profile_round_trip(
    session_factory: typ.Callable[[], AsyncSession],
) -> None:
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.series_profiles.add(profile)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored = await uow.series_profiles.get(profile.id)

    assert stored == profile
```

This is the standard pattern across repository and service tests because it
exercises the same unit-of-work boundary used by the application.

When a test needs direct session access instead of the unit of work, use
`pglite_session`:

```python
import pytest
import sqlalchemy as sa


@pytest.mark.asyncio
async def test_session_executes_sql(pglite_session) -> None:
    result = await pglite_session.execute(sa.text("SELECT 1"))
    assert result.scalar_one() == 1
```

`pglite_session` is backed by the migrated engine, so the current Alembic
schema is already present.

## 4. Writing engine-level tests

Use `pglite_engine` only for lower-level checks that need direct `AsyncEngine`
access:

```python
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.asyncio
async def test_engine_is_live(pglite_engine: AsyncEngine) -> None:
    async with pglite_engine.connect() as connection:
        result = await connection.execute(sa.text("SELECT 1"))

    assert result.scalar_one() == 1
```

Do not re-create an engine with `create_async_engine(...)` inside ordinary
tests. The helper-managed engine from py-pglite is the supported path here.

## 5. Writing synchronous Falcon API tests

Falcon endpoint tests in this repository stay synchronous at the test boundary
and use `canonical_api_client`:

```python
def test_create_series_profile(canonical_api_client) -> None:
    response = canonical_api_client.simulate_post(
        "/series-profiles",
        json={
            "slug": "my-series",
            "title": "My Series",
            "configuration": {},
        },
    )

    assert response.status_code == 201
```

The client is already wired to `create_app(...)` with
`SqlAlchemyUnitOfWork(session_factory)`, so API tests share the same migrated
py-pglite database stack as repository tests.

## 6. Migrations and schema drift

`migrated_engine` is the fixture boundary that applies the current Alembic
migration set to the ephemeral database. Tests should therefore prefer
`migrated_engine`, `session_factory`, or `pglite_session` over `pglite_engine`
when they need the actual application schema.

The repository also enforces migration drift separately:

- `make check-migrations` runs
  `python -m episodic.canonical.storage.migration_check`.
- That command starts a separate ephemeral py-pglite instance with plain
  `PGliteManager`.
- It then creates an async SQLAlchemy engine from
  `config.get_connection_string()`, applies Alembic migrations, and compares
  the migrated schema against `Base.metadata`.

That drift check is related to the test fixtures, but it is not implemented
through `tests/conftest.py`.

## 7. Operational rules

- Node.js 18 or newer is required because py-pglite runs a WebAssembly-based
  PostgreSQL runtime.
- `make test` defaults `PYTEST_XDIST_WORKERS=1`. Keep that default unless
  deliberately investigating worker-count behaviour; higher worker counts can
  trigger py-pglite cross-worker process termination.
- `EPISODIC_TEST_DB=sqlite` disables the py-pglite-backed fixtures. Tests that
  depend on those fixtures will be skipped.
- If `EPISODIC_TEST_DB` requests a non-SQLite backend and py-pglite is not
  available, the fixtures raise a clear error rather than silently skipping.
- Do not add a parallel raw-`asyncpg` fixture stack or bespoke connection
  bootstrap unless py-pglite compatibility has been re-verified for the current
  dependency set.

## 8. Maintenance guidance

When changing the database-test approach, keep these files in sync:

- `tests/conftest.py`
- `docs/developers-guide.md`
- `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`

If the fixture stack changes, update this guide to describe the new public
entry points and retire any examples that no longer match the repository.
