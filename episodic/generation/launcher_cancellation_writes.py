"""Track and bound the shielded cancellation writes of generation runs.

A cancellation write is shielded so a second cancellation cannot lose it,
which means an unresponsive database call could hold shutdown open. This unit
owns that bookkeeping: the pending and completed sets, the tasks themselves,
the timeout each wait applies, and the timeout counter. The scheduler keeps
scheduling and draining, and delegates every cancellation write here.
"""

import asyncio
import dataclasses as dc
import typing as typ

from episodic.logging import get_logger, log_info

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.generation.launcher_support import ClaimToken, RunClaim
    from episodic.observability import ValueMetricsPort

_METRIC_CANCELLATION_TIMEOUT = "generation_run_cancellation_write_timeouts_total"

logger = get_logger(__name__)

type CancellationRecorder = cabc.Callable[
    [uuid.UUID, RunClaim],
    cabc.Awaitable[ClaimToken | None],
]


@dc.dataclass(slots=True)
class CancellationWrites:
    """The cancellation writes one scheduler has started but not cleared.

    Attributes
    ----------
    record_cancellation : CancellationRecorder
        Persists one cancellation and reports whether it landed.
    metrics : ValueMetricsPort
        Sink for the timeout counter.
    timeout_seconds : cabc.Callable[[], float]
        Reads the deadline each wait applies to a shielded write. A getter,
        not a value, so a timeout changed after construction still bounds the
        next write; ``drain`` already reads the runtime value.
    tasks : set[asyncio.Task[ClaimToken | None]]
        Writes still in flight, retained so shutdown can await them.
    cancelled_run_ids : set[uuid.UUID]
        Runs whose cancellation write actually landed.
    pending_run_ids : set[uuid.UUID]
        Runs with a write in flight.
    """

    record_cancellation: CancellationRecorder
    metrics: ValueMetricsPort
    timeout_seconds: cabc.Callable[[], float]
    tasks: set[asyncio.Task[ClaimToken | None]] = dc.field(default_factory=set)
    cancelled_run_ids: set[uuid.UUID] = dc.field(default_factory=set)
    pending_run_ids: set[uuid.UUID] = dc.field(default_factory=set)

    async def record_owned(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> ClaimToken | None:
        """Record a cancellation from a task named for the run (INV-9).

        Returns
        -------
        ClaimToken | None
            The authority a committed write used, or ``None`` when the write
            was already recorded, did not land, or missed its deadline.
        """
        if run_id in self.cancelled_run_ids:
            return None
        if claim.token is None and run_id in self.pending_run_ids:
            return None
        self.pending_run_ids.add(run_id)

        async def perform() -> ClaimToken | None:
            """Await the configured recorder and report the token it used."""
            return await self.record_cancellation(run_id, claim)

        write = asyncio.create_task(
            perform(),
            name=f"generation-run-{run_id}",
        )
        self.tasks.add(write)
        write.add_done_callback(lambda task: self._clear(run_id, task))
        try:
            token = await asyncio.wait_for(
                asyncio.shield(write),
                timeout=self.timeout_seconds(),
            )
        except TimeoutError:
            self.report_timeout(run_id)
            return None
        if token is not None:
            self.cancelled_run_ids.add(run_id)
        return token

    def _clear(
        self,
        run_id: uuid.UUID,
        task: asyncio.Task[ClaimToken | None],
    ) -> None:
        """Forget a finished cancellation write."""
        self.tasks.discard(task)
        self.pending_run_ids.discard(run_id)

    def report_timeout(self, run_id: uuid.UUID | None) -> None:
        """Record that a cancellation write missed its deadline.

        The write is left running: it is shielded, so it can still land. A run
        whose earlier execution claim committed falls back to expired-lease
        reclamation. A failure-only claim commits with its terminal write, so a
        stalled one leaves the run pending, and any transaction still holding
        its row lock must be released before a fresh claim can succeed.
        """
        log_info(
            logger,
            "generation_run_launcher.cancellation_write_timeout run_id=%s",
            run_id,
        )
        self.metrics.increment_counter(_METRIC_CANCELLATION_TIMEOUT, labels={})

    async def drain(self, *, deadline: float | None) -> None:
        """Await the pending writes, bounded only when a deadline is given.

        Parameters
        ----------
        deadline : float | None
            Seconds to wait, or ``None`` to wait until every write finishes.
        """
        pending = tuple(self.tasks)
        if not pending:
            return
        if deadline is None:
            await asyncio.gather(*pending, return_exceptions=True)
            return
        _done, still_pending = await asyncio.wait(pending, timeout=deadline)
        if still_pending:
            self.report_timeout(None)
