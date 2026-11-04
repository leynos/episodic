"""Verify central serialization diagnostics for unmapped API errors."""

import dataclasses as dc
import logging
import traceback
import typing as typ
from functools import partial

import falcon
import pytest
from falcon import testing as falcon_testing

from episodic.api import errors as api_errors
from episodic.canonical.profile_templates.types import ProfileTemplateError
from episodic.canonical.reference_documents.types import ReferenceDocumentError
from episodic.canonical.source_intake_errors import SourceIntakeError
from episodic.logging import log_error
from tests.fixtures.api_errors import API_ERROR_TEST_LOGGER_NAME as _TEST_LOGGER_NAME

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from syrupy.assertion import SnapshotAssertion

    from tests.fixtures.api_errors import SpyLogger

_TEST_CREDENTIAL = "test-only-secret-marker"
_TEST_CAUSE_CREDENTIAL = "test-only-cause-secret-marker"
_TEST_ENTITY_ID = "00000000-0000-0000-0000-000000000007"


class _UnexpectedProfileTemplateError(ProfileTemplateError):
    """Represent a profile/template error without a dedicated HTTP mapping."""


class _UnexpectedReferenceDocumentError(ReferenceDocumentError):
    """Represent a reference error without a dedicated HTTP mapping."""


class _UnexpectedSourceIntakeError(SourceIntakeError):
    """Represent a source-intake error without a dedicated HTTP mapping."""


class _HasEnvelopeMetadata(typ.Protocol):
    """Describe the dynamic envelope metadata added to Falcon errors."""

    envelope_code: str
    envelope_details: dict[str, object]


def _envelope_code(error: falcon.HTTPError) -> str:
    """Return the dynamic error-envelope code attached by ``http_error``."""
    return typ.cast("_HasEnvelopeMetadata", error).envelope_code


def _envelope_details(error: falcon.HTTPError) -> dict[str, object]:
    """Return the dynamic error-envelope details attached by ``http_error``."""
    return typ.cast("_HasEnvelopeMetadata", error).envelope_details


def _raise_with_credential_cause(exc: Exception) -> typ.NoReturn:
    """Raise a mapper exception with a credential-like chained cause."""
    raise exc from RuntimeError(_TEST_CAUSE_CREDENTIAL)


def _assert_detached_exception_info_logged(
    caplog: pytest.LogCaptureFixture,
    exc: Exception,
) -> None:
    """Verify detached exception info cannot retain source frames or secrets."""
    records = [record for record in caplog.records if record.name == _TEST_LOGGER_NAME]
    assert len(records) == 1, "each unmapped error must emit one log record"
    record = records[0]
    assert record.exc_info is not None, "error log must include exception information"
    formatted_traceback = "".join(traceback.format_exception(*record.exc_info))
    logged_content = record.getMessage() + formatted_traceback
    assert _TEST_CREDENTIAL not in logged_content, (
        "logs must not include credential-like exception text"
    )
    assert _TEST_CAUSE_CREDENTIAL not in logged_content, (
        "logs must not include credential-like chained exception text"
    )
    logged_exception = record.exc_info[1]
    assert logged_exception is not None, "error log must include an exception value"
    assert logged_exception is not exc, "logs must not retain the source exception"
    assert logged_exception.__cause__ is None, "logs must omit chained causes"
    assert logged_exception.__context__ is None, (
        "logs must omit implicit exception chains"
    )
    assert record.exc_info[2] is None, (
        "log records must not retain a traceback that can expose caller locals"
    )
    assert type(exc).__name__ in record.getMessage(), (
        "the safe log message must identify the source exception type"
    )
    assert "Original exception message redacted." in formatted_traceback, (
        "detached exception information must identify redacted exception text"
    )
    assert "Source frames:" in formatted_traceback, (
        "detached exception information must preserve safe source-frame metadata"
    )


def _assert_spy_logger_call(
    spy_logger: SpyLogger,
    source_exception: Exception,
    expected_message: str,
) -> None:
    """Verify one error log carries a detached, redacted exception tuple."""
    assert len(spy_logger.calls) == 1, "each unmapped error must log once"
    level, message, exc_info = spy_logger.calls[0]
    assert (level, message) == ("ERROR", expected_message), (
        "the serializer must emit one ERROR with safe metadata"
    )
    assert isinstance(exc_info, tuple), (
        "the logging port must receive detached exception information"
    )
    assert len(exc_info) == 3, "detached exception information must be a triple"
    assert exc_info[1] is not source_exception, (
        "the logging port must not receive the source exception"
    )
    assert exc_info[2] is None, (
        "the logging port must not receive live traceback frames"
    )


@dc.dataclass(frozen=True, slots=True)
class _UnmappedMapperCase:
    """Describe one error mapper's unmapped fallback contract."""

    exception: Exception
    mapper: cabc.Callable[[Exception], falcon.HTTPError]
    expected_message: str


def _stable_mapper_snapshot(
    case: _UnmappedMapperCase,
    result: falcon.HTTPError,
    log_call: tuple[str, str, object],
) -> dict[str, object]:
    """Project mapper output onto stable, redacted snapshot fields."""
    level, message, exc_info = log_call
    assert isinstance(exc_info, tuple), "mapper diagnostics must include exc_info"
    logged_exception = typ.cast("BaseException", exc_info[1])
    stable_message = message.replace(
        type(case.exception).__name__,
        "<exception type>",
    ).replace(_TEST_ENTITY_ID, "<uuid>")
    return {
        "status": result.status,
        "envelope": {
            "code": _envelope_code(result),
            "message": result.description,
            "details": _envelope_details(result),
        },
        "log": {
            "level": level,
            "message": stable_message,
            "exception": {
                "type": "<detached exception>",
                "message": "Original exception message redacted. "
                "Source frames: <source frames>",
                "cause": "<omitted>"
                if logged_exception.__cause__ is None
                else "<redacted>",
                "context": "<omitted>"
                if logged_exception.__context__ is None
                else "<redacted>",
                "traceback": "<omitted>" if exc_info[2] is None else "<redacted>",
            },
        },
    }


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _UnmappedMapperCase(
                _UnexpectedProfileTemplateError(
                    "Unexpected profile/template failure: " + _TEST_CREDENTIAL,
                    entity_id=_TEST_ENTITY_ID,
                ),
                lambda exc: api_errors.map_profile_template_error(
                    typ.cast("ProfileTemplateError", exc),
                ),
                (
                    "Unmapped profile/template error: "
                    "type=_UnexpectedProfileTemplateError "
                    "code=profile_template_error "
                    f"entity_id={_TEST_ENTITY_ID}"
                ),
            ),
            id="profile-template",
        ),
        pytest.param(
            _UnmappedMapperCase(
                _UnexpectedReferenceDocumentError(
                    "Unexpected reference failure: " + _TEST_CREDENTIAL
                ),
                lambda exc: api_errors.map_reference_error(
                    typ.cast("ReferenceDocumentError", exc),
                    context="reference-document",
                ),
                (
                    "Unmapped reference error: "
                    "context=reference-document type=_UnexpectedReferenceDocumentError"
                ),
            ),
            id="reference",
        ),
        pytest.param(
            _UnmappedMapperCase(
                _UnexpectedSourceIntakeError(
                    "Unexpected source-intake failure: " + _TEST_CREDENTIAL
                ),
                lambda exc: api_errors.map_source_intake_error(
                    typ.cast("SourceIntakeError", exc),
                ),
                "Unmapped source-intake error: type=_UnexpectedSourceIntakeError",
            ),
            id="source-intake",
        ),
    ],
)
def test_unmapped_error_mappers_log_and_return_internal_error(
    case: _UnmappedMapperCase,
    spy_logger: SpyLogger,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
) -> None:
    """Mappers attach diagnostics for the central serializer to emit."""

    def raise_case_exception() -> None:
        _raise_with_credential_cause(case.exception)

    with caplog.at_level(logging.ERROR):
        try:
            raise_case_exception()
        except (
            ProfileTemplateError,
            ReferenceDocumentError,
            SourceIntakeError,
        ) as raised:
            result = case.mapper(raised)

    assert caplog.records == [], "mappers must not emit log records"

    assert isinstance(result, falcon.HTTPInternalServerError), (
        "unmapped domain errors must return HTTP 500"
    )
    assert _envelope_code(result) == "internal_error", (
        "unmapped domain errors must use the internal-error envelope"
    )
    assert spy_logger.calls == [], "mappers must not emit logs"
    response = falcon.Response()
    api_errors.serialize_http_error(
        falcon_testing.create_req(),
        response,
        result,
        emit_error=partial(log_error, spy_logger),
    )
    _assert_spy_logger_call(spy_logger, case.exception, case.expected_message)
    _assert_detached_exception_info_logged(caplog, case.exception)
    assert (
        _stable_mapper_snapshot(
            case,
            result,
            spy_logger.calls[0],
        )
        == snapshot
    ), "stable unmapped-mapper diagnostics must match the snapshot"


def test_unmapped_profile_error_response_redacts_exception_text(
    spy_logger: SpyLogger,
    caplog: pytest.LogCaptureFixture,
    snapshot: SnapshotAssertion,
) -> None:
    """An unmapped profile error must not expose its message to clients."""
    exc = _UnexpectedProfileTemplateError(
        "Unexpected profile/template failure: " + _TEST_CREDENTIAL,
        code="internal_error",
    )

    with caplog.at_level(logging.ERROR):
        try:
            raise exc
        except ProfileTemplateError as raised:
            mapped_error = api_errors.map_profile_template_error(raised)

    assert caplog.records == [], "mappers must not emit log records"
    assert spy_logger.calls == [], "mappers must not emit logs"

    response = falcon.Response()
    api_errors.serialize_http_error(
        falcon_testing.create_req(),
        response,
        mapped_error,
        emit_error=partial(log_error, spy_logger),
    )

    assert response.media == {
        "code": "internal_error",
        "message": "Unexpected profile/template error.",
        "details": {},
    }, "unmapped profile errors must use a generic client response"
    assert _TEST_CREDENTIAL not in str(response.media), (
        "serialized responses must not expose credential-like exception text"
    )
    assert len(spy_logger.calls) == 1, "unmapped errors must log once"
    stable_response = {
        "status": mapped_error.status,
        "envelope": response.media,
    }
    assert stable_response == snapshot, (
        "the generic profile error response must match the stable snapshot"
    )
