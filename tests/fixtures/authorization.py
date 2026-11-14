"""Authorization adapters and client builders for API tests."""

import dataclasses as dc
import logging
import typing as typ

from falcon import testing

from episodic import logging as episodic_logging
from episodic.api import create_app
from episodic.api.authorization import (
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationPort,
)
from episodic.api.authorization_observability import AuthorizationObserver
from tests.fixtures.api import build_api_dependencies

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.observability import MetricsPort


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


class AuthorizationWarningLogger:
    """Capture injected warning calls using the logging-port method contract."""

    def __init__(self) -> None:
        """Initialize the warning-call recorder."""
        self.warning_calls: list[tuple[str, object | None, bool]] = []
        self.warning_failure: Exception | None = None

    def log(
        self,
        level: int | str,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record warning-level calls through the generic logging port."""
        if level not in {logging.WARNING, episodic_logging.LogLevel.WARNING}:
            return
        self.warning_calls.append((message, exc_info, stack_info))
        if self.warning_failure is not None:
            raise self.warning_failure


def make_authorization_warning_backend() -> AuthorizationWarningLogger:
    """Return an explicit fake logger for authorization observer tests."""
    return AuthorizationWarningLogger()


def build_authorization_observer(
    warning_logger: object,
    metrics: MetricsPort | None = None,
) -> AuthorizationObserver:
    """Build an observer with injected fake logging and optional metrics."""
    logger = episodic_logging.LoggerHandle(
        typ.cast("episodic_logging._CompatibleLogger", warning_logger)
    )
    return AuthorizationObserver(logger, metrics)


def build_authorization_test_client(
    session_factory: async_sessionmaker[AsyncSession],
    authorization: AuthorizationPort,
    *,
    metrics: MetricsPort | None = None,
    warning_logger: object | None = None,
) -> testing.TestClient:
    """Build a canonical API client with an authorization adapter.

    Parameters
    ----------
    session_factory : async_sessionmaker[AsyncSession]
        Session factory wired into the API dependencies.
    authorization : AuthorizationPort
        Adapter used to decide requests to protected endpoints.
    metrics : MetricsPort or None, optional
        Metrics sink used by the authorization middleware.
    warning_logger : object | None, optional
        Fake logger injected into the authorization observer for assertions.

    Returns
    -------
    testing.TestClient
        Client configured with the supplied authorization adapter.
    """
    dependencies = build_api_dependencies(
        session_factory,
        authorization=authorization,
    )
    if metrics is not None:
        dependencies = dc.replace(dependencies, metrics=metrics)
    observer = (
        None
        if warning_logger is None
        else build_authorization_observer(warning_logger, dependencies.metrics)
    )
    return testing.TestClient(create_app(dependencies, authorization_observer=observer))
