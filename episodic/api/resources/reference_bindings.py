"""Falcon resources for reusable reference-binding endpoints."""

import typing as typ

import falcon

from episodic.api.helpers import parse_uuid, require_payload_dict
from episodic.api.serializers import serialize_reference_binding
from episodic.canonical.reference_documents import (
    ReferenceBindingData,
    ReferenceBindingListRequest,
    ReferenceConflictError,
    ReferenceEntityNotFoundError,
    ReferenceRevisionConflictError,
    ReferenceValidationError,
    create_reference_binding,
    get_reference_binding,
    list_reference_bindings,
)

if typ.TYPE_CHECKING:
    from episodic.api.types import JsonPayload, UowFactory

_DEFAULT_PAGE_LIMIT = 20
_MAX_PAGE_LIMIT = 100


def _map_reference_error(exc: Exception) -> falcon.HTTPError:
    """Map reference-binding errors to Falcon HTTP errors."""
    if isinstance(exc, ReferenceValidationError):
        return falcon.HTTPBadRequest(description=str(exc))
    if isinstance(exc, ReferenceEntityNotFoundError):
        return falcon.HTTPNotFound(description=str(exc))
    if isinstance(exc, (ReferenceRevisionConflictError, ReferenceConflictError)):
        return falcon.HTTPConflict(description=str(exc))
    msg = "Unexpected reference-binding error."
    return falcon.HTTPInternalServerError(description=msg)


def _parse_pagination(req: falcon.Request) -> tuple[int, int]:
    """Parse `limit` and `offset` query parameters."""
    raw_limit = req.get_param("limit")
    raw_offset = req.get_param("offset")

    try:
        limit = _DEFAULT_PAGE_LIMIT if raw_limit is None else int(raw_limit)
        offset = 0 if raw_offset is None else int(raw_offset)
    except ValueError as exc:
        msg = "Pagination parameters limit/offset must be integers."
        raise falcon.HTTPBadRequest(description=msg) from exc

    if limit < 1 or limit > _MAX_PAGE_LIMIT:
        msg = f"limit must be between 1 and {_MAX_PAGE_LIMIT}."
        raise falcon.HTTPBadRequest(description=msg)
    if offset < 0:
        msg = "offset must be a non-negative integer."
        raise falcon.HTTPBadRequest(description=msg)
    return limit, offset


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
        except Exception as exc:
            raise _map_reference_error(exc) from exc

        resp.media = serialize_reference_binding(binding)
        resp.status = falcon.HTTP_201

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """List reusable reference bindings for one target context."""
        payload = typ.cast("JsonPayload", {})
        payload["target_kind"] = req.get_param("target_kind")
        payload["target_id"] = req.get_param("target_id")

        missing = tuple(
            field
            for field in ("target_kind", "target_id")
            if payload.get(field) is None
        )
        if missing:
            msg = f"Missing required query parameter: {missing[0]}"
            raise falcon.HTTPBadRequest(description=msg)

        limit, offset = _parse_pagination(req)

        try:
            async with self._uow_factory() as uow:
                bindings = await list_reference_bindings(
                    uow,
                    request=ReferenceBindingListRequest(
                        target_kind=typ.cast("str", payload["target_kind"]),
                        target_id=str(
                            parse_uuid(
                                typ.cast("str", payload["target_id"]),
                                "target_id",
                            )
                        ),
                        limit=limit,
                        offset=offset,
                    ),
                )
        except Exception as exc:
            raise _map_reference_error(exc) from exc

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
        except Exception as exc:
            raise _map_reference_error(exc) from exc

        resp.media = serialize_reference_binding(binding)
        resp.status = falcon.HTTP_200
