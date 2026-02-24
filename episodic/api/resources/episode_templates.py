"""Episode-template Falcon resources."""

from __future__ import annotations

import typing as typ
from functools import partial
from itertools import starmap

import falcon

from episodic.api.helpers import (
    build_template_create_kwargs,
    build_template_update_request,
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
    serialize_episode_template,
    serialize_episode_template_history_entry,
)
from episodic.canonical.profile_templates import (
    create_episode_template,
    get_entity_with_revision,
    list_entities_with_revisions,
    list_history,
    update_episode_template,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.api.types import JsonPayload


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
    def _get_kwargs_builder() -> cabc.Callable[[JsonPayload], dict[str, object]]:
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


# NOTE: Intentional MRO-safe diamond inheritance: both parent ``__init__``
# implementations are identical, and placing ``_UpdateResourceBase`` first
# ensures patch-specific hooks resolve before shared get-by-id behavior.
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
