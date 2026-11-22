"""Characterization snapshots for the no-QA generation slice (INV-0).

These tests record the observable behaviour of a ``draft_without_qa`` run
before the content-generation graph is introduced: the event stream and its
payloads, the final run and episode rows, every metrics emission, and the
execution span's attributes. They must pass unmodified at every later
milestone, so a refactor that changes any of them fails loudly.

Latency observations record the metric name and labels but not the elapsed
value, which is wall-clock dependent. Every other recorded value is
deterministic. Identifiers are normalized through
:mod:`tests.snapshot_redaction`.
"""

import dataclasses as dc
import typing as typ

import pytest

from episodic.canonical.domain import (
    GenerationEvent,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.generation.draft_script import DraftScriptTransientProviderError
from episodic.generation.launcher import InProcessGenerationRunLauncher
from episodic.generation.launcher_support import GenerationSourceLimits
from episodic.observability import RecordingTracer
from tests.generation_run_launcher_observation_support import RecordingMetrics
from tests.generation_run_launcher_support import (
    NOW,
    BlockingDraftGenerator,
    CancelledDraftGenerator,
    FailingDraftGenerator,
    RecordingDraftGenerator,
    draft_result,
    prepare_pending_run,
    valid_tei,
)
from tests.no_qa_characterization_support import Findings, payload

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import datetime as dt
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from syrupy.assertion import SnapshotAssertion

    from episodic.canonical.domain import CanonicalEpisode
    from episodic.generation.draft_script import DraftScriptGenerator

type UnitOfWorkFactory = cabc.Callable[[], SqlAlchemyUnitOfWork]


@dc.dataclass(frozen=True, slots=True)
class _Case:
    """Observed outcome of one characterization case."""

    findings: Findings
    payload: dict[str, object]
    span_outcome: str | None


@dc.dataclass(frozen=True, slots=True)
class _Scenario:
    """Generator, unit-of-work factory, and limits for one case."""

    generator: object
    uow_factory: UnitOfWorkFactory | None = None
    source_limits: GenerationSourceLimits | None = None
    blocks_until_shutdown: bool = False


def _clock() -> dt.datetime:
    """Return the frozen launcher timestamp."""
    return NOW


class _MissingEpisodeRepository:
    """Episode repository fake whose lookups always miss."""

    async def get(self, episode_id: uuid.UUID) -> None:
        """Report that no episode exists for the identifier."""
        _ = episode_id


class _MissingEpisodeUnitOfWork(SqlAlchemyUnitOfWork):
    """Unit of work whose episode repository never finds a row."""

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        """Open the real unit of work and replace only the episode lookup."""
        uow = await super().__aenter__()
        uow.episodes = typ.cast("typ.Any", _MissingEpisodeRepository())
        return uow


def _default_uow_factory(
    factory: async_sessionmaker[AsyncSession],
) -> UnitOfWorkFactory:
    """Return the unit-of-work factory an ordinary launch uses."""

    def make() -> SqlAlchemyUnitOfWork:
        """Open one unit of work over the migrated database."""
        return SqlAlchemyUnitOfWork(factory)

    return make


def _missing_episode_uow_factory(
    factory: async_sessionmaker[AsyncSession],
) -> UnitOfWorkFactory:
    """Return a factory whose episode lookups always miss."""

    def make() -> SqlAlchemyUnitOfWork:
        """Open a unit of work with a missing-episode repository."""
        return _MissingEpisodeUnitOfWork(factory)

    return make


def _launcher(
    factory: async_sessionmaker[AsyncSession],
    generator: object,
    *,
    uow_factory: UnitOfWorkFactory | None = None,
    source_limits: GenerationSourceLimits | None = None,
) -> InProcessGenerationRunLauncher:
    """Build a launcher with characterization-grade collaborators."""
    return InProcessGenerationRunLauncher(
        uow_factory=(
            _default_uow_factory(factory) if uow_factory is None else uow_factory
        ),
        draft_generator=typ.cast("DraftScriptGenerator", generator),
        clock=_clock,
        source_limits=(
            GenerationSourceLimits() if source_limits is None else source_limits
        ),
    )


async def _load(
    factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    episode_id: uuid.UUID,
) -> tuple[GenerationRun, tuple[GenerationEvent, ...], CanonicalEpisode]:
    """Load the persisted run, event log, and episode after a case ran."""
    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
        events = await uow.generation_runs.list_events(run_id)
        episode = await uow.episodes.get(episode_id)
    assert run is not None, f"run {run_id} was not persisted; events={events!r}"
    assert episode is not None, f"episode {episode_id} was not persisted"
    return run, events, episode


def _standard_generator() -> RecordingDraftGenerator:
    """Return the generator that serves a valid draft."""
    return RecordingDraftGenerator(draft_result(valid_tei()))


def _scenario_builders(
    factory: async_sessionmaker[AsyncSession],
) -> dict[str, cabc.Callable[[], _Scenario]]:
    """Return the scenario each case name selects."""
    return {
        "success": lambda: _Scenario(generator=_standard_generator()),
        "provider_failure": lambda: _Scenario(
            generator=FailingDraftGenerator(
                DraftScriptTransientProviderError("try again later")
            )
        ),
        "invalid_tei": lambda: _Scenario(
            generator=RecordingDraftGenerator(draft_result("<TEI>broken"))
        ),
        "source_limit": lambda: _Scenario(
            generator=_standard_generator(),
            source_limits=GenerationSourceLimits(max_source_bytes=8),
        ),
        "missing_episode": lambda: _Scenario(
            generator=_standard_generator(),
            uow_factory=_missing_episode_uow_factory(factory),
        ),
        "generator_cancelled": lambda: _Scenario(generator=CancelledDraftGenerator()),
        "shutdown_during_generation": lambda: _Scenario(
            generator=BlockingDraftGenerator(), blocks_until_shutdown=True
        ),
    }


def _scenario(case: str, factory: async_sessionmaker[AsyncSession]) -> _Scenario:
    """Build the scenario a characterization case requires."""
    builders = _scenario_builders(factory)
    if case not in builders:
        msg = f"unknown characterization case: {case}"
        raise AssertionError(msg)
    return builders[case]()


async def _drive(
    run_launcher: InProcessGenerationRunLauncher,
    run_id: uuid.UUID,
    scenario: _Scenario,
) -> None:
    """Run the launcher to completion, or shut it down while it blocks."""
    if not scenario.blocks_until_shutdown:
        await run_launcher.launch(run_id)
        await run_launcher.drain()
        return
    generator = typ.cast("BlockingDraftGenerator", scenario.generator)
    await run_launcher.launch(run_id)
    await generator.started.wait()
    await run_launcher.shutdown()


async def _run_case(
    case: str,
    factory: async_sessionmaker[AsyncSession],
) -> _Case:
    """Execute one characterization case and return its observations."""
    run_id, episode_id = await prepare_pending_run(factory)
    scenario = _scenario(case, factory)
    metrics = RecordingMetrics()
    tracer = RecordingTracer()
    run_launcher = _launcher(
        factory,
        scenario.generator,
        uow_factory=scenario.uow_factory,
        source_limits=scenario.source_limits,
    )
    run_launcher.metrics = metrics
    run_launcher.tracer = tracer
    await _drive(run_launcher, run_id, scenario)
    run, events, episode = await _load(factory, run_id, episode_id)
    findings = Findings(
        run=run,
        events=events,
        episode=episode,
        metrics=metrics,
        tracer=tracer,
    )
    return _Case(
        findings=findings,
        payload=payload(findings),
        span_outcome=(
            None if not tracer.spans else tracer.spans[0].attributes.get("outcome")
        ),
    )


_CASES: tuple[str, ...] = (
    "success",
    "provider_failure",
    "invalid_tei",
    "source_limit",
    "missing_episode",
    "generator_cancelled",
    "shutdown_during_generation",
)

_EXPECTED: dict[str, tuple[GenerationRunStatus, str | None, str, str]] = {
    "success": (GenerationRunStatus.SUCCEEDED, None, "completed", "run.succeeded"),
    "provider_failure": (
        GenerationRunStatus.FAILED,
        "provider.transient",
        "failed",
        "run.failed",
    ),
    "invalid_tei": (GenerationRunStatus.FAILED, "tei.invalid", "failed", "run.failed"),
    "source_limit": (
        GenerationRunStatus.FAILED,
        "generation.source_limit",
        "failed",
        "run.failed",
    ),
    "missing_episode": (
        GenerationRunStatus.FAILED,
        "episode.not_found",
        "failed",
        "run.failed",
    ),
    "generator_cancelled": (
        GenerationRunStatus.FAILED,
        "launcher.shutdown",
        "cancelled",
        "run.failed",
    ),
    "shutdown_during_generation": (
        GenerationRunStatus.FAILED,
        "launcher.shutdown",
        "cancelled",
        "run.failed",
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _CASES)
async def test_no_qa_run_characterization(
    case: str,
    session_factory: async_sessionmaker[AsyncSession],
    snapshot: SnapshotAssertion,
) -> None:
    """No-QA runs must keep their recorded events, metrics, and span outcome."""
    expected_status, expected_category, expected_outcome, expected_final_kind = (
        _EXPECTED[case]
    )

    observed = await _run_case(case, session_factory)

    findings = observed.findings
    assert findings.run.status is expected_status, (
        f"{case}: status={findings.run.status}; events={findings.events!r}"
    )
    assert findings.run.error_category == expected_category, (
        f"{case}: error_category={findings.run.error_category!r}"
    )
    assert observed.span_outcome == expected_outcome, (
        f"{case}: span outcome={observed.span_outcome!r}"
    )
    assert findings.events, f"{case}: the event log must not be empty"
    assert findings.events[-1].kind == expected_final_kind, (
        f"{case}: final event={findings.events[-1]!r}"
    )
    assert observed.payload["metrics"], f"{case}: metrics must not be empty"
    assert observed.payload == snapshot, (
        f"{case}: the characterization payload must match its snapshot"
    )
