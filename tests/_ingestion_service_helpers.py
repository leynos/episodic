"""Shared helpers and fixtures for ingestion service tests."""

import typing as typ

from episodic.canonical.ingestion import (
    NormalizedSource,
    RawSourceInput,
    WeightingResult,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.storage import IngestionJobRecord


class RawSourceInputOverrides(typ.TypedDict, total=False):
    """Optional overrides accepted by `_make_raw_source`."""

    source_type: str
    source_uri: str
    content: str
    content_hash: str
    metadata: dict[str, object]


class RawSourceInputDict(typ.TypedDict):
    """Fully-resolved dictionary shape for `RawSourceInput` construction."""

    source_type: str
    source_uri: str
    content: str
    content_hash: str
    metadata: dict[str, object]


def _make_raw_source(**kwargs: typ.Unpack[RawSourceInputOverrides]) -> RawSourceInput:
    """Build a raw source input for testing with sensible defaults."""
    allowed_keys = {"source_type", "source_uri", "content", "content_hash", "metadata"}
    unknown_keys = set(kwargs) - allowed_keys
    if unknown_keys:
        msg = f"Invalid override keys: {sorted(unknown_keys)}"
        raise ValueError(msg)
    defaults: RawSourceInputDict = {
        "source_type": "transcript",
        "source_uri": "s3://bucket/transcript.txt",
        "content": "Episode transcript content",
        "content_hash": "hash-abc",
        "metadata": {},
    }
    merged: RawSourceInputDict = defaults.copy()
    if "source_type" in kwargs:
        merged["source_type"] = kwargs["source_type"]
    if "source_uri" in kwargs:
        merged["source_uri"] = kwargs["source_uri"]
    if "content" in kwargs:
        merged["content"] = kwargs["content"]
    if "content_hash" in kwargs:
        merged["content_hash"] = kwargs["content_hash"]
    if "metadata" in kwargs:
        merged["metadata"] = kwargs["metadata"]
    return RawSourceInput(**merged)


def _make_normalized_source(
    title: str = "Test Title",
    quality: float = 0.8,
    freshness: float = 0.7,
    reliability: float = 0.6,
) -> NormalizedSource:
    """Build a normalized source for testing."""
    import tei_rapporteur as _tei

    from episodic.canonical.domain import SourceDocumentInput

    tei_fragment = _tei.emit_xml(_tei.Document(title))
    return NormalizedSource(
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
    source = _make_normalized_source(title, quality, freshness, reliability)
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
    episode_id: UUID,
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
