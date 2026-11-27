"""Persist and schedule one generation run, recording scheduling failures.

Creation failures propagate unchanged. A launcher refusal is translated into
the overloaded error after the persisted run is marked terminal, so a run that
was never scheduled cannot stay pending forever.
"""

import dataclasses as dc
import typing as typ

from episodic.api.resources.generation_runs_errors import _generation_overloaded
from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.generation.launcher import GenerationRunAdmissionError

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.api.types import UowFactory
    from episodic.generation.launcher import GenerationRunLauncher
    from episodic.observability import SpanHandle
    from episodic.runtime_providers import Clock


@dc.dataclass(frozen=True, slots=True)
class SchedulingContext:
    """Collaborators a scheduling failure needs to mark its run terminal."""

    uow_factory: UowFactory
    clock: Clock


async def create_and_schedule_run(
    create_run: cabc.Awaitable[GenerationRun],
    launcher: GenerationRunLauncher,
    span: SpanHandle,
    context: SchedulingContext,
) -> GenerationRun:
    """Await run creation, schedule it, and mark terminal scheduling failures.

    Parameters
    ----------
    create_run : cabc.Awaitable[GenerationRun]
        The pending run creation already in flight.
    launcher : GenerationRunLauncher
        Launcher that accepts the run for detached execution.
    span : SpanHandle
        Command span that records the scheduling outcome.
    context : SchedulingContext
        Unit-of-work factory and clock used to mark a run terminal.

    Returns
    -------
    GenerationRun
        The persisted run after its launcher accepts scheduling.

    Raises
    ------
    _generation_overloaded
        If bounded launcher admission rejects the persisted run.
    Exception
        Any other scheduling failure, after the run is marked terminal.
    """  # ruff: ignore[docstring-extraneous-exception]  # The overloaded error is built by a helper.
    run = await create_run
    span.set_attribute("run_id", str(run.id))
    try:
        await launcher.launch(run.id)
    except GenerationRunAdmissionError as exc:
        span.set_attribute("outcome", "rejected")
        span.set_attribute("failure_category", "launcher.overloaded")
        await mark_launch_failed(
            context,
            run.id,
            error_message=str(exc),
            error_category="launcher.overloaded",
        )
        raise _generation_overloaded() from exc
    except Exception as exc:
        span.set_attribute("outcome", "failed")
        span.set_attribute("failure_category", "launcher.scheduling")
        await mark_launch_failed(
            context,
            run.id,
            error_message=str(exc),
            error_category="launcher.scheduling",
        )
        raise
    return run


async def mark_launch_failed(
    context: SchedulingContext,
    run_id: uuid.UUID,
    *,
    error_message: str,
    error_category: str,
) -> None:
    """Mark a run failed, ignoring runs that are terminal or missing."""
    now = context.clock()
    async with context.uow_factory() as uow:
        try:
            await uow.generation_runs.update_run_status(
                run_id,
                update=GenerationRunStatusUpdate(
                    status=GenerationRunStatus.FAILED,
                    current_node=None,
                    ended_at=now,
                    error_message=error_message,
                    error_category=error_category,
                ),
            )
        except RunAlreadyTerminal, RunNotFound:
            await uow.rollback()
        else:
            await uow.commit()


__all__ = ["SchedulingContext", "create_and_schedule_run", "mark_launch_failed"]
