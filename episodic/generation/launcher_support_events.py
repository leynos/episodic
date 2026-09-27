"""Map draft-script results and failures onto events, cost, and error records.

The event-payload and provider-record helpers translate ``DraftScriptResult``
usage, provider metadata, and content hashes into generation event payloads
and the ``CostRecorderPort`` contract's ``ProviderCallRecord``.
``classify_failure`` preserves stable terminal failure categories for the API
and metrics. These helpers accept the canonical unit of work and outbound
ports supplied by the launcher; they do not open, commit, or dispose
persistence sessions themselves.
"""

import dataclasses as dc
import typing as typ

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
from episodic.cost.recorder import ProviderCallRecord
from episodic.generation.draft_script import (
    DraftScriptGenerationError,
    DraftScriptProviderResponseError,
    DraftScriptResponseFormatError,
    DraftScriptResult,
    DraftScriptTeiError,
    DraftScriptTokenBudgetError,
    DraftScriptTransientProviderError,
)
from episodic.generation.launcher_support_sources import GenerationSourceLimitError

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from episodic.canonical.domain import JsonMapping


@dc.dataclass(frozen=True, slots=True)
class Failure:
    """Stable failure details recorded on a terminal run."""

    message: str
    category: str
    should_emit_invalid_tei: bool = False


@dc.dataclass(frozen=True, slots=True)
class ProviderCallRecordRequest:
    """Inputs required to build one provider-call cost record."""

    run_id: uuid.UUID
    provider_name: str
    provider_operation: str
    billing_period_key: BillingPeriodKey
    result: DraftScriptResult
    recorded_at: dt.datetime


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
