"""Integration tests for reference-binding resolution API flows."""

import asyncio
import datetime as dt
import typing as typ
import uuid

import test_reference_document_api_support as reference_support

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    TeiHeader,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    from falcon import testing
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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


def test_structured_brief_filters_series_bindings_by_episode(  # noqa: PLR0914
    canonical_api_client: testing.TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Brief endpoint should resolve series bindings when `episode_id` is provided."""
    fixture = reference_support._build_api_fixture(canonical_api_client)
    profile_id = fixture.primary_profile_id
    template_id = fixture.template_id

    with asyncio.Runner() as runner:
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

    document_id = reference_support._create_reference_document(
        canonical_api_client,
        profile_id=profile_id,
        kind="style_guide",
        name="Series style guide",
    )
    revision_early_id = reference_support._create_reference_document_revision(
        canonical_api_client,
        profile_id=profile_id,
        document_id=document_id,
        revision=reference_support._RevisionRequest(
            summary="Early style guide",
            content_hash="binding-resolution-api-early",
        ),
    )
    revision_late_id = reference_support._create_reference_document_revision(
        canonical_api_client,
        profile_id=profile_id,
        document_id=document_id,
        revision=reference_support._RevisionRequest(
            summary="Late style guide",
            content_hash="binding-resolution-api-late",
        ),
    )
    _create_series_binding(
        canonical_api_client,
        revision_id=revision_early_id,
        profile_id=profile_id,
        effective_from_episode_id=early_episode_id,
    )
    _create_series_binding(
        canonical_api_client,
        revision_id=revision_late_id,
        profile_id=profile_id,
        effective_from_episode_id=late_episode_id,
    )

    template_document_id = reference_support._create_reference_document(
        canonical_api_client,
        profile_id=profile_id,
        kind="guest_profile",
        name="Template guest profile",
    )
    template_revision_id = reference_support._create_reference_document_revision(
        canonical_api_client,
        profile_id=profile_id,
        document_id=template_document_id,
        revision=reference_support._RevisionRequest(
            summary="Template guest profile",
            content_hash="binding-resolution-api-template",
        ),
    )
    reference_support._create_reference_binding(
        canonical_api_client,
        revision_id=template_revision_id,
        template_id=template_id,
    )

    early_response = canonical_api_client.simulate_get(
        f"/series-profiles/{profile_id}/brief",
        params={
            "template_id": template_id,
            "episode_id": early_episode_id,
        },
    )
    assert early_response.status_code == 200, (
        "Expected structured brief lookup for the early episode to succeed."
    )
    early_documents = typ.cast(
        "list[dict[str, object]]",
        typ.cast("dict[str, object]", early_response.json)["reference_documents"],
    )
    assert [item["revision_id"] for item in early_documents] == [
        revision_early_id,
        template_revision_id,
    ], "Expected early episode brief to include early series revision plus template."

    late_response = canonical_api_client.simulate_get(
        f"/series-profiles/{profile_id}/brief",
        params={
            "template_id": template_id,
            "episode_id": late_episode_id,
        },
    )
    assert late_response.status_code == 200, (
        "Expected structured brief lookup for the late episode to succeed."
    )
    late_documents = typ.cast(
        "list[dict[str, object]]",
        typ.cast("dict[str, object]", late_response.json)["reference_documents"],
    )
    assert [item["revision_id"] for item in late_documents] == [
        revision_late_id,
        template_revision_id,
    ], "Expected late episode brief to include late series revision plus template."


def test_resolved_bindings_endpoint_returns_resolved_payloads(  # noqa: PLR0914
    canonical_api_client: testing.TestClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Resolved-bindings endpoint should return document, revision, and binding data."""
    fixture = reference_support._build_api_fixture(canonical_api_client)
    profile_id = fixture.primary_profile_id
    template_id = fixture.template_id

    with asyncio.Runner() as runner:
        episode_id = runner.run(
            _create_episode(
                session_factory,
                profile_id=profile_id,
                title="Resolution target episode",
                created_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
            )
        )

    series_document_id = reference_support._create_reference_document(
        canonical_api_client,
        profile_id=profile_id,
        kind="style_guide",
        name="Resolved series guide",
    )
    series_revision_id = reference_support._create_reference_document_revision(
        canonical_api_client,
        profile_id=profile_id,
        document_id=series_document_id,
        revision=reference_support._RevisionRequest(
            summary="Resolved series guide",
            content_hash="resolved-bindings-series",
        ),
    )
    _create_series_binding(
        canonical_api_client,
        revision_id=series_revision_id,
        profile_id=profile_id,
        effective_from_episode_id=episode_id,
    )

    template_document_id = reference_support._create_reference_document(
        canonical_api_client,
        profile_id=profile_id,
        kind="guest_profile",
        name="Resolved template guest",
    )
    template_revision_id = reference_support._create_reference_document_revision(
        canonical_api_client,
        profile_id=profile_id,
        document_id=template_document_id,
        revision=reference_support._RevisionRequest(
            summary="Resolved template guest",
            content_hash="resolved-bindings-template",
        ),
    )
    reference_support._create_reference_binding(
        canonical_api_client,
        revision_id=template_revision_id,
        template_id=template_id,
    )

    response = canonical_api_client.simulate_get(
        f"/series-profiles/{profile_id}/resolved-bindings",
        params={"episode_id": episode_id, "template_id": template_id},
    )

    assert response.status_code == 200, (
        "Expected resolved-bindings endpoint to return 200."
    )
    payload = typ.cast("dict[str, object]", response.json)
    items = typ.cast("list[dict[str, object]]", payload["items"])
    revisions = [typ.cast("dict[str, object]", item["revision"]) for item in items]
    documents = [typ.cast("dict[str, object]", item["document"]) for item in items]
    assert [revision["id"] for revision in revisions] == [
        series_revision_id,
        template_revision_id,
    ], "Expected resolved-bindings endpoint to return both resolved revisions."
    assert documents[0]["kind"] == "style_guide"
    assert documents[1]["kind"] == "guest_profile"


def test_resolved_bindings_endpoint_requires_episode_id(
    canonical_api_client: testing.TestClient,
) -> None:
    """Resolved-bindings endpoint should reject requests missing `episode_id`."""
    fixture = reference_support._build_api_fixture(canonical_api_client)

    response = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/resolved-bindings"
    )

    assert response.status_code == 400, (
        "Expected missing episode_id to return HTTP 400."
    )
    payload = typ.cast("dict[str, object]", response.json)
    assert payload["description"] == "Missing required query parameter: episode_id"


def test_resolved_bindings_endpoint_rejects_invalid_episode_id(
    canonical_api_client: testing.TestClient,
) -> None:
    """Resolved-bindings endpoint should reject invalid UUID query parameters."""
    fixture = reference_support._build_api_fixture(canonical_api_client)

    response = canonical_api_client.simulate_get(
        f"/series-profiles/{fixture.primary_profile_id}/resolved-bindings",
        params={"episode_id": "not-a-valid-uuid"},
    )

    assert response.status_code == 400, (
        "Expected invalid episode_id to return HTTP 400."
    )
    payload = typ.cast("dict[str, object]", response.json)
    assert payload["description"] == "Invalid UUID for episode_id: 'not-a-valid-uuid'."
