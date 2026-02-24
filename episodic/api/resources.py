"""Falcon resource adapters for canonical profile/template endpoints.

This module defines route-bound resource classes, including
``SeriesProfilesResource``, ``SeriesProfileResource``,
``SeriesProfileHistoryResource``, ``SeriesProfileBriefResource``,
``EpisodeTemplatesResource``, ``EpisodeTemplateResource``, and
``EpisodeTemplateHistoryResource``. Each resource maps Falcon request objects to
canonical service calls and serialises service-layer outputs into HTTP payloads.

Examples
--------
Create a resource and attach it to a Falcon route:

>>> resource = SeriesProfilesResource(uow_factory)
>>> app.add_route("/series-profiles", resource)
"""

from __future__ import annotations

import collections.abc as cabc
import typing as typ
from abc import ABC, abstractmethod
from functools import partial
from itertools import starmap

import falcon

from episodic.canonical.briefs import build_series_brief
from episodic.canonical.profile_templates import (
    EntityNotFoundError,
    create_episode_template,
    create_series_profile,
    get_entity_with_revision,
    list_entities_with_revisions,
    list_history,
    update_episode_template,
    update_series_profile,
)

from .handlers import (
    handle_create_entity,
    handle_get_entity,
    handle_get_history,
    handle_update_entity,
)
from .helpers import (
    build_profile_create_kwargs,
    build_profile_update_request,
    build_template_create_kwargs,
    build_template_update_request,
    parse_uuid,
    require_payload_dict,
)
from .serializers import (
    serialize_episode_template,
    serialize_episode_template_history_entry,
    serialize_series_profile,
    serialize_series_profile_history_entry,
)

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.profile_templates import (
        UpdateEpisodeTemplateRequest,
        UpdateSeriesProfileRequest,
    )

    from .types import UowFactory


type JsonPayload = dict[str, object]
type UpdateRequestBuilder = cabc.Callable[
    [uuid.UUID, dict[str, typ.Any]],
    UpdateSeriesProfileRequest | UpdateEpisodeTemplateRequest,
]


class _GetResourceBase(ABC):
    """Base resource for fetch-by-id endpoints."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

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
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]:
        """Return the fetch service function for the resource."""

    @staticmethod
    @abstractmethod
    def _get_serializer_fn() -> cabc.Callable[[object, int], JsonPayload]:
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


class _GetHistoryResourceBase(ABC):
    """Base resource for history-list endpoints."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

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
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[list[object]]]:
        """Return the history-list service function for the resource."""

    @staticmethod
    @abstractmethod
    def _get_serializer_fn() -> cabc.Callable[[object], JsonPayload]:
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


class _CreateResourceBase(ABC):
    """Base resource for create endpoints."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    @staticmethod
    @abstractmethod
    def _get_required_fields() -> tuple[str, ...]:
        """Return required payload fields for create operations."""

    @staticmethod
    @abstractmethod
    def _get_kwargs_builder() -> cabc.Callable[[dict[str, typ.Any]], dict[str, object]]:
        """Return payload-to-service-kwargs builder."""

    @staticmethod
    @abstractmethod
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]:
        """Return the create service function for the resource."""

    @staticmethod
    @abstractmethod
    def _get_serializer_fn() -> cabc.Callable[[object, int], JsonPayload]:
        """Return the response serializer for the resource."""

    async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        """Create a new entity for a collection endpoint."""
        payload = require_payload_dict(await req.get_media())
        resp.media, resp.status = await handle_create_entity(
            uow_factory=self._uow_factory,
            payload=payload,
            required_fields=self._get_required_fields(),
            kwargs_builder=self._get_kwargs_builder(),
            service_fn=self._get_service_fn(),
            serializer_fn=self._get_serializer_fn(),
        )


class _UpdateResourceBase(ABC):
    """Base resource for update-by-id endpoints."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

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
        ..., cabc.Awaitable[tuple[object, int]]
    ]:
        """Return the update service function for the resource."""

    @staticmethod
    @abstractmethod
    def _get_update_serializer_fn() -> cabc.Callable[[object, int], JsonPayload]:
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


class SeriesProfilesResource(_CreateResourceBase):
    """Handle collection operations for series profiles.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory used to create request-scoped units of work.

    Raises
    ------
    falcon.HTTPBadRequest
        Raised when required payload fields are missing during creation.
    """

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """List all series profiles.

        Parameters
        ----------
        req : falcon.Request
            Incoming Falcon request object.
        resp : falcon.Response
            Outgoing Falcon response object populated by this handler.

        Returns
        -------
        None
            Response media is set to an ``items`` list and status ``200``.
        """
        del req
        service_fn = partial(list_entities_with_revisions, kind="series_profile")
        async with self._uow_factory() as uow:
            items = await service_fn(uow)

        resp.media = {"items": list(starmap(serialize_series_profile, items))}
        resp.status = falcon.HTTP_200

    @staticmethod
    @typ.override
    def _get_required_fields() -> tuple[str, ...]:
        """Return required payload fields for profile creation."""
        return ("slug", "title", "configuration")

    @staticmethod
    @typ.override
    def _get_kwargs_builder() -> cabc.Callable[[dict[str, typ.Any]], dict[str, object]]:
        """Return the profile create kwargs builder."""
        return build_profile_create_kwargs

    @staticmethod
    @typ.override
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]:
        """Return the profile create service."""
        return typ.cast(
            "cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]",
            create_series_profile,
        )

    @staticmethod
    @typ.override
    def _get_serializer_fn() -> cabc.Callable[[object, int], JsonPayload]:
        """Return the profile serializer."""
        return typ.cast(
            "cabc.Callable[[object, int], JsonPayload]",
            serialize_series_profile,
        )


class SeriesProfileResource(_UpdateResourceBase, _GetResourceBase):
    """Handle single-entity operations for series profiles.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory used to create request-scoped units of work.
    """

    @staticmethod
    @typ.override
    def _get_entity_id_from_path(**kwargs: str) -> str:
        """Return the profile identifier from route params."""
        return kwargs["profile_id"]

    @staticmethod
    @typ.override
    def _get_id_field_name() -> str:
        """Return the profile identifier service argument."""
        return "profile_id"

    @staticmethod
    @typ.override
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]:
        """Return the profile fetch service."""
        return typ.cast(
            "cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]",
            partial(get_entity_with_revision, kind="series_profile"),
        )

    @staticmethod
    @typ.override
    def _get_serializer_fn() -> cabc.Callable[[object, int], JsonPayload]:
        """Return the profile serializer."""
        return typ.cast(
            "cabc.Callable[[object, int], JsonPayload]",
            serialize_series_profile,
        )

    @staticmethod
    @typ.override
    def _get_request_builder() -> UpdateRequestBuilder:
        """Return the profile update-request builder."""
        return build_profile_update_request

    @staticmethod
    @typ.override
    def _get_update_service_fn() -> cabc.Callable[
        ..., cabc.Awaitable[tuple[object, int]]
    ]:
        """Return the profile update service."""
        return typ.cast(
            "cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]",
            update_series_profile,
        )

    @staticmethod
    @typ.override
    def _get_update_serializer_fn() -> cabc.Callable[[object, int], JsonPayload]:
        """Return the profile update serializer."""
        return typ.cast(
            "cabc.Callable[[object, int], JsonPayload]",
            serialize_series_profile,
        )

    @staticmethod
    @typ.override
    def _get_required_fields() -> tuple[str, ...]:
        """Return required payload fields for profile updates."""
        return ("expected_revision", "title", "configuration")


class SeriesProfileHistoryResource(_GetHistoryResourceBase):
    """Handle history retrieval for series profiles.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory used to create request-scoped units of work.
    """

    @staticmethod
    @typ.override
    def _get_entity_id_from_path(**kwargs: str) -> str:
        """Return the profile identifier from route params."""
        return kwargs["profile_id"]

    @staticmethod
    @typ.override
    def _get_id_field_name() -> str:
        """Return the profile identifier service argument."""
        return "profile_id"

    @staticmethod
    @typ.override
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[list[object]]]:
        """Return the profile-history list service."""
        return typ.cast(
            "cabc.Callable[..., cabc.Awaitable[list[object]]]",
            partial(list_history, kind="series_profile"),
        )

    @staticmethod
    @typ.override
    def _get_serializer_fn() -> cabc.Callable[[object], JsonPayload]:
        """Return the profile-history serializer."""
        return typ.cast(
            "cabc.Callable[[object], JsonPayload]",
            serialize_series_profile_history_entry,
        )


class SeriesProfileBriefResource:
    """Return structured brief payloads for series profiles.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory used to create request-scoped units of work.
    """

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
    ) -> None:
        """Fetch a structured brief payload.

        Parameters
        ----------
        req : falcon.Request
            Incoming request, optionally including ``template_id`` query param.
        resp : falcon.Response
            Outgoing response object populated by this handler.
        profile_id : str
            Raw series-profile identifier from the route path.

        Returns
        -------
        None
            Response media is set to the brief payload and status ``200``.

        Raises
        ------
        falcon.HTTPBadRequest
            Raised when ``profile_id`` or ``template_id`` is not a valid UUID.
        falcon.HTTPNotFound
            Raised when the requested profile or template is not found.
        """
        parsed_profile_id = parse_uuid(profile_id, "profile_id")
        raw_template_id = req.get_param("template_id")
        template_id = (
            None
            if raw_template_id is None
            else parse_uuid(
                raw_template_id,
                "template_id",
            )
        )

        try:
            async with self._uow_factory() as uow:
                payload = await build_series_brief(
                    uow,
                    profile_id=parsed_profile_id,
                    template_id=template_id,
                )
        except EntityNotFoundError as exc:
            raise falcon.HTTPNotFound(description=str(exc)) from exc

        resp.media = payload
        resp.status = falcon.HTTP_200


class EpisodeTemplatesResource(_CreateResourceBase):
    """Handle collection operations for episode templates.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory used to create request-scoped units of work.
    """

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """List episode templates.

        Parameters
        ----------
        req : falcon.Request
            Incoming request, optionally including ``series_profile_id``.
        resp : falcon.Response
            Outgoing response object populated by this handler.

        Returns
        -------
        None
            Response media is set to an ``items`` list and status ``200``.

        Raises
        ------
        falcon.HTTPBadRequest
            Raised when ``series_profile_id`` is provided but invalid.
        """
        raw_series_profile_id = req.get_param("series_profile_id")
        series_profile_id = (
            None
            if raw_series_profile_id is None
            else parse_uuid(raw_series_profile_id, "series_profile_id")
        )

        async with self._uow_factory() as uow:
            service_fn = partial(list_entities_with_revisions, kind="episode_template")
            items = await service_fn(
                uow,
                series_profile_id=series_profile_id,
            )

        resp.media = {"items": list(starmap(serialize_episode_template, items))}
        resp.status = falcon.HTTP_200

    @staticmethod
    @typ.override
    def _get_required_fields() -> tuple[str, ...]:
        """Return required payload fields for template creation."""
        return ("series_profile_id", "slug", "title", "structure")

    @staticmethod
    @typ.override
    def _get_kwargs_builder() -> cabc.Callable[[dict[str, typ.Any]], dict[str, object]]:
        """Return the template create kwargs builder."""
        return build_template_create_kwargs

    @staticmethod
    @typ.override
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]:
        """Return the template create service."""
        return typ.cast(
            "cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]",
            create_episode_template,
        )

    @staticmethod
    @typ.override
    def _get_serializer_fn() -> cabc.Callable[[object, int], JsonPayload]:
        """Return the template serializer."""
        return typ.cast(
            "cabc.Callable[[object, int], JsonPayload]",
            serialize_episode_template,
        )


class EpisodeTemplateResource(_UpdateResourceBase, _GetResourceBase):
    """Handle single-entity operations for episode templates.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory used to create request-scoped units of work.
    """

    @staticmethod
    @typ.override
    def _get_entity_id_from_path(**kwargs: str) -> str:
        """Return the template identifier from route params."""
        return kwargs["template_id"]

    @staticmethod
    @typ.override
    def _get_id_field_name() -> str:
        """Return the template identifier service argument."""
        return "template_id"

    @staticmethod
    @typ.override
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]:
        """Return the template fetch service."""
        return typ.cast(
            "cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]",
            partial(get_entity_with_revision, kind="episode_template"),
        )

    @staticmethod
    @typ.override
    def _get_serializer_fn() -> cabc.Callable[[object, int], JsonPayload]:
        """Return the template serializer."""
        return typ.cast(
            "cabc.Callable[[object, int], JsonPayload]",
            serialize_episode_template,
        )

    @staticmethod
    @typ.override
    def _get_request_builder() -> UpdateRequestBuilder:
        """Return the template update-request builder."""
        return build_template_update_request

    @staticmethod
    @typ.override
    def _get_update_service_fn() -> cabc.Callable[
        ..., cabc.Awaitable[tuple[object, int]]
    ]:
        """Return the template update service."""
        return typ.cast(
            "cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]",
            update_episode_template,
        )

    @staticmethod
    @typ.override
    def _get_update_serializer_fn() -> cabc.Callable[[object, int], JsonPayload]:
        """Return the template update serializer."""
        return typ.cast(
            "cabc.Callable[[object, int], JsonPayload]",
            serialize_episode_template,
        )

    @staticmethod
    @typ.override
    def _get_required_fields() -> tuple[str, ...]:
        """Return required payload fields for template updates."""
        return ("expected_revision", "title", "structure")


class EpisodeTemplateHistoryResource(_GetHistoryResourceBase):
    """Handle history retrieval for episode templates.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory used to create request-scoped units of work.
    """

    @staticmethod
    @typ.override
    def _get_entity_id_from_path(**kwargs: str) -> str:
        """Return the template identifier from route params."""
        return kwargs["template_id"]

    @staticmethod
    @typ.override
    def _get_id_field_name() -> str:
        """Return the template identifier service argument."""
        return "template_id"

    @staticmethod
    @typ.override
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[list[object]]]:
        """Return the template-history list service."""
        return typ.cast(
            "cabc.Callable[..., cabc.Awaitable[list[object]]]",
            partial(list_history, kind="episode_template"),
        )

    @staticmethod
    @typ.override
    def _get_serializer_fn() -> cabc.Callable[[object], JsonPayload]:
        """Return the template-history serializer."""
        return typ.cast(
            "cabc.Callable[[object], JsonPayload]",
            serialize_episode_template_history_entry,
        )
