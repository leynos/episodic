"""Reusable endpoint handlers shared across Falcon resources."""

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


async def handle_get_entity[EntityT](  # noqa: PLR0913, PLR0917
    uow_factory: UowFactory,
    entity_id: str,
    id_field_name: str,
    service_fn: cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]],
    serializer_fn: cabc.Callable[[EntityT, int], dict[str, typ.Any]],
) -> tuple[dict[str, typ.Any], str]:
    """Handle common fetch-by-id endpoint behaviour."""
    parsed_entity_id = parse_uuid(entity_id, id_field_name)
    try:
        async with uow_factory() as uow:
            entity, revision = await service_fn(
                uow,
                **{id_field_name: parsed_entity_id},
            )
    except EntityNotFoundError as exc:
        raise falcon.HTTPNotFound(description=str(exc)) from exc
    return serializer_fn(entity, revision), falcon.HTTP_200


async def handle_get_history[EntityT](  # noqa: PLR0913, PLR0917
    uow_factory: UowFactory,
    entity_id: str,
    id_field_name: str,
    service_fn: cabc.Callable[..., cabc.Awaitable[list[EntityT]]],
    serializer_fn: cabc.Callable[[EntityT], dict[str, typ.Any]],
) -> tuple[dict[str, typ.Any], str]:
    """Handle common history-list endpoint behaviour."""
    parsed_entity_id = parse_uuid(entity_id, id_field_name)
    async with uow_factory() as uow:
        items = await service_fn(uow, **{id_field_name: parsed_entity_id})
    return {"items": [serializer_fn(item) for item in items]}, falcon.HTTP_200


async def handle_update_entity[EntityT](  # noqa: PLR0913, PLR0917
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
    serializer_fn: cabc.Callable[[EntityT, int], dict[str, typ.Any]],
) -> tuple[dict[str, typ.Any], str]:
    """Handle common optimistic-lock update endpoint behaviour."""
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
