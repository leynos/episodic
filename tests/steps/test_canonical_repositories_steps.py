"""Behavioural tests for canonical repository and unit-of-work semantics.

Examples
--------
Run the canonical repository BDD scenarios:

>>> pytest tests/steps/test_canonical_repositories_steps.py
"""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest
from pytest_bdd import given, scenario, then, when
from sqlalchemy import exc as sa_exc

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    IngestionJob,
    IngestionStatus,
    SeriesProfile,
    SourceDocument,
    TeiHeader,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession


def _run_async_step(
    runner: asyncio.Runner,
    step_fn: cabc.Callable[[], typ.Coroutine[object, object, None]],
) -> None:
    """Execute an async BDD step via the provided runner."""
    runner.run(step_fn())


class SeriesProfilePayload(typ.TypedDict, total=False):
    """Data required to create a series profile in tests.

    ``slug`` and ``title`` are required.  ``configuration`` defaults
    to ``{}`` when absent.
    """

    slug: typ.Required[str]
    title: typ.Required[str]
    configuration: dict[str, object]


async def _persist_series_profile(
    session_factory: cabc.Callable[[], AsyncSession],
    profile_data: SeriesProfilePayload,
    action: cabc.Callable[[SqlAlchemyUnitOfWork], typ.Awaitable[None]],
) -> SeriesProfile:
    """Create a series profile, add it via the UoW, and run *action*."""
    now = dt.datetime.now(dt.UTC)
    profile = SeriesProfile(
        id=uuid.uuid4(),
        slug=profile_data["slug"],
        title=profile_data["title"],
        description=None,
        configuration=profile_data.get("configuration", {}),
        created_at=now,
        updated_at=now,
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.series_profiles.add(profile)
        await action(uow)

    return profile


class RepositoryContext(typ.TypedDict, total=False):
    """Shared state for canonical repository BDD steps."""

    profile: SeriesProfile
    profile_id: uuid.UUID
    fetched_profile: SeriesProfile | None
    integrity_error_raised: bool
    _job_id: uuid.UUID
    _episode_id: uuid.UUID


# -- Scenario: Repository round-trip persists and retrieves a series profile


@scenario(
    "../features/canonical_repositories.feature",
    "Repository round-trip persists and retrieves a series profile",
)
def test_repository_round_trip() -> None:
    """Run the repository round-trip scenario."""


# -- Scenario: Rolled-back changes are not persisted


@scenario(
    "../features/canonical_repositories.feature",
    "Rolled-back changes are not persisted",
)
def test_rollback_discards_changes() -> None:
    """Run the rollback scenario."""


# -- Scenario: Weight constraint rejects out-of-range values


@scenario(
    "../features/canonical_repositories.feature",
    "Weight constraint rejects out-of-range values",
)
def test_weight_constraint() -> None:
    """Run the weight constraint scenario."""


@pytest.fixture
def context() -> RepositoryContext:
    """Share state between BDD steps."""
    return typ.cast("RepositoryContext", {})


# -- Given steps


@given("a series profile is added via the repository")
def add_series_profile(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: RepositoryContext,
) -> None:
    """Persist a series profile through the repository."""

    async def _store() -> None:
        profile = await _persist_series_profile(
            session_factory,
            {
                "slug": "bdd-round-trip",
                "title": "BDD Round Trip",
                "configuration": {"tone": "neutral"},
            },
            action=lambda uow: uow.commit(),
        )
        context["profile"] = profile
        context["profile_id"] = profile.id

    _run_async_step(_function_scoped_runner, _store)


@given("a series profile is added but the transaction is rolled back")
def add_and_rollback(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: RepositoryContext,
) -> None:
    """Add a series profile and roll back without committing."""

    async def _store_and_rollback() -> None:
        profile = await _persist_series_profile(
            session_factory,
            {"slug": "bdd-rollback", "title": "BDD Rollback", "configuration": {}},
            action=lambda uow: uow.rollback(),
        )
        context["profile"] = profile
        context["profile_id"] = profile.id

    _run_async_step(_function_scoped_runner, _store_and_rollback)


@given("a canonical episode with supporting entities exists")
def episode_with_dependencies(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: RepositoryContext,
) -> None:
    """Set up the entity graph required for a source document."""

    async def _setup() -> None:
        now = dt.datetime.now(dt.UTC)
        series_id = uuid.uuid4()
        header_id = uuid.uuid4()
        episode_id = uuid.uuid4()
        job_id = uuid.uuid4()

        series = SeriesProfile(
            id=series_id,
            slug="bdd-weight-check",
            title="BDD Weight Check",
            description=None,
            configuration={},
            created_at=now,
            updated_at=now,
        )
        header = TeiHeader(
            id=header_id,
            title="Weight Check Header",
            payload={"file_desc": {"title": "Weight Check"}},
            raw_xml="<TEI/>",
            created_at=now,
            updated_at=now,
        )
        episode = CanonicalEpisode(
            id=episode_id,
            series_profile_id=series_id,
            tei_header_id=header_id,
            title="Weight Check Episode",
            tei_xml="<TEI/>",
            status=EpisodeStatus.DRAFT,
            approval_state=ApprovalState.DRAFT,
            created_at=now,
            updated_at=now,
        )
        job = IngestionJob(
            id=job_id,
            series_profile_id=series_id,
            target_episode_id=episode_id,
            status=IngestionStatus.COMPLETED,
            requested_at=now,
            started_at=now,
            completed_at=now,
            error_message=None,
            created_at=now,
            updated_at=now,
        )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.series_profiles.add(series)
            await uow.tei_headers.add(header)
            await uow.commit()

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.episodes.add(episode)
            await uow.ingestion_jobs.add(job)
            await uow.commit()

        # Store IDs for the weight constraint step.
        context["_job_id"] = job_id
        context["_episode_id"] = episode_id

    _run_async_step(_function_scoped_runner, _setup)


# -- When steps


@when("the series profile is fetched by identifier")
def fetch_profile(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: RepositoryContext,
) -> None:
    """Fetch the series profile by its identifier."""

    async def _fetch() -> None:
        profile_id = context["profile_id"]

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            result = await uow.series_profiles.get(profile_id)

        context["fetched_profile"] = result

    _run_async_step(_function_scoped_runner, _fetch)


@when("a source document with weight 1.5 is added")
def add_bad_weight_source(
    _function_scoped_runner: asyncio.Runner,
    session_factory: cabc.Callable[[], AsyncSession],
    context: RepositoryContext,
) -> None:
    """Add a source document with an out-of-range weight."""

    async def _add() -> None:
        now = dt.datetime.now(dt.UTC)
        job_id: uuid.UUID = context["_job_id"]
        episode_id: uuid.UUID = context["_episode_id"]

        bad_source = SourceDocument(
            id=uuid.uuid4(),
            ingestion_job_id=job_id,
            canonical_episode_id=episode_id,
            source_type="web",
            source_uri="https://example.com/bdd-bad-weight",
            weight=1.5,
            content_hash="hash-bdd-bad",
            metadata={},
            created_at=now,
        )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.source_documents.add(bad_source)
            with pytest.raises(
                sa_exc.IntegrityError,
                match=r"(?i)ck_source_documents_weight|check",
            ):
                await uow.commit()
        context["integrity_error_raised"] = True

    _run_async_step(_function_scoped_runner, _add)


# -- Then steps


@then("the fetched profile matches the original")
def profile_matches(context: RepositoryContext) -> None:
    """Verify the fetched profile matches the original."""
    fetched = context["fetched_profile"]
    original = context["profile"]

    assert fetched is not None, "Expected a persisted series profile."
    assert fetched.id == original.id, "Expected the profile id to match."
    assert fetched.slug == original.slug, "Expected the slug to match."
    assert fetched.title == original.title, "Expected the title to match."


@then("no series profile is returned")
def profile_is_none(context: RepositoryContext) -> None:
    """Verify no profile was persisted."""
    assert context["fetched_profile"] is None, "Expected None after rollback."


@then("the commit fails with an integrity error")
def integrity_error_raised(context: RepositoryContext) -> None:
    """Verify an integrity error was raised."""
    assert context["integrity_error_raised"] is True, (
        "Expected an IntegrityError for out-of-range weight."
    )
