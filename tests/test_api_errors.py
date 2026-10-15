"""Verify diagnostics for API errors that lack dedicated HTTP mappings.

The examples isolate each mapper's unexpected-exception branch, confirming that
it preserves the internal-error envelope and emits one error record with
traceback information through the logging port.
"""

import asyncio
import dataclasses as dc
import logging
import traceback
import typing as typ
import uuid

import falcon
import pytest

from episodic.api import errors as api_errors
from episodic.api.handlers import handle_get_entity
from episodic.canonical.profile_templates.types import ProfileTemplateError
from episodic.canonical.reference_documents.types import ReferenceDocumentError
from episodic.canonical.source_intake_errors import SourceIntakeError

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork

_TEST_LOGGER_NAME = "test.episodic.api.errors"


@dc.dataclass(slots=True)
class _SpyLogger:
    """Capture error records emitted through the logging port."""

    calls: list[tuple[str, str, object | None]] = dc.field(default_factory=list)

    def error(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record an error log call."""
        self.calls.append(("ERROR", message, exc_info))
        logging.getLogger(_TEST_LOGGER_NAME).error(
            message,
            exc_info=exc_info is True,
            stack_info=stack_info,
        )


class _UnexpectedProfileTemplateError(ProfileTemplateError):
    """Represent a profile/template error without a dedicated HTTP mapping."""


class _UnexpectedReferenceDocumentError(ReferenceDocumentError):
    """Represent a reference error without a dedicated HTTP mapping."""


class _UnexpectedSourceIntakeError(SourceIntakeError):
    """Represent a source-intake error without a dedicated HTTP mapping."""


class _HasEnvelopeCode(typ.Protocol):
    """Describe the dynamic envelope metadata added to Falcon errors."""

    envelope_code: str


def _envelope_code(error: falcon.HTTPError) -> str:
    """Return the dynamic error-envelope code attached by ``http_error``."""
    return typ.cast("_HasEnvelopeCode", error).envelope_code


def _assert_traceback_was_logged(
    caplog: pytest.LogCaptureFixture,
    exc: Exception,
) -> None:
    """Verify the emitted Python log record contains the active exception."""
    records = [record for record in caplog.records if record.name == _TEST_LOGGER_NAME]
    assert len(records) == 1, "each unmapped error must emit one log record"
    record = records[0]
    assert record.exc_info is not None, "error log must include exception information"
    assert record.exc_info[1] is exc, "error log must capture the mapped exception"
    assert record.exc_info[2] is not None, "error log must include a traceback"
    formatted_traceback = "".join(traceback.format_exception(*record.exc_info))
    assert type(exc).__name__ in formatted_traceback, (
        "logged traceback must identify the exception type"
    )
    assert str(exc) in formatted_traceback, (
        "logged traceback must include the exception message"
    )


@dc.dataclass(frozen=True, slots=True)
class _UnmappedMapperCase:
    """Describe one error mapper's unmapped fallback contract."""

    exception: Exception
    mapper: cabc.Callable[[Exception], falcon.HTTPError]
    expected_message: str


class _EmptyUnitOfWork:
    """Provide a minimal unit-of-work context for handler tests."""

    async def __aenter__(self) -> CanonicalUnitOfWork:
        """Enter the test context."""
        return typ.cast("CanonicalUnitOfWork", self)

    async def __aexit__(
        self,
        _exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> None:
        """Exit the test context without handling service exceptions."""


def _empty_uow_factory() -> CanonicalUnitOfWork:
    """Create the minimal context used by the shared-handler regression."""
    return typ.cast("CanonicalUnitOfWork", _EmptyUnitOfWork())


@pytest.fixture
def spy_logger(monkeypatch: pytest.MonkeyPatch) -> _SpyLogger:
    """Patch the API-error logger with an isolated call-recording spy."""
    spy = _SpyLogger()
    monkeypatch.setattr(api_errors, "logger", spy)
    return spy


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _UnmappedMapperCase(
                _UnexpectedProfileTemplateError(
                    "Unexpected profile/template failure.",
                    code="internal_error",
                    entity_id="template-7",
                ),
                lambda exc: api_errors.map_profile_template_error(
                    typ.cast("ProfileTemplateError", exc)
                ),
                (
                    "Unmapped profile/template error: "
                    "type=_UnexpectedProfileTemplateError code=internal_error "
                    "entity_id=template-7"
                ),
            ),
            id="profile-template",
        ),
        pytest.param(
            _UnmappedMapperCase(
                _UnexpectedReferenceDocumentError("Unexpected reference failure."),
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
                _UnexpectedSourceIntakeError("Unexpected source-intake failure."),
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
    spy_logger: _SpyLogger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Each unmapped mapper preserves its envelope and logs the traceback."""

    def raise_case_exception() -> None:
        raise case.exception

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
    if isinstance(case.exception, ProfileTemplateError):
        assert _envelope_code(result) == case.exception.code, (
            "profile/template error envelopes must preserve the exception code"
        )
    assert spy_logger.calls == [("ERROR", case.expected_message, True)], (
        "each mapper must emit one traceback-enabled diagnostic"
    )
    _assert_traceback_was_logged(caplog, case.exception)


def test_shared_profile_handler_maps_unmapped_service_error(
    spy_logger: _SpyLogger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unmapped service errors reach the shared mapper with a traceback."""
    entity_id = uuid.uuid4()
    exc = _UnexpectedProfileTemplateError(
        "Unexpected profile/template service failure.",
        code="internal_error",
        entity_id=str(entity_id),
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
                _empty_uow_factory,
                str(entity_id),
                "profile_id",
                fail_service,
                serialize,
            )
        )

    assert _envelope_code(mapped_error.value) == "internal_error", (
        "unmapped profile service errors must use the internal-error envelope"
    )
    assert spy_logger.calls == [
        (
            "ERROR",
            (
                "Unmapped profile/template error: "
                "type=_UnexpectedProfileTemplateError code=internal_error "
                f"entity_id={entity_id}"
            ),
            True,
        )
    ], "the shared handler must emit one traceback-enabled fallback log"
    _assert_traceback_was_logged(caplog, exc)
