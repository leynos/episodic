"""In-memory checkpoint helpers for generation-run adapters.

These helpers keep checkpoint state inside the adapter store while preserving
the domain transitions and log events expected by the generation-run layer.

Examples
--------
Subclass the mixin on the in-memory generation-run store.
Outcome: checkpoint creation, lookup, and transitions reuse the same lock and
domain logging as the rest of the adapter.
"""

import dataclasses as dc
import typing as typ

from episodic.canonical.generation_run_errors import (
    CheckpointAlreadyTerminal,
    CheckpointNotFound,
    RunNotFound,
)
from episodic.orchestration._types import _log_event

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc
    import datetime as dt
    import uuid

    from episodic.canonical.domain import (
        Checkpoint,
        CheckpointResponse,
        GenerationRun,
    )


@dc.dataclass(frozen=True, slots=True)
class _CheckpointTransitionSpec:
    """Logging specification for a checkpoint domain transition."""

    missing_event: str
    done_event: str
    extra_fields: dict[str, str] = dc.field(default_factory=dict)


class InMemoryGenerationCheckpointMixin:
    """Checkpoint operations shared by the in-memory generation-run store.

    The mixin centralises checkpoint persistence and state transitions so the
    in-memory adapter can reuse the same domain rules as the rest of the
    generation-run implementation.

    Examples
    --------
    >>> class Store(InMemoryGenerationCheckpointMixin):
    ...     pass
    >>> isinstance(Store(), InMemoryGenerationCheckpointMixin)
    True
    """

    _lock: "asyncio.Lock"
    _runs: "dict[uuid.UUID, GenerationRun]"
    _checkpoints: "dict[uuid.UUID, Checkpoint]"

    async def create_checkpoint(self, checkpoint: "Checkpoint") -> "Checkpoint":
        """Persist a checkpoint in the in-memory store.

        Parameters
        ----------
        checkpoint : Checkpoint
            Checkpoint to store after validating that its generation run
            exists.

        Returns
        -------
        Checkpoint
            The checkpoint that was stored.

        Raises
        ------
        RunNotFound
            Raised when the checkpoint references an unknown generation run.

        Examples
        --------
        >>> # await store.create_checkpoint(checkpoint)
        >>> # returned_checkpoint is checkpoint
        True
        """
        async with self._lock:
            if checkpoint.generation_run_id not in self._runs:
                _log_event(
                    "warning",
                    "generation_run_store.create_checkpoint_missing_run",
                    checkpoint_id=str(checkpoint.id),
                    run_id=str(checkpoint.generation_run_id),
                )
                raise RunNotFound(checkpoint.generation_run_id)
            self._checkpoints[checkpoint.id] = checkpoint
            _log_event(
                "info",
                "generation_run_store.create_checkpoint",
                checkpoint_id=str(checkpoint.id),
                run_id=str(checkpoint.generation_run_id),
                status=checkpoint.status.value,
            )
            return checkpoint

    async def get_checkpoint(
        self,
        checkpoint_id: "uuid.UUID",
    ) -> "Checkpoint | None":
        """Return a checkpoint by identifier.

        Parameters
        ----------
        checkpoint_id : uuid.UUID
            Identifier of the checkpoint to fetch.

        Returns
        -------
        Checkpoint | None
            The stored checkpoint when present, otherwise `None`.

        Examples
        --------
        >>> # await store.get_checkpoint(checkpoint_id)
        >>> # returns the checkpoint when it exists, else None
        True
        """
        async with self._lock:
            return self._checkpoints.get(checkpoint_id)

    async def _apply_checkpoint_transition(
        self,
        checkpoint_id: "uuid.UUID",
        transition: "cabc.Callable[[Checkpoint], Checkpoint]",
        spec: "_CheckpointTransitionSpec",
    ) -> "Checkpoint":
        """Apply a domain transition to a stored checkpoint under the lock.

        Parameters
        ----------
        checkpoint_id : uuid.UUID
            Identifier of the checkpoint to transition.
        transition : collections.abc.Callable[[Checkpoint], Checkpoint]
            Domain transition to apply to the stored checkpoint.
        spec : _CheckpointTransitionSpec
            Logging labels associated with the transition.

        Returns
        -------
        Checkpoint
            The updated checkpoint after the domain transition.

        Raises
        ------
        CheckpointNotFound
            Raised when the checkpoint is not present in the store.
        CheckpointAlreadyTerminal
            Raised when the domain transition rejects a terminal checkpoint.

        Examples
        --------
        >>> # await store._apply_checkpoint_transition(checkpoint_id, transition, spec)
        >>> # returns the updated checkpoint when the transition succeeds
        True
        """
        async with self._lock:
            checkpoint = self._checkpoints.get(checkpoint_id)
            if checkpoint is None:
                _log_event(
                    "warning",
                    spec.missing_event,
                    checkpoint_id=str(checkpoint_id),
                    **spec.extra_fields,
                )
                raise CheckpointNotFound(checkpoint_id)
            try:
                updated = transition(checkpoint)
            except CheckpointAlreadyTerminal:
                _log_event(
                    "warning",
                    f"{spec.done_event}_already_terminal",
                    checkpoint_id=str(checkpoint_id),
                    run_id=str(checkpoint.generation_run_id),
                    status=checkpoint.status.value,
                    **spec.extra_fields,
                )
                raise
            self._checkpoints[checkpoint_id] = updated
            _log_event(
                "info",
                spec.done_event,
                checkpoint_id=str(checkpoint_id),
                run_id=str(updated.generation_run_id),
                status=updated.status.value,
                **spec.extra_fields,
            )
            return updated

    async def respond_to_checkpoint(
        self,
        checkpoint_id: "uuid.UUID",
        *,
        response: "CheckpointResponse",
    ) -> "Checkpoint":
        """Record a reviewer response using the checkpoint domain transition.

        Parameters
        ----------
        checkpoint_id : uuid.UUID
            Identifier of the checkpoint to respond to.
        response : CheckpointResponse
            Reviewer response to persist against the checkpoint.

        Returns
        -------
        Checkpoint
            The updated checkpoint with the reviewer response applied.

        Raises
        ------
        CheckpointNotFound
            Raised when the checkpoint cannot be found.
        CheckpointAlreadyTerminal
            Raised when the checkpoint has already reached a terminal state.

        Examples
        --------
        >>> # await store.respond_to_checkpoint(checkpoint_id, response=response)
        >>> # returns the checkpoint after applying the response
        True
        """
        return await self._apply_checkpoint_transition(
            checkpoint_id,
            lambda cp: cp.respond(response),
            _CheckpointTransitionSpec(
                missing_event="generation_run_store.respond_checkpoint_missing",
                done_event="generation_run_store.respond_checkpoint",
                extra_fields={"action": response.action.value},
            ),
        )

    async def time_out_checkpoint(
        self,
        checkpoint_id: "uuid.UUID",
        *,
        at: "dt.datetime",
    ) -> "Checkpoint":
        """Record a checkpoint timeout using the domain transition.

        Parameters
        ----------
        checkpoint_id : uuid.UUID
            Identifier of the checkpoint to time out.
        at : datetime.datetime
            Timestamp at which the timeout is recorded.

        Returns
        -------
        Checkpoint
            The updated checkpoint after timing out.

        Raises
        ------
        CheckpointNotFound
            Raised when the checkpoint cannot be found.
        CheckpointAlreadyTerminal
            Raised when the checkpoint has already reached a terminal state.

        Examples
        --------
        >>> # await store.time_out_checkpoint(checkpoint_id, at=moment)
        >>> # returns the checkpoint after applying the timeout
        True
        """
        return await self._apply_checkpoint_transition(
            checkpoint_id,
            lambda cp: cp.time_out(at),
            _CheckpointTransitionSpec(
                missing_event="generation_run_store.timeout_checkpoint_missing",
                done_event="generation_run_store.timeout_checkpoint",
            ),
        )

    async def cancel_checkpoint(
        self,
        checkpoint_id: "uuid.UUID",
        *,
        at: "dt.datetime",
    ) -> "Checkpoint":
        """Record checkpoint cancellation using the domain transition.

        Parameters
        ----------
        checkpoint_id : uuid.UUID
            Identifier of the checkpoint to cancel.
        at : datetime.datetime
            Timestamp at which the cancellation is recorded.

        Returns
        -------
        Checkpoint
            The updated checkpoint after cancellation.

        Raises
        ------
        CheckpointNotFound
            Raised when the checkpoint cannot be found.
        CheckpointAlreadyTerminal
            Raised when the checkpoint has already reached a terminal state.

        Examples
        --------
        >>> # await store.cancel_checkpoint(checkpoint_id, at=moment)
        >>> # returns the checkpoint after applying the cancellation
        True
        """
        return await self._apply_checkpoint_transition(
            checkpoint_id,
            lambda cp: cp.cancel(at),
            _CheckpointTransitionSpec(
                missing_event="generation_run_store.cancel_checkpoint_missing",
                done_event="generation_run_store.cancel_checkpoint",
            ),
        )
