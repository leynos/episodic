"""Falcon resources for source-intake uploads and ingestion jobs."""

from __future__ import annotations

import hashlib
import typing as typ

import falcon

from episodic.api.errors import http_error, map_source_intake_error
from episodic.api.helpers import (
    parse_enum_param,
    parse_optional_uuid_param,
    parse_pagination,
    parse_uuid,
    require_payload_dict,
)
from episodic.api.serializers import (
    serialize_ingestion_job,
    serialize_ingestion_job_source,
    serialize_upload,
)
from episodic.api.source_idempotency import (
    IdempotencyContext,
    IdempotentResponse,
    apply_response,
    principal_id,
    run_idempotent,
)
from episodic.api.source_intake_support import (
    UploadResourceConfig,
    build_attach_source_request,
    json_body_hash,
    parse_optional_payload_uuid,
    parse_upload_form,
    reject_oversized,
    require_str,
)
from episodic.canonical.domain import IngestionJobListFilters, IntakeState
from episodic.canonical.idempotency_service import (
    multipart_request_hash,
)
from episodic.canonical.source_intake_service import (
    CreateIngestionJobRequest,
    SourceIntakeError,
    UploadBytesRequest,
    attach_source_to_ingestion_job,
    create_ingestion_job,
    get_ingestion_job_status,
    list_ingestion_jobs,
    register_upload,
)

if typ.TYPE_CHECKING:
    from episodic.api.types import UowFactory

_UPLOAD_OPERATION = "upload.create"
_INGESTION_JOB_OPERATION = "ingestion_job.create"
_INGESTION_SOURCE_OPERATION = "ingestion_job.source.attach"


class UploadsResource:
    """Handle single-shot source upload creation."""

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        config: UploadResourceConfig,
    ) -> None:
        self._uow_factory = uow_factory
        self._config = config

    async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        """Create one ready upload from multipart form data."""
        object_store = self._config.object_store
        if object_store is None:
            raise http_error(
                falcon.HTTPServiceUnavailable(
                    description="Object storage is not configured."
                ),
                code="service_unavailable",
            )
        parsed = await parse_upload_form(req)
        reject_oversized(parsed.payload, self._config.max_bytes)
        if parsed.content_type not in self._config.content_types:
            raise http_error(
                falcon.HTTPUnsupportedMediaType(
                    description=f"Unsupported content_type: {parsed.content_type}."
                ),
                code="unsupported_content_type",
                details={"content_type": parsed.content_type},
            )
        metadata: dict[str, object] = {
            "content_type": parsed.content_type,
            "declared_size": parsed.declared_size,
            "declared_sha256": parsed.declared_sha256,
        }
        payload_sha256_hex = hashlib.sha256(parsed.payload).hexdigest()
        body_hash = multipart_request_hash(
            _UPLOAD_OPERATION,
            body_sha256=payload_sha256_hex,
            metadata=metadata,
        )

        async def work() -> IdempotentResponse:
            try:
                upload = await register_upload(
                    self._uow_factory,
                    object_store,
                    UploadBytesRequest(
                        owner_principal_id=principal_id(req),
                        content_type=parsed.content_type,
                        declared_size=parsed.declared_size,
                        declared_sha256=parsed.declared_sha256,
                        payload=parsed.payload,
                        max_bytes=self._config.max_bytes,
                        metadata=parsed.metadata,
                        payload_sha256=payload_sha256_hex,
                    ),
                )
            except SourceIntakeError as exc:
                raise map_source_intake_error(exc) from exc
            return IdempotentResponse(falcon.HTTP_201, serialize_upload(upload))

        result = await run_idempotent(
            self._uow_factory,
            context=IdempotencyContext(
                req=req,
                operation=_UPLOAD_OPERATION,
                body_hash=body_hash,
            ),
            work=work,
        )
        apply_response(resp, result)


class IngestionJobsResource:
    """Handle ingestion-job collection endpoints."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        """Create one intake-stage ingestion job."""
        payload = require_payload_dict(await req.get_media())
        body_hash = json_body_hash(payload)
        series_profile_id = parse_uuid(
            require_str(payload, "series_profile_id"), "series_profile_id"
        )
        target_episode_id = parse_optional_payload_uuid(payload, "target_episode_id")

        async def work() -> IdempotentResponse:
            async with self._uow_factory() as uow:
                try:
                    job = await create_ingestion_job(
                        uow,
                        CreateIngestionJobRequest(
                            series_profile_id=series_profile_id,
                            target_episode_id=target_episode_id,
                        ),
                    )
                except SourceIntakeError as exc:
                    raise map_source_intake_error(exc) from exc
            return IdempotentResponse(falcon.HTTP_201, serialize_ingestion_job(job))

        result = await run_idempotent(
            self._uow_factory,
            context=IdempotencyContext(
                req=req,
                operation=_INGESTION_JOB_OPERATION,
                body_hash=body_hash,
            ),
            work=work,
        )
        apply_response(resp, result)

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """List intake-stage ingestion jobs."""
        pagination = parse_pagination(req)
        series_profile_id = parse_optional_uuid_param(req, "series_profile_id")
        intake_state = parse_enum_param(req, "intake_state", IntakeState)
        async with self._uow_factory() as uow:
            page = await list_ingestion_jobs(
                uow,
                IngestionJobListFilters(
                    series_profile_id=series_profile_id,
                    intake_state=intake_state,
                ),
                pagination,
            )
        resp.media = {
            "items": [serialize_ingestion_job(job) for job in page.items],
            "limit": page.pagination.limit,
            "offset": page.pagination.offset,
            "total": page.total,
        }
        resp.status = falcon.HTTP_200


class IngestionJobResource:
    """Handle one ingestion-job status endpoint."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        job_id: str,
    ) -> None:
        """Return the current intake status for one ingestion job."""
        del req
        parsed_job_id = parse_uuid(job_id, "job_id")
        async with self._uow_factory() as uow:
            try:
                job = await get_ingestion_job_status(uow, parsed_job_id)
            except SourceIntakeError as exc:
                raise map_source_intake_error(exc) from exc
        next_poll = None
        if job.intake_state is IntakeState.AWAITING_SOURCES:
            next_poll = 5
        resp.media = serialize_ingestion_job(
            job,
            next_poll_after_seconds=next_poll,
        )
        resp.status = falcon.HTTP_200


class IngestionJobSourcesResource:
    """Handle source attachments for an ingestion job."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_post(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        job_id: str,
    ) -> None:
        """Attach one upload or remote URI source to an ingestion job."""
        parsed_job_id = parse_uuid(job_id, "job_id")
        payload = require_payload_dict(await req.get_media())
        body_hash = json_body_hash(payload)
        attach_request = build_attach_source_request(parsed_job_id, payload)

        async def work() -> IdempotentResponse:
            async with self._uow_factory() as uow:
                try:
                    source = await attach_source_to_ingestion_job(uow, attach_request)
                except SourceIntakeError as exc:
                    raise map_source_intake_error(exc) from exc
            return IdempotentResponse(
                falcon.HTTP_201,
                serialize_ingestion_job_source(source),
            )

        result = await run_idempotent(
            self._uow_factory,
            context=IdempotencyContext(
                req=req,
                operation=_INGESTION_SOURCE_OPERATION,
                body_hash=body_hash,
            ),
            work=work,
        )
        apply_response(resp, result)
