"""Translate canonical generation data at the launcher service boundary.

The public support types—``CostRecorderFactory``, ``SequentialDraftIds``,
``ClaimedRun``, ``Failure``, ``PersistedTei``, and
``ProviderCallRecordRequest``—keep launcher orchestration independent of
storage and provider representations. The helper services load source text
from canonical :class:`~episodic.canonical.domain.SourceDocument` records or
the object-store port, project resolved host and guest reference-document
bindings, and build the immutable request consumed by ``DraftScriptGenerator``.

The event-payload and provider-record helpers map ``DraftScriptResult`` usage,
provider metadata, and content hashes into generation events and the
``CostRecorderPort`` contract. ``classify_failure`` preserves stable terminal
categories for the API and metrics. These helpers accept the canonical unit
of work and outbound ports supplied by the launcher; they do not open,
commit, or dispose persistence sessions themselves.

Source loading and limits live in :mod:`episodic.generation.launcher_support_sources`,
presenter-profile projection lives in
:mod:`episodic.generation.launcher_support_presenters`, and event/cost/failure
mapping lives in :mod:`episodic.generation.launcher_support_events`. This
module re-exports their public names to preserve the original import path.
"""

import collections.abc as cabc
import dataclasses as dc
import typing as typ
import uuid

from episodic.canonical.episode_errors import EpisodeNotFoundError
from episodic.generation.draft_script import (
    DraftPresenterProfile,
    DraftScriptRequest,
    DraftScriptResult,
    DraftScriptSource,
)
from episodic.generation.launcher_support_events import (
    Failure,
    ProviderCallRecordRequest,
    classify_failure,
    draft_generated_payload,
    provider_call_record,
)
from episodic.generation.launcher_support_presenters import (
    project_presenter_profiles,
)
from episodic.generation.launcher_support_sources import (
    BoundedSourceLoader,
    GenerationSourceLimitError,
    GenerationSourceLimits,
    GenerationSourceLoader,
    SourceDocumentLoader,
    SourceLoadContext,
    SourceLoadRuntime,
    source_from_document,
)
from episodic.runtime_providers import Clock

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import CanonicalEpisode, GenerationRun
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.cost.recorder import CostRecorderPort

type DraftIdFactoryFactory = cabc.Callable[[], cabc.Callable[[str], str]]

__all__ = [
    "BoundedSourceLoader",
    "ClaimToken",
    "ClaimedRun",
    "ClaimedRunResult",
    "Clock",
    "CostRecorderFactory",
    "DraftIdFactoryFactory",
    "Failure",
    "FailureWrite",
    "FailureWriteResult",
    "GenerationSourceLimitError",
    "GenerationSourceLimits",
    "GenerationSourceLoader",
    "PersistedTei",
    "ProofFactory",
    "ProviderCallRecordRequest",
    "RunClaim",
    "SequentialDraftIds",
    "SourceDocumentLoader",
    "SourceLoadContext",
    "SourceLoadRuntime",
    "classify_failure",
    "draft_generated_payload",
    "draft_request",
    "project_presenter_profiles",
    "provider_call_record",
    "require_episode",
    "source_from_document",
]


class CostRecorderFactory(typ.Protocol):
    """Factory that binds a cost recorder to a unit of work."""

    def __call__(self, uow: CanonicalUnitOfWork) -> CostRecorderPort | None:
        """Return a recorder for the active unit of work, or disable recording."""


class SequentialDraftIds:
    """Deterministic per-run TEI id factory."""

    def __init__(self) -> None:
        """Start every prefix counter at zero."""
        self._counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        """Return the next identifier for a prefix."""
        next_value = self._counts.get(prefix, 0) + 1
        self._counts[prefix] = next_value
        return f"{prefix}-{next_value}"


@dc.dataclass(frozen=True, slots=True)
class ClaimToken:
    """Proof that one invocation won a run's pending-to-running claim.

    ``proof`` is the per-attempt value stored as the run's ``claim_token``; the
    store compares it on every terminal write, so a token is also the writer's
    key to terminate the run. ``run_id`` names the run it belongs to.
    """

    run_id: uuid.UUID
    proof: uuid.UUID | None = None


@dc.dataclass(frozen=True, slots=True)
class ClaimedRun:
    """Generation input loaded after claiming one run.

    ``token`` is the authority this invocation won with; terminal writes name
    it so the store can confirm the writer owns the run.
    """

    run: GenerationRun
    episode: CanonicalEpisode
    sources: tuple[DraftScriptSource, ...]
    presenter_profiles: tuple[DraftPresenterProfile, ...]
    token: ClaimToken


@dc.dataclass(frozen=True, slots=True)
class ClaimedRunResult:
    """One won claim reported as data: the run and its authority token."""

    run: GenerationRun
    token: ClaimToken


#: Source of a per-attempt claim proof. Injecting it lets a test supply a
#: deterministic proof instead of relying on ambient randomness.
type ProofFactory = cabc.Callable[[], uuid.UUID]


@dc.dataclass(slots=True)
class RunClaim:
    """The claim token one launcher invocation holds for the run it drives.

    ``proof`` is a unique per-attempt value stored with the claim, so a lost
    commit acknowledgement is reconciled against an exact attempt rather than
    a timestamp another attempt could share. ``proof_factory`` supplies it, so
    a caller can make the proof deterministic.
    """

    token: ClaimToken | None = None
    proof: uuid.UUID | None = None
    proof_factory: ProofFactory = uuid.uuid4

    def __post_init__(self) -> None:
        """Generate the proof from the factory when none was supplied."""
        if self.proof is None:
            self.proof = self.proof_factory()


@dc.dataclass(frozen=True, slots=True)
class FailureWrite:
    """One authorized failure write: the run, its failure, and any draft."""

    run_id: uuid.UUID
    failure: Failure
    draft: DraftScriptResult | None


@dc.dataclass(frozen=True, slots=True)
class FailureWriteResult:
    """Outcome of a failure write attempt."""

    written: bool
    token: ClaimToken | None = None


@dc.dataclass(frozen=True, slots=True)
class PersistedTei:
    """TEI persistence details needed by success event recording."""

    revision: int
    content_hash: str | None


async def require_episode(
    uow: CanonicalUnitOfWork,
    episode_id: uuid.UUID,
) -> CanonicalEpisode:
    """Return an episode or raise the episode-not-found error."""
    episode = await uow.episodes.get(episode_id)
    if episode is None:
        raise EpisodeNotFoundError(episode_id)
    return episode


def draft_request(
    *,
    claimed: ClaimedRun,
    clock: Clock,
    id_factory_factory: DraftIdFactoryFactory,
) -> DraftScriptRequest:
    """Build a draft-generation request from claimed run data."""
    return DraftScriptRequest(
        episode_id=claimed.run.episode_id,
        series_profile_id=claimed.episode.series_profile_id,
        title=claimed.episode.title,
        sources=claimed.sources,
        presenter_profiles=claimed.presenter_profiles,
        clock=clock,
        id_factory=id_factory_factory(),
    )
