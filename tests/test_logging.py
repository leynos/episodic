"""Tests for episodic logging integration and femtologging compatibility."""

from __future__ import annotations

import time
import typing as typ

import pytest

from episodic import logging as episodic_logging


class _SpyLogger:
    """Collect low-level log calls emitted by the compatibility wrappers."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object | None, bool]] = []

    def _record(
        self,
        level: str,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        self.calls.append((level, message, exc_info, stack_info))

    def info(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        self._record(
            episodic_logging.LogLevel.INFO,
            message,
            exc_info=exc_info,
            stack_info=stack_info,
        )

    def warning(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        self._record(
            episodic_logging.LogLevel.WARNING,
            message,
            exc_info=exc_info,
            stack_info=stack_info,
        )

    def error(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        self._record(
            episodic_logging.LogLevel.ERROR,
            message,
            exc_info=exc_info,
            stack_info=stack_info,
        )


class _CollectorHandler:
    """Capture femtologging records through the Python handler protocol."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, str]] = []

    def handle(self, logger_name: str, level: str, message: str) -> None:
        self.records.append((logger_name, level, message))


class _SupportsFlushHandlers(typ.Protocol):
    """Minimal logger protocol needed by the asynchronous test helper."""

    def flush_handlers(self) -> object: ...


def _wait_for_record_count(
    logger: _SupportsFlushHandlers,
    collector: _CollectorHandler,
    *,
    expected_count: int,
    timeout_seconds: float = 2.0,
) -> None:
    """Wait until the asynchronous logger worker drains into the collector."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        logger.flush_handlers()
        if len(collector.records) >= expected_count:
            return
        time.sleep(0.01)
    logger.flush_handlers()


@pytest.mark.parametrize(
    ("requested_level", "expected_level", "expected_used_default"),
    [
        (None, episodic_logging.LogLevel.INFO, True),
        ("", episodic_logging.LogLevel.INFO, True),
        ("debug", episodic_logging.LogLevel.DEBUG, False),
        ("warning", episodic_logging.LogLevel.WARNING, False),
        ("invalid", episodic_logging.LogLevel.INFO, True),
    ],
)
def test_configure_logging_normalizes_levels(
    monkeypatch: pytest.MonkeyPatch,
    requested_level: str | None,
    expected_level: str,
    expected_used_default: object,
) -> None:
    """configure_logging should normalize levels before delegating to femtologging."""
    recorded_calls: list[tuple[str, bool]] = []

    def _fake_basic_config(*, level: str, force: bool) -> None:
        recorded_calls.append((level, force))

    monkeypatch.setattr(episodic_logging, "basicConfig", _fake_basic_config)

    effective_level, used_default = episodic_logging.configure_logging(
        requested_level,
        force=True,
    )

    assert (effective_level, used_default) == (
        expected_level,
        expected_used_default,
    )
    assert recorded_calls == [(expected_level, True)]


def test_log_wrappers_delegate_through_logger_log() -> None:
    """Compatibility helpers should preserve percent-style formatting semantics."""
    logger = _SpyLogger()
    err = RuntimeError("boom")

    episodic_logging.log_info(logger, "Loaded %s documents", 3)
    episodic_logging.log_warning(logger, "Potential issue in %s", "ingestion")
    episodic_logging.log_error(
        logger,
        "Failed job %s",
        "job-1",
        exc_info=err,
    )

    assert logger.calls == [
        (episodic_logging.LogLevel.INFO, "Loaded 3 documents", None, False),
        (
            episodic_logging.LogLevel.WARNING,
            "Potential issue in ingestion",
            None,
            False,
        ),
        (
            episodic_logging.LogLevel.ERROR,
            "Failed job job-1",
            err,
            False,
        ),
    ]


def test_femtologging_exposes_stdlib_style_logger_surface() -> None:
    """The upgraded dependency should expose stdlib-like logger helpers."""
    import femtologging

    assert hasattr(femtologging, "getLogger")

    logger = femtologging.get_logger("tests.logging.surface")
    for method_name in (
        "debug",
        "info",
        "warning",
        "error",
        "critical",
        "exception",
        "isEnabledFor",
    ):
        assert hasattr(logger, method_name), method_name


def _raise_logged_exception() -> None:
    msg = "boom"
    raise RuntimeError(msg)


def test_stdlib_style_logger_methods_emit_to_python_handlers() -> None:
    """Direct logger convenience methods should work with Python handlers."""
    import femtologging

    femtologging.reset_manager()
    logger = femtologging.getLogger("tests.logging.runtime")
    collector = _CollectorHandler()
    logger.clear_handlers()
    logger.set_propagate(False)
    logger.add_handler(collector)

    assert logger.isEnabledFor("INFO") is True

    logger.info("hello from episodic")
    logger.error("failed job")
    try:
        _raise_logged_exception()
    except RuntimeError:
        logger.exception("captured failure")

    _wait_for_record_count(logger, collector, expected_count=3)

    assert collector.records == [
        ("tests.logging.runtime", "INFO", "hello from episodic"),
        ("tests.logging.runtime", "ERROR", "failed job"),
        ("tests.logging.runtime", "ERROR", "captured failure"),
    ]
