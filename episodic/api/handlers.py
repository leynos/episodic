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

from __future__ import annotations

import typing as typ

import falcon

from episodic.canonical.profile_templates import (
    EntityNotFoundError,
    RevisionConflictError,
    UpdateEpisodeTemplateRequest,
    UpdateSeriesProfileRequest,
)

from .helpers import parse_uuid

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from .types import UowFactory


type JsonPayload = dict[str, object]


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
        Serialised response payload and HTTP status code.

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
        raise falcon.HTTPNotFound(description=str(exc)) from exc
    return serializer_fn(entity, revision), falcon.HTTP_200


async def handle_get_history[EntityT](  # noqa: PLR0913, PLR0917  # TODO(@episodic-dev): https://github.com/leynos/episodic/issues/1234 explicit shared handler signature for resource adapters
    uow_factory: UowFactory,
    entity_id: str,
    id_field_name: str,
    service_fn: cabc.Callable[..., cabc.Awaitable[list[EntityT]]],
    serializer_fn: cabc.Callable[[EntityT], JsonPayload],
) -> tuple[JsonPayload, str]:
    """Handle history-list endpoint behaviour.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory that creates unit-of-work instances.
    entity_id : str
        Raw parent-entity identifier from the request path.
    id_field_name : str
        Name of the identifier field used for validation messages.
    service_fn : cabc.Callable[..., cabc.Awaitable[list[EntityT]]]
        Service function that returns history entries for one parent entity.
    serializer_fn : cabc.Callable[[EntityT], JsonPayload]
        Serializer for a single history entry.

    Returns
    -------
    tuple[JsonPayload, str]
        JSON object containing serialised ``items`` and HTTP status code.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when ``entity_id`` is not a valid UUID.
    falcon.HTTPNotFound
        Raised when the parent entity is not found.
    """
    parsed_entity_id = parse_uuid(entity_id, id_field_name)
    try:
        async with uow_factory() as uow:
            items = await service_fn(
                uow,
                parent_id=parsed_entity_id,
            )
    except EntityNotFoundError as exc:
        raise falcon.HTTPNotFound(
            title="Not Found",
            description="Parent entity not found",
        ) from exc
    return {"items": [serializer_fn(item) for item in items]}, falcon.HTTP_200


async def handle_update_entity[EntityT](  # noqa: PLR0913, PLR0917  # TODO(@episodic-dev): https://github.com/leynos/episodic/issues/1234 explicit shared handler signature for resource adapters
    uow_factory: UowFactory,
    entity_id: str,
    id_field_name: str,
    payload: dict[str, typ.Any],
    required_fields: tuple[str, ...],
    request_builder: cabc.Callable[
        [uuid.UUID, dict[str, typ.Any]],
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
    payload : dict[str, typ.Any]
        Parsed request payload.
    required_fields : tuple[str, ...]
        Required payload field names for the update operation.
    request_builder : cabc.Callable[
        [uuid.UUID, dict[str, typ.Any]],
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
        Serialised response payload and HTTP status code.

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
    for field_name in required_fields:
        if field_name not in payload:
            msg = f"Missing required field: {field_name}"
            raise falcon.HTTPBadRequest(description=msg)

    update_request = request_builder(parsed_entity_id, payload)

    try:
        async with uow_factory() as uow:
            entity, revision = await service_fn(
                uow,
                request=update_request,
            )
    except EntityNotFoundError as exc:
        raise falcon.HTTPNotFound(description=str(exc)) from exc
    except RevisionConflictError as exc:
        raise falcon.HTTPConflict(description=str(exc)) from exc
    return serializer_fn(entity, revision), falcon.HTTP_200


async def handle_create_entity[EntityT](  # noqa: PLR0913  # TODO(@episodic-dev): https://github.com/leynos/episodic/issues/1234 explicit shared creator signature for resource adapters
    uow_factory: UowFactory,
    payload: dict[str, typ.Any],
    *,
    required_fields: tuple[str, ...],
    kwargs_builder: cabc.Callable[[dict[str, typ.Any]], dict[str, object]],
    service_fn: cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]],
    serializer_fn: cabc.Callable[[EntityT, int], JsonPayload],
) -> tuple[JsonPayload, str]:
    """Handle create endpoint behaviour.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory that creates unit-of-work instances.
    payload : dict[str, typ.Any]
        Parsed request payload.
    required_fields : tuple[str, ...]
        Required payload field names for the create operation.
    kwargs_builder : cabc.Callable[[dict[str, typ.Any]], dict[str, object]]
        Builder that maps payload values into service keyword arguments.
    service_fn : cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]]
        Service function that creates an entity and returns entity/revision.
    serializer_fn : cabc.Callable[[EntityT, int], JsonPayload]
        Serializer that converts the created entity to response JSON.

    Returns
    -------
    tuple[JsonPayload, str]
        Serialised response payload and HTTP status code.

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
            raise falcon.HTTPBadRequest(description=msg)

    service_kwargs = kwargs_builder(payload)
    try:
        async with uow_factory() as uow:
            entity, revision = await service_fn(uow, **service_kwargs)
    except LookupError as exc:
        raise falcon.HTTPNotFound(description=str(exc)) from exc
    return serializer_fn(entity, revision), falcon.HTTP_201
