"""Falcon ASGI entry point for profile-template APIs.

This module exposes :func:`create_app`, which wires the canonical series
profile and episode template resources into a Falcon ASGI application.
Callers pass a unit-of-work factory and receive a ready-to-serve app object.

Example
-------
from episodic.api.app import create_app
app = create_app(uow_factory)  # Returns a Falcon ASGI app with API routes.
"""

import typing as typ

from falcon import asgi

from .resources import (
    EpisodeTemplateHistoryResource,
    EpisodeTemplateResource,
    EpisodeTemplatesResource,
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
)

if typ.TYPE_CHECKING:
    from .types import UowFactory


def create_app(uow_factory: UowFactory) -> asgi.App:
    """Build and return Falcon ASGI application for canonical APIs."""
    app = asgi.App()

    app.add_route("/series-profiles", SeriesProfilesResource(uow_factory))
    app.add_route("/series-profiles/{profile_id}", SeriesProfileResource(uow_factory))
    app.add_route(
        "/series-profiles/{profile_id}/history",
        SeriesProfileHistoryResource(uow_factory),
    )
    app.add_route(
        "/series-profiles/{profile_id}/brief",
        SeriesProfileBriefResource(uow_factory),
    )
    app.add_route(
        "/series-profiles/{profile_id}/resolved-bindings",
        ResolvedBindingsResource(uow_factory),
    )

    app.add_route("/episode-templates", EpisodeTemplatesResource(uow_factory))
    app.add_route(
        "/episode-templates/{template_id}",
        EpisodeTemplateResource(uow_factory),
    )
    app.add_route(
        "/episode-templates/{template_id}/history",
        EpisodeTemplateHistoryResource(uow_factory),
    )

    app.add_route(
        "/series-profiles/{profile_id}/reference-documents",
        ReferenceDocumentsResource(uow_factory),
    )
    app.add_route(
        "/series-profiles/{profile_id}/reference-documents/{document_id}",
        ReferenceDocumentResource(uow_factory),
    )
    app.add_route(
        "/series-profiles/{profile_id}/reference-documents/{document_id}/revisions",
        ReferenceDocumentRevisionsResource(uow_factory),
    )
    app.add_route(
        "/reference-document-revisions/{revision_id}",
        ReferenceDocumentRevisionResource(uow_factory),
    )
    app.add_route("/reference-bindings", ReferenceBindingsResource(uow_factory))
    app.add_route(
        "/reference-bindings/{binding_id}",
        ReferenceBindingResource(uow_factory),
    )

    return app
