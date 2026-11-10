"""Tests for pricing-snapshot failures during generation-run launches."""

import typing as typ

import pytest

from episodic.canonical.domain import GenerationRunStatus
from episodic.cost import PricingSnapshotNotFoundError
from episodic.observability import RecordingTracer
from tests.generation_run_launcher_support import (
    FailingDraftGenerator,
    launch_and_load_run,
    launcher,
    prepare_pending_run,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_launcher_records_pricing_snapshot_failure(
    session_factory: object,
) -> None:
    """A pricing-snapshot failure should become a failed run with its category."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    run_id, _ = await prepare_pending_run(factory)
    run_launcher = launcher(
        factory,
        FailingDraftGenerator(
            PricingSnapshotNotFoundError("No pricing snapshot found for id pinned.")
        ),
    )
    tracer = RecordingTracer()
    run_launcher.tracer = tracer

    run, events = await launch_and_load_run(factory, run_id, run_launcher)

    assert run.status is GenerationRunStatus.FAILED, (
        f"run {run_id} status={run.status}; events={events!r}"
    )
    assert [event.kind for event in events] == ["run.started", "run.failed"], (
        f"run {run_id} events={events!r}"
    )
    assert events[-1].payload["error_category"] == "cost.pricing_snapshot", (
        f"run {run_id} final event={events[-1]!r}"
    )
    assert tracer.spans[0].attributes["failure_category"] == "cost.pricing_snapshot", (
        f"run {run_id} span={tracer.spans[0]!r}"
    )
