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
"""

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import json
import typing as typ

from episodic.canonical.domain import ReferenceDocumentKind
from episodic.canonical.episode_errors import (
    EpisodeNotFoundError,
    EpisodeRevisionConflictError,
)
from episodic.canonical.generation_persistence import InvalidDraftTeiError
from episodic.cost.ports import (
    BillingPeriodKey,
    IdempotencyKey,
    PricingModel,
    UsageSource,
)
from episodic.cost.recorder import (
    CostRecorderPort,
    ProviderCallRecord,
)
from episodic.generation.draft_script import (
    DraftPresenterProfile,
    DraftScriptGenerationError,
    DraftScriptProviderResponseError,
    DraftScriptRequest,
    DraftScriptResponseFormatError,
    DraftScriptResult,
    DraftScriptSource,
    DraftScriptTeiError,
    DraftScriptTokenBudgetError,
    DraftScriptTransientProviderError,
)

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.domain import (
        CanonicalEpisode,
        GenerationRun,
        JsonMapping,
        SourceDocument,
    )
    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.reference_documents.resolution import ResolvedBinding
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork

type Clock = cabc.Callable[[], dt.datetime]
type DraftIdFactoryFactory = cabc.Callable[[], cabc.Callable[[str], str]]

_DEFAULT_MAX_SOURCE_COUNT = 32
_DEFAULT_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_DEFAULT_MAX_AGGREGATE_SOURCE_BYTES = 8 * 1024 * 1024
_DEFAULT_MAX_NORMALIZED_SOURCE_BYTES = 2 * 1024 * 1024


@dc.dataclass(frozen=True, slots=True)
class GenerationSourceLimits:
    """Validated bounds applied while building one draft's source input.

    Attributes
    ----------
    max_source_count : int
        Maximum number of source documents accepted for one draft.
    max_source_bytes : int
        Maximum bytes retained from one source document.
    max_aggregate_source_bytes : int
        Maximum bytes retained across all source documents.
    max_normalized_source_bytes : int
        Maximum UTF-8 bytes after source-text normalisation.

    Raises
    ------
    ValueError
        If any configured bound is less than one.
    """

    max_source_count: int = _DEFAULT_MAX_SOURCE_COUNT
    max_source_bytes: int = _DEFAULT_MAX_SOURCE_BYTES
    max_aggregate_source_bytes: int = _DEFAULT_MAX_AGGREGATE_SOURCE_BYTES
    max_normalized_source_bytes: int = _DEFAULT_MAX_NORMALIZED_SOURCE_BYTES

    def __post_init__(self) -> None:
        """Reject non-positive limits before a launcher begins work."""
        for name, value in dc.asdict(self).items():
            if value < 1:
                msg = f"{name} must be at least 1."
                raise ValueError(msg)


class GenerationSourceLimitError(DraftScriptGenerationError):
    """Raised when bounded generation source input exceeds a configured limit.

    This translated generation error keeps limit rejections stable and free of
    source content, identifiers, and byte counts.
    """

    @classmethod
    def source_count(cls) -> GenerationSourceLimitError:
        """Build the stable source-count rejection."""
        message = "Generation source count exceeds limit."
        return cls(message)

    @classmethod
    def source_bytes(cls) -> GenerationSourceLimitError:
        """Build the stable per-source byte rejection."""
        message = "Generation source exceeds byte limit."
        return cls(message)

    @classmethod
    def aggregate_bytes(cls) -> GenerationSourceLimitError:
        """Build the stable aggregate-byte rejection."""
        message = "Generation source aggregate exceeds byte limit."
        return cls(message)

    @classmethod
    def normalized_bytes(cls) -> GenerationSourceLimitError:
        """Build the stable normalized-text rejection."""
        message = "Generation source exceeds normalized limit."
        return cls(message)


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
class Failure:
    """Stable failure details recorded on a terminal run."""

    message: str
    category: str
    should_emit_invalid_tei: bool = False


@dc.dataclass(frozen=True, slots=True)
class PersistedTei:
    """TEI persistence details needed by success event recording."""

    revision: int
    content_hash: str | None


@dc.dataclass(frozen=True, slots=True)
class ProviderCallRecordRequest:
    """Inputs required to build one provider-call cost record."""

    run_id: uuid.UUID
    provider_name: str
    provider_operation: str
    billing_period_key: BillingPeriodKey
    result: DraftScriptResult
    recorded_at: dt.datetime


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


def project_presenter_profiles(
    resolved_bindings: list[ResolvedBinding],
) -> tuple[DraftPresenterProfile, ...]:
    """Project resolved host and guest revisions into draft input records."""
    presenter_kinds = {
        ReferenceDocumentKind.HOST_PROFILE,
        ReferenceDocumentKind.GUEST_PROFILE,
    }
    profiles: list[DraftPresenterProfile] = []
    for resolved in resolved_bindings:
        if resolved.document.kind not in presenter_kinds:
            continue
        content = resolved.revision.content
        metadata = resolved.document.metadata
        display_name = _first_string(content, "display_name", "name", "title")
        display_name = display_name or _first_string(
            metadata, "display_name", "name", "title"
        )
        source_content = _first_string(
            content,
            "source_content",
            "profile",
            "bio",
            "biography",
            "summary",
            "content",
            "text",
        )
        profiles.append(
            DraftPresenterProfile(
                display_name=display_name or str(resolved.document.id),
                role=resolved.document.kind.value.removesuffix("_profile"),
                source_content=source_content or json.dumps(content, sort_keys=True),
            )
        )
    return tuple(profiles)


def _first_string(values: cabc.Mapping[str, object], *keys: str) -> str | None:
    """Return the first non-empty string from the requested mapping keys."""
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def draft_generated_payload(result: DraftScriptResult) -> JsonMapping:
    """Build the draft-generated event payload."""
    return {
        "model": result.model,
        "provider_response_id": result.provider_response_id,
        "finish_reason": result.finish_reason,
        "content_hash": result.content_hash,
        "usage": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "total_tokens": result.usage.total_tokens,
        },
    }


def provider_call_record(request: ProviderCallRecordRequest) -> ProviderCallRecord:
    """Build a provider-call record from a draft result."""
    usage = request.result.provider_call_usage
    usage_metrics = (
        dict(usage.usage_metrics)
        if usage is not None
        else {
            "input_tokens": request.result.usage.input_tokens,
            "output_tokens": request.result.usage.output_tokens,
        }
    )
    usage_source = usage.usage_source if usage is not None else UsageSource.PROVIDER
    usage_complete = usage.usage_complete if usage is not None else True
    return ProviderCallRecord(
        idempotency_key=IdempotencyKey(
            f"run:{request.run_id}:node:draft:call:"
            f"{request.result.provider_response_id}:attempt:0"
        ),
        parent_cost_entry_id=None,
        provider_type="llm",
        provider_name=request.provider_name,
        model=request.result.model,
        workflow_node="draft",
        operation=request.provider_operation,
        usage=usage_metrics,
        usage_source=usage_source,
        usage_complete=usage_complete,
        pricing_model=PricingModel.PAYG,
        retry_attempt=0,
        billing_period_key=request.billing_period_key,
        workflow_run_id=str(request.run_id),
        recorded_at=request.recorded_at.isoformat(),
    )


_FAILURE_CATEGORIES: tuple[
    tuple[type[Exception] | tuple[type[Exception], ...], str, bool],
    ...,
] = (
    (EpisodeRevisionConflictError, "episode.persistence_conflict", False),
    (EpisodeNotFoundError, "episode.not_found", False),
    (GenerationSourceLimitError, "generation.source_limit", False),
    ((InvalidDraftTeiError, DraftScriptTeiError), "tei.invalid", True),
    (DraftScriptTransientProviderError, "provider.transient", False),
    (DraftScriptProviderResponseError, "provider.response", False),
    (DraftScriptTokenBudgetError, "provider.token_budget", False),
    (DraftScriptResponseFormatError, "draft.response_format", False),
    (DraftScriptGenerationError, "draft.generation", False),
)


def classify_failure(exc: Exception) -> Failure:
    """Map launcher failures to stable public error categories."""
    for error_type, category, should_emit_invalid_tei in _FAILURE_CATEGORIES:
        if isinstance(exc, error_type):
            return Failure(
                str(exc),
                category,
                should_emit_invalid_tei=should_emit_invalid_tei,
            )
    return Failure(str(exc), "unexpected")


async def source_from_document(
    document: SourceDocument,
    object_store: ObjectStorePort | None,
    limits: GenerationSourceLimits | None = None,
    *,
    remaining_aggregate_bytes: int | None = None,
) -> DraftScriptSource:
    """Build bounded draft source input from canonical document provenance."""
    from episodic.generation.launcher_sources import source_from_document as source

    return await source(
        document,
        object_store,
        limits,
        remaining_aggregate_bytes=remaining_aggregate_bytes,
    )
