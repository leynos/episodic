"""In-memory checkpoint helpers for generation-run adapters."""

from __future__ import annotations

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
    """Checkpoint operations shared by the in-memory generation-run store."""

    _lock: asyncio.Lock
    _runs: dict[uuid.UUID, GenerationRun]
    _checkpoints: dict[uuid.UUID, Checkpoint]

    async def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        """Persist a checkpoint."""
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
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None:
        """Return a checkpoint by identifier."""
        async with self._lock:
            return self._checkpoints.get(checkpoint_id)

    async def _apply_checkpoint_transition(
        self,
        checkpoint_id: uuid.UUID,
        transition: cabc.Callable[[Checkpoint], Checkpoint],
        spec: _CheckpointTransitionSpec,
    ) -> Checkpoint:
        """Apply a domain transition to a stored checkpoint under the lock."""
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
        """Record a reviewer response using the checkpoint domain transition."""
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
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Record a checkpoint timeout using the domain transition."""
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
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Record checkpoint cancellation using the domain transition."""
        return await self._apply_checkpoint_transition(
            checkpoint_id,
            lambda cp: cp.cancel(at),
            _CheckpointTransitionSpec(
                missing_event="generation_run_store.cancel_checkpoint_missing",
                done_event="generation_run_store.cancel_checkpoint",
            ),
        )
