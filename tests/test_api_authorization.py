"""Authorization middleware tests for canonical REST endpoints."""

import time
import typing as typ

import pytest
from falcon import testing

from episodic.api import authorization as authorization_module
from episodic.api import create_app
from episodic.api.authorization import (
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationPort,
    AuthorizationResult,
    StaticBearerTokenAuthorization,
)
from tests.fixtures.api import build_api_dependencies

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _AuthorizationLogCollector:
    """Collect authorization log records through the femtologging protocol."""

    def __init__(self) -> None:
        """Initialise an empty authorization-record collection."""
        self.records: list[tuple[str, str, str]] = []

    def handle(self, logger_name: str, level: str, message: str) -> None:
        """Record one emitted authorization log message."""
        self.records.append((logger_name, level, message))


class _SupportsFlushHandlers(typ.Protocol):
    """Minimal logger protocol needed by the authorization log assertions."""

    def flush_handlers(self) -> None:
        """Flush pending log records through attached handlers."""


def _wait_for_authorization_log(
    logger: _SupportsFlushHandlers,
    collector: _AuthorizationLogCollector,
) -> None:
    """Flush handlers until the expected authorization record arrives."""
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        logger.flush_handlers()
        if collector.records:
            return
        time.sleep(0.01)
    logger.flush_handlers()


class DenyAllAuthorization:
    """Authorization adapter that rejects every request as unauthenticated."""

    async def decide(self, context: AuthorizationContext) -> AuthorizationDecision:
        """Return an unauthenticated decision for any context."""
        del context
        return AuthorizationDecision.UNAUTHORIZED


class ForbidSeriesProfilesAuthorization:
    """Authorization adapter that forbids the series-profile collection."""

    async def decide(self, context: AuthorizationContext) -> AuthorizationDecision:
        """Forbid the series-profile collection and permit other routes."""
        if context.path == "/v1/series-profiles":
            return AuthorizationDecision.FORBIDDEN
        return AuthorizationDecision.PERMIT


class RaisingAuthorization:
    """Authorization adapter that simulates an unavailable policy service."""

    async def decide(self, context: AuthorizationContext) -> AuthorizationDecision:
        """Raise instead of returning a decision."""
        del context
        msg = "authorization backend unavailable"
        raise RuntimeError(msg)


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


def _build_client(
    session_factory: async_sessionmaker[AsyncSession],
    authorization: AuthorizationPort,
) -> testing.TestClient:
    """Build a canonical API client with an authorization adapter."""
    return testing.TestClient(
        create_app(
            build_api_dependencies(
                session_factory,
                authorization=authorization,
            )
        )
    )


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
    client = _build_client(session_factory, adapter_factory())

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


@pytest.mark.parametrize(
    ("adapter_factory", "expected"),
    [
        (DenyAllAuthorization, (AuthorizationDecision.UNAUTHORIZED, 401)),
        (
            ForbidSeriesProfilesAuthorization,
            (AuthorizationDecision.FORBIDDEN, 403),
        ),
    ],
    ids=["unauthorized", "forbidden"],
)
def test_authorization_denials_log_warning_without_credentials(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    adapter_factory: type[AuthorizationPort],
    expected: tuple[AuthorizationDecision, int],
) -> None:
    """Unauthorized and forbidden responses should emit redacted warnings."""
    import femtologging

    expected_decision, expected_status = expected
    femtologging.reset_manager()
    logger = femtologging.getLogger("episodic.api.authorization")
    collector = _AuthorizationLogCollector()
    logger.clear_handlers()
    logger.set_propagate(False)
    logger.add_handler(collector)
    monkeypatch.setattr(authorization_module, "logger", logger)

    try:
        client = _build_client(session_factory, adapter_factory())
        response = client.simulate_get(
            "/v1/series-profiles",
            headers={"Authorization": "Bearer sensitive-token"},
        )
        _wait_for_authorization_log(logger, collector)
    finally:
        femtologging.reset_manager()

    assert response.status_code == expected_status, response.status_code
    assert len(collector.records) == 1, collector.records
    logger_name, level, message = collector.records[0]
    assert logger_name == "episodic.api.authorization", logger_name
    assert level == "WARN", level
    assert message == (
        f"Authorization denied with {expected_decision} for GET /v1/series-profiles."
    ), message
    assert "Bearer sensitive-token" not in message, message
    assert "sensitive-token" not in message, message


def test_non_v1_paths_bypass_authorization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Non-`/v1` operator endpoints bypass API authorization."""
    client = _build_client(session_factory, DenyAllAuthorization())

    response = client.simulate_get("/health/live")

    assert response.status_code == 200, (
        "Expected liveness endpoint to bypass authorization middleware."
    )
