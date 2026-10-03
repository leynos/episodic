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
        assert not kwargs, "structured event fields must be encoded in the message"
        self.messages.append(message)


class _JsonFallbackLogger:
    """Reject plain messages and record JSON messages accepted on retry."""

    def __init__(self) -> None:
        """Initialize the logger's attempted and accepted messages."""
        self.attempted_messages: list[str] = []
        self.accepted_messages: list[str] = []

    def info(self, message: str, **kwargs: object) -> None:
        """Accept JSON and reject a plain message with ``TypeError``."""
        assert not kwargs, "log_event should not add logger kwargs"
        self.attempted_messages.append(message)
        if not message.startswith("{"):
            msg = "plain messages are unsupported"
            raise TypeError(msg)
        json.loads(message)
        self.accepted_messages.append(message)


class _EventState(enum.Enum):
    """Representative non-string enum used in structured fields."""

    READY = "ready"


def test_log_event_emits_plain_message_without_structured_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without structured fields, the original message is logged once."""
    logger = _EventSpyLogger()
    monkeypatch.setattr(episodic_logging, "_event_log", logger)

    episodic_logging.log_event("info", "generation.started")

    assert logger.messages == ["generation.started"], (
        "plain logging should emit the original message exactly once"
    )


def test_log_event_retries_plain_message_as_json_after_type_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry a logger's rejected plain message as an event JSON object."""
    logger = _JsonFallbackLogger()
    monkeypatch.setattr(episodic_logging, "_event_log", logger)

    episodic_logging.log_event("info", "generation.started")

    assert logger.attempted_messages == [
        "generation.started",
        '{"event": "generation.started"}',
    ], "TypeError should trigger one JSON event retry"
    assert [json.loads(message) for message in logger.accepted_messages] == [
        {"event": "generation.started"}
    ], "the logger should accept the JSON event retry"


def test_log_event_preserves_message_when_event_field_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit event message wins over a conflicting structured field."""
    logger = _EventSpyLogger()
    monkeypatch.setattr(episodic_logging, "_event_log", logger)

    episodic_logging.log_event(
        "info", "generation.original", event="generation.conflicting"
    )

    assert json.loads(logger.messages[0])["event"] == "generation.original", (
        "the message argument must take precedence over a conflicting event field"
    )


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

    expected_payload = {
        "error": "provider unavailable",
        "event": "generation.failed",
        "event_id": str(event_id),
        "occurred_at": "2026-08-03T12:30:00+00:00",
        "state": "ready",
    }
    assert json.loads(logger.messages[0]) == expected_payload, (
        "non-JSON fields must normalize to the expected event payload"
    )
