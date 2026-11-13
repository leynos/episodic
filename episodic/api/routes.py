"""Bind canonical API resources to their Falcon paths.

This internal composition helper is called only by
:func:`episodic.api.app.create_app`. It keeps the route table and resource
construction out of the app factory while leaving request handling inside the
resource adapters.
"""

import typing as typ

from .resources import (
    EpisodeQaEvaluationsResource,
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
    QaEvaluationResource,
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
from .resources.generation_runs import GenerationRunsResourceConfig
from .source_intake_support import UploadResourceConfig

if typ.TYPE_CHECKING:
    from falcon import asgi

    from .dependencies import ApiDependencies
    from .types import UowFactory


def _register_health_routes(app: asgi.App, dependencies: ApiDependencies) -> None:
    """Register the liveness and readiness routes on *app*."""
    app.add_route("/health/live", HealthLiveResource())
    app.add_route(
        "/health/ready",
        HealthReadyResource(dependencies.readiness_observer()),
    )


def _register_series_profile_routes(
    app: asgi.App,
    uow_factory: UowFactory,
) -> None:
    """Register the series-profile routes on *app*."""
    app.add_route(
        "/v1/series-profiles",
        SeriesProfilesResource(uow_factory),
    )
    app.add_route(
        "/v1/series-profiles/{profile_id}",
        SeriesProfileResource(uow_factory),
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


def _register_episode_template_routes(
    app: asgi.App,
    uow_factory: UowFactory,
) -> None:
    """Register the episode-template routes on *app*."""
    app.add_route(
        "/v1/episode-templates",
        EpisodeTemplatesResource(uow_factory),
    )
    app.add_route(
        "/v1/episode-templates/{template_id}",
        EpisodeTemplateResource(uow_factory),
    )
    app.add_route(
        "/v1/episode-templates/{template_id}/history",
        EpisodeTemplateHistoryResource(uow_factory),
    )


def _register_reference_document_routes(
    app: asgi.App,
    uow_factory: UowFactory,
) -> None:
    """Register the reference-document and revision routes on *app*."""
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


def _register_reference_binding_routes(
    app: asgi.App,
    uow_factory: UowFactory,
) -> None:
    """Register the reference-binding routes on *app*."""
    app.add_route(
        "/v1/reference-bindings",
        ReferenceBindingsResource(uow_factory),
    )
    app.add_route(
        "/v1/reference-bindings/{binding_id}",
        ReferenceBindingResource(uow_factory),
    )


def _register_intake_routes(
    app: asgi.App,
    uow_factory: UowFactory,
    dependencies: ApiDependencies,
) -> None:
    """Register the upload and ingestion-job routes on *app*."""
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
    app.add_route(
        "/v1/ingestion-jobs",
        IngestionJobsResource(uow_factory),
    )
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
    """Register the generation-run creation and polling routes on *app*."""
    app.add_route(
        "/v1/ingestion-jobs/{ingestion_job_id}/generation-runs",
        GenerationRunsResource(
            uow_factory,
            GenerationRunsResourceConfig(
                launcher=dependencies.launcher,
                max_source_count=(
                    None
                    if dependencies.generation_source_limits is None
                    else dependencies.generation_source_limits.max_source_count
                ),
                tracer=dependencies.tracer,
            ),
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
    """Register the episode TEI route on *app*."""
    app.add_route(
        "/v1/episodes/{episode_id}/tei",
        EpisodeTeiResource(uow_factory, tracer=dependencies.tracer),
    )


def _register_qa_artefact_routes(
    app: asgi.App,
    uow_factory: UowFactory,
    dependencies: ApiDependencies,
) -> None:
    """Register the QA evaluation routes on *app*."""
    app.add_route(
        "/v1/episodes/{episode_id}/qa-evaluations",
        EpisodeQaEvaluationsResource(uow_factory, tracer=dependencies.tracer),
    )
    app.add_route(
        "/v1/qa-evaluations/{evaluation_id}",
        QaEvaluationResource(uow_factory, tracer=dependencies.tracer),
    )


def _register_api_routes(
    app: asgi.App,
    dependencies: ApiDependencies,
) -> None:
    """Attach canonical API resources to the Falcon app."""
    uow_factory = dependencies.uow_factory
    _register_health_routes(app, dependencies)
    _register_series_profile_routes(app, uow_factory)
    _register_episode_template_routes(app, uow_factory)
    _register_reference_document_routes(app, uow_factory)
    _register_reference_binding_routes(app, uow_factory)
    _register_intake_routes(app, uow_factory, dependencies)
    _register_generation_run_routes(app, uow_factory, dependencies)
    _register_episode_tei_routes(app, uow_factory, dependencies)
    _register_qa_artefact_routes(app, uow_factory, dependencies)
