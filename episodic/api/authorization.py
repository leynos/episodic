"""Authorization port and Falcon middleware for canonical REST APIs."""

import dataclasses as dc
import enum
import typing as typ

import falcon

from episodic.logging import LogLevel, get_logger, log_warning

logger = get_logger(__name__)


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

    async def decide(  # noqa: PLR6301 - must match AuthorizationPort instance method.
        self,
        context: AuthorizationContext,
    ) -> AuthorizationResult:
        """Permit the request."""
        del context
        return AuthorizationResult(AuthorizationDecision.PERMIT)


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
        except OSError, RuntimeError, TypeError, ValueError:
            log_warning(
                logger,
                "Authorization adapter failed for %s %s.",
                context.method,
                context.path,
                exc_info=True,
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


def _log_authorization_denial(
    decision: AuthorizationDecision,
    context: AuthorizationContext,
) -> None:
    """Log non-permit decisions without recording credential material."""
    logger.log(
        LogLevel.DEBUG,
        (f"Authorization denied with {decision} for {context.method} {context.path}."),
    )
