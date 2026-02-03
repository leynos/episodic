"""Behavioural tests for canonical ingestion workflows."""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest
import tei_rapporteur as _tei
from pytest_bdd import given, scenario, then, when

from episodic.canonical.domain import (
    ApprovalState,
    IngestionRequest,
    SeriesProfile,
    SourceDocumentInput,
)
from episodic.canonical.services import ingest_sources
from episodic.canonical.storage import SqlAlchemyUnitOfWork

TEI: typ.Any = _tei

if typ.TYPE_CHECKING:
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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
    session_factory: object,
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

        factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
        async with SqlAlchemyUnitOfWork(factory) as uow:
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
    session_factory: object,
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

        factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
        async with SqlAlchemyUnitOfWork(factory) as uow:
            episode = await ingest_sources(uow, profile, request)

        context["episode_id"] = episode.id

    _function_scoped_runner.run(_ingest())


@then('the canonical episode is stored for "science-hour"')
def canonical_episode_stored(
    _function_scoped_runner: asyncio.Runner,
    session_factory: object,
    context: dict[str, typ.Any],
) -> None:
    """Verify the canonical episode was persisted."""

    async def _fetch() -> None:
        episode_id = typ.cast("uuid.UUID", context["episode_id"])

        factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
        async with SqlAlchemyUnitOfWork(factory) as uow:
            episode = await uow.episodes.get(episode_id)

        assert episode is not None
        assert episode.title == "Bridgewater"

    _function_scoped_runner.run(_fetch())


@then('the approval state is "draft"')
def approval_state_is_draft(
    _function_scoped_runner: asyncio.Runner,
    session_factory: object,
    context: dict[str, typ.Any],
) -> None:
    """Verify the episode approval state is draft."""

    async def _fetch() -> None:
        episode_id = typ.cast("uuid.UUID", context["episode_id"])

        factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
        async with SqlAlchemyUnitOfWork(factory) as uow:
            episode = await uow.episodes.get(episode_id)

        assert episode is not None
        assert episode.approval_state is ApprovalState.DRAFT

    _function_scoped_runner.run(_fetch())
