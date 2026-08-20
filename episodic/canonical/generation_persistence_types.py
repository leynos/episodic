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
    """Base class for draft persistence failures.

    Catch this exception to handle failures raised while materialising an
    episode or persisting its generated draft.
    """


class _IngestionJobPersistenceError(DraftScriptPersistenceError):
    """Base error that retains an ingestion-job identifier for diagnostics."""

    message_template: typ.ClassVar[str]

    def __init__(self, ingestion_job_id: uuid.UUID) -> None:
        """Initialize an ingestion-job persistence error."""
        self.ingestion_job_id = ingestion_job_id
        message = self.message_template.format(ingestion_job_id=ingestion_job_id)
        super().__init__(message)


class IngestionJobNotReadyError(_IngestionJobPersistenceError):
    """Raised when materialisation is requested before an intake job is ready.

    Parameters
    ----------
    ingestion_job_id : uuid.UUID
        Identifier of the ingestion job that is not ready for generation.

    Attributes
    ----------
    ingestion_job_id : uuid.UUID
        Identifier of the ingestion job retained for diagnostics.
    """

    message_template: typ.ClassVar[str] = (
        "Ingestion job {ingestion_job_id} is not ready for generation."
    )


class MissingAttachedSourcesError(_IngestionJobPersistenceError):
    """Raised when a ready ingestion job has no source attachments.

    Parameters
    ----------
    ingestion_job_id : uuid.UUID
        Identifier of the ready ingestion job without source attachments.

    Attributes
    ----------
    ingestion_job_id : uuid.UUID
        Identifier of the ingestion job retained for diagnostics.
    """

    message_template: typ.ClassVar[str] = (
        "Ingestion job {ingestion_job_id} has no attached sources."
    )


class GenerationSourceUploadNotFoundError(DraftScriptPersistenceError):
    """Raised when a generation source refers to an absent upload.

    Parameters
    ----------
    upload_id : uuid.UUID
        Identifier of the upload referenced by the generation source.

    Attributes
    ----------
    upload_id : uuid.UUID
        Identifier of the missing upload retained for diagnostics.
    """

    def __init__(self, upload_id: uuid.UUID) -> None:
        """Initialize an error for a missing generation-source upload.

        Parameters
        ----------
        upload_id : uuid.UUID
            Identifier of the upload referenced by the generation source.
        """
        self.upload_id = upload_id
        message = f"Upload {upload_id} was not found for ingestion source."
        super().__init__(message)


class DraftContentHashMismatchError(DraftScriptPersistenceError):
    """Raised when generated TEI and its declared hash disagree.

    Parameters
    ----------
    expected_hash : str
        SHA-256 hash calculated from the generated TEI.
    actual_hash : str
        Hash declared by the generated draft result.

    Attributes
    ----------
    expected_hash : str
        SHA-256 hash calculated from the generated TEI.
    actual_hash : str
        Hash declared by the generated draft result.
    """

    def __init__(self, expected_hash: str, actual_hash: str) -> None:
        """Initialize an error for mismatched generated-content hashes.

        Parameters
        ----------
        expected_hash : str
            SHA-256 hash calculated from the generated TEI.
        actual_hash : str
            Hash declared by the generated draft result.
        """
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        message = "Draft script content_hash does not match tei_xml."
        super().__init__(message)


class InvalidDraftTeiError(DraftScriptPersistenceError, ValueError):
    """Raised when generated TEI cannot be validated.

    The validation message is supplied to the inherited :class:`ValueError`
    constructor and is available through the standard exception arguments.
    """


class SourceDocumentProjectionError(DraftScriptPersistenceError):
    """Raised when a duplicate projection does not contain every source row.

    Parameters
    ----------
    missing_document_ids : collections.abc.Collection[uuid.UUID]
        Identifiers expected from the projection but absent after the
        duplicate-write race.

    Attributes
    ----------
    missing_document_ids : tuple[uuid.UUID, ...]
        Missing document identifiers, sorted by their string representation
        and retained as an immutable tuple for diagnostics.
    """

    def __init__(self, missing_document_ids: cabc.Collection[uuid.UUID]) -> None:
        """Initialize an error for an incomplete source-document projection.

        Parameters
        ----------
        missing_document_ids : collections.abc.Collection[uuid.UUID]
            Identifiers expected from the projection but absent after the
            duplicate-write race.
        """
        self.missing_document_ids = tuple(sorted(missing_document_ids, key=str))
        missing_ids = ", ".join(
            str(document_id) for document_id in self.missing_document_ids
        )
        message = (
            "Source document projection did not complete after a duplicate race: "
            f"missing {missing_ids}."
        )
        super().__init__(message)


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
