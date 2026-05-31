"""Architecture tests for concrete adapter port conformance."""

import inspect
import typing as typ

import httpx
import pytest

from episodic.canonical.adapters.normalizer import InMemorySourceNormalizer
from episodic.canonical.adapters.resolver import HighestWeightConflictResolver
from episodic.canonical.adapters.weighting import DefaultWeightingStrategy
from episodic.canonical.ingestion_ports import (
    ConflictResolver,
    SourceNormalizer,
    WeightingStrategy,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
from episodic.llm.openai_adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)
from episodic.llm.ports import LLMPort

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_sqlalchemy_unit_of_work_satisfies_canonical_port(
    session_factory: object,
) -> None:
    """The SQLAlchemy UoW exposes the canonical persistence port surface."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)

    async with SqlAlchemyUnitOfWork(factory) as uow:
        assert isinstance(uow, CanonicalUnitOfWork), "uow must be a CanonicalUnitOfWork"
        assert inspect.iscoroutinefunction(uow.commit), "uow.commit must be a coroutine"
        assert inspect.iscoroutinefunction(uow.rollback), (
            "uow.rollback must be a coroutine"
        )
        assert inspect.iscoroutinefunction(uow.flush), "uow.flush must be a coroutine"
        assert uow.series_profiles is not None, "uow.series_profiles must be exposed"
        assert uow.reference_bindings is not None, (
            "uow.reference_bindings must be exposed"
        )


def test_ingestion_adapters_satisfy_public_ports() -> None:
    """Concrete ingestion adapters satisfy their public protocol contracts."""
    normalizer = InMemorySourceNormalizer()
    weighting_strategy = DefaultWeightingStrategy(min_parallel_items=999_999)
    resolver = HighestWeightConflictResolver()

    assert isinstance(normalizer, SourceNormalizer), (
        "normalizer must be a SourceNormalizer"
    )
    assert inspect.iscoroutinefunction(normalizer.normalize), (
        "normalizer.normalize must be a coroutine"
    )
    assert isinstance(weighting_strategy, WeightingStrategy), (
        "weighting_strategy must be a WeightingStrategy"
    )
    assert inspect.iscoroutinefunction(weighting_strategy.compute_weights), (
        "weighting_strategy.compute_weights must be a coroutine"
    )
    assert isinstance(resolver, ConflictResolver), "resolver must be a ConflictResolver"
    assert inspect.iscoroutinefunction(resolver.resolve), (
        "resolver.resolve must be a coroutine"
    )


@pytest.mark.asyncio
async def test_openai_compatible_adapter_satisfies_llm_port() -> None:
    """The OpenAI-compatible adapter exposes the provider-neutral LLM port."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
        base_url="https://example.test/v1",
    ) as client:
        adapter = OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url="https://example.test/v1",
                api_key="test-key",
            ),
            client=client,
        )

        assert isinstance(adapter, LLMPort), "adapter must be an LLMPort"
        assert inspect.iscoroutinefunction(adapter.generate), (
            "adapter.generate must be a coroutine"
        )
