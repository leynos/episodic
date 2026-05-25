"""Authorization middleware tests for canonical REST endpoints."""

import typing as typ

from falcon import testing

from episodic.api import create_app
from episodic.api.authorization import (
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationPort,
)
from tests.fixtures.api import build_api_dependencies

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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


def test_deny_all_authorization_returns_unauthorized_envelope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Deny-all authorization returns the canonical 401 envelope."""
    client = _build_client(session_factory, DenyAllAuthorization())

    response = client.simulate_get("/v1/series-profiles")

    assert response.status_code == 401, "Expected denied request to return HTTP 401."
    payload = typ.cast("dict[str, object]", response.json)
    assert payload == {
        "code": "unauthorized",
        "message": "Authorization is required.",
        "details": {},
    }


def test_non_v1_paths_bypass_authorization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Non-`/v1` operator endpoints bypass API authorization."""
    client = _build_client(session_factory, DenyAllAuthorization())

    response = client.simulate_get("/health/live")

    assert response.status_code == 200, (
        "Expected liveness endpoint to bypass authorization middleware."
    )


def test_forbidden_authorization_returns_forbidden_envelope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Forbidden authorization returns the canonical 403 envelope."""
    client = _build_client(session_factory, ForbidSeriesProfilesAuthorization())

    response = client.simulate_get("/v1/series-profiles")

    assert response.status_code == 403, "Expected forbidden request to return HTTP 403."
    payload = typ.cast("dict[str, object]", response.json)
    assert payload == {
        "code": "forbidden",
        "message": "Access to this resource is forbidden.",
        "details": {},
    }


def test_authorization_adapter_exception_returns_503(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Authorization adapter failures return the canonical 503 envelope."""
    client = _build_client(session_factory, RaisingAuthorization())

    response = client.simulate_get("/v1/series-profiles")

    assert response.status_code == 503, (
        "Expected authorization backend failure to return HTTP 503."
    )
    payload = typ.cast("dict[str, object]", response.json)
    assert payload == {
        "code": "service_unavailable",
        "message": "Authorization service is unavailable.",
        "details": {},
    }
