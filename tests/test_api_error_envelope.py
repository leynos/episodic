"""Integration coverage for the canonical REST error envelope."""

import typing as typ

if typ.TYPE_CHECKING:
    from falcon import testing


# pylint: disable-next=too-many-arguments  # Test helper keeps assertions explicit at call sites.
def _assert_error_envelope(
    response: testing.Result,
    *,
    status_code: int,
    code: str,
    field: str | None = None,
    constraint: str | None = None,
) -> dict[str, object]:
    """Assert the common API error envelope and return its payload."""
    assert response.status_code == status_code, (
        f"expected status {status_code}, got {response.status_code}"
    )
    payload = typ.cast("dict[str, object]", response.json)
    expected_keys = {"code", "message", "details"}
    assert set(payload) == expected_keys, (
        f"expected envelope keys {expected_keys}, got {set(payload)}"
    )
    assert payload["code"] == code, (
        f"expected error code {code!r}, got {payload['code']!r}"
    )
    assert isinstance(payload["message"], str), (
        f"expected string message, got {type(payload['message']).__name__}"
    )
    details = typ.cast("dict[str, object]", payload["details"])
    if field is not None:
        assert details["field"] == field, (
            f"expected details field {field!r}, got {details.get('field')!r}"
        )
    if constraint is not None:
        assert details["constraint"] == constraint, (
            "expected details constraint "
            f"{constraint!r}, got {details.get('constraint')!r}"
        )
    return payload


def test_invalid_uuid_returns_validation_envelope(
    canonical_api_client: testing.TestClient,
) -> None:
    """Invalid path identifiers return a field-specific validation error."""
    response = canonical_api_client.simulate_get("/v1/series-profiles/not-a-valid-uuid")

    _assert_error_envelope(
        response,
        status_code=400,
        code="validation_error",
        field="profile_id",
        constraint="uuid",
    )


def test_invalid_pagination_returns_validation_envelope(
    canonical_api_client: testing.TestClient,
) -> None:
    """Invalid pagination bounds return range details."""
    response = canonical_api_client.simulate_get(
        "/v1/reference-bindings",
        params={
            "target_kind": "episode_template",
            "target_id": "irrelevant",
            "limit": "0",
        },
    )

    _assert_error_envelope(
        response,
        status_code=400,
        code="validation_error",
        field="limit",
        constraint="range",
    )


def test_missing_query_parameter_returns_validation_envelope(
    canonical_api_client: testing.TestClient,
) -> None:
    """Missing required query parameters return required-field details."""
    response = canonical_api_client.simulate_get(
        "/v1/series-profiles/018f0c2a-1234-7000-a000-000000000001/resolved-bindings"
    )

    _assert_error_envelope(
        response,
        status_code=400,
        code="validation_error",
        field="episode_id",
        constraint="required",
    )


def test_unknown_identifier_returns_not_found_envelope(
    canonical_api_client: testing.TestClient,
) -> None:
    """Unknown entities return the common not-found envelope."""
    response = canonical_api_client.simulate_get(
        "/v1/series-profiles/018f0c2a-1234-7000-a000-000000000001"
    )

    _assert_error_envelope(response, status_code=404, code="not_found")
