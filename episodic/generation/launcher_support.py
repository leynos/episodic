"""Support types for in-process generation-run launching."""

from __future__ import annotations

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import json
import typing as typ

from episodic.canonical.domain import ReferenceDocumentKind
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
    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.reference_documents.resolution import ResolvedBinding
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


async def source_from_document(
    document: SourceDocument,
    object_store: ObjectStorePort | None,
) -> DraftScriptSource:
    """Build generator source input from canonical source provenance."""
    metadata_content = document.metadata.get("content")
    if isinstance(metadata_content, str) and metadata_content.strip():
        content = metadata_content.strip()
    elif document.source_uri.startswith("upload:"):
        content = await _read_uploaded_source(document.source_uri, object_store)
    else:
        content = document.source_uri
    return DraftScriptSource(
        source_id=str(document.id),
        source_type=document.source_type,
        source_uri=document.source_uri,
        content=content,
        weight=document.weight,
    )


async def _read_uploaded_source(
    source_uri: str,
    object_store: ObjectStorePort | None,
) -> str:
    """Read and normalize UTF-8 source text from an upload provenance URI."""
    if object_store is None:
        msg = "An object store is required to load uploaded source content."
        raise DraftScriptGenerationError(msg)
    key = source_uri.removeprefix("upload:")
    async with object_store.open(key) as chunks:
        payload = b"".join([chunk async for chunk in chunks])
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        msg = f"Uploaded source {key!r} is not valid UTF-8 text."
        raise DraftScriptGenerationError(msg) from exc
    normalized = "\n".join(content.splitlines()).strip()
    if not normalized:
        msg = f"Uploaded source {key!r} contains no text."
        raise DraftScriptGenerationError(msg)
    return normalized


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
