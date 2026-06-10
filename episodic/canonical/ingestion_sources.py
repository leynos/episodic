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
        if has_upload == has_uri:
            msg = "Exactly one of upload_id or source_uri must be populated."
            raise ValueError(msg)
        if self.attachment_kind is AttachmentKind.UPLOAD and not has_upload:
            msg = "upload attachments must populate upload_id."
            raise ValueError(msg)
        if self.attachment_kind is AttachmentKind.SOURCE_URI and not has_uri:
            msg = "source_uri attachments must populate source_uri."
            raise ValueError(msg)
        if not self.source_type.strip():
            msg = "source_type must be a non-empty string."
            raise ValueError(msg)
        if not 0 <= self.weight <= 1:
            msg = "weight must be between 0 and 1."
            raise ValueError(msg)
