"""Root pytest configuration: plugin registration and cross-cutting fixtures."""

from __future__ import annotations

import asyncio
import typing as typ

import pytest

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    import sqlalchemy as sa

    from episodic.canonical.domain import EpisodeTemplate
    from episodic.canonical.ports import CanonicalUnitOfWork

pytest_plugins: list[str] = [
    "tests.fixtures.database",
    "tests.fixtures.llm",
    "tests.fixtures.api",
    "tests.fixtures.ingestion",
    "tests.fixtures.binding",
]


@pytest.fixture
def _function_scoped_runner() -> typ.Iterator[asyncio.Runner]:
    """Provide a function-scoped asyncio.Runner for sync BDD steps."""
    with asyncio.Runner() as runner:
        yield runner


def temporary_drift_table() -> typ.ContextManager[sa.Table]:
    """Compatibility wrapper for tests importing this helper from conftest."""
    from tests.fixtures.database import temporary_drift_table as _temporary_drift_table

    return _temporary_drift_table()


async def create_episode_template_for_binding_tests(
    uow: CanonicalUnitOfWork,
    series_id: uuid.UUID,
    now: dt.datetime,
) -> EpisodeTemplate:
    """Compatibility wrapper for tests importing this helper from conftest."""
    from tests.fixtures.binding import (
        create_episode_template_for_binding_tests as _create_episode_template,
    )

    return await _create_episode_template(uow, series_id, now)


def __getattr__(name: str) -> object:
    """Provide compatibility re-exports for tests importing from conftest."""
    if name == "BindingFixtures":
        from tests.fixtures.binding import BindingFixtures

        return BindingFixtures
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
