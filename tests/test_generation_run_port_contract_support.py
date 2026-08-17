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
    """No-op implementation used for composite protocol type checking."""

    async def create_run(
        self,
        run: GenerationRun,
        *,
        idempotency_key: str | None = None,
        idempotency_principal_id: str | None = None,
    ) -> GenerationRun:
        """Return the supplied run."""
        return run

    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None:
        """Return no run."""
        return None

    async def list_runs(
        self,
        episode_id: uuid.UUID,
        *,
        status: GenerationRunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[GenerationRun, ...]:
        """Return no runs."""
        return ()

    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        update: GenerationRunStatusUpdate,
    ) -> GenerationRun:
        """Raise for all updates."""
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
        """Raise for all execution claims."""
        raise RunNotFound(run_id)

    async def append_event(
        self,
        run_id: uuid.UUID,
        *,
        kind: str,
        payload: JsonMapping,
        occurred_at: dt.datetime | None = None,
    ) -> GenerationEvent:
        """Raise for all event appends."""
        raise RunNotFound(run_id)

    async def list_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[GenerationEvent, ...]:
        """Return no events."""
        return ()

    async def count_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
    ) -> int:
        """Return no events."""
        return 0

    async def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        """Return the supplied checkpoint."""
        return checkpoint

    async def get_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None:
        """Return no checkpoint."""
        return None

    async def respond_to_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        response: CheckpointResponse,
    ) -> Checkpoint:
        """Raise for all responses."""
        raise CheckpointNotFound(checkpoint_id)

    async def time_out_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Raise for all timeouts."""
        raise CheckpointNotFound(checkpoint_id)

    async def cancel_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Raise for all cancellations."""
        raise CheckpointNotFound(checkpoint_id)
