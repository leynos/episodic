"""Literal route and method cases for authorization log tests."""

import typing as typ


class AuthorizationLogRouteCase(typ.NamedTuple):
    """Literal route data for authorization warning assertions."""

    resource_key: str
    request_path: str
    expected_resource_label: str


AUTHORIZATION_LOG_ROUTE_CASES = (
    AuthorizationLogRouteCase(
        "episode-templates",
        "/v1/episode-templates/Bearer%20sensitive-path-token",
        "/v1/episode-templates",
    ),
    AuthorizationLogRouteCase(
        "episodes",
        "/v1/episodes/Bearer%20sensitive-path-token",
        "/v1/episodes",
    ),
    AuthorizationLogRouteCase(
        "generation-runs",
        "/v1/generation-runs/Bearer%20sensitive-path-token",
        "/v1/generation-runs",
    ),
    AuthorizationLogRouteCase(
        "ingestion-jobs",
        "/v1/ingestion-jobs/Bearer%20sensitive-path-token",
        "/v1/ingestion-jobs",
    ),
    AuthorizationLogRouteCase(
        "reference-bindings",
        "/v1/reference-bindings/Bearer%20sensitive-path-token",
        "/v1/reference-bindings",
    ),
    AuthorizationLogRouteCase(
        "reference-document-revisions",
        "/v1/reference-document-revisions/Bearer%20sensitive-path-token",
        "/v1/reference-document-revisions",
    ),
    AuthorizationLogRouteCase(
        "series-profiles",
        "/v1/series-profiles/Bearer%20sensitive-path-token",
        "/v1/series-profiles",
    ),
    AuthorizationLogRouteCase(
        "uploads",
        "/v1/uploads/Bearer%20sensitive-path-token",
        "/v1/uploads",
    ),
)
STANDARD_AUTHORIZATION_LOG_METHODS = (
    "DELETE",
    "GET",
    "HEAD",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
)
