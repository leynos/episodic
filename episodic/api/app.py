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

import asyncio
import typing as typ

from falcon import asgi

from .authorization import AuthorizationMiddleware
from .errors import serialize_http_error
from .resources import (
    EpisodeTemplateHistoryResource,
    EpisodeTemplateResource,
    EpisodeTemplatesResource,
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
    from .dependencies import ApiDependencies, ShutdownHook
    from .types import UowFactory


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
        await asyncio.gather(
            *(shutdown_hook() for shutdown_hook in self._shutdown_hooks)
        )


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
        "/v1/ingestion-jobs/{job_id}",
        IngestionJobResource(uow_factory),
    )
    app.add_route(
        "/v1/ingestion-jobs/{job_id}/sources",
        IngestionJobSourcesResource(uow_factory),
    )


def create_app(dependencies: ApiDependencies) -> asgi.App:
    """Build and return Falcon ASGI application for canonical APIs."""
    app = asgi.App()
    app.add_middleware(AuthorizationMiddleware(dependencies.authorization))
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

    return app
