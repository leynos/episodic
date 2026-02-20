"""Falcon API adapter for series profiles and episode templates."""

from __future__ import annotations

import typing as typ
import uuid
from itertools import starmap

import falcon
from falcon import asgi

from episodic.canonical.profile_templates import (
    EntityNotFoundError,
    RevisionConflictError,
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


def _serialize_series_profile_history_entry(
    entry: SeriesProfileHistoryEntry,
) -> dict[str, typ.Any]:
    """Serialize a profile history entry."""
    return {
        "id": str(entry.id),
        "series_profile_id": str(entry.series_profile_id),
        "revision": entry.revision,
        "actor": entry.actor,
        "note": entry.note,
        "snapshot": entry.snapshot,
        "created_at": entry.created_at.isoformat(),
    }


def _serialize_episode_template_history_entry(
    entry: EpisodeTemplateHistoryEntry,
) -> dict[str, typ.Any]:
    """Serialize an episode-template history entry."""
    return {
        "id": str(entry.id),
        "episode_template_id": str(entry.episode_template_id),
        "revision": entry.revision,
        "actor": entry.actor,
        "note": entry.note,
        "snapshot": entry.snapshot,
        "created_at": entry.created_at.isoformat(),
    }


class SeriesProfilesResource:
    """Collection resource for series profiles."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """List all series profiles."""
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
                slug=slug,
                title=title,
                description=description,
                configuration=configuration,
                actor=actor,
                note=note,
            )

        resp.media = _serialize_series_profile(profile, revision)
        resp.status = falcon.HTTP_201


class SeriesProfileResource:
    """Single-resource endpoint for series profiles."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
    ) -> None:
        """Fetch a series profile."""
        parsed_profile_id = _parse_uuid(profile_id, "profile_id")
        try:
            async with self._uow_factory() as uow:
                profile, revision = await get_series_profile(
                    uow,
                    profile_id=parsed_profile_id,
                )
        except EntityNotFoundError as exc:
            raise falcon.HTTPNotFound(description=str(exc)) from exc

        resp.media = _serialize_series_profile(profile, revision)
        resp.status = falcon.HTTP_200

    async def on_patch(  # noqa: PLR0914
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
    ) -> None:
        """Update a series profile using optimistic locking."""
        parsed_profile_id = _parse_uuid(profile_id, "profile_id")
        payload = _require_payload_dict(await req.get_media())
        try:
            expected_revision = int(payload["expected_revision"])
            title = typ.cast("str", payload["title"])
            description = typ.cast("str | None", payload.get("description"))
            configuration = typ.cast("dict[str, typ.Any]", payload["configuration"])
            actor = typ.cast("str | None", payload.get("actor"))
            note = typ.cast("str | None", payload.get("note"))
        except KeyError as exc:
            msg = f"Missing required field: {exc.args[0]}"
            raise falcon.HTTPBadRequest(description=msg) from exc

        try:
            async with self._uow_factory() as uow:
                profile, revision = await update_series_profile(
                    uow,
                    profile_id=parsed_profile_id,
                    expected_revision=expected_revision,
                    title=title,
                    description=description,
                    configuration=configuration,
                    actor=actor,
                    note=note,
                )
        except EntityNotFoundError as exc:
            raise falcon.HTTPNotFound(description=str(exc)) from exc
        except RevisionConflictError as exc:
            raise falcon.HTTPConflict(description=str(exc)) from exc

        resp.media = _serialize_series_profile(profile, revision)
        resp.status = falcon.HTTP_200


class SeriesProfileHistoryResource:
    """History endpoint for series profiles."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
    ) -> None:
        """List series profile history entries."""
        parsed_profile_id = _parse_uuid(profile_id, "profile_id")
        async with self._uow_factory() as uow:
            items = await list_series_profile_history(uow, profile_id=parsed_profile_id)

        resp.media = {
            "items": [_serialize_series_profile_history_entry(item) for item in items]
        }
        resp.status = falcon.HTTP_200


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
                    slug=slug,
                    title=title,
                    description=description,
                    structure=structure,
                    actor=actor,
                    note=note,
                )
        except EntityNotFoundError as exc:
            raise falcon.HTTPNotFound(description=str(exc)) from exc

        resp.media = _serialize_episode_template(template, revision)
        resp.status = falcon.HTTP_201


class EpisodeTemplateResource:
    """Single-resource endpoint for episode templates."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        template_id: str,
    ) -> None:
        """Fetch an episode template."""
        parsed_template_id = _parse_uuid(template_id, "template_id")
        try:
            async with self._uow_factory() as uow:
                template, revision = await get_episode_template(
                    uow,
                    template_id=parsed_template_id,
                )
        except EntityNotFoundError as exc:
            raise falcon.HTTPNotFound(description=str(exc)) from exc

        resp.media = _serialize_episode_template(template, revision)
        resp.status = falcon.HTTP_200

    async def on_patch(  # noqa: PLR0914
        self,
        req: falcon.Request,
        resp: falcon.Response,
        template_id: str,
    ) -> None:
        """Update an episode template using optimistic locking."""
        parsed_template_id = _parse_uuid(template_id, "template_id")
        payload = _require_payload_dict(await req.get_media())
        try:
            expected_revision = int(payload["expected_revision"])
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
                template, revision = await update_episode_template(
                    uow,
                    template_id=parsed_template_id,
                    expected_revision=expected_revision,
                    title=title,
                    description=description,
                    structure=structure,
                    actor=actor,
                    note=note,
                )
        except EntityNotFoundError as exc:
            raise falcon.HTTPNotFound(description=str(exc)) from exc
        except RevisionConflictError as exc:
            raise falcon.HTTPConflict(description=str(exc)) from exc

        resp.media = _serialize_episode_template(template, revision)
        resp.status = falcon.HTTP_200


class EpisodeTemplateHistoryResource:
    """History endpoint for episode templates."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        template_id: str,
    ) -> None:
        """List episode template history entries."""
        parsed_template_id = _parse_uuid(template_id, "template_id")
        async with self._uow_factory() as uow:
            items = await list_episode_template_history(
                uow,
                template_id=parsed_template_id,
            )

        resp.media = {
            "items": [_serialize_episode_template_history_entry(item) for item in items]
        }
        resp.status = falcon.HTTP_200


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
