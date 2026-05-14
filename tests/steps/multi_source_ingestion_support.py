"""Shared helpers for multi-source ingestion BDD steps.

This module centralizes the small orchestration utilities shared by the
multi-source ingestion step modules. Step definitions use ``run_async_step`` to
bridge synchronous pytest-bdd execution with async ingestion workflows, store
scenario state in ``MultiSourceContext``, and call ``add_raw_source`` when a
scenario introduces or replaces source material.

Examples
--------
Run an async step and record one source in the shared context:

>>> context: MultiSourceContext = {}
>>> add_raw_source(context, raw_source)
>>> run_async_step(runner, lambda: async_step(context))
"""

import typing as typ

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc
    import uuid

    from episodic.canonical.domain import CanonicalEpisode, SeriesProfile
    from episodic.canonical.ingestion import RawSourceInput


def run_async_step(
    runner: asyncio.Runner,
    step_fn: cabc.Callable[[], cabc.Awaitable[None]],
) -> None:
    """Execute an async BDD step via the provided runner.

    Parameters
    ----------
    runner : asyncio.Runner
        Runner owned by the function-scoped test fixture.
    step_fn : Callable[[], Awaitable[None]]
        Zero-argument callable returning the coroutine for the BDD step.

    Returns
    -------
    None
        The step is executed for its assertions and context mutation.

    Raises
    ------
    Exception
        Propagates any exception raised by the asynchronous step.
    """
    coro = typ.cast("cabc.Coroutine[object, object, None]", step_fn())
    runner.run(coro)


class MultiSourceContext(typ.TypedDict, total=False):
    """Shared state for multi-source ingestion BDD steps.

    Parameters
    ----------
    **kwargs : object
        Optional scenario fields populated by individual step functions.

    Attributes
    ----------
    profile : SeriesProfile
        Series profile under test.
    raw_sources : list[RawSourceInput]
        Raw source payloads collected before ingestion.
    episode : CanonicalEpisode
        Episode produced by the ingestion workflow.
    episode_id : uuid.UUID
        Identifier of the created or updated canonical episode.
    ingestion_job_id : uuid.UUID
        Identifier of the ingestion job created for the scenario.

    Examples
    --------
    >>> context: MultiSourceContext = {"raw_sources": []}
    >>> add_raw_source(context, raw_source)
    """

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
    """Append or replace a raw source in the shared context.

    Parameters
    ----------
    multi_source_context : MultiSourceContext
        Scenario state shared across step definitions.
    source : RawSourceInput
        Source payload to store in the context.
    replace : bool, default=False
        Replace all existing raw sources when true; append otherwise.

    Returns
    -------
    None
        The context is mutated in place.
    """
    if replace:
        multi_source_context["raw_sources"] = [source]
    else:
        sources = multi_source_context.get("raw_sources", [])
        sources.append(source)
        multi_source_context["raw_sources"] = sources
