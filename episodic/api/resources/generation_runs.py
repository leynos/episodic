"""Falcon resources for no-QA generation-run creation and polling."""

import datetime as dt
import typing as typ
import uuid

import falcon

from episodic.api.errors import http_error, map_source_intake_error
from episodic.api.helpers import parse_uuid, require_payload_dict
from episodic.api.resources.generation_runs_create_support import (
    _CreateGenerationRun,
    _parse_create_request,
)
from episodic.api.resources.generation_runs_errors import (
    _RETRY_AFTER,
    _generation_input_error,
    _generation_overloaded,
    _ingestion_job_not_found,
    _owns_ingestion_job,
)
from episodic.api.resources.generation_runs_events import (
    GenerationRunEventsResource,
    GenerationRunResource,
)
from episodic.api.serializers import serialize_generation_run
from episodic.api.source_idempotency import (
    IdempotencyContext,
    IdempotentResponse,
    apply_response,
    principal_id,
    run_idempotent,
)
from episodic.api.source_intake_support import json_body_hash
from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_persistence import (
    DraftScriptPersistenceError,
    EpisodeMaterialisationRequest,
    materialise_episode_from_ingestion,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.canonical.source_intake_service import SourceIntakeError
from episodic.generation.launcher import GenerationRunAdmissionError
from episodic.observability import NoopTracer

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.api.types import UowFactory
    from episodic.generation.launcher import GenerationRunLauncher
    from episodic.observability import TracerPort

__all__ = [
    "GenerationRunEventsResource",
    "GenerationRunResource",
    "GenerationRunsResource",
]

_GENERATION_RUN_OPERATION = "generation_run.create"

type Clock = cabc.Callable[[], dt.datetime]
type UuidFactory = cabc.Callable[[], uuid.UUID]


def _utc_now() -> dt.datetime:
    """Return the current UTC timestamp."""
    return dt.datetime.now(dt.UTC)


def _uuid7() -> uuid.UUID:
    """Return a time-ordered UUID."""
    return uuid.uuid7()


class GenerationRunsResource:
    """Create no-QA generation runs for authenticated ingestion-job owners.

    The resource materialises the caller-owned ready ingestion job, persists a
    durable generation-run checkpoint, and schedules detached execution. The
    authenticated principal becomes the durable run actor; request payloads
    cannot select another actor.
    """

    def __init__(  # noqa: PLR0913  # HTTP composition requires independent test seams.
        self,
        uow_factory: UowFactory,
        *,
        launcher: GenerationRunLauncher | None,
        clock: Clock = _utc_now,
        uuid_factory: UuidFactory = _uuid7,
        max_source_count: int | None = None,
        tracer: TracerPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._launcher = launcher
        self._clock = clock
        self._uuid_factory = uuid_factory
        self._max_source_count = max_source_count
        self._tracer = NoopTracer() if tracer is None else tracer

    async def on_post(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        ingestion_job_id: str,
    ) -> None:
        """Materialise and schedule a no-QA generation run.

        Parameters
        ----------
        ingestion_job_id
            Path identifier for the ready ingestion job owned by the
            authenticated principal.
        req
            Falcon request containing the no-QA command and idempotency key.
        resp
            Falcon response populated with the accepted run representation.

        Raises
        ------
        _ingestion_job_not_found
            If the caller has no access to the requested ingestion job.

        Notes
        -----
        ``Idempotency-Key`` is required. Replaying the same key for the same
        authenticated principal returns the original accepted response.
        Malformed input, unknown or inaccessible jobs, invalid source
        materialisation, unavailable launcher configuration, idempotency
        conflicts, and bounded-admission rejection use canonical HTTP error
        responses.
        """
        source_bundle_id = parse_uuid(ingestion_job_id, "ingestion_job_id")
        payload = require_payload_dict(await req.get_media())
        request = _parse_create_request(payload)
        launcher = self._require_launcher()
        idempotency_key = req.get_header("Idempotency-Key")
        actor = principal_id(req)
        if actor is None:
            raise _ingestion_job_not_found(source_bundle_id)

        async def work() -> IdempotentResponse:
            run = await self._create_run(
                source_bundle_id,
                request,
                actor=actor,
                idempotency_key=idempotency_key,
            )
            span.set_attribute("run_id", str(run.id))
            try:
                await launcher.launch(run.id)
            except GenerationRunAdmissionError as exc:
                span.set_attribute("outcome", "rejected")
                span.set_attribute("failure_category", "launcher.overloaded")
                await self._mark_launch_failed(
                    run.id,
                    error_message=str(exc),
                    error_category="launcher.overloaded",
                )
                raise _generation_overloaded() from exc
            except Exception as exc:
                span.set_attribute("outcome", "failed")
                span.set_attribute("failure_category", "launcher.scheduling")
                await self._mark_launch_failed(
                    run.id,
                    error_message=str(exc),
                    error_category="launcher.scheduling",
                )
                raise
            location = f"/v1/generation-runs/{run.id}"
            return IdempotentResponse(
                falcon.HTTP_202,
                serialize_generation_run(run),
                location=location,
                retry_after=_RETRY_AFTER,
            )

        with self._tracer.start_span(
            "generation_run.command",
            attributes={"operation": _GENERATION_RUN_OPERATION},
        ) as span:
            result = await run_idempotent(
                self._uow_factory,
                context=IdempotencyContext(
                    req=req,
                    operation=_GENERATION_RUN_OPERATION,
                    body_hash=json_body_hash(payload),
                ),
                work=work,
            )
            span.set_attribute("outcome", "accepted")
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
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> GenerationRun:
        async with self._uow_factory() as uow:
            job = await uow.ingestion_jobs.get(source_bundle_id)
            if job is None or not _owns_ingestion_job(job, actor):
                raise _ingestion_job_not_found(source_bundle_id)
            try:
                episode = await materialise_episode_from_ingestion(
                    uow,
                    EpisodeMaterialisationRequest(
                        ingestion_job_id=source_bundle_id,
                        title=f"Episode {source_bundle_id}",
                        clock=self._clock,
                        uuid_factory=self._uuid_factory,
                        max_source_count=(
                            32
                            if self._max_source_count is None
                            else self._max_source_count
                        ),
                    ),
                )
            except SourceIntakeError as exc:
                raise map_source_intake_error(exc) from exc
            except DraftScriptPersistenceError as exc:
                raise _generation_input_error(str(exc)) from exc
            now = self._clock()
            run = GenerationRun(
                id=self._uuid_factory(),
                episode_id=episode.id,
                source_bundle_id=source_bundle_id,
                actor=actor,
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
            run = await uow.generation_runs.create_run(
                run,
                idempotency_key=idempotency_key,
                idempotency_principal_id=actor,
            )
            await uow.commit()
            return run

    async def _mark_launch_failed(
        self,
        run_id: uuid.UUID,
        *,
        error_message: str,
        error_category: str,
    ) -> None:
        now = self._clock()
        async with self._uow_factory() as uow:
            try:
                await uow.generation_runs.update_run_status(
                    run_id,
                    update=GenerationRunStatusUpdate(
                        status=GenerationRunStatus.FAILED,
                        current_node=None,
                        ended_at=now,
                        error_message=error_message,
                        error_category=error_category,
                    ),
                )
            except RunAlreadyTerminal, RunNotFound:
                await uow.rollback()
            else:
                await uow.commit()
