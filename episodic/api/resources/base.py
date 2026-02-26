"""Shared base resources for Falcon canonical API adapters.

This module provides abstract resource mixins that standardize common GET,
history-list, create, and update endpoint behaviour across concrete adapters.
Subclasses provide identifier extraction, service functions, and serializers,
while the base classes handle payload validation and shared handler dispatch.

Examples
--------
>>> class MyEntityResource(_GetResourceBase): ...
>>> resource = MyEntityResource(uow_factory)  # Handles GET via shared handler.
"""

import collections.abc as cabc
import typing as typ
import uuid
from abc import ABC, abstractmethod

from episodic.api.handlers import (
    handle_create_entity,
    handle_get_entity,
    handle_get_history,
    handle_update_entity,
)
from episodic.api.helpers import require_payload_dict
from episodic.api.types import JsonPayload
from episodic.canonical.profile_templates import (
    UpdateEpisodeTemplateRequest,
    UpdateSeriesProfileRequest,
)

if typ.TYPE_CHECKING:
    import falcon

    from episodic.api.types import UowFactory


# NOTE: request builders accept validated JSON payload and return a typed
# service-layer request object for one of the supported update operations.
type UpdateRequestBuilder = cabc.Callable[
    [uuid.UUID, JsonPayload],
    UpdateSeriesProfileRequest | UpdateEpisodeTemplateRequest,
]


class _ResourceBase(ABC):
    """Shared base resource that stores the unit-of-work factory."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    @staticmethod
    @abstractmethod
    def _resource_base_marker() -> None:
        """Marker hook to keep the base mixin abstract."""


class _GetResourceBase[EntityT: object](_ResourceBase, ABC):
    """Base resource for fetch-by-id endpoints."""

    @staticmethod
    @typ.override
    def _resource_base_marker() -> None:
        """Concrete marker implementation inherited by get resources."""
        pass

    @staticmethod
    @abstractmethod
    def _get_entity_id_from_path(**kwargs: str) -> str:
        """Return the path parameter value used as the entity identifier."""

    @staticmethod
    @abstractmethod
    def _get_id_field_name() -> str:
        """Return the service argument name for the entity identifier."""

    @staticmethod
    @abstractmethod
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]]:
        """Return the fetch service function for the resource."""

    @staticmethod
    @abstractmethod
    def _get_serializer_fn() -> cabc.Callable[[EntityT, int], JsonPayload]:
        """Return the response serializer for the resource."""

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        **kwargs: str,
    ) -> None:
        """Fetch one entity by identifier."""
        del req
        resp.media, resp.status = await handle_get_entity(
            uow_factory=self._uow_factory,
            entity_id=self._get_entity_id_from_path(**kwargs),
            id_field_name=self._get_id_field_name(),
            service_fn=self._get_service_fn(),
            serializer_fn=self._get_serializer_fn(),
        )


class _GetHistoryResourceBase[HistoryT: object](_ResourceBase, ABC):
    """Base resource for history-list endpoints."""

    @staticmethod
    @typ.override
    def _resource_base_marker() -> None:
        """Concrete marker implementation inherited by history resources."""
        pass

    @staticmethod
    @abstractmethod
    def _get_entity_id_from_path(**kwargs: str) -> str:
        """Return the path parameter value used as the entity identifier."""

    @staticmethod
    @abstractmethod
    def _get_id_field_name() -> str:
        """Return the service argument name for the entity identifier."""

    @staticmethod
    @abstractmethod
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[list[HistoryT]]]:
        """Return the history-list service function for the resource."""

    @staticmethod
    @abstractmethod
    def _get_serializer_fn() -> cabc.Callable[[HistoryT], JsonPayload]:
        """Return the item serializer for the resource."""

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        **kwargs: str,
    ) -> None:
        """List history entries for one entity."""
        del req
        resp.media, resp.status = await handle_get_history(
            uow_factory=self._uow_factory,
            entity_id=self._get_entity_id_from_path(**kwargs),
            id_field_name=self._get_id_field_name(),
            service_fn=self._get_service_fn(),
            serializer_fn=self._get_serializer_fn(),
        )


class _CreateResourceBase[EntityT: object](_ResourceBase, ABC):
    """Base resource for create endpoints."""

    @staticmethod
    @typ.override
    def _resource_base_marker() -> None:
        """Concrete marker implementation inherited by create resources."""
        pass

    @staticmethod
    @abstractmethod
    def _get_required_fields() -> tuple[str, ...]:
        """Return required payload fields for create operations."""

    @staticmethod
    @abstractmethod
    def _get_kwargs_builder() -> cabc.Callable[[JsonPayload], dict[str, object]]:
        """Return payload-to-service-kwargs builder."""

    @staticmethod
    @abstractmethod
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]]:
        """Return the create service function for the resource."""

    @staticmethod
    @abstractmethod
    def _get_serializer_fn() -> cabc.Callable[[EntityT, int], JsonPayload]:
        """Return the response serializer for the resource."""

    async def on_post(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        **kwargs: str,
    ) -> None:
        """Create a new entity for a collection endpoint.

        Path params are currently unsupported for create routes. Extend
        ``_get_kwargs_builder`` if nested create routes are introduced.
        """
        del kwargs
        payload = require_payload_dict(await req.get_media())
        resp.media, resp.status = await handle_create_entity(
            uow_factory=self._uow_factory,
            payload=payload,
            required_fields=self._get_required_fields(),
            kwargs_builder=self._get_kwargs_builder(),
            service_fn=self._get_service_fn(),
            serializer_fn=self._get_serializer_fn(),
        )


class _UpdateResourceBase[EntityT: object](_ResourceBase, ABC):
    """Base resource for update-by-id endpoints."""

    @staticmethod
    @typ.override
    def _resource_base_marker() -> None:
        """Concrete marker implementation inherited by update resources."""
        pass

    @staticmethod
    @abstractmethod
    def _get_entity_id_from_path(**kwargs: str) -> str:
        """Return the path parameter value used as the entity identifier."""

    @staticmethod
    @abstractmethod
    def _get_id_field_name() -> str:
        """Return the service argument name for the entity identifier."""

    @staticmethod
    @abstractmethod
    def _get_request_builder() -> UpdateRequestBuilder:
        """Return the payload-to-request-object builder."""

    @staticmethod
    @abstractmethod
    def _get_update_service_fn() -> cabc.Callable[
        ..., cabc.Awaitable[tuple[EntityT, int]]
    ]:
        """Return the update service function for the resource."""

    @staticmethod
    @abstractmethod
    def _get_update_serializer_fn() -> cabc.Callable[[EntityT, int], JsonPayload]:
        """Return the response serializer for the resource."""

    @staticmethod
    def _get_required_fields() -> tuple[str, ...]:
        """Return required payload fields for update operations."""
        return ("expected_revision",)

    async def on_patch(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        **kwargs: str,
    ) -> None:
        """Update one entity by identifier."""
        payload = require_payload_dict(await req.get_media())
        resp.media, resp.status = await handle_update_entity(
            uow_factory=self._uow_factory,
            entity_id=self._get_entity_id_from_path(**kwargs),
            id_field_name=self._get_id_field_name(),
            payload=payload,
            required_fields=self._get_required_fields(),
            request_builder=self._get_request_builder(),
            service_fn=self._get_update_service_fn(),
            serializer_fn=self._get_update_serializer_fn(),
        )
