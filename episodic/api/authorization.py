"""Authorization port and Falcon middleware for canonical REST APIs."""

import dataclasses as dc
import enum
import hmac
import typing as typ

import falcon

from episodic.logging import get_logger, log_warning

logger = get_logger(__name__)

_AUTHORIZATION_LOG_RESOURCE_LABELS = {
    "episode-templates": "/v1/episode-templates",
    "episodes": "/v1/episodes",
    "generation-runs": "/v1/generation-runs",
    "ingestion-jobs": "/v1/ingestion-jobs",
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
_AUTHORIZATION_FAILURE_CATEGORIES: dict[type[Exception], str] = {
    OSError: "os_error",
    RuntimeError: "runtime_error",
    TypeError: "type_error",
    ValueError: "value_error",
}


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

    def __init__(self, authorization: AuthorizationPort) -> None:
        self._authorization = authorization

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
        except (OSError, RuntimeError, TypeError, ValueError) as error:  # fmt: skip
            # Adapter exception text may contain credentials from its context.
            failure_category = _AUTHORIZATION_FAILURE_CATEGORIES.get(
                type(error),
                "unknown_error",
            )
            log_warning(
                logger,
                "Authorization adapter failed with %s for %s %s.",
                failure_category,
                _authorization_method_label(context.method),
                _authorization_route_label(context.path),
            )
            resp.media = {
                "code": "service_unavailable",
                "message": "Authorization service is unavailable.",
                "details": {},
            }
            resp.status = falcon.HTTP_503
            resp.complete = True
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


def _log_authorization_denial(
    decision: AuthorizationDecision,
    context: AuthorizationContext,
) -> None:
    """Log non-permit decisions without recording credential material."""
    log_warning(
        logger,
        "Authorization denied with %s for %s %s.",
        decision,
        _authorization_method_label(context.method),
        _authorization_route_label(context.path),
    )
