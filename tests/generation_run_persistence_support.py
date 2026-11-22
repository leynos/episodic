"""Support fakes for generation-run persistence component tests."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

from episodic.canonical.domain import (
    CanonicalEpisode,
    EpisodeTeiUpdate,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.domain_enums import ApprovalState, EpisodeStatus
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.cost.ports import BillingPeriodKey, CostLedgerEntryId
from episodic.generation.launcher_persistence import GenerationRunPersistence
from episodic.generation.launcher_support import ClaimedRun
from tests.generation_run_launcher_support import draft_result, valid_tei

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.cost.recorder import CostProviderOperation, ProviderCallRecord
    from episodic.generation.draft_script import DraftScriptResult
    from episodic.observability import ValueMetricsPort

NOW = dt.datetime(2026, 9, 1, 9, 30, tzinfo=dt.UTC)
RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000000911")
EPISODE_ID = uuid.UUID("00000000-0000-0000-0000-000000000912")
SERIES_ID = uuid.UUID("00000000-0000-0000-0000-000000000913")


def clock() -> dt.datetime:
    """Return the frozen persistence timestamp."""
    return NOW


def running_run() -> GenerationRun:
    """Return a running generation run owned by the persistence component."""
    return GenerationRun(
        id=RUN_ID,
        episode_id=EPISODE_ID,
        source_bundle_id=uuid.UUID("00000000-0000-0000-0000-000000000914"),
        actor="editor@example.test",
        status=GenerationRunStatus.RUNNING,
        current_node="draft",
        budget_snapshot={},
        configuration={},
        created_at=NOW,
        updated_at=NOW,
        started_at=NOW,
        ended_at=None,
        error_message=None,
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="Vertical slice draft.",
    )


def episode() -> CanonicalEpisode:
    """Return the episode a persisted run belongs to."""
    return CanonicalEpisode(
        id=EPISODE_ID,
        series_profile_id=SERIES_ID,
        tei_header_id=uuid.UUID("00000000-0000-0000-0000-000000000915"),
        title="Bridgewater Futures",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=NOW,
        updated_at=NOW,
        tei_revision=3,
    )


def claimed_run_value() -> ClaimedRun:
    """Return a claimed run carrying the pre-persistence episode revision."""
    return ClaimedRun(
        run=running_run(),
        episode=episode(),
        sources=(),
        presenter_profiles=(),
    )


def result() -> DraftScriptResult:
    """Return a generated draft result with valid TEI."""
    return draft_result(valid_tei())


@dc.dataclass(slots=True)
class RecordingEpisodes:
    """Episode repository fake recording the revision-guarded TEI update."""

    episode: CanonicalEpisode
    updates: list[tuple[uuid.UUID, EpisodeTeiUpdate]] = dc.field(default_factory=list)

    async def update(
        self,
        episode_id: uuid.UUID,
        *,
        update: EpisodeTeiUpdate,
    ) -> CanonicalEpisode:
        """Record the TEI update and return the incremented episode."""
        self.updates.append((episode_id, update))
        return dc.replace(
            self.episode,
            tei_xml=update.tei_xml,
            qa_status=update.qa_status,
            last_generation_run_id=update.last_generation_run_id,
            tei_revision=update.expected_revision + 1,
            tei_content_hash="sha256:persisted",
        )


@dc.dataclass(slots=True)
class RecordingGenerationRuns:
    """Generation-run repository fake recording events and status updates."""

    events: list[tuple[uuid.UUID, str, dict[str, object], dt.datetime]] = dc.field(
        default_factory=list
    )
    status_updates: list[tuple[uuid.UUID, GenerationRunStatusUpdate]] = dc.field(
        default_factory=list
    )
    status_error: Exception | None = None

    async def append_event(
        self,
        run_id: uuid.UUID,
        *,
        kind: str,
        payload: cabc.Mapping[str, object],
        occurred_at: dt.datetime,
    ) -> object:
        """Record one appended event."""
        self.events.append((run_id, kind, dict(payload), occurred_at))
        return object()

    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        update: GenerationRunStatusUpdate,
    ) -> object:
        """Record the status update, or raise the configured repository error."""
        if self.status_error is not None:
            raise self.status_error
        self.status_updates.append((run_id, update))
        return object()


class RecordingUnitOfWork:
    """Unit-of-work fake exposing only the ports the persistence path writes."""

    def __init__(
        self,
        *,
        generation_runs: RecordingGenerationRuns,
        episodes: RecordingEpisodes,
    ) -> None:
        """Bind the repository fakes used by one write."""
        self.generation_runs = generation_runs
        self.episodes = episodes
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self) -> typ.Self:
        """Enter the fake transaction."""
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Exit the fake transaction without suppressing exceptions."""
        del exc_info

    async def commit(self) -> None:
        """Record one commit."""
        self.commits += 1

    async def rollback(self) -> None:
        """Record one rollback."""
        self.rollbacks += 1


@dc.dataclass(slots=True)
class RecordingCostRecorder:
    """Cost recorder fake capturing pins, provider calls, and roll-ups."""

    pins: list[tuple[str, tuple[CostProviderOperation, ...], BillingPeriodKey]] = (
        dc.field(default_factory=list)
    )
    provider_calls: list[ProviderCallRecord] = dc.field(default_factory=list)
    finalized: list[tuple[str, str | None]] = dc.field(default_factory=list)

    async def pin_run_pricing(
        self,
        workflow_run_id: str,
        providers: tuple[CostProviderOperation, ...],
        billing_period_key: BillingPeriodKey,
    ) -> None:
        """Capture one pricing pin."""
        self.pins.append((workflow_run_id, providers, billing_period_key))

    async def record_provider_call(
        self,
        record: ProviderCallRecord,
    ) -> CostLedgerEntryId:
        """Capture one provider-call record."""
        self.provider_calls.append(record)
        return CostLedgerEntryId("entry:provider")

    async def finalize_run(
        self,
        workflow_run_id: str,
        workflow_node: str | None,
    ) -> CostLedgerEntryId:
        """Capture one final roll-up request."""
        self.finalized.append((workflow_run_id, workflow_node))
        return CostLedgerEntryId("entry:rollup")


@dc.dataclass(slots=True)
class RecordingMetrics:
    """Metrics fake capturing counters and scalar observations."""

    counters: list[tuple[str, dict[str, str]]] = dc.field(default_factory=list)
    values: list[tuple[str, float, dict[str, str]]] = dc.field(default_factory=list)

    def increment_counter(self, name: str, *, labels: cabc.Mapping[str, str]) -> None:
        """Capture one counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(  # ruff: ignore[no-self-use]  # The metrics protocol fixes this instance method.
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Accept latency observations outside this component's scope."""
        _ = (name, value, labels)

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Capture one scalar observation."""
        self.values.append((name, value, dict(labels)))


def unit_of_work(
    *,
    status_error: Exception | None = None,
) -> RecordingUnitOfWork:
    """Build the unit-of-work fake for one persistence write."""
    return RecordingUnitOfWork(
        generation_runs=RecordingGenerationRuns(status_error=status_error),
        episodes=RecordingEpisodes(episode()),
    )


# pylint: disable-next=too-many-arguments  # Test wiring names each port it replaces.
def persistence(  # ruff: ignore[too-many-arguments]  # Test wiring names each port it replaces.
    uow: RecordingUnitOfWork,
    *,
    recorder: RecordingCostRecorder | None = None,
    metrics: ValueMetricsPort | None = None,
    provider_name: str = "openai",
    provider_operation: str = "chat_completions",
) -> GenerationRunPersistence:
    """Build a persistence component around explicit fakes."""
    return GenerationRunPersistence(
        uow_factory=lambda: typ.cast("CanonicalUnitOfWork", uow),
        clock=clock,
        cost_recorder_factory=(None if recorder is None else lambda uow: recorder),
        provider_name=provider_name,
        provider_operation=provider_operation,
        metrics=RecordingMetrics() if metrics is None else metrics,
    )
