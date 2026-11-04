"""Tests for episodic logging integration and femtologging compatibility."""

import logging
import time
import typing as typ

import pytest

from episodic import logging as episodic_logging

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

if typ.TYPE_CHECKING:
    import collections.abc as cabc


class _SpyLogger:
    """Collect low-level log calls emitted by the compatibility wrappers."""

    def __init__(self) -> None:
        """Initialise an empty call record."""
        self.calls: list[
            tuple[int | episodic_logging.LogLevel, str, object | None, bool]
        ] = []

    # pylint: disable-next=too-many-arguments  # mirrors stdlib/femtologging call signature
    def _record(
        self,
        level: int | episodic_logging.LogLevel,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Append a normalised call tuple to the record list."""
        self.calls.append((level, message, exc_info, stack_info))

    # @codescene(disable:"Code Duplication") Keep explicit protocol spy (2026-11-04).
    # pylint: disable-next=too-many-arguments  # mirrors stdlib/femtologging call signature
    def debug(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record a DEBUG-level call."""
        self._record(
            episodic_logging.LogLevel.DEBUG,
            message,
            exc_info=exc_info,
            stack_info=stack_info,
        )

    # pylint: disable-next=too-many-arguments  # mirrors stdlib/femtologging call signature
    def info(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record an INFO-level call."""
        self._record(
            episodic_logging.LogLevel.INFO,
            message,
            exc_info=exc_info,
            stack_info=stack_info,
        )

    # pylint: disable-next=too-many-arguments  # mirrors stdlib/femtologging call signature
    def warning(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record a WARNING-level call."""
        self._record(
            episodic_logging.LogLevel.WARNING,
            message,
            exc_info=exc_info,
            stack_info=stack_info,
        )

    # pylint: disable-next=too-many-arguments  # mirrors stdlib/femtologging call signature
    def error(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record an ERROR-level call."""
        self._record(
            episodic_logging.LogLevel.ERROR,
            message,
            exc_info=exc_info,
            stack_info=stack_info,
        )

    # pylint: disable-next=too-many-arguments  # mirrors stdlib/femtologging call signature
    def log(
        self,
        level: int | episodic_logging.LogLevel,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record fallback calls made for unimplemented convenience levels."""
        assert isinstance(level, (int, episodic_logging.LogLevel)), (
            "logger level must satisfy the integer or LogLevel contract"
        )
        self._record(
            level,
            message,
            exc_info=exc_info,
            stack_info=stack_info,
        )


class _LogOnlySpyLogger:
    """Collect low-level log calls through a stdlib-style `log` method only."""

    def __init__(self) -> None:
        """Initialise an empty call record."""
        self.calls: list[
            tuple[int | episodic_logging.LogLevel, str, object | None, bool]
        ] = []

    # pylint: disable-next=too-many-arguments  # mirrors stdlib/femtologging call signature
    def log(
        self,
        level: int | episodic_logging.LogLevel,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record a call made through the stdlib-style log() entry point."""
        assert isinstance(level, int), "logger level must satisfy the integer contract"
        self.calls.append((level, message, exc_info, stack_info))


class _RaisingInfoLogger(_LogOnlySpyLogger):
    """Record a convenience call before simulating an emission failure."""

    def info(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record one call then raise the original emission failure."""
        self.calls.append((
            episodic_logging.LogLevel.INFO,
            message,
            exc_info,
            stack_info,
        ))
        msg = "emission failed"
        raise TypeError(msg)


class _RaisingDebugLogger(_LogOnlySpyLogger):
    """Track a DEBUG attempt before simulating an emission failure."""

    def __init__(self) -> None:
        """Initialise the generic logger and DEBUG attempt records."""
        super().__init__()
        self.debug_calls: list[tuple[str, object | None, bool]] = []

    def debug(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record one call then raise the original emission failure."""
        self.debug_calls.append((message, exc_info, stack_info))
        msg = "emission failed"
        raise TypeError(msg)


class _LegacyDebugLogger(_LogOnlySpyLogger):
    """Logger with a DEBUG method that predates helper keyword arguments."""

    def __init__(self) -> None:
        """Initialise the generic logger and DEBUG attempt count."""
        super().__init__()
        self.debug_calls = 0

    def debug(self, message: str, /) -> None:
        """Record a DEBUG call that cannot accept the helper options."""
        del message
        self.debug_calls += 1


class _LogFallbackCase(typ.NamedTuple):
    emit: cabc.Callable[..., None]
    template: str
    args: tuple[object, ...]
    expected_level: int
    expected_message: str
    exc_info: object | None


def test_log_wrappers_delegate_through_convenience_methods(
    snapshot: SnapshotAssertion,
) -> None:
    """Compatibility helpers should preserve percent-style formatting semantics."""
    spy_logger = _SpyLogger()
    logger = episodic_logging.LoggerHandle(spy_logger)
    err = RuntimeError("boom")

    episodic_logging.log_debug(logger, "Loaded %s documents", 3)
    episodic_logging.log_info(logger, "Loaded %s documents", 3)
    episodic_logging.log_warning(logger, "Potential issue in %s", "ingestion")
    episodic_logging.log_error(
        logger,
        "Failed job %s",
        "job-1",
        exc_info=err,
    )
    assert spy_logger.calls == snapshot, (
        "convenience-wrapper calls must match the snapshot"
    )


@pytest.mark.parametrize(
    "wrapper",
    [episodic_logging.log_debug, episodic_logging.log_info],
    ids=["debug", "info"],
)
def test_log_wrappers_raise_type_error_on_mismatched_format(
    wrapper: cabc.Callable[..., None],
) -> None:
    """Compatibility helpers should propagate `TypeError` from formatting."""
    spy_logger = _SpyLogger()
    logger = episodic_logging.LoggerHandle(spy_logger)

    with pytest.raises(
        TypeError,
        match=r"not enough arguments for format string",
    ):
        wrapper(logger, "Loaded %s documents for %s", 3)

    assert spy_logger.calls == [], (  # pylint: disable=use-implicit-booleaness-not-comparison  # The explicit empty-list comparison documents the expected collection value.
        "expected no log calls after TypeError"
    )


def test_log_wrappers_fall_back_to_logger_log_when_needed(
    snapshot: SnapshotAssertion,
) -> None:
    """Compatibility helpers should support loggers that only expose `log()`."""
    spy_logger = _LogOnlySpyLogger()
    logger = episodic_logging.LoggerHandle(spy_logger)
    err = RuntimeError("boom")

    episodic_logging.log_info(logger, "Loaded %s documents", 3)
    episodic_logging.log_warning(logger, "Potential issue in %s", "ingestion")
    episodic_logging.log_error(
        logger,
        "Failed job %s",
        "job-1",
        exc_info=err,
    )
    assert spy_logger.calls == snapshot, "fallback logger calls must match the snapshot"


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _LogFallbackCase(
                episodic_logging.log_debug,
                "Loading %s documents",
                (3,),
                logging.DEBUG,
                "Loading 3 documents",
                None,
            ),
            id="debug",
        ),
        pytest.param(
            _LogFallbackCase(
                episodic_logging.log_exception,
                "Failed capture %s",
                ("job-2",),
                logging.ERROR,
                "Failed capture job-2",
                exc_info=True,
            ),
            id="exception",
        ),
    ],
)
def test_debug_and_exception_wrappers_fall_back_to_logger_log(
    case: _LogFallbackCase,
) -> None:
    """New level wrappers use log(), with exception info enabled by default."""
    spy_logger = _LogOnlySpyLogger()
    logger = episodic_logging.LoggerHandle(spy_logger)

    case.emit(logger, case.template, *case.args)

    assert spy_logger.calls == [
        (case.expected_level, case.expected_message, case.exc_info, False)
    ], "fallback calls should preserve formatting, level, and exception metadata"


def test_log_wrapper_does_not_retry_a_failed_convenience_emission() -> None:
    """A convenience-method TypeError propagates without a second log call."""
    spy_logger = _RaisingInfoLogger()
    logger = episodic_logging.LoggerHandle(spy_logger)

    with pytest.raises(TypeError, match="emission failed"):
        episodic_logging.log_info(logger, "Loaded %s documents", 3)

    assert spy_logger.calls == [
        (episodic_logging.LogLevel.INFO, "Loaded 3 documents", None, False)
    ], "A failed convenience call must not be retried through log()."


def test_debug_wrapper_falls_back_when_signature_rejects_helper_keywords() -> None:
    """Fall back when a legacy DEBUG method rejects helper keyword arguments."""
    spy_logger = _LegacyDebugLogger()
    logger = episodic_logging.LoggerHandle(spy_logger)

    episodic_logging.log_debug(logger, "Loaded %s documents", 3)

    assert spy_logger.debug_calls == 0, "signature mismatch must be detected"
    assert spy_logger.calls == [
        (logging.DEBUG, "Loaded 3 documents", None, False)
    ], "the rejected DEBUG call should fall back through log()"


def test_debug_wrapper_does_not_retry_internal_type_error() -> None:
    """Propagate compatible DEBUG failures to avoid emitting a duplicate."""
    spy_logger = _RaisingDebugLogger()
    logger = episodic_logging.LoggerHandle(spy_logger)

    with pytest.raises(TypeError, match="emission failed"):
        episodic_logging.log_debug(logger, "Loaded %s documents", 3)

    assert spy_logger.debug_calls == [
        ("Loaded 3 documents", None, False)
    ], "the compatible DEBUG method should be attempted once"
    assert spy_logger.calls == [], "internal failures must not be retried through log()"


def test_femtologging_exposes_stdlib_style_logger_surface() -> None:
    """The upgraded dependency should expose stdlib-like logger helpers."""
    import femtologging

    assert hasattr(femtologging, "getLogger"), (
        "femtologging must expose the required getLogger attribute"
    )

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


def test_episodic_logging_get_logger_returns_opaque_handle() -> None:
    """Episodic logging should hide the raw femtologging logger surface."""
    logger = episodic_logging.getLogger("tests.logging.surface")
    for method_name in (
        "debug",
        "info",
        "warning",
        "error",
        "critical",
        "exception",
        "isEnabledFor",
    ):
        assert not hasattr(logger, method_name), method_name


class _CollectorHandler:
    """Capture femtologging records through the Python handler protocol."""

    def __init__(self) -> None:
        """Initialise an empty records list."""
        self.records: list[tuple[str, str, str]] = []

    def handle(self, logger_name: str, level: str, message: str) -> None:
        """Append a (logger_name, level, message) tuple to the records list."""
        self.records.append((logger_name, level, message))


class _SupportsFlushHandlers(typ.Protocol):
    """Minimal logger protocol needed by the asynchronous test helper."""

    def flush_handlers(self) -> None:
        """Flush all pending records through attached handlers and return None."""


@pytest.fixture
def isolated_femtologging() -> cabc.Generator[None]:
    """Reset the femtologging global manager before and after each test."""
    import femtologging

    femtologging.reset_manager()
    yield
    femtologging.reset_manager()


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


def _raise_logged_exception() -> None:
    """Raise a RuntimeError for use in exception-logging tests."""
    msg = "boom"
    raise RuntimeError(msg)


def test_stdlib_style_logger_methods_emit_to_python_handlers(
    isolated_femtologging: None,
    snapshot: SnapshotAssertion,
) -> None:
    """Direct logger convenience methods should work with Python handlers."""
    import femtologging

    logger = femtologging.getLogger("tests.logging.runtime")
    collector = _CollectorHandler()
    logger.clear_handlers()
    logger.set_propagate(False)
    logger.add_handler(collector)

    assert logger.isEnabledFor("INFO") is True, (
        "runtime femtologging logger must report INFO as enabled"
    )

    logger.info("hello from episodic")
    logger.error("failed job")
    try:
        _raise_logged_exception()
    except RuntimeError:
        logger.exception("captured failure")

    _wait_for_record_count(logger, collector, expected_count=3)

    assert collector.records == snapshot, "handler records must match the snapshot"
