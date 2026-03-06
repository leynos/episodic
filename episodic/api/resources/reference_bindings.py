"""Falcon resources for reusable reference-binding endpoints."""

import typing as typ

import falcon

from episodic.api.helpers import (
    map_reference_error,
    parse_pagination,
    parse_uuid,
    require_payload_dict,
    require_query_params,
)
from episodic.api.serializers import serialize_reference_binding
from episodic.canonical.reference_documents import (
    ReferenceBindingData,
    ReferenceBindingListRequest,
    ReferenceDocumentError,
    create_reference_binding,
    get_reference_binding,
    list_reference_bindings,
)

if typ.TYPE_CHECKING:
    from episodic.api.types import UowFactory


class ReferenceBindingsResource:
    """Handle create/list endpoints for reusable reference bindings."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        """Create one reusable reference binding."""
        payload = require_payload_dict(await req.get_media())
        missing = tuple(
            field
            for field in ("reference_document_revision_id", "target_kind")
            if field not in payload
        )
        if missing:
            msg = f"Missing required field: {missing[0]}"
            raise falcon.HTTPBadRequest(description=msg)

        data = ReferenceBindingData(
            reference_document_revision_id=typ.cast(
                "str", payload["reference_document_revision_id"]
            ),
            target_kind=typ.cast("str", payload["target_kind"]),
            series_profile_id=typ.cast("str | None", payload.get("series_profile_id")),
            episode_template_id=typ.cast(
                "str | None", payload.get("episode_template_id")
            ),
            ingestion_job_id=typ.cast("str | None", payload.get("ingestion_job_id")),
            effective_from_episode_id=typ.cast(
                "str | None", payload.get("effective_from_episode_id")
            ),
        )

        try:
            async with self._uow_factory() as uow:
                binding = await create_reference_binding(uow, data=data)
        except ReferenceDocumentError as exc:
            raise map_reference_error(exc, context="reference-binding") from exc

        resp.media = serialize_reference_binding(binding)
        resp.status = falcon.HTTP_201

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """List reusable reference bindings for one target context."""
        params = require_query_params(req, "target_kind", "target_id")
        limit, offset = parse_pagination(req)

        try:
            async with self._uow_factory() as uow:
                bindings = await list_reference_bindings(
                    uow,
                    request=ReferenceBindingListRequest(
                        target_kind=params["target_kind"],
                        target_id=str(parse_uuid(params["target_id"], "target_id")),
                        limit=limit,
                        offset=offset,
                    ),
                )
        except ReferenceDocumentError as exc:
            raise map_reference_error(exc, context="reference-binding") from exc

        resp.media = {
            "items": [serialize_reference_binding(item) for item in bindings],
            "limit": limit,
            "offset": offset,
        }
        resp.status = falcon.HTTP_200


class ReferenceBindingResource:
    """Handle get endpoint for one reusable reference binding."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        binding_id: str,
    ) -> None:
        """Fetch one reusable reference binding by identifier."""
        del req

        try:
            async with self._uow_factory() as uow:
                binding = await get_reference_binding(
                    uow,
                    binding_id=str(parse_uuid(binding_id, "binding_id")),
                )
        except ReferenceDocumentError as exc:
            raise map_reference_error(exc, context="reference-binding") from exc

        resp.media = serialize_reference_binding(binding)
        resp.status = falcon.HTTP_200
