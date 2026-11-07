"""Response decoding for the Episodic REST client.

:class:`~episodic.cli.client.QaApiClient` only opens the connection; this module
turns the answer into either a page payload or one of the CLI's typed errors,
so status-code policy stays in one place.
"""

import typing as typ

import httpx

from episodic.cli.errors import MISSING_TOKEN_HINT, ApiError, RateLimitedError


def decode_page(
    response: httpx.Response,
    *,
    token_configured: bool,
) -> dict[str, object]:
    """Return a successful payload or raise the matching CLI error.

    Parameters
    ----------
    response : httpx.Response
        The completed API response.
    token_configured : bool
        Whether the invocation supplied a bearer token, which decides whether a
        401 is reported as a missing credential.

    Returns
    -------
    dict[str, object]
        The page envelope when the response is successful and carries an
        ``items`` list.

    Raises
    ------
    ApiError
        If the API answered with an error envelope, or with a successful body
        that is not a page envelope.
    RateLimitedError
        If the API throttled the request.
    """  # ruff: ignore[docstring-extraneous-exception]  # _successful_page() and _raise_api_error() raise them.
    payload = _decode(response)
    status = response.status_code
    if response.is_success:
        return _successful_page(payload, status)
    return _raise_api_error(response, payload, token_configured=token_configured)


def _successful_page(
    payload: dict[str, object],
    status: int,
) -> dict[str, object]:
    """Return a page envelope, or refuse a successful body that is not one."""
    match payload.get("items"):
        case list():
            return payload
        case _:
            unexpected = f"{status} the API returned an unexpected response body"
            raise ApiError(unexpected)


def _raise_api_error(
    response: httpx.Response,
    payload: dict[str, object],
    *,
    token_configured: bool,
) -> typ.NoReturn:
    """Raise the CLI error that matches the response's status and body."""
    code = _as_text(payload.get("code")) or "unknown_error"
    message = _as_text(payload.get("message")) or response.reason_phrase
    status = response.status_code
    if status == httpx.codes.TOO_MANY_REQUESTS or code == "rate_limited":
        raise RateLimitedError(
            _throttled_message(status, message, response.headers.get("Retry-After"))
        )
    unauthorized = status == httpx.codes.UNAUTHORIZED and not token_configured
    hint = MISSING_TOKEN_HINT if unauthorized else None
    text = f"{status} {message}"
    raise ApiError(text, hint=hint)


def _decode(response: httpx.Response) -> dict[str, object]:
    """Decode a JSON object body, treating anything else as absent."""
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    match payload:
        case dict() as body:
            return body
        case _:
            return {}


def _as_text(value: object) -> str | None:
    """Return a non-empty string value, or ``None``."""
    match value:
        case str() as text if text:
            return text
        case _:
            return None


def _throttled_message(status: int, message: str, retry_after: str | None) -> str:
    """Compose a throttle message that names the retry delay when present."""
    text = f"{status} {message}"
    if not retry_after:
        return text
    if retry_after.isdigit():
        return f"{text} (retry after {retry_after} seconds)"
    # RFC 9110 allows an HTTP-date as well as a delay in seconds, and a
    # "seconds" unit after a date would be a unit the server never sent.
    return f"{text} (retry after {retry_after})"
