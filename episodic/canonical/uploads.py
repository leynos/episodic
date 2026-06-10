"""Upload domain entities for source-intake workflows."""

import dataclasses as dc
import enum
import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from .domain import JsonMapping


class UploadState(enum.StrEnum):
    """Lifecycle states for uploaded source bytes."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


@dc.dataclass(frozen=True, slots=True)
class Upload:
    """Metadata record for uploaded bytes."""

    id: uuid.UUID
    owner_principal_id: str | None
    content_type: str
    declared_size: int
    actual_size: int | None
    declared_sha256: str | None
    content_hash: str | None
    storage_key: str
    state: UploadState
    metadata: JsonMapping
    created_at: dt.datetime
    updated_at: dt.datetime

    def __post_init__(self) -> None:
        """Validate upload invariants at the domain boundary."""
        if self.declared_size < 0:
            msg = "declared_size must be non-negative."
            raise ValueError(msg)
        if self.actual_size is not None and self.actual_size < 0:
            msg = "actual_size must be non-negative when provided."
            raise ValueError(msg)
        if not self.content_type.strip():
            msg = "content_type must be a non-empty string."
            raise ValueError(msg)
        if not self.storage_key.strip():
            msg = "storage_key must be a non-empty string."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class UploadInitRequest:
    """Validated request to reserve an upload metadata row."""

    owner_principal_id: str | None
    content_type: str
    declared_size: int
    declared_sha256: str | None
    metadata: JsonMapping

    def __post_init__(self) -> None:
        """Validate the client-declared upload metadata."""
        if self.declared_size < 0:
            msg = "declared_size must be non-negative."
            raise ValueError(msg)
        if not self.content_type.strip():
            msg = "content_type must be a non-empty string."
            raise ValueError(msg)
