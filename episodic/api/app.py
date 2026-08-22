"""Falcon ASGI entry point for canonical HTTP APIs.

This module exposes :func:`create_app`, which wires the canonical series
profile, episode template, reference-document, and health resources into a
Falcon ASGI application. Callers pass a typed dependency object and receive a
ready-to-serve app object.

Example
-------
from episodic.api import ApiDependencies, create_app
dependencies = ApiDependencies(uow_factory=uow_factory)
app = create_app(dependencies)  # Returns a Falcon ASGI app with API routes.
"""

import time
import typing as typ

from falcon import asgi

from episodic.logging import get_logger, log_error

from .authorization import AuthorizationMiddleware
from .errors import serialize_http_error
from .resources import (
    EpisodeTeiResource,
    EpisodeTemplateHistoryResource,
    EpisodeTemplateResource,
    EpisodeTemplatesResource,
    GenerationRunEventsResource,
    GenerationRunResource,
    GenerationRunsResource,
    HealthLiveResource,
    HealthReadyResource,
    IngestionJobResource,
    IngestionJobSourcesResource,
    IngestionJobsResource,
    ReferenceBindingResource,
    ReferenceBindingsResource,
    ReferenceDocumentResource,
    ReferenceDocumentRevisionResource,
    ReferenceDocumentRevisionsResource,
    ReferenceDocumentsResource,
    ResolvedBindingsResource,
    SeriesProfileBriefResource,
    SeriesProfileHistoryResource,
    SeriesProfileResource,
    SeriesProfilesResource,
    UploadResource,
    UploadsResource,
)
from .source_intake_support import UploadResourceConfig

if typ.TYPE_CHECKING:
    from episodic.observability import MetricsPort

    from .dependencies import ApiDependencies, ShutdownHook
    from .types import UowFactory


logger = get_logger(__name__)

_GENERATION_REQUEST_TOTAL = "generation_api_request_total"
_GENERATION_REQUEST_LATENCY = "generation_api_request_latency_ms"


def _generation_route_operation(path: str) -> str | None:
    """Return a bounded operation name for an instrumented API path."""
    if path.startswith("/v1/ingestion-jobs/") and path.endswith("/generation-runs"):
        return "generation_run.command"
    if path.startswith("/v1/generation-runs/"):
        return (
            "generation_run.events.list"
            if path.endswith("/events")
            else "generation_run.read"
        )
    if path.startswith("/v1/episodes/") and path.endswith("/tei"):
        return "episode_tei.read"
    return None


class _GenerationRouteMetricsMiddleware:
    """Emit bounded generation-route outcome and latency observations."""

    def __init__(self, metrics: MetricsPort) -> None:
        self._metrics = metrics
        self._monotonic = time.perf_counter

    async def process_request(
        self,
        req: asgi.Request,
        resp: asgi.Response,
    ) -> None:
        """Start timing an instrumented generation route."""
        del resp
        operation = _generation_route_operation(req.path)
        if operation is not None:
            req.context["generation_api_metrics"] = (
                operation,
                self._monotonic(),
            )

    async def process_response(
        self,
        req: asgi.Request,
        resp: asgi.Response,
        resource: object,
        req_succeeded: bool,  # noqa: FBT001  # Falcon ASGI middleware contract.
    ) -> None:
        """Record the completed response without retaining request data."""
        del resource, req_succeeded
        observation = req.context.get("generation_api_metrics")
        if not isinstance(observation, tuple):
            return
        operation, started_at = typ.cast(
            "tuple[str, float]",
            observation,
        )
        if not isinstance(operation, str) or not isinstance(started_at, float):
            return
        outcome = _response_outcome(resp.status)
        labels = {"operation": operation, "outcome": outcome}
        self._metrics.increment_counter(_GENERATION_REQUEST_TOTAL, labels=labels)
        self._metrics.observe_latency_ms(
            _GENERATION_REQUEST_LATENCY,
            (self._monotonic() - started_at) * 1_000,
            labels=labels,
        )


def _response_outcome(status: str | int) -> str:
    """Map an HTTP response status to a bounded metric outcome."""
    status = str(status)
    if status.startswith("304"):
        return "not_modified"
    if status.startswith("2"):
        return "success"
    if status.startswith("4"):
        return "rejected"
    return "failed"


class _ShutdownHooksMiddleware:
    """Run injected async cleanup hooks during the ASGI shutdown phase."""

    def __init__(self, shutdown_hooks: tuple[ShutdownHook, ...]) -> None:
        self._shutdown_hooks = shutdown_hooks

    async def process_shutdown(
        self,
        scope: dict[str, typ.Any],
        event: dict[str, typ.Any],
    ) -> None:
        """Release runtime-managed resources before the process exits."""
        del scope, event
        first_failure: Exception | None = None
        for shutdown_hook in self._shutdown_hooks:
            try:
                await shutdown_hook()
            except Exception as exc:  # noqa: BLE001 - cleanup must attempt every hook.
                log_error(logger, "ASGI shutdown hook failed.", exc_info=True)
                if first_failure is None:
                    first_failure = exc
        if first_failure is not None:
            raise first_failure


def _register_health_routes(app: asgi.App, dependencies: ApiDependencies) -> None:
    app.add_route("/health/live", HealthLiveResource())
    app.add_route(
        "/health/ready",
        HealthReadyResource(dependencies.readiness_observer()),
    )


def _register_series_profile_routes(app: asgi.App, uow_factory: UowFactory) -> None:
    app.add_route("/v1/series-profiles", SeriesProfilesResource(uow_factory))
    app.add_route(
        "/v1/series-profiles/{profile_id}", SeriesProfileResource(uow_factory)
    )
    app.add_route(
        "/v1/series-profiles/{profile_id}/history",
        SeriesProfileHistoryResource(uow_factory),
    )
    app.add_route(
        "/v1/series-profiles/{profile_id}/brief",
        SeriesProfileBriefResource(uow_factory),
    )
    app.add_route(
        "/v1/series-profiles/{profile_id}/resolved-bindings",
        ResolvedBindingsResource(uow_factory),
    )


def _register_episode_template_routes(app: asgi.App, uow_factory: UowFactory) -> None:
    app.add_route("/v1/episode-templates", EpisodeTemplatesResource(uow_factory))
    app.add_route(
        "/v1/episode-templates/{template_id}",
        EpisodeTemplateResource(uow_factory),
    )
    app.add_route(
        "/v1/episode-templates/{template_id}/history",
        EpisodeTemplateHistoryResource(uow_factory),
    )


def _register_reference_document_routes(app: asgi.App, uow_factory: UowFactory) -> None:
    app.add_route(
        "/v1/series-profiles/{profile_id}/reference-documents",
        ReferenceDocumentsResource(uow_factory),
    )
    app.add_route(
        "/v1/series-profiles/{profile_id}/reference-documents/{document_id}",
        ReferenceDocumentResource(uow_factory),
    )
    app.add_route(
        "/v1/series-profiles/{profile_id}/reference-documents/{document_id}/revisions",
        ReferenceDocumentRevisionsResource(uow_factory),
    )
    app.add_route(
        "/v1/reference-document-revisions/{revision_id}",
        ReferenceDocumentRevisionResource(uow_factory),
    )


def _register_reference_binding_routes(app: asgi.App, uow_factory: UowFactory) -> None:
    app.add_route("/v1/reference-bindings", ReferenceBindingsResource(uow_factory))
    app.add_route(
        "/v1/reference-bindings/{binding_id}",
        ReferenceBindingResource(uow_factory),
    )


def _register_intake_routes(
    app: asgi.App,
    uow_factory: UowFactory,
    dependencies: ApiDependencies,
) -> None:
    app.add_route(
        "/v1/uploads",
        UploadsResource(
            uow_factory,
            config=UploadResourceConfig(
                object_store=dependencies.object_store,
                max_bytes=dependencies.upload_max_bytes,
                content_types=frozenset(dependencies.upload_content_types),
            ),
        ),
    )
    app.add_route("/v1/uploads/{upload_id}", UploadResource(uow_factory))
    app.add_route("/v1/ingestion-jobs", IngestionJobsResource(uow_factory))
    app.add_route(
        "/v1/ingestion-jobs/{ingestion_job_id}",
        IngestionJobResource(uow_factory),
    )
    app.add_route(
        "/v1/ingestion-jobs/{ingestion_job_id}/sources",
        IngestionJobSourcesResource(uow_factory),
    )


def _register_generation_run_routes(
    app: asgi.App,
    uow_factory: UowFactory,
    dependencies: ApiDependencies,
) -> None:
    app.add_route(
        "/v1/ingestion-jobs/{ingestion_job_id}/generation-runs",
        GenerationRunsResource(
            uow_factory,
            launcher=dependencies.launcher,
            max_source_count=(
                None
                if dependencies.generation_source_limits is None
                else dependencies.generation_source_limits.max_source_count
            ),
            tracer=dependencies.tracer,
        ),
    )
    app.add_route(
        "/v1/generation-runs/{run_id}",
        GenerationRunResource(uow_factory, tracer=dependencies.tracer),
    )
    app.add_route(
        "/v1/generation-runs/{run_id}/events",
        GenerationRunEventsResource(uow_factory, tracer=dependencies.tracer),
    )


def _register_episode_tei_routes(
    app: asgi.App,
    uow_factory: UowFactory,
    dependencies: ApiDependencies,
) -> None:
    app.add_route(
        "/v1/episodes/{episode_id}/tei",
        EpisodeTeiResource(uow_factory, tracer=dependencies.tracer),
    )


def create_app(dependencies: ApiDependencies) -> asgi.App:
    """Build and return Falcon ASGI application for canonical APIs."""
    app = asgi.App()
    app.add_middleware(AuthorizationMiddleware(dependencies.authorization))
    app.add_middleware(_GenerationRouteMetricsMiddleware(dependencies.metrics))
    if dependencies.shutdown_hooks:
        # Falcon supports lifespan middleware at runtime, but its exported
        # middleware type union does not model process_shutdown-only hooks.
        app.add_middleware(
            typ.cast("typ.Any", _ShutdownHooksMiddleware(dependencies.shutdown_hooks))
        )
    app.set_error_serializer(serialize_http_error)

    uow_factory = dependencies.uow_factory

    _register_health_routes(app, dependencies)
    _register_series_profile_routes(app, uow_factory)
    _register_episode_template_routes(app, uow_factory)
    _register_reference_document_routes(app, uow_factory)
    _register_reference_binding_routes(app, uow_factory)
    _register_intake_routes(app, uow_factory, dependencies)
    _register_generation_run_routes(app, uow_factory, dependencies)
    _register_episode_tei_routes(app, uow_factory, dependencies)

    return app
