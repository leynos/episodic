"""Expired-lease reclamation for the durable generation-run adapter.

The reclamation transaction lives here rather than in
:mod:`episodic.canonical.storage.generation_runs` because it is the one
generation-run operation that reads two tables: the candidate runs and the
review checkpoints that guard them. Keeping it beside the store would push that
module past the project's file-size ceiling and bury the two-table relationship
among single-table operations.

It is a mixin so the composing store supplies its own session, event allocator,
and lifecycle transitions. A free function would take those as parameters, and
a second session would break the property that makes the guard worth having:
candidate selection and checkpoint lookup must be evaluated in one transaction.
"""

import typing as typ
import uuid  # ruff: ignore[typing-only-standard-library-import]  # SQLAlchemy evaluates annotations at runtime.

import sqlalchemy as sa

from episodic.canonical.domain import (
    CheckpointStatus,
    GenerationEvent,
    GenerationRun,
    GenerationRunStatus,
    JsonMapping,
)
from episodic.canonical.generation_run_lease_ports import lease_reclamation_limit
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.logging import log_event as _log_event

from .generation_run_mappers import run_from_record
from .generation_run_models import GenerationRunRecord
from .review_checkpoint_models import ReviewCheckpointRecord

if typ.TYPE_CHECKING:
    import datetime as dt

    from sqlalchemy.ext.asyncio import AsyncSession

_LEASE_ERROR_CATEGORY = "launcher.lease_expired"
_LEASE_ERROR_MESSAGE = "Generation lease expired; failed manually."


class GenerationRunLeaseHost(typ.Protocol):
    """Store members the lease-reclamation mixin calls back into."""

    _session: AsyncSession

    async def append_event(
        self,
        run_id: uuid.UUID,
        *,
        kind: str,
        payload: JsonMapping,
        occurred_at: dt.datetime | None = None,
    ) -> GenerationEvent:
        """Append an event to a run that is still mutable."""
        ...

    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        update: GenerationRunStatusUpdate,
    ) -> GenerationRun:
        """Apply a lifecycle transition to a run."""
        ...


def expired_lease_candidates(
    *,
    now: dt.datetime,
    limit: int,
) -> sa.Select[tuple[GenerationRunRecord]]:
    """Select runs whose execution lease expired at or before ``now``.

    Parameters
    ----------
    now : dt.datetime
        Instant the lease must have expired at or before.
    limit : int
        Maximum number of runs to select.

    Returns
    -------
    sa.Select
        Statement selecting candidate records oldest-expiry-first.

    Notes
    -----
    The checkpoint clause is a ``NOT EXISTS`` subquery rather than a Python
    read-filter-write, so the whole reclamation condition is one predicate the
    database evaluates. A split version would leave the checkpoint guard
    unprotected by the row selection, and no test under a harness that
    serializes every session could observe the difference.

    ``FOR UPDATE`` is retained: it is what the manual runbook relies on to stop
    a second operator acting on a row being reclaimed. ``SKIP LOCKED`` is
    deliberately absent -- under ``py-pglite`` one WebAssembly PostgreSQL
    backend serializes every session, so the clause can never be shown to skip
    a locked row, and shipping it would assert a concurrency guarantee nothing
    in this repository demonstrates.
    """
    open_checkpoint = (
        sa
        .select(ReviewCheckpointRecord.id)
        .where(
            ReviewCheckpointRecord.generation_run_id == GenerationRunRecord.id,
            ReviewCheckpointRecord.status == CheckpointStatus.CREATED,
        )
        .exists()
    )
    return (
        sa
        .select(GenerationRunRecord)
        .where(
            GenerationRunRecord.status == GenerationRunStatus.RUNNING,
            GenerationRunRecord.lease_expires_at.is_not(None),
            GenerationRunRecord.lease_expires_at <= now,
            ~open_checkpoint,
        )
        .order_by(
            GenerationRunRecord.lease_expires_at,
            GenerationRunRecord.id,
        )
        .limit(limit)
        .with_for_update()
    )


if typ.TYPE_CHECKING:
    _MixinBase = GenerationRunLeaseHost
else:
    _MixinBase = object


class GenerationRunLeaseReclamationMixin(_MixinBase):
    """Reclaim runs abandoned by a worker holding an expired execution lease."""

    async def fail_expired_leases(
        self,
        *,
        now: dt.datetime,
        limit: int = 100,
    ) -> tuple[GenerationRun, ...]:
        """Fail runs whose execution lease expired at or before ``now``.

        Parameters
        ----------
        now : dt.datetime
            The single instant this call reasons about. It bounds the expiry
            predicate *and* is written to ``ended_at``, ``updated_at``, and the
            ``run.failed`` event's ``occurred_at``, so one call never records
            two different "nows".
        limit : int
            Maximum number of runs to reclaim in this call. Must be positive;
            a call returning exactly ``limit`` runs has more work waiting, so a
            caller draining a backlog re-invokes until an empty tuple returns.

        Returns
        -------
        tuple[GenerationRun, ...]
            The reclaimed runs in their ``failed`` post-transition state,
            ordered by ascending ``(lease_expires_at, id)``.

        Notes
        -----
        Raises ``ValueError`` when ``limit`` is not positive; the shared
        validator owns that check and its message.

        A run is selected only when its status is ``running``, its
        ``lease_expires_at`` is non-null and at or before ``now``, and it has no
        checkpoint in ``created``. The checkpoint clause protects a run
        suspended awaiting human review, whose lease expires while it waits.

        Each reclaimed run gets exactly one ``run.failed`` event, appended
        **before** the status update: a run's event stream closes when the run
        ends, so an append attempted afterwards is rejected. The transition
        flushes rather than commits, so the caller owns the transaction and
        commits the event and the status change together.
        """
        lease_reclamation_limit(limit)
        result = await self._session.execute(
            expired_lease_candidates(now=now, limit=limit)
        )
        candidates = list(result.scalars())
        _log_event(
            "info",
            "sql_generation_run_store.fail_expired_leases",
            reclaimed=len(candidates),
            limit=limit,
        )
        reclaimed: list[GenerationRun] = []
        for record in candidates:
            await self.append_event(
                record.id,
                kind="run.failed",
                payload={
                    "error_category": _LEASE_ERROR_CATEGORY,
                    "error_message": _LEASE_ERROR_MESSAGE,
                },
                occurred_at=now,
            )
            await self.update_run_status(
                record.id,
                update=GenerationRunStatusUpdate(
                    status=GenerationRunStatus.FAILED,
                    current_node=None,
                    ended_at=now,
                    error_message=_LEASE_ERROR_MESSAGE,
                    error_category=_LEASE_ERROR_CATEGORY,
                ),
            )
            # `update_run_status` stamps `updated_at` from the adapter clock,
            # which is a *different* instant from `now`. This primitive promises
            # one instant per call, so the record is re-stamped and remapped
            # here rather than taken from the transition's return value. The
            # select above loaded this row into the same session, so `record` is
            # the instance the transition just updated.
            record.updated_at = now
            await self._session.flush()
            reclaimed.append(run_from_record(record))
        return tuple(reclaimed)
