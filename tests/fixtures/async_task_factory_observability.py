"""Test doubles for task-validation observability assertions."""

import dataclasses as dc
import typing as typ

from episodic import logging as episodic_logging
from episodic.observability import NoopMetrics

if typ.TYPE_CHECKING:
    import collections.abc as cabc


class SpyLogger:
    """Record log calls dispatched through the Episodic logging port."""

    def __init__(self) -> None:
        """Initialise an empty call record."""
        self.calls: list[
            tuple[int | episodic_logging.LogLevel, str, object | None, bool]
        ] = []

    def error(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record an ERROR-level call through the convenience method."""
        self.calls.append((
            episodic_logging.LogLevel.ERROR,
            message,
            exc_info,
            stack_info,
        ))

    def log(
        self,
        level: int | episodic_logging.LogLevel,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record a fallback call; the logging port prefers `error` instead."""
        self.calls.append((level, message, exc_info, stack_info))


@dc.dataclass(frozen=True, slots=True)
class FakeTaskValidationMetrics(NoopMetrics):
    """Record counter increments for task-validation assertions."""

    counters: list[tuple[str, dict[str, str]]] = dc.field(default_factory=list)

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Capture one counter increment."""
        self.counters.append((name, dict(labels)))
