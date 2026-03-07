"""Access and optimistic-lock API tests for reusable reference documents."""

import typing as typ

import test_reference_document_api_support as support

if typ.TYPE_CHECKING:
    from falcon import testing


def test_series_aligned_host_guest_access_paths(
    canonical_api_client: testing.TestClient,
) -> None:
    """Host/guest reference documents should remain series aligned."""
    fixture = support._build_api_fixture(canonical_api_client)

    host_response = canonical_api_client.simulate_post(
        f"/series-profiles/{fixture.primary_profile_id}/reference-documents",
        json={
            "kind": "host_profile",
            "lifecycle_state": "active",
            "metadata": {"name": "Aligned Host"},
        },
    )
    assert host_response.status_code == 201
    host_document_id = typ.cast(
        "str", typ.cast("dict[str, object]", host_response.json)["id"]
    )

    guest_response = canonical_api_client.simulate_post(
        f"/series-profiles/{fixture.primary_profile_id}/reference-documents",
        json={
            "kind": "guest_profile",
            "lifecycle_state": "active",
            "metadata": {"name": "Aligned Guest"},
        },
    )
    assert guest_response.status_code == 201

    host_list_response = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/reference-documents",
        params={"kind": "host_profile", "limit": "10", "offset": "0"},
    )
    assert host_list_response.status_code == 200
    host_list_items = typ.cast(
        "list[dict[str, object]]",
        typ.cast("dict[str, object]", host_list_response.json)["items"],
    )
    assert len(host_list_items) == 1, "Expected one host-profile document."

    guest_list_response = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/reference-documents",
        params={"kind": "guest_profile", "limit": "10", "offset": "0"},
    )
    assert guest_list_response.status_code == 200
    guest_list_items = typ.cast(
        "list[dict[str, object]]",
        typ.cast("dict[str, object]", guest_list_response.json)["items"],
    )
    assert len(guest_list_items) == 1, "Expected one guest-profile document."

    cross_series_get = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.secondary_profile_id}/reference-documents/{host_document_id}"
    )
    assert cross_series_get.status_code == 404, (
        "Expected cross-series document lookup to return 404."
    )


def test_reference_document_api_rejects_boolean_expected_lock_version(
    canonical_api_client: testing.TestClient,
) -> None:
    """Document updates should reject boolean lock versions."""
    fixture = support._build_api_fixture(canonical_api_client)
    document_id = support._create_reference_document(
        canonical_api_client,
        profile_id=fixture.primary_profile_id,
        kind="host_profile",
        name="Host API Bool Lock Version",
    )

    response = canonical_api_client.simulate_patch(
        f"/series-profiles/{fixture.primary_profile_id}/reference-documents/{document_id}",
        json={
            "expected_lock_version": True,
            "lifecycle_state": "active",
            "metadata": {"name": "should fail"},
        },
    )
    support._assert_bad_request_error(
        response,
        description="expected_lock_version must be a positive integer.",
    )
