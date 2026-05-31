"""Integration tests for reference-binding resolution API flows."""

import datetime as dt
import typing as typ
import uuid

import pytest

import tests.test_binding_resolution_support as binding_support
import tests.test_reference_document_api_support as reference_support

if typ.TYPE_CHECKING:
    import asyncio

    from falcon import testing
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _create_series_profile_binding(
    client: testing.TestClient,
    profile_id: str,
    episode_id: str,
) -> str:
    """Create a style-guide document, one revision, and a series-profile binding.

    Returns the revision ID.
    """
    _, revision_id = binding_support.create_document_with_revision(
        client,
        profile_id,
        binding_support.DocumentSpec(
            kind="style_guide",
            name="Resolved series guide",
            summary="Resolved series guide",
            content_hash="resolved-bindings-series",
        ),
    )
    binding_support.create_series_binding(
        client,
        revision_id=revision_id,
        profile_id=profile_id,
        effective_from_episode_id=episode_id,
    )
    return revision_id


def _create_episode_template_binding(
    client: testing.TestClient,
    profile_id: str,
    template_id: str,
) -> str:
    """Create a guest-profile document, one revision, and an episode-template binding.

    Returns the revision ID.
    """
    _, revision_id = binding_support.create_document_with_revision(
        client,
        profile_id,
        binding_support.DocumentSpec(
            kind="guest_profile",
            name="Resolved template guest",
            summary="Resolved template guest",
            content_hash="resolved-bindings-template",
        ),
    )
    reference_support.create_reference_binding(
        client,
        revision_id=revision_id,
        template_id=template_id,
    )
    return revision_id


def _assert_resolved_bindings_payload(
    payload: dict[str, object],
    series_revision_id: str,
    template_revision_id: str,
) -> None:
    """Assert the pagination envelope and items of a resolved-bindings response."""
    assert payload["limit"] == 20, (
        f"expected limit == 20, got {payload['limit']!r}; payload={payload}"
    )
    assert payload["offset"] == 0, (
        f"expected offset == 0, got {payload['offset']!r}; payload={payload}"
    )
    assert payload["total"] == 2, (
        f"expected total == 2 (series + template binding), "
        f"got {payload['total']!r}; payload={payload}"
    )
    items = typ.cast("list[dict[str, object]]", payload["items"])
    revisions = [typ.cast("dict[str, object]", item["revision"]) for item in items]
    documents = [typ.cast("dict[str, object]", item["document"]) for item in items]
    assert [revision["id"] for revision in revisions] == [
        series_revision_id,
        template_revision_id,
    ], "Expected resolved-bindings endpoint to return both resolved revisions."
    assert documents[0]["kind"] == "style_guide", (
        f"expected first resolved document kind == 'style_guide', "
        f"got {documents[0]['kind']!r}"
    )
    assert documents[1]["kind"] == "guest_profile", (
        f"expected second resolved document kind == 'guest_profile', "
        f"got {documents[1]['kind']!r}"
    )


def test_resolved_bindings_endpoint_returns_resolved_payloads(
    canonical_api_client: testing.TestClient,
    _function_scoped_runner: asyncio.Runner,  # noqa: PT019
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Resolved-bindings endpoint should return document, revision, and binding data."""
    fixture = reference_support.build_api_fixture(canonical_api_client)

    episode_id = _function_scoped_runner.run(
        binding_support.create_episode(
            session_factory,
            profile_id=fixture.primary_profile_id,
            title="Resolution target episode",
            created_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
        )
    )

    series_revision_id = _create_series_profile_binding(
        canonical_api_client, fixture.primary_profile_id, episode_id
    )
    template_revision_id = _create_episode_template_binding(
        canonical_api_client, fixture.primary_profile_id, fixture.template_id
    )

    response = canonical_api_client.simulate_get(
        f"/v1/series-profiles/{fixture.primary_profile_id}/resolved-bindings",
        params={"episode_id": episode_id, "template_id": fixture.template_id},
    )

    assert response.status_code == 200, (
        "Expected resolved-bindings endpoint to return 200."
    )
    _assert_resolved_bindings_payload(
        typ.cast("dict[str, object]", response.json),
        series_revision_id,
        template_revision_id,
    )


@pytest.mark.parametrize(
    ("params", "expected_description"),
    [
        (
            {},
            "Missing required query parameter: episode_id",
        ),
        (
            {"episode_id": "not-a-valid-uuid"},
            "Invalid UUID for episode_id: 'not-a-valid-uuid'.",
        ),
    ],
    ids=["missing_episode_id", "invalid_episode_id"],
)
def test_resolved_bindings_endpoint_rejects_bad_episode_id(
    canonical_api_client: testing.TestClient,
    params: dict[str, str],
    expected_description: str,
) -> None:
    """Resolved-bindings endpoint should reject malformed or absent episode_id."""
    fixture = reference_support.build_api_fixture(canonical_api_client)
    response = canonical_api_client.simulate_get(
        f"/v1/series-profiles/{fixture.primary_profile_id}/resolved-bindings",
        params=params,
    )
    assert response.status_code == 400, (
        f"expected HTTP 400 for params={params}, got {response.status_code}"
    )
    payload = typ.cast("dict[str, object]", response.json)
    assert payload["code"] == "validation_error", (
        f"expected code 'validation_error', got {payload.get('code')!r}; "
        f"payload={payload}"
    )
    assert payload["message"] == expected_description, (
        f"expected message {expected_description!r}, got {payload.get('message')!r}"
    )


def test_resolved_bindings_endpoint_returns_404_for_unknown_profile(
    canonical_api_client: testing.TestClient,
) -> None:
    """Resolved-bindings endpoint should return 404 for a nonexistent profile."""
    unknown_profile_id = str(uuid.uuid4())
    episode_id = str(uuid.uuid4())
    response = canonical_api_client.simulate_get(
        f"/v1/series-profiles/{unknown_profile_id}/resolved-bindings",
        params={"episode_id": episode_id},
    )
    assert response.status_code == 404, "Expected 404 for unknown series profile."


@pytest.mark.parametrize(
    "endpoint",
    ["resolved-bindings", "brief"],
    ids=["resolved_bindings", "brief"],
)
def test_endpoint_returns_404_for_episode_not_in_profile(
    canonical_api_client: testing.TestClient,
    _function_scoped_runner: asyncio.Runner,  # noqa: PT019
    session_factory: async_sessionmaker[AsyncSession],
    endpoint: str,
) -> None:
    """Both endpoints return 404 when episode_id belongs to a different profile."""
    fixture = reference_support.build_api_fixture(canonical_api_client)
    episode_id = _function_scoped_runner.run(
        binding_support.create_episode(
            session_factory,
            profile_id=fixture.secondary_profile_id,
            title="Wrong-profile episode",
            created_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
        )
    )
    response = canonical_api_client.simulate_get(
        f"/v1/series-profiles/{fixture.primary_profile_id}/{endpoint}",
        params={"episode_id": episode_id},
    )
    assert response.status_code == 404, (
        "Expected 404 when episode does not belong to the requested profile."
    )


@pytest.mark.parametrize(
    "use_secondary_template",
    [False, True],
    ids=["unknown_template", "cross_profile_template"],
)
def test_resolved_bindings_endpoint_returns_404_for_invalid_template(
    canonical_api_client: testing.TestClient,
    _function_scoped_runner: asyncio.Runner,  # noqa: PT019
    session_factory: async_sessionmaker[AsyncSession],
    use_secondary_template: object,
) -> None:
    """Resolved-bindings endpoint returns 404 for missing or cross-profile templates."""
    fixture = reference_support.build_api_fixture(canonical_api_client)
    episode_id = _function_scoped_runner.run(
        binding_support.create_episode(
            session_factory,
            profile_id=fixture.primary_profile_id,
            title="Test episode",
            created_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
        )
    )
    template_id = (
        fixture.secondary_template_id
        if typ.cast("bool", use_secondary_template)
        else str(uuid.uuid4())
    )
    response = canonical_api_client.simulate_get(
        f"/v1/series-profiles/{fixture.primary_profile_id}/resolved-bindings",
        params={"episode_id": episode_id, "template_id": template_id},
    )
    assert response.status_code == 404, (
        "Expected 404 for template not owned by the requested profile."
    )
