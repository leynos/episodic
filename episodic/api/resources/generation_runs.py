"""Falcon resources for generation-run creation and polling.

Creation accepts ``qa_gated`` only when ``accepted_quality_modes`` includes
it; otherwise the historical ``422`` stands.

The request rules run on exactly one of two named paths, chosen by the
idempotency key and the requested mode:

| Key     | Mode             | Path                   | Why                          |
| ------- | ---------------- | ---------------------- | ---------------------------- |
| absent  | any              | before idempotency     | no replay; nothing is masked |
| present | draft_without_qa | before idempotency     | a key cannot hide a 400      |
| present | qa_gated         | in the idempotent work | a stored 202 still replays   |

A path validates once: the before-idempotency path passes its prepared result
into the work, and the in-work path validates inside it. Neither path
re-validates after a conflict, so a keyed gated conflict reports its ``409``
without a second rules pass.
"""

import dataclasses as dc
import typing as typ

import falcon

from episodic.api.errors import http_error, map_source_intake_error
from episodic.api.helpers import parse_uuid, require_payload_dict
from episodic.api.resources.generation_runs_create_support import (
    PreparedRequest,
    RequestRuleOrder,
    _CreateGenerationRun,
    _parse_create_request,
    _request_rule_order,
    _Submission,
    prepare_request,
)
from episodic.api.resources.generation_runs_errors import (
    _RETRY_AFTER,
    _generation_input_error,
    _ingestion_job_not_found,
    _owns_ingestion_job,
)
from episodic.api.resources.generation_runs_events import (
    GenerationRunEventsResource,
    GenerationRunResource,
)
from episodic.api.resources.generation_runs_scheduling import (
    SchedulingContext,
    create_and_schedule_run,
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
from episodic.canonical.source_intake_service import SourceIntakeError
from episodic.observability import NoopTracer
from episodic.runtime_providers import Clock, UuidFactory, utc_now, uuid7

if typ.TYPE_CHECKING:
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


def _idempotency_context(submission: _Submission) -> IdempotencyContext:
    """Build the idempotency context for one submission."""
    return IdempotencyContext(
        req=submission.req,
        operation=_GENERATION_RUN_OPERATION,
        body_hash=json_body_hash(submission.payload),
    )


class GenerationRunsResource:
    """Create generation runs for authenticated ingestion-job owners.

    The resource materialises the caller-owned ready ingestion job, persists a
    durable checkpoint, and schedules detached execution. The authenticated
    principal becomes the durable run actor; payloads cannot select another.
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
        """Materialise and schedule a generation run.

        Parameters
        ----------
        ingestion_job_id
            Path identifier for the ready ingestion job owned by the
            authenticated principal.
        req
            Falcon request containing the run command and idempotency key.
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
        """Choose the request-rule path and submit the creation work."""
        idempotency_key = submission.req.get_header("Idempotency-Key")
        if _request_rule_order(submission.request, idempotency_key) is (
            RequestRuleOrder.BEFORE_IDEMPOTENCY
        ):
            return await self._submit_before_idempotency(submission)
        return await self._submit_in_idempotent_work(submission)

    async def _submit_before_idempotency(
        self,
        submission: _Submission,
    ) -> IdempotentResponse:
        """Validate first, then create under the key if one was supplied."""
        idempotency_key = submission.req.get_header("Idempotency-Key")
        prepared = prepare_request(
            submission,
            accepted_quality_modes=self._accepted_quality_modes,
            resolve_launcher=self._require_launcher,
        )
        with self._command_span() as span:

            async def work() -> IdempotentResponse:
                """Create and schedule the run from the prepared request."""
                return await self._create_and_respond(
                    submission,
                    prepared,
                    idempotency_key=idempotency_key,
                    span=span,
                )

            result = await run_idempotent(
                self._uow_factory,
                context=_idempotency_context(submission),
                work=work,
            )
            span.set_attribute("outcome", "accepted")
        return result

    async def _submit_in_idempotent_work(
        self,
        submission: _Submission,
    ) -> IdempotentResponse:
        """Validate inside the idempotent work, so a rejection releases the key."""
        idempotency_key = submission.req.get_header("Idempotency-Key")
        with self._command_span() as span:

            async def work() -> IdempotentResponse:
                """Validate, create and schedule the run inside the work."""
                prepared = prepare_request(
                    submission,
                    accepted_quality_modes=self._accepted_quality_modes,
                    resolve_launcher=self._require_launcher,
                )
                return await self._create_and_respond(
                    submission,
                    prepared,
                    idempotency_key=idempotency_key,
                    span=span,
                )

            result = await run_idempotent(
                self._uow_factory,
                context=_idempotency_context(submission),
                work=work,
            )
            span.set_attribute("outcome", "accepted")
        return result

    async def _create_and_respond(
        self,
        submission: _Submission,
        prepared: PreparedRequest,
        *,
        idempotency_key: str | None,
        span: SpanHandle,
    ) -> IdempotentResponse:
        """Persist and schedule one prepared request, then build its 202."""
        launcher = (
            self._require_launcher() if prepared.launcher is None else prepared.launcher
        )
        run = await create_and_schedule_run(
            self._create_run(
                submission.source_bundle_id,
                prepared.request,
                actor=submission.actor,
                idempotency_key=idempotency_key,
            ),
            launcher,
            span,
            SchedulingContext(self._uow_factory, self._clock),
        )
        return _accepted_response(run)

    def _command_span(self) -> SpanHandle:
        """Start the command span every submission path shares."""
        return self._tracer.start_span(
            "generation_run.command",
            attributes={"operation": _GENERATION_RUN_OPERATION},
        )

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
