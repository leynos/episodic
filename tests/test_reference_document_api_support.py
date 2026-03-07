"""Shared helpers for reference-document API tests."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    from falcon import testing


@dc.dataclass(frozen=True, slots=True)
class _ApiFixture:
    """Fixture payload for reference-document API tests."""

    primary_profile_id: str
    secondary_profile_id: str
    template_id: str


def _post_and_return_id(
    client: testing.TestClient,
    path: str,
    body: dict[str, object],
    *,
    assertion_message: str | None = None,
) -> str:
    """POST *body* to *path*, assert HTTP 201, and return the ``id`` field."""
    response = client.simulate_post(path, json=body)
    msg = assertion_message or f"Expected POST {path} to return 201."
    assert response.status_code == 201, msg
    return typ.cast("str", typ.cast("dict[str, object]", response.json)["id"])


def _profile_body(slug: str) -> dict[str, object]:
    """Return a series-profile creation body for *slug*."""
    return {
        "slug": slug,
        "title": f"{slug} title",
        "description": f"{slug} description",
        "configuration": {"tone": "neutral"},
        "actor": "api-reference@example.com",
        "note": "Create profile",
    }


def _build_api_fixture(client: testing.TestClient) -> _ApiFixture:
    """Build common API fixture entities for reference-document endpoint tests."""
    primary_profile_id = _post_and_return_id(
        client,
        "/series-profiles",
        _profile_body("api-reference-primary"),
        assertion_message="Expected profile creation to return 201.",
    )
    secondary_profile_id = _post_and_return_id(
        client,
        "/series-profiles",
        _profile_body("api-reference-secondary"),
        assertion_message="Expected profile creation to return 201.",
    )
    template_id = _post_and_return_id(
        client,
        "/episode-templates",
        {
            "series_profile_id": primary_profile_id,
            "slug": "api-reference-template",
            "title": "api-reference-template title",
            "description": "api-reference-template description",
            "structure": {"segments": ["intro", "main", "outro"]},
            "actor": "api-reference@example.com",
            "note": "Create template",
        },
        assertion_message="Expected template creation to return 201.",
    )
    return _ApiFixture(
        primary_profile_id=primary_profile_id,
        secondary_profile_id=secondary_profile_id,
        template_id=template_id,
    )


def _create_reference_document(
    client: testing.TestClient,
    *,
    profile_id: str,
    kind: str,
    name: str,
) -> str:
    """Create one reusable reference document and return its identifier."""
    response = client.simulate_post(
        f"/series-profiles/{profile_id}/reference-documents",
        json={
            "kind": kind,
            "lifecycle_state": "active",
            "metadata": {"name": name},
        },
    )
    assert response.status_code == 201, (
        "expected 201 creating reference document, got "
        f"{response.status_code}: {response.text}"
    )
    payload = typ.cast("dict[str, object]", response.json)
    assert payload["lock_version"] == 1, (
        f"unexpected lock_version in payload: {payload}"
    )
    return typ.cast("str", payload["id"])


def _assert_reference_document_list(
    client: testing.TestClient,
    *,
    profile_id: str,
    kind: str | None = None,
) -> list[dict[str, object]]:
    """List reference documents and assert a valid list envelope."""
    params: dict[str, str] = {"limit": "10", "offset": "0"}
    if kind is not None:
        params["kind"] = kind

    response = client.simulate_get(
        f"/series-profiles/{profile_id}/reference-documents",
        params=params,
    )
    assert response.status_code == 200, (
        f"unexpected status for GET reference documents: {response.status_code}: "
        f"{response.text}"
    )
    payload = typ.cast("dict[str, object]", response.json)
    assert isinstance(payload, dict), f"expected list payload dict, got: {payload!r}"
    items = typ.cast("list[dict[str, object]]", payload["items"])
    assert isinstance(items, list), f"expected items list in payload: {payload}"
    assert payload["limit"] == 10, f"expected limit 10 in payload: {payload}"
    assert payload["offset"] == 0, f"expected offset 0 in payload: {payload}"
    return items


@dc.dataclass(frozen=True, slots=True)
class _RevisionRequest:
    summary: str
    content_hash: str


def _create_reference_document_revision(
    client: testing.TestClient,
    *,
    profile_id: str,
    document_id: str,
    revision: _RevisionRequest,
) -> str:
    """Create one immutable reference-document revision and return its id."""
    response = client.simulate_post(
        f"/series-profiles/{profile_id}/reference-documents/{document_id}/revisions",
        json={
            "content": {"summary": revision.summary},
            "content_hash": revision.content_hash,
            "author": "api-reference@example.com",
            "change_note": revision.summary,
        },
    )
    assert response.status_code == 201, (
        "expected 201 creating reference-document revision, got "
        f"{response.status_code}: {response.text}"
    )
    payload = typ.cast("dict[str, object]", response.json)
    return typ.cast("str", payload["id"])


def _assert_reference_revision_history(
    client: testing.TestClient,
    *,
    profile_id: str,
    document_id: str,
) -> list[dict[str, object]]:
    """List immutable revisions and assert a valid list envelope."""
    response = client.simulate_get(
        f"/series-profiles/{profile_id}/reference-documents/{document_id}/revisions",
        params={"limit": "10", "offset": "0"},
    )
    assert response.status_code == 200, (
        f"unexpected status for GET revision history: {response.status_code}: "
        f"{response.text}"
    )
    payload = typ.cast("dict[str, object]", response.json)
    items = typ.cast("list[dict[str, object]]", payload["items"])
    assert payload["limit"] == 10, f"expected limit 10, got {payload['limit']}"
    assert payload["offset"] == 0, f"expected offset 0, got {payload['offset']}"
    return items


def _create_reference_binding(
    client: testing.TestClient,
    *,
    revision_id: str,
    template_id: str,
) -> str:
    """Create one reference binding and return its identifier."""
    response = client.simulate_post(
        "/reference-bindings",
        json={
            "reference_document_revision_id": revision_id,
            "target_kind": "episode_template",
            "episode_template_id": template_id,
        },
    )
    assert response.status_code == 201, (
        "expected 201 creating reference binding, got "
        f"{response.status_code}: {response.text}"
    )
    payload = typ.cast("dict[str, object]", response.json)
    return typ.cast("str", payload["id"])


def _assert_document_get_and_optimistic_lock(
    client: testing.TestClient,
    *,
    profile_id: str,
    document_id: str,
) -> None:
    """Assert get and optimistic-lock update behaviour for one document."""
    get_document_response = client.simulate_get(
        f"/series-profiles/{profile_id}/reference-documents/{document_id}"
    )
    assert get_document_response.status_code == 200, (
        "unexpected status for GET reference document: "
        f"{get_document_response.status_code}"
    )

    update_document_response = client.simulate_patch(
        f"/series-profiles/{profile_id}/reference-documents/{document_id}",
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
        f"/series-profiles/{profile_id}/reference-documents/{document_id}",
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
    first_revision_id = _create_reference_document_revision(
        client,
        profile_id=profile_id,
        document_id=document_id,
        revision=_RevisionRequest(
            summary="first revision",
            content_hash="api-reference-hash-1",
        ),
    )
    second_revision_id = _create_reference_document_revision(
        client,
        profile_id=profile_id,
        document_id=document_id,
        revision=_RevisionRequest(
            summary="second revision",
            content_hash="api-reference-hash-2",
        ),
    )
    revisions_items = _assert_reference_revision_history(
        client,
        profile_id=profile_id,
        document_id=document_id,
    )
    assert [item["id"] for item in revisions_items] == [
        first_revision_id,
        second_revision_id,
    ], "Expected revision history to preserve creation order."

    get_revision_response = client.simulate_get(
        f"/reference-document-revisions/{second_revision_id}"
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
    binding_id = _create_reference_binding(
        client,
        revision_id=second_revision_id,
        template_id=template_id,
    )
    get_binding_response = client.simulate_get(f"/reference-bindings/{binding_id}")
    assert get_binding_response.status_code == 200, (
        f"Unexpected status for GET binding: {get_binding_response.status_code}"
    )

    list_bindings_response = client.simulate_get(
        "/reference-bindings",
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
    response: object,
    *,
    description: str | None = None,
) -> None:
    """Assert Falcon returned the stable HTTP 400 JSON error envelope."""
    http_response = typ.cast("testing.Result", response)
    assert http_response.status_code == 400, (
        f"expected 400 but got {http_response.status_code} for response={http_response}"
    )
    payload = typ.cast("dict[str, object]", http_response.json)
    assert payload["title"] == "400 Bad Request", (
        f"unexpected title in payload: {payload}"
    )
    if description is not None:
        assert payload["description"] == description, (
            f"unexpected description {payload.get('description')!r} "
            f"for expected {description!r} in payload: {payload}"
        )


def _binding_list_params(
    fixture: _ApiFixture,
    **extra_params: str,
) -> dict[str, str]:
    """Build list-binding query params while preserving a valid target."""
    return {
        "target_kind": "episode_template",
        "target_id": fixture.template_id,
        **extra_params,
    }


def _seed_reference_binding(
    client: testing.TestClient,
    fixture: _ApiFixture,
) -> None:
    """Create one document, revision, and binding for negative-path list tests."""
    document_id = _create_reference_document(
        client,
        profile_id=fixture.primary_profile_id,
        kind="host_profile",
        name="Host API Validation",
    )
    revision_id = _create_reference_document_revision(
        client,
        profile_id=fixture.primary_profile_id,
        document_id=document_id,
        revision=_RevisionRequest(
            summary="validation revision",
            content_hash="api-reference-validation-hash",
        ),
    )
    _create_reference_binding(
        client,
        revision_id=revision_id,
        template_id=fixture.template_id,
    )
