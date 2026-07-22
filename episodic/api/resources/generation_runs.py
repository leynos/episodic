"""Falcon resources for no-QA generation-run creation and polling."""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import falcon

from episodic.api.errors import http_error, map_source_intake_error, validation_error
from episodic.api.helpers import parse_uuid, require_payload_dict
from episodic.api.serializers import (
    serialize_generation_event,
    serialize_generation_run,
)
from episodic.api.source_idempotency import (
    IdempotencyContext,
    IdempotentResponse,
    apply_response,
    run_idempotent,
)
from episodic.api.source_intake_support import json_body_hash, require_str
from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_persistence import (
    DraftScriptPersistenceError,
    EpisodeMaterialisationRequest,
    materialise_episode_from_ingestion,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_run_errors import RunNotFound
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate, event_seq
from episodic.canonical.source_intake_service import SourceIntakeError

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.api.types import JsonPayload, UowFactory
    from episodic.generation.launcher import GenerationRunLauncher

_GENERATION_RUN_OPERATION = "generation_run.create"
_RETRY_AFTER = "1"
_MAX_EVENT_LIMIT = 100


class GenerationRunsResource:
    """Create no-QA generation runs for ready ingestion jobs."""

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        launcher: GenerationRunLauncher | None,
    ) -> None:
        self._uow_factory = uow_factory
        self._launcher = launcher

    async def on_post(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        episode_id: str,
    ) -> None:
        """Materialize an episode and schedule its draft generation run."""
        source_bundle_id = parse_uuid(episode_id, "episode_id")
        payload = require_payload_dict(await req.get_media())
        request = _parse_create_request(payload)
        launcher = self._require_launcher()

        async def work() -> IdempotentResponse:
            run = await self._create_run(source_bundle_id, request)
            try:
                await launcher.launch(run.id)
            except Exception as exc:
                await self._mark_launch_failed(run.id, exc)
                raise
            location = f"/v1/generation-runs/{run.id}"
            return IdempotentResponse(
                falcon.HTTP_202,
                serialize_generation_run(run),
                location=location,
                retry_after=_RETRY_AFTER,
            )

        result = await run_idempotent(
            self._uow_factory,
            context=IdempotencyContext(
                req=req,
                operation=_GENERATION_RUN_OPERATION,
                body_hash=json_body_hash(payload),
            ),
            work=work,
        )
        apply_response(resp, result)

    def _require_launcher(self) -> GenerationRunLauncher:
        if self._launcher is None:
            raise http_error(
                falcon.HTTPServiceUnavailable(
                    description="Generation launcher is not configured."
                ),
                code="service_unavailable",
            )
        return self._launcher

    async def _create_run(
        self,
        source_bundle_id: uuid.UUID,
        request: _CreateGenerationRun,
    ) -> GenerationRun:
        async with self._uow_factory() as uow:
            try:
                episode = await materialise_episode_from_ingestion(
                    uow,
                    EpisodeMaterialisationRequest(
                        ingestion_job_id=source_bundle_id,
                        title=f"Episode {source_bundle_id}",
                        uuid_factory=_episode_uuid_factory(source_bundle_id),
                    ),
                )
            except SourceIntakeError as exc:
                raise map_source_intake_error(exc) from exc
            except DraftScriptPersistenceError as exc:
                raise _generation_input_error(str(exc)) from exc
            now = dt.datetime.now(dt.UTC)
            run = GenerationRun(
                id=uuid.uuid7(),
                episode_id=episode.id,
                source_bundle_id=source_bundle_id,
                actor=request.actor,
                status=GenerationRunStatus.PENDING,
                current_node=None,
                budget_snapshot=request.budget_snapshot,
                configuration=request.configuration,
                created_at=now,
                updated_at=now,
                started_at=None,
                ended_at=None,
                error_message=None,
                quality_mode=QualityMode.DRAFT_WITHOUT_QA,
                qa_status=QaStatus.SKIPPED,
                skip_qa_rationale=request.skip_qa_rationale,
            )
            await uow.generation_runs.create_run(run)
            await uow.commit()
            return run

    async def _mark_launch_failed(self, run_id: uuid.UUID, exc: Exception) -> None:
        now = dt.datetime.now(dt.UTC)
        async with self._uow_factory() as uow:
            await uow.generation_runs.update_run_status(
                run_id,
                update=GenerationRunStatusUpdate(
                    status=GenerationRunStatus.FAILED,
                    current_node=None,
                    ended_at=now,
                    error_message=str(exc),
                    error_category="launcher.schedule",
                ),
            )
            await uow.commit()


class GenerationRunResource:
    """Return one generation-run polling snapshot."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        run_id: str,
    ) -> None:
        """Return the current generation-run state."""
        del req
        parsed_run_id = parse_uuid(run_id, "run_id")
        async with self._uow_factory() as uow:
            run = await uow.generation_runs.get_run(parsed_run_id)
        if run is None:
            raise _run_not_found(parsed_run_id)
        resp.media = serialize_generation_run(run)
        resp.status = falcon.HTTP_200
        if not run.status.is_terminal():
            resp.set_header("Retry-After", _RETRY_AFTER)


class GenerationRunEventsResource:
    """Return cursor-paginated events for one generation run."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow_factory = uow_factory

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        run_id: str,
    ) -> None:
        """List events after an optional sequence cursor."""
        parsed_run_id = parse_uuid(run_id, "run_id")
        after_seq = _parse_optional_positive_int(req, "after_seq")
        limit = _parse_limit(req)
        async with self._uow_factory() as uow:
            try:
                events = await uow.generation_runs.list_events(
                    parsed_run_id,
                    after_seq=None if after_seq is None else event_seq(after_seq),
                    limit=limit,
                )
            except RunNotFound as exc:
                raise _run_not_found(parsed_run_id) from exc
        resp.media = {
            "items": [serialize_generation_event(event) for event in events],
            "after_seq": after_seq,
            "limit": limit,
        }
        resp.status = falcon.HTTP_200


class _CreateGenerationRun(typ.NamedTuple):
    actor: str
    skip_qa_rationale: str
    configuration: JsonPayload
    budget_snapshot: JsonPayload


def _parse_create_request(payload: JsonPayload) -> _CreateGenerationRun:
    quality_mode = require_str(payload, "quality_mode")
    if quality_mode == "qa_gated":
        raise typ.cast(
            "falcon.HTTPUnprocessableEntity",
            http_error(
                falcon.HTTPUnprocessableEntity(
                    description=f"Unsupported quality_mode: {quality_mode}."
                ),
                code="quality_mode_unsupported",
                details={"quality_mode": quality_mode},
            ),
        )
    try:
        parsed_mode = QualityMode(quality_mode)
    except ValueError as exc:
        message = f"Invalid quality_mode: {quality_mode!r}."
        raise validation_error(
            message,
            field="quality_mode",
            constraint="enum",
        ) from exc
    typ.assert_type(parsed_mode, QualityMode)
    configuration = {
        key: payload[key]
        for key in ("template_id", "prompt_overrides")
        if key in payload
    }
    budget_snapshot = _optional_mapping(payload, "budget_hints")
    return _CreateGenerationRun(
        actor=require_str(payload, "actor"),
        skip_qa_rationale=require_str(payload, "skip_qa_rationale"),
        configuration=configuration,
        budget_snapshot=budget_snapshot,
    )


def _optional_mapping(payload: JsonPayload, field_name: str) -> JsonPayload:
    value = payload.get(field_name, {})
    if not isinstance(value, dict):
        message = f"{field_name} must be a JSON object."
        raise validation_error(
            message,
            field=field_name,
            constraint="object",
        )
    return typ.cast("JsonPayload", value)


def _episode_uuid_factory(episode_id: uuid.UUID) -> cabc.Callable[[], uuid.UUID]:
    first = True

    def next_uuid() -> uuid.UUID:
        nonlocal first
        if first:
            first = False
            return episode_id
        return uuid.uuid7()

    return next_uuid


def _parse_optional_positive_int(req: falcon.Request, name: str) -> int | None:
    raw = req.get_param(name)
    if raw is None:
        return None
    value = _parse_int(raw, name)
    if value < 1:
        message = f"{name} must be a positive integer."
        raise validation_error(
            message,
            field=name,
            constraint="range",
        )
    return value


def _parse_limit(req: falcon.Request) -> int:
    raw = req.get_param("limit")
    value = _MAX_EVENT_LIMIT if raw is None else _parse_int(raw, "limit")
    if value < 1 or value > _MAX_EVENT_LIMIT:
        message = f"limit must be between 1 and {_MAX_EVENT_LIMIT}."
        raise validation_error(
            message,
            field="limit",
            constraint="range",
        )
    return value


def _parse_int(raw: str, name: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        message = f"{name} must be an integer."
        raise validation_error(
            message,
            field=name,
            constraint="type",
        ) from exc


def _run_not_found(run_id: uuid.UUID) -> falcon.HTTPNotFound:
    return typ.cast(
        "falcon.HTTPNotFound",
        http_error(
            falcon.HTTPNotFound(description=f"Generation run not found: {run_id}."),
            code="generation_run_not_found",
            details={"run_id": str(run_id)},
        ),
    )


def _generation_input_error(message: str) -> falcon.HTTPUnprocessableEntity:
    return typ.cast(
        "falcon.HTTPUnprocessableEntity",
        http_error(
            falcon.HTTPUnprocessableEntity(description=message),
            code="generation_input_invalid",
        ),
    )
