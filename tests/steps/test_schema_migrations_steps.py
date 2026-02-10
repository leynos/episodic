"""Behavioural tests for schema migration drift detection.

Examples
--------
Run the schema migration BDD scenarios:

>>> pytest tests/steps/test_schema_migrations_steps.py -k schema
"""

from __future__ import annotations

import typing as typ

import pytest
import sqlalchemy as sa
from pytest_bdd import given, scenario, then, when

from episodic.canonical.storage.migration_check import detect_schema_drift
from episodic.canonical.storage.models import Base

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncEngine


class DriftContext(typ.TypedDict, total=False):
    """Shared state for schema migration BDD steps."""

    engine: AsyncEngine
    diffs: list[tuple[object, ...]]
    temp_table: sa.Table | None


def _run_async_step(
    runner: asyncio.Runner,
    step_fn: cabc.Callable[[], typ.Awaitable[None]],
) -> None:
    """Execute an async BDD step via the provided runner."""
    coro = typ.cast("typ.Coroutine[object, object, None]", step_fn())
    runner.run(coro)


@scenario(
    "../features/schema_migrations.feature",
    "No drift when models match migrations",
)
def test_no_drift_when_models_match_migrations() -> None:
    """Run the no-drift scenario."""


@scenario(
    "../features/schema_migrations.feature",
    "Drift detected when models diverge from migrations",
)
def test_drift_detected_when_models_diverge() -> None:
    """Run the drift-detected scenario."""


@pytest.fixture
def drift_context() -> typ.Iterator[DriftContext]:
    """Share state between BDD steps and clean up temp tables."""
    ctx: DriftContext = typ.cast("DriftContext", {})
    yield ctx
    temp_table = ctx.get("temp_table")
    if temp_table is not None and temp_table.key in Base.metadata.tables:
        Base.metadata.remove(temp_table)


@given("all Alembic migrations have been applied")
def migrations_applied(
    migrated_engine: AsyncEngine,
    drift_context: DriftContext,
) -> None:
    """Store the migrated engine in the shared context."""
    drift_context["engine"] = migrated_engine


@given(
    "an unmigrated table has been added to the ORM metadata",
    target_fixture="drift_context",
)
def unmigrated_table_added(drift_context: DriftContext) -> DriftContext:
    """Add a temporary table to Base.metadata that has no migration."""
    table = sa.Table(
        "_test_drift_table",
        Base.metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )
    drift_context["temp_table"] = table
    return drift_context


@when("the schema drift check runs")
def drift_check_runs(
    _function_scoped_runner: asyncio.Runner,
    drift_context: DriftContext,
) -> None:
    """Run the schema drift detection."""

    async def _check() -> None:
        engine = drift_context["engine"]
        drift_context["diffs"] = await detect_schema_drift(engine)

    _run_async_step(_function_scoped_runner, _check)


@then("no drift is detected")
def no_drift(drift_context: DriftContext) -> None:
    """Assert the drift check found no differences."""
    diffs = drift_context["diffs"]
    assert diffs == [], f"Expected no schema drift, found: {diffs}"


@then("schema drift is reported")
def drift_reported(drift_context: DriftContext) -> None:
    """Assert the drift check found at least one difference."""
    diffs = drift_context["diffs"]
    assert len(diffs) > 0, "Expected schema drift to be detected."
