"""Admit, schedule, and shut down background generation-run tasks.

:class:`_SchedulingMixin` supplies :class:`InProcessGenerationRunLauncher`
with bounded task admission, strong task references, and cancellation
handling. Admission is checked before an asyncio task is allocated, so a
launcher never exceeds its configured concurrency and pending-run budget.
Shutdown cancels outstanding tasks, drains them, and records cancellation as
a terminal failure rather than a restart-recoverable state.
"""

import asyncio
import dataclasses as dc
import typing as typ

from episodic.canonical.generation_graph_ports import ContentGenerationRequest
from episodic.canonical.generation_routing import (
    GenerationTerminal,
    route_quality_mode,
    terminal_outcome,
)
from episodic.generation.launcher_session import (
    RunNotClaimedError,
    _LauncherRunSession,
)
from episodic.generation.launcher_support import (
    Failure,
    RunClaim,
    classify_failure,
)
from episodic.logging import get_logger, log_info

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.generation_quality import QualityMode

_METRIC_ADMISSION_REJECTED = "generation_run_admission_rejected_total"

logger = get_logger(__name__)


def _terminal_outcome_name(terminal: GenerationTerminal) -> str:
    """Name the span outcome a terminal records."""
    outcome = terminal_outcome(terminal)
    return "escalated" if outcome.error_category is not None else "completed"


class GenerationRunAdmissionError(RuntimeError):
    """Raised when a launcher cannot retain another pending run."""


@dc.dataclass(frozen=True, slots=True)
class _ExecutionOutcome:
    """Describe the terminal result of one launcher task."""

    outcome: str
    failure_category: str | None = None
    quality_branch: str | None = None
    terminal: str | None = None


if typ.TYPE_CHECKING:
    from episodic.generation.launcher_host import LauncherHost as _MixinBase
else:
    _MixinBase = object


class _SchedulingMixin(_MixinBase):
    """Bound task admission and drive scheduled generation-run tasks."""

    __slots__ = ()

    async def launch(self, run_id: uuid.UUID) -> None:
        """Schedule a background task for one generation run."""
        self._admit()
        try:
            task = asyncio.create_task(
                self._run_task(run_id),
                name=f"generation-run-{run_id}",
            )
        except Exception:
            self._admitted_run_count -= 1
            self._record_pending_depth()
            raise
        self._tasks.add(task)
        self._task_run_ids[task] = run_id
        task.add_done_callback(self._discard_task)
        log_info(logger, "generation_run_launcher.scheduled run_id=%s", run_id)

    async def drain(self) -> None:
        """Wait for all currently scheduled tasks to finish."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    @property
    def scheduled_run_count(self) -> int:
        """The number of background runs retained by the launcher."""
        return len(self._tasks)

    async def shutdown(self) -> None:
        """Cancel and drain all scheduled generation tasks."""
        self._is_shutting_down = True
        cancelled_tasks = tuple(
            (task, self._task_run_ids[task]) for task in self._tasks if not task.done()
        )
        for task, _ in cancelled_tasks:
            task.cancel()
        await self.drain()
        for task, run_id in cancelled_tasks:
            if task.cancelled():
                await self._record_cancellation_owned(run_id, RunClaim())

    async def _record_cancellation_owned(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> None:
        """Record a cancellation from a task named for the run (INV-9).

        Shielding keeps a second cancellation from truncating the terminal
        event; naming the shielded write keeps the single-writer invariant
        true for this path too.
        """
        if run_id in self._cancelled_run_ids:
            return
        write = asyncio.create_task(
            self._record_cancellation(run_id, claim),
            name=f"generation-run-{run_id}",
        )
        recorded = await asyncio.shield(write)
        if recorded:
            self._cancelled_run_ids.add(run_id)

    def _discard_task(self, task: asyncio.Task[None]) -> None:
        """Remove finished tasks from the strong-reference registry."""
        self._tasks.discard(task)
        self._task_run_ids.pop(task, None)
        self._admitted_run_count -= 1
        self._record_pending_depth()

    def _admit(self) -> None:
        """Reserve bounded capacity before creating a background task."""
        if self._is_shutting_down:
            self.metrics.increment_counter(
                _METRIC_ADMISSION_REJECTED,
                labels={"reason": "shutdown"},
            )
            msg = "Generation run admission is closed during shutdown."
            raise GenerationRunAdmissionError(msg)
        capacity = self.max_concurrency + self.max_pending_runs
        if self._admitted_run_count >= capacity:
            self.metrics.increment_counter(
                _METRIC_ADMISSION_REJECTED,
                labels={"reason": "capacity"},
            )
            msg = "Generation run admission capacity is exhausted."
            raise GenerationRunAdmissionError(msg)
        self._admitted_run_count += 1
        self._record_pending_depth()

    async def _run_task(self, run_id: uuid.UUID) -> None:
        """Execute one scheduled generation run."""
        with self.tracer.start_span(
            "generation_run.execute",
            attributes={"operation": "generation_run.execute", "run_id": str(run_id)},
        ) as span:
            claim = RunClaim()
            try:
                async with self._semaphore:
                    outcome = await self._execute_run(run_id, claim)
            except asyncio.CancelledError:
                span.set_attribute("outcome", "cancelled")
                span.set_attribute("failure_category", "launcher.shutdown")
                await self._record_cancellation_owned(run_id, claim)
                raise
            span.set_attribute("outcome", outcome.outcome)
            if outcome.failure_category is not None:
                span.set_attribute("failure_category", outcome.failure_category)
            if outcome.quality_branch is not None:
                span.set_attribute("quality_branch", outcome.quality_branch)
            if outcome.terminal is not None:
                span.set_attribute("terminal", outcome.terminal)

    async def _read_quality_mode(self, run_id: uuid.UUID) -> QualityMode | None:
        """Read a run's requested quality mode before the graph forks on it."""
        async with self.uow_factory() as uow:
            run = await uow.generation_runs.get_run(run_id)
        return None if run is None else run.quality_mode

    async def _execute_run(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> _ExecutionOutcome:
        """Execute one generation run through the content-generation graph.

        ``claim`` carries this invocation's token once its claim commits. Until
        then a failure is written only if the failure path can claim the run
        itself, so a launcher that lost the race cannot overwrite the winner.

        Returns
        -------
        _ExecutionOutcome
            The terminal outcome, or ``not_claimed`` when another launcher
            owns the run.
        """
        try:
            quality_mode = await self._read_quality_mode(run_id)
            if quality_mode is None:
                return _ExecutionOutcome(outcome="not_claimed")
            terminal = await self.content_graph.run(
                ContentGenerationRequest(
                    run_id=run_id,
                    quality_mode=quality_mode,
                ),
                steps=_LauncherRunSession(
                    launcher=self,
                    run_id=run_id,
                    claim=claim,
                ),
            )
        except RunNotClaimedError:
            return _ExecutionOutcome(outcome="not_claimed")
        except Exception as exc:  # ruff: ignore[blind-except]  # Task boundary must persist unexpected failures.
            failure = classify_failure(exc)
            recorded = await self._record_failure(
                run_id,
                failure,
                claim=claim,
            )
            if not recorded:
                return _ExecutionOutcome(outcome="not_claimed")
            return _ExecutionOutcome(
                outcome="failed",
                failure_category=failure.category,
            )
        branch = route_quality_mode(quality_mode)
        log_info(
            logger,
            "generation_run.quality_branch run_id=%s branch=%s",
            run_id,
            branch.value,
        )
        return _ExecutionOutcome(
            outcome=_terminal_outcome_name(terminal),
            quality_branch=branch.value,
            terminal=terminal.value,
        )

    async def _record_cancellation(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> bool:
        """Record cancellation consistently before or during execution.

        Returns
        -------
        bool
            ``True`` when this invocation wrote the terminal state. A refused
            write must not mark the run cancelled, or a losing invocation
            would suppress the owner's cancellation write.
        """
        return await self._record_failure(
            run_id,
            Failure(
                message="Generation task cancelled during shutdown.",
                category="launcher.shutdown",
            ),
            claim=claim,
        )
