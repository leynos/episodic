"""Falcon resources for profile and template endpoints."""

from __future__ import annotations

import typing as typ
from abc import ABC, abstractmethod
from functools import partial
from itertools import starmap

import falcon

from episodic.canonical.briefs import build_series_brief
from episodic.canonical.profile_templates import (
    EntityNotFoundError,
    EpisodeTemplateData,
    SeriesProfileCreateData,
    create_episode_template,
    create_series_profile,
    get_entity_with_revision,
    list_entities_with_revisions,
    list_history,
    update_episode_template,
    update_series_profile,
)

from .handlers import handle_get_entity, handle_get_history, handle_update_entity
from .helpers import (
    build_audit_metadata,
    build_profile_update_request,
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
    import collections.abc as cabc

    from .types import UowFactory


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
    def _get_serializer_fn() -> cabc.Callable[[object, int], dict[str, typ.Any]]:
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
    def _get_serializer_fn() -> cabc.Callable[[object], dict[str, typ.Any]]:
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


class SeriesProfilesResource:
    """Collection resource for series profiles."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """List all series profiles."""
        del req
        service_fn = partial(list_entities_with_revisions, kind="series_profile")
        async with self._uow_factory() as uow:
            items = await service_fn(uow)

        resp.media = {"items": list(starmap(serialize_series_profile, items))}
        resp.status = falcon.HTTP_200

    async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        """Create a series profile."""
        payload = require_payload_dict(await req.get_media())
        try:
            slug = typ.cast("str", payload["slug"])
            title = typ.cast("str", payload["title"])
            description = typ.cast("str | None", payload.get("description"))
            configuration = typ.cast("dict[str, typ.Any]", payload["configuration"])
        except KeyError as exc:
            msg = f"Missing required field: {exc.args[0]}"
            raise falcon.HTTPBadRequest(description=msg) from exc

        async with self._uow_factory() as uow:
            profile, revision = await create_series_profile(
                uow,
                data=SeriesProfileCreateData(
                    slug=slug,
                    title=title,
                    description=description,
                    configuration=configuration,
                ),
                audit=build_audit_metadata(payload),
            )

        resp.media = serialize_series_profile(profile, revision)
        resp.status = falcon.HTTP_201


class SeriesProfileResource(_GetResourceBase):
    """Single-resource endpoint for series profiles."""

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
    def _get_serializer_fn() -> cabc.Callable[[object, int], dict[str, typ.Any]]:
        """Return the profile serializer."""
        return typ.cast(
            "cabc.Callable[[object, int], dict[str, typ.Any]]",
            serialize_series_profile,
        )

    async def on_patch(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
    ) -> None:
        """Update a series profile using optimistic locking."""
        payload = require_payload_dict(await req.get_media())
        resp.media, resp.status = await handle_update_entity(
            uow_factory=self._uow_factory,
            entity_id=profile_id,
            id_field_name="profile_id",
            payload=payload,
            required_fields=("expected_revision", "title", "configuration"),
            request_builder=build_profile_update_request,
            service_fn=update_series_profile,
            serializer_fn=serialize_series_profile,
        )


class SeriesProfileHistoryResource(_GetHistoryResourceBase):
    """History endpoint for series profiles."""

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
    def _get_serializer_fn() -> cabc.Callable[[object], dict[str, typ.Any]]:
        """Return the profile-history serializer."""
        return typ.cast(
            "cabc.Callable[[object], dict[str, typ.Any]]",
            serialize_series_profile_history_entry,
        )


class SeriesProfileBriefResource:
    """Structured brief endpoint for downstream generators."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
    ) -> None:
        """Fetch a structured brief payload."""
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


class EpisodeTemplatesResource:
    """Collection resource for episode templates."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """List episode templates."""
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

    async def on_post(
        self,
        req: falcon.Request,
        resp: falcon.Response,
    ) -> None:
        """Create an episode template."""
        payload = require_payload_dict(await req.get_media())
        try:
            series_profile_id = parse_uuid(
                typ.cast("str", payload["series_profile_id"]),
                "series_profile_id",
            )
            slug = typ.cast("str", payload["slug"])
            title = typ.cast("str", payload["title"])
            description = typ.cast("str | None", payload.get("description"))
            structure = typ.cast("dict[str, typ.Any]", payload["structure"])
        except KeyError as exc:
            msg = f"Missing required field: {exc.args[0]}"
            raise falcon.HTTPBadRequest(description=msg) from exc

        try:
            async with self._uow_factory() as uow:
                template, revision = await create_episode_template(
                    uow,
                    series_profile_id=series_profile_id,
                    data=EpisodeTemplateData(
                        slug=slug,
                        title=title,
                        description=description,
                        structure=structure,
                        actor=typ.cast("str | None", payload.get("actor")),
                        note=typ.cast("str | None", payload.get("note")),
                    ),
                )
        except EntityNotFoundError as exc:
            raise falcon.HTTPNotFound(description=str(exc)) from exc

        resp.media = serialize_episode_template(template, revision)
        resp.status = falcon.HTTP_201


class EpisodeTemplateResource(_GetResourceBase):
    """Single-resource endpoint for episode templates."""

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
    def _get_serializer_fn() -> cabc.Callable[[object, int], dict[str, typ.Any]]:
        """Return the template serializer."""
        return typ.cast(
            "cabc.Callable[[object, int], dict[str, typ.Any]]",
            serialize_episode_template,
        )

    async def on_patch(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        template_id: str,
    ) -> None:
        """Update an episode template using optimistic locking."""
        payload = require_payload_dict(await req.get_media())
        resp.media, resp.status = await handle_update_entity(
            uow_factory=self._uow_factory,
            entity_id=template_id,
            id_field_name="template_id",
            payload=payload,
            required_fields=("expected_revision", "title", "structure"),
            request_builder=build_template_update_request,
            service_fn=update_episode_template,
            serializer_fn=serialize_episode_template,
        )


class EpisodeTemplateHistoryResource(_GetHistoryResourceBase):
    """History endpoint for episode templates."""

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
    def _get_serializer_fn() -> cabc.Callable[[object], dict[str, typ.Any]]:
        """Return the template-history serializer."""
        return typ.cast(
            "cabc.Callable[[object], dict[str, typ.Any]]",
            serialize_episode_template_history_entry,
        )
