"""Validation API tests for reusable reference-document endpoints."""

import typing as typ

import test_reference_document_api_support as support

if typ.TYPE_CHECKING:
    from falcon import testing


def test_reference_document_api_rejects_invalid_pagination_params(
    canonical_api_client: testing.TestClient,
) -> None:
    """Reference-document list endpoints should reject invalid pagination values."""
    fixture = support._build_api_fixture(canonical_api_client)
    support._seed_reference_binding(canonical_api_client, fixture)
    bad_pagination_requests = (
        (
            f"/series-profiles/{fixture.primary_profile_id}/reference-documents",
            {"limit": "not-an-int"},
            "Pagination parameters limit/offset must be integers.",
        ),
        (
            f"/series-profiles/{fixture.primary_profile_id}/reference-documents",
            {"offset": "not-an-int"},
            "Pagination parameters limit/offset must be integers.",
        ),
        (
            f"/series-profiles/{fixture.primary_profile_id}/reference-documents",
            {"limit": "0"},
            "limit must be between 1 and 100.",
        ),
        (
            f"/series-profiles/{fixture.primary_profile_id}/reference-documents",
            {"limit": "101"},
            "limit must be between 1 and 100.",
        ),
        (
            f"/series-profiles/{fixture.primary_profile_id}/reference-documents",
            {"offset": "-1"},
            "offset must be a non-negative integer.",
        ),
        (
            "/reference-bindings",
            support._binding_list_params(fixture, limit="not-an-int"),
            "Pagination parameters limit/offset must be integers.",
        ),
        (
            "/reference-bindings",
            support._binding_list_params(fixture, offset="not-an-int"),
            "Pagination parameters limit/offset must be integers.",
        ),
        (
            "/reference-bindings",
            support._binding_list_params(fixture, limit="0"),
            "limit must be between 1 and 100.",
        ),
        (
            "/reference-bindings",
            support._binding_list_params(fixture, limit="101"),
            "limit must be between 1 and 100.",
        ),
        (
            "/reference-bindings",
            support._binding_list_params(fixture, offset="-1"),
            "offset must be a non-negative integer.",
        ),
    )
    for path, params, description in bad_pagination_requests:
        response = canonical_api_client.simulate_get(path, params=params)
        support._assert_bad_request_error(response, description=description)


def test_reference_document_api_rejects_missing_required_binding_params(
    canonical_api_client: testing.TestClient,
) -> None:
    """Binding list endpoint should reject requests missing required query params."""
    fixture = support._build_api_fixture(canonical_api_client)
    support._seed_reference_binding(canonical_api_client, fixture)

    missing_target_kind = canonical_api_client.simulate_get(
        "/reference-bindings",
        params={"target_id": fixture.template_id},
    )
    support._assert_bad_request_error(
        missing_target_kind,
        description="Missing required query parameter: target_kind",
    )

    missing_target_id = canonical_api_client.simulate_get(
        "/reference-bindings",
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
    fixture = support._build_api_fixture(canonical_api_client)

    invalid_document_id = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/reference-documents/not-a-valid-uuid"
    )
    support._assert_bad_request_error(
        invalid_document_id,
        description="Invalid UUID for document_id: 'not-a-valid-uuid'.",
    )

    invalid_revision_id = canonical_api_client.simulate_get(
        "/reference-document-revisions/not-a-valid-uuid"
    )
    support._assert_bad_request_error(
        invalid_revision_id,
        description="Invalid UUID for revision_id: 'not-a-valid-uuid'.",
    )

    invalid_binding_id = canonical_api_client.simulate_get(
        "/reference-bindings/not-a-valid-uuid"
    )
    support._assert_bad_request_error(
        invalid_binding_id,
        description="Invalid UUID for binding_id: 'not-a-valid-uuid'.",
    )

    invalid_target_id = canonical_api_client.simulate_get(
        "/reference-bindings",
        params={
            "target_kind": "episode_template",
            "target_id": "not-a-valid-uuid",
        },
    )
    support._assert_bad_request_error(
        invalid_target_id,
        description="Invalid UUID for target_id: 'not-a-valid-uuid'.",
    )
