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


def test_reference_document_lists_report_total_across_pages(
    canonical_api_client: testing.TestClient,
) -> None:
    """Reference-document list envelopes should report unpaginated totals."""
    fixture = support.build_api_fixture(canonical_api_client)
    document_ids = [
        support.create_reference_document(
            canonical_api_client,
            profile_id=fixture.primary_profile_id,
            kind="host_profile",
            name=f"Host API Page {index}",
        )
        for index in range(3)
    ]

    first_page_response = canonical_api_client.simulate_get(
        f"/v1/series-profiles/{fixture.primary_profile_id}/reference-documents",
        params={"limit": "2", "offset": "0"},
    )
    assert first_page_response.status_code == 200
    first_page = typ.cast("dict[str, object]", first_page_response.json)
    assert len(typ.cast("list[object]", first_page["items"])) == 2
    assert first_page["total"] == 3

    revision_ids = [
        support.create_reference_document_revision(
            canonical_api_client,
            profile_id=fixture.primary_profile_id,
            document_id=document_ids[0],
            revision=support.RevisionRequest(
                summary=f"revision {index}",
                content_hash=f"api-reference-page-hash-{index}",
            ),
        )
        for index in range(2)
    ]

    revision_page_response = canonical_api_client.simulate_get(
        f"/v1/series-profiles/{fixture.primary_profile_id}/reference-documents/"
        f"{document_ids[0]}/revisions",
        params={"limit": "1", "offset": "0"},
    )
    assert revision_page_response.status_code == 200
    revision_page = typ.cast("dict[str, object]", revision_page_response.json)
    assert len(typ.cast("list[object]", revision_page["items"])) == 1
    assert revision_page["total"] == 2

    for revision_id in revision_ids:
        support.create_reference_binding(
            canonical_api_client,
            revision_id=revision_id,
            template_id=fixture.template_id,
        )

    binding_page_response = canonical_api_client.simulate_get(
        "/v1/reference-bindings",
        params={
            "target_kind": "episode_template",
            "target_id": fixture.template_id,
            "limit": "1",
            "offset": "0",
        },
    )
    assert binding_page_response.status_code == 200
    binding_page = typ.cast("dict[str, object]", binding_page_response.json)
    assert len(typ.cast("list[object]", binding_page["items"])) == 1
    assert binding_page["total"] == 2
