"""Support fakes for generation-run claim component tests."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

from episodic.canonical.domain import (
    CanonicalEpisode,
    GenerationRun,
    GenerationRunStatus,
    SourceDocument,
)
from episodic.canonical.domain_enums import ApprovalState, EpisodeStatus
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.generation.draft_script import (
    DraftScriptRequest,
    DraftScriptResult,
    DraftScriptSource,
)
from episodic.generation.launcher_claim import ClaimerContext, GenerationRunClaimer
from episodic.generation.launcher_support import ClaimedRun
from episodic.llm import LLMUsage

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.generation_claim import ExecutionClaim
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork

NOW = dt.datetime(2026, 9, 1, 9, 30, tzinfo=dt.UTC)
RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000000901")
EPISODE_ID = uuid.UUID("00000000-0000-0000-0000-000000000902")
SERIES_ID = uuid.UUID("00000000-0000-0000-0000-000000000903")
BUNDLE_ID = uuid.UUID("00000000-0000-0000-0000-000000000904")


def clock() -> dt.datetime:
    """Return the frozen claim timestamp."""
    return NOW


def running_run() -> GenerationRun:
    """Return a running generation run owned by the claim component."""
    return GenerationRun(
        id=RUN_ID,
        episode_id=EPISODE_ID,
        source_bundle_id=BUNDLE_ID,
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
    """Return the episode a claimed run belongs to."""
    return CanonicalEpisode(
        id=EPISODE_ID,
        series_profile_id=SERIES_ID,
        tei_header_id=uuid.UUID("00000000-0000-0000-0000-000000000905"),
        title="Bridgewater Futures",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=NOW,
        updated_at=NOW,
        tei_revision=3,
    )


def source_document() -> SourceDocument:
    """Return one canonical source document for the run's bundle."""
    return SourceDocument(
        id=uuid.UUID("00000000-0000-0000-0000-000000000906"),
        ingestion_job_id=BUNDLE_ID,
        canonical_episode_id=EPISODE_ID,
        reference_document_revision_id=None,
        source_type="research_brief",
        source_uri="https://example.test/source.md",
        weight=1.0,
        content_hash="sha256:source",
        metadata={"content": "Bridgewater launch source text."},
        created_at=NOW,
    )


def source() -> DraftScriptSource:
    """Return one hydrated generator source."""
    return DraftScriptSource(
        source_id=str(source_document().id),
        source_type="research_brief",
        source_uri="https://example.test/source.md",
        content="Bridgewater launch source text.",
        weight=1.0,
    )


def draft_result() -> DraftScriptResult:
    """Return a generated draft result."""
    return DraftScriptResult(
        tei_xml="<TEI/>",
        content_hash="sha256:draft",
        usage=LLMUsage(input_tokens=1, output_tokens=2, total_tokens=3),
        model="gpt-4o-mini",
        provider_response_id="resp-1",
        finish_reason="stop",
    )


def claimed_run_value() -> ClaimedRun:
    """Return a claimed-run value for generation-only tests."""
    return ClaimedRun(
        run=running_run(),
        episode=episode(),
        sources=(source(),),
        presenter_profiles=(),
    )


@dc.dataclass(slots=True)
class RecordingGenerationRuns:
    """Generation-run repository fake recording claim and event writes."""

    run: GenerationRun | None
    claims: list[dict[str, object]] = dc.field(default_factory=list)
    events: list[tuple[uuid.UUID, str, dict[str, object], dt.datetime]] = dc.field(
        default_factory=list
    )

    async def claim_run_for_execution(
        self,
        run_id: uuid.UUID,
        claim: ExecutionClaim,
    ) -> GenerationRun | None:
        """Record the claim request and return the configured run."""
        self.claims.append({
            "run_id": run_id,
            "current_node": claim.current_node,
            "started_at": claim.started_at,
            "lease_expires_at": claim.lease_expires_at,
            "claim_token": claim.claim_token,
        })
        return self.run

    @staticmethod
    async def claim_token_for(run_id: uuid.UUID) -> uuid.UUID | None:
        """Report that no claim token is stored for any run."""
        _ = run_id
        return None

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


@dc.dataclass(slots=True)
class RecordingEpisodes:
    """Episode repository fake returning one persisted episode."""

    episode: CanonicalEpisode | None
    reads: list[uuid.UUID] = dc.field(default_factory=list)

    async def get(self, episode_id: uuid.UUID) -> CanonicalEpisode | None:
        """Record the read and return the configured episode."""
        self.reads.append(episode_id)
        return self.episode


@dc.dataclass(slots=True)
class RecordingSourceDocuments:
    """Source-document repository fake returning a fixed document list."""

    documents: list[SourceDocument]
    reads: list[uuid.UUID] = dc.field(default_factory=list)

    async def list_for_job(self, job_id: uuid.UUID) -> list[SourceDocument]:
        """Record the bundle read and return the configured documents."""
        self.reads.append(job_id)
        return self.documents


@dc.dataclass(slots=True)
class RecordingReferenceBindings:
    """Reference-binding repository fake recording target queries."""

    targets: list[tuple[object, object]] = dc.field(default_factory=list)

    async def list_for_target(
        self,
        *,
        target_kind: object,
        target_id: object,
    ) -> list[object]:
        """Record the target query and return no bindings."""
        self.targets.append((target_kind, target_id))
        return []


class RecordingUnitOfWork:
    """Unit-of-work fake exposing only the ports the claim path reads."""

    def __init__(
        self,
        *,
        generation_runs: RecordingGenerationRuns,
        episodes: RecordingEpisodes,
        source_documents: RecordingSourceDocuments,
    ) -> None:
        """Bind the repository fakes used by one claim."""
        self.generation_runs = generation_runs
        self.episodes = episodes
        self.source_documents = source_documents
        self.reference_bindings = RecordingReferenceBindings()
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
class RecordingSourceLoader:
    """Source loader fake that records the documents and limits it received."""

    sources: tuple[DraftScriptSource, ...] = ()
    calls: list[list[SourceDocument]] = dc.field(default_factory=list)

    async def load(
        self,
        documents: cabc.Sequence[SourceDocument],
    ) -> tuple[DraftScriptSource, ...]:
        """Record the load and return the configured sources."""
        self.calls.append(list(documents))
        return self.sources


@dc.dataclass(slots=True)
class RecordingDraftGenerator:
    """Draft generator fake capturing the request it received."""

    result: DraftScriptResult
    requests: list[DraftScriptRequest] = dc.field(default_factory=list)

    async def generate(self, request: DraftScriptRequest) -> DraftScriptResult:
        """Capture the request and return the configured result."""
        self.requests.append(request)
        return self.result


@dc.dataclass(slots=True)
class RecordingMetrics:
    """Metrics fake capturing counters and latency observations."""

    counters: list[tuple[str, dict[str, str]]] = dc.field(default_factory=list)
    latencies: list[tuple[str, float, dict[str, str]]] = dc.field(default_factory=list)

    def increment_counter(self, name: str, *, labels: cabc.Mapping[str, str]) -> None:
        """Capture one counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Capture one latency observation."""
        self.latencies.append((name, value, dict(labels)))

    def observe_value(  # ruff: ignore[no-self-use]  # The metrics protocol fixes this instance method.
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Accept scalar observations outside this component's scope."""
        _ = (name, value, labels)


class SteppingMonotonicClock:
    """Monotonic clock fake returning preconfigured timestamps."""

    def __init__(self, stamps: cabc.Iterator[float]) -> None:
        """Store the timestamps to replay."""
        self._stamps = stamps

    def monotonic_seconds(self) -> float:
        """Return the next configured timestamp."""
        return next(self._stamps)


def claimer_context(
    uow: RecordingUnitOfWork,
    loader: RecordingSourceLoader,
) -> ClaimerContext:
    """Build a value-backed claimer runtime around explicit fakes.

    Tests that need other collaborators replace the returned context with
    ``dataclasses.replace``, so this seam stays small.

    Returns
    -------
    ClaimerContext
        Runtime wired to the supplied fakes and the deterministic clocks.
    """
    return ClaimerContext(
        uow_factory=lambda: typ.cast("CanonicalUnitOfWork", uow),
        draft_generator=RecordingDraftGenerator(draft_result()),
        source_loader=loader,
        clock=clock,
        monotonic_clock=SteppingMonotonicClock(iter((100.0, 100.25))),
    )


def claimer(
    uow: RecordingUnitOfWork,
    loader: RecordingSourceLoader,
) -> GenerationRunClaimer:
    """Build a claimer around explicit unit-of-work and source-loader fakes.

    Returns
    -------
    GenerationRunClaimer
        Claimer wired to the supplied fakes and the deterministic clocks.
    """
    return GenerationRunClaimer(runtime=claimer_context(uow, loader))


def unit_of_work(
    *,
    generation_run: GenerationRun | None = None,
) -> RecordingUnitOfWork:
    """Build the unit-of-work fake for one claim."""
    return RecordingUnitOfWork(
        generation_runs=RecordingGenerationRuns(
            running_run() if generation_run is None else generation_run
        ),
        episodes=RecordingEpisodes(episode()),
        source_documents=RecordingSourceDocuments([source_document()]),
    )
