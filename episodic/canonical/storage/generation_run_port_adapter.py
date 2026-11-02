"""Composite adapter exposing one generation-run port over two stores.

The run/event store and the review-checkpoint store were written separately
because they own different tables and different lifecycles. Callers want one
object: the design document's class diagram has a single composite
``GenerationRunPort``, and ``CanonicalUnitOfWork`` exposes one attribute for it.

Delegation is explicit rather than inherited. A mixin would put both stores'
private helpers on one namespace, and the checkpoint store's compare-and-set
transitions have nothing to reuse from the run store's row locking.
"""

import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from episodic.canonical.domain import (
        Checkpoint,
        CheckpointResponse,
        CheckpointStatus,
        GenerationEvent,
        GenerationRun,
        GenerationRunStatus,
        JsonMapping,
    )
    from episodic.canonical.generation_run_ports import (
        EventSeq,
        GenerationRunStatusUpdate,
    )

    from .generation_runs import SqlAlchemyGenerationRunStore
    from .review_checkpoints import SqlAlchemyReviewCheckpointStore


class SqlAlchemyGenerationRunPortAdapter:
    """Compose the run/event and review-checkpoint stores into one port."""

    def __init__(
        self,
        runs: SqlAlchemyGenerationRunStore,
        checkpoints: SqlAlchemyReviewCheckpointStore,
    ) -> None:
        self._runs = runs
        self._checkpoints = checkpoints

    async def create_run(
        self,
        run: GenerationRun,
        *,
        idempotency_key: str | None = None,
        idempotency_principal_id: str | None = None,
    ) -> GenerationRun:
        """Create a run or return the first run for a principal-scoped key."""
        return await self._runs.create_run(
            run,
            idempotency_key=idempotency_key,
            idempotency_principal_id=idempotency_principal_id,
        )

    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None:
        """Return a run by identifier."""
        return await self._runs.get_run(run_id)

    # pylint: disable-next=too-many-arguments  # Port signature is fixed.
    async def list_runs(
        self,
        episode_id: uuid.UUID,
        *,
        status: GenerationRunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[GenerationRun, ...]:
        """List an episode's runs, oldest-created first.

        Parameters
        ----------
        episode_id : uuid.UUID
            Episode that owns the runs.
        status : GenerationRunStatus | None, optional
            When given, only runs in this lifecycle state are returned.
        limit : int, optional
            Maximum number of runs to return. Defaults to 50, matching the
            run store's narrower default.
        offset : int, optional
            Runs to skip after ordering.

        Returns
        -------
        tuple of GenerationRun
            Ordered by ``(created_at, id)``.
        """
        return await self._runs.list_runs(
            episode_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        update: GenerationRunStatusUpdate,
    ) -> GenerationRun:
        """Update the run lifecycle state and return the stored run."""
        return await self._runs.update_run_status(run_id, update=update)

    # pylint: disable-next=too-many-arguments  # Port signature is fixed.
    async def claim_run_for_execution(
        self,
        run_id: uuid.UUID,
        *,
        current_node: str | None,
        started_at: dt.datetime,
        lease_expires_at: dt.datetime | None,
    ) -> GenerationRun | None:
        """Atomically move a pending run to running, or return None if lost."""
        return await self._runs.claim_run_for_execution(
            run_id,
            current_node=current_node,
            started_at=started_at,
            lease_expires_at=lease_expires_at,
        )

    # pylint: disable-next=too-many-arguments  # Port signature is fixed.
    async def append_event(
        self,
        run_id: uuid.UUID,
        *,
        kind: str,
        payload: JsonMapping,
        occurred_at: dt.datetime | None = None,
    ) -> GenerationEvent:
        """Append an event and return it with the allocated sequence."""
        return await self._runs.append_event(
            run_id,
            kind=kind,
            payload=payload,
            occurred_at=occurred_at,
        )

    async def list_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[GenerationEvent, ...]:
        """Return the run's recorded events from ``after_seq`` onwards.

        The adapter forwards both selectors as given; the run store rejects a
        request supplying both, because a sequence cursor and an offset name the
        same window two ways and combining them is ambiguous.

        Returns
        -------
        tuple of GenerationEvent
            Ordered by ascending ``seq``, the run store's own order.
        """
        return await self._runs.list_events(
            run_id,
            after_seq=after_seq,
            limit=limit,
            offset=offset,
        )

    async def count_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
    ) -> int:
        """Count events for a run after an optional sequence cursor."""
        return await self._runs.count_events(run_id, after_seq=after_seq)

    async def fail_expired_leases(
        self,
        *,
        now: dt.datetime,
        limit: int = 100,
    ) -> tuple[GenerationRun, ...]:
        """Fail runs whose execution lease expired at or before ``now``."""
        return await self._runs.fail_expired_leases(now=now, limit=limit)

    async def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        """Persist a checkpoint."""
        return await self._checkpoints.create_checkpoint(checkpoint)

    async def get_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None:
        """Return a checkpoint by identifier."""
        return await self._checkpoints.get_checkpoint(checkpoint_id)

    # pylint: disable-next=too-many-arguments  # Port signature is fixed.
    async def list_checkpoints(
        self,
        run_id: uuid.UUID,
        *,
        status: CheckpointStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Checkpoint, ...]:
        """List a run's review checkpoints, oldest-created first.

        Checkpoints live in their own table, so this forwards to the
        checkpoint store rather than to the run store the other listings use.

        Returns
        -------
        tuple of Checkpoint
            Ordered by ``(created_at, id)``.
        """
        return await self._checkpoints.list_checkpoints(
            run_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def respond_to_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        response: CheckpointResponse,
    ) -> Checkpoint:
        """Record a reviewer response for a checkpoint."""
        return await self._checkpoints.respond_to_checkpoint(
            checkpoint_id,
            response=response,
        )

    async def time_out_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Record that a checkpoint timed out."""
        return await self._checkpoints.time_out_checkpoint(checkpoint_id, at=at)

    async def cancel_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Record that a checkpoint was cancelled."""
        return await self._checkpoints.cancel_checkpoint(checkpoint_id, at=at)
