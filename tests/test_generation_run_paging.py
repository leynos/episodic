"""Unit tests for generation-run event-page validation."""

import pytest

from episodic.canonical.generation_run_ports import (
    EventSeq,
    event_page_minimum_sequence,
    event_seq,
)


@pytest.mark.parametrize(
    ("after_seq", "limit", "offset", "expected"),
    [(None, 10, 0, 0), (event_seq(4), 10, 0, 4), (None, 10, 3, 0)],
)
def test_event_page_minimum_sequence_returns_cursor_boundary(
    after_seq: EventSeq | None,
    limit: int,
    offset: int,
    expected: int,
) -> None:
    """Valid pagination inputs produce their exclusive event-sequence bound."""
    assert (
        event_page_minimum_sequence(
            after_seq=after_seq,
            limit=limit,
            offset=offset,
        )
        == expected
    ), f"Expected boundary {expected} for cursor {after_seq!r}."


@pytest.mark.parametrize(
    ("after_seq", "limit", "offset", "message"),
    [
        (None, -1, 0, "limit and offset must be non-negative"),
        (None, 1, -1, "limit and offset must be non-negative"),
        (event_seq(1), 1, 1, "after_seq and offset cannot be combined"),
    ],
)
def test_event_page_minimum_sequence_rejects_invalid_pagination(
    after_seq: EventSeq | None,
    limit: int,
    offset: int,
    message: str,
) -> None:
    """Invalid pagination combinations retain the port contract errors."""
    with pytest.raises(ValueError, match=message):
        event_page_minimum_sequence(
            after_seq=after_seq,
            limit=limit,
            offset=offset,
        )
