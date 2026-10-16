"""Verify sensitive profile/template log metadata is redacted."""

import traceback
import typing as typ
from unittest import mock

import falcon
from falcon import testing as falcon_testing
from hypothesis import given, settings
from hypothesis import strategies as st

from episodic.api import errors as api_errors
from episodic.canonical.profile_templates.types import ProfileTemplateError

_TEST_CREDENTIAL = "test-only-secret-marker"
_TEST_CAUSE_CREDENTIAL = "test-only-cause-secret-marker"

if typ.TYPE_CHECKING:
    import types

    from tests.fixtures.api_errors import SpyLogger


class _CredentialCodedProfileTemplateError(ProfileTemplateError):
    """Represent a subclass whose declared code must not enter error logs."""

    error_code: typ.ClassVar[str] = _TEST_CREDENTIAL


class _HasEnvelopeCode(typ.Protocol):
    """Describe the error metadata attached by the API mapper."""

    envelope_code: str


def test_profile_template_error_redacts_credential_metadata(
    spy_logger: SpyLogger,
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
    }, "unmapped error metadata must not be exposed to API clients"
    assert _TEST_CREDENTIAL not in str(response.media), (
        "responses must omit credential-like error codes"
    )
    assert _TEST_CAUSE_CREDENTIAL not in str(response.media), (
        "responses must omit credential-like entity IDs"
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
    spy_logger: SpyLogger,
) -> None:
    """Deep tracebacks retain the raise site and mark omitted outer frames."""
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
    assert frame_labels[0] == "...", "logs must mark omitted outer frames"
    innermost_frame_function = frame_labels[-1].split(":", maxsplit=2)[1]
    assert innermost_frame_function == "_raise_profile_template_error", (
        "logs must retain the innermost source frame where the exception was raised"
    )


@settings(max_examples=30)
@given(
    secret=st.text(min_size=1),
    has_traceback=st.booleans(),
    has_cause=st.booleans(),
    exception_type=st.sampled_from((
        ProfileTemplateError,
        _CredentialCodedProfileTemplateError,
    )),
)
def test_profile_error_logging_redacts_generated_untrusted_values(
    secret: str,
    *,
    has_traceback: bool,
    has_cause: bool,
    exception_type: type[ProfileTemplateError],
) -> None:
    """Arbitrary source strings never enter detached mapper diagnostics."""
    credential = "credential-marker:" + secret
    exc = exception_type(
        "exception message:" + credential,
        code=credential,
        entity_id=credential,
    )
    if has_cause:
        exc.__cause__ = RuntimeError("chained cause:" + credential)

    spy = mock.Mock()
    with mock.patch.object(api_errors, "logger", spy):
        if has_traceback:
            try:
                raise exc
            except ProfileTemplateError as raised:
                mapped_error = api_errors.map_profile_template_error(raised)
        else:
            mapped_error = api_errors.map_profile_template_error(exc)

    assert isinstance(mapped_error, falcon.HTTPInternalServerError), (
        "unmapped profile errors must return HTTP 500"
    )
    assert spy.error.call_count == 1, "unmapped profile errors must emit one ERROR log"
    logged_message = typ.cast("str", spy.error.call_args.args[0])
    assert credential not in logged_message, "metadata values must be redacted"
    logged_exc_info = typ.cast(
        "tuple[type[BaseException], BaseException, types.TracebackType | None]",
        spy.error.call_args.kwargs["exc_info"],
    )
    formatted_traceback = "".join(traceback.format_exception(*logged_exc_info))
    assert credential not in formatted_traceback, (
        "exception messages and causes must be redacted"
    )
    assert logged_exc_info[1] is not exc, "logs must not retain the source exception"
    assert logged_exc_info[2] is None, "logs must not retain source traceback frames"
    assert logged_exc_info[1].__cause__ is None, (
        "logs must omit source exception causes"
    )
    assert logged_exc_info[1].__context__ is None, (
        "logs must omit implicit exception context"
    )
    if not has_traceback:
        assert "Source frames: unavailable" in formatted_traceback, (
            "errors without tracebacks must be reported without fabricated frames"
        )
