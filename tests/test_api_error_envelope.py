"""Integration coverage for the canonical REST error envelope."""

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    from falcon import testing


@dc.dataclass(frozen=True, slots=True)
class _Expected:
    """Expected envelope fields for ``_assert_error_envelope``."""

    status_code: int
    code: str
    field: str | None = None
    constraint: str | None = None


def _assert_error_envelope(
    response: testing.Result,
    expected: _Expected,
) -> dict[str, object]:
    """Assert the common API error envelope and return its payload."""
    assert response.status_code == expected.status_code, (
        f"expected status {expected.status_code}, got {response.status_code}"
    )
    payload = typ.cast("dict[str, object]", response.json)
    expected_keys = {"code", "message", "details"}
    assert set(payload) == expected_keys, (
        f"expected envelope keys {expected_keys}, got {set(payload)}"
    )
    assert payload["code"] == expected.code, (
        f"expected error code {expected.code!r}, got {payload['code']!r}"
    )
    assert isinstance(payload["message"], str), (
        f"expected string message, got {type(payload['message']).__name__}"
    )
    raw_details = payload["details"]
    assert isinstance(raw_details, dict), (
        f"expected envelope `details` to be a dict, "
        f"got {type(raw_details).__name__}; payload={payload}"
    )
    details = typ.cast("dict[str, object]", raw_details)
    if expected.field is not None:
        assert details["field"] == expected.field, (
            f"expected details field {expected.field!r}, got {details.get('field')!r}"
        )
    if expected.constraint is not None:
        assert details["constraint"] == expected.constraint, (
            f"expected details constraint {expected.constraint!r}, "
            f"got {details.get('constraint')!r}"
        )
    return payload


def test_invalid_uuid_returns_validation_envelope(
    canonical_api_client: testing.TestClient,
) -> None:
    """Invalid path identifiers return a field-specific validation error."""
    response = canonical_api_client.simulate_get("/v1/series-profiles/not-a-valid-uuid")

    _assert_error_envelope(
        response,
        _Expected(
            status_code=400,
            code="validation_error",
            field="profile_id",
            constraint="uuid",
        ),
    )


def test_invalid_pagination_returns_validation_envelope(
    canonical_api_client: testing.TestClient,
) -> None:
    """Invalid pagination bounds return range details."""
    response = canonical_api_client.simulate_get(
        "/v1/reference-bindings",
        params={
            "target_kind": "episode_template",
            "target_id": "00000000-0000-0000-0000-000000000000",
            "limit": "0",
        },
    )

    _assert_error_envelope(
        response,
        _Expected(
            status_code=400,
            code="validation_error",
            field="limit",
            constraint="range",
        ),
    )


def test_invalid_optional_uuid_filter_returns_validation_envelope(
    canonical_api_client: testing.TestClient,
) -> None:
    """Invalid optional UUID query filters return field-specific details."""
    response = canonical_api_client.simulate_get(
        "/v1/episode-templates",
        params={"series_profile_id": "not-a-uuid"},
    )

    _assert_error_envelope(
        response,
        _Expected(
            status_code=400,
            code="validation_error",
            field="series_profile_id",
            constraint="uuid",
        ),
    )


def test_invalid_reference_document_kind_filter_returns_validation_envelope(
    canonical_api_client: testing.TestClient,
) -> None:
    """Invalid document-kind filters return field-specific enum details."""
    response = canonical_api_client.simulate_get(
        "/v1/series-profiles/018f0c2a-1234-7000-a000-000000000001/reference-documents",
        params={"kind": "not-a-kind"},
    )

    _assert_error_envelope(
        response,
        _Expected(
            status_code=400,
            code="validation_error",
            field="kind",
            constraint="enum",
        ),
    )


def test_invalid_reference_binding_target_kind_returns_validation_envelope(
    canonical_api_client: testing.TestClient,
) -> None:
    """Invalid binding target-kind filters return field-specific enum details."""
    response = canonical_api_client.simulate_get(
        "/v1/reference-bindings",
        params={
            "target_kind": "not-a-target",
            "target_id": "018f0c2a-1234-7000-a000-000000000001",
        },
    )

    _assert_error_envelope(
        response,
        _Expected(
            status_code=400,
            code="validation_error",
            field="target_kind",
            constraint="enum",
        ),
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
        _Expected(
            status_code=400,
            code="validation_error",
            field="episode_id",
            constraint="required",
        ),
    )


def test_unknown_identifier_returns_not_found_envelope(
    canonical_api_client: testing.TestClient,
) -> None:
    """Unknown entities return the common not-found envelope."""
    response = canonical_api_client.simulate_get(
        "/v1/series-profiles/018f0c2a-1234-7000-a000-000000000001"
    )

    _assert_error_envelope(response, _Expected(status_code=404, code="not_found"))
