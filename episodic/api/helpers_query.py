"""Query-parameter and payload-shape parsing for Falcon resource adapters.

This module holds the request-facing parsing utilities used by resource
classes and shared handlers: UUID parsing, JSON payload shape validation,
pagination, and generic query-parameter helpers (required/optional/enum).
It is split out of :mod:`episodic.api.helpers`, which re-exports these names
so existing import paths keep working.

Examples
--------
Parse and validate identifiers before service dispatch:

>>> profile_id = parse_uuid(raw_profile_id, "profile_id")
"""

import enum
import typing as typ
import uuid

from episodic.canonical.pagination import Pagination

from .errors import validation_error

if typ.TYPE_CHECKING:
    import falcon

    from .types import JsonPayload

_DEFAULT_PAGE_LIMIT = 20
_MAX_PAGE_LIMIT = 100


def parse_uuid(raw_value: str, field_name: str) -> uuid.UUID:
    """Parse a UUID string for a named request field.

    Parameters
    ----------
    raw_value : str
        Raw string value to parse.
    field_name : str
        Request field name used in validation error messages.

    Returns
    -------
    uuid.UUID
        Parsed UUID value.

    Raises
    ------
    falcon.HTTPBadRequest
        If ``raw_value`` cannot be parsed as a UUID; the exception carries the
        validation error envelope for ``field_name``.
    """  # noqa: DOC501, DOC502  # validation_error returns this concrete Falcon exception.
    try:
        return uuid.UUID(raw_value)
    except (TypeError, ValueError, AttributeError) as exc:
        msg = f"Invalid UUID for {field_name}: {raw_value!r}."
        raise validation_error(msg, field=field_name, constraint="uuid") from exc


def require_payload_dict(payload: object) -> JsonPayload:
    """Validate that request media is a JSON object mapping.

    Parameters
    ----------
    payload : object
        Parsed Falcon request media.

    Returns
    -------
    JsonPayload
        Validated JSON object payload.

    Raises
    ------
    falcon.HTTPBadRequest
        If request media is not a JSON object; the exception carries the
        validation error envelope.
    """  # noqa: DOC501, DOC502  # validation_error returns this concrete Falcon exception.
    if not isinstance(payload, dict):
        msg = "JSON object payload is required."
        raise validation_error(msg, constraint="object")
    return typ.cast("JsonPayload", payload)


def require_query_params(req: falcon.Request, *names: str) -> dict[str, str]:
    """Return required query parameters or raise HTTP 400."""
    values: dict[str, str] = {}
    for name in names:
        value = req.get_param(name)
        if value is None:
            msg = f"Missing required query parameter: {name}"
            raise validation_error(msg, field=name, constraint="required")
        values[name] = value
    return values


def parse_pagination(req: falcon.Request) -> Pagination:
    """Parse and validate common `limit`/`offset` query parameters."""
    limit = _parse_int_query_param(
        req.get_param("limit"),
        name="limit",
        default=_DEFAULT_PAGE_LIMIT,
    )
    offset = _parse_int_query_param(
        req.get_param("offset"),
        name="offset",
        default=0,
    )

    if limit < 1 or limit > _MAX_PAGE_LIMIT:
        msg = f"limit must be between 1 and {_MAX_PAGE_LIMIT}."
        raise validation_error(msg, field="limit", constraint="range")
    if offset < 0:
        msg = "offset must be a non-negative integer."
        raise validation_error(msg, field="offset", constraint="range")
    return Pagination(limit=limit, offset=offset)


def parse_optional_uuid_param(req: falcon.Request, name: str) -> uuid.UUID | None:
    """Parse an optional UUID query parameter by name."""
    raw_value = req.get_param(name)
    if raw_value is None:
        return None
    return parse_uuid(raw_value, name)


def parse_enum_param[EnumT: enum.Enum](
    req: falcon.Request,
    name: str,
    enum_type: type[EnumT],
) -> EnumT | None:
    """Parse an optional enum query parameter by name."""
    raw_value = req.get_param(name)
    if raw_value is None:
        return None
    try:
        return enum_type(raw_value)
    except ValueError as exc:
        msg = f"Invalid enum value for {name}: {raw_value!r}."
        raise validation_error(msg, field=name, constraint="enum") from exc


def _parse_int_query_param(
    raw_value: str | None,
    *,
    name: str,
    default: int,
) -> int:
    """Parse an optional integer query parameter or raise a validation error."""
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        msg = f"{name} must be an integer."
        raise validation_error(msg, field=name, constraint="type") from exc
