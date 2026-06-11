"""Repository protocols for upload and intake idempotency entities."""

import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from .domain import IntakeState
    from .idempotency import (
        IdempotencyAcquireRequest,
        IdempotencyOutcome,
        IdempotencyRecord,
    )
    from .ingestion_sources import IngestionJobSource
    from .uploads import Upload


class UploadRepository(typ.Protocol):
    """Persistence interface for upload metadata."""

    async def add(self, upload: Upload) -> None:
        """Persist an upload metadata record."""
        raise NotImplementedError

    async def get(self, upload_id: uuid.UUID) -> Upload | None:
        """Fetch an upload by identifier."""
        raise NotImplementedError

    async def mark_ready(
        self,
        upload_id: uuid.UUID,
        *,
        content_hash: str,
        actual_size: int,
    ) -> Upload:
        """Mark an upload as ready after bytes are stored."""
        raise NotImplementedError

    async def mark_failed(self, upload_id: uuid.UUID, reason: str) -> Upload:
        """Mark an upload as failed."""
        raise NotImplementedError


class IngestionJobSourceRepository(typ.Protocol):
    """Persistence interface for intake source attachments."""

    async def add(self, source: IngestionJobSource) -> None:
        """Persist a source attachment."""
        raise NotImplementedError

    async def get(self, source_id: uuid.UUID) -> IngestionJobSource | None:
        """Fetch a source attachment by identifier."""
        raise NotImplementedError

    async def list_for_job_paged(
        self,
        job_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> cabc.Sequence[IngestionJobSource]:
        """List source attachments for one ingestion job."""
        raise NotImplementedError

    async def count_for_job(self, job_id: uuid.UUID) -> int:
        """Count source attachments for one ingestion job."""
        raise NotImplementedError


class IdempotencyStore(typ.Protocol):
    """Persistence interface for retryable side-effect records."""

    async def acquire(
        self,
        *,
        request: IdempotencyAcquireRequest,
    ) -> IdempotencyOutcome:
        """Acquire or inspect an idempotency record."""
        raise NotImplementedError

    async def complete(
        self,
        *,
        record_id: uuid.UUID,
        serialised_outcome: bytes,
    ) -> None:
        """Store an opaque completed outcome for replay."""
        raise NotImplementedError

    async def lookup(
        self,
        *,
        principal_id: str | None,
        operation: str,
        idempotency_key: str,
    ) -> IdempotencyRecord | None:
        """Fetch an idempotency record by its logical key."""
        raise NotImplementedError


class IntakeStateTransitionRepository(typ.Protocol):
    """Persistence interface for conditional intake-state transitions."""

    async def transition_intake_state(
        self,
        job_id: uuid.UUID,
        *,
        from_state: IntakeState,
        to_state: IntakeState,
    ) -> bool:
        """Return True only when the conditional state update matched."""
        raise NotImplementedError
