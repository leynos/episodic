"""Authorization logging failures must preserve canonical responses."""

import sys
import typing as typ
from unittest import mock

import pytest
from falcon import testing

from episodic.api import create_app
from tests.fixtures.api import build_api_dependencies
from tests.fixtures.authorization import (
    AuthorizationWarningLogger,
    DenyAllAuthorization,
    ForbidSeriesProfilesAuthorization,
    RaisingAuthorization,
    build_authorization_test_client,
    make_authorization_warning_backend,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.authorization import (
        AuthorizationContext,
        AuthorizationDecision,
        AuthorizationPort,
    )


@pytest.fixture
def authorization_warning_backend() -> AuthorizationWarningLogger:
    """Capture authorization warnings through an injected fake logger."""
    return make_authorization_warning_backend()


class _WarningFailureCase(typ.NamedTuple):
    """Expected response for one authorization warning failure path."""

    authorization: AuthorizationPort
    metrics_error: type[Exception] | None
    status: int
    code: str
    message: str
    warning_calls: int
    fallback_calls: int
    warning_error: type[Exception] | None = RuntimeError


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _WarningFailureCase(
                RaisingAuthorization(),
                None,
                503,
                "service_unavailable",
                "Authorization service is unavailable.",
                1,
                1,
            ),
            id="adapter-warning-fails",
        ),
        pytest.param(
            _WarningFailureCase(
                RaisingAuthorization(),
                RuntimeError,
                503,
                "service_unavailable",
                "Authorization service is unavailable.",
                2,
                2,
            ),
            id="metric-and-adapter-warnings-fail",
        ),
        pytest.param(
            _WarningFailureCase(
                RaisingAuthorization(),
                KeyError,
                503,
                "service_unavailable",
                "Authorization service is unavailable.",
                2,
                0,
                None,
            ),
            id="key-error-from-metrics-sink",
        ),
        pytest.param(
            _WarningFailureCase(
                RaisingAuthorization(),
                IndexError,
                503,
                "service_unavailable",
                "Authorization service is unavailable.",
                2,
                0,
                None,
            ),
            id="index-error-from-metrics-sink",
        ),
        pytest.param(
            _WarningFailureCase(
                DenyAllAuthorization(),
                None,
                401,
                "unauthorized",
                "Authorization is required.",
                1,
                1,
            ),
            id="unauthorized-warning-fails",
        ),
        pytest.param(
            _WarningFailureCase(
                ForbidSeriesProfilesAuthorization(),
                None,
                403,
                "forbidden",
                "Access to this resource is forbidden.",
                1,
                1,
            ),
            id="forbidden-warning-fails",
        ),
        pytest.param(
            _WarningFailureCase(
                DenyAllAuthorization(),
                None,
                401,
                "unauthorized",
                "Authorization is required.",
                1,
                1,
                KeyError,
            ),
            id="key-error-from-warning-sink",
        ),
        pytest.param(
            _WarningFailureCase(
                DenyAllAuthorization(),
                None,
                401,
                "unauthorized",
                "Authorization is required.",
                1,
                1,
                IndexError,
            ),
            id="index-error-from-warning-sink",
        ),
        pytest.param(
            _WarningFailureCase(
                RaisingAuthorization(),
                AssertionError,
                503,
                "service_unavailable",
                "Authorization service is unavailable.",
                0,
                1,
                None,
            ),
            id="unexpected-error-from-metrics-sink",
        ),
        pytest.param(
            _WarningFailureCase(
                DenyAllAuthorization(),
                None,
                401,
                "unauthorized",
                "Authorization is required.",
                1,
                1,
                AssertionError,
            ),
            id="unexpected-error-from-unauthorized-warning-sink",
        ),
        pytest.param(
            _WarningFailureCase(
                ForbidSeriesProfilesAuthorization(),
                None,
                403,
                "forbidden",
                "Access to this resource is forbidden.",
                1,
                1,
                AssertionError,
            ),
            id="unexpected-error-from-forbidden-warning-sink",
        ),
        pytest.param(
            _WarningFailureCase(
                RaisingAuthorization(),
                None,
                503,
                "service_unavailable",
                "Authorization service is unavailable.",
                1,
                1,
                AssertionError,
            ),
            id="unexpected-error-from-adapter-warning-sink",
        ),
    ],
)
def test_warning_failures_do_not_interrupt_authorization_response(
    session_factory: async_sessionmaker[AsyncSession],
    authorization_warning_backend: AuthorizationWarningLogger,
    case: _WarningFailureCase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Logging errors cannot replace the canonical authorization response."""
    authorization_warning_backend.warning_failure = (
        None
        if case.warning_error is None
        else case.warning_error("warning backend unavailable")
    )
    metrics = mock.Mock()
    if case.metrics_error is not None:
        metrics.increment_counter.side_effect = case.metrics_error(
            "metrics unavailable"
        )
    client = build_authorization_test_client(
        session_factory,
        case.authorization,
        metrics=metrics,
        warning_logger=authorization_warning_backend,
    )

    response = client.simulate_get(
        "/v1/series-profiles",
        headers={"Authorization": "Bearer sensitive-token"},
    )

    assert response.status_code == case.status, (
        "warning failures must preserve the canonical HTTP status"
    )
    assert response.json == {
        "code": case.code,
        "message": case.message,
        "details": {},
    }, "warning failures must preserve the canonical response envelope"
    assert len(authorization_warning_backend.warning_calls) == case.warning_calls, (
        "warning attempts must match the authorization failure path"
    )
    assert metrics.increment_counter.call_count == int(case.status == 503), (
        "adapter failures must attempt their metric exactly once"
    )
    assert "Bearer sensitive-token" not in repr(
        authorization_warning_backend.warning_calls,
    ), "authorization credentials must not reach a failed warning backend"
    fallback_lines = capsys.readouterr().err.splitlines()
    assert (
        fallback_lines
        == ["Authorization warning sink failed; request details omitted."]
        * case.fallback_calls
    ), "logger failures must use one fixed, credential-free signal"


class _UnavailableStandardError:
    """Represent a stderr stream that cannot deliver the fallback signal."""

    def __init__(self, error_type: type[Exception]) -> None:
        """Configure the error reported by this unavailable stream."""
        self._error_type = error_type
        self.messages: list[str] = []

    def write(self, message: str) -> int:
        """Record the fixed signal before reporting an unavailable stream."""
        self.messages.append(message)
        msg = "stderr unavailable"
        raise self._error_type(msg)

    def flush(self) -> None:
        """Report that the fallback stream cannot be flushed."""
        msg = "stderr unavailable"
        raise self._error_type(msg)


@pytest.mark.parametrize("error_type", [OSError, AssertionError])
def test_unavailable_warning_fallback_preserves_unauthorized_response(
    session_factory: async_sessionmaker[AsyncSession],
    authorization_warning_backend: AuthorizationWarningLogger,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    """Keep the canonical response when both warning and fallback sinks fail."""
    authorization_warning_backend.warning_failure = RuntimeError(
        "warning backend unavailable"
    )
    fallback_stream = _UnavailableStandardError(error_type)
    monkeypatch.setattr(sys, "stderr", fallback_stream)
    client = build_authorization_test_client(
        session_factory,
        DenyAllAuthorization(),
        warning_logger=authorization_warning_backend,
    )

    response = client.simulate_get(
        "/v1/series-profiles",
        headers={"Authorization": "Bearer sensitive-token"},
    )

    assert response.status_code == 401, (
        "an unavailable fallback must not replace the canonical HTTP status"
    )
    assert response.json == {
        "code": "unauthorized",
        "message": "Authorization is required.",
        "details": {},
    }, "an unavailable fallback must not replace the canonical response envelope"
    assert fallback_stream.messages == [
        "Authorization warning sink failed; request details omitted.\n"
    ], "the fallback may contain only its fixed signal"


class _CredentialBearingAuthorizationFailure:
    """Raise the supplied header to check the observer's privacy boundary."""

    async def decide(self, context: AuthorizationContext) -> AuthorizationDecision:
        """Raise an adapter error containing the request credential."""
        msg = context.authorization_header or "missing Authorization header"
        raise RuntimeError(msg)


class _RaisingAuthorizationObserver:
    """Observer test double that raises outside the built-in observer."""

    def record_authorization_outcome(
        self,
        outcome: object,
        *,
        method: str,
        path: str,
    ) -> None:
        """Raise a diagnostic failure while the middleware handles an error."""
        del outcome, method, path
        msg = "custom observer unavailable"
        raise AssertionError(msg)


def test_custom_observer_failure_preserves_response_and_hides_credentials(
    session_factory: async_sessionmaker[AsyncSession],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Keep adapter credentials out of output when an injected observer fails."""
    dependencies = build_api_dependencies(
        session_factory,
        authorization=_CredentialBearingAuthorizationFailure(),
    )
    client = testing.TestClient(
        create_app(
            dependencies,
            authorization_observer=_RaisingAuthorizationObserver(),
        )
    )

    response = client.simulate_get(
        "/v1/series-profiles",
        headers={"Authorization": "Bearer sensitive-token"},
    )

    assert response.status_code == 503, "observer errors must preserve HTTP 503"
    assert response.json == {
        "code": "service_unavailable",
        "message": "Authorization service is unavailable.",
        "details": {},
    }, "observer errors must preserve the canonical response envelope"
    assert "Bearer sensitive-token" not in response.text, (
        "the HTTP response must not disclose the adapter's credential"
    )
    diagnostics = capsys.readouterr().err
    assert (
        diagnostics == "Authorization warning sink failed; request details omitted.\n"
    ), "observer failures must emit only the fixed fallback marker"
    assert "Bearer sensitive-token" not in diagnostics, (
        "fallback diagnostics must not disclose the adapter's credential"
    )
    assert "Traceback" not in diagnostics, (
        "observer failures must not print the credential-bearing traceback"
    )
