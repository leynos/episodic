"""Integration tests for reference-binding brief endpoint filtering."""

import typing as typ
import uuid

import tests.test_binding_resolution_support as binding_support
import tests.test_reference_document_api_support as reference_support

if typ.TYPE_CHECKING:
    import asyncio

    from falcon import testing
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_structured_brief_filters_series_bindings_by_episode(
    canonical_api_client: testing.TestClient,
    _function_scoped_runner: asyncio.Runner,  # noqa: PT019
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Brief endpoint should resolve series bindings when `episode_id` is provided."""
    fixture = binding_support.setup_brief_filter_fixture(
        canonical_api_client, _function_scoped_runner, session_factory
    )
    binding_support.assert_brief_response(
        canonical_api_client,
        binding_support.BriefRequest(
            fixture.profile_id, fixture.template_id, fixture.early_episode_id
        ),
        [fixture.revision_early_id, fixture.template_revision_id],
        "Expected early episode brief to include early series revision plus template.",
    )
    binding_support.assert_brief_response(
        canonical_api_client,
        binding_support.BriefRequest(
            fixture.profile_id, fixture.template_id, fixture.late_episode_id
        ),
        [fixture.revision_late_id, fixture.template_revision_id],
        "Expected late episode brief to include late series revision plus template.",
    )


def test_brief_endpoint_returns_404_for_invalid_episode(
    canonical_api_client: testing.TestClient,
) -> None:
    """Brief endpoint should return 404 when episode_id does not exist."""
    fixture = reference_support.build_api_fixture(canonical_api_client)
    nonexistent_episode_id = str(uuid.uuid4())
    response = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/brief",
        params={"episode_id": nonexistent_episode_id},
    )
    assert response.status_code == 404, "Expected 404 when episode_id does not exist."
