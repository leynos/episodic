"""Episode persistence errors."""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    import uuid


class EpisodeError(Exception):
    """Base class for canonical episode errors."""


class EpisodeNotFoundError(EpisodeError):
    """Raised when an episode row cannot be found."""

    def __init__(self, episode_id: uuid.UUID) -> None:
        self.episode_id = episode_id
        message = f"Episode {episode_id} was not found."
        super().__init__(message)


class EpisodeRevisionConflictError(EpisodeError):
    """Raised when an optimistic TEI revision precondition fails."""

    def __init__(self, episode_id: uuid.UUID, expected_revision: int) -> None:
        self.episode_id = episode_id
        self.expected_revision = expected_revision
        message = (
            f"Episode {episode_id} revision did not match expected revision "
            f"{expected_revision}."
        )
        super().__init__(message)
