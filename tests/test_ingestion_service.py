"""Unit tests for the multi-source ingestion service.

Examples
--------
Run the multi-source ingestion tests:

>>> pytest tests/test_ingestion_service.py -v
"""

from __future__ import annotations

import typing as typ
import uuid

import pytest
import pytest_asyncio

from episodic.canonical.adapters.normaliser import InMemorySourceNormaliser
from episodic.canonical.adapters.resolver import HighestWeightConflictResolver
from episodic.canonical.adapters.weighting import DefaultWeightingStrategy
from episodic.canonical.domain import SeriesProfile
from episodic.canonical.ingestion import (
    MultiSourceRequest,
    NormalisedSource,
    RawSourceInput,
    WeightingResult,
)
from episodic.canonical.ingestion_service import (
    IngestionPipeline,
    ingest_multi_source,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.tei import parse_tei_header

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.storage import IngestionJobRecord


def _make_raw_source(**kwargs: object) -> RawSourceInput:
    """Build a raw source input for testing with sensible defaults."""
    defaults: dict[str, object] = {
        "source_type": "transcript",
        "source_uri": "s3://bucket/transcript.txt",
        "content": "Episode transcript content",
        "content_hash": "hash-abc",
        "metadata": {},
    }
    merged = defaults | kwargs
    # merged is dict[str, object]; RawSourceInput expects explicit keyword
    # types.  The values are correct at runtime — the dict just has a wider
    # value type than the constructor signature declares.
    return RawSourceInput(**merged)  # type: ignore[arg-type]


def _make_normalised_source(
    title: str = "Test Title",
    quality: float = 0.8,
    freshness: float = 0.7,
    reliability: float = 0.6,
) -> NormalisedSource:
    """Build a normalised source for testing."""
    import tei_rapporteur as _tei

    from episodic.canonical.domain import SourceDocumentInput

    tei_fragment = _tei.emit_xml(_tei.Document(title))
    return NormalisedSource(
        source_input=SourceDocumentInput(
            source_type="transcript",
            source_uri="s3://bucket/test.txt",
            weight=0.0,
            content_hash="hash-test",
            metadata={},
        ),
        title=title,
        tei_fragment=tei_fragment,
        quality_score=quality,
        freshness_score=freshness,
        reliability_score=reliability,
    )


def _make_weighting_result(
    title: str = "Test Title",
    weight: float = 0.8,
    scores: dict[str, float] | None = None,
) -> WeightingResult:
    """Build a weighting result for testing."""
    resolved = scores or {}
    quality = resolved.get("quality", 0.8)
    freshness = resolved.get("freshness", 0.7)
    reliability = resolved.get("reliability", 0.6)
    source = _make_normalised_source(title, quality, freshness, reliability)
    return WeightingResult(
        source=source,
        computed_weight=weight,
        factors={
            "quality_score": quality,
            "freshness_score": freshness,
            "reliability_score": reliability,
        },
    )


async def _get_job_record_for_episode(
    session_factory: cabc.Callable[[], AsyncSession],
    episode_id: uuid.UUID,
) -> IngestionJobRecord:
    """Look up the ingestion job record targeting *episode_id*."""
    import sqlalchemy as sa

    from episodic.canonical.storage import IngestionJobRecord

    async with session_factory() as session:
        result = await session.execute(
            sa.select(IngestionJobRecord).where(
                IngestionJobRecord.target_episode_id == episode_id,
            ),
        )
        return result.scalar_one()


@pytest_asyncio.fixture
async def series_profile_for_ingestion(
    session_factory: typ.Callable[[], AsyncSession],
) -> SeriesProfile:
    """Create and persist a series profile for integration tests."""
    import datetime as dt

    now = dt.datetime.now(dt.UTC)
    profile = SeriesProfile(
        id=uuid.uuid4(),
        slug=f"test-series-{uuid.uuid4().hex[:8]}",
        title="Test Series",
        description=None,
        configuration={"tone": "neutral"},
        created_at=now,
        updated_at=now,
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.series_profiles.add(profile)
        await uow.commit()
    return profile


# -- Normaliser tests --


@pytest.mark.asyncio
async def test_normaliser_produces_valid_tei_fragment() -> None:
    """The normaliser produces a NormalisedSource with parseable TEI XML."""
    normaliser = InMemorySourceNormaliser()
    raw = _make_raw_source(
        source_type="transcript",
        content="Transcript content here",
        metadata={"title": "My Transcript"},
    )

    result = await normaliser.normalise(raw)

    # TEI fragment should be parseable.
    parsed = parse_tei_header(result.tei_fragment)
    assert parsed.title == "My Transcript", (
        "Expected parsed TEI title to match metadata title."
    )

    # Scores should match transcript defaults.
    assert result.quality_score == pytest.approx(0.9), (
        "Expected transcript quality score to use transcript defaults."
    )
    assert result.freshness_score == pytest.approx(0.8), (
        "Expected transcript freshness score to use transcript defaults."
    )
    assert result.reliability_score == pytest.approx(0.9), (
        "Expected transcript reliability score to use transcript defaults."
    )

    # Source input should carry through metadata.
    assert result.source_input.source_type == "transcript", (
        "Expected source type to be preserved from raw input."
    )
    assert result.source_input.source_uri == raw.source_uri, (
        "Expected source URI to be preserved from raw input."
    )


@pytest.mark.asyncio
async def test_normaliser_unknown_source_type_uses_defaults() -> None:
    """An unknown source type gets mid-range fallback scores."""
    normaliser = InMemorySourceNormaliser()
    raw = _make_raw_source(source_type="unknown_format")

    result = await normaliser.normalise(raw)

    assert result.quality_score == pytest.approx(0.5), (
        "Expected unknown source types to fall back to default quality."
    )
    assert result.freshness_score == pytest.approx(0.5), (
        "Expected unknown source types to fall back to default freshness."
    )
    assert result.reliability_score == pytest.approx(0.5), (
        "Expected unknown source types to fall back to default reliability."
    )


@pytest.mark.asyncio
async def test_normaliser_infers_title_from_content() -> None:
    """Without a metadata title, the first content line is used."""
    normaliser = InMemorySourceNormaliser()
    raw = _make_raw_source(
        content="First line of content\nSecond line",
        metadata={},
    )

    result = await normaliser.normalise(raw)

    assert result.title == "First line of content", (
        "Expected title to be inferred from the first content line."
    )


@pytest.mark.asyncio
async def test_normaliser_infers_title_from_source_type() -> None:
    """With no metadata title and empty content, source_type is used."""
    normaliser = InMemorySourceNormaliser()
    raw = _make_raw_source(
        source_type="press_release",
        content="",
        metadata={},
    )

    result = await normaliser.normalise(raw)

    assert result.title == "Press Release", (
        "Expected title fallback to convert source type into title case."
    )


# -- Weighting strategy tests --


@pytest.mark.asyncio
async def test_weighting_strategy_computes_weighted_average() -> None:
    """The strategy computes weights as a weighted average with defaults."""
    strategy = DefaultWeightingStrategy()
    source = _make_normalised_source(
        quality=0.9,
        freshness=0.8,
        reliability=0.9,
    )

    results = await strategy.compute_weights([source], {})

    assert len(results) == 1, "Expected one weighting result for one input source."
    # Default: 0.9*0.5 + 0.8*0.3 + 0.9*0.2 = 0.45 + 0.24 + 0.18 = 0.87
    assert results[0].computed_weight == pytest.approx(0.87), (
        "Expected weighted average to use default coefficients."
    )
    assert "quality_coefficient" in results[0].factors, (
        "Expected factor breakdown to include quality coefficient."
    )
    assert results[0].factors["quality_coefficient"] == pytest.approx(0.5), (
        "Expected default quality coefficient to be recorded."
    )


@pytest.mark.asyncio
async def test_weighting_strategy_respects_series_configuration() -> None:
    """Custom coefficients from series configuration are used."""
    strategy = DefaultWeightingStrategy()
    source = _make_normalised_source(
        quality=1.0,
        freshness=0.0,
        reliability=0.0,
    )
    config = {
        "weighting": {
            "quality_coefficient": 1.0,
            "freshness_coefficient": 0.0,
            "reliability_coefficient": 0.0,
        },
    }

    results = await strategy.compute_weights([source], config)

    # 1.0*1.0 + 0.0*0.0 + 0.0*0.0 = 1.0
    assert results[0].computed_weight == pytest.approx(1.0), (
        "Expected custom coefficients in configuration to drive weighting."
    )


@pytest.mark.asyncio
async def test_weighting_strategy_clamps_to_unit_interval() -> None:
    """Weights are clamped to [0, 1] even with extreme scores."""
    strategy = DefaultWeightingStrategy()
    # Scores above 1.0 should be clamped.
    source = _make_normalised_source(
        quality=2.0,
        freshness=2.0,
        reliability=2.0,
    )

    results = await strategy.compute_weights([source], {})

    assert results[0].computed_weight <= 1.0, (
        "Expected computed weights to be clamped to the upper bound."
    )
    assert results[0].computed_weight >= 0.0, (
        "Expected computed weights to be clamped to the lower bound."
    )


# -- Conflict resolver tests --


@pytest.mark.asyncio
async def test_conflict_resolver_selects_highest_weight() -> None:
    """The resolver selects the highest-weighted source as preferred."""
    resolver = HighestWeightConflictResolver()
    high = _make_weighting_result(title="High Priority", weight=0.9)
    low = _make_weighting_result(title="Low Priority", weight=0.3)

    outcome = await resolver.resolve([low, high])

    assert len(outcome.preferred_sources) == 1, "Expected exactly one preferred source."
    assert outcome.preferred_sources[0].source.title == "High Priority", (
        "Expected highest-weight source to be preferred."
    )
    assert len(outcome.rejected_sources) == 1, (
        "Expected non-winning source to be rejected."
    )
    assert outcome.rejected_sources[0].source.title == "Low Priority", (
        "Expected lower-weight source to be rejected."
    )
    assert outcome.merged_title == "High Priority", (
        "Expected merged title to come from the preferred source."
    )


@pytest.mark.asyncio
async def test_conflict_resolver_single_source_no_conflict() -> None:
    """A single source is selected with no rejections."""
    resolver = HighestWeightConflictResolver()
    single = _make_weighting_result(title="Only Source", weight=0.8)

    outcome = await resolver.resolve([single])

    assert len(outcome.preferred_sources) == 1, (
        "Expected single-source input to yield one preferred source."
    )
    assert outcome.preferred_sources[0].source.title == "Only Source", (
        "Expected only source to be selected as preferred."
    )
    assert len(outcome.rejected_sources) == 0, (
        "Expected no rejected sources for single-source input."
    )


@pytest.mark.asyncio
async def test_conflict_resolver_records_resolution_notes() -> None:
    """The resolver produces human-readable resolution notes."""
    resolver = HighestWeightConflictResolver()
    high = _make_weighting_result(title="Winner", weight=0.9)
    low = _make_weighting_result(title="Loser", weight=0.3)

    outcome = await resolver.resolve([high, low])

    assert "Winner" in outcome.resolution_notes, (
        "Expected resolution notes to mention the winning source."
    )
    assert "selected as canonical" in outcome.resolution_notes, (
        "Expected resolution notes to include canonical-selection language."
    )
    assert "Loser" in outcome.resolution_notes, (
        "Expected resolution notes to mention the rejected source."
    )
    assert "rejected" in outcome.resolution_notes, (
        "Expected resolution notes to describe rejection."
    )


# -- Integration tests --


@pytest.mark.asyncio
async def test_ingest_multi_source_end_to_end(
    session_factory: typ.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
) -> None:
    """End-to-end integration test for multi-source ingestion."""
    profile = series_profile_for_ingestion
    pipeline = IngestionPipeline(
        normaliser=InMemorySourceNormaliser(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )

    request = MultiSourceRequest(
        raw_sources=[
            _make_raw_source(
                source_type="transcript",
                source_uri="s3://bucket/transcript.txt",
                content="Primary transcript",
                content_hash="hash-primary",
                metadata={"title": "Primary Episode"},
            ),
            _make_raw_source(
                source_type="brief",
                source_uri="s3://bucket/brief.txt",
                content="Background brief",
                content_hash="hash-brief",
                metadata={"title": "Brief Notes"},
            ),
        ],
        series_slug=profile.slug,
        requested_by="producer@example.com",
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        episode = await ingest_multi_source(
            uow,
            profile,
            request,
            pipeline,
        )

    # Episode should be persisted.
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        persisted = await uow.episodes.get(episode.id)

    assert persisted is not None, (
        "Expected persisted episode to be retrievable after ingestion."
    )
    assert persisted.title == "Primary Episode", (
        "Expected winning source title to persist as canonical episode title."
    )

    # Find the ingestion job via a plain session query.
    job_record = await _get_job_record_for_episode(
        session_factory,
        episode.id,
    )

    # Source documents should be persisted with computed weights.
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        documents = await uow.source_documents.list_for_job(job_record.id)

    assert len(documents) == 2, (
        "Expected all input sources to be persisted as source documents."
    )
    # Weights should be computed, not zero placeholders.
    for doc in documents:
        assert doc.weight > 0.0, (
            "Expected persisted source weight to be greater than zero."
        )
        assert doc.weight <= 1.0, (
            "Expected persisted source weight to be capped at one."
        )


@pytest.mark.asyncio
async def test_ingest_multi_source_preserves_all_sources(
    session_factory: typ.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
) -> None:
    """All sources are persisted, even those rejected in conflict resolution."""
    profile = series_profile_for_ingestion
    pipeline = IngestionPipeline(
        normaliser=InMemorySourceNormaliser(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )

    source_uris = [
        "s3://bucket/source-1.txt",
        "s3://bucket/source-2.txt",
        "s3://bucket/source-3.txt",
    ]
    request = MultiSourceRequest(
        raw_sources=[
            _make_raw_source(
                source_type="transcript",
                source_uri=source_uris[0],
                content="Source one",
                content_hash="hash-1",
                metadata={"title": "Source One"},
            ),
            _make_raw_source(
                source_type="brief",
                source_uri=source_uris[1],
                content="Source two",
                content_hash="hash-2",
                metadata={"title": "Source Two"},
            ),
            _make_raw_source(
                source_type="rss",
                source_uri=source_uris[2],
                content="Source three",
                content_hash="hash-3",
                metadata={"title": "Source Three"},
            ),
        ],
        series_slug=profile.slug,
        requested_by="test@example.com",
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        episode = await ingest_multi_source(
            uow,
            profile,
            request,
            pipeline,
        )

    # Find the ingestion job via a plain session query.
    job_record = await _get_job_record_for_episode(
        session_factory,
        episode.id,
    )

    # All three sources should be persisted, not just the winner.
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        documents = await uow.source_documents.list_for_job(job_record.id)

    assert len(documents) == 3, "Expected all three sources to be persisted."
    persisted_uris = {doc.source_uri for doc in documents}
    assert persisted_uris == set(source_uris), (
        "Expected persisted source URIs to match all input URIs."
    )


@pytest.mark.asyncio
async def test_ingest_multi_source_empty_sources_raises(
    session_factory: typ.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
) -> None:
    """Submitting zero raw sources raises ValueError."""
    profile = series_profile_for_ingestion
    pipeline = IngestionPipeline(
        normaliser=InMemorySourceNormaliser(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )

    request = MultiSourceRequest(
        raw_sources=[],
        series_slug=profile.slug,
        requested_by="test@example.com",
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ValueError, match="At least one raw source"):
            await ingest_multi_source(
                uow,
                profile,
                request,
                pipeline,
            )


@pytest.mark.asyncio
async def test_ingest_multi_source_slug_mismatch_raises(
    session_factory: typ.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
) -> None:
    """Mismatched series slug raises ValueError."""
    profile = series_profile_for_ingestion
    pipeline = IngestionPipeline(
        normaliser=InMemorySourceNormaliser(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )

    request = MultiSourceRequest(
        raw_sources=[_make_raw_source()],
        series_slug="wrong-slug",
        requested_by="test@example.com",
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        with pytest.raises(ValueError, match="Series slug mismatch"):
            await ingest_multi_source(
                uow,
                profile,
                request,
                pipeline,
            )


@pytest.mark.asyncio
async def test_ingest_multi_source_records_conflict_metadata(
    session_factory: typ.Callable[[], AsyncSession],
    series_profile_for_ingestion: SeriesProfile,
) -> None:
    """Conflict-resolution metadata is recorded in source document metadata."""
    profile = series_profile_for_ingestion
    pipeline = IngestionPipeline(
        normaliser=InMemorySourceNormaliser(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )

    request = MultiSourceRequest(
        raw_sources=[
            _make_raw_source(
                source_type="transcript",
                source_uri="s3://bucket/winner.txt",
                content="Winner content",
                content_hash="hash-winner",
                metadata={"title": "Winner"},
            ),
            _make_raw_source(
                source_type="rss",
                source_uri="s3://bucket/loser.txt",
                content="Loser content",
                content_hash="hash-loser",
                metadata={"title": "Loser"},
            ),
        ],
        series_slug=profile.slug,
        requested_by="test@example.com",
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        episode = await ingest_multi_source(
            uow,
            profile,
            request,
            pipeline,
        )

    job_record = await _get_job_record_for_episode(
        session_factory,
        episode.id,
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        documents = await uow.source_documents.list_for_job(job_record.id)

    for doc in documents:
        assert "conflict_resolution" in doc.metadata, (
            "Expected conflict-resolution metadata to be attached to each source."
        )
        cr = doc.metadata["conflict_resolution"]
        assert "preferred_sources" in cr, (
            "Expected conflict metadata to include preferred sources."
        )
        assert "rejected_sources" in cr, (
            "Expected conflict metadata to include rejected sources."
        )
        assert "resolution_notes" in cr, (
            "Expected conflict metadata to include resolver notes."
        )
