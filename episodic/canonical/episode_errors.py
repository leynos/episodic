"""Episode persistence errors."""

import typing as typ

if typ.TYPE_CHECKING:
    import uuid


class EpisodeError(Exception):
    """Base exception for failures in the canonical episode lifecycle.

    Canonical repositories and generation services use this exception family
    when an episode cannot be loaded or its optimistic persistence precondition
    is not satisfied.

    Notes
    -----
    Application boundaries can catch this base class while preserving the more
    specific subclass and its diagnostic attributes for stable failure
    categorisation.
    """


class EpisodeNotFoundError(EpisodeError):
    """Signal that a requested canonical episode does not exist.

    Raised when a repository or generation service cannot load the episode
    required for a lifecycle operation such as draft generation or TEI
    retrieval.

    Parameters
    ----------
    episode_id : uuid.UUID
        Identifier of the episode that could not be loaded.

    Attributes
    ----------
    episode_id : uuid.UUID
        Identifier of the missing episode, retained for error mapping and
        diagnostics.

    Notes
    -----
    This error represents a lookup failure before the requested generation or
    TEI persistence transition can begin.
    """

    def __init__(self, episode_id: uuid.UUID) -> None:
        """Initialize an error for a missing canonical episode.

        Parameters
        ----------
        episode_id : uuid.UUID
            Identifier of the episode that could not be loaded.
        """
        self.episode_id = episode_id
        message = f"Episode {episode_id} was not found."
        super().__init__(message)


class EpisodeRevisionConflictError(EpisodeError):
    """Signal that an episode TEI revision precondition failed.

    Raised when a generation result attempts to persist against an episode
    whose stored ``tei_revision`` no longer matches the caller's expectation.

    Parameters
    ----------
    episode_id : uuid.UUID
        Identifier of the episode whose TEI revision changed.
    expected_revision : int
        Revision the caller required before applying its update.

    Attributes
    ----------
    episode_id : uuid.UUID
        Identifier of the conflicting episode.
    expected_revision : int
        Revision supplied by the caller for the optimistic concurrency check.

    Notes
    -----
    This error occurs at the TEI persistence boundary after generation has
    produced output but before that output is committed to the episode.
    """

    def __init__(self, episode_id: uuid.UUID, expected_revision: int) -> None:
        """Initialize an error for a failed optimistic revision check.

        Parameters
        ----------
        episode_id : uuid.UUID
            Identifier of the episode whose TEI revision changed.
        expected_revision : int
            Revision the caller required before applying its update.
        """
        self.episode_id = episode_id
        self.expected_revision = expected_revision
        message = (
            f"Episode {episode_id} revision did not match expected revision "
            f"{expected_revision}."
        )
        super().__init__(message)
