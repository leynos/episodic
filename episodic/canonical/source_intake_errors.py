"""Source-intake application error types."""


class SourceIntakeError(Exception):
    """Base class for source-intake domain errors."""


class SeriesProfileNotFoundError(SourceIntakeError):
    """Raised when creating a job for an unknown series profile."""


class IngestionJobNotFoundError(SourceIntakeError):
    """Raised when an ingestion job cannot be found."""


class UploadNotFoundError(SourceIntakeError):
    """Raised when a source attachment references an unknown upload."""


class UploadNotReadyError(SourceIntakeError):
    """Raised when a source attachment references a non-ready upload."""


class UploadHashMismatchError(SourceIntakeError):
    """Raised when the declared upload hash does not match stored bytes."""


class UploadSizeMismatchError(SourceIntakeError):
    """Raised when the declared upload size does not match stored bytes."""
