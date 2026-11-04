"""Authorization warning tests for redaction and log-safe paths."""

from __future__ import annotations

import time
import typing as typ
import unicodedata
from unittest import mock

import femtologging
import pytest

from episodic.api import authorization as authorization_module
from episodic import logging as episodic_logging
from tests.fixtures.authorization import (
    DenyAllAuthorization,
    ForbidSeriesProfilesAuthorization,
    RaisingAuthorization,
    build_authorization_test_client,
)

_LOG_ESCAPED_UNICODE_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.authorization import (
        AuthorizationContext,
        AuthorizationDecision,
        AuthorizationPort,
    )


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


@pytest.fixture
def authorization_log_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> cabc.Iterator[tuple[_SupportsFlushHandlers, _AuthorizationLogCollector]]:
    """Capture authorization warnings and reset the logging manager safely."""
    femtologging.reset_manager()
    backend = femtologging.getLogger("episodic.api.authorization")
    logger = episodic_logging.LoggerHandle(
        typ.cast("episodic_logging._CompatibleLogger", backend)
    )
    collector = _AuthorizationLogCollector()
    backend.clear_handlers()
    backend.set_propagate(False)
    backend.add_handler(collector)
    monkeypatch.setattr(authorization_module, "logger", logger)
    yield backend, collector
    femtologging.reset_manager()


class _AuthorizationHeaderFailure:
    """Authorization adapter that includes the request header in its error."""

    async def decide(self, context: AuthorizationContext) -> AuthorizationDecision:
        """Raise with the raw header to test the middleware logging boundary."""
        header = context.authorization_header
        raise RuntimeError(header if header is not None else "missing header")


class _AuthorizationLogCase(typ.NamedTuple):
    """Inputs and expected output for one authorization log assertion."""

    adapter_factory: type[AuthorizationPort]
    request_path: str
    expected_status: int
    expected_message: str
    authorization_header: str | None = "Bearer sensitive-token"


def test_authorization_adapter_failure_does_not_log_exception_metadata(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing adapter cannot leak its exception or the raw bearer header."""
    backend = mock.Mock()
    logger = episodic_logging.LoggerHandle(
        typ.cast("episodic_logging._CompatibleLogger", backend)
    )
    monkeypatch.setattr(authorization_module, "logger", logger)
    authorization_header = "Bearer sensitive-token"
    client = build_authorization_test_client(
        session_factory,
        _AuthorizationHeaderFailure(),
    )

    response = client.simulate_get(
        "/v1/series-profiles",
        headers={"Authorization": authorization_header},
    )

    assert response.status_code == 503, response.status_code
    backend.warning.assert_called_once_with(
        "Authorization adapter failed for GET /v1/series-profiles.",
        exc_info=None,
        stack_info=False,
    )
    assert authorization_header not in repr(backend.warning.call_args), (
        "authorization header must not reach the warning logger"
    )


@pytest.mark.parametrize(
    "case",
    [
        _AuthorizationLogCase(
            DenyAllAuthorization,
            "/v1/series-profiles",
            401,
            "Authorization denied with unauthorized for GET /v1/series-profiles.",
        ),
        _AuthorizationLogCase(
            ForbidSeriesProfilesAuthorization,
            "/v1/series-profiles",
            403,
            "Authorization denied with forbidden for GET /v1/series-profiles.",
        ),
        _AuthorizationLogCase(
            DenyAllAuthorization,
            "/v1/series-profiles/Bearer%20sensitive-path-token",
            401,
            "Authorization denied with unauthorized for GET /v1/series-profiles.",
            None,
        ),
        _AuthorizationLogCase(
            DenyAllAuthorization,
            "/v1/Bearer%20sensitive-path-token",
            401,
            "Authorization denied with unauthorized for GET /v1/<unknown>.",
            None,
        ),
        _AuthorizationLogCase(
            DenyAllAuthorization,
            "/v1/series-profiles%0Aforged",
            401,
            "Authorization denied with unauthorized for GET /v1/<unknown>.",
        ),
        _AuthorizationLogCase(
            RaisingAuthorization,
            "/v1/episode-templates/Bearer%20sensitive-path-token",
            503,
            "Authorization adapter failed for GET /v1/episode-templates.",
            None,
        ),
        _AuthorizationLogCase(
            RaisingAuthorization,
            "/v1/series-profiles%0Dforged",
            503,
            "Authorization adapter failed for GET /v1/<unknown>.",
        ),
    ],
    ids=[
        "unauthorized",
        "forbidden",
        "unauthorized-known-resource-path-token",
        "unauthorized-unknown-resource-path-token",
        "unauthorized-control-path",
        "adapter-error-known-resource-path-token",
        "adapter-error-control-path",
    ],
)
def test_authorization_logs_warning_without_credentials_or_unsafe_unicode(
    session_factory: async_sessionmaker[AsyncSession],
    authorization_log_collector: tuple[
        _SupportsFlushHandlers,
        _AuthorizationLogCollector,
    ],
    case: _AuthorizationLogCase,
) -> None:
    """Authorization warnings should be redacted and safe for log records."""
    backend, collector = authorization_log_collector
    client = build_authorization_test_client(
        session_factory,
        case.adapter_factory(),
    )
    response = client.simulate_get(
        case.request_path,
        headers=(
            {}
            if case.authorization_header is None
            else {"Authorization": case.authorization_header}
        ),
    )
    _wait_for_authorization_log(backend, collector)

    assert response.status_code == case.expected_status, response.status_code
    assert len(collector.records) == 1, collector.records
    logger_name, level, message = collector.records[0]
    assert logger_name == "episodic.api.authorization", logger_name
    assert level == "WARN", level
    assert message == case.expected_message, message
    assert all(
        unicodedata.category(char) not in _LOG_ESCAPED_UNICODE_CATEGORIES
        for char in message
    ), message
    assert "Bearer sensitive-token" not in message, message
    assert "sensitive-token" not in message, message
    assert "sensitive-path-token" not in message, message
