"""Route-versioning contract tests for the Falcon canonical API.

These tests implement the roadmap 4.1.1 route-versioning strategy. Canonical
client resources such as series profiles, episode templates, reference
documents, reference-document revisions, and reference bindings must be
registered under `/v1`. Representative unversioned canonical resource paths
must return `404`, proving they are not compatibility aliases.

Health endpoints are operator endpoints rather than client API resources.
`/health/live` and `/health/ready` must stay registered at root paths, while
`/v1/health/live` and `/v1/health/ready` remain unregistered.
"""

import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from falcon import testing

_CANONICAL_ROUTE_CONTRACT_PATHS = (
    ("/series-profiles", "series-profiles"),
    ("/series-profiles/not-a-valid-uuid", "series-profile"),
    ("/series-profiles/not-a-valid-uuid/brief", "series-profile-brief"),
    (
        "/series-profiles/not-a-valid-uuid/resolved-bindings",
        "resolved-bindings",
    ),
    ("/episode-templates", "episode-templates"),
    ("/episode-templates/not-a-valid-uuid", "episode-template"),
    (
        "/series-profiles/not-a-valid-uuid/reference-documents",
        "reference-documents",
    ),
    (
        (
            "/series-profiles/not-a-valid-uuid/reference-documents/"
            "not-a-valid-uuid/revisions"
        ),
        "reference-document-revisions",
    ),
    (
        "/reference-document-revisions/not-a-valid-uuid",
        "reference-document-revision",
    ),
    ("/reference-bindings", "reference-bindings"),
    ("/reference-bindings/not-a-valid-uuid", "reference-binding"),
)

_UNVERSIONED_CANONICAL_PATHS = tuple(
    (path, case_id) for path, case_id in _CANONICAL_ROUTE_CONTRACT_PATHS
)

_VERSIONED_CANONICAL_PATHS = tuple(
    (f"/v1{path}", case_id) for path, case_id in _CANONICAL_ROUTE_CONTRACT_PATHS
)


def test_versioned_canonical_api_routes_are_registered(
    canonical_api_client: testing.TestClient,
) -> None:
    """Route canonical API requests through `/v1` to their resource handlers."""
    for path, case_id in _VERSIONED_CANONICAL_PATHS:
        response = canonical_api_client.simulate_get(path)

        assert response.status_code != 404, (
            f"Expected registered /v1 route for {case_id}, got 404."
        )


def test_unversioned_canonical_api_routes_are_not_registered(
    canonical_api_client: testing.TestClient,
) -> None:
    """Keep pre-v0.1.0 canonical API routes unavailable without `/v1`."""
    for path, case_id in _UNVERSIONED_CANONICAL_PATHS:
        response = canonical_api_client.simulate_get(path)

        assert response.status_code == 404, (
            f"Expected 404 for unversioned {case_id}, got {response.status_code}."
        )


@pytest.mark.parametrize("path", ["/v1/health/live", "/v1/health/ready"])
def test_versioned_health_routes_are_not_registered(
    canonical_api_client: testing.TestClient,
    path: str,
) -> None:
    """Keep operator health endpoints outside the client-facing API prefix."""
    response = canonical_api_client.simulate_get(path)

    assert response.status_code == 404, (
        f"Expected 404 for {path}, got {response.status_code}."
    )


@pytest.mark.parametrize("path", ["/series-profiles", "/episode-templates"])
def test_unversioned_canonical_write_routes_are_not_registered(
    canonical_api_client: testing.TestClient,
    path: str,
) -> None:
    """Keep unversioned canonical write routes unavailable without `/v1`."""
    response = canonical_api_client.simulate_post(path, json={})

    assert response.status_code == 404, (
        f"Expected 404 for unversioned POST {path}, got {response.status_code}."
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
