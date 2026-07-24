"""In-memory generation-run port adapter.

This module provides a reference implementation of the generation-run port
protocols for tests and local development. It is ephemeral, single-process
storage and is not a production persistence layer.
"""

import asyncio
import bisect
import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import uuid

from episodic.canonical.domain import (
    Checkpoint,
    GenerationEvent,
    GenerationRun,
    GenerationRunStatus,
    JsonMapping,
)
from episodic.canonical.generation_run_errors import (
    RunAlreadyTerminal,
    RunNotFound,
)
from episodic.canonical.generation_run_ports import (
    EventSeq,
    GenerationRunStatusUpdate,
    event_seq,
)
from episodic.orchestration._types import _log_event

from .generation_checkpoints import InMemoryGenerationCheckpointMixin

TimeProvider = cabc.Callable[[], dt.datetime]


def _now_utc() -> dt.datetime:
    """Return the current UTC time for in-memory records."""
    return dt.datetime.now(dt.UTC)


def _default_time_provider() -> TimeProvider:
    """Return the default in-memory timestamp provider."""
    return _now_utc


@dc.dataclass(slots=True)
class InMemoryGenerationRunStore(InMemoryGenerationCheckpointMixin):
    """In-memory reference adapter for the composite generation-run port."""

    time_provider: TimeProvider = dc.field(default_factory=_default_time_provider)
    _runs: dict[uuid.UUID, GenerationRun] = dc.field(default_factory=dict)
    _run_ids_by_episode: dict[uuid.UUID, list[tuple[dt.datetime, uuid.UUID]]] = (
        dc.field(default_factory=dict)
    )
    _events: dict[uuid.UUID, list[GenerationEvent]] = dc.field(default_factory=dict)
    _checkpoints: dict[uuid.UUID, Checkpoint] = dc.field(default_factory=dict)
    _idempotency_keys: dict[str, uuid.UUID] = dc.field(default_factory=dict)
    _lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)

    def _require_mutable_run(self, run_id: uuid.UUID) -> GenerationRun:
        """Return a run that may still accept lifecycle mutations."""
        run = self._runs.get(run_id)
        if run is None:
            raise RunNotFound(run_id)
        if run.status.is_terminal():
            raise RunAlreadyTerminal(run_id)
        return run

    def _runs_for_episode(
        self,
        episode_id: uuid.UUID,
        *,
        status: GenerationRunStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[GenerationRun, ...]:
        """Return indexed runs for one episode without scanning all runs."""
        indexed_ids = self._run_ids_by_episode.get(episode_id, [])
        if status is None:
            selected_ids = indexed_ids[offset : offset + limit]
            return tuple(self._runs[run_id] for _, run_id in selected_ids)
        skipped = 0
        selected: list[GenerationRun] = []
        for _, run_id in indexed_ids:
            run = self._runs[run_id]
            if run.status is not status:
                continue
            if skipped < offset:
                skipped += 1
                continue
            selected.append(run)
            if len(selected) == limit:
                break
        return tuple(selected)

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
                    _log_event(
                        "info",
                        "generation_run_store.create_run_reused",
                        run_id=str(existing_id),
                        supplied_run_id=str(run.id),
                        episode_id=str(run.episode_id),
                    )
                    return self._runs[existing_id]
            self._runs[run.id] = run
            bisect.insort(
                self._run_ids_by_episode.setdefault(run.episode_id, []),
                (run.created_at, run.id),
            )
            self._events.setdefault(run.id, [])
            if idempotency_key is not None:
                self._idempotency_keys[idempotency_key] = run.id
            _log_event(
                "info",
                "generation_run_store.create_run",
                run_id=str(run.id),
                episode_id=str(run.episode_id),
                status=run.status.value,
                idempotent=idempotency_key is not None,
            )
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
            return self._runs_for_episode(
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
        """Update lifecycle fields for a run."""
        async with self._lock:
            try:
                run = self._require_mutable_run(run_id)
            except RunNotFound:
                _log_event(
                    "warning",
                    "generation_run_store.update_run_missing",
                    run_id=str(run_id),
                    status=update.status.value,
                )
                raise
            except RunAlreadyTerminal:
                run = self._runs[run_id]
                _log_event(
                    "warning",
                    "generation_run_store.update_run_terminal",
                    run_id=str(run_id),
                    current_status=run.status.value,
                    requested_status=update.status.value,
                )
                raise
            updated = dc.replace(
                run,
                status=update.status,
                current_node=update.current_node,
                ended_at=update.ended_at,
                error_message=update.error_message,
                error_category=update.error_category,
                updated_at=self.time_provider(),
            )
            self._runs[run_id] = updated
            _log_event(
                "info",
                "generation_run_store.update_run_status",
                run_id=str(run_id),
                previous_status=run.status.value,
                status=update.status.value,
                current_node=update.current_node,
            )
            return updated

    # pylint: disable-next=too-many-arguments  # Port signature is fixed.
    async def claim_run_for_execution(
        self,
        run_id: uuid.UUID,
        *,
        current_node: str | None,
        started_at: dt.datetime,
        lease_expires_at: dt.datetime | None,
    ) -> GenerationRun | None:
        """Atomically claim a pending run for execution."""
        async with self._lock:
            try:
                run = self._require_mutable_run(run_id)
            except RunNotFound:
                _log_event(
                    "warning",
                    "generation_run_store.claim_run_missing",
                    run_id=str(run_id),
                )
                raise
            except RunAlreadyTerminal:
                run = self._runs[run_id]
                _log_event(
                    "warning",
                    "generation_run_store.claim_run_terminal",
                    run_id=str(run_id),
                    status=run.status.value,
                )
                raise
            if run.status is not GenerationRunStatus.PENDING:
                _log_event(
                    "info",
                    "generation_run_store.claim_run_lost",
                    run_id=str(run_id),
                    status=run.status.value,
                )
                return None
            updated = dc.replace(
                run,
                status=GenerationRunStatus.RUNNING,
                current_node=current_node,
                started_at=started_at,
                updated_at=self.time_provider(),
            )
            self._runs[run_id] = updated
            _log_event(
                "info",
                "generation_run_store.claim_run",
                run_id=str(run_id),
                current_node=current_node,
                lease_expires_at=lease_expires_at.isoformat()
                if lease_expires_at is not None
                else None,
            )
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
            try:
                self._require_mutable_run(run_id)
            except RunNotFound:
                _log_event(
                    "warning",
                    "generation_run_store.append_event_missing_run",
                    run_id=str(run_id),
                    kind=kind,
                )
                raise
            except RunAlreadyTerminal:
                run = self._runs[run_id]
                _log_event(
                    "warning",
                    "generation_run_store.append_event_terminal_run",
                    run_id=str(run_id),
                    status=run.status.value,
                    kind=kind,
                )
                raise
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
            _log_event(
                "info",
                "generation_run_store.append_event",
                run_id=str(run_id),
                event_id=str(event.id),
                seq=int(event.seq),
                kind=kind,
            )
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
