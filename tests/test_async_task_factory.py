"""Tests for asyncio task-factory keyword propagation utilities."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars as cv
import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.asyncio_tasks import (
    TASK_METADATA_KWARG,
    TaskMetadata,
    create_task,
    create_task_in_group,
)
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
    MultiSourceRequest,
    NormalizedSource,
    RawSourceInput,
    WeightingResult,
)
from episodic.canonical.ingestion_service import (
    IngestionPipeline,
    ingest_multi_source,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork


class _TaskConstructorKwargs(typ.TypedDict):
    """Kwargs accepted by `asyncio.Task` for the recording test factory."""

    name: str | None
    context: cv.Context | None
    eager_start: bool


def _extract_task_constructor_kwargs(
    task_kwargs: dict[str, object],
) -> _TaskConstructorKwargs:
    """Return kwargs accepted by `asyncio.Task` constructor."""
    eager_start = typ.cast("bool | None", task_kwargs.get("eager_start", False))
    return {
        "name": typ.cast("str | None", task_kwargs.get("name")),
        "context": typ.cast("cv.Context | None", task_kwargs.get("context")),
        "eager_start": eager_start if eager_start is not None else False,
    }


@contextlib.contextmanager
def _recording_task_factory() -> typ.Iterator[list[dict[str, object]]]:
    """Install a task factory that records kwargs for every created task."""
    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    captured: list[dict[str, object]] = []

    def _factory(
        running_loop: asyncio.AbstractEventLoop,
        coro: typ.Coroutine[object, object, object],
        **task_kwargs: object,
    ) -> asyncio.Task[object]:
        task_kwargs_dict = dict(task_kwargs)
        captured.append(task_kwargs_dict)
        return asyncio.Task(
            coro,
            loop=running_loop,
            **_extract_task_constructor_kwargs(task_kwargs_dict),
        )

    loop.set_task_factory(_factory)
    try:
        yield captured
    finally:
        loop.set_task_factory(previous_factory)


def _select_captured_task_kwargs(
    captured_task_kwargs: list[dict[str, object]],
    expected_name: str,
) -> dict[str, object]:
    """Return captured kwargs for a task name, tolerating extra loop tasks."""
    matching = [
        kwargs for kwargs in captured_task_kwargs if kwargs.get("name") == expected_name
    ]
    captured_names = [kwargs.get("name") for kwargs in captured_task_kwargs]
    assert matching, (
        f"Expected a captured task named {expected_name!r}; "
        f"captured names were {captured_names!r}."
    )
    return matching[-1]


def _make_profile(slug: str = "series-slug") -> SeriesProfile:
    """Return a minimal series profile for orchestration tests."""
    now = dt.datetime.now(dt.UTC)
    return SeriesProfile(
        id=uuid.uuid4(),
        slug=slug,
        title="Series",
        description=None,
        configuration={"tone": "neutral"},
        created_at=now,
        updated_at=now,
    )


def _make_normalised_source(raw: RawSourceInput) -> NormalizedSource:
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


def _make_episode(series_profile_id: uuid.UUID) -> CanonicalEpisode:
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


class _TestNormaliser:
    """Normalize raw sources deterministically for this test."""

    async def normalize(self, raw_source: RawSourceInput) -> NormalizedSource:
        await asyncio.sleep(0)
        return _make_normalised_source(raw_source)


class _TestWeighting:
    """Return deterministic weights in source input order."""

    async def compute_weights(
        self,
        sources: list[NormalizedSource],
        series_configuration: dict[str, object],
    ) -> list[WeightingResult]:
        _ = series_configuration
        return [
            WeightingResult(
                source=source,
                computed_weight=max(0.1, 1.0 - (index * 0.1)),
                factors={"quality_score": source.quality_score},
            )
            for index, source in enumerate(sources)
        ]


class _TestResolver:
    """Mark the first source as preferred and retain the rest."""

    async def resolve(
        self,
        weighted_sources: list[WeightingResult],
    ) -> ConflictOutcome:
        return ConflictOutcome(
            merged_tei_xml="<TEI/>",
            merged_title="Merged title",
            preferred_sources=weighted_sources[:1],
            rejected_sources=weighted_sources[1:],
            resolution_notes="Preferred first source by deterministic order.",
        )


def _make_fake_ingest_sources(
    profile_id: uuid.UUID,
    captured_sources: list[SourceDocumentInput],
) -> typ.Callable[
    [object, SeriesProfile, IngestionRequest], typ.Awaitable[CanonicalEpisode]
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
        return _make_episode(profile_id)

    return _fake_ingest_sources


def _make_multi_source_request(slug: str) -> MultiSourceRequest:
    """Build a deterministic two-source ingestion request for tests."""
    return MultiSourceRequest(
        raw_sources=[
            RawSourceInput(
                source_type="transcript",
                source_uri="s3://bucket/source-1.txt",
                content="Source one",
                content_hash="hash-1",
                metadata={"title": "Source One"},
            ),
            RawSourceInput(
                source_type="brief",
                source_uri="s3://bucket/source-2.txt",
                content="Source two",
                content_hash="hash-2",
                metadata={"title": "Source Two"},
            ),
        ],
        series_slug=slug,
        requested_by="test@example.com",
    )


@pytest.mark.asyncio
async def test_create_task_forwards_task_factory_kwargs() -> None:
    """`create_task` forwards stdlib and custom kwargs to task factories."""

    async def _job() -> str:
        await asyncio.sleep(0)
        return "done"

    metadata = {
        "operation_name": "tests.create_task",
        "correlation_id": "corr-123",
        "priority_hint": 3,
    }
    context = cv.copy_context()

    with _recording_task_factory() as captured:
        task = create_task(
            _job(),
            name="create-task-test",
            context=context,
            eager_start=True,
            metadata=metadata,
        )
        result = await task

    assert result == "done", f"expected result == 'done', got {result!r}"
    kwargs = _select_captured_task_kwargs(captured, "create-task-test")
    assert kwargs["name"] == "create-task-test", (
        f"expected task name 'create-task-test', got {kwargs['name']!r}"
    )
    assert kwargs["context"] is context, (
        f"expected task context object {context!r}, got {kwargs['context']!r}"
    )
    assert kwargs["eager_start"] is True, (
        f"expected eager_start True, got {kwargs['eager_start']!r}"
    )
    assert kwargs[TASK_METADATA_KWARG] == metadata, (
        f"expected metadata {metadata!r}, got {kwargs[TASK_METADATA_KWARG]!r}"
    )


@pytest.mark.asyncio
async def test_create_task_in_group_forwards_task_factory_kwargs() -> None:
    """`create_task_in_group` forwards kwargs to task factories."""

    async def _job() -> str:
        await asyncio.sleep(0)
        return "group-done"

    metadata = {
        "operation_name": "tests.task_group",
        "correlation_id": "group-456",
    }

    with _recording_task_factory() as captured:
        async with asyncio.TaskGroup() as group:
            task = create_task_in_group(
                group,
                _job(),
                name="task-group-test",
                eager_start=False,
                metadata=metadata,
            )

    task_result = task.result()
    assert task_result == "group-done", (
        f"expected task group result 'group-done', got {task_result!r}"
    )
    kwargs = _select_captured_task_kwargs(captured, "task-group-test")
    assert kwargs["name"] == "task-group-test", (
        f"expected task name 'task-group-test', got {kwargs['name']!r}"
    )
    assert kwargs["eager_start"] is False, (
        f"expected eager_start False, got {kwargs['eager_start']!r}"
    )
    assert kwargs[TASK_METADATA_KWARG] == metadata, (
        f"expected metadata {metadata!r}, got {kwargs[TASK_METADATA_KWARG]!r}"
    )


def test_create_task_rejects_unsupported_metadata_key() -> None:
    """Unsupported metadata keys are rejected with a clear error."""
    coro: typ.Coroutine[object, object, object] | None = None
    try:
        with pytest.raises(ValueError, match="Unsupported task metadata keys"):
            create_task(
                coro := asyncio.sleep(0),
                metadata=typ.cast("dict[str, object]", {"unsupported_key": "nope"}),
            )
    finally:
        if coro is not None:
            coro.close()


@pytest.mark.parametrize(
    ("metadata", "expected_pattern"),
    [
        (
            {"operation_name": 123},
            "operation_name",
        ),
        (
            {"operation_name": ""},
            "operation_name",
        ),
        (
            {"correlation_id": 123},
            "correlation_id",
        ),
        (
            {"correlation_id": ""},
            "correlation_id",
        ),
        (
            {"priority_hint": "high"},
            "priority_hint",
        ),
        (
            {"priority_hint": True},
            "priority_hint",
        ),
    ],
    ids=[
        "operation_name_non_string",
        "operation_name_empty",
        "correlation_id_non_string",
        "correlation_id_empty",
        "priority_hint_non_int",
        "priority_hint_bool",
    ],
)
def test_create_task_rejects_invalid_metadata_values(
    metadata: dict[str, object],
    expected_pattern: str,
) -> None:
    """Invalid metadata values raise typed validation errors."""
    coro = asyncio.sleep(0)
    try:
        with pytest.raises(TypeError, match=expected_pattern):
            create_task(coro, metadata=typ.cast("TaskMetadata", metadata))
    finally:
        coro.close()


@pytest.mark.asyncio
async def test_create_task_ignores_metadata_without_custom_factory() -> None:
    """Custom metadata is ignored when the running loop has no task factory."""
    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    loop.set_task_factory(None)
    try:

        async def _job() -> str:
            await asyncio.sleep(0)
            return "ok"

        task = create_task(
            _job(),
            metadata={"operation_name": "tests.no_factory"},
        )
        task_result = await task
        assert task_result == "ok", (
            f"expected task result 'ok' without custom factory, got {task_result!r}"
        )
    finally:
        loop.set_task_factory(previous_factory)


@pytest.mark.asyncio
async def test_create_task_empty_metadata_is_not_forwarded() -> None:
    """An empty metadata dictionary is treated as absent metadata."""

    async def _job() -> str:
        await asyncio.sleep(0)
        return "done"

    with _recording_task_factory() as captured:
        task = create_task(
            _job(),
            name="create-task-empty-metadata",
            metadata=typ.cast("TaskMetadata", {}),
        )
        result = await task

    assert result == "done", f"expected result == 'done', got {result!r}"
    kwargs = _select_captured_task_kwargs(captured, "create-task-empty-metadata")
    assert kwargs["name"] == "create-task-empty-metadata", (
        f"expected task name 'create-task-empty-metadata', got {kwargs['name']!r}"
    )
    assert TASK_METADATA_KWARG not in kwargs, (
        f"expected no {TASK_METADATA_KWARG!r} in task kwargs, got {kwargs!r}"
    )


@pytest.mark.asyncio
async def test_create_task_partial_metadata_forwards_present_keys_only() -> None:
    """Partial metadata is forwarded without synthesizing missing keys."""

    async def _job() -> str:
        await asyncio.sleep(0)
        return "done"

    metadata: TaskMetadata = {"operation_name": "tests.create_task.partial"}

    with _recording_task_factory() as captured:
        task = create_task(
            _job(),
            name="create-task-partial-metadata",
            metadata=metadata,
        )
        result = await task

    assert result == "done", f"expected result == 'done', got {result!r}"
    kwargs = _select_captured_task_kwargs(captured, "create-task-partial-metadata")
    forwarded_metadata = typ.cast("dict[str, object]", kwargs[TASK_METADATA_KWARG])
    assert forwarded_metadata["operation_name"] == "tests.create_task.partial", (
        "expected operation_name 'tests.create_task.partial', "
        f"got {forwarded_metadata['operation_name']!r}"
    )
    assert "correlation_id" not in forwarded_metadata, (
        "expected forwarded metadata to omit 'correlation_id', "
        f"got {forwarded_metadata!r}"
    )
    assert "priority_hint" not in forwarded_metadata, (
        "expected forwarded metadata to omit 'priority_hint', "
        f"got {forwarded_metadata!r}"
    )


@pytest.mark.asyncio
async def test_ingest_multi_source_emits_metadata_aware_normalisation_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ingestion fan-out creates metadata-aware normalization tasks."""
    profile = _make_profile()
    captured_sources: list[SourceDocumentInput] = []

    monkeypatch.setattr(
        "episodic.canonical.ingestion_service.ingest_sources",
        _make_fake_ingest_sources(profile.id, captured_sources),
    )

    request = _make_multi_source_request(profile.slug)
    pipeline = IngestionPipeline(
        normalizer=_TestNormaliser(),
        weighting=_TestWeighting(),
        resolver=_TestResolver(),
    )

    with _recording_task_factory() as captured_task_kwargs:
        episode = await ingest_multi_source(
            typ.cast("CanonicalUnitOfWork", object()),
            profile,
            request,
            pipeline,
        )

    assert episode.series_profile_id == profile.id, (
        f"expected episode.series_profile_id {profile.id!r}, "
        f"got {episode.series_profile_id!r}"
    )
    assert len(captured_sources) == 2, (
        f"expected 2 captured sources, got {len(captured_sources)}"
    )

    normalise_task_kwargs: list[dict[str, object]] = []
    for kwargs in captured_task_kwargs:
        task_name = kwargs.get("name")
        if isinstance(task_name, str) and task_name.startswith(
            "canonical.ingestion.normalise:"
        ):
            normalise_task_kwargs.append(kwargs)

    assert len(normalise_task_kwargs) == 2, (
        "expected 2 normalisation task kwargs entries, "
        f"got {len(normalise_task_kwargs)}"
    )
    for index, kwargs in enumerate(normalise_task_kwargs, start=1):
        metadata = typ.cast("dict[str, object]", kwargs[TASK_METADATA_KWARG])
        assert metadata["operation_name"] == "canonical.ingestion.normalise", (
            "expected operation_name 'canonical.ingestion.normalise', "
            f"got {metadata['operation_name']!r}"
        )
        assert metadata["correlation_id"] == profile.slug, (
            f"expected correlation_id {profile.slug!r}, "
            f"got {metadata['correlation_id']!r}"
        )
        assert metadata["priority_hint"] == index, (
            f"expected priority_hint {index}, got {metadata['priority_hint']!r}"
        )
