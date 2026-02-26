"""Integration tests for profile/template REST endpoints."""

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    from falcon import testing


@dc.dataclass(frozen=True, slots=True)
class EntityUpdateSpec:
    """Specification for updating an entity via PATCH."""

    endpoint_path: str
    payload: dict[str, typ.Any]
    entity_label: str


def _create_profile(
    client: testing.TestClient,
    *,
    slug: str = "api-profile",
) -> tuple[str, dict[str, typ.Any]]:
    """Create a series profile and return its identifier and payload."""
    create_profile_response = client.simulate_post(
        "/series-profiles",
        json={
            "slug": slug,
            "title": "API Profile",
            "description": "Created through API",
            "configuration": {"tone": "precise"},
            "actor": "api-user@example.com",
            "note": "Initial profile",
        },
    )
    assert create_profile_response.status_code == 201, (
        "Expected profile creation to return 201."
    )
    profile_payload = create_profile_response.json
    profile_id = profile_payload["id"]
    assert profile_payload["revision"] == 1, "Expected revision 1 on create."
    return profile_id, profile_payload


def _create_template(
    client: testing.TestClient,
    profile_id: str,
) -> tuple[str, dict[str, typ.Any]]:
    """Create an episode template and return its identifier and payload."""
    create_template_response = client.simulate_post(
        "/episode-templates",
        json={
            "series_profile_id": profile_id,
            "slug": "api-template",
            "title": "API Template",
            "description": "Template through API",
            "structure": {"segments": ["intro", "main", "outro"]},
            "actor": "api-user@example.com",
            "note": "Initial template",
        },
    )
    assert create_template_response.status_code == 201, (
        "Expected template creation to return 201."
    )
    template_payload = create_template_response.json
    template_id = template_payload["id"]
    assert template_payload["revision"] == 1, "Expected template revision 1."
    return template_id, template_payload


def _update_entity_and_verify_revision(
    client: testing.TestClient,
    spec: EntityUpdateSpec,
) -> None:
    """Update an entity and verify optimistic-lock revision increment."""
    update_response = client.simulate_patch(
        spec.endpoint_path,
        json=spec.payload,
    )
    assert update_response.status_code == 200, (
        f"Expected {spec.entity_label} update to return 200."
    )
    assert update_response.json["revision"] == 2, (
        f"Expected {spec.entity_label} revision to increment on update."
    )


def _verify_stale_update_rejected_generic(
    client: testing.TestClient,
    spec: EntityUpdateSpec,
) -> None:
    """Verify stale updates are rejected by optimistic locking."""
    stale_update_response = client.simulate_patch(
        spec.endpoint_path,
        json=spec.payload,
    )
    assert stale_update_response.status_code == 409, (
        f"Expected stale {spec.entity_label} update to return 409."
    )
    assert isinstance(stale_update_response.json, dict), (
        f"Expected stale {spec.entity_label} error as a JSON object."
    )


def _verify_entity_history(
    client: testing.TestClient,
    history_path: str,
    entity_label: str,
) -> None:
    """Verify entity history includes both create and update revisions."""
    history_response = client.simulate_get(history_path)
    assert history_response.status_code == 200, (
        f"Expected {entity_label} history endpoint to return 200."
    )

    history_payload = history_response.json
    items = (
        history_payload["items"]
        if isinstance(history_payload, dict)
        else history_payload
    )
    assert isinstance(items, list), (
        f"Expected {entity_label} history response to be a JSON list."
    )
    assert len(items) == 2, f"Expected two {entity_label} history revisions."


def _update_profile(client: testing.TestClient, profile_id: str) -> None:
    """Update a profile and verify revision increment."""
    _update_entity_and_verify_revision(
        client,
        EntityUpdateSpec(
            endpoint_path=f"/series-profiles/{profile_id}",
            payload={
                "expected_revision": 1,
                "title": "API Profile Updated",
                "description": "Updated through API",
                "configuration": {"tone": "decisive"},
                "actor": "editor@example.com",
                "note": "Profile update",
            },
            entity_label="profile",
        ),
    )


def _update_template(client: testing.TestClient, template_id: str) -> None:
    """Update a template and verify revision increment."""
    _update_entity_and_verify_revision(
        client,
        EntityUpdateSpec(
            endpoint_path=f"/episode-templates/{template_id}",
            payload={
                "expected_revision": 1,
                "title": "API Template Updated",
                "description": "Updated template through API",
                "structure": {"segments": ["intro", "deep-dive", "outro"]},
                "actor": "editor@example.com",
                "note": "Template update",
            },
            entity_label="episode-template",
        ),
    )


def _verify_stale_update_rejected(
    client: testing.TestClient,
    profile_id: str,
) -> None:
    """Verify stale profile updates are rejected by optimistic locking."""
    _verify_stale_update_rejected_generic(
        client,
        EntityUpdateSpec(
            endpoint_path=f"/series-profiles/{profile_id}",
            payload={
                "expected_revision": 1,
                "title": "Stale update",
                "description": "Should fail",
                "configuration": {"tone": "stale"},
                "actor": "editor@example.com",
                "note": "Stale attempt",
            },
            entity_label="profile",
        ),
    )


def _verify_episode_template_stale_update_rejected(
    client: testing.TestClient,
    template_id: str,
) -> None:
    """Verify stale template updates are rejected by optimistic locking."""
    _verify_stale_update_rejected_generic(
        client,
        EntityUpdateSpec(
            endpoint_path=f"/episode-templates/{template_id}",
            payload={
                "expected_revision": 1,
                "title": "Stale template update",
                "description": "Should fail",
                "structure": {"segments": ["stale"]},
                "actor": "editor@example.com",
                "note": "Stale attempt",
            },
            entity_label="episode-template",
        ),
    )


def _verify_profile_history(client: testing.TestClient, profile_id: str) -> None:
    """Verify profile history includes both create and update revisions."""
    _verify_entity_history(
        client,
        f"/series-profiles/{profile_id}/history",
        "profile",
    )


def _verify_episode_template_history(
    client: testing.TestClient,
    template_id: str,
) -> None:
    """Verify template history includes both create and update revisions."""
    _verify_entity_history(
        client,
        f"/episode-templates/{template_id}/history",
        "episode-template",
    )


def _verify_structured_brief(
    client: testing.TestClient,
    profile_id: str,
    template_id: str,
) -> None:
    """Verify structured brief returns the expected profile and template."""
    brief_response = client.simulate_get(
        f"/series-profiles/{profile_id}/brief",
        params={"template_id": template_id},
    )
    assert brief_response.status_code == 200, (
        "Expected structured brief endpoint to return 200."
    )
    assert brief_response.json["series_profile"]["id"] == profile_id, (
        "Expected structured brief to include profile."
    )
    assert brief_response.json["episode_templates"][0]["id"] == template_id, (
        "Expected structured brief to include template."
    )


def test_profile_and_template_api_round_trip(
    canonical_api_client: testing.TestClient,
) -> None:
    """Create, update, and retrieve profile/template resources."""
    profile_id, _ = _create_profile(canonical_api_client)
    template_id, _ = _create_template(canonical_api_client, profile_id)
    _update_profile(canonical_api_client, profile_id)
    _update_template(canonical_api_client, template_id)
    _verify_stale_update_rejected(canonical_api_client, profile_id)
    _verify_episode_template_stale_update_rejected(canonical_api_client, template_id)
    _verify_profile_history(canonical_api_client, profile_id)
    _verify_episode_template_history(canonical_api_client, template_id)
    _verify_structured_brief(canonical_api_client, profile_id, template_id)


def test_get_structured_brief_template_not_in_profile(
    canonical_api_client: testing.TestClient,
) -> None:
    """Return 404 when template does not belong to the series profile."""
    profile_id_1, _ = _create_profile(canonical_api_client)
    template_id, _ = _create_template(canonical_api_client, profile_id_1)
    profile_id_2, _ = _create_profile(
        canonical_api_client,
        slug="api-profile-two",
    )

    response = canonical_api_client.simulate_get(
        f"/series-profiles/{profile_id_2}/brief",
        params={"template_id": template_id},
    )

    assert response.status_code == 404, (
        "Expected 404 when template does not belong to profile."
    )


def test_update_rejects_non_integer_expected_revision(
    canonical_api_client: testing.TestClient,
) -> None:
    """Return 400 when expected_revision is not an integer."""
    profile_id, _ = _create_profile(canonical_api_client)
    template_id, _ = _create_template(canonical_api_client, profile_id)

    profile_response = canonical_api_client.simulate_patch(
        f"/series-profiles/{profile_id}",
        json={
            "expected_revision": "not-an-int",
            "title": "Invalid profile update",
            "description": "Should fail",
            "configuration": {"tone": "invalid"},
        },
    )
    assert profile_response.status_code == 400, (
        "Expected profile update with non-integer revision to return 400."
    )

    template_response = canonical_api_client.simulate_patch(
        f"/episode-templates/{template_id}",
        json={
            "expected_revision": "not-an-int",
            "title": "Invalid template update",
            "description": "Should fail",
            "structure": {"segments": ["invalid"]},
        },
    )
    assert template_response.status_code == 400, (
        "Expected template update with non-integer revision to return 400."
    )


def test_update_rejects_missing_expected_revision(
    canonical_api_client: testing.TestClient,
) -> None:
    """Return 400 when expected_revision is missing."""
    profile_id, _ = _create_profile(canonical_api_client)
    template_id, _ = _create_template(canonical_api_client, profile_id)

    profile_response = canonical_api_client.simulate_patch(
        f"/series-profiles/{profile_id}",
        json={
            "title": "Invalid profile update",
            "description": "Should fail",
            "configuration": {"tone": "invalid"},
        },
    )
    assert profile_response.status_code == 400, (
        "Expected profile update without expected_revision to return 400."
    )

    template_response = canonical_api_client.simulate_patch(
        f"/episode-templates/{template_id}",
        json={
            "title": "Invalid template update",
            "description": "Should fail",
            "structure": {"segments": ["invalid"]},
        },
    )
    assert template_response.status_code == 400, (
        "Expected template update without expected_revision to return 400."
    )
