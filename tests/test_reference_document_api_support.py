"""Shared helpers for reference-document API tests."""

import typing as typ

from tests import api_fixtures

if typ.TYPE_CHECKING:
    from falcon import testing

ApiFixture = api_fixtures.ApiFixture
RevisionRequest = api_fixtures.RevisionRequest
post_and_return_id = api_fixtures.post_and_return_id
profile_body = api_fixtures.profile_body
build_api_fixture = api_fixtures.build_api_fixture
create_reference_document = api_fixtures.create_reference_document
assert_reference_document_list = api_fixtures.assert_reference_document_list
create_reference_document_revision = api_fixtures.create_reference_document_revision
assert_reference_revision_history = api_fixtures.assert_reference_revision_history
create_reference_binding = api_fixtures.create_reference_binding


def _assert_document_get_and_optimistic_lock(
    client: testing.TestClient,
    *,
    profile_id: str,
    document_id: str,
) -> None:
    """Assert get and optimistic-lock update behaviour for one document."""
    get_document_response = client.simulate_get(
        f"/v1/series-profiles/{profile_id}/reference-documents/{document_id}"
    )
    assert get_document_response.status_code == 200, (
        "unexpected status for GET reference document: "
        f"{get_document_response.status_code}"
    )

    update_document_response = client.simulate_patch(
        f"/v1/series-profiles/{profile_id}/reference-documents/{document_id}",
        json={
            "expected_lock_version": 1,
            "lifecycle_state": "active",
            "metadata": {"name": "Host API One Updated"},
        },
    )
    assert update_document_response.status_code == 200, (
        "unexpected status for PATCH reference document: "
        f"{update_document_response.status_code}"
    )
    updated_document = typ.cast("dict[str, object]", update_document_response.json)
    assert updated_document["lock_version"] == 2, (
        f"expected updated lock_version 2, got {updated_document['lock_version']}"
    )

    stale_update_response = client.simulate_patch(
        f"/v1/series-profiles/{profile_id}/reference-documents/{document_id}",
        json={
            "expected_lock_version": 1,
            "lifecycle_state": "archived",
            "metadata": {"name": "stale update"},
        },
    )
    assert stale_update_response.status_code == 409, (
        f"expected stale update to return 409, got {stale_update_response.status_code}"
    )


def _assert_revision_and_binding_workflow(
    client: testing.TestClient,
    *,
    profile_id: str,
    document_id: str,
    template_id: str,
) -> None:
    """Assert revision history and binding workflow endpoints."""
    first_revision_id = create_reference_document_revision(
        client,
        profile_id=profile_id,
        document_id=document_id,
        revision=RevisionRequest(
            summary="first revision",
            content_hash="api-reference-hash-1",
        ),
    )
    second_revision_id = create_reference_document_revision(
        client,
        profile_id=profile_id,
        document_id=document_id,
        revision=RevisionRequest(
            summary="second revision",
            content_hash="api-reference-hash-2",
        ),
    )
    revisions_items = assert_reference_revision_history(
        client,
        profile_id=profile_id,
        document_id=document_id,
    )
    assert [item["id"] for item in revisions_items] == [
        first_revision_id,
        second_revision_id,
    ], "Expected revision history to preserve creation order."

    get_revision_response = client.simulate_get(
        f"/v1/reference-document-revisions/{second_revision_id}"
    )
    assert get_revision_response.status_code == 200, (
        f"Unexpected status for GET revision: {get_revision_response.status_code}"
    )

    _assert_binding_list_workflow(
        client,
        second_revision_id=second_revision_id,
        template_id=template_id,
    )


def _assert_binding_list_workflow(
    client: testing.TestClient,
    *,
    second_revision_id: str,
    template_id: str,
) -> None:
    """Create a binding, verify it via GET, and assert the binding list response."""
    binding_id = create_reference_binding(
        client,
        revision_id=second_revision_id,
        template_id=template_id,
    )
    get_binding_response = client.simulate_get(f"/v1/reference-bindings/{binding_id}")
    assert get_binding_response.status_code == 200, (
        f"Unexpected status for GET binding: {get_binding_response.status_code}"
    )

    list_bindings_response = client.simulate_get(
        "/v1/reference-bindings",
        params={
            "target_kind": "episode_template",
            "target_id": template_id,
            "limit": "10",
            "offset": "0",
        },
    )
    assert list_bindings_response.status_code == 200, (
        "unexpected status for GET bindings list: "
        f"{list_bindings_response.status_code}: {list_bindings_response.text}"
    )
    bindings_payload = typ.cast("dict[str, object]", list_bindings_response.json)
    bindings_items = typ.cast("list[dict[str, object]]", bindings_payload["items"])
    assert bindings_payload["limit"] == 10, (
        f"expected limit 10 in bindings payload: {bindings_payload}"
    )
    assert bindings_payload["offset"] == 0, (
        f"expected offset 0 in bindings payload: {bindings_payload}"
    )
    assert len(bindings_items) == 1, (
        f"Expected one binding in list response, got {len(bindings_items)}"
    )


def _assert_bad_request_error(
    response: testing.Result,
    *,
    description: str | None = None,
) -> None:
    """Assert Falcon returned the stable HTTP 400 JSON error envelope."""
    assert response.status_code == 400, (
        f"expected 400 but got {response.status_code} for response={response}"
    )
    payload = typ.cast("dict[str, object]", response.json)
    assert payload["title"] == "400 Bad Request", (
        f"unexpected title in payload: {payload}"
    )
    if description is not None:
        assert payload["description"] == description, (
            f"unexpected description {payload.get('description')!r} "
            f"for expected {description!r} in payload: {payload}"
        )


def _binding_list_params(
    fixture: ApiFixture,
    **extra_params: str,
) -> dict[str, str]:
    """Build list-binding query params while preserving a valid target."""
    return {
        **extra_params,
        "target_kind": "episode_template",
        "target_id": fixture.template_id,
    }


def _seed_reference_binding(
    client: testing.TestClient,
    fixture: ApiFixture,
) -> None:
    """Create one document, revision, and binding for negative-path list tests."""
    document_id = create_reference_document(
        client,
        profile_id=fixture.primary_profile_id,
        kind="host_profile",
        name="Host API Validation",
    )
    revision_id = create_reference_document_revision(
        client,
        profile_id=fixture.primary_profile_id,
        document_id=document_id,
        revision=RevisionRequest(
            summary="validation revision",
            content_hash="api-reference-validation-hash",
        ),
    )
    create_reference_binding(
        client,
        revision_id=revision_id,
        template_id=fixture.template_id,
    )
