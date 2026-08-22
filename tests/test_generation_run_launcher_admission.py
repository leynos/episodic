"""Tests for in-process generation-run admission capacity."""

import dataclasses as dc
import typing as typ
import uuid

import pytest

from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.generation.launcher import GenerationRunAdmissionError
from tests.generation_run_launcher_support import (
    LauncherOptions,
    ReleasableDraftGenerator,
    draft_result,
    launcher,
    prepare_pending_run,
    valid_tei,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_launcher_releases_admission_capacity_after_completion(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A completed run should release capacity for a later launch."""
    first_run_id, _ = await prepare_pending_run(session_factory)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        first_run = await uow.generation_runs.get_run(first_run_id)
        assert first_run is not None, f"run {first_run_id} was not persisted"
        second_run_id = uuid.uuid7()
        await uow.generation_runs.create_run(dc.replace(first_run, id=second_run_id))
        await uow.commit()
    generator = ReleasableDraftGenerator(draft_result(valid_tei()))
    run_launcher = launcher(
        session_factory,
        generator,
        options=LauncherOptions(max_concurrency=1, max_pending_runs=0),
    )

    await run_launcher.launch(first_run_id)
    await generator.started.wait()
    with pytest.raises(GenerationRunAdmissionError, match="capacity"):
        await run_launcher.launch(second_run_id)

    generator.release.set()
    await run_launcher.drain()

    assert run_launcher.scheduled_run_count == 0, (
        f"retained runs: {run_launcher.scheduled_run_count}"
    )

    await run_launcher.launch(second_run_id)
    await run_launcher.drain()

    assert run_launcher.scheduled_run_count == 0, (
        f"retained runs: {run_launcher.scheduled_run_count}"
    )
