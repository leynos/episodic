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

from episodic.generation.launcher_support import Failure, classify_failure
from episodic.logging import get_logger, log_info

if typ.TYPE_CHECKING:
    import uuid

_METRIC_ADMISSION_REJECTED = "generation_run_admission_rejected_total"

logger = get_logger(__name__)


class GenerationRunAdmissionError(RuntimeError):
    """Raised when a launcher cannot retain another pending run."""


@dc.dataclass(frozen=True, slots=True)
class _ExecutionOutcome:
    """Describe the terminal result of one launcher task."""

    outcome: str
    failure_category: str | None = None


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
        """Return the number of background runs retained by the launcher."""
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
            if task.cancelled() and run_id not in self._cancelled_run_ids:
                await asyncio.shield(self._record_cancellation(run_id))
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
            try:
                async with self._semaphore:
                    outcome = await self._execute_run(run_id)
            except asyncio.CancelledError:
                span.set_attribute("outcome", "cancelled")
                span.set_attribute("failure_category", "launcher.shutdown")
                await asyncio.shield(self._record_cancellation(run_id))
                self._cancelled_run_ids.add(run_id)
                raise
            else:
                span.set_attribute("outcome", outcome.outcome)
                if outcome.failure_category is not None:
                    span.set_attribute("failure_category", outcome.failure_category)

    async def _execute_run(self, run_id: uuid.UUID) -> _ExecutionOutcome:
        """Execute one generation run while its concurrency permit is held."""
        try:
            claimed = await self._claim(run_id)
            if claimed is None:
                return _ExecutionOutcome(outcome="not_claimed")
            result = await self._generate(claimed)
            await self._record_draft_generated(claimed.run.id, result)
            await self._persist_success(claimed, result)
            return _ExecutionOutcome(outcome="completed")
        except Exception as exc:  # noqa: BLE001  # Task boundary must persist unexpected failures.
            failure = classify_failure(exc)
            await self._record_failure(run_id, failure)
            return _ExecutionOutcome(
                outcome="failed",
                failure_category=failure.category,
            )

    async def _record_cancellation(self, run_id: uuid.UUID) -> None:
        """Record cancellation consistently before or during execution."""
        await self._record_failure(
            run_id,
            Failure(
                message="Generation task cancelled during shutdown.",
                category="launcher.shutdown",
            ),
        )
