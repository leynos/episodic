"""In-memory generation-run port adapter.

This module provides a reference implementation of the generation-run port
protocols for tests and local development. It is ephemeral, single-process
storage and is not a production persistence layer.

`InMemoryGenerationRunStore` protects all mutable dictionaries with one
`asyncio.Lock`, so callers get simple consistency guarantees at the cost of
coarse-grained concurrency. Typical use:

```python
store = InMemoryGenerationRunStore()
run = await store.create_run(generation_run)
event = await store.append_event(run.id, kind="created", payload={})
```
"""

import asyncio
import collections.abc as cabc
import dataclasses as dc
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
from episodic.canonical.generation_run_errors import (
    CheckpointNotFound,
    RunAlreadyTerminal,
    RunNotFound,
)
from episodic.canonical.generation_run_ports import EventSeq, event_seq

TimeProvider = cabc.Callable[[], dt.datetime]


def _now_utc() -> dt.datetime:
    """Return the current UTC time for in-memory records."""
    return dt.datetime.now(dt.UTC)


def _default_time_provider() -> TimeProvider:
    """Return the default in-memory timestamp provider."""
    return _now_utc


@dc.dataclass(slots=True)
class InMemoryGenerationRunStore:
    """In-memory reference adapter for the composite generation-run port."""

    time_provider: TimeProvider = dc.field(default_factory=_default_time_provider)
    _runs: dict[uuid.UUID, GenerationRun] = dc.field(default_factory=dict)
    _events: dict[uuid.UUID, list[GenerationEvent]] = dc.field(default_factory=dict)
    _checkpoints: dict[uuid.UUID, Checkpoint] = dc.field(default_factory=dict)
    _idempotency_keys: dict[str, uuid.UUID] = dc.field(default_factory=dict)
    _lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)

    async def create_run(
        self,
        run: GenerationRun,
        *,
        idempotency_key: str | None = None,
    ) -> GenerationRun:
        """Create a run, preserving first-write-wins idempotency.

        When ``idempotency_key`` already exists, the originally stored run is
        returned and the supplied ``run`` is ignored. Retried requests therefore
        cannot overwrite the first write.
        """
        async with self._lock:
            if idempotency_key is not None:
                existing_id = self._idempotency_keys.get(idempotency_key)
                if existing_id is not None:
                    return self._runs[existing_id]
            self._runs[run.id] = run
            self._events.setdefault(run.id, [])
            if idempotency_key is not None:
                self._idempotency_keys[idempotency_key] = run.id
            return run

    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None:
        """Return a run by identifier."""
        async with self._lock:
            return self._runs.get(run_id)

    # pylint: disable-next=too-many-arguments  # Port signature is fixed.
    async def list_runs(
        self,
        episode_id: uuid.UUID,
        *,
        status: GenerationRunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[GenerationRun, ...]:
        """List runs for one episode in creation order."""
        if limit < 0 or offset < 0:
            msg = "limit and offset must be non-negative."
            raise ValueError(msg)
        async with self._lock:
            runs = [
                run
                for run in self._runs.values()
                if run.episode_id == episode_id
                and (status is None or run.status == status)
            ]
            runs.sort(key=lambda run: (run.created_at, run.id))
        return tuple(runs[offset : offset + limit])

    # pylint: disable-next=too-many-arguments  # Port signature is fixed.
    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        status: GenerationRunStatus,
        current_node: str | None,
        ended_at: dt.datetime | None,
    ) -> GenerationRun:
        """Update lifecycle fields for a run."""
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise RunNotFound(run_id)
            if run.status.is_terminal():
                raise RunAlreadyTerminal(run_id)
            updated = dc.replace(
                run,
                status=status,
                current_node=current_node,
                ended_at=ended_at,
                updated_at=self.time_provider(),
            )
            self._runs[run_id] = updated
            return updated

    # pylint: disable-next=too-many-arguments  # Port signature is fixed.
    async def append_event(
        self,
        run_id: uuid.UUID,
        *,
        kind: str,
        payload: JsonMapping,
        occurred_at: dt.datetime | None = None,
    ) -> GenerationEvent:
        """Append an event with an adapter-allocated sequence."""
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise RunNotFound(run_id)
            if run.status.is_terminal():
                raise RunAlreadyTerminal(run_id)
            events = self._events.setdefault(run_id, [])
            now = self.time_provider()
            event = GenerationEvent(
                id=uuid.uuid7(),
                generation_run_id=run_id,
                seq=event_seq(len(events) + 1),
                kind=kind,
                payload=payload,
                created_at=now,
                occurred_at=occurred_at or now,
            )
            events.append(event)
            return event

    async def list_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
        limit: int = 100,
    ) -> tuple[GenerationEvent, ...]:
        """List events for a run after an optional sequence cursor."""
        if limit < 0:
            msg = "limit must be non-negative."
            raise ValueError(msg)
        async with self._lock:
            if run_id not in self._runs:
                raise RunNotFound(run_id)
            minimum_seq = int(after_seq) if after_seq is not None else 0
            events = [
                event
                for event in self._events.get(run_id, [])
                if event.seq > minimum_seq
            ]
            return tuple(events[:limit])

    async def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        """Persist a checkpoint."""
        async with self._lock:
            if checkpoint.generation_run_id not in self._runs:
                raise RunNotFound(checkpoint.generation_run_id)
            self._checkpoints[checkpoint.id] = checkpoint
            return checkpoint

    async def get_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None:
        """Return a checkpoint by identifier."""
        async with self._lock:
            return self._checkpoints.get(checkpoint_id)

    async def respond_to_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        response: CheckpointResponse,
    ) -> Checkpoint:
        """Record a reviewer response using the checkpoint domain transition."""
        async with self._lock:
            checkpoint = self._checkpoints.get(checkpoint_id)
            if checkpoint is None:
                raise CheckpointNotFound(checkpoint_id)
            responded = checkpoint.respond(response)
            self._checkpoints[checkpoint_id] = responded
            return responded
