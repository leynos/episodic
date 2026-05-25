"""Reusable API fixture builders for reference-document endpoint tests."""

import dataclasses as dc
import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from falcon import testing

HTTP_OK = 200
HTTP_CREATED = 201
DEFAULT_LIMIT = 10


@dc.dataclass(frozen=True, slots=True)
class ApiFixture:
    """Fixture payload for reference-document API tests."""

    primary_profile_id: str
    secondary_profile_id: str
    template_id: str
    secondary_template_id: str


@dc.dataclass(frozen=True, slots=True)
class RevisionRequest:
    """Reference-document revision request fixture payload."""

    summary: str
    content_hash: str


def _fail(message: str) -> typ.NoReturn:
    pytest.fail(message)


def _assert_status(
    actual_status: int,
    expected_status: int,
    message: str,
) -> None:
    if actual_status != expected_status:
        _fail(message)


def _assert_equal(actual: object, expected: object, message: str) -> None:
    if actual != expected:
        _fail(message)


def _assert_instance(value: object, expected_type: type[object], message: str) -> None:
    if not isinstance(value, expected_type):
        _fail(message)


def post_and_return_id(
    client: testing.TestClient,
    path: str,
    body: dict[str, object],
    *,
    assertion_message: str | None = None,
) -> str:
    """POST *body* to *path*, assert HTTP 201, and return the ``id`` field."""
    response = client.simulate_post(path, json=body)
    msg = assertion_message or f"Expected POST {path} to return 201."
    _assert_status(response.status_code, HTTP_CREATED, msg)
    return typ.cast("str", typ.cast("dict[str, object]", response.json)["id"])


def profile_body(slug: str) -> dict[str, object]:
    """Return a series-profile creation body for *slug*."""
    return {
        "slug": slug,
        "title": f"{slug} title",
        "description": f"{slug} description",
        "configuration": {"tone": "neutral"},
        "actor": "api-reference@example.com",
        "note": "Create profile",
    }


def build_api_fixture(client: testing.TestClient) -> ApiFixture:
    """Build common API fixture entities for reference-document endpoint tests."""
    primary_profile_id = post_and_return_id(
        client,
        "/v1/series-profiles",
        profile_body("api-reference-primary"),
        assertion_message="Expected profile creation to return 201.",
    )
    secondary_profile_id = post_and_return_id(
        client,
        "/v1/series-profiles",
        profile_body("api-reference-secondary"),
        assertion_message="Expected profile creation to return 201.",
    )
    template_id = post_and_return_id(
        client,
        "/v1/episode-templates",
        {
            "series_profile_id": primary_profile_id,
            "slug": "api-reference-template",
            "title": "api-reference-template title",
            "description": "api-reference-template description",
            "structure": {"segments": ["intro", "main", "outro"]},
            "actor": "api-reference@example.com",
            "note": "Create template",
        },
        assertion_message="Expected template creation to return 201.",
    )
    secondary_template_id = post_and_return_id(
        client,
        "/v1/episode-templates",
        {
            "series_profile_id": secondary_profile_id,
            "slug": "api-reference-secondary-template",
            "title": "api-reference-secondary-template title",
            "description": "api-reference-secondary-template description",
            "structure": {"segments": ["intro", "outro"]},
            "actor": "api-reference@example.com",
            "note": "Create secondary template",
        },
        assertion_message="Expected secondary template creation to return 201.",
    )
    return ApiFixture(
        primary_profile_id=primary_profile_id,
        secondary_profile_id=secondary_profile_id,
        template_id=template_id,
        secondary_template_id=secondary_template_id,
    )


def create_reference_document(
    client: testing.TestClient,
    *,
    profile_id: str,
    kind: str,
    name: str,
) -> str:
    """Create one reusable reference document and return its identifier."""
    response = client.simulate_post(
        f"/v1/series-profiles/{profile_id}/reference-documents",
        json={
            "kind": kind,
            "lifecycle_state": "active",
            "metadata": {"name": name},
        },
    )
    _assert_status(
        response.status_code,
        HTTP_CREATED,
        "expected 201 creating reference document, got "
        f"{response.status_code}: {response.text}",
    )
    payload = typ.cast("dict[str, object]", response.json)
    _assert_equal(payload["lock_version"], 1, f"unexpected lock_version: {payload}")
    return typ.cast("str", payload["id"])


def assert_reference_document_list(
    client: testing.TestClient,
    *,
    profile_id: str,
    kind: str | None = None,
) -> list[dict[str, object]]:
    """List reference documents and assert a valid list envelope."""
    params: dict[str, str] = {"limit": "10", "offset": "0"}
    if kind is not None:
        params["kind"] = kind

    response = client.simulate_get(
        f"/v1/series-profiles/{profile_id}/reference-documents",
        params=params,
    )
    _assert_status(
        response.status_code,
        HTTP_OK,
        f"unexpected status for GET reference documents: {response.status_code}: "
        f"{response.text}",
    )
    payload = typ.cast("dict[str, object]", response.json)
    _assert_instance(payload, dict, f"expected list payload dict, got: {payload!r}")
    items = typ.cast("list[dict[str, object]]", payload["items"])
    _assert_instance(items, list, f"expected items list in payload: {payload}")
    _assert_equal(
        payload["limit"],
        DEFAULT_LIMIT,
        f"expected limit 10 in payload: {payload}",
    )
    _assert_equal(payload["offset"], 0, f"expected offset 0 in payload: {payload}")
    _assert_equal(
        payload["total"],
        len(items),
        f"expected total to match returned items in payload: {payload}",
    )
    return items


def create_reference_document_revision(
    client: testing.TestClient,
    *,
    profile_id: str,
    document_id: str,
    revision: RevisionRequest,
) -> str:
    """Create one immutable reference-document revision and return its id."""
    response = client.simulate_post(
        f"/v1/series-profiles/{profile_id}/reference-documents/{document_id}/revisions",
        json={
            "content": {"summary": revision.summary},
            "content_hash": revision.content_hash,
            "author": "api-reference@example.com",
            "change_note": revision.summary,
        },
    )
    _assert_status(
        response.status_code,
        HTTP_CREATED,
        "expected 201 creating reference-document revision, got "
        f"{response.status_code}: {response.text}",
    )
    payload = typ.cast("dict[str, object]", response.json)
    return typ.cast("str", payload["id"])


def assert_reference_revision_history(
    client: testing.TestClient,
    *,
    profile_id: str,
    document_id: str,
) -> list[dict[str, object]]:
    """List immutable revisions and assert a valid list envelope."""
    response = client.simulate_get(
        f"/v1/series-profiles/{profile_id}/reference-documents/{document_id}/revisions",
        params={"limit": "10", "offset": "0"},
    )
    _assert_status(
        response.status_code,
        HTTP_OK,
        f"unexpected status for GET revision history: {response.status_code}: "
        f"{response.text}",
    )
    payload = typ.cast("dict[str, object]", response.json)
    items = typ.cast("list[dict[str, object]]", payload["items"])
    _assert_equal(
        payload["limit"],
        DEFAULT_LIMIT,
        f"expected limit 10, got {payload['limit']}",
    )
    _assert_equal(payload["offset"], 0, f"expected offset 0, got {payload['offset']}")
    _assert_equal(
        payload["total"],
        len(items),
        f"expected total to match returned revisions in payload: {payload}",
    )
    return items


def create_reference_binding(
    client: testing.TestClient,
    *,
    revision_id: str,
    template_id: str,
) -> str:
    """Create one reference binding and return its identifier."""
    response = client.simulate_post(
        "/v1/reference-bindings",
        json={
            "reference_document_revision_id": revision_id,
            "target_kind": "episode_template",
            "episode_template_id": template_id,
        },
    )
    _assert_status(
        response.status_code,
        HTTP_CREATED,
        "expected 201 creating reference binding, got "
        f"{response.status_code}: {response.text}",
    )
    payload = typ.cast("dict[str, object]", response.json)
    return typ.cast("str", payload["id"])
