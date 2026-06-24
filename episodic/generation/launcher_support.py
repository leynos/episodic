"""Support types for in-process generation-run launching."""

from __future__ import annotations

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import typing as typ

from episodic.canonical.generation_persistence import InvalidDraftTeiError
from episodic.canonical.generation_run_errors import RunNotFound
from episodic.cost.ports import (
    BillingPeriodKey,
    IdempotencyKey,
    PricingModel,
    UsageSource,
)
from episodic.cost.recorder import CostProviderOperation, ProviderCallRecord
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
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork

Clock = cabc.Callable[[], dt.datetime]
DraftIdFactoryFactory = cabc.Callable[[], cabc.Callable[[str], str]]


class CostRecorderPort(typ.Protocol):
    """Cost-recorder surface used by the launcher."""

    async def pin_run_pricing(
        self,
        workflow_run_id: str,
        providers: tuple[CostProviderOperation, ...],
        billing_period_key: BillingPeriodKey,
    ) -> None:
        """Pin pricing for a workflow run."""

    async def record_provider_call(
        self,
        record: ProviderCallRecord,
    ) -> object:
        """Record one provider call."""

    async def finalize_run(
        self,
        workflow_run_id: str,
        workflow_node: str | None,
    ) -> object:
        """Record the run roll-up."""


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
    """Return an episode or raise the run-not-found error family."""
    episode = await uow.episodes.get(episode_id)
    if episode is None:
        raise RunNotFound(episode_id)
    return episode


def source_from_document(document: SourceDocument) -> DraftScriptSource:
    """Build generator source input from canonical source provenance."""
    metadata_content = document.metadata.get("content")
    content = (
        metadata_content.strip()
        if isinstance(metadata_content, str) and metadata_content.strip()
        else document.source_uri
    )
    return DraftScriptSource(
        source_id=str(document.id),
        source_type=document.source_type,
        source_uri=document.source_uri,
        content=content,
        weight=document.weight,
    )


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
