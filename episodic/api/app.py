"""Falcon API adapter for series profiles and episode templates."""

from __future__ import annotations

import typing as typ
import uuid
from abc import ABC, abstractmethod
from itertools import starmap

import falcon
from falcon import asgi

from episodic.canonical.profile_templates import (
    AuditMetadata,
    EntityNotFoundError,
    EpisodeTemplateData,
    EpisodeTemplateUpdateFields,
    RevisionConflictError,
    SeriesProfileCreateData,
    SeriesProfileData,
    UpdateEpisodeTemplateRequest,
    UpdateSeriesProfileRequest,
    build_series_brief,
    create_episode_template,
    create_series_profile,
    get_episode_template,
    get_series_profile,
    list_episode_template_history,
    list_episode_templates,
    list_series_profile_history,
    list_series_profiles,
    update_episode_template,
    update_series_profile,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.domain import (
        EpisodeTemplate,
        EpisodeTemplateHistoryEntry,
        SeriesProfile,
        SeriesProfileHistoryEntry,
    )
    from episodic.canonical.ports import CanonicalUnitOfWork

    type UowFactory = cabc.Callable[[], CanonicalUnitOfWork]


def _parse_uuid(raw_value: str, field_name: str) -> uuid.UUID:
    """Parse a UUID string or raise HTTP 400."""
    try:
        return uuid.UUID(raw_value)
    except ValueError as exc:
        msg = f"Invalid UUID for {field_name}: {raw_value!r}."
        raise falcon.HTTPBadRequest(description=msg) from exc


def _require_payload_dict(payload: typ.Any) -> dict[str, typ.Any]:  # noqa: ANN401
    """Validate request media payload shape."""
    if not isinstance(payload, dict):
        msg = "JSON object payload is required."
        raise falcon.HTTPBadRequest(description=msg)
    return payload


def _build_audit_metadata(payload: dict[str, typ.Any]) -> AuditMetadata:
    """Extract audit metadata from request payload."""
    return AuditMetadata(
        actor=typ.cast("str | None", payload.get("actor")),
        note=typ.cast("str | None", payload.get("note")),
    )


def _parse_expected_revision(payload: dict[str, typ.Any]) -> int:
    """Parse expected revision or raise HTTP 400."""
    if "expected_revision" not in payload:
        msg = "Missing required field: expected_revision"
        raise falcon.HTTPBadRequest(description=msg)

    raw_expected_revision = payload["expected_revision"]
    try:
        return int(raw_expected_revision)
    except (TypeError, ValueError) as exc:
        msg = f"Invalid integer for expected_revision: {raw_expected_revision!r}."
        raise falcon.HTTPBadRequest(description=msg) from exc


def _build_update_kwargs[DataT](
    payload: dict[str, typ.Any],
    data_key: str,
    data_builder: cabc.Callable[[dict[str, typ.Any]], DataT],
) -> dict[str, typ.Any]:
    """Build generic update service kwargs with optimistic locking."""
    return {
        "expected_revision": _parse_expected_revision(payload),
        data_key: data_builder(payload),
        "audit": _build_audit_metadata(payload),
    }


def _build_profile_data(payload: dict[str, typ.Any]) -> SeriesProfileData:
    """Build SeriesProfileData from payload."""
    return SeriesProfileData(
        title=typ.cast("str", payload["title"]),
        description=typ.cast("str | None", payload.get("description")),
        configuration=typ.cast("dict[str, typ.Any]", payload["configuration"]),
    )


def _build_template_fields(
    payload: dict[str, typ.Any],
) -> EpisodeTemplateUpdateFields:
    """Build EpisodeTemplateUpdateFields from payload."""
    return EpisodeTemplateUpdateFields(
        title=typ.cast("str", payload["title"]),
        description=typ.cast("str | None", payload.get("description")),
        structure=typ.cast("dict[str, typ.Any]", payload["structure"]),
    )


def _build_profile_update_kwargs(payload: dict[str, typ.Any]) -> dict[str, typ.Any]:
    """Build update service kwargs for profile updates."""
    return _build_update_kwargs(payload, "data", _build_profile_data)


def _build_template_update_kwargs(payload: dict[str, typ.Any]) -> dict[str, typ.Any]:
    """Build update service kwargs for template updates."""
    return _build_update_kwargs(payload, "fields", _build_template_fields)


def _build_profile_update_request(
    entity_id: uuid.UUID,
    update_kwargs: dict[str, typ.Any],
) -> UpdateSeriesProfileRequest:
    """Build an update request for series profiles."""
    expected_revision = typ.cast("int", update_kwargs["expected_revision"])
    audit = typ.cast("AuditMetadata", update_kwargs["audit"])
    return UpdateSeriesProfileRequest(
        profile_id=entity_id,
        expected_revision=expected_revision,
        data=typ.cast("SeriesProfileData", update_kwargs["data"]),
        audit=audit,
    )


def _build_template_update_request(
    entity_id: uuid.UUID,
    update_kwargs: dict[str, typ.Any],
) -> UpdateEpisodeTemplateRequest:
    """Build an update request for episode templates."""
    expected_revision = typ.cast("int", update_kwargs["expected_revision"])
    audit = typ.cast("AuditMetadata", update_kwargs["audit"])
    return UpdateEpisodeTemplateRequest(
        template_id=entity_id,
        expected_revision=expected_revision,
        fields=typ.cast("EpisodeTemplateUpdateFields", update_kwargs["fields"]),
        audit=audit,
    )


async def _handle_get_entity[EntityT](  # noqa: PLR0913, PLR0917
    uow_factory: UowFactory,
    entity_id: str,
    id_field_name: str,
    service_fn: cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]],
    serializer_fn: cabc.Callable[[EntityT, int], dict[str, typ.Any]],
) -> tuple[dict[str, typ.Any], str]:
    """Handle common fetch-by-id endpoint behaviour."""
    parsed_entity_id = _parse_uuid(entity_id, id_field_name)
    try:
        async with uow_factory() as uow:
            entity, revision = await service_fn(
                uow,
                **{id_field_name: parsed_entity_id},
            )
    except EntityNotFoundError as exc:
        raise falcon.HTTPNotFound(description=str(exc)) from exc
    return serializer_fn(entity, revision), falcon.HTTP_200


async def _handle_get_history[EntityT](  # noqa: PLR0913, PLR0917
    uow_factory: UowFactory,
    entity_id: str,
    id_field_name: str,
    service_fn: cabc.Callable[..., cabc.Awaitable[list[EntityT]]],
    serializer_fn: cabc.Callable[[EntityT], dict[str, typ.Any]],
) -> tuple[dict[str, typ.Any], str]:
    """Handle common history-list endpoint behaviour."""
    parsed_entity_id = _parse_uuid(entity_id, id_field_name)
    async with uow_factory() as uow:
        items = await service_fn(uow, **{id_field_name: parsed_entity_id})
    return {"items": [serializer_fn(item) for item in items]}, falcon.HTTP_200


async def _handle_update_entity[EntityT](  # noqa: PLR0913, PLR0917
    uow_factory: UowFactory,
    entity_id: str,
    id_field_name: str,
    payload: dict[str, typ.Any],
    required_fields: tuple[str, ...],
    kwargs_builder: cabc.Callable[[dict[str, typ.Any]], dict[str, typ.Any]],
    request_builder: cabc.Callable[
        [uuid.UUID, dict[str, typ.Any]],
        UpdateSeriesProfileRequest | UpdateEpisodeTemplateRequest,
    ],
    service_fn: cabc.Callable[..., cabc.Awaitable[tuple[EntityT, int]]],
    serializer_fn: cabc.Callable[[EntityT, int], dict[str, typ.Any]],
) -> tuple[dict[str, typ.Any], str]:
    """Handle common optimistic-lock update endpoint behaviour."""
    parsed_entity_id = _parse_uuid(entity_id, id_field_name)
    for field_name in required_fields:
        if field_name not in payload:
            msg = f"Missing required field: {field_name}"
            raise falcon.HTTPBadRequest(description=msg)

    update_payload_kwargs = kwargs_builder(payload)
    update_request = request_builder(
        parsed_entity_id,
        update_payload_kwargs,
    )

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


def _serialize_series_profile(
    profile: SeriesProfile, revision: int
) -> dict[str, typ.Any]:
    """Serialize a series profile response payload."""
    return {
        "id": str(profile.id),
        "slug": profile.slug,
        "title": profile.title,
        "description": profile.description,
        "configuration": profile.configuration,
        "revision": revision,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


def _serialize_episode_template(
    template: EpisodeTemplate,
    revision: int,
) -> dict[str, typ.Any]:
    """Serialize an episode template response payload."""
    return {
        "id": str(template.id),
        "series_profile_id": str(template.series_profile_id),
        "slug": template.slug,
        "title": template.title,
        "description": template.description,
        "structure": template.structure,
        "revision": revision,
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


def _serialize_history_entry(
    entry: SeriesProfileHistoryEntry | EpisodeTemplateHistoryEntry,
    parent_id_field: str,
) -> dict[str, typ.Any]:
    """Serialise a history entry to JSON."""
    parent_id = getattr(entry, parent_id_field)
    return {
        "id": str(entry.id),
        parent_id_field: str(parent_id),
        "revision": entry.revision,
        "actor": entry.actor,
        "note": entry.note,
        "snapshot": entry.snapshot,
        "created_at": entry.created_at.isoformat(),
    }


def _serialize_series_profile_history_entry(
    entry: SeriesProfileHistoryEntry,
) -> dict[str, typ.Any]:
    """Serialize a profile history entry."""
    return _serialize_history_entry(entry, "series_profile_id")


def _serialize_episode_template_history_entry(
    entry: EpisodeTemplateHistoryEntry,
) -> dict[str, typ.Any]:
    """Serialize an episode-template history entry."""
    return _serialize_history_entry(entry, "episode_template_id")


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
        resp.media, resp.status = await _handle_get_entity(
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
        resp.media, resp.status = await _handle_get_history(
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
        async with self._uow_factory() as uow:
            items = await list_series_profiles(uow)

        resp.media = {"items": list(starmap(_serialize_series_profile, items))}
        resp.status = falcon.HTTP_200

    async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        """Create a series profile."""
        payload = _require_payload_dict(await req.get_media())
        try:
            slug = typ.cast("str", payload["slug"])
            title = typ.cast("str", payload["title"])
            description = typ.cast("str | None", payload.get("description"))
            configuration = typ.cast("dict[str, typ.Any]", payload["configuration"])
            actor = typ.cast("str | None", payload.get("actor"))
            note = typ.cast("str | None", payload.get("note"))
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
                audit=AuditMetadata(actor=actor, note=note),
            )

        resp.media = _serialize_series_profile(profile, revision)
        resp.status = falcon.HTTP_201


class SeriesProfileResource(_GetResourceBase):
    """Single-resource endpoint for series profiles."""

    @staticmethod
    def _get_entity_id_from_path(**kwargs: str) -> str:
        """Return the profile identifier from route params."""
        return kwargs["profile_id"]

    @staticmethod
    def _get_id_field_name() -> str:
        """Return the profile identifier service argument."""
        return "profile_id"

    @staticmethod
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]:
        """Return the profile fetch service."""
        return typ.cast(
            "cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]",
            get_series_profile,
        )

    @staticmethod
    def _get_serializer_fn() -> cabc.Callable[[object, int], dict[str, typ.Any]]:
        """Return the profile serializer."""
        return typ.cast(
            "cabc.Callable[[object, int], dict[str, typ.Any]]",
            _serialize_series_profile,
        )

    async def on_patch(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
    ) -> None:
        """Update a series profile using optimistic locking."""
        payload = _require_payload_dict(await req.get_media())
        resp.media, resp.status = await _handle_update_entity(
            uow_factory=self._uow_factory,
            entity_id=profile_id,
            id_field_name="profile_id",
            payload=payload,
            required_fields=("expected_revision", "title", "configuration"),
            kwargs_builder=_build_profile_update_kwargs,
            request_builder=_build_profile_update_request,
            service_fn=update_series_profile,
            serializer_fn=_serialize_series_profile,
        )


class SeriesProfileHistoryResource(_GetHistoryResourceBase):
    """History endpoint for series profiles."""

    @staticmethod
    def _get_entity_id_from_path(**kwargs: str) -> str:
        """Return the profile identifier from route params."""
        return kwargs["profile_id"]

    @staticmethod
    def _get_id_field_name() -> str:
        """Return the profile identifier service argument."""
        return "profile_id"

    @staticmethod
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[list[object]]]:
        """Return the profile-history list service."""
        return typ.cast(
            "cabc.Callable[..., cabc.Awaitable[list[object]]]",
            list_series_profile_history,
        )

    @staticmethod
    def _get_serializer_fn() -> cabc.Callable[[object], dict[str, typ.Any]]:
        """Return the profile-history serializer."""
        return typ.cast(
            "cabc.Callable[[object], dict[str, typ.Any]]",
            _serialize_series_profile_history_entry,
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
        parsed_profile_id = _parse_uuid(profile_id, "profile_id")
        raw_template_id = req.get_param("template_id")
        template_id = (
            None
            if raw_template_id is None
            else _parse_uuid(
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
            else _parse_uuid(raw_series_profile_id, "series_profile_id")
        )

        async with self._uow_factory() as uow:
            items = await list_episode_templates(
                uow,
                series_profile_id=series_profile_id,
            )

        resp.media = {"items": list(starmap(_serialize_episode_template, items))}
        resp.status = falcon.HTTP_200

    async def on_post(  # noqa: PLR0914
        self,
        req: falcon.Request,
        resp: falcon.Response,
    ) -> None:
        """Create an episode template."""
        payload = _require_payload_dict(await req.get_media())
        try:
            series_profile_id = _parse_uuid(
                typ.cast("str", payload["series_profile_id"]),
                "series_profile_id",
            )
            slug = typ.cast("str", payload["slug"])
            title = typ.cast("str", payload["title"])
            description = typ.cast("str | None", payload.get("description"))
            structure = typ.cast("dict[str, typ.Any]", payload["structure"])
            actor = typ.cast("str | None", payload.get("actor"))
            note = typ.cast("str | None", payload.get("note"))
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
                        actor=actor,
                        note=note,
                    ),
                )
        except EntityNotFoundError as exc:
            raise falcon.HTTPNotFound(description=str(exc)) from exc

        resp.media = _serialize_episode_template(template, revision)
        resp.status = falcon.HTTP_201


class EpisodeTemplateResource(_GetResourceBase):
    """Single-resource endpoint for episode templates."""

    @staticmethod
    def _get_entity_id_from_path(**kwargs: str) -> str:
        """Return the template identifier from route params."""
        return kwargs["template_id"]

    @staticmethod
    def _get_id_field_name() -> str:
        """Return the template identifier service argument."""
        return "template_id"

    @staticmethod
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]:
        """Return the template fetch service."""
        return typ.cast(
            "cabc.Callable[..., cabc.Awaitable[tuple[object, int]]]",
            get_episode_template,
        )

    @staticmethod
    def _get_serializer_fn() -> cabc.Callable[[object, int], dict[str, typ.Any]]:
        """Return the template serializer."""
        return typ.cast(
            "cabc.Callable[[object, int], dict[str, typ.Any]]",
            _serialize_episode_template,
        )

    async def on_patch(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        template_id: str,
    ) -> None:
        """Update an episode template using optimistic locking."""
        payload = _require_payload_dict(await req.get_media())
        resp.media, resp.status = await _handle_update_entity(
            uow_factory=self._uow_factory,
            entity_id=template_id,
            id_field_name="template_id",
            payload=payload,
            required_fields=("expected_revision", "title", "structure"),
            kwargs_builder=_build_template_update_kwargs,
            request_builder=_build_template_update_request,
            service_fn=update_episode_template,
            serializer_fn=_serialize_episode_template,
        )


class EpisodeTemplateHistoryResource(_GetHistoryResourceBase):
    """History endpoint for episode templates."""

    @staticmethod
    def _get_entity_id_from_path(**kwargs: str) -> str:
        """Return the template identifier from route params."""
        return kwargs["template_id"]

    @staticmethod
    def _get_id_field_name() -> str:
        """Return the template identifier service argument."""
        return "template_id"

    @staticmethod
    def _get_service_fn() -> cabc.Callable[..., cabc.Awaitable[list[object]]]:
        """Return the template-history list service."""
        return typ.cast(
            "cabc.Callable[..., cabc.Awaitable[list[object]]]",
            list_episode_template_history,
        )

    @staticmethod
    def _get_serializer_fn() -> cabc.Callable[[object], dict[str, typ.Any]]:
        """Return the template-history serializer."""
        return typ.cast(
            "cabc.Callable[[object], dict[str, typ.Any]]",
            _serialize_episode_template_history_entry,
        )


def create_app(uow_factory: UowFactory) -> asgi.App:
    """Build and return Falcon ASGI application for canonical profile/template APIs."""
    app = asgi.App()

    app.add_route("/series-profiles", SeriesProfilesResource(uow_factory))
    app.add_route("/series-profiles/{profile_id}", SeriesProfileResource(uow_factory))
    app.add_route(
        "/series-profiles/{profile_id}/history",
        SeriesProfileHistoryResource(uow_factory),
    )
    app.add_route(
        "/series-profiles/{profile_id}/brief",
        SeriesProfileBriefResource(uow_factory),
    )

    app.add_route("/episode-templates", EpisodeTemplatesResource(uow_factory))
    app.add_route(
        "/episode-templates/{template_id}",
        EpisodeTemplateResource(uow_factory),
    )
    app.add_route(
        "/episode-templates/{template_id}/history",
        EpisodeTemplateHistoryResource(uow_factory),
    )

    return app
