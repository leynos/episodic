"""Verify that protocol stub methods raise NotImplementedError."""

import collections.abc as cabc
import typing as typ

import pytest

from episodic.canonical.entity_protocols import (
    ApprovalEventRepository,
    EpisodeRepository,
    EpisodeTemplateRepository,
    IngestionJobRepository,
    SeriesProfileRepository,
    SourceDocumentRepository,
    TeiHeaderRepository,
)
from episodic.canonical.history_protocols import (
    EpisodeTemplateHistoryRepository,
    SeriesProfileHistoryRepository,
)
from episodic.canonical.ingestion_ports import (
    ConflictResolver,
    SourceNormalizer,
    WeightingStrategy,
)
from episodic.canonical.reference_protocols import (
    ReferenceBindingRepository,
    ReferenceDocumentRepository,
    ReferenceDocumentRevisionRepository,
)
from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
from episodic.concurrent_interpreters import CpuTaskExecutor
from episodic.llm.ports import LLMPort
from episodic.qa.langgraph import PedanteEvaluatorPort

_AsyncMethod = cabc.Callable[..., cabc.Awaitable[object]]


def _concrete_protocol_instance(protocol_class: type[object]) -> object:
    """Build a concrete subclass that inherits the protocol stub methods."""
    concrete_class = type(f"Concrete{protocol_class.__name__}", (protocol_class,), {})
    return concrete_class()


async def _assert_async_stub_raises(
    protocol_class: type[object],
    method_name: str,
    *args: object,
    **kwargs: object,
) -> None:
    """Call one inherited async protocol stub and expect NotImplementedError."""
    instance = _concrete_protocol_instance(protocol_class)
    method = typ.cast("_AsyncMethod", getattr(instance, method_name))
    with pytest.raises(NotImplementedError):
        await method(*args, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("protocol_class", "method_name", "args", "kwargs"),
    [
        (SourceNormalizer, "normalize", (None,), {}),
        (WeightingStrategy, "compute_weights", ([], {}), {}),
        (ConflictResolver, "resolve", ([],), {}),
        (CpuTaskExecutor, "map_ordered", (lambda item: item, ()), {}),
        (LLMPort, "generate", (None,), {}),
        (PedanteEvaluatorPort, "evaluate", (None,), {}),
        (SeriesProfileRepository, "add", (None,), {}),
        (SeriesProfileRepository, "get", (None,), {}),
        (SeriesProfileRepository, "get_by_slug", ("slug",), {}),
        (SeriesProfileRepository, "list", (), {}),
        (SeriesProfileRepository, "update", (None,), {}),
        (TeiHeaderRepository, "add", (None,), {}),
        (TeiHeaderRepository, "get", (None,), {}),
        (EpisodeRepository, "add", (None,), {}),
        (EpisodeRepository, "get", (None,), {}),
        (EpisodeRepository, "list_by_ids", ((),), {}),
        (IngestionJobRepository, "add", (None,), {}),
        (IngestionJobRepository, "get", (None,), {}),
        (SourceDocumentRepository, "add", (None,), {}),
        (SourceDocumentRepository, "list_for_job", (None,), {}),
        (ApprovalEventRepository, "add", (None,), {}),
        (ApprovalEventRepository, "list_for_episode", (None,), {}),
        (ReferenceDocumentRepository, "add", (None,), {}),
        (ReferenceDocumentRepository, "get", (None,), {}),
        (ReferenceDocumentRepository, "list_for_series", (None,), {}),
        (ReferenceDocumentRepository, "list_by_ids", ((),), {}),
        (ReferenceDocumentRepository, "update", (None,), {}),
        (
            ReferenceDocumentRepository,
            "update_with_optimistic_lock",
            (None,),
            {"expected_lock_version": 1},
        ),
        (ReferenceDocumentRevisionRepository, "add", (None,), {}),
        (ReferenceDocumentRevisionRepository, "get", (None,), {}),
        (ReferenceDocumentRevisionRepository, "list_for_document", (None,), {}),
        (ReferenceDocumentRevisionRepository, "list_by_ids", ((),), {}),
        (
            ReferenceDocumentRevisionRepository,
            "get_latest_for_document",
            (None,),
            {},
        ),
        (ReferenceBindingRepository, "add", (None,), {}),
        (ReferenceBindingRepository, "get", (None,), {}),
        (
            ReferenceBindingRepository,
            "list_for_target",
            (),
            {"target_kind": None, "target_id": None},
        ),
        (EpisodeTemplateRepository, "add", (None,), {}),
        (EpisodeTemplateRepository, "get", (None,), {}),
        (EpisodeTemplateRepository, "list", (None,), {}),
        (EpisodeTemplateRepository, "get_by_slug", (None, "slug"), {}),
        (EpisodeTemplateRepository, "update", (None,), {}),
        (SeriesProfileHistoryRepository, "add", (None,), {}),
        (SeriesProfileHistoryRepository, "list_for_profile", (None,), {}),
        (SeriesProfileHistoryRepository, "get_latest_for_profile", (None,), {}),
        (
            SeriesProfileHistoryRepository,
            "get_latest_revisions_for_profiles",
            ((),),
            {},
        ),
        (EpisodeTemplateHistoryRepository, "add", (None,), {}),
        (EpisodeTemplateHistoryRepository, "list_for_template", (None,), {}),
        (EpisodeTemplateHistoryRepository, "get_latest_for_template", (None,), {}),
        (
            EpisodeTemplateHistoryRepository,
            "get_latest_revisions_for_templates",
            ((),),
            {},
        ),
        (CanonicalUnitOfWork, "__aenter__", (), {}),
        (CanonicalUnitOfWork, "__aexit__", (None, None, None), {}),
        (CanonicalUnitOfWork, "commit", (), {}),
        (CanonicalUnitOfWork, "flush", (), {}),
        (CanonicalUnitOfWork, "rollback", (), {}),
    ],
)
async def test_protocol_stub_method_raises_not_implemented_error(
    protocol_class: type[object],
    method_name: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> None:
    """Protocol stub methods must fail explicitly when inherited directly."""
    await _assert_async_stub_raises(protocol_class, method_name, *args, **kwargs)
