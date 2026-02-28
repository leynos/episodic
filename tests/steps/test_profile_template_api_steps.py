"""Behavioural tests for profile/template API workflows."""

from __future__ import annotations

import dataclasses as dc
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


@dc.dataclass(frozen=True, slots=True)
class HttpRequest:
    """HTTP request specification for testing."""

    method: str
    path: str
    json: dict[str, typ.Any] | None = None
    params: dict[str, typ.Any] | None = None


@dc.dataclass(frozen=True, slots=True)
class EntityCreationSpec:
    """Specification for creating an entity and storing its ID."""

    path: str
    payload: dict[str, typ.Any]
    context_key: str


def _make_request_and_assert_status(
    client: testing.TestClient,
    request: HttpRequest,
    expected_status: int,
) -> dict[str, typ.Any]:
    """Send a request, assert status, and return the JSON payload."""
    method_upper = request.method.upper()
    if method_upper == "POST":
        response = client.simulate_post(
            request.path,
            json=request.json,
            params=request.params,
        )
    elif method_upper == "PATCH":
        response = client.simulate_patch(
            request.path,
            json=request.json,
            params=request.params,
        )
    elif method_upper == "GET":
        response = client.simulate_get(request.path, params=request.params)
    else:
        msg = f"Unsupported HTTP method: {request.method}"
        raise ValueError(msg)

    assert response.status_code == expected_status
    return typ.cast("dict[str, typ.Any]", response.json)


def _create_entity_and_store_id(
    client: testing.TestClient,
    spec: EntityCreationSpec,
    context: ProfileTemplateApiContext,
) -> None:
    """Create an entity via POST and store its ID in context."""
    response_payload = _make_request_and_assert_status(
        client,
        HttpRequest(method="POST", path=spec.path, json=spec.payload),
        201,
    )
    mutable_context = typ.cast("dict[str, typ.Any]", context)
    mutable_context[spec.context_key] = typ.cast("str", response_payload["id"])


def _update_entity_and_assert_revision(
    client: testing.TestClient,
    path: str,
    payload: dict[str, typ.Any],
    expected_revision: int,
) -> None:
    """Update an entity via PATCH and assert the resulting revision."""
    response_payload = _make_request_and_assert_status(
        client,
        HttpRequest(method="PATCH", path=path, json=payload),
        200,
    )
    assert response_payload["revision"] == expected_revision


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
    _create_entity_and_store_id(
        canonical_api_client,
        EntityCreationSpec(
            path="/series-profiles",
            payload={
                "slug": "bdd-profile",
                "title": "BDD Profile",
                "description": "BDD profile",
                "configuration": {"tone": "clear"},
                "actor": "bdd@example.com",
                "note": "Initial profile",
            },
            context_key="profile_id",
        ),
        context,
    )


@when("an episode template is created for that profile")
def create_template(
    canonical_api_client: testing.TestClient,
    context: ProfileTemplateApiContext,
) -> None:
    """Create a template through the API."""
    _create_entity_and_store_id(
        canonical_api_client,
        EntityCreationSpec(
            path="/episode-templates",
            payload={
                "series_profile_id": context["profile_id"],
                "slug": "bdd-template",
                "title": "BDD Template",
                "description": "BDD template",
                "structure": {"segments": ["intro", "topic", "outro"]},
                "actor": "bdd@example.com",
                "note": "Initial template",
            },
            context_key="template_id",
        ),
        context,
    )


@when("the series profile is updated with optimistic locking")
def update_profile(
    canonical_api_client: testing.TestClient,
    context: ProfileTemplateApiContext,
) -> None:
    """Update profile using expected revision."""
    _update_entity_and_assert_revision(
        canonical_api_client,
        f"/series-profiles/{context['profile_id']}",
        {
            "expected_revision": 1,
            "title": "BDD Profile Updated",
            "description": "Updated BDD profile",
            "configuration": {"tone": "assertive"},
            "actor": "bdd-editor@example.com",
            "note": "Update profile",
        },
        2,
    )


@then("the series profile history contains two revisions")
def assert_history(
    canonical_api_client: testing.TestClient,
    context: ProfileTemplateApiContext,
) -> None:
    """Assert profile history revision count."""
    payload = _make_request_and_assert_status(
        canonical_api_client,
        HttpRequest(
            method="GET",
            path=f"/series-profiles/{context['profile_id']}/history",
        ),
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
        HttpRequest(
            method="GET",
            path=f"/series-profiles/{context['profile_id']}/brief",
            params={"template_id": context["template_id"]},
        ),
        200,
    )
    series_profile = typ.cast("dict[str, typ.Any]", payload["series_profile"])
    episode_templates = typ.cast(
        "list[dict[str, typ.Any]]", payload["episode_templates"]
    )
    reference_documents = typ.cast(
        "list[dict[str, typ.Any]]", payload["reference_documents"]
    )
    context["brief_profile_id"] = typ.cast("str", series_profile["id"])
    context["brief_template_id"] = typ.cast("str", episode_templates[0]["id"])
    assert context["brief_profile_id"] == context["profile_id"], (
        "Expected brief to include selected profile."
    )
    assert context["brief_template_id"] == context["template_id"], (
        "Expected brief to include selected template."
    )
    assert reference_documents == [], (
        "Expected empty reference_documents list without configured bindings."
    )
