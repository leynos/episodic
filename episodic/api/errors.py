"""Map domain exceptions to stable Falcon error envelopes.

Only unmapped HTTP ``500`` responses carry diagnostic metadata to the central
Falcon serializer. Mappers remain pure: they return the HTTP mapping and safe
diagnostic data but do not log. Records use synthetic redacted exceptions and
sanitized source metadata; profile/template records include only known codes
and UUID identifiers.
"""

import collections.abc as cabc
import typing as typ

import falcon

from episodic.canonical.profile_templates import (
    EntityNotFoundError,
    RevisionConflictError,
)
from episodic.canonical.reference_documents import (
    ReferenceConflictError,
    ReferenceDocumentError,
    ReferenceEntityNotFoundError,
    ReferenceRevisionConflictError,
    ReferenceValidationError,
)
from episodic.canonical.source_intake_service import (
    IngestionJobNotFoundError,
    SeriesProfileNotFoundError,
    SourceIntakeError,
    UploadHashMismatchError,
    UploadNotFoundError,
    UploadNotReadyError,
    UploadSizeMismatchError,
)

from ._error_logging import (
    _profile_template_error_diagnostic,
    _safe_profile_template_entity_id,
    _unmapped_error_diagnostic,
)
from .error_envelopes import (
    ErrorEnvelope,
    http_error,
    serialize_http_error,
    validation_error,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.profile_templates.types import ProfileTemplateError

type _HttpErrorFactory = cabc.Callable[..., falcon.HTTPError]

__all__ = (
    "ErrorEnvelope",
    "http_error",
    "map_profile_template_error",
    "map_reference_error",
    "map_source_intake_error",
    "serialize_http_error",
    "validation_error",
)


def map_profile_template_error(
    exc: ProfileTemplateError,
    *,
    entity_id: object | None = None,
    expected_revision: int | None = None,
) -> falcon.HTTPError:
    """Map profile/template domain errors to enriched Falcon errors.

    Parameters
    ----------
    exc : ProfileTemplateError
        Domain error raised by profile/template services.
    entity_id : object | None
        Optional entity identifier to use when the exception does not carry a
        safe identifier.
    expected_revision : int | None
        Optional optimistic-lock revision expected by the caller.

    Returns
    -------
    falcon.HTTPError
        Falcon error enriched with the API envelope metadata.

    Examples
    --------
    >>> map_profile_template_error(EntityNotFoundError("Profile not found."))
    """
    safe_entity_id = _safe_profile_template_entity_id(exc.entity_id)
    if safe_entity_id is None:
        safe_entity_id = _safe_profile_template_entity_id(entity_id)
    log_entity_id = safe_entity_id if safe_entity_id is not None else exc.entity_id
    details: dict[str, object] = {}
    if safe_entity_id is not None:
        details["entity_id"] = safe_entity_id
    if expected_revision is not None:
        details["expected_revision"] = expected_revision
    match exc:
        case EntityNotFoundError():
            return http_error(
                falcon.HTTPNotFound(description=str(exc)),
                code="not_found",
                details=details,
            )
        case RevisionConflictError() as revision_conflict:
            return http_error(
                falcon.HTTPConflict(description=str(revision_conflict)),
                code=revision_conflict.code,
                details=details,
            )
        case _:
            diagnostic = _profile_template_error_diagnostic(
                exc,
                log_entity_id,
            )
            return http_error(
                falcon.HTTPInternalServerError(
                    description="Unexpected profile/template error."
                ),
                code="internal_error",
                details={},
                unmapped_error_diagnostic=diagnostic,
            )


def map_reference_error(
    exc: ReferenceDocumentError,
    *,
    context: str,
) -> falcon.HTTPError:
    """Map reusable reference-document domain errors to Falcon HTTP errors.

    Parameters
    ----------
    exc : ReferenceDocumentError
        Domain error raised by reusable-reference services.
    context : str
        Short context label used for unexpected internal-error messages.

    Returns
    -------
    falcon.HTTPError
        Falcon ``400``, ``404``, ``409``, or ``500`` error enriched with
        envelope metadata.

    Examples
    --------
    >>> try:
    ...     raise ReferenceValidationError("Invalid reference document.")
    ... except ReferenceDocumentError as exc:
    ...     raise map_reference_error(
    ...         exc,
    ...         context="reference-document",
    ...     ) from exc
    """
    match exc:
        case ReferenceValidationError():
            return http_error(
                falcon.HTTPBadRequest(description=str(exc)),
                code="validation_error",
            )
        case ReferenceEntityNotFoundError():
            return http_error(
                falcon.HTTPNotFound(description=str(exc)),
                code="not_found",
            )
        case ReferenceRevisionConflictError():
            return http_error(
                falcon.HTTPConflict(description=str(exc)),
                code="revision_conflict",
            )
        case ReferenceConflictError():
            return http_error(
                falcon.HTTPConflict(description=str(exc)),
                code="conflict",
            )
    msg = f"Unexpected {context} error."
    diagnostic = _unmapped_error_diagnostic(
        exc.__traceback__,
        "Unmapped reference error: context=%s type=%s",
        context,
        type(exc).__name__,
    )
    return http_error(
        falcon.HTTPInternalServerError(description=msg),
        code="internal_error",
        unmapped_error_diagnostic=diagnostic,
    )


def map_source_intake_error(
    exc: SourceIntakeError,
) -> falcon.HTTPError:
    """Map source-intake errors to Falcon errors with safe diagnostics.

    Parameters
    ----------
    exc : SourceIntakeError
        Error raised by a source-intake service.

    Returns
    -------
    falcon.HTTPError
        Falcon error enriched with the API envelope metadata.

    Examples
    --------
    >>> try:
    ...     raise UploadNotReadyError("Upload is not ready.")
    ... except SourceIntakeError as exc:
    ...     raise map_source_intake_error(exc) from exc
    """
    mapping = _source_intake_error_mapping()
    for error_type, factory, code in mapping:
        if isinstance(exc, error_type):
            return http_error(factory(description=str(exc)), code=code)
    diagnostic = _unmapped_error_diagnostic(
        exc.__traceback__,
        "Unmapped source-intake error: type=%s",
        type(exc).__name__,
    )
    return http_error(
        falcon.HTTPInternalServerError(description="Unexpected source-intake error."),
        code="internal_error",
        unmapped_error_diagnostic=diagnostic,
    )


def _source_intake_error_mapping() -> tuple[
    tuple[type[SourceIntakeError], _HttpErrorFactory, str],
    ...,
]:
    """Return source-intake exception to HTTP error mappings."""
    return (
        (SeriesProfileNotFoundError, falcon.HTTPNotFound, "series_profile_not_found"),
        (IngestionJobNotFoundError, falcon.HTTPNotFound, "ingestion_job_not_found"),
        (UploadNotFoundError, falcon.HTTPNotFound, "upload_not_found"),
        (UploadNotReadyError, falcon.HTTPConflict, "upload_not_ready"),
        (UploadHashMismatchError, falcon.HTTPBadRequest, "upload_hash_mismatch"),
        (UploadSizeMismatchError, falcon.HTTPBadRequest, "upload_size_mismatch"),
    )
