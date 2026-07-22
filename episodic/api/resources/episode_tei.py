"""Falcon resource and content negotiation for generated episode TEI."""

from __future__ import annotations

import typing as typ

import falcon

from episodic.api.errors import http_error
from episodic.api.helpers import parse_uuid
from episodic.api.serializers import serialize_tei_envelope

if typ.TYPE_CHECKING:
    import uuid

    from episodic.api.types import UowFactory
    from episodic.canonical.domain import CanonicalEpisode

_JSON_MEDIA_TYPE = "application/json"
_TEI_MEDIA_TYPE = "application/tei+xml"


class EpisodeTeiResource:
    """Return generated episode TEI as metadata or an XML attachment."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        episode_id: str,
    ) -> None:
        """Return generated TEI using the requested representation."""
        parsed_episode_id = parse_uuid(episode_id, "episode_id")
        async with self._uow_factory() as uow:
            episode = await uow.episodes.get(parsed_episode_id)
        if episode is None or not _has_generated_draft(episode):
            raise _tei_not_found(parsed_episode_id)

        media_type = negotiate_tei_media_type(req.accept)
        if media_type == _TEI_MEDIA_TYPE:
            _apply_tei_attachment(resp, episode)
            return
        resp.media = serialize_tei_envelope(episode)
        resp.status = falcon.HTTP_200


def negotiate_tei_media_type(accept: str | None) -> str:
    """Choose JSON metadata or raw TEI XML from an HTTP Accept header."""
    if accept is None or not accept.strip():
        return _JSON_MEDIA_TYPE
    accepted = {part.split(";", maxsplit=1)[0].strip() for part in accept.split(",")}
    if _TEI_MEDIA_TYPE in accepted:
        return _TEI_MEDIA_TYPE
    if _JSON_MEDIA_TYPE in accepted or "*/*" in accepted:
        return _JSON_MEDIA_TYPE
    raise typ.cast(
        "falcon.HTTPNotAcceptable",
        http_error(
            falcon.HTTPNotAcceptable(
                description="Accept must allow application/json or application/tei+xml."
            ),
            code="not_acceptable",
            details={"supported": [_JSON_MEDIA_TYPE, _TEI_MEDIA_TYPE]},
        ),
    )


def _has_generated_draft(episode: CanonicalEpisode) -> bool:
    return (
        episode.last_generation_run_id is not None
        and episode.tei_content_hash is not None
        and episode.qa_status is not None
    )


def _apply_tei_attachment(
    resp: falcon.Response,
    episode: CanonicalEpisode,
) -> None:
    resp.status = falcon.HTTP_200
    resp.content_type = _TEI_MEDIA_TYPE
    resp.text = episode.tei_xml
    resp.set_header(
        "Content-Disposition",
        f'attachment; filename="episode-{episode.id}.xml"',
    )
    resp.set_header("ETag", f'"{episode.tei_content_hash}"')


def _tei_not_found(episode_id: uuid.UUID) -> falcon.HTTPNotFound:
    return typ.cast(
        "falcon.HTTPNotFound",
        http_error(
            falcon.HTTPNotFound(
                description=f"Generated TEI not found for episode: {episode_id}."
            ),
            code="episode_tei_not_found",
            details={"episode_id": str(episode_id)},
        ),
    )
