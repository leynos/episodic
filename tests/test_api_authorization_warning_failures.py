"""Authorization logging failures must preserve canonical responses."""

import sys
import typing as typ
from unittest import mock

import pytest

from tests.fixtures.authorization import (
    DenyAllAuthorization,
    ForbidSeriesProfilesAuthorization,
    RaisingAuthorization,
    build_authorization_test_client,
    patch_authorization_warning_backend,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.authorization import AuthorizationPort


@pytest.fixture
def authorization_warning_backend(monkeypatch: pytest.MonkeyPatch) -> mock.Mock:
    """Capture authorization warnings through a mocked logger backend."""
    return patch_authorization_warning_backend(monkeypatch)


class _WarningFailureCase(typ.NamedTuple):
    """Expected response for one authorization warning failure path."""

    authorization: AuthorizationPort
    metrics_error: type[Exception] | None
    status: int
    code: str
    message: str
    warning_calls: int


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
            ),
            id="metric-and-adapter-warnings-fail",
        ),
        pytest.param(
            _WarningFailureCase(
                DenyAllAuthorization(),
                None,
                401,
                "unauthorized",
                "Authorization is required.",
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
            ),
            id="forbidden-warning-fails",
        ),
    ],
)
def test_warning_failures_do_not_interrupt_authorization_response(
    session_factory: async_sessionmaker[AsyncSession],
    authorization_warning_backend: mock.Mock,
    case: _WarningFailureCase,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Logging errors cannot replace the canonical authorization response."""
    authorization_warning_backend.warning.side_effect = RuntimeError(
        "warning backend unavailable"
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
    assert authorization_warning_backend.warning.call_count == case.warning_calls, (
        "warning attempts must match the authorization failure path"
    )
    assert metrics.increment_counter.call_count == int(case.status == 503), (
        "adapter failures must attempt their metric exactly once"
    )
    assert "Bearer sensitive-token" not in repr(
        authorization_warning_backend.warning.call_args_list,
    ), "authorization credentials must not reach a failed warning backend"
    fallback_lines = capsys.readouterr().err.splitlines()
    assert (
        fallback_lines
        == ["Authorization warning sink failed; request details omitted."]
        * case.warning_calls
    ), "logger failures must use one fixed, credential-free signal"


class _UnavailableStandardError:
    """Represent a stderr stream that cannot deliver the fallback signal."""

    def __init__(self) -> None:
        """Initialize the attempted fallback messages."""
        self.messages: list[str] = []

    def write(self, message: str) -> int:
        """Record the fixed signal before reporting an unavailable stream."""
        self.messages.append(message)
        msg = "stderr unavailable"
        raise OSError(msg)

    def flush(self) -> None:
        """Report that the fallback stream cannot be flushed."""
        msg = "stderr unavailable"
        raise OSError(msg)


def test_unavailable_warning_fallback_preserves_unauthorized_response(
    session_factory: async_sessionmaker[AsyncSession],
    authorization_warning_backend: mock.Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the canonical response when both warning and fallback sinks fail."""
    authorization_warning_backend.warning.side_effect = RuntimeError(
        "warning backend unavailable"
    )
    fallback_stream = _UnavailableStandardError()
    monkeypatch.setattr(sys, "stderr", fallback_stream)
    client = build_authorization_test_client(
        session_factory,
        DenyAllAuthorization(),
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
