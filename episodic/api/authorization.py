"""Authorization port and Falcon middleware for canonical REST APIs."""

import dataclasses as dc
import enum
import hmac
import typing as typ

import falcon

if typ.TYPE_CHECKING:
    from .authorization_observability import AuthorizationObservabilityPort


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
        observer: AuthorizationObservabilityPort,
    ) -> None:
        """Initialize middleware with decision and observability ports.

        Parameters
        ----------
        authorization : AuthorizationPort
            Async port that decides the outcome for each protected request.
        observer : AuthorizationObservabilityPort
            Boundary observer for credential-free logs and bounded metrics.
        """
        self._authorization = authorization
        self._observer = observer

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
            try:
                self._observer.record_authorization_outcome(
                    error,
                    method=context.method,
                    path=context.path,
                )
            except Exception as observer_error:
                raise observer_error from None
            _set_authorization_response(
                resp,
                code="service_unavailable",
                message="Authorization service is unavailable.",
                status=falcon.HTTP_503,
            )
            return

        match result.decision:
            case AuthorizationDecision.PERMIT:
                req.context.principal_id = result.principal_id
                return
            case AuthorizationDecision.UNAUTHORIZED:
                self._observer.record_authorization_outcome(
                    result.decision,
                    method=context.method,
                    path=context.path,
                )
                _set_authorization_response(
                    resp,
                    code="unauthorized",
                    message="Authorization is required.",
                    status=falcon.HTTP_401,
                )
            case AuthorizationDecision.FORBIDDEN:
                self._observer.record_authorization_outcome(
                    result.decision,
                    method=context.method,
                    path=context.path,
                )
                _set_authorization_response(
                    resp,
                    code="forbidden",
                    message="Access to this resource is forbidden.",
                    status=falcon.HTTP_403,
                )
            case _:
                self._observer.record_authorization_outcome(
                    result.decision,
                    method=context.method,
                    path=context.path,
                )
                _set_authorization_response(
                    resp,
                    code="internal_error",
                    message="Unexpected authorization decision.",
                    status=falcon.HTTP_503,
                )


def _set_authorization_response(
    response: falcon.Response,
    *,
    code: str,
    message: str,
    status: str,
) -> None:
    """Set the canonical authorization envelope and stop request dispatch."""
    response.media = {"code": code, "message": message, "details": {}}
    response.status = status
    response.complete = True


def _authorization_result(
    outcome: AuthorizationDecision | AuthorizationResult,
) -> AuthorizationResult:
    """Normalise legacy decision-only adapters to a principal-aware result."""
    if isinstance(outcome, AuthorizationResult):
        return outcome
    return AuthorizationResult(decision=outcome)
