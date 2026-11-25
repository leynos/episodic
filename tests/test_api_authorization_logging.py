"""Authorization warning tests for redaction and log-safe paths."""

import logging
import typing as typ
import unicodedata

import pytest

from episodic.api.authorization_observability import (
    _AUTHORIZATION_LOG_METHODS,
    _AUTHORIZATION_LOG_RESOURCE_LABELS,
)
from tests.fixtures.authorization import (
    DenyAllAuthorization,
    ForbidSeriesProfilesAuthorization,
    RaisingAuthorization,
    build_authorization_test_client,
)
from tests.fixtures.authorization_log_routes import (
    AUTHORIZATION_LOG_ROUTE_CASES,
    STANDARD_AUTHORIZATION_LOG_METHODS,
    AuthorizationLogRouteCase,
)

_LOG_ESCAPED_UNICODE_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.authorization import (
        AuthorizationContext,
        AuthorizationDecision,
        AuthorizationPort,
    )


class _AuthorizationLogCollector:
    """Collect records through the injected authorization logging contract."""

    def __init__(self) -> None:
        """Initialize an empty authorization-record collection."""
        self.records: list[tuple[str, str, str, object | None, bool]] = []

    def _record(
        self,
        level: str,
        message: str,
        *,
        exc_info: object | None,
        stack_info: bool,
    ) -> None:
        """Append one normalized record for assertions."""
        self.records.append((
            "episodic.api.authorization",
            level,
            message,
            exc_info,
            stack_info,
        ))

    def log(
        self,
        level: int | str,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Capture records through the logging port's generic fallback."""
        level_name = "WARN" if level == logging.WARNING else str(level)
        self._record(
            level_name,
            message,
            exc_info=exc_info,
            stack_info=stack_info,
        )


@pytest.fixture
def authorization_log_collector() -> _AuthorizationLogCollector:
    """Capture authorization warnings through an injected synchronous logger."""
    return _AuthorizationLogCollector()


class _InvalidDecisionAuthorization:
    """Authorization adapter that returns an unsafe, invalid decision value."""

    async def decide(self, context: AuthorizationContext) -> AuthorizationDecision:
        """Return an invalid label to test the middleware logging boundary."""
        del context
        return typ.cast(
            "AuthorizationDecision",
            "forged\nBearer sensitive-token",
        )


class _AuthorizationLogCase(typ.NamedTuple):
    """Inputs and expected output for one authorization log assertion."""

    adapter_factory: type[AuthorizationPort]
    request_path: str
    expected_status: int
    expected_message: str
    authorization_header: str | None = "Bearer sensitive-token"
    request_method: str = "GET"


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
            _InvalidDecisionAuthorization,
            "/v1/series-profiles",
            503,
            "Authorization denied with unknown for GET /v1/series-profiles.",
        ),
        _AuthorizationLogCase(
            DenyAllAuthorization,
            "/v1/series-profiles",
            401,
            "Authorization denied with unauthorized for <other> /v1/series-profiles.",
            request_method="FORGED-AUDIT-ENTRY",
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
            "Authorization adapter failed with runtime_error for GET "
            "/v1/episode-templates.",
            None,
        ),
        _AuthorizationLogCase(
            RaisingAuthorization,
            "/v1/series-profiles",
            503,
            "Authorization adapter failed with runtime_error for <other> "
            "/v1/series-profiles.",
            request_method="FORGED-AUDIT-ENTRY",
        ),
        _AuthorizationLogCase(
            RaisingAuthorization,
            "/v1/series-profiles%0Dforged",
            503,
            "Authorization adapter failed with runtime_error for GET /v1/<unknown>.",
        ),
    ],
    ids=[
        "unauthorized",
        "forbidden",
        "unknown-decision",
        "unauthorized-custom-method",
        "unauthorized-known-resource-path-token",
        "unauthorized-unknown-resource-path-token",
        "unauthorized-control-path",
        "adapter-error-known-resource-path-token",
        "adapter-error-custom-method",
        "adapter-error-control-path",
    ],
)
def test_authorization_logs_warning_without_credentials_or_unsafe_unicode(
    session_factory: async_sessionmaker[AsyncSession],
    authorization_log_collector: _AuthorizationLogCollector,
    case: _AuthorizationLogCase,
) -> None:
    """Authorization warnings should be redacted and safe for log records."""
    collector = authorization_log_collector
    client = build_authorization_test_client(
        session_factory,
        case.adapter_factory(),
        warning_logger=collector,
    )
    response = client.simulate_request(
        path=case.request_path,
        method=case.request_method,
        headers=(
            {}
            if case.authorization_header is None
            else {"Authorization": case.authorization_header}
        ),
    )
    assert response.status_code == case.expected_status, response.status_code
    assert len(collector.records) == 1, collector.records
    logger_name, level, message, exc_info, stack_info = collector.records[0]
    assert logger_name == "episodic.api.authorization", logger_name
    assert level == "WARN", level
    assert message == case.expected_message, message
    assert exc_info is None, exc_info
    assert stack_info is False, stack_info
    assert all(
        unicodedata.category(char) not in _LOG_ESCAPED_UNICODE_CATEGORIES
        for char in message
    ), message
    assert "Bearer sensitive-token" not in message, message
    assert "sensitive-token" not in message, message
    assert "sensitive-path-token" not in message, message


def test_authorization_log_cases_cover_every_configured_root_and_method() -> None:
    """Keep independent literal expectations complete as allow-lists evolve."""
    # Read private allow-lists only to keep the literal test matrix complete.
    assert {case.resource_key for case in AUTHORIZATION_LOG_ROUTE_CASES} == set(
        _AUTHORIZATION_LOG_RESOURCE_LABELS
    ), "literal route expectations must cover every configured resource root"
    assert set(STANDARD_AUTHORIZATION_LOG_METHODS) == (_AUTHORIZATION_LOG_METHODS), (
        "literal method expectations must cover every configured method"
    )


@pytest.mark.parametrize(
    "route_case",
    AUTHORIZATION_LOG_ROUTE_CASES,
    ids=[case.resource_key for case in AUTHORIZATION_LOG_ROUTE_CASES],
)
@pytest.mark.parametrize("method", STANDARD_AUTHORIZATION_LOG_METHODS)
def test_denial_warning_uses_literal_route_and_standard_method_labels(
    session_factory: async_sessionmaker[AsyncSession],
    authorization_log_collector: _AuthorizationLogCollector,
    route_case: AuthorizationLogRouteCase,
    method: str,
) -> None:
    """Emit an exact, credential-free warning for each allowed route and method."""
    collector = authorization_log_collector
    client = build_authorization_test_client(
        session_factory,
        DenyAllAuthorization(),
        warning_logger=collector,
    )

    response = client.simulate_request(
        path=route_case.request_path,
        method=method,
        headers={"Authorization": "Bearer sensitive-token"},
    )
    expected_message = (
        f"Authorization denied with unauthorized for {method} "
        f"{route_case.expected_resource_label}."
    )
    assert response.status_code == 401, response.status_code
    assert len(collector.records) == 1, collector.records
    logger_name, level, message, exc_info, stack_info = collector.records[0]
    assert logger_name == "episodic.api.authorization", logger_name
    assert level == "WARN", level
    assert message == expected_message, message
    assert exc_info is None, exc_info
    assert stack_info is False, stack_info
    assert "Bearer sensitive-token" not in message, message
    assert "sensitive-token" not in message, message
    assert "sensitive-path-token" not in message, message
