"""Shared helpers for binding-resolution API tests."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import tests.test_reference_document_api_support as reference_support
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
class BriefFilterFixture:
    """Reference-binding fixture data for brief filtering assertions."""

    profile_id: str
    template_id: str
    early_episode_id: str
    late_episode_id: str
    revision_early_id: str
    revision_late_id: str
    template_revision_id: str


@dc.dataclass(frozen=True, slots=True)
class DocumentSpec:
    """Document-creation parameters for reference-document test helpers."""

    kind: str
    name: str
    summary: str
    content_hash: str


@dc.dataclass(frozen=True, slots=True)
class BriefRequest:
    """Brief endpoint request identifiers."""

    profile_id: str
    template_id: str
    episode_id: str


def create_series_binding(
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


async def create_episode(
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


def create_document_with_revision(
    client: testing.TestClient,
    profile_id: str,
    spec: DocumentSpec,
) -> tuple[str, str]:
    """Create a reference document and its first revision; return ids."""
    document_id = reference_support.create_reference_document(
        client,
        profile_id=profile_id,
        kind=spec.kind,
        name=spec.name,
    )
    revision_id = reference_support.create_reference_document_revision(
        client,
        profile_id=profile_id,
        document_id=document_id,
        revision=reference_support.RevisionRequest(
            summary=spec.summary,
            content_hash=spec.content_hash,
        ),
    )
    return document_id, revision_id


def create_episode_pair(
    runner: asyncio.Runner,
    session_factory: async_sessionmaker[AsyncSession],
    profile_id: str,
) -> tuple[str, str]:
    """Create an early (2026-01-01) and late (2026-01-10) episode; return their IDs."""
    early_episode_id = runner.run(
        create_episode(
            session_factory,
            profile_id=profile_id,
            title="Early episode",
            created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        )
    )
    late_episode_id = runner.run(
        create_episode(
            session_factory,
            profile_id=profile_id,
            title="Late episode",
            created_at=dt.datetime(2026, 1, 10, tzinfo=dt.UTC),
        )
    )
    return early_episode_id, late_episode_id


def create_style_guide_bindings(
    client: testing.TestClient,
    profile_id: str,
    early_episode_id: str,
    late_episode_id: str,
) -> tuple[str, str]:
    """Create a style-guide document with early/late revisions and series bindings."""
    document_id, revision_early_id = create_document_with_revision(
        client,
        profile_id,
        DocumentSpec(
            kind="style_guide",
            name="Series style guide",
            summary="Early style guide",
            content_hash="binding-resolution-api-early",
        ),
    )
    revision_late_id = reference_support.create_reference_document_revision(
        client,
        profile_id=profile_id,
        document_id=document_id,
        revision=reference_support.RevisionRequest(
            summary="Late style guide",
            content_hash="binding-resolution-api-late",
        ),
    )
    create_series_binding(
        client,
        revision_id=revision_early_id,
        profile_id=profile_id,
        effective_from_episode_id=early_episode_id,
    )
    create_series_binding(
        client,
        revision_id=revision_late_id,
        profile_id=profile_id,
        effective_from_episode_id=late_episode_id,
    )
    return revision_early_id, revision_late_id


def create_template_guest_binding(
    client: testing.TestClient, profile_id: str, template_id: str
) -> str:
    """Create a guest-profile document, revision, and template binding."""
    _, template_revision_id = create_document_with_revision(
        client,
        profile_id,
        DocumentSpec(
            kind="guest_profile",
            name="Template guest profile",
            summary="Template guest profile",
            content_hash="binding-resolution-api-template",
        ),
    )
    reference_support.create_reference_binding(
        client,
        revision_id=template_revision_id,
        template_id=template_id,
    )
    return template_revision_id


def setup_brief_filter_fixture(
    canonical_api_client: testing.TestClient,
    runner: asyncio.Runner,
    session_factory: async_sessionmaker[AsyncSession],
) -> BriefFilterFixture:
    """Create the series/template bindings used by brief filter assertions."""
    fixture = reference_support.build_api_fixture(canonical_api_client)
    profile_id = fixture.primary_profile_id
    template_id = fixture.template_id
    early_episode_id, late_episode_id = create_episode_pair(
        runner, session_factory, profile_id
    )
    revision_early_id, revision_late_id = create_style_guide_bindings(
        canonical_api_client, profile_id, early_episode_id, late_episode_id
    )
    template_revision_id = create_template_guest_binding(
        canonical_api_client, profile_id, template_id
    )
    return BriefFilterFixture(
        profile_id=profile_id,
        template_id=template_id,
        early_episode_id=early_episode_id,
        late_episode_id=late_episode_id,
        revision_early_id=revision_early_id,
        revision_late_id=revision_late_id,
        template_revision_id=template_revision_id,
    )


def assert_brief_response(
    client: testing.TestClient,
    request: BriefRequest,
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
