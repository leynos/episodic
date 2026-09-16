"""Verify diagnostics for API errors that lack dedicated HTTP mappings.

The examples isolate each mapper's unexpected-exception branch, confirming that
it preserves the internal-error envelope and emits one error record with
traceback information through the logging port.
"""

import dataclasses as dc
import typing as typ

import falcon
import pytest

from episodic.api import errors as api_errors
from episodic.canonical.profile_templates.types import ProfileTemplateError
from episodic.canonical.reference_documents.types import ReferenceDocumentError
from episodic.canonical.source_intake_errors import SourceIntakeError


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
        del stack_info
        self.calls.append(("ERROR", message, exc_info))


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


@pytest.fixture
def spy_logger(monkeypatch: pytest.MonkeyPatch) -> _SpyLogger:
    """Patch the API-error logger with an isolated call-recording spy."""
    spy = _SpyLogger()
    monkeypatch.setattr(api_errors, "logger", spy)
    return spy


class TestApiErrors:
    """Tests for unmapped API-error envelope diagnostics."""

    @staticmethod
    def test_unmapped_profile_template_error_logs_and_returns_internal_error(
        spy_logger: _SpyLogger,
    ) -> None:
        """Unmapped profile/template errors retain their code and emit diagnostics."""
        exc = _UnexpectedProfileTemplateError(
            "Unexpected profile/template failure.",
            code="internal_error",
            entity_id="template-7",
        )

        result = api_errors.map_profile_template_error(exc)

        assert isinstance(result, falcon.HTTPInternalServerError), (
            "unmapped profile/template errors must return HTTP 500"
        )
        assert _envelope_code(result) == "internal_error", (
            "unmapped profile/template errors must use the internal-error envelope"
        )
        assert _envelope_code(result) == exc.code, (
            "profile/template error envelopes must preserve the exception code"
        )
        assert spy_logger.calls == [
            (
                "ERROR",
                (
                    "Unmapped profile/template error: "
                    "type=_UnexpectedProfileTemplateError code=internal_error "
                    "entity_id=template-7"
                ),
                True,
            )
        ], "profile/template fallback must emit one diagnostic with traceback info"

    @staticmethod
    def test_unmapped_reference_error_logs_and_returns_internal_error(
        spy_logger: _SpyLogger,
    ) -> None:
        """Unmapped reference errors emit their context without response details."""
        exc = _UnexpectedReferenceDocumentError("Unexpected reference failure.")

        result = api_errors.map_reference_error(exc, context="reference-document")

        assert isinstance(result, falcon.HTTPInternalServerError), (
            "unmapped reference errors must return HTTP 500"
        )
        assert _envelope_code(result) == "internal_error", (
            "unmapped reference errors must use the internal-error envelope"
        )
        assert spy_logger.calls == [
            (
                "ERROR",
                (
                    "Unmapped reference error: "
                    "context=reference-document type=_UnexpectedReferenceDocumentError"
                ),
                True,
            )
        ], "reference fallback must emit one diagnostic with traceback info"

    @staticmethod
    def test_unmapped_source_intake_error_logs_and_returns_internal_error(
        spy_logger: _SpyLogger,
    ) -> None:
        """Unmapped source-intake errors emit diagnostics without credentials."""
        exc = _UnexpectedSourceIntakeError("Unexpected source-intake failure.")

        result = api_errors.map_source_intake_error(exc)

        assert isinstance(result, falcon.HTTPInternalServerError), (
            "unmapped source-intake errors must return HTTP 500"
        )
        assert _envelope_code(result) == "internal_error", (
            "unmapped source-intake errors must use the internal-error envelope"
        )
        assert spy_logger.calls == [
            (
                "ERROR",
                "Unmapped source-intake error: type=_UnexpectedSourceIntakeError",
                True,
            )
        ], "source-intake fallback must emit one diagnostic with traceback info"
