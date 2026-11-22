"""Resolve canonical episodes the requesting principal may observe.

Episode ownership follows the launcher run recorded on the episode: a request
may read an episode only when that run's actor matches the authenticated
principal. Resources call :func:`read_owned_episode` before exposing episode
data, so an artefact with another owner is reported as absent rather than
forbidden.
"""

import typing as typ

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.domain import CanonicalEpisode, GenerationRun
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


async def read_owned_episode(
    uow: CanonicalUnitOfWork,
    episode_id: uuid.UUID,
    actor: str | None,
) -> CanonicalEpisode | None:
    """Return the episode when its launcher run belongs to the actor.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit of work used to read the episode and its launcher run.
    episode_id : uuid.UUID
        Episode to resolve.
    actor : str | None
        Authenticated principal, or ``None`` when the request carries no
        credential.

    Returns
    -------
    CanonicalEpisode | None
        The episode when it exists, records a launcher run, and that run's
        actor equals ``actor``; otherwise ``None``.

    Notes
    -----
    An ownership check is a query path, so it must not flush work the caller
    has staged: doing so would turn a read into a write and report a constraint
    failure against a request that never wrote it. The repositories keep that
    boundary themselves, so this function reads without managing autoflush.
    """
    resolved = await read_owned_episode_and_run(uow, episode_id, actor)
    return None if resolved is None else resolved[0]


async def read_owned_episode_and_run(
    uow: CanonicalUnitOfWork,
    episode_id: uuid.UUID,
    actor: str | None,
) -> tuple[CanonicalEpisode, GenerationRun] | None:
    """Return an owned episode with the launcher run that produced it.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit of work used to read the episode and its launcher run.
    episode_id : uuid.UUID
        Episode to resolve.
    actor : str | None
        Authenticated principal, or ``None`` when the request carries no
        credential.

    Returns
    -------
    tuple[CanonicalEpisode, GenerationRun] | None
        The episode and its producing run when both exist and the run's actor
        equals ``actor``; otherwise ``None``.
    """
    if actor is None:
        return None
    episode = await uow.episodes.get(episode_id)
    if episode is None or episode.last_generation_run_id is None:
        return None
    run = await uow.generation_runs.get_run(episode.last_generation_run_id)
    if run is None or run.actor != actor:
        return None
    return episode, run
