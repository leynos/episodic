"""No-op implementations for generation-run protocol contract tests."""

import typing as typ

from episodic.canonical.generation_run_errors import CheckpointNotFound, RunNotFound

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


# Protocol arity is fixed by the port contract; this is a minimal test stub.
class NoopGenerationRunPort:  # pylint: disable=too-many-arguments
    """No-op composite port implementation used for protocol type checking.

    Read operations return empty values, creation operations return their input,
    and mutation operations raise the corresponding not-found exception. The
    implementation exists only to exercise the complete composite protocol
    surface without persistence.

    Every parameter is accepted to match the port's signature and otherwise
    unused: there is no store to consult, so nothing here reads one. Each
    method states the empty or rejected outcome it produces.
    """

    async def create_run(
        self,
        run: GenerationRun,
        *,
        idempotency_key: str | None = None,
        idempotency_principal_id: str | None = None,
    ) -> GenerationRun:
        """Hand back the run unchanged, as a create would after storing it."""
        return run

    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None:
        """Report that no run exists under any identifier."""
        return None

    async def list_runs(
        self,
        episode_id: uuid.UUID,
        *,
        status: GenerationRunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[GenerationRun, ...]:
        """Return an empty run page for every episode and filter.

        Parameters
        ----------
        episode_id
            Episode whose runs would be listed; none exist here.
        status
            Optional lifecycle filter, accepted and unused.
        limit
            Page cap, accepted and unused.
        offset
            Rows to skip, accepted and unused.

        Returns
        -------
        tuple of GenerationRun
            Always empty, because this stub creates no runs.
        """
        return ()

    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        update: GenerationRunStatusUpdate,
    ) -> GenerationRun:
        """Refuse the update by raising ``RunNotFound`` for the identifier."""
        _ = update
        raise RunNotFound(run_id)

    async def claim_run_for_execution(
        self,
        run_id: uuid.UUID,
        *,
        current_node: str | None,
        started_at: dt.datetime,
        lease_expires_at: dt.datetime | None,
    ) -> GenerationRun | None:
        """Reject every execution claim because no run is stored.

        Parameters
        ----------
        run_id
            Identifier of the run to claim.
        current_node
            Worker node that would own the claim.
        started_at
            Timestamp at which execution would start.
        lease_expires_at
            Optional timestamp at which the execution lease would expire.

        Raises
        ------
        RunNotFound
            Always, because this implementation stores no runs.
        """
        raise RunNotFound(run_id)

    async def fail_expired_leases(
        self,
        *,
        now: dt.datetime,
        limit: int = 100,
    ) -> tuple[GenerationRun, ...]:
        """Reclaim no runs because this implementation stores none.

        Parameters
        ----------
        now
            Instant the expiry predicate would use, ignored here.
        limit
            Maximum batch size accepted by the port contract and ignored here.

        Returns
        -------
        tuple of GenerationRun
            Always an empty tuple because this implementation stores no runs.
        """
        return ()

    async def append_event(
        self,
        run_id: uuid.UUID,
        *,
        kind: str,
        payload: JsonMapping,
        occurred_at: dt.datetime | None = None,
    ) -> GenerationEvent:
        """Reject every event append because no run is stored.

        Parameters
        ----------
        run_id
            Identifier of the run to which the event would be appended.
        kind
            Event kind accepted by the port contract.
        payload
            Event payload accepted by the port contract.
        occurred_at
            Optional event timestamp accepted by the port contract.

        Raises
        ------
        RunNotFound
            Always, because this implementation stores no runs.
        """
        raise RunNotFound(run_id)

    async def list_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[GenerationEvent, ...]:
        """Return an empty event page for every run and cursor.

        A cursor beyond any real sequence still yields nothing rather than an
        error, because nothing was ever appended through this stub.

        Returns
        -------
        tuple of GenerationEvent
            Always empty.
        """
        return ()

    async def count_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
    ) -> int:
        """Count zero events for every run and cursor."""
        return 0

    async def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        """Hand back the checkpoint unchanged, as a stored create would."""
        return checkpoint

    async def get_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None:
        """Report that no checkpoint exists under any identifier."""
        return None

    async def list_checkpoints(
        self,
        run_id: uuid.UUID,
        *,
        status: CheckpointStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Checkpoint, ...]:
        """Return an empty checkpoint page for every run and filter.

        Filtering an empty store by status cannot change the result, so the
        filtered and unfiltered calls agree.

        Returns
        -------
        tuple of Checkpoint
            Always empty.
        """
        return ()

    async def respond_to_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        response: CheckpointResponse,
    ) -> Checkpoint:
        """Refuse the response: no checkpoint holds that identifier."""
        raise CheckpointNotFound(checkpoint_id)

    async def time_out_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Refuse the timeout: no checkpoint holds that identifier."""
        raise CheckpointNotFound(checkpoint_id)

    async def cancel_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Refuse the cancellation: no checkpoint holds that identifier."""
        raise CheckpointNotFound(checkpoint_id)
