"""Verify mapped API errors stay expected and do not emit error logs."""

import dataclasses as dc
import typing as typ
from unittest import mock

import falcon
import pytest

from episodic.api import errors as api_errors
from episodic.canonical.profile_templates import (
    EntityNotFoundError,
    RevisionConflictError,
)
from episodic.canonical.reference_documents.types import (
    ReferenceConflictError,
    ReferenceDocumentError,
    ReferenceEntityNotFoundError,
    ReferenceRevisionConflictError,
    ReferenceValidationError,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.profile_templates.types import ProfileTemplateError
from episodic.canonical.source_intake_errors import (
    IngestionJobNotFoundError,
    SeriesProfileNotFoundError,
    SourceIntakeError,
    UploadHashMismatchError,
    UploadNotFoundError,
    UploadNotReadyError,
    UploadSizeMismatchError,
)


@dc.dataclass(frozen=True, slots=True)
class _MappedErrorCase:
    """Describe one expected domain-error mapping."""

    exception: Exception
    mapper: cabc.Callable[[Exception], falcon.HTTPError]
    expected_type: type[falcon.HTTPError]
    expected_code: str


def _map_profile_error(exc: Exception) -> falcon.HTTPError:
    """Map one profile/template error case."""
    return api_errors.map_profile_template_error(typ.cast("ProfileTemplateError", exc))


def _map_reference_error(exc: Exception) -> falcon.HTTPError:
    """Map one reference-document error case."""
    return api_errors.map_reference_error(
        typ.cast("ReferenceDocumentError", exc),
        context="reference-document",
    )


def _map_source_intake_error(exc: Exception) -> falcon.HTTPError:
    """Map one source-intake error case."""
    return api_errors.map_source_intake_error(typ.cast("SourceIntakeError", exc))


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _MappedErrorCase(
                EntityNotFoundError("Profile not found."),
                _map_profile_error,
                falcon.HTTPNotFound,
                "not_found",
            ),
            id="profile-not-found",
        ),
        pytest.param(
            _MappedErrorCase(
                RevisionConflictError("Revision conflict."),
                _map_profile_error,
                falcon.HTTPConflict,
                "revision_conflict",
            ),
            id="profile-revision-conflict",
        ),
        pytest.param(
            _MappedErrorCase(
                ReferenceValidationError("Invalid reference."),
                _map_reference_error,
                falcon.HTTPBadRequest,
                "validation_error",
            ),
            id="reference-validation",
        ),
        pytest.param(
            _MappedErrorCase(
                ReferenceEntityNotFoundError("Reference not found."),
                _map_reference_error,
                falcon.HTTPNotFound,
                "not_found",
            ),
            id="reference-not-found",
        ),
        pytest.param(
            _MappedErrorCase(
                ReferenceRevisionConflictError("Reference revision conflict."),
                _map_reference_error,
                falcon.HTTPConflict,
                "revision_conflict",
            ),
            id="reference-revision-conflict",
        ),
        pytest.param(
            _MappedErrorCase(
                ReferenceConflictError("Reference conflict."),
                _map_reference_error,
                falcon.HTTPConflict,
                "conflict",
            ),
            id="reference-conflict",
        ),
        pytest.param(
            _MappedErrorCase(
                SeriesProfileNotFoundError("Profile not found."),
                _map_source_intake_error,
                falcon.HTTPNotFound,
                "series_profile_not_found",
            ),
            id="intake-profile-not-found",
        ),
        pytest.param(
            _MappedErrorCase(
                IngestionJobNotFoundError("Job not found."),
                _map_source_intake_error,
                falcon.HTTPNotFound,
                "ingestion_job_not_found",
            ),
            id="intake-job-not-found",
        ),
        pytest.param(
            _MappedErrorCase(
                UploadNotFoundError("Upload not found."),
                _map_source_intake_error,
                falcon.HTTPNotFound,
                "upload_not_found",
            ),
            id="intake-upload-not-found",
        ),
        pytest.param(
            _MappedErrorCase(
                UploadNotReadyError("Upload is not ready."),
                _map_source_intake_error,
                falcon.HTTPConflict,
                "upload_not_ready",
            ),
            id="intake-upload-not-ready",
        ),
        pytest.param(
            _MappedErrorCase(
                UploadHashMismatchError("Upload hash mismatch."),
                _map_source_intake_error,
                falcon.HTTPBadRequest,
                "upload_hash_mismatch",
            ),
            id="intake-hash-mismatch",
        ),
        pytest.param(
            _MappedErrorCase(
                UploadSizeMismatchError("Upload size mismatch."),
                _map_source_intake_error,
                falcon.HTTPBadRequest,
                "upload_size_mismatch",
            ),
            id="intake-size-mismatch",
        ),
    ],
)
def test_mapped_domain_errors_do_not_log(
    case: _MappedErrorCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expected 400, 404 and 409 outcomes return their mappings without logs."""
    spy_logger = mock.Mock()
    monkeypatch.setattr(api_errors, "logger", spy_logger)

    result = case.mapper(case.exception)

    assert isinstance(result, case.expected_type), (
        f"expected {case.expected_type.__name__}, got {type(result).__name__}"
    )
    assert typ.cast("typ.Any", result).envelope_code == case.expected_code, (
        f"expected envelope code {case.expected_code!r}"
    )
    spy_logger.error.assert_not_called()


@pytest.mark.parametrize(
    "exception",
    [
        pytest.param(
            EntityNotFoundError("Profile not found.", entity_id="untrusted-id"),
            id="not-found",
        ),
        pytest.param(
            RevisionConflictError("Revision conflict.", entity_id="untrusted-id"),
            id="revision-conflict",
        ),
    ],
)
def test_mapped_profile_errors_omit_untrusted_entity_ids(
    exception: ProfileTemplateError,
) -> None:
    """Mapped profile errors do not return non-UUID identifiers to clients."""
    result = api_errors.map_profile_template_error(exception)

    assert typ.cast("typ.Any", result).envelope_details == {}, (
        "mapped error details must omit non-UUID entity identifiers"
    )
