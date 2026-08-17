"""No-op implementations for generation-run protocol contract tests."""

import typing as typ

from episodic.canonical.generation_run_errors import CheckpointNotFound, RunNotFound

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from episodic.canonical.domain import (
        Checkpoint,
        CheckpointResponse,
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
    """

    async def create_run(
        self,
        run: GenerationRun,
        *,
        idempotency_key: str | None = None,
        idempotency_principal_id: str | None = None,
    ) -> GenerationRun:
        """Return the supplied run without persisting it.

        Parameters
        ----------
        run
            Generation run to return.
        idempotency_key
            Idempotency key accepted by the port contract and ignored here.
        idempotency_principal_id
            Principal identifier accepted by the port contract and ignored here.

        Returns
        -------
        GenerationRun
            The supplied generation run.
        """
        return run

    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None:
        """Return no run for the supplied identifier.

        Parameters
        ----------
        run_id
            Run identifier, which is ignored by this no-op implementation.

        Returns
        -------
        GenerationRun or None
            Always ``None`` because this implementation stores no runs.
        """
        return None

    async def list_runs(
        self,
        episode_id: uuid.UUID,
        *,
        status: GenerationRunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[GenerationRun, ...]:
        """Return no runs for the supplied episode.

        Parameters
        ----------
        episode_id
            Episode identifier, which is ignored by this no-op implementation.
        status
            Optional lifecycle filter accepted by the port contract and ignored
            here.
        limit
            Maximum number of runs accepted by the port contract and ignored
            here.
        offset
            Number of runs to skip accepted by the port contract and ignored
            here.

        Returns
        -------
        tuple of GenerationRun
            Always an empty tuple because this implementation stores no runs.
        """
        return ()

    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        update: GenerationRunStatusUpdate,
    ) -> GenerationRun:
        """Reject every lifecycle update because no run is stored.

        Parameters
        ----------
        run_id
            Identifier of the run to update.
        update
            Lifecycle update to apply.

        Raises
        ------
        RunNotFound
            Always, because this implementation stores no runs.
        """
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
        """Return no events for the supplied run.

        Parameters
        ----------
        run_id
            Run identifier, which is ignored by this no-op implementation.
        after_seq
            Optional event-sequence cursor accepted by the port contract and
            ignored here.
        limit
            Maximum number of events accepted by the port contract and ignored
            here.
        offset
            Number of events to skip accepted by the port contract and ignored
            here.

        Returns
        -------
        tuple of GenerationEvent
            Always an empty tuple because this implementation stores no events.
        """
        return ()

    async def count_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
    ) -> int:
        """Return zero for the supplied run's event count.

        Parameters
        ----------
        run_id
            Run identifier, which is ignored by this no-op implementation.
        after_seq
            Optional event-sequence cursor accepted by the port contract and
            ignored here.

        Returns
        -------
        int
            Always zero because this implementation stores no events.
        """
        return 0

    async def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        """Return the supplied checkpoint without persisting it.

        Parameters
        ----------
        checkpoint
            Checkpoint to return.

        Returns
        -------
        Checkpoint
            The supplied checkpoint.
        """
        return checkpoint

    async def get_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None:
        """Return no checkpoint for the supplied identifier.

        Parameters
        ----------
        checkpoint_id
            Checkpoint identifier, which is ignored by this no-op
            implementation.

        Returns
        -------
        Checkpoint or None
            Always ``None`` because this implementation stores no checkpoints.
        """
        return None

    async def respond_to_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        response: CheckpointResponse,
    ) -> Checkpoint:
        """Reject every checkpoint response because none is stored.

        Parameters
        ----------
        checkpoint_id
            Identifier of the checkpoint to respond to.
        response
            Reviewer response to record.

        Raises
        ------
        CheckpointNotFound
            Always, because this implementation stores no checkpoints.
        """
        raise CheckpointNotFound(checkpoint_id)

    async def time_out_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Reject every checkpoint timeout because none is stored.

        Parameters
        ----------
        checkpoint_id
            Identifier of the checkpoint to time out.
        at
            Timestamp at which the timeout would be recorded.

        Raises
        ------
        CheckpointNotFound
            Always, because this implementation stores no checkpoints.
        """
        raise CheckpointNotFound(checkpoint_id)

    async def cancel_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Reject every checkpoint cancellation because none is stored.

        Parameters
        ----------
        checkpoint_id
            Identifier of the checkpoint to cancel.
        at
            Timestamp at which the cancellation would be recorded.

        Raises
        ------
        CheckpointNotFound
            Always, because this implementation stores no checkpoints.
        """
        raise CheckpointNotFound(checkpoint_id)
