"""Pagination tests for profile/template history REST endpoints.

The tests cover ``/v1/series-profiles/{id}/history`` and
``/v1/episode-templates/{id}/history`` with ``limit`` and ``offset`` query
parameters, including default behaviour, min/max limit boundaries, negative
values, and non-numeric input.
"""

import typing as typ

import pytest

from tests.test_profile_template_api import _create_profile, _create_template

if typ.TYPE_CHECKING:
    from falcon import testing


def _create_entity_id_for_endpoint(
    client: testing.TestClient,
    endpoint_kind: str,
) -> str:
    """Create the entity required by one history endpoint."""
    profile_id, _ = _create_profile(client)
    if endpoint_kind == "templates":
        return _create_template(client, profile_id)[0]
    return profile_id


def _assert_validation_error_payload(response_json: object) -> None:
    """Assert invalid pagination returns field-level error details."""
    response_data = typ.cast("dict[str, object]", response_json)
    assert response_data["code"] == "validation_error", (
        "Expected invalid history pagination to use validation_error."
    )
    details = response_data.get("details")
    assert isinstance(details, dict), (
        "Expected invalid history pagination details to be an object."
    )
    assert details, "Expected invalid history pagination to include error details."
    assert {"field", "constraint"} <= details.keys(), (
        "Expected invalid history pagination details to identify the field."
    )


def _assert_success_payload(response_json: object, params: dict[str, str]) -> None:
    """Assert valid pagination returns the expected envelope."""
    payload = typ.cast("dict[str, object]", response_json)
    assert {"items", "limit", "offset", "total"} <= payload.keys(), (
        "Expected valid history pagination to return a full envelope."
    )
    assert isinstance(payload["items"], list), (
        "Expected valid history pagination items to be a list."
    )
    expected_limit = int(params.get("limit", "20"))
    expected_offset = int(params.get("offset", "0"))
    assert payload["limit"] == expected_limit, (
        "Expected valid history pagination to echo limit."
    )
    assert payload["offset"] == expected_offset, (
        "Expected valid history pagination to echo offset."
    )


@pytest.mark.parametrize(
    "endpoint_case",
    [
        ("profiles", "/v1/series-profiles/{entity_id}/history"),
        ("templates", "/v1/episode-templates/{entity_id}/history"),
    ],
)
@pytest.mark.parametrize(
    ("params", "expected_status"),
    [
        ({}, 200),
        ({"limit": "10"}, 200),
        ({"offset": "5"}, 200),
        ({"limit": "0", "offset": "0"}, 400),
        ({"limit": "1", "offset": "0"}, 200),
        ({"limit": "-1", "offset": "-1"}, 400),
        ({"limit": "ten", "offset": "zero"}, 400),
        ({"limit": "100", "offset": "0"}, 200),
        ({"limit": "101", "offset": "0"}, 400),
        ({"limit": "1000000", "offset": "0"}, 400),
        ({"limit": "10", "offset": "-1"}, 400),
        ({"limit": "10", "offset": "0"}, 200),
        ({"limit": "10", "offset": "100"}, 200),
    ],
)
def test_history_endpoints_validate_pagination(
    canonical_api_client: testing.TestClient,
    endpoint_case: tuple[str, str],
    params: dict[str, str],
    expected_status: int,
) -> None:
    """Validate paginated history endpoint responses across a parameter matrix.

    Valid ``limit``/``offset`` combinations must return HTTP 200 with the full
    pagination envelope. Invalid combinations must return HTTP 400 with
    field-level validation details.

    Parameters
    ----------
    canonical_api_client : testing.TestClient
        Falcon test client backed by canonical storage fixtures.
    endpoint_case : tuple[str, str]
        Endpoint kind and path template under test.
    params : dict[str, str]
        Query parameters sent with the history request.
    expected_status : int
        HTTP status expected for the query-parameter combination.
    """
    endpoint_kind, endpoint = endpoint_case
    entity_id = _create_entity_id_for_endpoint(canonical_api_client, endpoint_kind)

    response = canonical_api_client.simulate_get(
        endpoint.format(entity_id=entity_id),
        params=params,
    )

    assert response.status_code == expected_status, (
        "Expected history pagination validation to return the expected status."
    )
    if expected_status == 400:
        _assert_validation_error_payload(response.json)
    else:
        _assert_success_payload(response.json, params)
