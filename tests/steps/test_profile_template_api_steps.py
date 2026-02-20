"""Behavioural tests for profile/template API workflows."""

from __future__ import annotations

import typing as typ

import pytest
from pytest_bdd import given, scenario, then, when

if typ.TYPE_CHECKING:
    from falcon import testing


class ProfileTemplateApiContext(typ.TypedDict, total=False):
    """Shared state for profile/template API BDD steps."""

    profile_id: str
    template_id: str
    history_count: int
    brief_profile_id: str
    brief_template_id: str


@scenario(
    "../features/profile_template_api.feature",
    "Editorial team manages profile and template revisions",
)
def test_profile_template_api_behaviour() -> None:
    """Run profile/template API scenario."""


@pytest.fixture
def context() -> ProfileTemplateApiContext:
    """Share state between profile/template API steps."""
    return typ.cast("ProfileTemplateApiContext", {})


@given("the profile/template API is available")
def api_available(context: ProfileTemplateApiContext) -> None:
    """Initialize shared context for API scenario."""
    mutable_context = typ.cast("dict[str, typ.Any]", context)
    mutable_context.clear()


@when("a series profile is created through the API")
def create_profile(
    canonical_api_client: testing.TestClient,
    context: ProfileTemplateApiContext,
) -> None:
    """Create a profile through the API."""
    response = canonical_api_client.simulate_post(
        "/series-profiles",
        json={
            "slug": "bdd-profile",
            "title": "BDD Profile",
            "description": "BDD profile",
            "configuration": {"tone": "clear"},
            "actor": "bdd@example.com",
            "note": "Initial profile",
        },
    )
    assert response.status_code == 201, "Expected profile creation to return 201."
    context["profile_id"] = response.json["id"]


@when("an episode template is created for that profile")
def create_template(
    canonical_api_client: testing.TestClient,
    context: ProfileTemplateApiContext,
) -> None:
    """Create a template through the API."""
    response = canonical_api_client.simulate_post(
        "/episode-templates",
        json={
            "series_profile_id": context["profile_id"],
            "slug": "bdd-template",
            "title": "BDD Template",
            "description": "BDD template",
            "structure": {"segments": ["intro", "topic", "outro"]},
            "actor": "bdd@example.com",
            "note": "Initial template",
        },
    )
    assert response.status_code == 201, "Expected template creation to return 201."
    context["template_id"] = response.json["id"]


@when("the series profile is updated with optimistic locking")
def update_profile(
    canonical_api_client: testing.TestClient,
    context: ProfileTemplateApiContext,
) -> None:
    """Update profile using expected revision."""
    response = canonical_api_client.simulate_patch(
        f"/series-profiles/{context['profile_id']}",
        json={
            "expected_revision": 1,
            "title": "BDD Profile Updated",
            "description": "Updated BDD profile",
            "configuration": {"tone": "assertive"},
            "actor": "bdd-editor@example.com",
            "note": "Update profile",
        },
    )
    assert response.status_code == 200, "Expected profile update to return 200."
    assert response.json["revision"] == 2, "Expected revision increment."


@then("the series profile history contains two revisions")
def assert_history(
    canonical_api_client: testing.TestClient,
    context: ProfileTemplateApiContext,
) -> None:
    """Assert profile history revision count."""
    response = canonical_api_client.simulate_get(
        f"/series-profiles/{context['profile_id']}/history"
    )
    assert response.status_code == 200, (
        "Expected profile history response to return 200."
    )
    context["history_count"] = len(response.json["items"])
    assert context["history_count"] == 2, "Expected exactly two revisions."


@then("a structured brief can be retrieved for downstream generators")
def assert_brief(
    canonical_api_client: testing.TestClient,
    context: ProfileTemplateApiContext,
) -> None:
    """Assert structured brief retrieval."""
    response = canonical_api_client.simulate_get(
        f"/series-profiles/{context['profile_id']}/brief",
        params={"template_id": context["template_id"]},
    )
    assert response.status_code == 200, (
        "Expected structured brief response to return 200."
    )
    payload = response.json
    context["brief_profile_id"] = payload["series_profile"]["id"]
    context["brief_template_id"] = payload["episode_templates"][0]["id"]
    assert context["brief_profile_id"] == context["profile_id"], (
        "Expected brief to include selected profile."
    )
    assert context["brief_template_id"] == context["template_id"], (
        "Expected brief to include selected template."
    )
