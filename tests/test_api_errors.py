"""Verify diagnostics for API errors that lack dedicated HTTP mappings.

The examples isolate each mapper's unexpected-exception branch, confirming that
it preserves the internal-error envelope and emits one error record with
detached exception information through the logging port.
"""

import asyncio
import dataclasses as dc
import logging
import traceback
import typing as typ
import uuid

import falcon
import pytest
from falcon import testing as falcon_testing

from episodic.api import errors as api_errors
from episodic.api.handlers import handle_get_entity
from episodic.canonical.profile_templates.types import ProfileTemplateError
from episodic.canonical.reference_documents.types import ReferenceDocumentError
from episodic.canonical.source_intake_errors import SourceIntakeError
from tests.fixtures.api_errors import API_ERROR_TEST_LOGGER_NAME as _TEST_LOGGER_NAME

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from tests.fixtures.api_errors import EmptyUnitOfWorkFactory, SpyLogger

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
        "the mapper must log one ERROR with its safe metadata"
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
                    typ.cast("ProfileTemplateError", exc)
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
                    typ.cast("SourceIntakeError", exc)
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
) -> None:
    """Each unmapped mapper preserves its envelope and logs detached error info."""

    def raise_case_exception() -> None:
        _raise_with_credential_cause(case.exception)

    with caplog.at_level(logging.ERROR, logger=_TEST_LOGGER_NAME):
        try:
            raise_case_exception()
        except (
            ProfileTemplateError,
            ReferenceDocumentError,
            SourceIntakeError,
        ) as raised:
            result = case.mapper(raised)

    assert isinstance(result, falcon.HTTPInternalServerError), (
        "unmapped domain errors must return HTTP 500"
    )
    assert _envelope_code(result) == "internal_error", (
        "unmapped domain errors must use the internal-error envelope"
    )
    _assert_spy_logger_call(spy_logger, case.exception, case.expected_message)
    _assert_detached_exception_info_logged(caplog, case.exception)


def test_unmapped_profile_error_response_redacts_exception_text(
    spy_logger: SpyLogger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unmapped profile error must not expose its message to clients."""
    exc = _UnexpectedProfileTemplateError(
        "Unexpected profile/template failure: " + _TEST_CREDENTIAL,
        code="internal_error",
    )

    with caplog.at_level(logging.ERROR, logger=_TEST_LOGGER_NAME):
        try:
            raise exc
        except ProfileTemplateError as raised:
            mapped_error = api_errors.map_profile_template_error(raised)

    response = falcon.Response()
    api_errors.serialize_http_error(
        falcon_testing.create_req(),
        response,
        mapped_error,
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


def test_shared_profile_handler_maps_unmapped_service_error(
    spy_logger: SpyLogger,
    empty_uow_factory: EmptyUnitOfWorkFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unmapped service errors reach the shared mapper with detached error info."""
    entity_id = uuid.uuid4()
    exc = _UnexpectedProfileTemplateError(
        "Unexpected profile/template service failure: " + _TEST_CREDENTIAL,
        code="internal_error",
    )

    async def fail_service(
        _uow: object,
        *,
        entity_id: uuid.UUID,
    ) -> tuple[object, int]:
        del entity_id
        await asyncio.sleep(0)
        raise exc

    def serialize(_entity: object, _revision: int) -> dict[str, object]:
        raise AssertionError

    with (
        caplog.at_level(logging.ERROR, logger=_TEST_LOGGER_NAME),
        pytest.raises(falcon.HTTPInternalServerError) as mapped_error,
    ):
        asyncio.run(
            handle_get_entity(
                empty_uow_factory,
                str(entity_id),
                "profile_id",
                fail_service,
                serialize,
            )
        )

    assert _envelope_code(mapped_error.value) == "internal_error", (
        "unmapped profile service errors must use the internal-error envelope"
    )
    assert _envelope_details(mapped_error.value) == {}, (
        "unmapped profile errors must not expose entity metadata in the envelope"
    )
    _assert_spy_logger_call(
        spy_logger,
        exc,
        (
            "Unmapped profile/template error: "
            "type=_UnexpectedProfileTemplateError code=internal_error "
            f"entity_id={entity_id}"
        ),
    )
    _assert_detached_exception_info_logged(caplog, exc)
