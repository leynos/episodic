"""Integration tests for reference-binding resolution API flows."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest
import test_reference_document_api_support as reference_support

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    TeiHeader,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    import asyncio

    from falcon import testing
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dc.dataclass(frozen=True, slots=True)
class _BriefFilterFixture:
    """Reference-binding fixture data for brief filtering assertions."""

    profile_id: str
    template_id: str
    early_episode_id: str
    late_episode_id: str
    revision_early_id: str
    revision_late_id: str
    template_revision_id: str


@dc.dataclass(frozen=True, slots=True)
class _DocumentSpec:
    """Document-creation parameters for reference-document test helpers."""

    kind: str
    name: str
    summary: str
    content_hash: str


@dc.dataclass(frozen=True, slots=True)
class _BriefRequest:
    profile_id: str
    template_id: str
    episode_id: str


def _create_series_binding(
    client: testing.TestClient,
    *,
    revision_id: str,
    profile_id: str,
    effective_from_episode_id: str | None,
) -> str:
    """Create a series-profile binding through the API."""
    response = client.simulate_post(
        "/reference-bindings",
        json={
            "reference_document_revision_id": revision_id,
            "target_kind": "series_profile",
            "series_profile_id": profile_id,
            "effective_from_episode_id": effective_from_episode_id,
        },
    )
    assert response.status_code == 201, (
        "expected 201 creating series reference binding, got "
        f"{response.status_code}: {response.text}"
    )
    payload = typ.cast("dict[str, object]", response.json)
    return typ.cast("str", payload["id"])


async def _create_episode(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    profile_id: str,
    title: str,
    created_at: dt.datetime,
) -> str:
    """Persist one canonical episode for API resolution tests."""
    episode_id = uuid.uuid4()
    header_id = uuid.uuid4()
    header = TeiHeader(
        id=header_id,
        title=title,
        payload={"file_desc": {"title": title}},
        raw_xml="<teiHeader/>",
        created_at=created_at,
        updated_at=created_at,
    )
    episode = CanonicalEpisode(
        id=episode_id,
        series_profile_id=uuid.UUID(profile_id),
        tei_header_id=header_id,
        title=title,
        tei_xml=f"<TEI><text>{title}</text></TEI>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=created_at,
        updated_at=created_at,
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.tei_headers.add(header)
        await uow.flush()
        await uow.episodes.add(episode)
        await uow.commit()
    return str(episode_id)


def _create_document_with_revision(
    client: testing.TestClient,
    profile_id: str,
    spec: _DocumentSpec,
) -> tuple[str, str]:
    """Create a reference document and its first revision; return ids."""
    document_id = reference_support._create_reference_document(
        client,
        profile_id=profile_id,
        kind=spec.kind,
        name=spec.name,
    )
    revision_id = reference_support._create_reference_document_revision(
        client,
        profile_id=profile_id,
        document_id=document_id,
        revision=reference_support._RevisionRequest(
            summary=spec.summary,
            content_hash=spec.content_hash,
        ),
    )
    return document_id, revision_id


def _create_episode_pair(
    runner: asyncio.Runner,
    session_factory: async_sessionmaker[AsyncSession],
    profile_id: str,
) -> tuple[str, str]:
    """Create an early (2026-01-01) and late (2026-01-10) episode; return their IDs."""
    early_episode_id = runner.run(
        _create_episode(
            session_factory,
            profile_id=profile_id,
            title="Early episode",
            created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        )
    )
    late_episode_id = runner.run(
        _create_episode(
            session_factory,
            profile_id=profile_id,
            title="Late episode",
            created_at=dt.datetime(2026, 1, 10, tzinfo=dt.UTC),
        )
    )
    return early_episode_id, late_episode_id


def _create_style_guide_bindings(
    client: testing.TestClient,
    profile_id: str,
    early_episode_id: str,
    late_episode_id: str,
) -> tuple[str, str]:
    """Create a style-guide document with early/late revisions and series bindings."""
    document_id, revision_early_id = _create_document_with_revision(
        client,
        profile_id,
        _DocumentSpec(
            kind="style_guide",
            name="Series style guide",
            summary="Early style guide",
            content_hash="binding-resolution-api-early",
        ),
    )
    revision_late_id = reference_support._create_reference_document_revision(
        client,
        profile_id=profile_id,
        document_id=document_id,
        revision=reference_support._RevisionRequest(
            summary="Late style guide",
            content_hash="binding-resolution-api-late",
        ),
    )
    _create_series_binding(
        client,
        revision_id=revision_early_id,
        profile_id=profile_id,
        effective_from_episode_id=early_episode_id,
    )
    _create_series_binding(
        client,
        revision_id=revision_late_id,
        profile_id=profile_id,
        effective_from_episode_id=late_episode_id,
    )
    return revision_early_id, revision_late_id


def _create_template_guest_binding(
    client: testing.TestClient, profile_id: str, template_id: str
) -> str:
    """Create a guest-profile document, revision, and template binding."""
    _, template_revision_id = _create_document_with_revision(
        client,
        profile_id,
        _DocumentSpec(
            kind="guest_profile",
            name="Template guest profile",
            summary="Template guest profile",
            content_hash="binding-resolution-api-template",
        ),
    )
    reference_support._create_reference_binding(
        client,
        revision_id=template_revision_id,
        template_id=template_id,
    )
    return template_revision_id


def _setup_brief_filter_fixture(
    canonical_api_client: testing.TestClient,
    runner: asyncio.Runner,
    session_factory: async_sessionmaker[AsyncSession],
) -> _BriefFilterFixture:
    """Create the series/template bindings used by brief filter assertions."""
    fixture = reference_support._build_api_fixture(canonical_api_client)
    profile_id = fixture.primary_profile_id
    template_id = fixture.template_id
    early_episode_id, late_episode_id = _create_episode_pair(
        runner, session_factory, profile_id
    )
    revision_early_id, revision_late_id = _create_style_guide_bindings(
        canonical_api_client, profile_id, early_episode_id, late_episode_id
    )
    template_revision_id = _create_template_guest_binding(
        canonical_api_client, profile_id, template_id
    )
    return _BriefFilterFixture(
        profile_id=profile_id,
        template_id=template_id,
        early_episode_id=early_episode_id,
        late_episode_id=late_episode_id,
        revision_early_id=revision_early_id,
        revision_late_id=revision_late_id,
        template_revision_id=template_revision_id,
    )


def _assert_brief_response(
    client: testing.TestClient,
    request: _BriefRequest,
    expected_revision_ids: list[str],
    description: str,
) -> None:
    """Assert that one brief response contains the expected revision ids."""
    response = client.simulate_get(
        f"/series-profiles/{request.profile_id}/brief",
        params={
            "template_id": request.template_id,
            "episode_id": request.episode_id,
        },
    )
    assert response.status_code == 200, description
    documents = typ.cast(
        "list[dict[str, object]]",
        typ.cast("dict[str, object]", response.json)["reference_documents"],
    )
    assert [item["revision_id"] for item in documents] == expected_revision_ids, (
        description
    )


def test_structured_brief_filters_series_bindings_by_episode(
    canonical_api_client: testing.TestClient,
    _function_scoped_runner: asyncio.Runner,  # noqa: PT019
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Brief endpoint should resolve series bindings when `episode_id` is provided."""
    fixture = _setup_brief_filter_fixture(
        canonical_api_client, _function_scoped_runner, session_factory
    )
    _assert_brief_response(
        canonical_api_client,
        _BriefRequest(
            fixture.profile_id, fixture.template_id, fixture.early_episode_id
        ),
        [fixture.revision_early_id, fixture.template_revision_id],
        "Expected early episode brief to include early series revision plus template.",
    )
    _assert_brief_response(
        canonical_api_client,
        _BriefRequest(fixture.profile_id, fixture.template_id, fixture.late_episode_id),
        [fixture.revision_late_id, fixture.template_revision_id],
        "Expected late episode brief to include late series revision plus template.",
    )


def test_resolved_bindings_endpoint_returns_resolved_payloads(
    canonical_api_client: testing.TestClient,
    _function_scoped_runner: asyncio.Runner,  # noqa: PT019
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Resolved-bindings endpoint should return document, revision, and binding data."""
    fixture = reference_support._build_api_fixture(canonical_api_client)

    episode_id = _function_scoped_runner.run(
        _create_episode(
            session_factory,
            profile_id=fixture.primary_profile_id,
            title="Resolution target episode",
            created_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
        )
    )

    _, series_revision_id = _create_document_with_revision(
        canonical_api_client,
        fixture.primary_profile_id,
        _DocumentSpec(
            kind="style_guide",
            name="Resolved series guide",
            summary="Resolved series guide",
            content_hash="resolved-bindings-series",
        ),
    )
    _create_series_binding(
        canonical_api_client,
        revision_id=series_revision_id,
        profile_id=fixture.primary_profile_id,
        effective_from_episode_id=episode_id,
    )

    _, template_revision_id = _create_document_with_revision(
        canonical_api_client,
        fixture.primary_profile_id,
        _DocumentSpec(
            kind="guest_profile",
            name="Resolved template guest",
            summary="Resolved template guest",
            content_hash="resolved-bindings-template",
        ),
    )
    reference_support._create_reference_binding(
        canonical_api_client,
        revision_id=template_revision_id,
        template_id=fixture.template_id,
    )

    response = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/resolved-bindings",
        params={"episode_id": episode_id, "template_id": fixture.template_id},
    )

    assert response.status_code == 200, (
        "Expected resolved-bindings endpoint to return 200."
    )
    items = typ.cast(
        "list[dict[str, object]]",
        typ.cast("dict[str, object]", response.json)["items"],
    )
    revisions = [typ.cast("dict[str, object]", item["revision"]) for item in items]
    documents = [typ.cast("dict[str, object]", item["document"]) for item in items]
    assert [revision["id"] for revision in revisions] == [
        series_revision_id,
        template_revision_id,
    ], "Expected resolved-bindings endpoint to return both resolved revisions."
    assert documents[0]["kind"] == "style_guide"
    assert documents[1]["kind"] == "guest_profile"


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
    fixture = reference_support._build_api_fixture(canonical_api_client)
    response = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/resolved-bindings",
        params=params,
    )
    assert response.status_code == 400
    payload = typ.cast("dict[str, object]", response.json)
    assert payload["description"] == expected_description


def test_resolved_bindings_endpoint_returns_404_for_unknown_profile(
    canonical_api_client: testing.TestClient,
) -> None:
    """Resolved-bindings endpoint should return 404 for a nonexistent profile."""
    unknown_profile_id = str(uuid.uuid4())
    episode_id = str(uuid.uuid4())
    response = canonical_api_client.simulate_get(
        f"/series-profiles/{unknown_profile_id}/resolved-bindings",
        params={"episode_id": episode_id},
    )
    assert response.status_code == 404, "Expected 404 for unknown series profile."


def test_resolved_bindings_endpoint_returns_404_for_episode_not_in_profile(
    canonical_api_client: testing.TestClient,
    _function_scoped_runner: asyncio.Runner,  # noqa: PT019
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Resolved-bindings endpoint returns 404 for cross-profile episode."""
    fixture = reference_support._build_api_fixture(canonical_api_client)
    # Create an episode under the *secondary* profile.
    episode_id = _function_scoped_runner.run(
        _create_episode(
            session_factory,
            profile_id=fixture.secondary_profile_id,
            title="Wrong-profile episode",
            created_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
        )
    )
    # Request resolved bindings for the *primary* profile with this episode.
    response = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/resolved-bindings",
        params={"episode_id": episode_id},
    )
    assert response.status_code == 404, (
        "Expected 404 when episode does not belong to the requested profile."
    )


def test_brief_endpoint_returns_404_for_invalid_episode(
    canonical_api_client: testing.TestClient,
) -> None:
    """Brief endpoint should return 404 when episode_id does not exist."""
    fixture = reference_support._build_api_fixture(canonical_api_client)
    nonexistent_episode_id = str(uuid.uuid4())
    response = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/brief",
        params={"episode_id": nonexistent_episode_id},
    )
    assert response.status_code == 404, "Expected 404 when episode_id does not exist."


def test_brief_endpoint_returns_404_for_episode_not_in_profile(
    canonical_api_client: testing.TestClient,
    _function_scoped_runner: asyncio.Runner,  # noqa: PT019
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Brief endpoint returns 404 when episode belongs to a different profile."""
    fixture = reference_support._build_api_fixture(canonical_api_client)
    # Create an episode under the *secondary* profile.
    episode_id = _function_scoped_runner.run(
        _create_episode(
            session_factory,
            profile_id=fixture.secondary_profile_id,
            title="Wrong-profile episode for brief",
            created_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
        )
    )
    # Request brief for the *primary* profile with this episode.
    response = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/brief",
        params={"episode_id": episode_id},
    )
    assert response.status_code == 404, (
        "Expected 404 when episode does not belong to the requested profile."
    )


def test_resolved_bindings_endpoint_returns_404_for_unknown_template(
    canonical_api_client: testing.TestClient,
    _function_scoped_runner: asyncio.Runner,  # noqa: PT019
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Resolved-bindings endpoint should return 404 for a nonexistent template."""
    fixture = reference_support._build_api_fixture(canonical_api_client)
    episode_id = _function_scoped_runner.run(
        _create_episode(
            session_factory,
            profile_id=fixture.primary_profile_id,
            title="Test episode",
            created_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
        )
    )
    unknown_template_id = str(uuid.uuid4())
    response = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/resolved-bindings",
        params={"episode_id": episode_id, "template_id": unknown_template_id},
    )
    assert response.status_code == 404, "Expected 404 for unknown episode template."


def test_resolved_bindings_endpoint_returns_404_for_cross_profile_template(
    canonical_api_client: testing.TestClient,
    _function_scoped_runner: asyncio.Runner,  # noqa: PT019
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Resolved-bindings endpoint returns 404 for template not in profile."""
    fixture = reference_support._build_api_fixture(canonical_api_client)
    # Create an episode under the primary profile.
    episode_id = _function_scoped_runner.run(
        _create_episode(
            session_factory,
            profile_id=fixture.primary_profile_id,
            title="Test episode",
            created_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
        )
    )
    # Request resolved bindings for the primary profile with the secondary
    # profile's template.
    response = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/resolved-bindings",
        params={"episode_id": episode_id, "template_id": fixture.secondary_template_id},
    )
    assert response.status_code == 404, (
        "Expected 404 when template does not belong to the requested profile."
    )
