"""Build and serialize the stable Falcon error envelope.

This module owns the shared response contract. Domain-specific exception
mappings live in :mod:`episodic.api.errors` and use these helpers to preserve
the same client envelope across API features.
"""

import dataclasses as dc
import http
import typing as typ

import falcon

if typ.TYPE_CHECKING:
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


def serialize_http_error(
    _req: falcon.Request,
    resp: falcon.Response,
    exc: falcon.HTTPError,
) -> None:
    """Serialize Falcon HTTP errors as the documented response envelope.

    Wired through :meth:`falcon.asgi.App.set_error_serializer`. Falcon's
    default error handler sets ``resp.status`` from ``exc.status`` before
    invoking the serializer, so this function only needs to populate
    ``resp.media`` with the ``{code, message, details}`` envelope. The API
    serializer wrapper emits any detached unmapped-domain diagnostic before
    calling this envelope serializer. Falcon accepts both sync and async
    serializers; a sync function keeps the body free of unnecessary coroutine
    machinery.

    Parameters
    ----------
    _req : falcon.Request
        Incoming request required by Falcon's callback contract. This
        serializer does not inspect it.
    resp : falcon.Response
        Response populated with the error envelope.
    exc : falcon.HTTPError
        Falcon error raised by a resource, hook, or middleware component.
    """
    resp.media = ErrorEnvelope(
        _error_code(exc),
        _error_message(exc),
        _error_details(exc),
    ).as_json()


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
    except (IndexError, ValueError):  # fmt: skip
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
