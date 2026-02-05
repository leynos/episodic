"""Behavioural tests for canonical ingestion workflows."""

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
    IngestionRequest,
    SeriesProfile,
    SourceDocumentInput,
)
from episodic.canonical.services import ingest_sources
from episodic.canonical.storage import IngestionJobRecord, SqlAlchemyUnitOfWork


class TEIProtocol(typ.Protocol):
    """Typed surface for tei_rapporteur interactions in tests."""

    Document: typ.Callable[[str], object]
    emit_xml: typ.Callable[[object], str]


TEI: TEIProtocol = typ.cast("TEIProtocol", _tei)

if typ.TYPE_CHECKING:
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession


@scenario(
    "../features/canonical_ingestion.feature",
    "Ingestion job records canonical content",
)
def test_ingestion_job_records_canonical_content() -> None:
    """Run the canonical ingestion scenario."""


@pytest.fixture
def context() -> dict[str, typ.Any]:
    """Share state between BDD steps."""
    return {}


@given('a series profile "science-hour" exists')
def series_profile_exists(
    _function_scoped_runner: asyncio.Runner,
    session_factory: typ.Callable[[], AsyncSession],
    context: dict[str, typ.Any],
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

    _function_scoped_runner.run(_store_profile())


@given('a TEI document titled "Bridgewater" is available')
def tei_document_available(context: dict[str, typ.Any]) -> None:
    """Provide TEI XML for ingestion."""
    document = TEI.Document("Bridgewater")
    context["tei_xml"] = TEI.emit_xml(document)


@when("an ingestion job records source documents")
def ingestion_job_records_sources(
    _function_scoped_runner: asyncio.Runner,
    session_factory: typ.Callable[[], AsyncSession],
    context: dict[str, typ.Any],
) -> None:
    """Ingest source documents into a canonical episode."""

    async def _ingest() -> None:
        profile = typ.cast("SeriesProfile", context["profile"])
        tei_xml = typ.cast("str", context["tei_xml"])
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
            episode = await ingest_sources(uow, profile, request)

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

    _function_scoped_runner.run(_ingest())


@then('the canonical episode is stored for "science-hour"')
def canonical_episode_stored(
    _function_scoped_runner: asyncio.Runner,
    session_factory: typ.Callable[[], AsyncSession],
    context: dict[str, typ.Any],
) -> None:
    """Verify the canonical episode was persisted."""

    async def _fetch() -> None:
        episode_id = typ.cast("uuid.UUID", context["episode_id"])

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            episode = await uow.episodes.get(episode_id)

        assert episode is not None, "Expected a persisted canonical episode."
        assert episode.title == "Bridgewater", "Expected the episode title."

    _function_scoped_runner.run(_fetch())


@then('the approval state is "draft"')
def approval_state_is_draft(
    _function_scoped_runner: asyncio.Runner,
    session_factory: typ.Callable[[], AsyncSession],
    context: dict[str, typ.Any],
) -> None:
    """Verify the episode approval state is draft."""

    async def _fetch() -> None:
        episode_id = typ.cast("uuid.UUID", context["episode_id"])

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            episode = await uow.episodes.get(episode_id)

        assert episode is not None, "Expected a persisted canonical episode."
        assert episode.approval_state is ApprovalState.DRAFT, (
            "Expected the episode approval state to be draft."
        )

    _function_scoped_runner.run(_fetch())


@then("an approval event is persisted for the ingestion job")
def approval_event_persisted(
    _function_scoped_runner: asyncio.Runner,
    session_factory: typ.Callable[[], AsyncSession],
    context: dict[str, typ.Any],
) -> None:
    """Verify approval events are stored for the ingestion."""

    async def _fetch() -> None:
        episode_id = typ.cast("uuid.UUID", context["episode_id"])
        source_uris = typ.cast("list[str]", context["source_uris"])

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            events = await uow.approval_events.list_for_episode(episode_id)

        assert events, "Expected approval events for the episode."
        event = events[0]
        assert event.from_state is None, "Expected the initial approval event."
        assert event.to_state is ApprovalState.DRAFT, (
            "Expected the approval event to transition to draft."
        )
        assert isinstance(event.payload, dict), "Expected a payload dictionary."
        assert set(event.payload.get("sources", [])) >= set(source_uris), (
            "Expected the approval payload to include the ingested sources."
        )

    _function_scoped_runner.run(_fetch())


@then("source documents are stored and linked to the ingestion job and episode")
def source_documents_linked(
    _function_scoped_runner: asyncio.Runner,
    session_factory: typ.Callable[[], AsyncSession],
    context: dict[str, typ.Any],
) -> None:
    """Verify source documents are linked to ingestion jobs and episodes."""

    async def _fetch() -> None:
        job_id = typ.cast("uuid.UUID", context["ingestion_job_id"])
        episode_id = typ.cast("uuid.UUID", context["episode_id"])
        source_uris = typ.cast("list[str]", context["source_uris"])

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            documents = await uow.source_documents.list_for_job(job_id)

        assert len(documents) == len(source_uris), (
            "Expected one persisted document per ingested source."
        )
        for document in documents:
            assert document.ingestion_job_id == job_id, (
                "Expected document to reference the ingestion job."
            )
            assert document.canonical_episode_id == episode_id, (
                "Expected document to link to the canonical episode."
            )
            assert document.source_uri in source_uris, (
                "Expected document source URI to match an ingested source."
            )

    _function_scoped_runner.run(_fetch())
