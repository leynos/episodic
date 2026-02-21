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


def _make_request_and_assert_status(
    client: testing.TestClient,
    method: str,
    path: str,
    expected_status: int,
    *,
    json: dict[str, typ.Any] | None = None,
    params: dict[str, typ.Any] | None = None,
) -> dict[str, typ.Any]:
    """Send a request, assert status, and return the JSON payload."""
    method_upper = method.upper()
    if method_upper == "POST":
        response = client.simulate_post(path, json=json, params=params)
    elif method_upper == "PATCH":
        response = client.simulate_patch(path, json=json, params=params)
    elif method_upper == "GET":
        response = client.simulate_get(path, params=params)
    else:
        msg = f"Unsupported HTTP method: {method}"
        raise ValueError(msg)

    assert response.status_code == expected_status
    return typ.cast("dict[str, typ.Any]", response.json)


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
    payload = _make_request_and_assert_status(
        canonical_api_client,
        "POST",
        "/series-profiles",
        201,
        json={
            "slug": "bdd-profile",
            "title": "BDD Profile",
            "description": "BDD profile",
            "configuration": {"tone": "clear"},
            "actor": "bdd@example.com",
            "note": "Initial profile",
        },
    )
    context["profile_id"] = typ.cast("str", payload["id"])


@when("an episode template is created for that profile")
def create_template(
    canonical_api_client: testing.TestClient,
    context: ProfileTemplateApiContext,
) -> None:
    """Create a template through the API."""
    payload = _make_request_and_assert_status(
        canonical_api_client,
        "POST",
        "/episode-templates",
        201,
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
    context["template_id"] = typ.cast("str", payload["id"])


@when("the series profile is updated with optimistic locking")
def update_profile(
    canonical_api_client: testing.TestClient,
    context: ProfileTemplateApiContext,
) -> None:
    """Update profile using expected revision."""
    payload = _make_request_and_assert_status(
        canonical_api_client,
        "PATCH",
        f"/series-profiles/{context['profile_id']}",
        200,
        json={
            "expected_revision": 1,
            "title": "BDD Profile Updated",
            "description": "Updated BDD profile",
            "configuration": {"tone": "assertive"},
            "actor": "bdd-editor@example.com",
            "note": "Update profile",
        },
    )
    assert payload["revision"] == 2, "Expected revision increment."


@then("the series profile history contains two revisions")
def assert_history(
    canonical_api_client: testing.TestClient,
    context: ProfileTemplateApiContext,
) -> None:
    """Assert profile history revision count."""
    payload = _make_request_and_assert_status(
        canonical_api_client,
        "GET",
        f"/series-profiles/{context['profile_id']}/history",
        200,
    )
    context["history_count"] = len(typ.cast("list[object]", payload["items"]))
    assert context["history_count"] == 2, "Expected exactly two revisions."


@then("a structured brief can be retrieved for downstream generators")
def assert_brief(
    canonical_api_client: testing.TestClient,
    context: ProfileTemplateApiContext,
) -> None:
    """Assert structured brief retrieval."""
    payload = _make_request_and_assert_status(
        canonical_api_client,
        "GET",
        f"/series-profiles/{context['profile_id']}/brief",
        200,
        params={"template_id": context["template_id"]},
    )
    series_profile = typ.cast("dict[str, typ.Any]", payload["series_profile"])
    episode_templates = typ.cast(
        "list[dict[str, typ.Any]]", payload["episode_templates"]
    )
    context["brief_profile_id"] = typ.cast("str", series_profile["id"])
    context["brief_template_id"] = typ.cast("str", episode_templates[0]["id"])
    assert context["brief_profile_id"] == context["profile_id"], (
        "Expected brief to include selected profile."
    )
    assert context["brief_template_id"] == context["template_id"], (
        "Expected brief to include selected template."
    )
