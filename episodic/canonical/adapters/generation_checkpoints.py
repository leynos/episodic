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
    CheckpointAlreadyExists,
    CheckpointAlreadyTerminal,
    CheckpointNotFound,
    RunNotFound,
)
from episodic.logging import log_event as _log_event

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc
    import datetime as dt
    import uuid

    from episodic.canonical.domain import (
        Checkpoint,
        CheckpointResponse,
        CheckpointStatus,
        GenerationRun,
    )


_EVENT_PREFIX = "generation_run_store."


@dc.dataclass(frozen=True, slots=True)
class _CheckpointTransitionSpec:
    """Logging specification for a checkpoint domain transition.

    The event names are derived from one stem so the ``_missing`` suffix that
    distinguishes a rejected lookup from a completed transition is applied in
    one place rather than re-spelled at each call site.
    """

    stem: str
    extra_fields: dict[str, str] = dc.field(default_factory=dict)

    @property
    def missing_event(self) -> str:
        """Event name logged when no stored checkpoint holds the identifier."""
        return f"{_EVENT_PREFIX}{self.stem}_missing"

    @property
    def done_event(self) -> str:
        """Event name logged when the transition has been applied."""
        return f"{_EVENT_PREFIX}{self.stem}"


class InMemoryGenerationCheckpointMixin:
    """Checkpoint operations shared by the in-memory generation-run store.

    The mixin centralises checkpoint persistence and state transitions so the
    in-memory adapter can reuse the same domain rules as the rest of the
    generation-run implementation.

    Transitions run under the store's lock and a rejected one leaves the
    stored checkpoint untouched. Each transition method reports the same
    two failures: `CheckpointNotFound` when no stored checkpoint holds the
    identifier, and `CheckpointAlreadyTerminal` on one already resolved.

    Examples
    --------
    >>> class Store(InMemoryGenerationCheckpointMixin):
    ...     pass
    >>> isinstance(Store(), InMemoryGenerationCheckpointMixin)
    True
    """

    _lock: asyncio.Lock
    _runs: dict[uuid.UUID, GenerationRun]
    _checkpoints: dict[uuid.UUID, Checkpoint]

    async def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
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
        CheckpointAlreadyExists
            Raised when the identifier is already in use. Without this the
            store silently overwrites, which would reset a resolved checkpoint
            to ``created`` on a replayed create.
        CheckpointAlreadyTerminal
            Raised when the checkpoint arrives already resolved.

        Examples
        --------
        >>> # await store.create_checkpoint(checkpoint)
        >>> # returned_checkpoint is checkpoint
        True
        """
        async with self._lock:
            if checkpoint.status.is_terminal():
                _log_event(
                    "warning",
                    "generation_run_store.create_checkpoint_terminal",
                    checkpoint_id=str(checkpoint.id),
                    run_id=str(checkpoint.generation_run_id),
                    status=checkpoint.status.value,
                )
                raise CheckpointAlreadyTerminal(checkpoint.id)
            if checkpoint.generation_run_id not in self._runs:
                _log_event(
                    "warning",
                    "generation_run_store.create_checkpoint_missing_run",
                    checkpoint_id=str(checkpoint.id),
                    run_id=str(checkpoint.generation_run_id),
                )
                raise RunNotFound(checkpoint.generation_run_id)
            if checkpoint.id in self._checkpoints:
                _log_event(
                    "warning",
                    "generation_run_store.create_checkpoint_duplicate",
                    checkpoint_id=str(checkpoint.id),
                    run_id=str(checkpoint.generation_run_id),
                )
                raise CheckpointAlreadyExists(checkpoint.id)
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
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None:
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

    async def list_checkpoints(
        self,
        run_id: uuid.UUID,
        *,
        status: CheckpointStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Checkpoint, ...]:
        """List a run's checkpoints, oldest-created first.

        Parameters
        ----------
        run_id : uuid.UUID
            Identifier of the generation run whose checkpoints to list.
        status : CheckpointStatus | None, optional
            Restrict the result to one lifecycle status.
        limit : int, optional
            Maximum number of checkpoints to return.
        offset : int, optional
            Number of checkpoints to skip after ordering.

        Returns
        -------
        tuple[Checkpoint, ...]
            Matching checkpoints in ``(created_at, id)`` order.

        Raises
        ------
        RunNotFound
            Raised when the run is not present in the store.
        ValueError
            Raised when ``limit`` or ``offset`` is negative.

        Examples
        --------
        >>> # await store.list_checkpoints(run_id, status=CheckpointStatus.CREATED)
        >>> # returns the run's unresolved checkpoints
        True
        """
        if limit < 0 or offset < 0:
            msg = "limit and offset must be non-negative."
            raise ValueError(msg)
        async with self._lock:
            if run_id not in self._runs:
                raise RunNotFound(run_id)
            found = self._matching_checkpoints(run_id, status=status)
        return tuple(found[offset : offset + limit])

    def _matching_checkpoints(
        self,
        run_id: uuid.UUID,
        *,
        status: CheckpointStatus | None,
    ) -> list[Checkpoint]:
        """Return a run's checkpoints, ordered; callers hold the lock."""
        return sorted(
            (
                checkpoint
                for checkpoint in self._checkpoints.values()
                if checkpoint.generation_run_id == run_id
                and (status is None or checkpoint.status is status)
            ),
            key=lambda checkpoint: (checkpoint.created_at, str(checkpoint.id)),
        )

    async def _apply_checkpoint_transition(
        self,
        checkpoint_id: uuid.UUID,
        transition: cabc.Callable[[Checkpoint], Checkpoint],
        spec: _CheckpointTransitionSpec,
    ) -> Checkpoint:
        """Apply a domain transition under the lock, then store what it returns."""
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
        checkpoint_id: uuid.UUID,
        *,
        response: CheckpointResponse,
    ) -> Checkpoint:
        """Record a reviewer response against a stored checkpoint.

        Parameters
        ----------
        checkpoint_id : uuid.UUID
            Identifier of the checkpoint the reviewer answered.
        response : CheckpointResponse
            The reviewer's action, payload, and instant, applied through the
            domain's ``respond`` rule rather than interpreted here.

        Returns
        -------
        Checkpoint
            The checkpoint the rule resolved, carrying the reviewer's payload.

        Examples
        --------
        >>> # await store.respond_to_checkpoint(checkpoint_id, response=response)
        >>> # returns the checkpoint carrying the reviewer's payload
        True
        """
        return await self._apply_checkpoint_transition(
            checkpoint_id,
            lambda cp: cp.respond(response),
            _CheckpointTransitionSpec(
                stem="respond_checkpoint",
                extra_fields={"action": response.action.value},
            ),
        )

    async def time_out_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Record that a review window closed with nobody answering.

        Parameters
        ----------
        checkpoint_id : uuid.UUID
            Identifier of the checkpoint whose window closed.
        at : datetime.datetime
            The instant the window closed, supplied by the caller, not read
            from the store's clock.

        Returns
        -------
        Checkpoint
            The checkpoint the rule expired at the supplied instant.

        Examples
        --------
        >>> # await store.time_out_checkpoint(checkpoint_id, at=moment)
        >>> # returns the checkpoint expired at the caller's instant
        True
        """
        return await self._apply_checkpoint_transition(
            checkpoint_id,
            lambda cp: cp.time_out(at),
            _CheckpointTransitionSpec(stem="timeout_checkpoint"),
        )

    async def cancel_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Record an operator withdrawing a checkpoint.

        Withdrawal is deliberate rather than time-driven, so the instant is
        recorded but gates nothing: the ``cancel`` rule alone decides.

        Parameters
        ----------
        checkpoint_id : uuid.UUID
            Identifier of the checkpoint being withdrawn.
        at : datetime.datetime
            When the operator withdrew it, recorded as the resolution time.

        Returns
        -------
        Checkpoint
            The checkpoint the ``cancel`` rule withdrew.

        Examples
        --------
        >>> # await store.cancel_checkpoint(checkpoint_id, at=moment)
        >>> # returns the checkpoint withdrawn by the operator's act
        True
        """
        return await self._apply_checkpoint_transition(
            checkpoint_id,
            lambda cp: cp.cancel(at),
            _CheckpointTransitionSpec(stem="cancel_checkpoint"),
        )
