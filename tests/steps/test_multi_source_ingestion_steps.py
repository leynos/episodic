"""Behavioural tests for multi-source ingestion workflows.

Examples
--------
Run the multi-source ingestion BDD scenarios:

>>> pytest tests/steps/test_multi_source_ingestion_steps.py -v
"""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
from pytest_bdd import given, parsers, scenario, then, when

from episodic.canonical.adapters.normaliser import InMemorySourceNormaliser
from episodic.canonical.adapters.resolver import HighestWeightConflictResolver
from episodic.canonical.adapters.weighting import DefaultWeightingStrategy
from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    SeriesProfile,
)
from episodic.canonical.ingestion import MultiSourceRequest, RawSourceInput
from episodic.canonical.ingestion_service import (
    IngestionPipeline,
    ingest_multi_source,
)
from episodic.canonical.storage import (
    IngestionJobRecord,
    SqlAlchemyUnitOfWork,
)

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession


def _run_async_step(
    runner: asyncio.Runner,
    step_fn: cabc.Callable[[], typ.Awaitable[None]],
) -> None:
    """Execute an async BDD step via the provided runner."""
    coro = typ.cast("typ.Coroutine[object, object, None]", step_fn())
    runner.run(coro)


class MultiSourceContext(typ.TypedDict, total=False):
    """Shared state for multi-source ingestion BDD steps."""

    profile: SeriesProfile
    raw_sources: list[RawSourceInput]
    episode: CanonicalEpisode
    episode_id: uuid.UUID
    ingestion_job_id: uuid.UUID


def _add_raw_source(
    multi_source_context: MultiSourceContext,
    source: RawSourceInput,
    *,
    replace: bool = False,
) -> None:
    """Append (or replace) a raw source in the shared context.

    Parameters
    ----------
    multi_source_context : MultiSourceContext
        Shared BDD step state dictionary.
    source : RawSourceInput
        Pre-constructed raw source to register.
    replace : bool
        When ``True``, discard any previously registered sources and
        start a fresh list containing only *source*.
    """
    if replace:
        multi_source_context["raw_sources"] = [source]
    else:
        sources = multi_source_context.get("raw_sources", [])
        sources.append(source)
        multi_source_context["raw_sources"] = sources


@scenario(
    "../features/multi_source_ingestion.feature",
    "Ingestion normalizes and merges multiple sources",
)
def test_multi_source_ingestion() -> None:
    """Run the multi-source ingestion scenario."""


@scenario(
    "../features/multi_source_ingestion.feature",
    "Single source ingestion requires no conflict resolution",
)
def test_single_source_ingestion() -> None:
    """Run the single-source ingestion scenario."""


@pytest.fixture
def multi_source_context() -> MultiSourceContext:
    """Share state between multi-source BDD steps."""
    return typ.cast("MultiSourceContext", {})


@given(
    parsers.re(
        r'a series profile "(?P<slug>[^"]+)" '
        r"exists for multi-source ingestion"
    ),
    converters={"slug": str},
)
def series_profile_exists_for_multi_source(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    multi_source_context: MultiSourceContext,
    slug: str,
) -> None:
    """Persist a series profile for multi-source ingestion."""

    async def _store_profile() -> None:
        now = dt.datetime.now(dt.UTC)
        profile = SeriesProfile(
            id=uuid.uuid4(),
            slug=slug,
            title=slug.replace("-", " ").title(),
            description=None,
            configuration={"tone": "informative"},
            created_at=now,
            updated_at=now,
        )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.series_profiles.add(profile)
            await uow.commit()

        multi_source_context["profile"] = profile

    _run_async_step(_function_scoped_runner, _store_profile)


@given("a transcript source is available for multi-source ingestion")
def transcript_source_available(
    multi_source_context: MultiSourceContext,
) -> None:
    """Provide a transcript raw source."""
    source = RawSourceInput(
        source_type="transcript",
        source_uri="s3://bucket/transcript.txt",
        content="Full episode transcript content",
        content_hash="hash-transcript",
        metadata={"title": "Episode Transcript"},
    )
    _add_raw_source(multi_source_context, source)


@given("a brief source is available for multi-source ingestion")
def brief_source_available(
    multi_source_context: MultiSourceContext,
) -> None:
    """Provide a brief raw source."""
    source = RawSourceInput(
        source_type="brief",
        source_uri="s3://bucket/brief.txt",
        content="Background briefing material",
        content_hash="hash-brief",
        metadata={"title": "Episode Brief"},
    )
    _add_raw_source(multi_source_context, source)


@given(
    "a single transcript source is available for multi-source ingestion",
)
def single_transcript_source_available(
    multi_source_context: MultiSourceContext,
) -> None:
    """Provide a single transcript raw source."""
    source = RawSourceInput(
        source_type="transcript",
        source_uri="s3://bucket/solo-transcript.txt",
        content="Solo episode transcript",
        content_hash="hash-solo",
        metadata={"title": "Solo Transcript"},
    )
    _add_raw_source(multi_source_context, source, replace=True)


@when("multi-source ingestion processes the sources")
def multi_source_ingestion_processes(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    multi_source_context: MultiSourceContext,
) -> None:
    """Run multi-source ingestion with the reference adapters."""

    async def _ingest() -> None:
        profile = multi_source_context["profile"]
        raw_sources = multi_source_context["raw_sources"]
        pipeline = IngestionPipeline(
            normaliser=InMemorySourceNormaliser(),
            weighting=DefaultWeightingStrategy(),
            resolver=HighestWeightConflictResolver(),
        )
        request = MultiSourceRequest(
            raw_sources=raw_sources,
            series_slug=profile.slug,
            requested_by="bdd-test@example.com",
        )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            episode = await ingest_multi_source(
                uow,
                profile,
                request,
                pipeline,
            )
            # Query job while UoW is still open.
            session = uow._session
            assert session is not None, (
                "Expected an active session while unit of work is open."
            )
            result = await session.execute(
                sa.select(IngestionJobRecord).where(
                    IngestionJobRecord.target_episode_id == episode.id,
                ),
            )
            job_record = result.scalar_one()

        multi_source_context["episode"] = episode
        multi_source_context["episode_id"] = episode.id
        multi_source_context["ingestion_job_id"] = job_record.id

    _run_async_step(_function_scoped_runner, _ingest)


@then(parsers.re(r'a canonical episode is created for "(?P<slug>[^"]+)"'))
def canonical_episode_created(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    multi_source_context: MultiSourceContext,
    slug: str,
) -> None:
    """Verify the canonical episode was persisted."""

    async def _verify() -> None:
        episode_id = multi_source_context["episode_id"]
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            episode = await uow.episodes.get(episode_id)

        assert episode is not None, "Expected a persisted canonical episode."
        assert episode.approval_state is ApprovalState.DRAFT, (
            "Expected the episode approval state to be draft."
        )

    _run_async_step(_function_scoped_runner, _verify)


@then("source documents are persisted with computed weights")
def source_documents_persisted_with_weights(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    multi_source_context: MultiSourceContext,
) -> None:
    """Verify source documents have non-zero computed weights."""

    async def _verify() -> None:
        job_id = multi_source_context["ingestion_job_id"]
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            documents = await uow.source_documents.list_for_job(job_id)

        assert len(documents) >= 2, "Expected at least two source documents."
        for doc in documents:
            assert doc.weight > 0.0, "Expected computed weight to be non-zero."
            assert doc.weight <= 1.0, "Expected computed weight within [0, 1]."

    _run_async_step(_function_scoped_runner, _verify)


@then(
    "conflict resolution metadata is recorded in the approval event",
)
def conflict_resolution_metadata_recorded(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    multi_source_context: MultiSourceContext,
) -> None:
    """Verify the approval event records source provenance."""

    async def _verify() -> None:
        episode_id = multi_source_context["episode_id"]
        job_id = multi_source_context["ingestion_job_id"]
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            events = await uow.approval_events.list_for_episode(
                episode_id,
            )

        assert events, "Expected approval events for the episode."
        event = events[0]
        assert event.to_state is ApprovalState.DRAFT, (
            "Expected initial approval state to be draft."
        )
        assert isinstance(event.payload, dict), "Expected a payload dictionary."
        assert "sources" in event.payload, (
            "Expected source URIs in the approval payload."
        )

        # Conflict-resolution metadata should be embedded in each
        # source document's metadata.
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            documents = await uow.source_documents.list_for_job(job_id)

        for idx, doc in enumerate(documents):
            assert "conflict_resolution" in doc.metadata, (
                f"Expected conflict_resolution in source document "
                f"metadata for doc index={idx} id={doc.id}."
            )
            cr = typ.cast("dict[str, object]", doc.metadata["conflict_resolution"])
            assert "preferred_sources" in cr, (
                f"Expected preferred_sources in conflict_resolution "
                f"metadata for doc index={idx} id={doc.id}."
            )
            assert "rejected_sources" in cr, (
                f"Expected rejected_sources in conflict_resolution "
                f"metadata for doc index={idx} id={doc.id}."
            )
            assert "resolution_notes" in cr, (
                f"Expected resolution_notes in conflict_resolution "
                f"metadata for doc index={idx} id={doc.id}."
            )

    _run_async_step(_function_scoped_runner, _verify)


@then("the single source is marked as preferred")
def single_source_marked_as_preferred(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    multi_source_context: MultiSourceContext,
) -> None:
    """Verify a single source is persisted as the sole document."""

    async def _verify() -> None:
        job_id = multi_source_context["ingestion_job_id"]
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            documents = await uow.source_documents.list_for_job(job_id)

        assert len(documents) == 1, "Expected exactly one source document."
        assert documents[0].weight > 0.0, (
            "Expected the single source to have a non-zero weight."
        )

    _run_async_step(_function_scoped_runner, _verify)


@then("TEI header provenance captures source priorities")
def tei_header_provenance_captures_priorities(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    multi_source_context: MultiSourceContext,
) -> None:
    """Verify TEI header provenance captures source-priority ordering."""

    async def _verify() -> None:
        episode_id = multi_source_context["episode_id"]

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            episode = await uow.episodes.get(episode_id)
            assert episode is not None, "Expected a persisted canonical episode."
            header = await uow.tei_headers.get(episode.tei_header_id)

        assert header is not None, "Expected TEI header for canonical episode."
        provenance = header.payload.get("episodic_provenance")
        assert isinstance(provenance, dict), (
            "Expected TEI header to include provenance metadata."
        )
        provenance_dict = typ.cast("dict[str, object]", provenance)
        assert provenance_dict.get("capture_context") == "source_ingestion", (
            "Expected ingestion capture context in TEI provenance."
        )
        assert provenance_dict.get("reviewer_identities") == ["bdd-test@example.com"], (
            "Expected ingestion actor identity in provenance metadata."
        )
        priorities = provenance_dict.get("source_priorities")
        assert isinstance(priorities, list), (
            "Expected list of source priorities in TEI provenance."
        )
        priority_items = typ.cast("list[dict[str, object]]", priorities)
        assert priorities, "Expected at least one source priority entry."

        if len(priorities) > 1:
            assert priority_items[0]["source_uri"] == "s3://bucket/transcript.txt", (
                "Expected transcript source to rank highest in default weighting."
            )

    _run_async_step(_function_scoped_runner, _verify)
