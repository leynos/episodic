"""Shared Falcon endpoint handlers for canonical API resources.

The module provides reusable request/response helpers for resource adapters:
``handle_get_entity``, ``handle_get_history``, and ``handle_update_entity``.
Resources should import these handlers when they need consistent UUID parsing,
service dispatch, and Falcon HTTP error translation.

Examples
--------
>>> context = HandlerContext(uow_factory=uow_factory)
>>> request = GetEntityRequest(
...     context=context,
...     entity_id=profile_id,
...     id_field_name="profile_id",
...     service_fn=service_fn,
...     serializer_fn=serializer_fn,
... )
>>> media, status = await handle_get_entity(request)
>>> request = HistoryRequest(
...     context=context,
...     entity_id=profile_id,
...     id_field_name="profile_id",
...     service_fn=history_fn,
...     serializer_fn=serializer_fn,
...     page=page,
... )
>>> media, status = await handle_get_history(request)
"""

import dataclasses as dc
import typing as typ

import falcon

from episodic.canonical.profile_templates import (
    RevisionConflictError,
)
from episodic.canonical.profile_templates.types import ProfileTemplateError

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


@dc.dataclass(frozen=True, slots=True)
class HandlerContext:
    """Shared runtime port for the canonical API handler boundary.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory that creates unit-of-work instances.
    """

    uow_factory: UowFactory


@dc.dataclass(frozen=True, slots=True)
class GetEntityRequest[EntityT]:
    """Inputs and ports for one fetch-by-identifier handler call.

    Parameters
    ----------
    context : HandlerContext
        Shared unit-of-work port.
    entity_id : str
        Raw entity identifier from the request path.
    id_field_name : str
        Name of the identifier field used for validation messages.
    service_fn : cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]]
        Service function that returns an entity and its revision.
    serializer_fn : cabc.Callable[[EntityT, int], JsonPayload]
        Serializer that converts the entity payload to response JSON.
    """

    context: HandlerContext
    entity_id: str
    id_field_name: str
    service_fn: cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]]
    serializer_fn: cabc.Callable[[EntityT, int], JsonPayload]


async def handle_get_entity[EntityT](
    request: GetEntityRequest[EntityT],
) -> tuple[JsonPayload, str]:
    """Handle fetch-by-identifier endpoint behaviour.

    Parameters
    ----------
    request : GetEntityRequest[EntityT]
        Handler inputs, service functions and the unit-of-work factory.

    Returns
    -------
    tuple[JsonPayload, str]
        Serialized response payload and HTTP status code.

    Raises
    ------
    falcon.HTTPBadRequest
        If ``entity_id`` is not a valid UUID.
    falcon.HTTPNotFound
        If the requested entity does not exist.
    falcon.HTTPInternalServerError
        If the service raises an unmapped profile/template error.
    """  # ruff: ignore[docstring-extraneous-exception]  # Indirect exceptions form part of this public contract.
    parsed_entity_id = parse_uuid(request.entity_id, request.id_field_name)
    try:
        async with request.context.uow_factory() as uow:
            entity, revision = await request.service_fn(
                uow,
                entity_id=parsed_entity_id,
            )
    except ProfileTemplateError as exc:
        mapped_error = map_profile_template_error(
            exc,
            entity_id=parsed_entity_id,
        )
        raise mapped_error from exc
    return request.serializer_fn(entity, revision), falcon.HTTP_200


@dc.dataclass(frozen=True, slots=True)
class HistoryRequest[EntityT]:
    """Per-call inputs for :func:`handle_get_history`.

    Bundling shared ports, query inputs, and serializer callbacks keeps the
    handler boundary explicit while preserving the shared-resource pattern.
    """

    context: HandlerContext
    entity_id: str
    id_field_name: str
    service_fn: cabc.Callable[..., cabc.Awaitable[tuple[list[EntityT], int]]]
    serializer_fn: cabc.Callable[[EntityT], JsonPayload]
    page: Pagination


async def handle_get_history[EntityT](
    request: HistoryRequest[EntityT],
) -> tuple[JsonPayload, str]:
    """Handle history-list endpoint behaviour.

    Parameters
    ----------
    request : HistoryRequest[EntityT]
        Shared ports, parsed inputs, and service callbacks.

    Returns
    -------
    tuple[JsonPayload, str]
        JSON object containing serialized ``items`` and HTTP status code.

    Raises
    ------
    falcon.HTTPBadRequest
        If the parent entity identifier is not a valid UUID.
    falcon.HTTPNotFound
        If the requested parent entity does not exist.
    falcon.HTTPInternalServerError
        If the service raises an unmapped profile/template error.
    """  # ruff: ignore[docstring-extraneous-exception]  # Indirect exceptions form part of this public contract.
    parsed_entity_id = parse_uuid(request.entity_id, request.id_field_name)
    try:
        async with request.context.uow_factory() as uow:
            items, total = await request.service_fn(
                uow,
                parent_id=parsed_entity_id,
                page=request.page,
            )
    except ProfileTemplateError as exc:
        mapped_error = map_profile_template_error(
            exc,
            entity_id=parsed_entity_id,
        )
        raise mapped_error from exc
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
    exc: ProfileTemplateError,
    *,
    entity_id: uuid.UUID,
    expected_revision: int | None,
) -> typ.NoReturn:
    """Re-raise a domain update error as a typed envelope-aware Falcon error.

    ``expected_revision`` is only attached to ``revision_conflict`` envelopes;
    callers should pass the parsed integer from the typed update request so
    the envelope ``details`` stays type-stable (no raw payload values leak
    into the response).

    Raises
    ------
    falcon.HTTPNotFound
        If the target entity does not exist.
    falcon.HTTPConflict
        If the expected revision does not match the persisted revision.
    falcon.HTTPInternalServerError
        If the service raises an unmapped profile/template error.
    """  # ruff: ignore[docstring-missing-exception, docstring-extraneous-exception]  # The mapper returns these concrete Falcon exceptions.
    raise map_profile_template_error(
        exc,
        entity_id=entity_id,
        expected_revision=(
            expected_revision if isinstance(exc, RevisionConflictError) else None
        ),
    ) from exc


@dc.dataclass(frozen=True, slots=True)
class UpdateEntityRequest[EntityT]:
    """Inputs and collaborators for one optimistic-lock update handler call.

    Parameters
    ----------
    context : HandlerContext
        Shared unit-of-work port.
    entity_id : str
        Raw entity identifier from the request path.
    id_field_name : str
        Name of the identifier field used for validation messages.
    payload : JsonPayload
        Parsed request payload.
    required_fields : tuple[str, ...]
        Required payload fields for the update operation.
    request_builder : cabc.Callable
        Builder that creates a typed update request from the parsed payload.
    service_fn : cabc.Callable
        Service function that executes the update.
    serializer_fn : cabc.Callable
        Serializer that converts the updated entity to response JSON.
    """

    context: HandlerContext
    entity_id: str
    id_field_name: str
    payload: JsonPayload
    required_fields: tuple[str, ...]
    request_builder: cabc.Callable[
        [uuid.UUID, JsonPayload],
        UpdateSeriesProfileRequest | UpdateEpisodeTemplateRequest,
    ]
    service_fn: cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]]
    serializer_fn: cabc.Callable[[EntityT, int], JsonPayload]


async def handle_update_entity[EntityT](
    request: UpdateEntityRequest[EntityT],
) -> tuple[JsonPayload, str]:
    """Handle optimistic-lock update endpoint behaviour.

    Parameters
    ----------
    request : UpdateEntityRequest[EntityT]
        Parsed inputs and service collaborators.

    Returns
    -------
    tuple[JsonPayload, str]
        Serialized response payload and HTTP status code.

    Raises
    ------
    falcon.HTTPBadRequest
        If the identifier, required fields, or update payload are invalid.
    falcon.HTTPNotFound
        If the target entity does not exist.
    falcon.HTTPConflict
        If the expected revision does not match the persisted revision.
    falcon.HTTPInternalServerError
        If the service raises an unmapped profile/template error.
    """  # ruff: ignore[docstring-extraneous-exception]  # Indirect exceptions form part of this public contract.
    parsed_entity_id = parse_uuid(request.entity_id, request.id_field_name)
    _require_payload_fields(request.payload, request.required_fields)
    update_request = request.request_builder(parsed_entity_id, request.payload)
    try:
        async with request.context.uow_factory() as uow:
            entity, revision = await request.service_fn(
                uow,
                request=update_request,
            )
    except ProfileTemplateError as exc:
        _raise_mapped_update_error(
            exc,
            entity_id=parsed_entity_id,
            expected_revision=update_request.expected_revision,
        )
    return request.serializer_fn(entity, revision), falcon.HTTP_200


@dc.dataclass(frozen=True, slots=True)
class CreateEntityRequest[EntityT]:
    """Inputs and collaborators for one create-entity handler call.

    Parameters
    ----------
    context : HandlerContext
        Shared unit-of-work port.
    payload : JsonPayload
        Parsed request payload.
    required_fields : tuple[str, ...]
        Required fields for the create operation.
    kwargs_builder : cabc.Callable
        Builder that maps payload values into service keyword arguments.
    service_fn : cabc.Callable
        Service function that creates and returns an entity and revision.
    serializer_fn : cabc.Callable
        Serializer that converts the created entity to response JSON.
    """

    context: HandlerContext
    payload: JsonPayload
    required_fields: tuple[str, ...]
    kwargs_builder: cabc.Callable[[JsonPayload], dict[str, object]]
    service_fn: cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]]
    serializer_fn: cabc.Callable[[EntityT, int], JsonPayload]


async def handle_create_entity[EntityT](
    request: CreateEntityRequest[EntityT],
) -> tuple[JsonPayload, str]:
    """Handle create endpoint behaviour.

    Parameters
    ----------
    request : CreateEntityRequest[EntityT]
        Parsed payload and service collaborators.

    Returns
    -------
    tuple[JsonPayload, str]
        Serialized response payload and HTTP status code.

    Raises
    ------
    falcon.HTTPBadRequest
        If a required field is missing or the create payload is invalid.
    falcon.HTTPNotFound
        If a referenced entity required for creation does not exist.
    falcon.HTTPInternalServerError
        If the service raises an unmapped profile/template error.
    """  # ruff: ignore[docstring-missing-exception, docstring-extraneous-exception]  # Indirect exceptions form part of this public contract.
    _require_payload_fields(request.payload, request.required_fields)

    service_kwargs = request.kwargs_builder(request.payload)
    try:
        async with request.context.uow_factory() as uow:
            entity, revision = await request.service_fn(uow, **service_kwargs)
    except ProfileTemplateError as exc:
        raise map_profile_template_error(
            exc,
        ) from exc
    except LookupError as exc:
        raise falcon.HTTPNotFound(description=str(exc)) from exc
    return request.serializer_fn(entity, revision), falcon.HTTP_201
