"""Shared helpers for multi-source ingestion BDD steps."""

import typing as typ

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc
    import uuid

    from episodic.canonical.domain import CanonicalEpisode, SeriesProfile
    from episodic.canonical.ingestion import RawSourceInput


def run_async_step(
    runner: asyncio.Runner,
    step_fn: cabc.Callable[[], typ.Awaitable[None]],
) -> None:
    """Execute an async BDD step via the provided runner."""
    coro = typ.cast("typ.Coroutine[object, object, None]", step_fn())
    runner.run(coro)


class MultiSourceContext(typ.TypedDict, total=False):
    """Shared state for multi-source ingestion BDD steps."""

    profile: SeriesProfile
    raw_sources: list[RawSourceInput]
    episode: CanonicalEpisode
    episode_id: uuid.UUID
    ingestion_job_id: uuid.UUID


def add_raw_source(
    multi_source_context: MultiSourceContext,
    source: RawSourceInput,
    *,
    replace: bool = False,
) -> None:
    """Append or replace a raw source in the shared context."""
    if replace:
        multi_source_context["raw_sources"] = [source]
    else:
        sources = multi_source_context.get("raw_sources", [])
        sources.append(source)
        multi_source_context["raw_sources"] = sources
