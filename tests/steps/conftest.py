"""Fixtures shared by the generation-slice behavioural step modules."""

import typing as typ

import pytest

from tests.steps.no_qa_generation_slice_support import NoQaGenerationSliceContext

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def generation_slice_context(
    session_factory: async_sessionmaker[AsyncSession],
    _function_scoped_runner: asyncio.Runner,
) -> cabc.Iterator[NoQaGenerationSliceContext]:
    """Provide shared scenario state and release external resources afterward."""
    ctx = NoQaGenerationSliceContext(session_factory, _function_scoped_runner)
    yield ctx
    ctx.tear_down()
