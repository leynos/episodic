"""Error-envelope helpers for Falcon resource adapters.

This module provides the stable JSON error envelope used by the canonical REST
API: ``{"code": "...", "message": "...", "details": {...}}``. Resource
adapters use these helpers to map domain exceptions to Falcon HTTP errors and
attach envelope metadata before Falcon serialises the response.

Examples
--------
>>> http_error(
...     falcon.HTTPBadRequest(description="Invalid limit."),
...     code="validation_error",
... )
HTTPBadRequest(...)
>>> validation_error("Invalid UUID.", field="profile_id", constraint="uuid")
HTTPBadRequest(...)
>>> try:
...     raise EntityNotFoundError("Profile not found.")
... except EntityNotFoundError as exc:
...     raise map_profile_template_error(exc, entity_id="profile-1") from exc
"""

import dataclasses as dc
import http
import typing as typ

import falcon

from episodic.canonical.profile_templates import (
    EntityNotFoundError,
    RevisionConflictError,
)
from episodic.canonical.reference_documents import (
    ReferenceConflictError,
    ReferenceDocumentError,
    ReferenceEntityNotFoundError,
    ReferenceRevisionConflictError,
    ReferenceValidationError,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.profile_templates.types import ProfileTemplateError

    from .types import JsonPayload


@dc.dataclass(frozen=True, slots=True)
class ErrorEnvelope:
    """Stable JSON error contract for REST clients."""

    code: str
    message: str
    details: dict[str, object]

    def as_json(self) -> JsonPayload:
        """Return the envelope as a Falcon-serialisable payload.

        Returns
        -------
        JsonPayload
            Mapping with ``code``, ``message``, and ``details`` keys suitable
            for assignment to ``falcon.Response.media``.
        """
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


def http_error(
    error: falcon.HTTPError,
    *,
    code: str,
    details: dict[str, object] | None = None,
) -> falcon.HTTPError:
    """Attach API error-envelope metadata to a Falcon error.

    Parameters
    ----------
    error : falcon.HTTPError
        Falcon error instance to enrich.
    code : str
        Machine-readable error code returned in the envelope.
    details : dict[str, object] | None
        Optional field-level or domain-specific envelope details.

    Returns
    -------
    falcon.HTTPError
        The same error instance enriched with envelope metadata.

    Examples
    --------
    >>> http_error(
    ...     falcon.HTTPBadRequest(description="Invalid limit."),
    ...     code="validation_error",
    ...     details={"field": "limit", "constraint": "range"},
    ... )
    HTTPBadRequest(...)
    """
    error_with_metadata = typ.cast("typ.Any", error)
    error_with_metadata.envelope_code = code
    error_with_metadata.envelope_details = {} if details is None else details
    return error


def validation_error(
    message: str,
    *,
    field: str | None = None,
    constraint: str | None = None,
) -> falcon.HTTPBadRequest:
    """Build a validation error with optional field-level details.

    Parameters
    ----------
    message : str
        Human-readable validation failure message.
    field : str | None
        Optional request field associated with the validation failure.
    constraint : str | None
        Optional violated constraint name, such as ``uuid`` or ``range``.

    Returns
    -------
    falcon.HTTPBadRequest
        Falcon bad-request error enriched with ``validation_error`` metadata.

    Examples
    --------
    >>> validation_error("Invalid UUID.", field="profile_id", constraint="uuid")
    HTTPBadRequest(...)
    """
    details: dict[str, object] = {}
    if field is not None:
        details["field"] = field
    if constraint is not None:
        details["constraint"] = constraint
    return typ.cast(
        "falcon.HTTPBadRequest",
        http_error(
            falcon.HTTPBadRequest(description=message),
            code="validation_error",
            details=details,
        ),
    )


# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # Falcon ASGI owns this handler signature.
async def handle_http_error(  # noqa: PLR0913, PLR0917, RUF029  # Falcon ASGI requires coroutine error handlers.
    req: falcon.Request,
    resp: falcon.Response | None,
    exc: falcon.HTTPError,
    params: dict[str, object],
    ws: object | None = None,
) -> None:
    """Serialise Falcon HTTP errors as the documented envelope.

    Parameters
    ----------
    req : falcon.Request
        Incoming request. Unused by this handler.
    resp : falcon.Response | None
        Response object populated with the error envelope. ``None`` for
        WebSocket error handling paths.
    exc : falcon.HTTPError
        Falcon error raised by a resource, hook, or middleware component.
    params : dict[str, object]
        Route parameters supplied by Falcon. Unused by this handler.
    ws : object | None
        Optional WebSocket object supplied by Falcon ASGI. Unused here.

    Notes
    -----
    Falcon ASGI requires registered error handlers to be coroutine functions,
    even when the handler body performs only synchronous response mutation.
    """
    del req, params, ws
    if resp is None:
        return
    code = _error_code(exc)
    message = _error_message(exc)
    details = _error_details(exc)
    resp.status = exc.status
    resp.media = ErrorEnvelope(code, message, details).as_json()


def map_profile_template_error(
    exc: ProfileTemplateError,
    *,
    entity_id: object | None = None,
    expected_revision: int | None = None,
) -> falcon.HTTPError:
    """Map profile/template domain errors to enriched Falcon errors.

    Parameters
    ----------
    exc : ProfileTemplateError
        Domain error raised by profile/template services.
    entity_id : object | None
        Optional entity identifier to include in envelope details when the
        exception does not already carry one.
    expected_revision : int | None
        Optional optimistic-lock revision expected by the caller.

    Returns
    -------
    falcon.HTTPError
        Falcon error enriched with the API envelope metadata.

    Examples
    --------
    >>> try:
    ...     raise EntityNotFoundError("Profile not found.")
    ... except EntityNotFoundError as exc:
    ...     raise map_profile_template_error(exc, entity_id="profile-1") from exc
    """
    details: dict[str, object] = {}
    if exc.entity_id is not None:
        details["entity_id"] = exc.entity_id
    elif entity_id is not None:
        details["entity_id"] = str(entity_id)
    if expected_revision is not None:
        details["expected_revision"] = expected_revision

    match exc:
        case EntityNotFoundError():
            return http_error(
                falcon.HTTPNotFound(description=str(exc)),
                code="not_found",
                details=details,
            )
        case RevisionConflictError() as revision_conflict:
            return http_error(
                falcon.HTTPConflict(description=str(revision_conflict)),
                code=revision_conflict.code,
                details=details,
            )
        case _:
            return http_error(
                falcon.HTTPInternalServerError(description=str(exc)),
                code=exc.code,
                details=details,
            )


def map_reference_error(
    exc: ReferenceDocumentError,
    *,
    context: str,
) -> falcon.HTTPError:
    """Map reusable reference-document domain errors to Falcon HTTP errors.

    Parameters
    ----------
    exc : ReferenceDocumentError
        Domain error raised by reusable-reference services.
    context : str
        Short context label used for unexpected internal-error messages.

    Returns
    -------
    falcon.HTTPError
        Falcon ``400``, ``404``, ``409``, or ``500`` error enriched with
        envelope metadata.

    Examples
    --------
    >>> try:
    ...     raise ReferenceValidationError("Invalid reference document.")
    ... except ReferenceDocumentError as exc:
    ...     raise map_reference_error(exc, context="reference-document") from exc
    """
    match exc:
        case ReferenceValidationError():
            return http_error(
                falcon.HTTPBadRequest(description=str(exc)),
                code="validation_error",
            )
        case ReferenceEntityNotFoundError():
            return http_error(
                falcon.HTTPNotFound(description=str(exc)),
                code="not_found",
            )
        case ReferenceRevisionConflictError():
            return http_error(
                falcon.HTTPConflict(description=str(exc)),
                code="revision_conflict",
            )
        case ReferenceConflictError():
            return http_error(
                falcon.HTTPConflict(description=str(exc)),
                code="conflict",
            )
    msg = f"Unexpected {context} error."
    return http_error(
        falcon.HTTPInternalServerError(description=msg),
        code="internal_error",
    )


def _error_code(exc: falcon.HTTPError) -> str:
    """Return the envelope error code for an HTTP error."""
    raw_code = getattr(exc, "envelope_code", None)
    if isinstance(raw_code, str) and raw_code:
        return raw_code
    return _DEFAULT_CODES.get(_status_code(exc), "internal_error")


def _error_message(exc: falcon.HTTPError) -> str:
    """Return the envelope message for an HTTP error."""
    if isinstance(exc.description, str) and exc.description:
        return exc.description
    if isinstance(exc.title, str) and exc.title:
        return exc.title
    try:
        return http.HTTPStatus(_status_code(exc)).phrase
    except ValueError:
        return "An error occurred."


def _error_details(exc: falcon.HTTPError) -> dict[str, object]:
    """Return the envelope details for an HTTP error."""
    raw_details = getattr(exc, "envelope_details", None)
    if isinstance(raw_details, dict):
        return raw_details
    return {}


def _status_code(exc: falcon.HTTPError) -> int:
    """Return the numeric HTTP status code for an HTTP error."""
    if isinstance(exc.status, int):
        return exc.status
    try:
        return int(exc.status.split(" ", maxsplit=1)[0])
    except IndexError, ValueError:  # parsed as tuple in Python 3
        return 500


_DEFAULT_CODES = {
    400: "validation_error",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "unprocessable_entity",
    500: "internal_error",
}
