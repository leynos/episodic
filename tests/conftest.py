"""Pytest fixtures for database-backed tests.

These fixtures follow the py-pglite approach documented in
`docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`.

Examples
--------
Run database-backed tests with py-pglite:

>>> EPISODIC_TEST_DB=pglite pytest -k canonical
"""

import asyncio
import contextlib
import datetime as dt  # noqa: TC003
import json
import os
import typing as typ
import uuid

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
import sqlalchemy.exc as sa_exc

from episodic.canonical.storage.alembic_helpers import apply_migrations
from episodic.canonical.storage.models import Base
from episodic.llm import (
    LLMProviderOperation,
    LLMRequest,
    LLMTokenBudget,
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)

if typ.TYPE_CHECKING:
    from pathlib import Path

    from falcon import testing
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from episodic.canonical.domain import (
        CanonicalEpisode,
        EpisodeTemplate,
        ReferenceDocument,
        ReferenceDocumentRevision,
        SeriesProfile,
        TeiHeader,
    )
    from episodic.canonical.ingestion_service import IngestionPipeline
    from episodic.canonical.ports import CanonicalUnitOfWork
    from openai_test_types import (
        _OpenAIAdapterFactory,
        _OpenAIInvalidConfigBuilder,
        _OpenAIJsonResponseBuilder,
        _OpenAIRequestBuilder,
    )

try:
    from py_pglite import PGliteConfig, PGliteManager

    _PGLITE_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    _PGLITE_AVAILABLE = False

_OPENAI_TEST_BASE_URL = "https://example.test/v1"
_OPENAI_TEST_API_KEY = "test-key"


def _should_use_pglite() -> bool:
    """Return True when tests should attempt py-pglite.

    If a non-SQLite backend is requested but py-pglite is unavailable,
    fail fast with a clear error instead of silently skipping tests.
    """
    target = os.getenv("EPISODIC_TEST_DB", "pglite").lower()
    if target == "sqlite":
        return False
    if not _PGLITE_AVAILABLE:
        msg = (
            "Database-backed tests requested via EPISODIC_TEST_DB="
            f"{target!r}, but py-pglite is not installed or unavailable. "
            "Install py-pglite (see docs/testing-sqlalchemy-with-pytest-and-"
            "py-pglite.md) or set EPISODIC_TEST_DB=sqlite."
        )
        raise RuntimeError(msg)
    return True


@contextlib.asynccontextmanager
async def _pglite_engine(tmp_path: Path) -> typ.AsyncIterator[AsyncEngine]:
    """Start a py-pglite Postgres and yield an async engine bound to it."""
    if not _PGLITE_AVAILABLE:  # pragma: no cover - defensive guard
        msg = "py-pglite is not available for test fixtures."
        raise RuntimeError(msg)

    work_dir = tmp_path / "pglite"
    config = PGliteConfig(work_dir=work_dir)

    with PGliteManager(config):
        from sqlalchemy.ext.asyncio import create_async_engine

        dsn = config.get_connection_string()
        engine = create_async_engine(dsn, pool_pre_ping=True)
        try:
            await _wait_for_engine_ready(engine)
            yield engine
        finally:
            await engine.dispose()


async def _wait_for_engine_ready(engine: AsyncEngine) -> None:
    """Wait for py-pglite to accept SQLAlchemy connections.

    Under xdist parallel workers, py-pglite can report startup before the
    socket is ready for the first connection. This retry keeps tests stable.
    """
    max_attempts = 30
    delay_seconds = 0.1
    for attempt in range(1, max_attempts + 1):
        try:
            async with engine.connect() as connection:
                await connection.execute(sa.text("SELECT 1"))
        except sa_exc.OperationalError:
            if attempt == max_attempts:
                raise
            await asyncio.sleep(delay_seconds)
        else:
            return


@contextlib.contextmanager
def temporary_drift_table() -> typ.Iterator[sa.Table]:
    """Add a temporary table to Base.metadata and remove it on exit.

    This helper is shared between the unit tests and BDD steps that
    verify schema drift detection against an unmigrated table.
    """
    table = sa.Table(
        "_test_drift_table",
        Base.metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )
    try:
        yield table
    finally:
        Base.metadata.remove(table)


@pytest_asyncio.fixture
async def pglite_engine(tmp_path: Path) -> typ.AsyncIterator[AsyncEngine]:
    """Yield an async engine backed by py-pglite Postgres."""
    if not _should_use_pglite():
        pytest.skip("EPISODIC_TEST_DB=sqlite disables py-pglite-backed fixtures.")

    async with _pglite_engine(tmp_path) as engine:
        yield engine


@pytest.fixture
def _function_scoped_runner() -> typ.Iterator[asyncio.Runner]:
    """Provide a function-scoped asyncio.Runner for sync BDD steps."""
    with asyncio.Runner() as runner:
        yield runner


@pytest.fixture
def openai_request_builder() -> _OpenAIRequestBuilder:
    """Build representative OpenAI-adapter requests for unit tests."""

    def _build_request(
        *,
        operation: str | LLMProviderOperation = "chat_completions",
        prompt: str = "Draft the episode opener.",
    ) -> LLMRequest:
        return LLMRequest(
            model="gpt-4o-mini",
            prompt=prompt,
            system_prompt="Keep the output factual and concise.",
            provider_operation=operation,
            token_budget=LLMTokenBudget(
                max_input_tokens=400,
                max_output_tokens=200,
                max_total_tokens=500,
            ),
        )

    return _build_request


@pytest.fixture
def openai_json_response() -> _OpenAIJsonResponseBuilder:
    """Build JSON HTTPX responses for OpenAI-adapter tests."""

    def _json_response(
        payload: dict[str, object],
        status_code: int = 200,
    ) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode("utf-8"),
        )

    return _json_response


@pytest.fixture
def openai_invalid_config_builder() -> _OpenAIInvalidConfigBuilder:
    """Build invalid OpenAI adapter configs for parametrized tests."""

    def _build_invalid_config(
        config_kwargs: dict[str, object],
    ) -> OpenAICompatibleLLMConfig:
        allowed_keys = {
            "api_key",
            "base_url",
            "max_attempts",
            "provider_operation",
            "retry_delay_seconds",
            "timeout_seconds",
        }
        unexpected_keys = set(config_kwargs) - allowed_keys
        if unexpected_keys:
            msg = (
                f"Unsupported OpenAI config override keys: {sorted(unexpected_keys)!r}"
            )
            raise ValueError(msg)
        merged_config = {
            "base_url": _OPENAI_TEST_BASE_URL,
            "api_key": _OPENAI_TEST_API_KEY,
            "timeout_seconds": 30.0,
            **config_kwargs,
        }
        return OpenAICompatibleLLMConfig(
            base_url=typ.cast("str", merged_config["base_url"]),
            api_key=typ.cast("str", merged_config["api_key"]),
            provider_operation=typ.cast(
                "str | LLMProviderOperation",
                merged_config.get("provider_operation", "chat_completions"),
            ),
            timeout_seconds=typ.cast("float", merged_config["timeout_seconds"]),
            max_attempts=typ.cast("int", merged_config.get("max_attempts", 3)),
            retry_delay_seconds=typ.cast(
                "float", merged_config.get("retry_delay_seconds", 0.5)
            ),
        )

    return _build_invalid_config


@pytest.fixture
def openai_adapter_factory() -> _OpenAIAdapterFactory:
    """Build async context managers yielding configured OpenAI adapters."""

    @contextlib.asynccontextmanager
    async def _build_adapter(  # noqa: PLR0913  # TODO(@codex): mirrors config overrides across tests; see https://github.com/leynos/episodic/pull/49
        *,
        transport: httpx.AsyncBaseTransport,
        provider_operation: str | LLMProviderOperation = "chat_completions",
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.5,
        timeout_seconds: float = 30.0,
    ) -> typ.AsyncIterator[OpenAICompatibleLLMAdapter]:
        async with httpx.AsyncClient(
            transport=transport,
            base_url=_OPENAI_TEST_BASE_URL,
        ) as client:
            yield OpenAICompatibleLLMAdapter(
                config=OpenAICompatibleLLMConfig(
                    base_url=_OPENAI_TEST_BASE_URL,
                    api_key=_OPENAI_TEST_API_KEY,
                    provider_operation=provider_operation,
                    max_attempts=max_attempts,
                    retry_delay_seconds=retry_delay_seconds,
                    timeout_seconds=timeout_seconds,
                ),
                client=client,
            )

    return _build_adapter


@pytest_asyncio.fixture
async def migrated_engine(
    pglite_engine: AsyncEngine,
) -> typ.AsyncIterator[AsyncEngine]:
    """Yield a py-pglite engine with migrations applied."""
    await apply_migrations(pglite_engine)
    yield pglite_engine


@pytest.fixture
def session_factory(
    migrated_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Yield an async session factory bound to the migrated engine."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    return async_sessionmaker(
        migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest_asyncio.fixture
async def series_profile_for_ingestion(
    session_factory: typ.Callable[[], AsyncSession],
) -> SeriesProfile:
    """Create and persist a series profile for ingestion integration tests.

    Parameters
    ----------
    session_factory : Callable[[], AsyncSession]
        Factory that returns an async SQLAlchemy session bound to the
        migrated test database.

    Returns
    -------
    SeriesProfile
        Persisted series profile instance used by ingestion integration
        tests.
    """
    import datetime as dt

    from episodic.canonical.domain import SeriesProfile
    from episodic.canonical.storage import SqlAlchemyUnitOfWork

    now = dt.datetime.now(dt.UTC)
    profile = SeriesProfile(
        id=uuid.uuid4(),
        slug=f"test-series-{uuid.uuid4().hex[:8]}",
        title="Test Series",
        description=None,
        configuration={"tone": "neutral"},
        guardrails={},
        created_at=now,
        updated_at=now,
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.series_profiles.add(profile)
        await uow.commit()
    return profile


@pytest_asyncio.fixture
async def ingestion_pipeline() -> IngestionPipeline:
    """Build the standard multi-source ingestion pipeline for tests.

    Parameters
    ----------
    None

    Returns
    -------
    IngestionPipeline
        The ``ingestion_pipeline`` fixture instance configured with
        ``InMemorySourceNormalizer``, ``DefaultWeightingStrategy``, and
        ``HighestWeightConflictResolver``.
    """
    # Yield control once so async fixture setup is consistently scheduled.
    await asyncio.sleep(0)

    from episodic.canonical.adapters.normalizer import InMemorySourceNormalizer
    from episodic.canonical.adapters.resolver import HighestWeightConflictResolver
    from episodic.canonical.adapters.weighting import DefaultWeightingStrategy
    from episodic.canonical.ingestion_service import IngestionPipeline

    return IngestionPipeline(
        normalizer=InMemorySourceNormalizer(),
        weighting=DefaultWeightingStrategy(),
        resolver=HighestWeightConflictResolver(),
    )


@pytest_asyncio.fixture
async def pglite_session(
    migrated_engine: AsyncEngine,
) -> typ.AsyncIterator[AsyncSession]:
    """Yield an async SQLAlchemy session bound to py-pglite."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_factory = async_sessionmaker(
        migrated_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
def canonical_api_client(
    session_factory: async_sessionmaker[AsyncSession],
) -> testing.TestClient:
    """Build a Falcon test client for profile/template REST endpoints."""
    from falcon import testing

    from episodic.api import create_app
    from episodic.canonical.storage import SqlAlchemyUnitOfWork

    app = create_app(lambda: SqlAlchemyUnitOfWork(session_factory))
    return testing.TestClient(app)


# Binding resolution test helpers and fixtures


def create_series_for_binding_tests(now: dt.datetime) -> SeriesProfile:
    """Create and return a series profile for binding resolution tests."""
    from episodic.canonical.domain import SeriesProfile

    return SeriesProfile(
        id=uuid.uuid4(),
        title="Resolution Test Series",
        slug="resolution-test",
        description="Series for resolution tests",
        configuration={},
        guardrails={},
        created_at=now,
        updated_at=now,
    )


def create_episodes_with_headers_for_binding_tests(
    series_id: uuid.UUID, now: dt.datetime
) -> tuple[CanonicalEpisode, CanonicalEpisode, CanonicalEpisode, list[TeiHeader]]:
    """Create three episodes with staggered timestamps and their TEI headers."""
    import datetime as dt

    from episodic.canonical.domain import (
        ApprovalState,
        CanonicalEpisode,
        EpisodeStatus,
        TeiHeader,
    )

    episode_early = CanonicalEpisode(
        id=uuid.uuid4(),
        series_profile_id=series_id,
        tei_header_id=uuid.uuid4(),
        title="Early Episode",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now - dt.timedelta(days=10),
        updated_at=now - dt.timedelta(days=10),
    )
    episode_middle = CanonicalEpisode(
        id=uuid.uuid4(),
        series_profile_id=series_id,
        tei_header_id=uuid.uuid4(),
        title="Middle Episode",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now - dt.timedelta(days=5),
        updated_at=now - dt.timedelta(days=5),
    )
    episode_late = CanonicalEpisode(
        id=uuid.uuid4(),
        series_profile_id=series_id,
        tei_header_id=uuid.uuid4(),
        title="Late Episode",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )

    headers = [
        TeiHeader(
            id=ep.tei_header_id,
            title=ep.title,
            payload={"file_desc": {"title": ep.title}},
            raw_xml="<teiHeader/>",
            created_at=ep.created_at,
            updated_at=ep.updated_at,
        )
        for ep in [episode_early, episode_middle, episode_late]
    ]

    return episode_early, episode_middle, episode_late, headers


def create_reference_document_for_binding_tests(
    series_id: uuid.UUID, now: dt.datetime
) -> ReferenceDocument:
    """Create and return a reference document for binding resolution tests."""
    from episodic.canonical.domain import (
        ReferenceDocument,
        ReferenceDocumentKind,
        ReferenceDocumentLifecycleState,
    )

    return ReferenceDocument(
        id=uuid.uuid4(),
        owner_series_profile_id=series_id,
        kind=ReferenceDocumentKind.STYLE_GUIDE,
        lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
        metadata={},
        created_at=now,
        updated_at=now,
        lock_version=1,
    )


def create_revisions_for_binding_tests(
    doc_id: uuid.UUID, now: dt.datetime
) -> tuple[
    ReferenceDocumentRevision, ReferenceDocumentRevision, ReferenceDocumentRevision
]:
    """Create and return three revisions with staggered timestamps."""
    import datetime as dt

    from episodic.canonical.domain import ReferenceDocumentRevision

    revision_v1 = ReferenceDocumentRevision(
        id=uuid.uuid4(),
        reference_document_id=doc_id,
        content={"version": "1", "rules": ["rule1"]},
        content_hash="hash-v1",
        author="editor",
        change_note="Initial version",
        created_at=now - dt.timedelta(days=15),
    )
    revision_v2 = ReferenceDocumentRevision(
        id=uuid.uuid4(),
        reference_document_id=doc_id,
        content={"version": "2", "rules": ["rule1", "rule2"]},
        content_hash="hash-v2",
        author="editor",
        change_note="Added rule2",
        created_at=now - dt.timedelta(days=8),
    )
    revision_v3 = ReferenceDocumentRevision(
        id=uuid.uuid4(),
        reference_document_id=doc_id,
        content={"version": "3", "rules": ["rule1", "rule2", "rule3"]},
        content_hash="hash-v3",
        author="editor",
        change_note="Added rule3",
        created_at=now - dt.timedelta(days=2),
    )
    return revision_v1, revision_v2, revision_v3


async def create_episode_template_for_binding_tests(
    uow: CanonicalUnitOfWork, series_id: uuid.UUID, now: dt.datetime
) -> EpisodeTemplate:
    """Create, persist, commit, and return an episode template for testing."""
    from episodic.canonical.domain import EpisodeTemplate

    template = EpisodeTemplate(
        id=uuid.uuid4(),
        series_profile_id=series_id,
        slug="test-template",
        title="Test Template",
        description=None,
        structure={},
        guardrails={},
        created_at=now,
        updated_at=now,
    )
    await uow.episode_templates.add(template)
    await uow.commit()
    return template


class BindingFixtures(typ.TypedDict):
    """Type definition for uow_with_binding_fixtures fixture."""

    uow: CanonicalUnitOfWork
    series: SeriesProfile
    episode_early: CanonicalEpisode
    episode_middle: CanonicalEpisode
    episode_late: CanonicalEpisode
    doc: ReferenceDocument
    revision_v1: ReferenceDocumentRevision
    revision_v2: ReferenceDocumentRevision
    revision_v3: ReferenceDocumentRevision
    now: dt.datetime


@pytest_asyncio.fixture
async def uow_with_binding_fixtures(
    session_factory: async_sessionmaker[AsyncSession],
) -> typ.AsyncIterator[BindingFixtures]:
    """Provide UOW with series, episodes, reference documents, and revisions."""
    import datetime as dt

    from episodic.canonical.storage.uow import SqlAlchemyUnitOfWork

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        now = dt.datetime.now(tz=dt.UTC)

        series = create_series_for_binding_tests(now)
        await uow.series_profiles.add(series)
        await uow.flush()

        episode_early, episode_middle, episode_late, headers = (
            create_episodes_with_headers_for_binding_tests(series.id, now)
        )
        for ep, header in zip(
            [episode_early, episode_middle, episode_late], headers, strict=True
        ):
            await uow.tei_headers.add(header)
            await uow.flush()
            await uow.episodes.add(ep)

        doc = create_reference_document_for_binding_tests(series.id, now)
        await uow.reference_documents.add(doc)

        revision_v1, revision_v2, revision_v3 = create_revisions_for_binding_tests(
            doc.id, now
        )
        for rev in [revision_v1, revision_v2, revision_v3]:
            await uow.reference_document_revisions.add(rev)

        await uow.commit()

        yield {
            "uow": uow,
            "series": series,
            "episode_early": episode_early,
            "episode_middle": episode_middle,
            "episode_late": episode_late,
            "doc": doc,
            "revision_v1": revision_v1,
            "revision_v2": revision_v2,
            "revision_v3": revision_v3,
            "now": now,
        }
