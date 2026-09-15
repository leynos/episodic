"""Unit tests for canonical draft-episode construction."""

import datetime as dt
import uuid

from episodic.canonical.domain import ApprovalState, EpisodeStatus, TeiHeader
from episodic.canonical.episode_factory import build_draft_episode


def test_build_draft_episode_uses_header_content_and_draft_states() -> None:
    """A new episode inherits header content with the initial lifecycle states."""
    now = dt.datetime(2026, 8, 23, 12, 0, tzinfo=dt.UTC)
    header = TeiHeader(
        id=uuid.uuid7(),
        title="Episode title",
        payload={},
        raw_xml="<TEI/>",
        created_at=now,
        updated_at=now,
    )
    series_profile_id = uuid.uuid7()
    episode_id = uuid.uuid7()

    episode = build_draft_episode(
        episode_id=episode_id,
        series_profile_id=series_profile_id,
        header=header,
        now=now,
    )

    assert episode.id == episode_id, "The reserved identifier must be retained."
    assert episode.series_profile_id == series_profile_id, (
        "The supplied profile must own the new episode."
    )
    assert episode.tei_header_id == header.id, "The parsed header must be retained."
    assert episode.title == header.title, "The title must come from the header."
    assert episode.tei_xml == header.raw_xml, "The TEI XML must come from the header."
    assert episode.status is EpisodeStatus.DRAFT, "New episodes must begin as drafts."
    assert episode.approval_state is ApprovalState.DRAFT, (
        "New episodes must begin with draft approval."
    )
    assert episode.created_at == now, "The supplied timestamp must set creation."
    assert episode.updated_at == now, "The supplied timestamp must set updates."
