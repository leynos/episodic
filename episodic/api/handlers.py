"""Shared Falcon endpoint handlers for canonical API resources.

The module provides reusable request/response helpers for resource adapters:
``handle_get_entity``, ``handle_get_history``, and ``handle_update_entity``.
Resources should import these handlers when they need consistent UUID parsing,
service dispatch, and Falcon HTTP error translation.

Examples
--------
>>> media, status = await handle_get_entity(
...     factory, profile_id, "profile_id", service_fn, serializer_fn
... )
>>> media, status = await handle_get_history(
...     factory, profile_id, "profile_id", history_fn, serializer_fn
... )
"""

import dataclasses as dc
import typing as typ

import falcon

from episodic.canonical.profile_templates import (
    EntityNotFoundError,
    RevisionConflictError,
)

from .errors import map_profile_template_error, validation_error
from .helpers import parse_uuid

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.canonical.pagination import Pagination
    from episodic.canonical.profile_templates import (
        UpdateEpisodeTemplateRequest,
        UpdateSeriesProfileRequest,
    )

    from .types import JsonPayload, UowFactory


async def handle_get_entity[EntityT](  # noqa: PLR0913, PLR0917  # TODO(@episodic-dev): https://github.com/leynos/episodic/issues/1234 explicit shared handler signature for resource adapters
    uow_factory: UowFactory,
    entity_id: str,
    id_field_name: str,
    service_fn: cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]],
    serializer_fn: cabc.Callable[[EntityT, int], JsonPayload],
) -> tuple[JsonPayload, str]:
    """Handle fetch-by-identifier endpoint behaviour.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory that creates unit-of-work instances.
    entity_id : str
        Raw entity identifier from the request path.
    id_field_name : str
        Name of the identifier field used for validation messages.
    service_fn : cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]]
        Service function that returns an entity and its revision.
    serializer_fn : cabc.Callable[[EntityT, int], JsonPayload]
        Serializer that converts the entity payload to response JSON.

    Returns
    -------
    tuple[JsonPayload, str]
        Serialized response payload and HTTP status code.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when ``entity_id`` is not a valid UUID.
    falcon.HTTPNotFound
        Raised when the requested entity does not exist.
    """
    parsed_entity_id = parse_uuid(entity_id, id_field_name)
    try:
        async with uow_factory() as uow:
            entity, revision = await service_fn(
                uow,
                entity_id=parsed_entity_id,
            )
    except EntityNotFoundError as exc:
        raise map_profile_template_error(exc, entity_id=parsed_entity_id) from exc
    return serializer_fn(entity, revision), falcon.HTTP_200


@dc.dataclass(frozen=True, slots=True)
class HistoryRequest[EntityT]:
    """Per-call inputs for :func:`handle_get_history`.

    Bundling these fields keeps the public handler signature small while
    preserving the shared-base resource pattern that the canonical history
    resources rely on.
    """

    entity_id: str
    id_field_name: str
    service_fn: cabc.Callable[..., cabc.Awaitable[tuple[list[EntityT], int]]]
    serializer_fn: cabc.Callable[[EntityT], JsonPayload]
    page: Pagination


async def handle_get_history[EntityT](
    uow_factory: UowFactory,
    request: HistoryRequest[EntityT],
) -> tuple[JsonPayload, str]:
    """Handle history-list endpoint behaviour.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory that creates unit-of-work instances.
    request : HistoryRequest[EntityT]
        Parsed history-list inputs: parent identifier, service callable,
        serializer, and pagination.

    Returns
    -------
    tuple[JsonPayload, str]
        JSON object containing serialized ``items`` and HTTP status code.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when ``request.entity_id`` is not a valid UUID.
    falcon.HTTPNotFound
        Raised when the parent entity is not found.
    """
    parsed_entity_id = parse_uuid(request.entity_id, request.id_field_name)
    try:
        async with uow_factory() as uow:
            items, total = await request.service_fn(
                uow,
                parent_id=parsed_entity_id,
                page=request.page,
            )
    except EntityNotFoundError as exc:
        raise map_profile_template_error(exc, entity_id=parsed_entity_id) from exc
    return (
        {
            "items": [request.serializer_fn(item) for item in items],
            "limit": request.page.limit,
            "offset": request.page.offset,
            "total": total,
        },
        falcon.HTTP_200,
    )


def _require_payload_fields(
    payload: JsonPayload, required_fields: cabc.Sequence[str]
) -> None:
    """Raise ``validation_error`` for the first missing required payload field."""
    for field_name in required_fields:
        if field_name not in payload:
            msg = f"Missing required field: {field_name}"
            raise validation_error(msg, field=field_name, constraint="required")


def _raise_mapped_update_error(
    exc: EntityNotFoundError | RevisionConflictError,
    *,
    entity_id: uuid.UUID,
    expected_revision: int | None,
) -> typ.NoReturn:
    """Re-raise a domain update error as a typed envelope-aware Falcon error.

    ``expected_revision`` is only attached to ``revision_conflict`` envelopes;
    callers should pass the parsed integer from the typed update request so
    the envelope ``details`` stays type-stable (no raw payload values leak
    into the response).
    """
    raise map_profile_template_error(
        exc,
        entity_id=entity_id,
        expected_revision=(
            expected_revision if isinstance(exc, RevisionConflictError) else None
        ),
    ) from exc


async def handle_update_entity[EntityT](  # noqa: PLR0913, PLR0917  # TODO(@episodic-dev): https://github.com/leynos/episodic/issues/1234 explicit shared handler signature for resource adapters
    uow_factory: UowFactory,
    entity_id: str,
    id_field_name: str,
    payload: JsonPayload,
    required_fields: tuple[str, ...],
    request_builder: cabc.Callable[
        [uuid.UUID, JsonPayload],
        UpdateSeriesProfileRequest | UpdateEpisodeTemplateRequest,
    ],
    service_fn: cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]],
    serializer_fn: cabc.Callable[[EntityT, int], JsonPayload],
) -> tuple[JsonPayload, str]:
    """Handle optimistic-lock update endpoint behaviour.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory that creates unit-of-work instances.
    entity_id : str
        Raw entity identifier from the request path.
    id_field_name : str
        Name of the identifier field used for validation messages.
    payload : JsonPayload
        Parsed request payload.
    required_fields : tuple[str, ...]
        Required payload field names for the update operation.
    request_builder : cabc.Callable[
        [uuid.UUID, JsonPayload],
        UpdateSeriesProfileRequest | UpdateEpisodeTemplateRequest,
    ]
        Builder that creates a typed update request object.
    service_fn : cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]]
        Service function that executes the update and returns entity/revision.
    serializer_fn : cabc.Callable[[EntityT, int], JsonPayload]
        Serializer that converts the updated entity to response JSON.

    Returns
    -------
    tuple[JsonPayload, str]
        Serialized response payload and HTTP status code.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when required fields are missing or the identifier is invalid.
    falcon.HTTPNotFound
        Raised when the target entity does not exist.
    falcon.HTTPConflict
        Raised when optimistic-lock revision preconditions fail.
    """
    parsed_entity_id = parse_uuid(entity_id, id_field_name)
    _require_payload_fields(payload, required_fields)
    update_request = request_builder(parsed_entity_id, payload)
    try:
        async with uow_factory() as uow:
            entity, revision = await service_fn(uow, request=update_request)
    except (EntityNotFoundError, RevisionConflictError) as exc:
        _raise_mapped_update_error(
            exc,
            entity_id=parsed_entity_id,
            expected_revision=update_request.expected_revision,
        )
    return serializer_fn(entity, revision), falcon.HTTP_200


async def handle_create_entity[EntityT](  # noqa: PLR0913  # TODO(@episodic-dev): https://github.com/leynos/episodic/issues/1234 explicit shared creator signature for resource adapters
    uow_factory: UowFactory,
    payload: JsonPayload,
    *,
    required_fields: tuple[str, ...],
    kwargs_builder: cabc.Callable[[JsonPayload], dict[str, object]],
    service_fn: cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]],
    serializer_fn: cabc.Callable[[EntityT, int], JsonPayload],
) -> tuple[JsonPayload, str]:
    """Handle create endpoint behaviour.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory that creates unit-of-work instances.
    payload : JsonPayload
        Parsed request payload.
    required_fields : tuple[str, ...]
        Required payload field names for the create operation.
    kwargs_builder : cabc.Callable[[JsonPayload], dict[str, object]]
        Builder that maps payload values into service keyword arguments.
    service_fn : cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]]
        Service function that creates an entity and returns entity/revision.
    serializer_fn : cabc.Callable[[EntityT, int], JsonPayload]
        Serializer that converts the created entity to response JSON.

    Returns
    -------
    tuple[JsonPayload, str]
        Serialized response payload and HTTP status code.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when required fields are missing.
    falcon.HTTPNotFound
        Raised when create preconditions reference unknown entities.
    """
    for field_name in required_fields:
        if field_name not in payload:
            msg = f"Missing required field: {field_name}"
            raise validation_error(msg, field=field_name, constraint="required")

    service_kwargs = kwargs_builder(payload)
    try:
        async with uow_factory() as uow:
            entity, revision = await service_fn(uow, **service_kwargs)
    except (EntityNotFoundError, LookupError) as exc:
        if isinstance(exc, EntityNotFoundError):
            raise map_profile_template_error(exc) from exc
        raise falcon.HTTPNotFound(description=str(exc)) from exc
    return serializer_fn(entity, revision), falcon.HTTP_201
