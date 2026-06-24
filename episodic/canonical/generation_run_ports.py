"""Port protocols for user-facing generation runs.

The repository, event-log, and checkpoint protocols define the domain-facing
contracts that adapters implement in Episodic's hexagonal architecture. Storage
or test adapters can satisfy only the sub-port they need, while
`GenerationRunPort` composes all three for callers that require the complete
generation-run surface:

```python
async def use_runs(port: GenerationRunPort) -> None:
    run = await port.get_run(run_id)
```
"""

import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from .domain import (
        Checkpoint,
        CheckpointResponse,
        GenerationEvent,
        GenerationRun,
        GenerationRunStatus,
        JsonMapping,
    )

EventSeq = typ.NewType("EventSeq", int)


def event_seq(value: int) -> EventSeq:
    """Validate and convert a positive event sequence integer."""
    if not isinstance(value, int) or value < 1:
        msg = "seq must be a positive integer."
        raise ValueError(msg)
    return EventSeq(value)


@typ.runtime_checkable
class GenerationRunRepository(typ.Protocol):
    """Repository port for generation-run aggregate roots."""

    async def create_run(
        self,
        run: GenerationRun,
        *,
        idempotency_key: str | None = None,
    ) -> GenerationRun:
        """Create a run or return the first run for an idempotency key."""
        raise NotImplementedError

    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None:
        """Return a run by identifier."""
        raise NotImplementedError

    # pylint: disable-next=too-many-arguments  # Port signature is fixed.
    async def list_runs(
        self,
        episode_id: uuid.UUID,
        *,
        status: GenerationRunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[GenerationRun, ...]:
        """List runs for an episode, ordered by creation time."""
        raise NotImplementedError

    # pylint: disable-next=too-many-arguments  # Port signature is fixed.
    async def update_run_status(  # noqa: PLR0913
        self,
        run_id: uuid.UUID,
        *,
        status: GenerationRunStatus,
        current_node: str | None,
        ended_at: dt.datetime | None,
        error_message: str | None = None,
        error_category: str | None = None,
    ) -> GenerationRun:
        """Update the run lifecycle state and return the stored run."""
        raise NotImplementedError

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
        raise NotImplementedError


@typ.runtime_checkable
class GenerationEventLog(typ.Protocol):
    """Append-only event-log port for generation runs.

    `list_events` returns records ordered ascending by `seq`. When
    `after_seq` is supplied, the result range is half-open `(after_seq, ...]`;
    otherwise it starts from sequence 1. `limit` is a hard cap.
    """

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
        raise NotImplementedError

    async def list_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
        limit: int = 100,
    ) -> tuple[GenerationEvent, ...]:
        """List events for a run."""
        raise NotImplementedError


@typ.runtime_checkable
class GenerationRunEventStore(
    GenerationRunRepository,
    GenerationEventLog,
    typ.Protocol,
):
    """Composite port for run persistence plus append-only event logging."""


@typ.runtime_checkable
class GenerationCheckpointPort(typ.Protocol):
    """Port for user-facing generation-run checkpoints."""

    async def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        """Persist a checkpoint."""
        raise NotImplementedError

    async def get_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None:
        """Return a checkpoint by identifier."""
        raise NotImplementedError

    async def respond_to_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        response: CheckpointResponse,
    ) -> Checkpoint:
        """Record a reviewer response for a checkpoint."""
        raise NotImplementedError

    async def time_out_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Record that a checkpoint timed out."""
        raise NotImplementedError

    async def cancel_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Record that a checkpoint was cancelled."""
        raise NotImplementedError


@typ.runtime_checkable
class GenerationRunPort(
    GenerationRunRepository,
    GenerationEventLog,
    GenerationCheckpointPort,
    typ.Protocol,
):
    """Composite port matching the design-document class diagram."""
