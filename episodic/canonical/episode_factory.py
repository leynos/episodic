"""Canonical construction helpers for new draft episodes.

This application-layer module owns the common initial state for new canonical
episodes. It accepts only domain values and has no persistence or transport
dependencies, allowing both ingestion workflows to share it without coupling
their orchestration steps.
"""

import typing as typ

from .domain import ApprovalState, CanonicalEpisode, EpisodeStatus, TeiHeader

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid


def build_draft_episode(
    *,
    episode_id: uuid.UUID,
    series_profile_id: uuid.UUID,
    header: TeiHeader,
    now: dt.datetime,
) -> CanonicalEpisode:
    """Build a new canonical episode in its initial draft state.

    Parameters
    ----------
    episode_id : uuid.UUID
        Identifier reserved for the new episode.
    series_profile_id : uuid.UUID
        Identifier of the profile that owns the episode.
    header : TeiHeader
        Parsed TEI header supplying the title and source XML.
    now : datetime.datetime
        Timestamp applied to both creation and update fields.

    Returns
    -------
    CanonicalEpisode
        A draft episode with draft approval state and header-derived content.
    """
    return CanonicalEpisode(
        id=episode_id,
        series_profile_id=series_profile_id,
        tei_header_id=header.id,
        title=header.title,
        tei_xml=header.raw_xml,
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )
