"""Episode persistence errors."""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    import uuid


class EpisodeError(Exception):
    """Base class for canonical episode errors."""


class EpisodeNotFound(EpisodeError):  # noqa: N818 - mirrors existing domain errors.
    """Raised when an episode row cannot be found."""

    def __init__(self, episode_id: uuid.UUID) -> None:
        super().__init__(f"Episode {episode_id} was not found.")


class EpisodeRevisionConflict(EpisodeError):  # noqa: N818 - stable storage contract.
    """Raised when an optimistic TEI revision precondition fails."""

    def __init__(self, episode_id: uuid.UUID, expected_revision: int) -> None:
        super().__init__(
            f"Episode {episode_id} revision did not match expected revision "
            f"{expected_revision}."
        )
