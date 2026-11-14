"""Authorization adapter failure logging tests."""

import traceback
import typing as typ
from unittest import mock

import falcon
import pytest

from episodic.api import authorization as authorization_module
from tests.fixtures.authorization import (
    AuthorizationWarningLogger,
    DenyAllAuthorization,
    ForbidSeriesProfilesAuthorization,
    RaisingAuthorization,
    build_authorization_observer,
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


class _AuthorizationHeaderFailure:
    """Authorization adapter that includes the request header in its error."""

    def __init__(self, error_type: type[Exception] = RuntimeError) -> None:
        """Set the exception type used to expose the raw request header."""
        self._error_type = error_type

    async def decide(self, context: AuthorizationContext) -> AuthorizationDecision:
        """Raise with the raw header to test the middleware logging boundary."""
        header = context.authorization_header
        raise self._error_type(header if header is not None else "missing header")


class _AuthorizationFailureLogCase(typ.NamedTuple):
    """Adapter input and bounded output expected for one failure case."""

    authorization: AuthorizationPort
    expected_category: str
    forbidden_values: tuple[str, ...]
    expected_diagnostic_id: str | None = None


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _AuthorizationFailureLogCase(
                _AuthorizationHeaderFailure(AssertionError),
                "assertion_error",
                ("Bearer sensitive-token",),
            ),
            id="header-assertion-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                _AuthorizationHeaderFailure(KeyError),
                "key_error",
                ("Bearer sensitive-token",),
            ),
            id="header-key-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                _AuthorizationHeaderFailure(AttributeError),
                "attribute_error",
                ("Bearer sensitive-token",),
            ),
            id="header-attribute-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                _AuthorizationHeaderFailure(RuntimeError),
                "runtime_error",
                ("Bearer sensitive-token",),
            ),
            id="header-runtime-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                RaisingAuthorization(error_type=ConnectionError),
                "os_error",
                ("authorization backend unavailable", "Bearer sensitive-token"),
            ),
            id="connection-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                RaisingAuthorization(error_type=IndexError),
                "index_error",
                ("authorization backend unavailable", "Bearer sensitive-token"),
            ),
            id="index-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                RaisingAuthorization(error_type=KeyError),
                "key_error",
                ("authorization backend unavailable", "Bearer sensitive-token"),
            ),
            id="key-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                RaisingAuthorization(error_type=AttributeError),
                "attribute_error",
                ("authorization backend unavailable", "Bearer sensitive-token"),
            ),
            id="attribute-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                RaisingAuthorization(error_type=LookupError),
                "unknown_error",
                ("authorization backend unavailable", "Bearer sensitive-token"),
                "063d85c714a4",
            ),
            id="unknown-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                RaisingAuthorization(error_type=ZeroDivisionError),
                "unknown_error",
                ("authorization backend unavailable", "Bearer sensitive-token"),
                "050fc615ac6b",
            ),
            id="unknown-arithmetic-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                RaisingAuthorization(error_type=OSError),
                "os_error",
                ("authorization backend unavailable", "Bearer sensitive-token"),
            ),
            id="os-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                RaisingAuthorization(error_type=RuntimeError),
                "runtime_error",
                ("authorization backend unavailable", "Bearer sensitive-token"),
            ),
            id="runtime-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                RaisingAuthorization(error_type=TimeoutError),
                "os_error",
                ("authorization backend unavailable", "Bearer sensitive-token"),
            ),
            id="timeout-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                RaisingAuthorization(error_type=TypeError),
                "type_error",
                ("authorization backend unavailable", "Bearer sensitive-token"),
            ),
            id="type-error",
        ),
        pytest.param(
            _AuthorizationFailureLogCase(
                RaisingAuthorization(error_type=ValueError),
                "value_error",
                ("authorization backend unavailable", "Bearer sensitive-token"),
            ),
            id="value-error",
        ),
    ],
)
def test_authorization_adapter_failures_log_fixed_categories_without_details(
    session_factory: async_sessionmaker[AsyncSession],
    authorization_warning_backend: AuthorizationWarningLogger,
    case: _AuthorizationFailureLogCase,
) -> None:
    """Adapter failures emit bounded logs and metrics without exception text."""
    metrics = mock.Mock()
    authorization_header = "Bearer sensitive-token"
    client = build_authorization_test_client(
        session_factory,
        case.authorization,
        metrics=metrics,
        warning_logger=authorization_warning_backend,
    )

    response = client.simulate_get(
        "/v1/series-profiles",
        headers={"Authorization": authorization_header},
    )

    assert response.status_code == 503, response.status_code
    diagnostic_id = (
        f" (diagnostic_id={case.expected_diagnostic_id})"
        if case.expected_diagnostic_id is not None
        else ""
    )
    assert authorization_warning_backend.warning_calls == [
        (
            (
                f"Authorization adapter failed with {case.expected_category}"
                f"{diagnostic_id} for GET /v1/series-profiles."
            ),
            None,
            False,
        )
    ], "adapter failures must emit one sanitized warning"
    metrics.increment_counter.assert_called_once_with(
        "authorization_adapter_failure_total",
        labels={"category": case.expected_category},
    )
    warning_call = repr(authorization_warning_backend.warning_calls)
    for forbidden_value in case.forbidden_values:
        assert forbidden_value not in warning_call, (
            f"{forbidden_value!r} must not reach the warning logger"
        )


def test_metrics_failure_does_not_interrupt_authorization_adapter_response(
    session_factory: async_sessionmaker[AsyncSession],
    authorization_warning_backend: AuthorizationWarningLogger,
) -> None:
    """Metrics errors cannot mask the adapter failure response or leak details."""
    metrics = mock.Mock()
    metrics.increment_counter.side_effect = RuntimeError("Bearer sensitive-token")
    client = build_authorization_test_client(
        session_factory,
        _AuthorizationHeaderFailure(),
        metrics=metrics,
        warning_logger=authorization_warning_backend,
    )

    response = client.simulate_get(
        "/v1/series-profiles",
        headers={"Authorization": "Bearer sensitive-token"},
    )

    assert response.status_code == 503, "metrics failure must preserve the 503 response"
    warning_calls = authorization_warning_backend.warning_calls
    assert len(warning_calls) == 2, "both fixed warnings must be recorded"
    metric_warning, adapter_warning = warning_calls
    assert metric_warning == (
        "Authorization adapter failure metric could not be recorded.",
        None,
        False,
    ), "metrics failures must use a fixed warning without exception metadata"
    expected_adapter_message = (
        "Authorization adapter failed with runtime_error for GET /v1/series-profiles."
    )
    assert adapter_warning == (expected_adapter_message, None, False), (
        "adapter warning must follow a metrics failure"
    )
    assert "Bearer sensitive-token" not in repr(
        warning_calls,
    ), "authorization credentials must not reach either warning"


@pytest.mark.asyncio
async def test_missing_metrics_does_not_add_a_failure_warning(
    authorization_warning_backend: AuthorizationWarningLogger,
) -> None:
    """Adapter failures remain safe when the middleware uses no metrics port."""
    middleware = authorization_module.AuthorizationMiddleware(
        _AuthorizationHeaderFailure(),
        build_authorization_observer(authorization_warning_backend),
    )
    request = mock.Mock()
    request.path = "/v1/series-profiles"
    request.method = "GET"
    request.get_header.return_value = "Bearer sensitive-token"
    response = mock.Mock()

    await middleware.process_request(request, response)

    assert response.status == falcon.HTTP_503, "adapter failures must retain HTTP 503"
    assert response.media == {
        "code": "service_unavailable",
        "message": "Authorization service is unavailable.",
        "details": {},
    }, "adapter failures must use the canonical service-unavailable envelope"
    assert response.complete is True, "adapter failures must stop request dispatch"
    assert authorization_warning_backend.warning_calls == [
        (
            (
                "Authorization adapter failed with runtime_error "
                "for GET /v1/series-profiles."
            ),
            None,
            False,
        )
    ], "adapter runtime failures must emit one sanitized warning"
    assert "Bearer sensitive-token" not in repr(
        authorization_warning_backend.warning_calls,
    ), "the warning must not include the Authorization header value"


@pytest.mark.asyncio
async def test_observer_failure_does_not_chain_adapter_credentials(
    authorization_warning_backend: AuthorizationWarningLogger,
) -> None:
    """Do not expose adapter exception text through an observer traceback."""
    authorization_warning_backend.warning_failure = AssertionError(
        "warning backend assertion"
    )
    middleware = authorization_module.AuthorizationMiddleware(
        _AuthorizationHeaderFailure(),
        build_authorization_observer(authorization_warning_backend),
    )
    request = mock.Mock()
    request.path = "/v1/series-profiles"
    request.method = "GET"
    request.get_header.return_value = "Bearer sensitive-token"

    with pytest.raises(AssertionError) as caught:
        await middleware.process_request(request, mock.Mock())

    assert caught.value.__suppress_context__ is True, (
        "observer failures must suppress the credential-bearing adapter context"
    )
    assert "Bearer sensitive-token" not in "".join(
        traceback.format_exception(caught.value)
    ), "observer tracebacks must not expose adapter exception text"


@pytest.mark.parametrize(
    ("authorization", "authorization_header", "expected_status"),
    [
        pytest.param(
            authorization_module.StaticBearerTokenAuthorization(
                token="".join(("configured", "-token")),
                principal_id="configured-principal",
            ),
            "Bearer configured-token",
            200,
            id="permitted",
        ),
        pytest.param(
            DenyAllAuthorization(),
            "Bearer sensitive-token",
            401,
            id="unauthorized",
        ),
        pytest.param(
            ForbidSeriesProfilesAuthorization(),
            "Bearer sensitive-token",
            403,
            id="forbidden",
        ),
    ],
)
def test_nonfailure_authorization_decisions_do_not_increment_adapter_metric(
    session_factory: async_sessionmaker[AsyncSession],
    authorization: AuthorizationPort,
    authorization_header: str,
    expected_status: int,
) -> None:
    """Permits and denials leave the adapter-failure counter untouched."""
    metrics = mock.Mock()
    client = build_authorization_test_client(
        session_factory,
        authorization,
        metrics=metrics,
    )

    response = client.simulate_get(
        "/v1/series-profiles",
        headers={"Authorization": authorization_header},
    )

    assert response.status_code == expected_status, response.status_code
    metrics.increment_counter.assert_not_called()
