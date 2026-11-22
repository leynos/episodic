"""Unit tests for the generation-run claim component."""

import datetime as dt

import pytest

from episodic.canonical.domain import ReferenceBindingTargetKind
from episodic.canonical.generation_quality import QualityMode
from episodic.generation.launcher_support import (
    GenerationSourceLimitError,
    GenerationSourceLimits,
)
from tests.generation_run_claim_support import (
    BUNDLE_ID,
    EPISODE_ID,
    NOW,
    RUN_ID,
    SERIES_ID,
    RecordingDraftGenerator,
    RecordingGenerationRuns,
    RecordingMetrics,
    RecordingSourceDocuments,
    RecordingSourceLoader,
    claimed_run_value,
    claimer,
    clock,
    draft_result,
    source,
    source_document,
    unit_of_work,
)


@pytest.mark.asyncio
async def test_claim_takes_a_lease_and_records_started_event() -> None:
    """A claim should record the lease and make the started event durable."""
    uow = unit_of_work()
    run_claimer = claimer(uow=uow, loader=RecordingSourceLoader(sources=(source(),)))

    claimed = await run_claimer.claim(RUN_ID)

    assert claimed is not None, "expected the run to be claimed"
    assert uow.generation_runs.claims == [
        {
            "run_id": RUN_ID,
            "current_node": "draft",
            "started_at": NOW,
            "lease_expires_at": NOW + dt.timedelta(seconds=900),
        }
    ], uow.generation_runs.claims
    assert uow.generation_runs.events == [
        (RUN_ID, "run.started", {"current_node": "draft"}, NOW)
    ], uow.generation_runs.events
    assert uow.commits == 1, uow.commits
    assert uow.rollbacks == 0, uow.rollbacks


@pytest.mark.asyncio
async def test_claim_hydrates_episode_and_sources() -> None:
    """Hydration should read the episode and bundle, then load bounded sources."""
    uow = unit_of_work()
    limits = GenerationSourceLimits(max_source_count=4)
    loader = RecordingSourceLoader(sources=(source(),))
    metrics = RecordingMetrics()
    run_claimer = claimer(uow=uow, loader=loader, metrics=metrics, limits=limits)

    claimed = await run_claimer.claim(RUN_ID)

    assert claimed is not None, "expected the run to be claimed"
    # The claim reads the episode for hydration; binding resolution re-reads it
    # to validate the series context.
    assert uow.episodes.reads == [EPISODE_ID, EPISODE_ID], uow.episodes.reads
    assert uow.source_documents.reads == [BUNDLE_ID], uow.source_documents.reads
    assert uow.reference_bindings.targets == [
        (ReferenceBindingTargetKind.SERIES_PROFILE, SERIES_ID)
    ], uow.reference_bindings.targets
    assert loader.calls == [([source_document()], limits)], loader.calls
    assert claimed.sources == (source(),), claimed.sources
    assert claimed.presenter_profiles == (), claimed.presenter_profiles
    assert metrics.counters == [
        (
            "generation_run_qa_bypass_total",
            {"quality_mode": QualityMode.DRAFT_WITHOUT_QA.value},
        )
    ], metrics.counters


@pytest.mark.asyncio
async def test_claim_rejects_source_bundle_above_the_count_limit() -> None:
    """Hydration should reject an over-count bundle before loading content."""
    uow = unit_of_work()
    uow.source_documents = RecordingSourceDocuments([
        source_document(),
        source_document(),
    ])
    loader = RecordingSourceLoader()
    run_claimer = claimer(
        uow=uow,
        loader=loader,
        limits=GenerationSourceLimits(max_source_count=1),
    )

    with pytest.raises(GenerationSourceLimitError, match="count"):
        await run_claimer.claim(RUN_ID)

    assert loader.calls == [], loader.calls


@pytest.mark.asyncio
async def test_claim_rolls_back_and_returns_none_when_the_claim_is_lost() -> None:
    """A lost claim should roll back without starting or hydrating anything."""
    uow = unit_of_work()
    uow.generation_runs = RecordingGenerationRuns(None)
    loader = RecordingSourceLoader()
    run_claimer = claimer(uow=uow, loader=loader)

    claimed = await run_claimer.claim(RUN_ID)

    assert claimed is None, claimed
    assert uow.generation_runs.events == [], uow.generation_runs.events
    assert uow.rollbacks == 1, uow.rollbacks
    assert uow.commits == 0, uow.commits
    assert uow.episodes.reads == [], uow.episodes.reads
    assert loader.calls == [], loader.calls


@pytest.mark.asyncio
async def test_generate_records_draft_latency_from_the_monotonic_clock() -> None:
    """Draft generation should observe latency measured by the injected clock."""
    uow = unit_of_work()
    generator = RecordingDraftGenerator(draft_result())
    metrics = RecordingMetrics()
    run_claimer = claimer(
        uow=uow,
        loader=RecordingSourceLoader(),
        generator=generator,
        metrics=metrics,
    )

    result = await run_claimer.generate(claimed_run_value())

    assert result is generator.result, result
    assert metrics.latencies == [
        (
            "generation_run_draft_latency_ms",
            250.0,
            {"quality_mode": QualityMode.DRAFT_WITHOUT_QA.value},
        )
    ], metrics.latencies
    assert generator.requests[0].clock is clock, generator.requests
    assert generator.requests[0].id_factory("turn") == "turn-1", generator.requests
