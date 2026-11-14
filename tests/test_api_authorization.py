"""Authorization middleware tests for canonical REST endpoints."""

import dataclasses as dc
import typing as typ
from unittest import mock

import pytest
from falcon import testing

from episodic import logging as episodic_logging
from episodic.api import create_app
from episodic.api.authorization import (
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationPort,
    AuthorizationResult,
    StaticBearerTokenAuthorization,
)
from tests.fixtures.api import build_api_dependencies
from tests.fixtures.authorization import (
    AuthorizationWarningLogger,
    DenyAllAuthorization,
    ForbidSeriesProfilesAuthorization,
    RaisingAuthorization,
    build_authorization_test_client,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer configured-token", AuthorizationDecision.PERMIT),
        ("bearer configured-token", AuthorizationDecision.PERMIT),
        ("BEARER configured-token", AuthorizationDecision.PERMIT),
        ("Basic configured-token", AuthorizationDecision.UNAUTHORIZED),
        ("Bearer", AuthorizationDecision.UNAUTHORIZED),
        ("Bearer wrong-token", AuthorizationDecision.UNAUTHORIZED),
        (None, AuthorizationDecision.UNAUTHORIZED),
    ],
)
async def test_static_bearer_authorization_parses_scheme_and_token(
    header: str | None,
    expected: AuthorizationDecision,
) -> None:
    """Accept case-insensitive Bearer schemes and reject malformed credentials."""
    configured_credential = "".join(("configured", "-token"))
    authorization = StaticBearerTokenAuthorization(
        token=configured_credential,
        principal_id="configured-principal",
    )

    result = await authorization.decide(
        AuthorizationContext(
            method="GET", path="/v1/example", authorization_header=header
        )
    )

    assert isinstance(result, AuthorizationResult), result
    assert result.decision is expected, result
    if expected is AuthorizationDecision.PERMIT:
        assert result.principal_id == "configured-principal", result
    else:
        assert result.principal_id is None, result


def test_default_authorization_permits_v1_without_header(
    canonical_api_client: testing.TestClient,
) -> None:
    """Default permit-all authorization preserves unauthenticated responses."""
    response = canonical_api_client.simulate_get("/v1/series-profiles")

    assert response.status_code == 200, (
        "Expected default authorization to permit unauthenticated /v1 requests."
    )


@pytest.mark.parametrize(
    ("adapter_factory", "expected_status", "expected_payload"),
    [
        (
            DenyAllAuthorization,
            401,
            {
                "code": "unauthorized",
                "message": "Authorization is required.",
                "details": {},
            },
        ),
        (
            ForbidSeriesProfilesAuthorization,
            403,
            {
                "code": "forbidden",
                "message": "Access to this resource is forbidden.",
                "details": {},
            },
        ),
        (
            RaisingAuthorization,
            503,
            {
                "code": "service_unavailable",
                "message": "Authorization service is unavailable.",
                "details": {},
            },
        ),
    ],
    ids=["unauthorized", "forbidden", "service_unavailable"],
)
def test_authorization_decision_serializes_to_canonical_envelope(
    session_factory: async_sessionmaker[AsyncSession],
    adapter_factory: type[AuthorizationPort],
    expected_status: int,
    expected_payload: dict[str, object],
) -> None:
    """Each non-permit decision returns the matching error envelope."""
    client = build_authorization_test_client(session_factory, adapter_factory())

    response = client.simulate_get("/v1/series-profiles")

    assert response.status_code == expected_status, (
        f"Expected HTTP {expected_status} for "
        f"{adapter_factory.__name__}; got {response.status_code}."
    )
    payload = typ.cast("dict[str, object]", response.json)
    assert payload == expected_payload, (
        f"Expected envelope {expected_payload} for "
        f"{adapter_factory.__name__}; got {payload}."
    )


@dc.dataclass(frozen=True, slots=True)
class _DefaultObserverCase:
    """Expected output from a default-observer integration case."""

    authorization: AuthorizationPort
    expected_status: int
    expected_warning: str
    failure_category: str | None


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _DefaultObserverCase(
                DenyAllAuthorization(),
                401,
                "Authorization denied with unauthorized for GET /v1/series-profiles.",
                None,
            ),
            id="default-observer-denial",
        ),
        pytest.param(
            _DefaultObserverCase(
                RaisingAuthorization(),
                503,
                "Authorization adapter failed with runtime_error for GET "
                "/v1/series-profiles.",
                "runtime_error",
            ),
            id="default-observer-adapter-failure",
        ),
    ],
)
def test_create_app_wires_default_authorization_observer(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    case: _DefaultObserverCase,
) -> None:
    """The composition root sends default observer output to configured ports."""
    warning_logger = AuthorizationWarningLogger()
    logger_handle = episodic_logging.LoggerHandle(
        typ.cast("episodic_logging._CompatibleLogger", warning_logger)
    )

    def get_authorization_logger(name: str) -> episodic_logging.LoggerHandle:
        """Return the test backend for the expected production logger name."""
        assert name == "episodic.api.authorization", (
            "The default observer should use the authorization logger name."
        )
        return logger_handle

    monkeypatch.setattr("episodic.api.app.get_logger", get_authorization_logger)
    metrics = mock.Mock()
    dependencies = dc.replace(
        build_api_dependencies(session_factory, authorization=case.authorization),
        metrics=metrics,
    )
    client = testing.TestClient(create_app(dependencies))

    response = client.simulate_get(
        "/v1/series-profiles",
        headers={"Authorization": "Bearer sensitive-token"},
    )

    assert response.status_code == case.expected_status, response.status_code
    assert warning_logger.warning_calls == [(case.expected_warning, None, False)], (
        "The default observer should emit the expected warning through the port."
    )
    assert "sensitive-token" not in repr(warning_logger.warning_calls), (
        "Authorization credentials must not appear in warning records."
    )
    if case.failure_category is None:
        metrics.increment_counter.assert_not_called()
    else:
        metrics.increment_counter.assert_called_once_with(
            "authorization_adapter_failure_total",
            labels={"category": case.failure_category},
        )


@pytest.mark.parametrize(
    "exception_type",
    [
        AttributeError,
        AssertionError,
        IndexError,
        KeyError,
        LookupError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ],
    ids=[
        "attribute-error",
        "assertion-error",
        "index-error",
        "key-error",
        "lookup-error",
        "os-error",
        "runtime-error",
        "type-error",
        "value-error",
    ],
)
def test_authorization_adapter_failure_types_return_service_unavailable(
    session_factory: async_sessionmaker[AsyncSession],
    exception_type: type[Exception],
) -> None:
    """Every handled adapter failure returns the canonical 503 envelope."""
    client = build_authorization_test_client(
        session_factory,
        RaisingAuthorization(error_type=exception_type),
    )

    response = client.simulate_get("/v1/series-profiles")

    assert response.status_code == 503, response.status_code
    payload = typ.cast("dict[str, object]", response.json)
    assert payload == {
        "code": "service_unavailable",
        "message": "Authorization service is unavailable.",
        "details": {},
    }, payload


def test_non_v1_paths_bypass_authorization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Non-`/v1` operator endpoints bypass API authorization."""
    client = build_authorization_test_client(session_factory, DenyAllAuthorization())

    response = client.simulate_get("/health/live")

    assert response.status_code == 200, (
        "Expected liveness endpoint to bypass authorization middleware."
    )
