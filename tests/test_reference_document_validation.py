"""Validation API tests for reusable reference-document endpoints."""

import typing as typ

import pytest

import tests.test_reference_document_api_support as support

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from falcon import testing


@pytest.mark.parametrize(
    ("path_template", "params_builder", "description"),
    [
        (
            "/v1/series-profiles/{profile_id}/reference-documents",
            lambda fixture: {"limit": "not-an-int"},
            "Pagination parameters limit/offset must be integers.",
        ),
        (
            "/v1/series-profiles/{profile_id}/reference-documents",
            lambda fixture: {"offset": "not-an-int"},
            "Pagination parameters limit/offset must be integers.",
        ),
        (
            "/v1/series-profiles/{profile_id}/reference-documents",
            lambda fixture: {"limit": "0"},
            "limit must be between 1 and 100.",
        ),
        (
            "/v1/series-profiles/{profile_id}/reference-documents",
            lambda fixture: {"limit": "101"},
            "limit must be between 1 and 100.",
        ),
        (
            "/v1/series-profiles/{profile_id}/reference-documents",
            lambda fixture: {"offset": "-1"},
            "offset must be a non-negative integer.",
        ),
        (
            "/v1/reference-bindings",
            lambda fixture: support._binding_list_params(
                fixture,
                limit="not-an-int",
            ),
            "Pagination parameters limit/offset must be integers.",
        ),
        (
            "/v1/reference-bindings",
            lambda fixture: support._binding_list_params(
                fixture,
                offset="not-an-int",
            ),
            "Pagination parameters limit/offset must be integers.",
        ),
        (
            "/v1/reference-bindings",
            lambda fixture: support._binding_list_params(fixture, limit="0"),
            "limit must be between 1 and 100.",
        ),
        (
            "/v1/reference-bindings",
            lambda fixture: support._binding_list_params(fixture, limit="101"),
            "limit must be between 1 and 100.",
        ),
        (
            "/v1/reference-bindings",
            lambda fixture: support._binding_list_params(fixture, offset="-1"),
            "offset must be a non-negative integer.",
        ),
    ],
)
def test_reference_document_api_rejects_invalid_pagination_params(
    canonical_api_client: testing.TestClient,
    path_template: str,
    params_builder: cabc.Callable[[support.ApiFixture], dict[str, str]],
    description: str,
) -> None:
    """Reference-document list endpoints should reject invalid pagination values."""
    fixture = support.build_api_fixture(canonical_api_client)
    support._seed_reference_binding(canonical_api_client, fixture)
    path = path_template.format(profile_id=fixture.primary_profile_id)
    response = canonical_api_client.simulate_get(path, params=params_builder(fixture))
    support._assert_bad_request_error(response, description=description)


def test_reference_document_api_rejects_missing_required_binding_params(
    canonical_api_client: testing.TestClient,
) -> None:
    """Binding list endpoint should reject requests missing required query params."""
    fixture = support.build_api_fixture(canonical_api_client)
    support._seed_reference_binding(canonical_api_client, fixture)

    missing_target_kind = canonical_api_client.simulate_get(
        "/v1/reference-bindings",
        params={"target_id": fixture.template_id},
    )
    support._assert_bad_request_error(
        missing_target_kind,
        description="Missing required query parameter: target_kind",
    )

    missing_target_id = canonical_api_client.simulate_get(
        "/v1/reference-bindings",
        params={"target_kind": "episode_template"},
    )
    support._assert_bad_request_error(
        missing_target_id,
        description="Missing required query parameter: target_id",
    )


def test_reference_document_api_rejects_invalid_uuids(
    canonical_api_client: testing.TestClient,
) -> None:
    """Reference-document endpoints should reject syntactically invalid UUIDs."""
    fixture = support.build_api_fixture(canonical_api_client)

    invalid_document_id = canonical_api_client.simulate_get(
        f"/v1/series-profiles/{fixture.primary_profile_id}/reference-documents/not-a-valid-uuid"
    )
    support._assert_bad_request_error(
        invalid_document_id,
        description="Invalid UUID for document_id: 'not-a-valid-uuid'.",
    )

    invalid_revision_id = canonical_api_client.simulate_get(
        "/v1/reference-document-revisions/not-a-valid-uuid"
    )
    support._assert_bad_request_error(
        invalid_revision_id,
        description="Invalid UUID for revision_id: 'not-a-valid-uuid'.",
    )

    invalid_binding_id = canonical_api_client.simulate_get(
        "/v1/reference-bindings/not-a-valid-uuid"
    )
    support._assert_bad_request_error(
        invalid_binding_id,
        description="Invalid UUID for binding_id: 'not-a-valid-uuid'.",
    )

    invalid_target_id = canonical_api_client.simulate_get(
        "/v1/reference-bindings",
        params={
            "target_kind": "episode_template",
            "target_id": "not-a-valid-uuid",
        },
    )
    support._assert_bad_request_error(
        invalid_target_id,
        description="Invalid UUID for target_id: 'not-a-valid-uuid'.",
    )
