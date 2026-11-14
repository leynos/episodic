"""Test doubles for the content-addressed pricing snapshot migration."""

import logging


class RecordMessages(logging.Filter):
    """Collect the messages logged through the logger it is attached to.

    Alembic's ``env.py`` re-runs ``fileConfig`` per invocation, which clears the
    handlers on the root logger and on the ``alembic`` tree, so a recording
    handler never observes a migration's lines. Filters survive ``fileConfig``,
    so the message is captured here instead.
    """

    def __init__(self) -> None:
        """Start with no collected messages."""
        super().__init__()
        self.messages: list[str] = []

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep the message and let the record continue."""
        self.messages.append(record.getMessage())
        return True


class FixedDigest:
    """Stand-in for a SHA-256 digest whose value never changes."""

    def hexdigest(self) -> str:
        """Return one constant digest, so distinct content collides."""
        return "0" * 64


def colliding_sha256(*_args: object, **_kwargs: object) -> FixedDigest:
    """Return the same digest for every input, forcing a collision."""
    return FixedDigest()
