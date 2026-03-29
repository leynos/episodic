"""Behavioural tests for reference-binding resolution workflows."""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
import test_reference_document_api_support as reference_support
from pytest_bdd import given, scenario, then, when

from episodic.canonical.adapters.normalizer import InMemorySourceNormalizer
from episodic.canonical.adapters.resolver import HighestWeightConflictResolver
from episodic.canonical.adapters.weighting import DefaultWeightingStrategy
from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    SeriesProfile,
    TeiHeader,
)
from episodic.canonical.ingestion import MultiSourceRequest, RawSourceInput
from episodic.canonical.ingestion_service import IngestionPipeline, ingest_multi_source
from episodic.canonical.storage import IngestionJobRecord, SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc

    from falcon import testing
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _run_async_step(
    runner: asyncio.Runner,
    step_fn: cabc.Callable[[], typ.Awaitable[None]],
) -> None:
    """Execute an async BDD step via the provided runner."""
    coro = typ.cast("typ.Coroutine[object, object, None]", step_fn())
    runner.run(coro)


class BindingResolutionContext(typ.TypedDict, total=False):
    """Shared state for binding-resolution BDD steps."""

    profile_id: str
    template_id: str
    early_episode_id: str
    late_episode_id: str
    early_revision_id: str
    late_revision_id: str
    template_revision_id: str
    early_brief_revision_ids: list[str]
    late_resolved_revision_ids: list[str]
    ingestion_job_id: str


@scenario(
    "../features/binding_resolution.feature",
    (
        "Editorial team resolves bindings for an episode and snapshots them "
        "during ingestion"
    ),
)
def test_binding_resolution_behaviour() -> None:
    """Run the reference-binding resolution scenario."""


@pytest.fixture
def context() -> BindingResolutionContext:
    """Share state between binding-resolution BDD steps."""
    return typ.cast("BindingResolutionContext", {})


@given("reference-binding resolution fixtures exist")
def binding_resolution_fixtures(
    canonical_api_client: testing.TestClient,
    context: BindingResolutionContext,
) -> None:
    """Create a profile and template used by the resolution scenario."""
    fixture = reference_support._build_api_fixture(canonical_api_client)
    context["profile_id"] = fixture.primary_profile_id
    context["template_id"] = fixture.template_id


@given("series episodes exist for binding resolution")
def create_binding_resolution_episodes(
    _function_scoped_runner: asyncio.Runner,
    session_factory: async_sessionmaker[AsyncSession],
    context: BindingResolutionContext,
) -> None:
    """Persist early and late episodes for the scenario profile."""

    async def _create() -> None:
        profile_id = uuid.UUID(context["profile_id"])
        episode_specs = [
            ("early", dt.datetime(2026, 1, 1, tzinfo=dt.UTC)),
            ("late", dt.datetime(2026, 1, 10, tzinfo=dt.UTC)),
        ]
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            for label, created_at in episode_specs:
                episode_id = uuid.uuid4()
                header = TeiHeader(
                    id=uuid.uuid4(),
                    title=f"{label.title()} episode",
                    payload={"file_desc": {"title": f"{label.title()} episode"}},
                    raw_xml="<teiHeader/>",
                    created_at=created_at,
                    updated_at=created_at,
                )
                episode = CanonicalEpisode(
                    id=episode_id,
                    series_profile_id=profile_id,
                    tei_header_id=header.id,
                    title=f"{label.title()} episode",
                    tei_xml=f"<TEI><text>{label}</text></TEI>",
                    status=EpisodeStatus.DRAFT,
                    approval_state=ApprovalState.DRAFT,
                    created_at=created_at,
                    updated_at=created_at,
                )
                await uow.tei_headers.add(header)
                await uow.flush()
                await uow.episodes.add(episode)
                if label == "early":
                    context["early_episode_id"] = str(episode_id)
                else:
                    context["late_episode_id"] = str(episode_id)
            await uow.commit()

    _run_async_step(_function_scoped_runner, _create)


@given("series and template reference bindings exist for binding resolution")
def create_binding_resolution_bindings(
    canonical_api_client: testing.TestClient,
    context: BindingResolutionContext,
) -> None:
    """Create series-level and template-level bindings for the scenario."""
    profile_id = context["profile_id"]
    template_id = context["template_id"]

    series_document_id = reference_support._create_reference_document(
        canonical_api_client,
        profile_id=profile_id,
        kind="style_guide",
        name="BDD style guide",
    )
    context["early_revision_id"] = (
        reference_support._create_reference_document_revision(
            canonical_api_client,
            profile_id=profile_id,
            document_id=series_document_id,
            revision=reference_support._RevisionRequest(
                summary="BDD early style guide",
                content_hash="bdd-binding-resolution-early",
            ),
        )
    )
    context["late_revision_id"] = reference_support._create_reference_document_revision(
        canonical_api_client,
        profile_id=profile_id,
        document_id=series_document_id,
        revision=reference_support._RevisionRequest(
            summary="BDD late style guide",
            content_hash="bdd-binding-resolution-late",
        ),
    )
    for revision_id, effective_from_episode_id in (
        (context["early_revision_id"], context["early_episode_id"]),
        (context["late_revision_id"], context["late_episode_id"]),
    ):
        response = canonical_api_client.simulate_post(
            "/reference-bindings",
            json={
                "reference_document_revision_id": revision_id,
                "target_kind": "series_profile",
                "series_profile_id": profile_id,
                "effective_from_episode_id": effective_from_episode_id,
            },
        )
        assert response.status_code == 201

    template_document_id = reference_support._create_reference_document(
        canonical_api_client,
        profile_id=profile_id,
        kind="guest_profile",
        name="BDD template guest",
    )
    context["template_revision_id"] = (
        reference_support._create_reference_document_revision(
            canonical_api_client,
            profile_id=profile_id,
            document_id=template_document_id,
            revision=reference_support._RevisionRequest(
                summary="BDD template guest",
                content_hash="bdd-binding-resolution-template",
            ),
        )
    )
    reference_support._create_reference_binding(
        canonical_api_client,
        revision_id=context["template_revision_id"],
        template_id=template_id,
    )


def _simulate_get_ok(
    client: testing.TestClient,
    path: str,
    params: dict[str, str],
) -> dict[str, object]:
    """Make a GET request, assert HTTP 200, and return the parsed JSON payload."""
    response = client.simulate_get(path, params=params)
    assert response.status_code == 200
    return typ.cast("dict[str, object]", response.json)


@when("the editorial team requests the structured brief for the early episode")
def request_early_episode_brief(
    canonical_api_client: testing.TestClient,
    context: BindingResolutionContext,
) -> None:
    """Request the structured brief using the early-episode context."""
    payload = _simulate_get_ok(
        canonical_api_client,
        f"/series-profiles/{context['profile_id']}/brief",
        {
            "template_id": context["template_id"],
            "episode_id": context["early_episode_id"],
        },
    )
    reference_documents = typ.cast(
        "list[dict[str, object]]", payload["reference_documents"]
    )
    context["early_brief_revision_ids"] = [
        typ.cast("str", item["revision_id"]) for item in reference_documents
    ]


@when("the editorial team requests the resolved bindings for the late episode")
def request_late_episode_resolution(
    canonical_api_client: testing.TestClient,
    context: BindingResolutionContext,
) -> None:
    """Request the resolved-bindings endpoint using the late-episode context."""
    payload = _simulate_get_ok(
        canonical_api_client,
        f"/series-profiles/{context['profile_id']}/resolved-bindings",
        {
            "template_id": context["template_id"],
            "episode_id": context["late_episode_id"],
        },
    )
    items = typ.cast("list[dict[str, object]]", payload["items"])
    context["late_resolved_revision_ids"] = [
        typ.cast("str", typ.cast("dict[str, object]", item["revision"])["id"])
        for item in items
    ]


@when("multi-source ingestion runs with reference bindings")
def run_ingestion_with_reference_bindings(
    _function_scoped_runner: asyncio.Runner,
    session_factory: async_sessionmaker[AsyncSession],
    context: BindingResolutionContext,
) -> None:
    """Run multi-source ingestion so resolved bindings are snapshotted."""

    async def _ingest() -> None:
        pipeline = IngestionPipeline(
            normalizer=InMemorySourceNormalizer(),
            weighting=DefaultWeightingStrategy(),
            resolver=HighestWeightConflictResolver(),
        )
        request = MultiSourceRequest(
            raw_sources=[
                RawSourceInput(
                    source_type="transcript",
                    source_uri="s3://bucket/bdd-reference-transcript.txt",
                    content="BDD transcript content",
                    content_hash="bdd-reference-transcript",
                    metadata={"title": "BDD Reference Episode"},
                )
            ],
            series_slug="api-reference-primary",
            requested_by="bdd-resolution@example.com",
            episode_template_id=uuid.UUID(context["template_id"]),
        )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            profile = await uow.series_profiles.get(uuid.UUID(context["profile_id"]))
            assert isinstance(profile, SeriesProfile)
            episode = await ingest_multi_source(
                uow,
                profile,
                request,
                pipeline,
            )
            session = uow._session
            assert session is not None
            result = await session.execute(
                sa.select(IngestionJobRecord).where(
                    IngestionJobRecord.target_episode_id == episode.id
                )
            )
            job_record = result.scalar_one()
        context["ingestion_job_id"] = str(job_record.id)

    _run_async_step(_function_scoped_runner, _ingest)


@then("the early-episode brief returns the earlier series revision")
def assert_early_brief_revision(context: BindingResolutionContext) -> None:
    """Verify that the early-episode brief resolves the earlier series revision."""
    assert context["early_brief_revision_ids"] == [
        context["early_revision_id"],
        context["template_revision_id"],
    ]


@then(
    "the late-episode resolved bindings include the latest series revision "
    "and the template revision"
)
def assert_late_resolution(context: BindingResolutionContext) -> None:
    """Verify that the late-episode resolution returns both expected revisions."""
    assert context["late_resolved_revision_ids"] == [
        context["late_revision_id"],
        context["template_revision_id"],
    ]


@then("ingestion snapshots the resolved reference documents as source documents")
def assert_ingestion_snapshots(
    _function_scoped_runner: asyncio.Runner,
    session_factory: async_sessionmaker[AsyncSession],
    context: BindingResolutionContext,
) -> None:
    """Verify that ingestion persists reference snapshots as source documents."""

    async def _assert_snapshots() -> None:
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            documents = await uow.source_documents.list_for_job(
                uuid.UUID(context["ingestion_job_id"])
            )

        reference_snapshots = [
            document
            for document in documents
            if document.source_type == "reference_document"
        ]
        assert len(reference_snapshots) == 2
        assert {
            str(document.reference_document_revision_id)
            for document in reference_snapshots
        } == {
            context["late_revision_id"],
            context["template_revision_id"],
        }

    _run_async_step(_function_scoped_runner, _assert_snapshots)
