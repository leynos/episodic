"""Authorization adapters and client builders for API tests."""

from __future__ import annotations

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

    def __init__(self, error_type: type[Exception] = RuntimeError) -> None:
        """Set the adapter failure type used by the request tests."""
        self._error_type = error_type

    async def decide(self, context: AuthorizationContext) -> AuthorizationDecision:
        """Raise instead of returning a decision."""
        del context
        msg = "authorization backend unavailable"
        raise self._error_type(msg)


def build_authorization_test_client(
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
