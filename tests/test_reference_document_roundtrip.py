"""Round-trip API tests for reusable reference-document endpoints."""

import typing as typ

import tests.test_reference_document_api_support as support

if typ.TYPE_CHECKING:
    from falcon import testing


def test_reference_document_round_trip_and_binding_workflow(
    canonical_api_client: testing.TestClient,
) -> None:
    """Reference-document API should support create/get/list/update/revision/binding."""
    fixture = support.build_api_fixture(canonical_api_client)
    document_id = support.create_reference_document(
        canonical_api_client,
        profile_id=fixture.primary_profile_id,
        kind="host_profile",
        name="Host API One",
    )
    list_items = support.assert_reference_document_list(
        canonical_api_client,
        profile_id=fixture.primary_profile_id,
    )
    assert len(list_items) == 1, "Expected one reference document in list response."

    support._assert_document_get_and_optimistic_lock(
        canonical_api_client,
        profile_id=fixture.primary_profile_id,
        document_id=document_id,
    )
    support._assert_revision_and_binding_workflow(
        canonical_api_client,
        profile_id=fixture.primary_profile_id,
        document_id=document_id,
        template_id=fixture.template_id,
    )


def _assert_document_page_total(
    client: testing.TestClient,
    profile_id: str,
) -> list[str]:
    """Create three documents and assert the first reference-document page total."""
    document_ids = [
        support.create_reference_document(
            client,
            profile_id=profile_id,
            kind="host_profile",
            name=f"Host API Page {index}",
        )
        for index in range(3)
    ]
    response = client.simulate_get(
        f"/v1/series-profiles/{profile_id}/reference-documents",
        params={"limit": "2", "offset": "0"},
    )
    assert response.status_code == 200, (
        f"expected 200 for first reference-document page, got {response.status_code}"
    )
    page = typ.cast("dict[str, object]", response.json)
    assert len(typ.cast("list[object]", page["items"])) == 2, (
        f"expected 2 items on the first reference-document page; payload={page}"
    )
    assert page["total"] == 3, (
        f"expected total 3 reference documents, got {page['total']!r}; payload={page}"
    )
    return document_ids


def _assert_revision_page_total(
    client: testing.TestClient,
    profile_id: str,
    document_id: str,
) -> list[str]:
    """Create two revisions and assert the first reference-revision page total."""
    revision_ids = [
        support.create_reference_document_revision(
            client,
            profile_id=profile_id,
            document_id=document_id,
            revision=support.RevisionRequest(
                summary=f"revision {index}",
                content_hash=f"api-reference-page-hash-{index}",
            ),
        )
        for index in range(2)
    ]
    response = client.simulate_get(
        f"/v1/series-profiles/{profile_id}/reference-documents/{document_id}/revisions",
        params={"limit": "1", "offset": "0"},
    )
    assert response.status_code == 200, (
        f"expected 200 for reference-revision page, got {response.status_code}"
    )
    page = typ.cast("dict[str, object]", response.json)
    assert len(typ.cast("list[object]", page["items"])) == 1, (
        f"expected 1 item on the first reference-revision page; payload={page}"
    )
    assert page["total"] == 2, (
        f"expected total 2 reference revisions, got {page['total']!r}; payload={page}"
    )
    return revision_ids


def _assert_binding_page_total(
    client: testing.TestClient,
    revision_ids: list[str],
    template_id: str,
) -> None:
    """Bind each revision and assert the first reference-binding page total."""
    for revision_id in revision_ids:
        support.create_reference_binding(
            client,
            revision_id=revision_id,
            template_id=template_id,
        )
    response = client.simulate_get(
        "/v1/reference-bindings",
        params={
            "target_kind": "episode_template",
            "target_id": template_id,
            "limit": "1",
            "offset": "0",
        },
    )
    assert response.status_code == 200, (
        f"expected 200 for reference-binding page, got {response.status_code}"
    )
    page = typ.cast("dict[str, object]", response.json)
    assert len(typ.cast("list[object]", page["items"])) == 1, (
        f"expected 1 item on the first reference-binding page; payload={page}"
    )
    assert page["total"] == 2, (
        f"expected total 2 reference bindings, got {page['total']!r}; payload={page}"
    )


def test_reference_document_lists_report_total_across_pages(
    canonical_api_client: testing.TestClient,
) -> None:
    """Reference-document list envelopes should report unpaginated totals."""
    fixture = support.build_api_fixture(canonical_api_client)
    document_ids = _assert_document_page_total(
        canonical_api_client, fixture.primary_profile_id
    )
    revision_ids = _assert_revision_page_total(
        canonical_api_client, fixture.primary_profile_id, document_ids[0]
    )
    _assert_binding_page_total(canonical_api_client, revision_ids, fixture.template_id)
