"""Verify sensitive profile/template log metadata is redacted."""

import dataclasses as dc
import types
import typing as typ

import falcon
import pytest

from episodic.api import errors as api_errors
from episodic.canonical.profile_templates.types import ProfileTemplateError

_TEST_LOGGER_NAME = "test.episodic.api.errors"
_TEST_CREDENTIAL = "test-only-secret-marker"
_TEST_CAUSE_CREDENTIAL = "test-only-cause-secret-marker"
type _ExcInfo = (
    bool
    | tuple[type[BaseException], BaseException, types.TracebackType | None]
    | tuple[None, None, None]
    | BaseException
    | None
)


@dc.dataclass(slots=True)
class _SpyLogger:
    """Capture error records emitted through the logging port."""

    calls: list[tuple[str, str, _ExcInfo]] = dc.field(default_factory=list)

    def error(
        self,
        message: str,
        /,
        *,
        exc_info: _ExcInfo = None,
        stack_info: bool = False,
    ) -> None:
        """Record one error call."""
        del stack_info
        self.calls.append(("ERROR", message, exc_info))


class _CredentialCodedProfileTemplateError(ProfileTemplateError):
    """Represent a subclass whose declared code must not enter error logs."""

    error_code: typ.ClassVar[str] = _TEST_CREDENTIAL


class _HasEnvelopeCode(typ.Protocol):
    """Describe the error metadata attached by the API mapper."""

    envelope_code: str


@pytest.fixture
def spy_logger(monkeypatch: pytest.MonkeyPatch) -> _SpyLogger:
    """Patch the API-error logger with an isolated call-recording spy."""
    spy = _SpyLogger()
    monkeypatch.setattr(api_errors, "logger", spy)
    return spy


def test_profile_template_error_redacts_credential_metadata(
    spy_logger: _SpyLogger,
) -> None:
    """Credential-shaped codes and entity IDs never reach the error log."""
    exc = _CredentialCodedProfileTemplateError(
        "Unexpected profile/template failure: " + _TEST_CREDENTIAL,
        entity_id=_TEST_CAUSE_CREDENTIAL,
    )
    try:
        raise exc from RuntimeError(_TEST_CAUSE_CREDENTIAL)
    except ProfileTemplateError as raised:
        mapped_error = api_errors.map_profile_template_error(raised)

    assert isinstance(mapped_error, falcon.HTTPInternalServerError), (
        "unmapped profile/template errors must return HTTP 500"
    )
    assert (
        typ.cast("_HasEnvelopeCode", mapped_error).envelope_code == "internal_error"
    ), "unmapped profile/template errors must not expose an untrusted code"
    assert len(spy_logger.calls) == 1, "unmapped errors must log once"
    level, message, exc_info = spy_logger.calls[0]
    assert level == "ERROR", "unmapped errors must be logged at ERROR"
    assert message == (
        "Unmapped profile/template error: "
        "type=_CredentialCodedProfileTemplateError code=<redacted> "
        "entity_id=<redacted>"
    ), "untrusted profile metadata must be redacted from the log message"
    assert _TEST_CREDENTIAL not in message, "logs must omit credential-like codes"
    assert _TEST_CAUSE_CREDENTIAL not in message, (
        "logs must omit credential-like entity IDs"
    )
    assert isinstance(exc_info, tuple), (
        "error logs must include detached exception information"
    )
    assert len(exc_info) == 3, "detached exception information must be a triple"
    logged_exception = typ.cast("BaseException", exc_info[1])
    assert logged_exception is not exc, "logs must not retain the source exception"
    assert exc_info[2] is None, "logs must not retain source traceback frames"
    assert logged_exception.__cause__ is None, "logs must omit chained causes"
    assert logged_exception.__context__ is None, "logs must omit exception context"
    assert _TEST_CREDENTIAL not in str(logged_exception), (
        "logs must omit credential-like exception text"
    )
    assert _TEST_CAUSE_CREDENTIAL not in str(logged_exception), (
        "logs must omit credential-like chained exception text"
    )


def _raise_profile_template_error(
    remaining_frames: int,
    error: ProfileTemplateError,
) -> None:
    """Raise one profile error through a bounded recursive call chain."""
    if remaining_frames == 0:
        raise error
    _raise_profile_template_error(remaining_frames - 1, error)


def test_unmapped_error_bounds_logged_source_frames(
    spy_logger: _SpyLogger,
) -> None:
    """Deep tracebacks produce bounded frame metadata and an omission marker."""
    exc = ProfileTemplateError("Deep profile/template failure.")
    try:
        _raise_profile_template_error(30, exc)
    except ProfileTemplateError as raised:
        api_errors.map_profile_template_error(raised)

    exc_info = spy_logger.calls[0][2]
    assert isinstance(exc_info, tuple), "error logs must include exception info"
    logged_exception = typ.cast("BaseException", exc_info[1])
    frame_summary = str(logged_exception).partition("Source frames: ")[2]
    frame_labels = frame_summary.split(" <- ")
    assert len(frame_labels) == 21, "logs must cap source frames at 20 plus marker"
    assert frame_labels[-1] == "...", "logs must mark omitted source frames"
