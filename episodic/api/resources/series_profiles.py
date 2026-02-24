"""Series-profile Falcon resources."""

from __future__ import annotations

import typing as typ
from functools import partial
from itertools import starmap

import falcon

from episodic.api.helpers import (
    build_profile_create_kwargs,
    build_profile_update_request,
    parse_uuid,
)
from episodic.api.resources.base import (
    UpdateRequestBuilder,
    _CreateResourceBase,
    _GetHistoryResourceBase,
    _GetResourceBase,
    _UpdateResourceBase,
)
from episodic.api.serializers import (
    serialize_series_profile,
    serialize_series_profile_history_entry,
)
from episodic.canonical.briefs import build_series_brief
from episodic.canonical.profile_templates import (
    EntityNotFoundError,
    create_series_profile,
    get_entity_with_revision,
    list_entities_with_revisions,
    list_history,
    update_series_profile,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.api.types import JsonPayload, UowFactory


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
    def _get_kwargs_builder() -> cabc.Callable[[JsonPayload], dict[str, object]]:
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


# NOTE: Intentional MRO-safe diamond inheritance: both parent ``__init__``
# implementations are identical, and placing ``_UpdateResourceBase`` first
# ensures patch-specific hooks resolve before shared get-by-id behavior.
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
