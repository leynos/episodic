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


def _validate_exclusive_attachment(
    upload_id: uuid.UUID | None, source_uri: str | None
) -> None:
    if (upload_id is not None) == (source_uri is not None):
        msg = "Exactly one of upload_id or source_uri must be populated."
        raise ValueError(msg)


def _validate_upload_kind(kind: AttachmentKind, upload_id: uuid.UUID | None) -> None:
    if kind is AttachmentKind.UPLOAD and upload_id is None:
        msg = "upload attachments must populate upload_id."
        raise ValueError(msg)


def _validate_source_uri_kind(kind: AttachmentKind, source_uri: str | None) -> None:
    if kind is AttachmentKind.SOURCE_URI and source_uri is None:
        msg = "source_uri attachments must populate source_uri."
        raise ValueError(msg)


def _validate_source_type(source_type: str) -> None:
    if not source_type.strip():
        msg = "source_type must be a non-empty string."
        raise ValueError(msg)


def _validate_weight(weight: float) -> None:
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
        _validate_exclusive_attachment(self.upload_id, self.source_uri)
        _validate_upload_kind(self.attachment_kind, self.upload_id)
        _validate_source_uri_kind(self.attachment_kind, self.source_uri)
        _validate_source_type(self.source_type)
        _validate_weight(self.weight)
