"""Authorization logging failures must preserve canonical responses."""

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
    assert "Bearer sensitive-token" not in repr(
        authorization_warning_backend.warning.call_args_list,
    ), "authorization credentials must not reach a failed warning backend"
