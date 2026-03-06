"""Behavioural tests for reusable reference-document API workflows."""

from __future__ import annotations

import typing as typ

from pytest_bdd import given, scenario, then, when

if typ.TYPE_CHECKING:
    from falcon import testing


class ReferenceDocumentApiContext(typ.TypedDict, total=False):
    """Shared state for reusable reference-document API BDD steps."""

    primary_profile_id: str
    secondary_profile_id: str
    template_id: str
    document_id: str
    first_revision_id: str
    second_revision_id: str
    binding_id: str


@scenario(
    "../features/reference_document_api.feature",
    "Editorial team manages reusable reference documents and bindings",
)
def test_reference_document_api_behaviour() -> None:
    """Run reusable reference-document API scenario."""


def _create_profile(client: testing.TestClient, slug: str) -> str:
    """Create one series profile and return its identifier."""
    response = client.simulate_post(
        "/series-profiles",
        json={
            "slug": slug,
            "title": f"{slug} title",
            "description": f"{slug} description",
            "configuration": {"tone": "clear"},
            "actor": "bdd-reference@example.com",
            "note": "Create profile",
        },
    )
    assert response.status_code == 201
    return typ.cast("str", typ.cast("dict[str, object]", response.json)["id"])


@given("reusable-reference API fixtures exist", target_fixture="context")
def reference_fixtures(
    canonical_api_client: testing.TestClient,
) -> ReferenceDocumentApiContext:
    """Create two profiles and one template for reference-document API scenario."""
    primary_profile_id = _create_profile(canonical_api_client, "bdd-reference-primary")
    secondary_profile_id = _create_profile(
        canonical_api_client,
        "bdd-reference-secondary",
    )
    template_response = canonical_api_client.simulate_post(
        "/episode-templates",
        json={
            "series_profile_id": primary_profile_id,
            "slug": "bdd-reference-template",
            "title": "BDD reference template",
            "description": "BDD template",
            "structure": {"segments": ["intro", "analysis", "outro"]},
            "actor": "bdd-reference@example.com",
            "note": "Create template",
        },
    )
    assert template_response.status_code == 201
    template_id = typ.cast(
        "str", typ.cast("dict[str, object]", template_response.json)["id"]
    )
    return {
        "primary_profile_id": primary_profile_id,
        "secondary_profile_id": secondary_profile_id,
        "template_id": template_id,
    }


@when("a host reference document is created")
def create_host_document(
    canonical_api_client: testing.TestClient,
    context: ReferenceDocumentApiContext,
) -> None:
    """Create one host reference document for the primary profile."""
    response = canonical_api_client.simulate_post(
        f"/series-profiles/{context['primary_profile_id']}/reference-documents",
        json={
            "kind": "host_profile",
            "lifecycle_state": "active",
            "metadata": {"name": "BDD Host"},
        },
    )
    assert response.status_code == 201
    context["document_id"] = typ.cast(
        "str", typ.cast("dict[str, object]", response.json)["id"]
    )


@when("the host reference document is updated with optimistic locking")
def update_host_document(
    canonical_api_client: testing.TestClient,
    context: ReferenceDocumentApiContext,
) -> None:
    """Update the host reference document with lock precondition."""
    response = canonical_api_client.simulate_patch(
        f"/series-profiles/{context['primary_profile_id']}/reference-documents/"
        f"{context['document_id']}",
        json={
            "expected_lock_version": 1,
            "lifecycle_state": "active",
            "metadata": {"name": "BDD Host Updated"},
        },
    )
    assert response.status_code == 200
    assert typ.cast("dict[str, object]", response.json)["lock_version"] == 2


@when("two revisions are added for the host reference document")
def add_revisions(
    canonical_api_client: testing.TestClient,
    context: ReferenceDocumentApiContext,
) -> None:
    """Create two immutable revisions for the host reference document."""
    first = canonical_api_client.simulate_post(
        (
            f"/series-profiles/{context['primary_profile_id']}/reference-documents/"
            f"{context['document_id']}/revisions"
        ),
        json={
            "content": {"summary": "first"},
            "content_hash": "bdd-reference-hash-1",
            "author": "bdd-reference@example.com",
            "change_note": "First",
        },
    )
    assert first.status_code == 201
    context["first_revision_id"] = typ.cast(
        "str", typ.cast("dict[str, object]", first.json)["id"]
    )

    second = canonical_api_client.simulate_post(
        (
            f"/series-profiles/{context['primary_profile_id']}/reference-documents/"
            f"{context['document_id']}/revisions"
        ),
        json={
            "content": {"summary": "second"},
            "content_hash": "bdd-reference-hash-2",
            "author": "bdd-reference@example.com",
            "change_note": "Second",
        },
    )
    assert second.status_code == 201
    context["second_revision_id"] = typ.cast(
        "str", typ.cast("dict[str, object]", second.json)["id"]
    )


@when("the latest revision is bound to the episode template")
def bind_revision(
    canonical_api_client: testing.TestClient,
    context: ReferenceDocumentApiContext,
) -> None:
    """Bind the latest revision to the prepared episode template."""
    response = canonical_api_client.simulate_post(
        "/reference-bindings",
        json={
            "reference_document_revision_id": context["second_revision_id"],
            "target_kind": "episode_template",
            "episode_template_id": context["template_id"],
        },
    )
    assert response.status_code == 201
    context["binding_id"] = typ.cast(
        "str", typ.cast("dict[str, object]", response.json)["id"]
    )


@then("revision history retrieval returns both revisions")
def assert_history(
    canonical_api_client: testing.TestClient,
    context: ReferenceDocumentApiContext,
) -> None:
    """Ensure revision history endpoint returns both revisions in order."""
    response = canonical_api_client.simulate_get(
        (
            f"/series-profiles/{context['primary_profile_id']}/reference-documents/"
            f"{context['document_id']}/revisions"
        ),
        params={"limit": "10", "offset": "0"},
    )
    assert response.status_code == 200
    payload = typ.cast("dict[str, object]", response.json)
    items = typ.cast("list[dict[str, object]]", payload["items"])
    assert [item["id"] for item in items] == [
        context["first_revision_id"],
        context["second_revision_id"],
    ]


@then("stale reference document updates are rejected")
def assert_stale_rejected(
    canonical_api_client: testing.TestClient,
    context: ReferenceDocumentApiContext,
) -> None:
    """Ensure stale optimistic-lock updates return conflict."""
    response = canonical_api_client.simulate_patch(
        (
            f"/series-profiles/{context['primary_profile_id']}/reference-documents/"
            f"{context['document_id']}"
        ),
        json={
            "expected_lock_version": 1,
            "lifecycle_state": "archived",
            "metadata": {"name": "stale"},
        },
    )
    assert response.status_code == 409


@then("host and guest documents are accessed through series-aligned paths")
def assert_series_alignment(
    canonical_api_client: testing.TestClient,
    context: ReferenceDocumentApiContext,
) -> None:
    """Ensure host/guest filtering and cross-series guard behaviour."""
    guest_document_response = canonical_api_client.simulate_post(
        f"/series-profiles/{context['primary_profile_id']}/reference-documents",
        json={
            "kind": "guest_profile",
            "lifecycle_state": "active",
            "metadata": {"name": "BDD Guest"},
        },
    )
    assert guest_document_response.status_code == 201

    host_list = canonical_api_client.simulate_get(
        f"/series-profiles/{context['primary_profile_id']}/reference-documents",
        params={"kind": "host_profile", "limit": "10", "offset": "0"},
    )
    assert host_list.status_code == 200
    host_items = typ.cast(
        "list[dict[str, object]]",
        typ.cast("dict[str, object]", host_list.json)["items"],
    )
    assert len(host_items) == 1

    guest_list = canonical_api_client.simulate_get(
        f"/series-profiles/{context['primary_profile_id']}/reference-documents",
        params={"kind": "guest_profile", "limit": "10", "offset": "0"},
    )
    assert guest_list.status_code == 200
    guest_items = typ.cast(
        "list[dict[str, object]]",
        typ.cast("dict[str, object]", guest_list.json)["items"],
    )
    assert len(guest_items) == 1

    cross_series = canonical_api_client.simulate_get(
        f"/series-profiles/{context['secondary_profile_id']}/reference-documents/"
        f"{context['document_id']}"
    )
    assert cross_series.status_code == 404
