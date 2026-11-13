"""Authorization port and Falcon middleware for canonical REST APIs."""

import contextlib
import dataclasses as dc
import enum
import hashlib
import hmac
import sys
import typing as typ

import falcon

from episodic.logging import get_logger, log_warning
from episodic.observability import MetricsPort, NoopMetrics

logger = get_logger(__name__)

_AUTHORIZATION_ADAPTER_FAILURE_TOTAL = "authorization_adapter_failure_total"
_AUTHORIZATION_WARNING_FALLBACK_MESSAGE = (
    "Authorization warning sink failed; request details omitted.\n"
)
# Exceptions outside this table intentionally use the fixed `unknown_error` label.
_AUTHORIZATION_FAILURE_CATEGORIES = (
    (AssertionError, "assertion_error"),
    (AttributeError, "attribute_error"),
    (IndexError, "index_error"),
    (KeyError, "key_error"),
    (OSError, "os_error"),
    (RuntimeError, "runtime_error"),
    (TypeError, "type_error"),
    (ValueError, "value_error"),
)
_AUTHORIZATION_LOG_RESOURCE_LABELS = {
    "episode-templates": "/v1/episode-templates",
    "episodes": "/v1/episodes",
    "generation-runs": "/v1/generation-runs",
    "ingestion-jobs": "/v1/ingestion-jobs",
    "qa-evaluations": "/v1/qa-evaluations",
    "reference-bindings": "/v1/reference-bindings",
    "reference-document-revisions": "/v1/reference-document-revisions",
    "series-profiles": "/v1/series-profiles",
    "uploads": "/v1/uploads",
}
_UNKNOWN_AUTHORIZATION_LOG_RESOURCE = "/v1/<unknown>"
_AUTHORIZATION_LOG_METHODS = frozenset({
    "DELETE",
    "GET",
    "HEAD",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
})
_OTHER_AUTHORIZATION_LOG_METHOD = "<other>"


class AuthorizationDecision(enum.StrEnum):
    """Possible authorization outcomes for one HTTP request."""

    PERMIT = "permit"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"


@dc.dataclass(frozen=True, slots=True)
class AuthorizationResult:
    """Decision returned by authorization with the authenticated principal."""

    decision: AuthorizationDecision
    principal_id: str | None = None


@dc.dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """Request data supplied to authorization adapters."""

    method: str
    path: str
    authorization_header: str | None


@typ.runtime_checkable
class AuthorizationPort(typ.Protocol):
    """Port used by the API adapter to authorize incoming requests."""

    async def decide(
        self,
        context: AuthorizationContext,
    ) -> AuthorizationDecision | AuthorizationResult:
        """Return the authorization decision for one request."""
        ...  # pylint: disable=unnecessary-ellipsis  # Protocol stub.


class PermitAll:
    """Default authorization adapter that permits every request."""

    async def decide(  # ruff: ignore[no-self-use] - must match AuthorizationPort instance method.
        self,
        context: AuthorizationContext,
    ) -> AuthorizationResult:
        """Permit the request."""
        del context
        return AuthorizationResult(AuthorizationDecision.PERMIT)


@dc.dataclass(frozen=True, slots=True)
class StaticBearerTokenAuthorization:
    """Authorize one configured bearer token as one configured principal."""

    token: str
    principal_id: str

    async def decide(
        self,
        context: AuthorizationContext,
    ) -> AuthorizationResult:
        """Return the configured principal for a matching bearer token."""
        header = context.authorization_header
        if header is None:
            return AuthorizationResult(AuthorizationDecision.UNAUTHORIZED)
        scheme, separator, token = header.partition(" ")
        if not separator or not token:
            return AuthorizationResult(AuthorizationDecision.UNAUTHORIZED)
        if scheme.casefold() != "bearer":
            return AuthorizationResult(AuthorizationDecision.UNAUTHORIZED)
        if not hmac.compare_digest(token, self.token):
            return AuthorizationResult(AuthorizationDecision.UNAUTHORIZED)
        return AuthorizationResult(
            AuthorizationDecision.PERMIT,
            principal_id=self.principal_id,
        )


class AuthorizationMiddleware:
    """Falcon middleware that short-circuits unauthorized `/v1` requests."""

    def __init__(
        self,
        authorization: AuthorizationPort,
        metrics: MetricsPort | None = None,
    ) -> None:
        """Initialize middleware with authorization and metrics ports.

        Parameters
        ----------
        authorization : AuthorizationPort
            Async port that decides the outcome for each protected request.
        metrics : MetricsPort | None, optional
            Port for bounded adapter-failure counters. When omitted, a no-op
            metrics port is used.
        """
        self._authorization = authorization
        self._metrics = NoopMetrics() if metrics is None else metrics

    async def process_request(
        self,
        req: falcon.Request,
        resp: falcon.Response,
    ) -> None:
        """Authorize one incoming request before resource dispatch."""
        if not req.path.startswith("/v1/"):
            return

        context = AuthorizationContext(
            method=req.method,
            path=req.path,
            authorization_header=req.get_header("Authorization"),
        )
        try:
            result = _authorization_result(await self._authorization.decide(context))
        except Exception as error:  # ruff: ignore[blind-except]  # Adapter errors may contain credentials.
            _handle_authorization_adapter_failure(
                error,
                context,
                self._metrics,
                resp,
            )
            return

        match result.decision:
            case AuthorizationDecision.PERMIT:
                req.context.principal_id = result.principal_id
                return
            case AuthorizationDecision.UNAUTHORIZED:
                _log_authorization_denial(result.decision, context)
                resp.media = {
                    "code": "unauthorized",
                    "message": "Authorization is required.",
                    "details": {},
                }
                resp.status = falcon.HTTP_401
            case AuthorizationDecision.FORBIDDEN:
                _log_authorization_denial(result.decision, context)
                resp.media = {
                    "code": "forbidden",
                    "message": "Access to this resource is forbidden.",
                    "details": {},
                }
                resp.status = falcon.HTTP_403
            case _:
                _log_authorization_denial(result.decision, context)
                resp.media = {
                    "code": "internal_error",
                    "message": "Unexpected authorization decision.",
                    "details": {},
                }
                resp.status = falcon.HTTP_503
        resp.complete = True


def _authorization_failure_category(error: Exception) -> str:
    """Return a bounded category for a caught authorization adapter error."""
    return next(
        (
            category
            for error_type, category in _AUTHORIZATION_FAILURE_CATEGORIES
            if isinstance(error, error_type)
        ),
        "unknown_error",
    )


def _authorization_failure_diagnostic_id(error: Exception) -> str:
    """Fingerprint an unclassified exception type without logging its name."""
    error_type = type(error)
    module = type.__getattribute__(error_type, "__module__")
    qualified_name = type.__getattribute__(error_type, "__qualname__")
    if not isinstance(module, str) or not isinstance(qualified_name, str):
        module, qualified_name = "unknown", "exception"
    type_identity = f"{module}.{qualified_name}"
    return hashlib.sha256(
        type_identity.encode("utf-8", errors="backslashreplace"),
    ).hexdigest()[:12]


def _log_authorization_warning(
    template: str,
    *args: object,
) -> None:
    """Keep logger failures from masking canonical authorization responses."""
    try:
        log_warning(logger, template, *args)
    except Exception:  # ruff: ignore[blind-except]  # Preserve canonical authorization responses.
        _write_authorization_warning_fallback()


def _write_authorization_warning_fallback() -> None:
    """Write a fixed stderr marker when the central warning sink fails."""
    stream = sys.stderr
    if stream is None:
        return
    # A failed secondary sink must not replace the canonical response.
    with contextlib.suppress(Exception):
        stream.write(_AUTHORIZATION_WARNING_FALLBACK_MESSAGE)
        stream.flush()


def _record_authorization_adapter_failure(
    metrics: MetricsPort,
    failure_category: str,
) -> None:
    """Record an adapter failure without allowing metrics errors to mask it."""
    try:
        metrics.increment_counter(
            _AUTHORIZATION_ADAPTER_FAILURE_TOTAL,
            labels={"category": failure_category},
        )
    except Exception:  # ruff: ignore[blind-except]  # Metrics must not mask adapter failures.
        _log_authorization_warning(
            "Authorization adapter failure metric could not be recorded.",
        )


def _handle_authorization_adapter_failure(
    error: Exception,
    context: AuthorizationContext,
    metrics: MetricsPort,
    response: falcon.Response,
) -> None:
    """Record safe diagnostics and set the canonical adapter-failure response."""
    # Adapter exception text may contain credentials from its context.
    failure_category = _authorization_failure_category(error)
    _record_authorization_adapter_failure(metrics, failure_category)
    diagnostic_id = (
        _authorization_failure_diagnostic_id(error)
        if failure_category == "unknown_error"
        else ""
    )
    diagnostic_suffix = f" (diagnostic_id={diagnostic_id})" if diagnostic_id else ""
    _log_authorization_warning(
        "Authorization adapter failed with %s%s for %s %s.",
        failure_category,
        diagnostic_suffix,
        _authorization_method_label(context.method),
        _authorization_route_label(context.path),
    )
    response.media = {
        "code": "service_unavailable",
        "message": "Authorization service is unavailable.",
        "details": {},
    }
    response.status = falcon.HTTP_503
    response.complete = True


def _authorization_result(
    outcome: AuthorizationDecision | AuthorizationResult,
) -> AuthorizationResult:
    """Normalise legacy decision-only adapters to a principal-aware result."""
    if isinstance(outcome, AuthorizationResult):
        return outcome
    return AuthorizationResult(decision=outcome)


def _authorization_route_label(path: str) -> str:
    """Return an allow-listed route root without client-controlled path values."""
    if not path.startswith("/v1/"):
        return _UNKNOWN_AUTHORIZATION_LOG_RESOURCE
    resource = path.removeprefix("/v1/").partition("/")[0]
    return _AUTHORIZATION_LOG_RESOURCE_LABELS.get(
        resource,
        _UNKNOWN_AUTHORIZATION_LOG_RESOURCE,
    )


def _authorization_method_label(method: str) -> str:
    """Return a standard HTTP method name, or a fixed placeholder."""
    return (
        method
        if method in _AUTHORIZATION_LOG_METHODS
        else _OTHER_AUTHORIZATION_LOG_METHOD
    )


def _authorization_decision_label(decision: object) -> str:
    """Return a fixed label for known authorization decisions."""
    match decision:
        case AuthorizationDecision() as known_decision:
            return known_decision.value
        case _:
            return "unknown"


def _log_authorization_denial(
    decision: AuthorizationDecision,
    context: AuthorizationContext,
) -> None:
    """Log non-permit decisions without recording credential material."""
    _log_authorization_warning(
        "Authorization denied with %s for %s %s.",
        _authorization_decision_label(decision),
        _authorization_method_label(context.method),
        _authorization_route_label(context.path),
    )
