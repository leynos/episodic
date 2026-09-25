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
import datetime as dt
import typing as typ

from episodic.canonical.episode_errors import EpisodeNotFoundError
from episodic.generation.draft_script import (
    DraftPresenterProfile,
    DraftScriptRequest,
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
    GenerationSourceLimitError,
    GenerationSourceLimits,
    source_from_document,
)

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.domain import CanonicalEpisode, GenerationRun
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.cost.recorder import CostRecorderPort

type Clock = cabc.Callable[[], dt.datetime]
type DraftIdFactoryFactory = cabc.Callable[[], cabc.Callable[[str], str]]

__all__ = [
    "ClaimedRun",
    "Clock",
    "CostRecorderFactory",
    "DraftIdFactoryFactory",
    "Failure",
    "GenerationSourceLimitError",
    "GenerationSourceLimits",
    "PersistedTei",
    "ProviderCallRecordRequest",
    "SequentialDraftIds",
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
        self._counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        """Return the next identifier for a prefix."""
        next_value = self._counts.get(prefix, 0) + 1
        self._counts[prefix] = next_value
        return f"{prefix}-{next_value}"


@dc.dataclass(frozen=True, slots=True)
class ClaimedRun:
    """Generation input loaded after claiming one run."""

    run: GenerationRun
    episode: CanonicalEpisode
    sources: tuple[DraftScriptSource, ...]
    presenter_profiles: tuple[DraftPresenterProfile, ...]


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
