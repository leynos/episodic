"""Behavioural tests for canonical ingestion workflows.

Examples
--------
Run the canonical ingestion BDD scenario:

>>> pytest tests/steps/test_canonical_ingestion_steps.py -k ingestion
"""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
import tei_rapporteur as _tei
from pytest_bdd import given, scenario, then, when

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    IngestionRequest,
    SeriesProfile,
    SourceDocumentInput,
)
from episodic.canonical.services import ingest_sources
from episodic.canonical.storage import IngestionJobRecord, SqlAlchemyUnitOfWork
from tests.test_uuid_assertions import assert_uuid7


def _run_async_step(
    runner: asyncio.Runner,
    step_fn: cabc.Callable[[], typ.Awaitable[None]],
) -> None:
    """Execute an async BDD step via the provided runner."""
    coro = typ.cast("typ.Coroutine[object, object, None]", step_fn())
    runner.run(coro)


async def _require_episode(
    session_factory: cabc.Callable[[], AsyncSession],
    episode_id: uuid.UUID,
) -> CanonicalEpisode:
    """Fetch the persisted canonical episode."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        episode = await uow.episodes.get(episode_id)

    assert episode is not None, "Expected a persisted canonical episode."
    return episode


class IngestionContext(typ.TypedDict, total=False):
    """Shared state for canonical ingestion BDD steps."""

    profile: SeriesProfile
    tei_xml: str
    episode_id: uuid.UUID
    ingestion_job_id: uuid.UUID
    source_uris: list[str]


def _run_episode_assertion(
    runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: IngestionContext,
    assertion: cabc.Callable[[CanonicalEpisode], None],
) -> None:
    """Execute a canonical episode assertion for a BDD step."""

    async def _fetch() -> None:
        episode_id = context["episode_id"]

        episode = await _require_episode(session_factory, episode_id)
        assertion(episode)

    _run_async_step(runner, _fetch)


def _assert_episode_title(episode: CanonicalEpisode) -> None:
    """Assert the canonical episode title matches expectations."""
    assert episode.title == "Bridgewater", "Expected the episode title."


def _assert_episode_is_draft(episode: CanonicalEpisode) -> None:
    """Assert the canonical episode approval state is draft."""
    assert_uuid7(episode.id, "canonical episode")
    assert episode.approval_state is ApprovalState.DRAFT, (
        "Expected the episode approval state to be draft."
    )


if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession


@scenario(
    "../features/canonical_ingestion.feature",
    "Ingestion job records canonical content",
)
def test_ingestion_job_records_canonical_content() -> None:
    """Run the canonical ingestion scenario."""


@pytest.fixture
def context() -> IngestionContext:
    """Share state between BDD steps."""
    return typ.cast("IngestionContext", {})


@given('a series profile "science-hour" exists')
def series_profile_exists(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: IngestionContext,
) -> None:
    """Persist a series profile for ingestion."""

    async def _store_profile() -> None:
        now = dt.datetime.now(dt.UTC)
        profile = SeriesProfile(
            id=uuid.uuid4(),
            slug="science-hour",
            title="Science Hour",
            description=None,
            configuration={"tone": "bright"},
            created_at=now,
            updated_at=now,
        )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.series_profiles.add(profile)
            await uow.commit()

        context["profile"] = profile

    _run_async_step(_function_scoped_runner, _store_profile)


@given('a TEI document titled "Bridgewater" is available')
def tei_document_available(context: IngestionContext) -> None:
    """Provide TEI XML for ingestion."""
    document = _tei.Document("Bridgewater")
    context["tei_xml"] = _tei.emit_xml(document)


@when("an ingestion job records source documents")
def ingestion_job_records_sources(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: IngestionContext,
) -> None:
    """Ingest source documents into a canonical episode."""

    async def _ingest() -> None:
        profile = context["profile"]
        tei_xml = context["tei_xml"]
        sources = [
            SourceDocumentInput(
                source_type="web",
                source_uri="https://example.com/report",
                weight=0.8,
                content_hash="hash-bridgewater",
                metadata={"kind": "report"},
            ),
            SourceDocumentInput(
                source_type="transcript",
                source_uri="s3://bucket/transcript.txt",
                weight=0.6,
                content_hash="hash-transcript",
                metadata={"kind": "transcript"},
            ),
        ]

        request = IngestionRequest(
            tei_xml=tei_xml,
            sources=sources,
            requested_by="producer@example.com",
        )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            episode = await ingest_sources(
                uow=uow,
                series_profile=profile,
                request=request,
            )

        async with session_factory() as session:
            result = await session.execute(
                sa.select(IngestionJobRecord).where(
                    IngestionJobRecord.target_episode_id == episode.id
                )
            )
            job_record = result.scalar_one()

        context["episode_id"] = episode.id
        context["ingestion_job_id"] = job_record.id
        context["source_uris"] = [source.source_uri for source in sources]

    _run_async_step(_function_scoped_runner, _ingest)


@then('the canonical episode is stored for "science-hour"')
def canonical_episode_stored(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: IngestionContext,
) -> None:
    """Verify the canonical episode was persisted."""
    _run_episode_assertion(
        _function_scoped_runner,
        session_factory,
        context,
        _assert_episode_title,
    )


@then('the approval state is "draft"')
def approval_state_is_draft(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: IngestionContext,
) -> None:
    """Verify the episode approval state is draft."""
    _run_episode_assertion(
        _function_scoped_runner,
        session_factory,
        context,
        _assert_episode_is_draft,
    )


@then("an approval event is persisted for the ingestion job")
def approval_event_persisted(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: IngestionContext,
) -> None:
    """Verify approval events are stored for the ingestion."""

    async def _fetch() -> None:
        episode_id = context["episode_id"]
        source_uris = context["source_uris"]

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            events = await uow.approval_events.list_for_episode(episode_id)

        assert events, "Expected approval events for the episode."
        event = events[0]
        assert_uuid7(event.id, "approval event")
        assert event.from_state is None, "Expected the initial approval event."
        assert event.to_state is ApprovalState.DRAFT, (
            "Expected the approval event to transition to draft."
        )
        assert isinstance(event.payload, dict), "Expected a payload dictionary."
        assert set(typ.cast("list[str]", event.payload.get("sources", []))) == set(
            source_uris
        ), "Expected the approval payload to include the ingested sources."

    _run_async_step(_function_scoped_runner, _fetch)


@then("source documents are stored and linked to the ingestion job and episode")
def source_documents_linked(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: IngestionContext,
) -> None:
    """Verify source documents are linked to ingestion jobs and episodes."""

    async def _fetch() -> None:
        job_id = context["ingestion_job_id"]
        episode_id = context["episode_id"]
        source_uris = context["source_uris"]

        assert_uuid7(job_id, "ingestion job")
        assert_uuid7(episode_id, "canonical episode")

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            documents = await uow.source_documents.list_for_job(job_id)

        assert len(documents) == len(source_uris), (
            "Expected one persisted document per ingested source."
        )
        for document in documents:
            assert_uuid7(document.id, "source document")
            assert document.ingestion_job_id == job_id, (
                "Expected document to reference the ingestion job."
            )
            assert document.canonical_episode_id == episode_id, (
                "Expected document to link to the canonical episode."
            )
            assert document.source_uri in source_uris, (
                "Expected document source URI to match an ingested source."
            )

    _run_async_step(_function_scoped_runner, _fetch)


@then("TEI header provenance metadata is captured for the ingestion")
def tei_header_provenance_captured(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: IngestionContext,
) -> None:
    """Verify TEI header provenance metadata is persisted."""

    async def _fetch() -> None:
        episode_id = context["episode_id"]
        source_uris = context["source_uris"]

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            episode = await uow.episodes.get(episode_id)
            assert episode is not None, "Expected a persisted canonical episode."
            assert_uuid7(episode.id, "canonical episode")
            assert_uuid7(episode.tei_header_id, "TEI header reference")
            header = await uow.tei_headers.get(episode.tei_header_id)

        assert header is not None, "Expected the TEI header to be persisted."
        assert_uuid7(header.id, "TEI header")
        provenance = header.payload.get("episodic_provenance")
        assert isinstance(provenance, dict), (
            "Expected TEI header provenance dictionary."
        )
        provenance_dict = typ.cast("dict[str, object]", provenance)
        assert provenance_dict.get("capture_context") == "source_ingestion", (
            "Expected ingestion provenance context."
        )
        assert provenance_dict.get("reviewer_identities") == ["producer@example.com"], (
            "Expected reviewer identity from ingestion request."
        )
        assert isinstance(provenance_dict.get("ingestion_timestamp"), str), (
            "Expected ingestion timestamp string in provenance."
        )
        priorities = provenance_dict.get("source_priorities")
        assert isinstance(priorities, list), (
            "Expected source priorities list in provenance."
        )
        priority_items = typ.cast("list[dict[str, object]]", priorities)
        assert len(priorities) == len(source_uris), (
            "Expected one source-priority record per source URI."
        )
        assert priority_items[0]["source_uri"] == "https://example.com/report", (
            "Expected highest-weight source URI to be first."
        )

    _run_async_step(_function_scoped_runner, _fetch)
