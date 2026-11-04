"""Tests for logging convenience wrappers that were recently added."""

import episodic.logging as episodic_logging


class _DebugExceptionLogger:
    """Capture the level-specific convenience methods without a log fallback."""

    def __init__(self) -> None:
        """Initialize the captured call list."""
        self.calls: list[tuple[str, str, object | None, bool]] = []

    def log(
        self,
        level: int | episodic_logging.LogLevel,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record an unexpected fallback so the test distinguishes dispatch."""
        del level
        self.calls.append(("log", message, exc_info, stack_info))

    def debug(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record a DEBUG convenience-method call."""
        self.calls.append(("debug", message, exc_info, stack_info))

    def exception(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record an ERROR convenience-method call."""
        self.calls.append(("exception", message, exc_info, stack_info))


def test_debug_and_exception_wrappers_use_convenience_methods() -> None:
    """Level-specific wrappers use their method and preserve exception data."""
    spy_logger = _DebugExceptionLogger()
    logger = episodic_logging.LoggerHandle(spy_logger)

    episodic_logging.log_debug(logger, "Loaded %s documents", 3)
    episodic_logging.log_exception(logger, "Failed capture %s", "job-2")

    expected_calls = [
        ("debug", "Loaded 3 documents", None, False),
        ("exception", "Failed capture job-2", True, False),
    ]
    assert spy_logger.calls == expected_calls, (
        "wrappers should use convenience methods and default exception details"
    )
