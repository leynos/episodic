"""Falcon resource for resolved reference-binding lookups."""

import typing as typ

import falcon

from episodic.api.helpers import parse_uuid, require_query_params
from episodic.api.serializers import serialize_resolved_binding
from episodic.canonical.profile_templates import EntityNotFoundError
from episodic.canonical.reference_documents import resolve_bindings

if typ.TYPE_CHECKING:
    from episodic.api.types import UowFactory


class ResolvedBindingsResource:
    """Return resolved reference bindings for a series profile context."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
    ) -> None:
        """Resolve bindings for a series profile plus episode context."""
        parsed_profile_id = parse_uuid(profile_id, "profile_id")
        params = require_query_params(req, "episode_id")
        parsed_episode_id = parse_uuid(params["episode_id"], "episode_id")
        raw_template_id = req.get_param("template_id")
        template_id = (
            None
            if raw_template_id is None
            else parse_uuid(raw_template_id, "template_id")
        )

        try:
            async with self._uow_factory() as uow:
                profile = await uow.series_profiles.get(parsed_profile_id)
                if profile is None:
                    msg = f"Series profile not found: {parsed_profile_id}."
                    raise falcon.HTTPNotFound(description=msg)

                episode = await uow.episodes.get(parsed_episode_id)
                if episode is None or episode.series_profile_id != parsed_profile_id:
                    msg = (
                        f"Episode not found or does not belong to "
                        f"series profile: {parsed_episode_id}."
                    )
                    raise falcon.HTTPNotFound(description=msg)

                resolved = await resolve_bindings(
                    uow,
                    series_profile_id=parsed_profile_id,
                    template_id=template_id,
                    episode_id=parsed_episode_id,
                )
        except EntityNotFoundError as exc:
            raise falcon.HTTPNotFound(description=str(exc)) from exc

        resp.media = {"items": [serialize_resolved_binding(item) for item in resolved]}
        resp.status = falcon.HTTP_200
