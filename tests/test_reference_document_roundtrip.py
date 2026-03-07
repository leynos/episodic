"""Round-trip API tests for reusable reference-document endpoints."""

import typing as typ

import test_reference_document_api_support as support

if typ.TYPE_CHECKING:
    from falcon import testing


def test_reference_document_round_trip_and_binding_workflow(
    canonical_api_client: testing.TestClient,
) -> None:
    """Reference-document API should support create/get/list/update/revision/binding."""
    fixture = support._build_api_fixture(canonical_api_client)
    document_id = support._create_reference_document(
        canonical_api_client,
        profile_id=fixture.primary_profile_id,
        kind="host_profile",
        name="Host API One",
    )
    list_items = support._assert_reference_document_list(
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
