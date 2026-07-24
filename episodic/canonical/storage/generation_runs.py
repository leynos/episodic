"""SQLAlchemy adapter for durable generation runs and event logs."""

import datetime as dt
import typing as typ
import uuid

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import (
    GenerationEvent,
    GenerationRun,
    GenerationRunStatus,
    JsonMapping,
)
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.canonical.generation_run_ports import (
    EventSeq,
    GenerationRunStatusUpdate,
    event_seq,
)
from episodic.orchestration._types import _log_event

from .generation_run_models import GenerationEventRecord, GenerationRunRecord

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession


def _now() -> dt.datetime:
    """Return a timezone-aware timestamp for adapter-owned updates."""
    return dt.datetime.now(dt.UTC)


def _run_from_record(record: GenerationRunRecord) -> GenerationRun:
    """Map a generation-run record to a domain entity."""
    return GenerationRun(
        id=record.id,
        episode_id=record.episode_id,
        source_bundle_id=record.source_bundle_id,
        actor=record.actor,
        status=record.status,
        current_node=record.current_node,
        budget_snapshot=record.budget_snapshot,
        configuration=record.configuration,
        created_at=record.created_at,
        updated_at=record.updated_at,
        started_at=record.started_at,
        ended_at=record.ended_at,
        error_message=record.error_message,
        error_category=record.error_category,
        quality_mode=record.quality_mode,
        qa_status=record.qa_status,
        skip_qa_rationale=record.skip_qa_rationale,
    )


def _run_to_record(
    run: GenerationRun,
    *,
    idempotency_key: str | None,
) -> GenerationRunRecord:
    """Map a generation-run domain entity to a SQLAlchemy record."""
    return GenerationRunRecord(
        id=run.id,
        episode_id=run.episode_id,
        source_bundle_id=run.source_bundle_id,
        actor=run.actor,
        status=run.status,
        current_node=run.current_node,
        budget_snapshot=run.budget_snapshot,
        configuration=run.configuration,
        quality_mode=run.quality_mode,
        qa_status=run.qa_status,
        skip_qa_rationale=run.skip_qa_rationale,
        idempotency_key=idempotency_key,
        error_message=run.error_message,
        error_category=run.error_category,
        lease_expires_at=None,
        started_at=run.started_at,
        ended_at=run.ended_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _event_from_record(record: GenerationEventRecord) -> GenerationEvent:
    """Map an event record to a domain event."""
    return GenerationEvent(
        id=record.id,
        generation_run_id=record.generation_run_id,
        seq=event_seq(record.seq),
        kind=record.kind,
        payload=record.payload,
        occurred_at=record.occurred_at,
        created_at=record.created_at,
    )


class SqlAlchemyGenerationRunStore:
    """Durable generation-run repository and event-log adapter."""

    def __init__(self, session: "AsyncSession") -> None:  # noqa: UP037
        self._session = session

    async def _get_record(self, run_id: uuid.UUID) -> GenerationRunRecord | None:
        """Return the storage record for a run id."""
        return await self._session.get(GenerationRunRecord, run_id)

    async def _require_mutable_run(
        self,
        run_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> GenerationRunRecord:
        """Return a non-terminal run record or raise the domain error."""
        if lock:
            result = await self._session.execute(
                sa
                .select(GenerationRunRecord)
                .where(GenerationRunRecord.id == run_id)
                .with_for_update()
            )
            record = result.scalar_one_or_none()
        else:
            record = await self._get_record(run_id)
        if record is None:
            raise RunNotFound(run_id)
        if record.status.is_terminal():
            raise RunAlreadyTerminal(run_id)
        return record

    async def _get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> GenerationRun | None:
        """Return the first run for an idempotency key."""
        result = await self._session.execute(
            sa.select(GenerationRunRecord).where(
                GenerationRunRecord.idempotency_key == idempotency_key
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return _run_from_record(record)

    async def create_run(
        self,
        run: GenerationRun,
        *,
        idempotency_key: str | None = None,
    ) -> GenerationRun:
        """Create a run, reusing the first run for an idempotency key."""
        if idempotency_key is not None:
            existing = await self._get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        record = _run_to_record(run, idempotency_key=idempotency_key)
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError:
            if idempotency_key is None:
                raise
            existing = await self._get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
            raise
        _log_event(
            "info",
            "sql_generation_run_store.create_run",
            run_id=str(run.id),
            episode_id=str(run.episode_id),
            idempotent=idempotency_key is not None,
        )
        return _run_from_record(record)

    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None:
        """Return a run by identifier."""
        record = await self._get_record(run_id)
        if record is None:
            return None
        return _run_from_record(record)

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
        statement = (
            sa
            .select(GenerationRunRecord)
            .where(GenerationRunRecord.episode_id == episode_id)
            .order_by(GenerationRunRecord.created_at, GenerationRunRecord.id)
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            statement = statement.where(GenerationRunRecord.status == status)
        result = await self._session.execute(statement)
        return tuple(_run_from_record(record) for record in result.scalars())

    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        update: GenerationRunStatusUpdate,
    ) -> GenerationRun:
        """Update lifecycle fields for a run."""
        record = await self._require_mutable_run(run_id, lock=True)
        record.status = update.status
        record.current_node = update.current_node
        record.ended_at = update.ended_at
        record.error_message = update.error_message
        record.error_category = update.error_category
        record.updated_at = _now()
        await self._session.flush()
        await self._session.refresh(record)
        _log_event(
            "info",
            "sql_generation_run_store.update_run_status",
            run_id=str(run_id),
            status=update.status.value,
            current_node=update.current_node,
        )
        return _run_from_record(record)

    async def claim_run_for_execution(
        self,
        run_id: uuid.UUID,
        *,
        current_node: str | None,
        started_at: dt.datetime,
        lease_expires_at: dt.datetime | None,
    ) -> GenerationRun | None:
        """Atomically move a pending run to running, or return None if lost."""
        now = _now()
        result = await self._session.execute(
            sa
            .update(GenerationRunRecord)
            .where(
                GenerationRunRecord.id == run_id,
                GenerationRunRecord.status == GenerationRunStatus.PENDING,
            )
            .values(
                status=GenerationRunStatus.RUNNING,
                current_node=current_node,
                started_at=started_at,
                lease_expires_at=lease_expires_at,
                updated_at=now,
            )
        )
        cursor_result = typ.cast("CursorResult[typ.Any]", result)
        if cursor_result.rowcount == 1:
            record = await self._get_record(run_id)
            if record is None:  # pragma: no cover - guarded by updated row.
                raise RunNotFound(run_id)
            return _run_from_record(record)

        record = await self._get_record(run_id)
        if record is None:
            raise RunNotFound(run_id)
        if record.status.is_terminal():
            raise RunAlreadyTerminal(run_id)
        return None

    async def append_event(
        self,
        run_id: uuid.UUID,
        *,
        kind: str,
        payload: JsonMapping,
        occurred_at: dt.datetime | None = None,
    ) -> GenerationEvent:
        """Append an event with an adapter-allocated sequence."""
        await self._require_mutable_run(run_id, lock=True)
        now = _now()
        max_seq = await self._session.scalar(
            sa.select(sa.func.max(GenerationEventRecord.seq)).where(
                GenerationEventRecord.generation_run_id == run_id
            )
        )
        record = GenerationEventRecord(
            id=uuid.uuid7(),
            generation_run_id=run_id,
            seq=(max_seq or 0) + 1,
            kind=kind,
            payload=payload,
            occurred_at=occurred_at or now,
            created_at=now,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        _log_event(
            "info",
            "sql_generation_run_store.append_event",
            run_id=str(run_id),
            event_id=str(record.id),
            seq=record.seq,
            kind=kind,
        )
        return _event_from_record(record)

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
        if await self._get_record(run_id) is None:
            raise RunNotFound(run_id)
        minimum_seq = int(after_seq) if after_seq is not None else 0
        result = await self._session.execute(
            sa
            .select(GenerationEventRecord)
            .where(
                GenerationEventRecord.generation_run_id == run_id,
                GenerationEventRecord.seq > minimum_seq,
            )
            .order_by(GenerationEventRecord.seq)
            .limit(limit)
        )
        return tuple(_event_from_record(record) for record in result.scalars())
