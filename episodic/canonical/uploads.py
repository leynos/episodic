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


def _require_non_negative_size(value: int, field_name: str) -> None:
    """Raise ValueError when an integer size field is negative."""
    if value < 0:
        msg = f"{field_name} must be non-negative."
        raise ValueError(msg)


def _require_non_empty_string(value: str, field_name: str) -> None:
    """Raise ValueError when *value* is blank after stripping whitespace."""
    if not value.strip():
        msg = f"{field_name} must be a non-empty string."
        raise ValueError(msg)


def _require_non_negative_actual_size(actual_size: int | None) -> None:
    """Raise ValueError when actual_size is provided but negative."""
    if actual_size is not None and actual_size < 0:
        msg = "actual_size must be non-negative when provided."
        raise ValueError(msg)


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
        _require_non_negative_size(self.declared_size, "declared_size")
        _require_non_negative_actual_size(self.actual_size)
        _require_non_empty_string(self.content_type, "content_type")
        _require_non_empty_string(self.storage_key, "storage_key")


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
        _require_non_negative_size(self.declared_size, "declared_size")
        _require_non_empty_string(self.content_type, "content_type")
