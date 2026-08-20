"""Falcon resource and content negotiation for generated episode TEI."""

import hashlib
import json
import typing as typ

import falcon

from episodic.api.errors import http_error
from episodic.api.helpers import parse_uuid
from episodic.api.serializers import serialize_tei_envelope
from episodic.api.source_idempotency import principal_id
from episodic.observability import NoopTracer

if typ.TYPE_CHECKING:
    import uuid

    from episodic.api.types import UowFactory
    from episodic.canonical.domain import CanonicalEpisode, GenerationRun
    from episodic.observability import TracerPort

_JSON_MEDIA_TYPE = "application/json"
_TEI_MEDIA_TYPE = "application/tei+xml"
_ANONYMOUS_TEST_PRINCIPAL = "anonymous"


class EpisodeTeiResource:
    """Return generated episode TEI as metadata or an XML attachment.

    Parameters
    ----------
    uow_factory : UowFactory
        Callable dependency retained by the resource and invoked to construct
        an asynchronous unit of work for each request.
    """

    def __init__(
        self, uow_factory: UowFactory, *, tracer: TracerPort | None = None
    ) -> None:
        self._uow_factory = uow_factory
        self._tracer = NoopTracer() if tracer is None else tracer

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        episode_id: str,
    ) -> None:
        """Return generated TEI using the requested representation.

        Parameters
        ----------
        req : falcon.Request
            Request whose ``Accept`` and ``If-None-Match`` headers select and
            condition the representation.
        resp : falcon.Response
            Response to populate with JSON metadata or an XML attachment.
        episode_id : str
            Episode UUID from the route path.

        Raises
        ------
        falcon.HTTPBadRequest
            If ``episode_id`` is not a valid UUID (HTTP 400).
        falcon.HTTPNotFound
            If the episode is absent or has no generated TEI (HTTP 404).
        falcon.HTTPNotAcceptable
            If ``Accept`` excludes both supported media types (HTTP 406).

        Notes
        -----
        JSON metadata (``application/json``) is the default representation.
        ``application/tei+xml`` selects the generated XML attachment. A
        matching or wildcard ``If-None-Match`` validator returns HTTP 304 with
        no response body.
        """  # noqa: DOC501, DOC502  # Indirect exceptions form part of this public contract.
        with self._tracer.start_span(
            "episode_tei.read",
            attributes={"operation": "episode_tei.read"},
        ) as span:
            try:
                parsed_episode_id = parse_uuid(episode_id, "episode_id")
            except falcon.HTTPError:
                span.set_attribute("outcome", "rejected")
                span.set_attribute("failure_category", "invalid_input")
                raise
            async with self._uow_factory() as uow:
                episode = await uow.episodes.get(parsed_episode_id)
                run = (
                    None
                    if episode is None or episode.last_generation_run_id is None
                    else await uow.generation_runs.get_run(
                        episode.last_generation_run_id
                    )
                )
            actor = principal_id(req) or _ANONYMOUS_TEST_PRINCIPAL
            if not _has_accessible_draft(episode, run, actor):
                span.set_attribute("outcome", "not_found")
                span.set_attribute("failure_category", "episode.not_found")
                raise _tei_not_found(parsed_episode_id)
            episode = typ.cast("CanonicalEpisode", episode)
            try:
                media_type = negotiate_tei_media_type(req.accept)
            except falcon.HTTPNotAcceptable:
                span.set_attribute("outcome", "rejected")
                span.set_attribute("failure_category", "not_acceptable")
                raise
            span.set_attribute("representation", media_type)
            if media_type == _TEI_MEDIA_TYPE:
                _apply_tei_attachment(req, resp, episode)
            else:
                _apply_tei_json(req, resp, episode)
            span.set_attribute("outcome", "success")


def negotiate_tei_media_type(accept: str | None) -> str:
    """Choose JSON metadata or raw TEI XML from an HTTP Accept header.

    Parameters
    ----------
    accept
        Raw value of the request ``Accept`` header. Missing or blank values
        select JSON metadata.

    Returns
    -------
    str
        ``application/json`` or ``application/tei+xml``, chosen by the
        highest acceptable quality value.

    Raises
    ------
    falcon.HTTPNotAcceptable
        Raised when neither supported representation has a positive quality.
    """  # noqa: DOC502 - http_error() preserves the concrete Falcon exception.
    if accept is None or not accept.strip():
        return _JSON_MEDIA_TYPE
    tei_quality = falcon.mediatypes.quality(_TEI_MEDIA_TYPE, accept)
    json_quality = falcon.mediatypes.quality(_JSON_MEDIA_TYPE, accept)
    if tei_quality > 0 and tei_quality > json_quality:
        return _TEI_MEDIA_TYPE
    if json_quality > 0:
        return _JSON_MEDIA_TYPE
    error = falcon.HTTPNotAcceptable(
        description="Accept must allow application/json or application/tei+xml."
    )
    http_error(
        error,
        code="not_acceptable",
        details={"supported": [_JSON_MEDIA_TYPE, _TEI_MEDIA_TYPE]},
    )
    raise error


def _has_generated_draft(episode: CanonicalEpisode) -> bool:
    return (
        episode.last_generation_run_id is not None
        and episode.tei_content_hash is not None
        and episode.qa_status is not None
    )


def _has_accessible_draft(
    episode: CanonicalEpisode | None,
    run: GenerationRun | None,
    actor: str,
) -> bool:
    """Return whether the requested actor can retrieve this generated draft."""
    return (
        episode is not None
        and _has_generated_draft(episode)
        and run is not None
        and run.actor == actor
    )


def _apply_tei_json(
    req: falcon.Request,
    resp: falcon.Response,
    episode: CanonicalEpisode,
) -> None:
    content = json.dumps(serialize_tei_envelope(episode), ensure_ascii=False).encode()
    _apply_representation(req, resp, content=content, media_type=_JSON_MEDIA_TYPE)


def _apply_tei_attachment(
    req: falcon.Request,
    resp: falcon.Response,
    episode: CanonicalEpisode,
) -> None:
    resp.set_header(
        "Content-Disposition",
        f'attachment; filename="episode-{episode.id}.xml"',
    )
    _apply_representation(
        req,
        resp,
        content=episode.tei_xml.encode(),
        media_type=_TEI_MEDIA_TYPE,
    )


def _apply_representation(
    req: falcon.Request,
    resp: falcon.Response,
    *,
    content: bytes,
    media_type: str,
) -> None:
    """Set one TEI representation or its conditional ``304`` response."""
    etag = _representation_etag(content)
    resp.set_header("ETag", f'"{etag}"')
    if any(validator in {"*", etag} for validator in req.if_none_match or []):
        resp.status = falcon.HTTP_304
        return
    resp.status = falcon.HTTP_200
    resp.content_type = media_type
    resp.data = content


def _representation_etag(content: bytes) -> str:
    """Return the strong ETag value for serialized representation bytes."""
    return hashlib.sha256(content).hexdigest()


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
