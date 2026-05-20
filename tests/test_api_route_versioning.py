"""Route-versioning contract tests for the Falcon canonical API.

These tests implement the roadmap 4.1.1 route-versioning strategy. Canonical
client resources such as series profiles, episode templates, reference
documents, reference-document revisions, and reference bindings must be
registered under `/v1`. Unversioned canonical resource paths must return
`404`, proving they are not compatibility aliases.

Health endpoints are operator endpoints rather than client API resources.
`/health/live` and `/health/ready` must stay registered at root paths, while
`/v1/health/live` remains unregistered.
"""

import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from falcon import testing

_CANONICAL_ROUTES = (
    ("/series-profiles", 200, "series-profiles"),
    ("/series-profiles/not-a-valid-uuid", 400, "series-profile"),
    ("/series-profiles/not-a-valid-uuid/history", 400, "series-profile-history"),
    ("/series-profiles/not-a-valid-uuid/brief", 400, "series-profile-brief"),
    (
        "/series-profiles/not-a-valid-uuid/resolved-bindings",
        400,
        "resolved-bindings",
    ),
    ("/episode-templates", 200, "episode-templates"),
    ("/episode-templates/not-a-valid-uuid", 400, "episode-template"),
    (
        "/episode-templates/not-a-valid-uuid/history",
        400,
        "episode-template-history",
    ),
    (
        "/series-profiles/not-a-valid-uuid/reference-documents",
        400,
        "reference-documents",
    ),
    (
        "/series-profiles/not-a-valid-uuid/reference-documents/not-a-valid-uuid",
        400,
        "reference-document",
    ),
    (
        (
            "/series-profiles/not-a-valid-uuid/reference-documents/"
            "not-a-valid-uuid/revisions"
        ),
        400,
        "reference-document-revisions",
    ),
    (
        "/reference-document-revisions/not-a-valid-uuid",
        400,
        "reference-document-revision",
    ),
    # Expects 400: listing reference bindings requires target_kind and target_id.
    ("/reference-bindings", 400, "reference-bindings"),
    ("/reference-bindings/not-a-valid-uuid", 400, "reference-binding"),
)

_UNVERSIONED_CANONICAL_PATHS = tuple(
    pytest.param(path, id=case_id)
    for path, _expected_status, case_id in _CANONICAL_ROUTES
)

_VERSIONED_CANONICAL_PATHS = tuple(
    pytest.param(f"/v1{path}", expected_status, id=case_id)
    for path, expected_status, case_id in _CANONICAL_ROUTES
)


@pytest.mark.parametrize(("path", "expected_status"), _VERSIONED_CANONICAL_PATHS)
def test_versioned_canonical_api_routes_are_registered(
    canonical_api_client: testing.TestClient,
    path: str,
    expected_status: int,
) -> None:
    """Route canonical API requests through `/v1` to their resource handlers."""
    response = canonical_api_client.simulate_get(path)

    assert response.status_code == expected_status, (
        f"Expected {expected_status} for {path}, got {response.status_code}."
    )


@pytest.mark.parametrize("path", _UNVERSIONED_CANONICAL_PATHS)
def test_unversioned_canonical_api_routes_are_not_registered(
    canonical_api_client: testing.TestClient,
    path: str,
) -> None:
    """Keep pre-v0.1.0 canonical API routes unavailable without `/v1`."""
    response = canonical_api_client.simulate_get(path)

    assert response.status_code == 404, (
        f"Expected 404 for unversioned {path}, got {response.status_code}."
    )


def test_versioned_health_route_is_not_registered(
    canonical_api_client: testing.TestClient,
) -> None:
    """Keep operator health endpoints outside the client-facing API prefix."""
    response = canonical_api_client.simulate_get("/v1/health/live")

    assert response.status_code == 404, (
        f"Expected 404 for /v1/health/live, got {response.status_code}."
    )


@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
def test_unversioned_health_routes_remain_registered(
    canonical_api_client: testing.TestClient,
    path: str,
) -> None:
    """Keep liveness and readiness endpoints available at root paths."""
    response = canonical_api_client.simulate_get(path)

    assert response.status_code == 200, (
        f"Expected 200 for {path}, got {response.status_code}."
    )
