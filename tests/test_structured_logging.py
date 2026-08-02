"""Tests for structured event logging."""

import datetime as dt
import enum
import json
import typing as typ
import uuid

from episodic import logging as episodic_logging

if typ.TYPE_CHECKING:
    import pytest


class _EventSpyLogger:
    """Collect structured messages emitted by `log_event`."""

    def __init__(self) -> None:
        """Initialize an empty message record."""
        self.messages: list[str] = []

    def info(self, message: str, **kwargs: object) -> None:
        """Record one INFO message and verify no logger kwargs were added."""
        assert not kwargs
        self.messages.append(message)


class _EventState(enum.Enum):
    """Representative non-string enum used in structured fields."""

    READY = "ready"


def test_log_event_normalizes_non_json_structured_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structured logging normalizes common non-JSON field values."""
    logger = _EventSpyLogger()
    monkeypatch.setattr(episodic_logging, "_event_log", logger)
    event_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    occurred_at = dt.datetime(2026, 8, 3, 12, 30, tzinfo=dt.UTC)

    episodic_logging.log_event(
        "info",
        "generation.failed",
        event_id=event_id,
        occurred_at=occurred_at,
        state=_EventState.READY,
        error=RuntimeError("provider unavailable"),
    )

    assert json.loads(logger.messages[0]) == {
        "error": "provider unavailable",
        "event": "generation.failed",
        "event_id": str(event_id),
        "occurred_at": "2026-08-03T12:30:00+00:00",
        "state": "ready",
    }
