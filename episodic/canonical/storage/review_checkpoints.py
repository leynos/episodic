"""PostgreSQL adapter for user-facing generation-run review checkpoints.

Every state change routes through the domain transition on :class:`Checkpoint`
and then persists whatever entity the domain returned. The adapter owns no
lifecycle rules of its own: INV-CKPT-1 exists because two independent
implementations of one rule set drift.

Transitions are applied by compare-and-set rather than ``SELECT ... FOR UPDATE``
(D-10, ADR-018). The predicate ``status = 'created'`` is the concurrency
control, and its outcome is observable sequentially — which a row lock is not,
under a harness that serializes every transaction globally.
"""

import typing as typ

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import Checkpoint, CheckpointStatus
from episodic.canonical.generation_run_errors import (
    CheckpointAlreadyExists,
    CheckpointAlreadyTerminal,
    CheckpointNotFound,
    RunNotFound,
)
from episodic.logging import log_event as _log_event
from episodic.observability import NoopValueMetrics, ValueMetricsPort

from .generation_run_models import GenerationRunRecord
from .generation_run_storage_runtime import (
    GenerationRunStorageRuntime,
    generation_run_storage_runtime,
)
from .review_checkpoint_mappers import (
    checkpoint_from_record,
    checkpoint_to_record,
    resolved_values,
)
from .review_checkpoint_models import ReviewCheckpointRecord

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import datetime as dt
    import uuid

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.domain import CheckpointResponse

_METRIC_CREATED = "review_checkpoint_created_total"
_METRIC_RESOLVED = "review_checkpoint_resolved_total"
_METRIC_OPEN = "review_checkpoint_open_gauge"
_METRIC_TERMINAL_CONFLICT = "review_checkpoint_terminal_conflict_total"


@typ.final
class SqlAlchemyReviewCheckpointStore:
    """Durable review-checkpoint adapter."""

    def __init__(
        self,
        session: "AsyncSession",  # ruff: ignore[quoted-annotation]  # Imported only during type checking.
        *,
        runtime: GenerationRunStorageRuntime | None = None,
        metrics: ValueMetricsPort | None = None,
    ) -> None:
        self._session = session
        self._runtime = generation_run_storage_runtime(runtime)
        self._metrics = metrics or NoopValueMetrics()

    async def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        """Persist a checkpoint, rejecting duplicate or terminal input.

        Parameters
        ----------
        checkpoint : Checkpoint
            Checkpoint to store. Its status must be ``created``.

        Returns
        -------
        Checkpoint
            The checkpoint that was stored.

        Raises
        ------
        RunNotFound
            If the parent generation run does not exist. Only existence is
            checked; the run's own status is deliberately not a precondition,
            so this adapter agrees with the in-memory one.
        CheckpointAlreadyExists
            If the identifier is already in use. Two adapters must not disagree
            on whether a replayed create overwrites a reviewer's decision.
        CheckpointAlreadyTerminal
            If the checkpoint arrives already resolved.
        """
        if checkpoint.status is not CheckpointStatus.CREATED:
            _log_event(
                "warning",
                "sql_review_checkpoint_store.create_checkpoint_terminal",
                checkpoint_id=str(checkpoint.id),
                run_id=str(checkpoint.generation_run_id),
                status=checkpoint.status.value,
            )
            raise CheckpointAlreadyTerminal(checkpoint.id)

        parent = await self._session.get(
            GenerationRunRecord, checkpoint.generation_run_id
        )
        if parent is None:
            _log_event(
                "warning",
                "sql_review_checkpoint_store.create_checkpoint_missing_run",
                checkpoint_id=str(checkpoint.id),
                run_id=str(checkpoint.generation_run_id),
            )
            raise RunNotFound(checkpoint.generation_run_id)

        record = checkpoint_to_record(checkpoint)
        try:
            # A nested transaction contains the primary-key violation, so a
            # rejected create does not poison unrelated pending writes on the
            # outer session.
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError as exc:
            raise CheckpointAlreadyExists(checkpoint.id) from exc

        self._metrics.increment_counter(_METRIC_CREATED, labels={})
        _log_event(
            "info",
            "sql_review_checkpoint_store.create_checkpoint",
            checkpoint_id=str(checkpoint.id),
            run_id=str(checkpoint.generation_run_id),
            status=checkpoint.status.value,
        )
        return checkpoint_from_record(record)

    async def get_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None:
        """Return a checkpoint by identifier."""
        record = await self._session.get(ReviewCheckpointRecord, checkpoint_id)
        if record is None:
            return None
        return checkpoint_from_record(record)

    # pylint: disable-next=too-many-arguments  # Port signature is fixed.
    async def list_checkpoints(
        self,
        run_id: uuid.UUID,
        *,
        status: CheckpointStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Checkpoint, ...]:
        """List a run's checkpoints, oldest-created first.

        Returns
        -------
        tuple of Checkpoint
            Matching checkpoints in ``(created_at, id)`` order.

        Raises
        ------
        RunNotFound
            If ``run_id`` does not identify a stored generation run.
        ValueError
            If ``limit`` or ``offset`` is negative.
        """
        if limit < 0 or offset < 0:
            msg = "limit and offset must be non-negative."
            raise ValueError(msg)
        if await self._session.get(GenerationRunRecord, run_id) is None:
            raise RunNotFound(run_id)
        statement = (
            sa
            .select(ReviewCheckpointRecord)
            .where(ReviewCheckpointRecord.generation_run_id == run_id)
            .order_by(ReviewCheckpointRecord.created_at, ReviewCheckpointRecord.id)
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            statement = statement.where(ReviewCheckpointRecord.status == status)
        result = await self._session.execute(statement)
        return tuple(checkpoint_from_record(record) for record in result.scalars())

    async def respond_to_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        response: CheckpointResponse,
    ) -> Checkpoint:
        """Record a reviewer response through the domain transition.

        Returns
        -------
        Checkpoint
            The resolved checkpoint the domain transition returned.
        """
        return await self._resolve(
            checkpoint_id,
            transition=lambda checkpoint: checkpoint.respond(response),
            event="respond_checkpoint",
            extra={"action": response.action.value},
        )

    async def time_out_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Record a timeout through the domain transition.

        Returns
        -------
        Checkpoint
            The resolved checkpoint the domain transition returned.
        """
        return await self._resolve(
            checkpoint_id,
            transition=lambda checkpoint: checkpoint.time_out(at),
            event="timeout_checkpoint",
        )

    async def cancel_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Record a cancellation through the domain transition.

        Returns
        -------
        Checkpoint
            The resolved checkpoint the domain transition returned.
        """
        return await self._resolve(
            checkpoint_id,
            transition=lambda checkpoint: checkpoint.cancel(at),
            event="cancel_checkpoint",
        )

    async def _resolve(
        self,
        checkpoint_id: uuid.UUID,
        *,
        transition: cabc.Callable[[Checkpoint], Checkpoint],
        event: str,
        extra: dict[str, str] | None = None,
    ) -> Checkpoint:
        """Apply one terminal transition by compare-and-set.

        The write is guarded by ``status = 'created'`` rather than by locking
        the row, so a losing writer learns it lost from `rowcount` instead of
        from lock ordering. The domain transition runs first and its result is
        what gets persisted; the adapter never reimplements the rule, and a
        rejection leaves the row untouched.

        Returns
        -------
        Checkpoint
            The resolved checkpoint, once the `UPDATE` has applied it.

        Raises
        ------
        CheckpointNotFound
            If no checkpoint holds the identifier.
        CheckpointAlreadyTerminal
            If the checkpoint was resolved by someone else first.
        """  # ruff: ignore[docstring-extraneous-exception]  # Raised by the lost-race helper this delegates to.
        fields: dict[str, str] = {} if extra is None else extra
        record = await self._session.get(ReviewCheckpointRecord, checkpoint_id)
        if record is None:
            _log_event(
                "warning",
                f"sql_review_checkpoint_store.{event}_missing",
                checkpoint_id=str(checkpoint_id),
                **fields,
            )
            raise CheckpointNotFound(checkpoint_id)

        updated = transition(checkpoint_from_record(record))
        result = await self._session.execute(
            sa
            .update(ReviewCheckpointRecord)
            .where(
                ReviewCheckpointRecord.id == checkpoint_id,
                # The predicate is the concurrency control: only a checkpoint
                # still in `created` may be resolved, so a second writer's
                # update matches no row and its outcome is observable.
                ReviewCheckpointRecord.status == CheckpointStatus.CREATED,
            )
            .values(**resolved_values(updated))
        )
        cursor_result = typ.cast("CursorResult[object]", result)
        if cursor_result.rowcount != 1:
            await self._raise_lost_race(checkpoint_id, event=event, fields=fields)
        self._metrics.increment_counter(
            _METRIC_RESOLVED,
            labels={"action": updated.status.value},
        )
        _log_event(
            "info",
            f"sql_review_checkpoint_store.{event}",
            checkpoint_id=str(checkpoint_id),
            run_id=str(updated.generation_run_id),
            status=updated.status.value,
            **fields,
        )
        await self._refresh_resolved(record, updated)
        return updated

    async def _refresh_resolved(
        self,
        record: ReviewCheckpointRecord,
        checkpoint: Checkpoint,
    ) -> None:
        """Synchronise the identity-mapped record with the row just written.

        A core ``UPDATE`` bypasses the ORM's unit of work, so the session's copy
        of the row is stale until something reconciles it. The record is
        refreshed rather than mutated so that the stored row, not the local
        entity, remains authoritative.
        """
        await self._session.refresh(record)
        self._metrics.observe_value(
            _METRIC_OPEN,
            await self._count_open(checkpoint.generation_run_id),
            labels={},
        )

    async def _count_open(self, run_id: uuid.UUID) -> float:
        """Return the number of unresolved checkpoints for one run."""
        count = await self._session.scalar(
            sa
            .select(sa.func.count())
            .select_from(ReviewCheckpointRecord)
            .where(
                ReviewCheckpointRecord.generation_run_id == run_id,
                ReviewCheckpointRecord.status == CheckpointStatus.CREATED,
            )
        )
        return float(typ.cast("int", count))

    async def _raise_lost_race(
        self,
        checkpoint_id: uuid.UUID,
        *,
        event: str,
        fields: dict[str, str],
    ) -> typ.NoReturn:
        """Distinguish a deleted checkpoint from one that changed underneath.

        The re-read is the point of the compare-and-set shape: `rowcount == 0`
        alone cannot say whether the row vanished or was already resolved.

        Raises
        ------
        CheckpointNotFound
            If the row is gone.
        CheckpointAlreadyTerminal
            If another writer resolved it first.
        """
        current = await self._session.get(ReviewCheckpointRecord, checkpoint_id)
        if current is None:
            _log_event(
                "warning",
                f"sql_review_checkpoint_store.{event}_missing",
                checkpoint_id=str(checkpoint_id),
                **fields,
            )
            raise CheckpointNotFound(checkpoint_id)
        self._metrics.increment_counter(_METRIC_TERMINAL_CONFLICT, labels={})
        _log_event(
            "warning",
            f"sql_review_checkpoint_store.{event}_already_terminal",
            checkpoint_id=str(checkpoint_id),
            run_id=str(current.generation_run_id),
            status=current.status.value,
            **fields,
        )
        raise CheckpointAlreadyTerminal(checkpoint_id)
