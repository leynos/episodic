"""Shared helpers for asyncio task-factory propagation tests."""

import asyncio
import contextlib
import datetime as dt
import typing as typ
import uuid

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    IngestionRequest,
    SeriesProfile,
    SourceDocumentInput,
)
from episodic.canonical.ingestion import (
    ConflictOutcome,
    NormalizedSource,
    RawSourceInput,
    WeightingResult,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import contextvars as cv


class TaskConstructorKwargs(typ.TypedDict):
    """Kwargs accepted by `asyncio.Task` for the recording test factory."""

    name: str | None
    context: cv.Context | None
    eager_start: bool


def extract_task_constructor_kwargs(
    task_kwargs: dict[str, object],
) -> TaskConstructorKwargs:
    """Return kwargs accepted by `asyncio.Task` constructor."""
    eager_start = typ.cast("bool | None", task_kwargs.get("eager_start", False))
    return {
        "name": typ.cast("str | None", task_kwargs.get("name")),
        "context": typ.cast("cv.Context | None", task_kwargs.get("context")),
        "eager_start": eager_start if eager_start is not None else False,
    }


@contextlib.contextmanager
def recording_task_factory() -> typ.Iterator[list[dict[str, object]]]:
    """Install a task factory that records kwargs for every created task."""
    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    captured: list[dict[str, object]] = []

    def _factory(
        running_loop: asyncio.AbstractEventLoop,
        coro: cabc.Coroutine[object, object, object],
        **task_kwargs: object,
    ) -> asyncio.Task[object]:
        task_kwargs_dict = dict(task_kwargs)
        captured.append(task_kwargs_dict)
        return asyncio.Task(
            coro,
            loop=running_loop,
            **extract_task_constructor_kwargs(task_kwargs_dict),
        )

    loop.set_task_factory(_factory)
    try:
        yield captured
    finally:
        loop.set_task_factory(previous_factory)


def select_captured_task_kwargs(
    captured_task_kwargs: list[dict[str, object]],
    expected_name: str,
) -> dict[str, object]:
    """Return captured kwargs for a task name, tolerating extra loop tasks."""
    matching = [
        kwargs for kwargs in captured_task_kwargs if kwargs.get("name") == expected_name
    ]
    captured_names = [kwargs.get("name") for kwargs in captured_task_kwargs]
    if not matching:
        msg = (
            f"Expected a captured task named {expected_name!r}; "
            f"captured names were {captured_names!r}."
        )
        raise AssertionError(msg)
    return matching[-1]


def make_profile(slug: str = "series-slug") -> SeriesProfile:
    """Return a minimal series profile for orchestration tests."""
    now = dt.datetime.now(dt.UTC)
    return SeriesProfile(
        id=uuid.uuid4(),
        slug=slug,
        title="Series",
        description=None,
        configuration={"tone": "neutral"},
        guardrails={},
        created_at=now,
        updated_at=now,
    )


def make_normalized_source(raw: RawSourceInput) -> NormalizedSource:
    """Create a deterministic normalized source from raw input."""
    return NormalizedSource(
        source_input=SourceDocumentInput(
            source_type=raw.source_type,
            source_uri=raw.source_uri,
            weight=0.0,
            content_hash=raw.content_hash,
            metadata=raw.metadata,
        ),
        title=typ.cast("str", raw.metadata.get("title", "Untitled")),
        tei_fragment=f"<div>{raw.content}</div>",
        quality_score=0.8,
        freshness_score=0.7,
        reliability_score=0.6,
    )


def make_episode(series_profile_id: uuid.UUID) -> CanonicalEpisode:
    """Create a canonical episode for ingestion-service stubbing."""
    now = dt.datetime.now(dt.UTC)
    return CanonicalEpisode(
        id=uuid.uuid4(),
        series_profile_id=series_profile_id,
        tei_header_id=uuid.uuid4(),
        title="Merged title",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )


class TestNormalizer:
    """Normalize raw sources deterministically for this test."""

    @staticmethod
    async def normalize(raw_source: RawSourceInput) -> NormalizedSource:
        """Normalize one raw source with deterministic scores."""
        await asyncio.sleep(0)
        return make_normalized_source(raw_source)


class TestWeighting:
    """Return deterministic weights in source input order."""

    @staticmethod
    async def compute_weights(
        sources: list[NormalizedSource],
        series_configuration: dict[str, object],
    ) -> list[WeightingResult]:
        """Compute deterministic weights for normalized sources."""
        _ = series_configuration
        return [
            WeightingResult(
                source=source,
                computed_weight=max(0.1, 1.0 - (index * 0.1)),
                factors={"quality_score": source.quality_score},
            )
            for index, source in enumerate(sources)
        ]


class TestResolver:
    """Mark the first source as preferred and retain the rest."""

    @staticmethod
    async def resolve(
        weighted_sources: list[WeightingResult],
    ) -> ConflictOutcome:
        """Resolve weighted sources by selecting the first as preferred."""
        return ConflictOutcome(
            merged_tei_xml="<TEI/>",
            merged_title="Merged title",
            preferred_sources=weighted_sources[:1],
            rejected_sources=weighted_sources[1:],
            resolution_notes="Preferred first source by deterministic order.",
        )


def make_fake_ingest_sources(
    profile_id: uuid.UUID,
    captured_sources: list[SourceDocumentInput],
) -> cabc.Callable[
    [object, SeriesProfile, IngestionRequest], cabc.Awaitable[CanonicalEpisode]
]:
    """Create a fake ingest function that records persisted sources."""

    async def _fake_ingest_sources(
        uow: object,
        series_profile: SeriesProfile,
        request: IngestionRequest,
    ) -> CanonicalEpisode:
        await asyncio.sleep(0)
        _ = (uow, series_profile)
        captured_sources.extend(request.sources)
        return make_episode(profile_id)

    return _fake_ingest_sources
