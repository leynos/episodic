"""Source attachment entities for intake-stage ingestion jobs."""

import dataclasses as dc
import enum
import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from .domain import JsonMapping


class AttachmentKind(enum.StrEnum):
    """Supported source attachment kinds."""

    UPLOAD = "upload"
    SOURCE_URI = "source_uri"


def _require_exclusive_source(has_upload: bool, has_uri: bool) -> None:
    """Raise ValueError when exactly one source identifier is not populated."""
    if has_upload == has_uri:
        msg = "Exactly one of upload_id or source_uri must be populated."
        raise ValueError(msg)


def _require_kind_upload_populated(
    kind: AttachmentKind, has_upload: bool
) -> None:
    """Raise ValueError when an upload attachment lacks upload_id."""
    if kind is AttachmentKind.UPLOAD and not has_upload:
        msg = "upload attachments must populate upload_id."
        raise ValueError(msg)


def _require_kind_source_uri_populated(
    kind: AttachmentKind, has_uri: bool
) -> None:
    """Raise ValueError when a source_uri attachment lacks source_uri."""
    if kind is AttachmentKind.SOURCE_URI and not has_uri:
        msg = "source_uri attachments must populate source_uri."
        raise ValueError(msg)


def _require_non_empty_source_type(source_type: str) -> None:
    """Raise ValueError when source_type is blank after stripping whitespace."""
    if not source_type.strip():
        msg = "source_type must be a non-empty string."
        raise ValueError(msg)


def _require_valid_weight(weight: float) -> None:
    """Raise ValueError when weight is outside the [0, 1] range."""
    if not 0 <= weight <= 1:
        msg = "weight must be between 0 and 1."
        raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class IngestionJobSource:
    """A source attached to an ingestion job before generation starts."""

    id: uuid.UUID
    ingestion_job_id: uuid.UUID
    attachment_kind: AttachmentKind
    upload_id: uuid.UUID | None
    source_uri: str | None
    source_type: str
    weight: float
    metadata: JsonMapping
    created_at: dt.datetime

    def __post_init__(self) -> None:
        """Validate attachment shape and weighting invariants."""
        has_upload = self.upload_id is not None
        has_uri = self.source_uri is not None
        _require_exclusive_source(has_upload, has_uri)
        _require_kind_upload_populated(self.attachment_kind, has_upload)
        _require_kind_source_uri_populated(self.attachment_kind, has_uri)
        _require_non_empty_source_type(self.source_type)
        _require_valid_weight(self.weight)
