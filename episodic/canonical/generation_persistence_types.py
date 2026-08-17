"""Commands, typed errors, and projections for draft persistence services."""

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

if typ.TYPE_CHECKING:
    from episodic.canonical.ingestion_sources import IngestionJobSource
    from episodic.canonical.uploads import Upload
    from episodic.generation.draft_script import DraftScriptResult

type Clock = cabc.Callable[[], dt.datetime]
type UuidFactory = cabc.Callable[[], uuid.UUID]


def _utc_now() -> dt.datetime:
    """Return a timezone-aware UTC timestamp."""
    return dt.datetime.now(dt.UTC)


def _uuid7() -> uuid.UUID:
    """Return a monotonic storage UUID."""
    return uuid.uuid7()


class DraftScriptPersistenceError(Exception):
    """Base class for draft persistence failures."""


class IngestionJobNotReadyError(DraftScriptPersistenceError):
    """Raised when materialisation is requested before an intake job is ready."""

    def __init__(self, ingestion_job_id: uuid.UUID) -> None:
        self.ingestion_job_id = ingestion_job_id
        message = f"Ingestion job {ingestion_job_id} is not ready for generation."
        super().__init__(message)


class MissingAttachedSourcesError(DraftScriptPersistenceError):
    """Raised when a ready ingestion job has no source attachments."""

    def __init__(self, ingestion_job_id: uuid.UUID) -> None:
        self.ingestion_job_id = ingestion_job_id
        message = f"Ingestion job {ingestion_job_id} has no attached sources."
        super().__init__(message)


class GenerationSourceUploadNotFoundError(DraftScriptPersistenceError):
    """Raised when a generation source refers to an absent upload."""

    def __init__(self, upload_id: uuid.UUID) -> None:
        self.upload_id = upload_id
        message = f"Upload {upload_id} was not found for ingestion source."
        super().__init__(message)


class DraftContentHashMismatchError(DraftScriptPersistenceError):
    """Raised when generated TEI and its declared hash disagree."""

    def __init__(self, expected_hash: str, actual_hash: str) -> None:
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        message = "Draft script content_hash does not match tei_xml."
        super().__init__(message)


class InvalidDraftTeiError(DraftScriptPersistenceError, ValueError):
    """Raised when generated TEI cannot be validated."""


class SourceDocumentProjectionError(DraftScriptPersistenceError):
    """Raised when a duplicate projection does not contain every source row."""


@dc.dataclass(frozen=True, slots=True)
class EpisodeMaterialisationRequest:
    """Command for materialising an episode from an ingestion job.

    Parameters
    ----------
    ingestion_job_id
        Ready ingestion job whose attached sources become canonical documents.
    title
        Initial title for a newly materialised placeholder episode.
    clock
        UTC clock used for durable placeholder timestamps.
    uuid_factory
        Identifier factory used only when the job has no target episode.
    """

    ingestion_job_id: uuid.UUID
    title: str
    clock: Clock = _utc_now
    uuid_factory: UuidFactory = _uuid7


@dc.dataclass(frozen=True, slots=True)
class DraftScriptPersistenceRequest:
    """Command for writing generated draft TEI to an episode.

    Parameters
    ----------
    episode_id
        Canonical episode receiving the generated TEI revision.
    generation_run_id
        Run recorded as provenance for the no-QA update.
    result
        Validated draft output from :class:`DraftScriptGenerator`.
    expected_revision
        Revision that must still be current when the TEI is written.
    clock
        UTC clock used for the persisted update timestamp.
    """

    episode_id: uuid.UUID
    generation_run_id: uuid.UUID
    result: DraftScriptResult
    expected_revision: int
    clock: Clock = _utc_now


@dc.dataclass(frozen=True, slots=True)
class _SourceDocumentProjection:
    """Values needed to turn an intake attachment into a source document."""

    source: IngestionJobSource
    upload: Upload | None
    episode_id: uuid.UUID
    document_id: uuid.UUID
    now: dt.datetime
