"""Falcon resources for reusable reference-document endpoints."""

import typing as typ

import falcon

from episodic.api.helpers import (
    map_reference_error,
    parse_pagination,
    parse_uuid,
    require_payload_dict,
)
from episodic.api.serializers import (
    serialize_reference_document,
    serialize_reference_document_revision,
)
from episodic.canonical.reference_documents import (
    ReferenceDocumentCreateData,
    ReferenceDocumentError,
    ReferenceDocumentListRequest,
    ReferenceDocumentRevisionData,
    ReferenceDocumentRevisionListRequest,
    ReferenceDocumentUpdateRequest,
    create_reference_document,
    create_reference_document_revision,
    get_reference_document,
    get_reference_document_revision,
    list_reference_document_revisions,
    list_reference_documents,
    update_reference_document,
)

if typ.TYPE_CHECKING:
    from episodic.api.types import JsonPayload, UowFactory


def _parse_expected_lock_version(payload: JsonPayload) -> int:
    """Parse expected lock version from payload."""
    raw_expected = payload.get("expected_lock_version")
    if raw_expected is None:
        msg = "Missing required field: expected_lock_version"
        raise falcon.HTTPBadRequest(description=msg)
    try:
        expected = int(typ.cast("int | str", raw_expected))
    except (TypeError, ValueError) as exc:
        msg = "expected_lock_version must be a positive integer."
        raise falcon.HTTPBadRequest(description=msg) from exc
    if expected < 1:
        msg = "expected_lock_version must be a positive integer."
        raise falcon.HTTPBadRequest(description=msg)
    return expected


class ReferenceDocumentsResource:
    """Handle collection endpoints for reusable reference documents."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_post(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
    ) -> None:
        """Create one reusable reference document for a series profile."""
        payload = require_payload_dict(await req.get_media())
        missing = tuple(
            field
            for field in ("kind", "lifecycle_state", "metadata")
            if field not in payload
        )
        if missing:
            msg = f"Missing required field: {missing[0]}"
            raise falcon.HTTPBadRequest(description=msg)

        data = ReferenceDocumentCreateData(
            owner_series_profile_id=str(parse_uuid(profile_id, "profile_id")),
            kind=typ.cast("str", payload["kind"]),
            lifecycle_state=typ.cast("str", payload["lifecycle_state"]),
            metadata=typ.cast("dict[str, object]", payload["metadata"]),
        )

        try:
            async with self._uow_factory() as uow:
                document = await create_reference_document(uow, data=data)
        except ReferenceDocumentError as exc:
            raise map_reference_error(exc, context="reference-document") from exc

        resp.media = serialize_reference_document(document)
        resp.status = falcon.HTTP_201

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
    ) -> None:
        """List reusable reference documents for one series profile."""
        limit, offset = parse_pagination(req)
        kind = req.get_param("kind")

        try:
            async with self._uow_factory() as uow:
                documents = await list_reference_documents(
                    uow,
                    request=ReferenceDocumentListRequest(
                        owner_series_profile_id=str(
                            parse_uuid(profile_id, "profile_id")
                        ),
                        kind=kind,
                        limit=limit,
                        offset=offset,
                    ),
                )
        except ReferenceDocumentError as exc:
            raise map_reference_error(exc, context="reference-document") from exc

        resp.media = {
            "items": [serialize_reference_document(item) for item in documents],
            "limit": limit,
            "offset": offset,
        }
        resp.status = falcon.HTTP_200


class ReferenceDocumentResource:
    """Handle read/update endpoints for one reusable reference document."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
        document_id: str,
    ) -> None:
        """Fetch one reusable reference document by identifier."""
        del req
        try:
            async with self._uow_factory() as uow:
                document = await get_reference_document(
                    uow,
                    document_id=str(parse_uuid(document_id, "document_id")),
                    owner_series_profile_id=str(parse_uuid(profile_id, "profile_id")),
                )
        except ReferenceDocumentError as exc:
            raise map_reference_error(exc, context="reference-document") from exc

        resp.media = serialize_reference_document(document)
        resp.status = falcon.HTTP_200

    async def on_patch(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
        document_id: str,
    ) -> None:
        """Update one reusable reference document with optimistic locking."""
        payload = require_payload_dict(await req.get_media())
        missing = tuple(
            field for field in ("lifecycle_state", "metadata") if field not in payload
        )
        if missing:
            msg = f"Missing required field: {missing[0]}"
            raise falcon.HTTPBadRequest(description=msg)

        request = ReferenceDocumentUpdateRequest(
            document_id=str(parse_uuid(document_id, "document_id")),
            owner_series_profile_id=str(parse_uuid(profile_id, "profile_id")),
            expected_lock_version=_parse_expected_lock_version(payload),
            lifecycle_state=typ.cast("str", payload["lifecycle_state"]),
            metadata=typ.cast("dict[str, object]", payload["metadata"]),
        )

        try:
            async with self._uow_factory() as uow:
                updated = await update_reference_document(
                    uow,
                    request=request,
                )
        except ReferenceDocumentError as exc:
            raise map_reference_error(exc, context="reference-document") from exc

        resp.media = serialize_reference_document(updated)
        resp.status = falcon.HTTP_200


class ReferenceDocumentRevisionsResource:
    """Handle create/list endpoints for one document's immutable revisions."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_post(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
        document_id: str,
    ) -> None:
        """Create one immutable revision for a reusable reference document."""
        payload = require_payload_dict(await req.get_media())
        missing = tuple(
            field for field in ("content", "content_hash") if field not in payload
        )
        if missing:
            msg = f"Missing required field: {missing[0]}"
            raise falcon.HTTPBadRequest(description=msg)

        data = ReferenceDocumentRevisionData(
            content=typ.cast("dict[str, object]", payload["content"]),
            content_hash=typ.cast("str", payload["content_hash"]),
            author=typ.cast("str | None", payload.get("author")),
            change_note=typ.cast("str | None", payload.get("change_note")),
        )

        try:
            async with self._uow_factory() as uow:
                revision = await create_reference_document_revision(
                    uow,
                    document_id=str(parse_uuid(document_id, "document_id")),
                    owner_series_profile_id=str(parse_uuid(profile_id, "profile_id")),
                    data=data,
                )
        except ReferenceDocumentError as exc:
            raise map_reference_error(exc, context="reference-document") from exc

        resp.media = serialize_reference_document_revision(revision)
        resp.status = falcon.HTTP_201

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        profile_id: str,
        document_id: str,
    ) -> None:
        """List immutable revisions for one reusable reference document."""
        limit, offset = parse_pagination(req)

        try:
            async with self._uow_factory() as uow:
                revisions = await list_reference_document_revisions(
                    uow,
                    request=ReferenceDocumentRevisionListRequest(
                        document_id=str(parse_uuid(document_id, "document_id")),
                        owner_series_profile_id=str(
                            parse_uuid(profile_id, "profile_id")
                        ),
                        limit=limit,
                        offset=offset,
                    ),
                )
        except ReferenceDocumentError as exc:
            raise map_reference_error(exc, context="reference-document") from exc

        resp.media = {
            "items": [
                serialize_reference_document_revision(item) for item in revisions
            ],
            "limit": limit,
            "offset": offset,
        }
        resp.status = falcon.HTTP_200


class ReferenceDocumentRevisionResource:
    """Handle get endpoint for one immutable reference-document revision."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        revision_id: str,
    ) -> None:
        """Fetch one immutable revision by identifier."""
        owner_series_profile_id = req.get_param("owner_series_profile_id")

        try:
            async with self._uow_factory() as uow:
                revision = await get_reference_document_revision(
                    uow,
                    revision_id=str(parse_uuid(revision_id, "revision_id")),
                    owner_series_profile_id=(
                        None
                        if owner_series_profile_id is None
                        else str(
                            parse_uuid(
                                owner_series_profile_id,
                                "owner_series_profile_id",
                            )
                        )
                    ),
                )
        except ReferenceDocumentError as exc:
            raise map_reference_error(exc, context="reference-document") from exc

        resp.media = serialize_reference_document_revision(revision)
        resp.status = falcon.HTTP_200
