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

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from .domain import (
        Checkpoint,
        CheckpointResponse,
        CheckpointStatus,
        GenerationEvent,
        GenerationRun,
        GenerationRunStatus,
        JsonMapping,
    )

EventSeq = typ.NewType("EventSeq", int)


@dc.dataclass(frozen=True, slots=True)
class GenerationRunStatusUpdate:
    """Lifecycle fields to apply to a generation run.

    Attributes
    ----------
    status : GenerationRunStatus
        New durable lifecycle status.
    current_node : str | None
        Current launcher node, or ``None`` for a terminal run.
    ended_at : dt.datetime | None
        Terminal timestamp, when the lifecycle transition ends a run.
    error_message : str | None
        Failure detail. An omitted value clears the persisted field.
    error_category : str | None
        Stable failure classification. An omitted value clears the persisted
        field.
    """

    status: GenerationRunStatus
    current_node: str | None
    ended_at: dt.datetime | None
    error_message: str | None = None
    error_category: str | None = None


def event_seq(value: int) -> EventSeq:
    """Validate and convert a positive event sequence integer."""
    if not isinstance(value, int) or value < 1:
        msg = "seq must be a positive integer."
        raise ValueError(msg)
    return EventSeq(value)


def event_page_minimum_sequence(
    *,
    after_seq: EventSeq | None,
    limit: int,
    offset: int,
) -> int:
    """Validate event-page arguments and return the exclusive sequence bound.

    Parameters
    ----------
    after_seq : EventSeq | None
        Optional exclusive cursor for the event sequence.
    limit : int
        Maximum number of events requested.
    offset : int
        Number of events to skip after cursor selection.

    Returns
    -------
    int
        The exclusive event-sequence bound, or zero without a cursor.

    Raises
    ------
    ValueError
        If pagination bounds are negative or a cursor is combined with an
        offset.
    """
    if limit < 0 or offset < 0:
        msg = "limit and offset must be non-negative."
        raise ValueError(msg)
    if after_seq is not None and offset != 0:
        msg = "after_seq and offset cannot be combined."
        raise ValueError(msg)
    return int(after_seq) if after_seq is not None else 0


@typ.runtime_checkable
class GenerationRunRepository(typ.Protocol):
    """Repository port for generation-run aggregate roots."""

    async def create_run(
        self,
        run: GenerationRun,
        *,
        idempotency_key: str | None = None,
        idempotency_principal_id: str | None = None,
    ) -> GenerationRun:
        """Create a run or return the first run for a principal-scoped key."""
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

    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        update: GenerationRunStatusUpdate,
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
    otherwise it starts from sequence 1. `offset` skips records within the
    range selected by `after_seq`, and `limit` is a hard cap. Callers must use
    either `after_seq` or `offset`, not both.

    Sequences are allocated per run and are **gapless**: after `N` successful
    appends the persisted sequence numbers are exactly `{1, ..., N}`, and
    `list_events` never returns a previously-unseen sequence at or below one it
    has already returned. That guarantee assumes a **single writer per run**;
    it holds under concurrent writers only because allocation takes a row lock
    on the parent run, so allocation order equals commit order.
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
        """Append an event and return it with the allocated sequence.

        Raises
        ------
        RunNotFound
            If `run_id` does not identify a stored generation run.
        RunAlreadyTerminal
            If the run has already reached a terminal status. A run's event
            stream is closed when the run ends.
        """
        raise NotImplementedError

    async def list_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[GenerationEvent, ...]:
        """List events for a run.

        Raises
        ------
        ValueError
            If ``after_seq`` is supplied with a non-zero ``offset``. These
            pagination mechanisms are mutually exclusive.
        RunNotFound
            If `run_id` does not identify a stored generation run.
        """
        raise NotImplementedError

    async def count_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
    ) -> int:
        """Count events for a run after an optional sequence cursor.

        Raises
        ------
        RunNotFound
            If ``run_id`` does not identify a stored generation run.
        """
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
    """Port for user-facing generation-run checkpoints.

    Notes
    -----
    The contract below is the part two independent implementers could not
    otherwise agree on, and is what the shared scenarios in
    ``tests/generation_run_contract_scenarios.py`` enforce.

    Creation preconditions are *existence*, not lifecycle: `create_checkpoint`
    requires the parent run to exist and raises `RunNotFound` when it does not,
    but it does **not** consult the run's status. An implementer that reused a
    run-level "must be mutable" guard would reject checkpoints on a running run
    and diverge from every other implementation.

    A duplicate identifier raises `CheckpointAlreadyExists` rather than
    overwriting. A checkpoint arriving with a status other than `created`
    raises `CheckpointAlreadyTerminal`. Together these make creation
    non-destructive under a replayed request.

    Adapters may impose length limits on `node`, `prompt`, `responded_by`, and
    the option strings; the port states no bound, so callers must not assume
    one. Option *order* is part of the value and survives a round trip.
    """

    async def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        """Persist a checkpoint.

        Returns
        -------
        Checkpoint
            The stored checkpoint. Implementations return a re-read of what was
            persisted, not the input object, so a caller observes any adapter
            normalisation at once.

        Raises
        ------
        RunNotFound
            If the parent generation run does not exist. The run's status is
            deliberately not a precondition.
        CheckpointAlreadyExists
            If the identifier is already in use.
        CheckpointAlreadyTerminal
            If `checkpoint.status` is not `created`.
        """
        raise NotImplementedError

    async def get_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None:
        """Return a checkpoint by identifier, or `None` when absent."""
        raise NotImplementedError

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

        Raises
        ------
        RunNotFound
            If `run_id` does not identify a stored generation run.
        ValueError
            If `limit` or `offset` is negative.
        """
        raise NotImplementedError

    async def respond_to_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        response: CheckpointResponse,
    ) -> Checkpoint:
        """Record a reviewer response for a checkpoint.

        Raises
        ------
        CheckpointNotFound
            If no checkpoint holds the identifier.
        CheckpointAlreadyTerminal
            If the checkpoint is already `responded`, `timed_out`, or
            `cancelled`. The stored row is left unchanged.
        """
        raise NotImplementedError

    async def time_out_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Record that a checkpoint timed out.

        Raises
        ------
        CheckpointNotFound
            If no checkpoint holds the identifier.
        CheckpointAlreadyTerminal
            If the checkpoint is already resolved.
        """
        raise NotImplementedError

    async def cancel_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Record that a checkpoint was cancelled.

        Raises
        ------
        CheckpointNotFound
            If no checkpoint holds the identifier.
        CheckpointAlreadyTerminal
            If the checkpoint is already resolved.
        """
        raise NotImplementedError


@typ.runtime_checkable
class GenerationRunPort(
    GenerationRunRepository,
    GenerationEventLog,
    GenerationCheckpointPort,
    typ.Protocol,
):
    """Composite port matching the design-document class diagram."""
