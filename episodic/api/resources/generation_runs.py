"""Falcon resources for no-QA generation-run creation and polling."""

import dataclasses as dc
import typing as typ

import falcon

from episodic.api.errors import http_error, map_source_intake_error
from episodic.api.helpers import parse_uuid, require_payload_dict
from episodic.api.resources.generation_runs_create_support import (
    _CreateGenerationRun,
    _parse_create_request,
    _Submission,
    _validate_quality_request,
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
from episodic.runtime_providers import Clock, UuidFactory, utc_now, uuid7

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.api.types import UowFactory
    from episodic.generation.launcher import GenerationRunLauncher
    from episodic.observability import SpanHandle, TracerPort


__all__ = [
    "GenerationRunEventsResource",
    "GenerationRunResource",
    "GenerationRunsResource",
]

_GENERATION_RUN_OPERATION = "generation_run.create"
_DEFAULT_MAX_SOURCE_COUNT = 32


@dc.dataclass(frozen=True, slots=True)
class GenerationRunsResourceConfig:
    """Ports and deterministic seams for generation-run resource creation.

    Parameters
    ----------
    launcher : GenerationRunLauncher | None
        Optional launcher that schedules detached generation work.
    clock : Clock
        Clock used to stamp persisted run state.
    uuid_factory : UuidFactory
        UUID source used to create deterministic run identifiers in tests.
    max_source_count : int | None
        Optional limit for source materialisation.
    tracer : TracerPort | None
        Optional tracing port used by the resource.
    accepted_quality_modes : frozenset[QualityMode]
        Quality modes this deployment can execute. ``draft_without_qa`` must
        always be present; ``qa_gated`` is added only when evaluators exist.
    """

    launcher: GenerationRunLauncher | None
    clock: Clock = utc_now
    uuid_factory: UuidFactory = uuid7
    max_source_count: int | None = None
    tracer: TracerPort | None = None
    accepted_quality_modes: frozenset[QualityMode] = frozenset({
        QualityMode.DRAFT_WITHOUT_QA
    })


def _accepted_response(run: GenerationRun) -> IdempotentResponse:
    """Build the 202 response for a scheduled generation run."""
    return IdempotentResponse(
        falcon.HTTP_202,
        serialize_generation_run(run),
        location=f"/v1/generation-runs/{run.id}",
        retry_after=_RETRY_AFTER,
    )


class GenerationRunsResource:
    """Create no-QA generation runs for authenticated ingestion-job owners.

    The resource materialises the caller-owned ready ingestion job, persists a
    durable generation-run checkpoint, and schedules detached execution.

    Notes
    -----
    The authenticated principal becomes the durable run actor; request
    payloads cannot select another actor.
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        config: GenerationRunsResourceConfig,
    ) -> None:
        """Store the unit-of-work factory, launcher, injected seams and tracer."""
        self._uow_factory = uow_factory
        self._launcher = config.launcher
        self._clock = config.clock
        self._uuid_factory = config.uuid_factory
        self._max_source_count = config.max_source_count
        self._tracer = NoopTracer() if config.tracer is None else config.tracer
        self._accepted_quality_modes = frozenset(config.accepted_quality_modes)

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
        A successful request populates ``resp`` with HTTP 202, the serialized
        run, its ``Location``, and ``Retry-After: 1``. ``Idempotency-Key`` is
        required; replay for the same principal returns the original response.
        """
        source_bundle_id = parse_uuid(ingestion_job_id, "ingestion_job_id")
        payload = require_payload_dict(await req.get_media())
        request = _parse_create_request(payload)
        actor = principal_id(req)
        if actor is None:
            raise _ingestion_job_not_found(source_bundle_id)
        submission = _Submission(
            req=req,
            payload=payload,
            request=request,
            source_bundle_id=source_bundle_id,
            actor=actor,
        )
        apply_response(resp, await self._submit(submission))

    async def _submit(self, submission: _Submission) -> IdempotentResponse:
        """Apply the request rules and run the idempotent creation work."""
        req = submission.req
        payload = submission.payload
        request = submission.request
        idempotency_key = req.get_header("Idempotency-Key")
        # Without a key no replay is possible, so the request rules are
        # reported before the missing-key error, as they were before this
        # item. With a key they run inside the idempotent work: a stored 202
        # must still replay after the deployment withdraws the capability, and
        # a rejection must release the key.
        launcher: GenerationRunLauncher | None = None
        has_key = idempotency_key is not None and bool(idempotency_key.strip())
        accepted_here = request.quality_mode in self._accepted_quality_modes
        if not has_key or accepted_here:
            # Base order: request errors are reported before a missing
            # launcher, so the 503 never masks a 400 or 422, and an accepted
            # mode's 503 precedes its idempotency outcomes. An unaccepted mode
            # is left to the work (or the replay it finds), so a stored gated
            # 202 still replays after the capability is withdrawn.
            request = _validate_quality_request(
                request,
                payload,
                self._accepted_quality_modes,
            )
            launcher = self._require_launcher()

        def _precondition() -> None:
            """Apply the body rules before a conflict is reported."""
            _validate_quality_request(
                request,
                payload,
                self._accepted_quality_modes,
            )

        with self._tracer.start_span(
            "generation_run.command",
            attributes={"operation": _GENERATION_RUN_OPERATION},
        ) as span:

            async def work() -> IdempotentResponse:
                """Create and schedule the run, then build its 202 response."""
                validated = _validate_quality_request(
                    request,
                    payload,
                    self._accepted_quality_modes,
                )
                resolved_launcher = (
                    self._require_launcher() if launcher is None else launcher
                )
                run = await self._create_and_schedule_run(
                    self._create_run(
                        submission.source_bundle_id,
                        validated,
                        actor=submission.actor,
                        idempotency_key=idempotency_key,
                    ),
                    resolved_launcher,
                    span,
                )
                return _accepted_response(run)

            result = await run_idempotent(
                self._uow_factory,
                context=IdempotencyContext(
                    req=req,
                    operation=_GENERATION_RUN_OPERATION,
                    body_hash=json_body_hash(payload),
                ),
                work=work,
                precondition=_precondition,
            )
            span.set_attribute("outcome", "accepted")
        return result

    async def _create_and_schedule_run(
        self,
        create_run: cabc.Awaitable[GenerationRun],
        launcher: GenerationRunLauncher,
        span: SpanHandle,
    ) -> GenerationRun:
        """Persist and schedule a run, recording terminal scheduling failures.

        Creation failures propagate unchanged. Scheduling failures first mark
        the persisted run terminal before propagating.

        Returns
        -------
        GenerationRun
            The persisted run after its launcher accepts scheduling.

        Raises
        ------
        _generation_overloaded
            If bounded launcher admission rejects the persisted run.
        """
        run = await create_run
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
        return run

    def _require_launcher(self) -> GenerationRunLauncher:
        """Return the configured launcher or raise a 503 error if absent."""
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
        """Materialise an episode and persist a pending run for an owned job."""
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
                            _DEFAULT_MAX_SOURCE_COUNT
                            if self._max_source_count is None
                            else self._max_source_count
                        ),
                    ),
                )
            except SourceIntakeError as exc:
                raise map_source_intake_error(
                    exc,
                ) from exc
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
                quality_mode=request.quality_mode,
                qa_status=(
                    QaStatus.PENDING
                    if request.quality_mode is QualityMode.QA_GATED
                    else QaStatus.SKIPPED
                ),
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
        """Mark a run failed, ignoring runs that are terminal or missing."""
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
