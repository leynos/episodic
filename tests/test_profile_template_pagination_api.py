"""Pagination tests for profile/template REST list endpoints."""

import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from falcon import testing

    from tests.fixtures.api import CanonicalApiCreators


@pytest.mark.parametrize(
    ("endpoint", "setup_count"),
    [
        ("/v1/series-profiles", 3),
        ("/v1/episode-templates", 3),
    ],
)
def test_list_endpoints_return_pagination_envelopes(
    canonical_api_client: testing.TestClient,
    canonical_api_creators: CanonicalApiCreators,
    endpoint: str,
    setup_count: int,
) -> None:
    """List endpoints should return pagination envelopes with totals."""
    profile_ids = [
        canonical_api_creators.series_profile(f"api-profile-page-{index}")
        for index in range(setup_count)
    ]
    expected_ids = profile_ids

    if endpoint == "/v1/episode-templates":
        expected_ids = [
            canonical_api_creators.episode_template(profile_id)
            for profile_id in profile_ids
        ]

    response = canonical_api_client.simulate_get(
        endpoint,
        params={"limit": "2", "offset": "0"},
    )
    assert response.status_code == 200, (
        f"Expected {endpoint} pagination request to return HTTP 200."
    )
    assert response.json is not None, (
        f"Expected {endpoint} pagination response to include a JSON payload."
    )
    payload = typ.cast("dict[str, object]", response.json)
    items = typ.cast("list[dict[str, object]]", payload["items"])
    assert len(items) == 2, f"Expected {endpoint} to return two items for limit=2."
    returned_ids = [item["id"] for item in items]
    assert returned_ids == expected_ids[:2], (
        f"Expected {endpoint} to return the first two created IDs in order."
    )
    assert payload["limit"] == 2, (
        f"Expected {endpoint} pagination envelope to echo limit=2."
    )
    assert payload["offset"] == 0, (
        f"Expected {endpoint} pagination envelope to echo offset=0."
    )
    assert payload["total"] == setup_count, (
        f"Expected {endpoint} pagination envelope to include the total count."
    )
