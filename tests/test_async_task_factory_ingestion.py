"""Tests for ingestion task-factory metadata propagation."""

import typing as typ

import pytest

from episodic.asyncio_tasks import TASK_METADATA_KWARG
from episodic.canonical.ingestion import MultiSourceRequest, RawSourceInput
from episodic.canonical.ingestion_service import IngestionPipeline, ingest_multi_source
from tests.fixtures.async_task_factory import (
    TestNormalizer,
    TestResolver,
    TestWeighting,
    make_fake_ingest_sources,
    make_profile,
    recording_task_factory,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import SourceDocumentInput
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


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
async def test_ingest_multi_source_emits_metadata_aware_normalisation_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ingestion fan-out creates metadata-aware normalization tasks."""
    profile = make_profile()
    captured_sources: list[SourceDocumentInput] = []

    monkeypatch.setattr(
        "episodic.canonical.ingestion_service.ingest_sources",
        make_fake_ingest_sources(profile.id, captured_sources),
    )

    request = _make_multi_source_request(profile.slug)
    pipeline = IngestionPipeline(
        normalizer=TestNormalizer(),
        weighting=TestWeighting(),
        resolver=TestResolver(),
    )

    with recording_task_factory() as captured_task_kwargs:
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
