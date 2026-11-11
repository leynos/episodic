"""Integration tests for the public logging port and its backend."""

import time
import typing as typ

import pytest

from episodic import logging as episodic_logging

if typ.TYPE_CHECKING:
    import collections.abc as cabc


class _ExceptionInfo(typ.TypedDict, total=False):
    """Exception details preserved by femtologging's structured record."""

    type_name: str
    message: str


class _RecordCollector:
    """Capture the rich records dispatched by femtologging."""

    def __init__(self) -> None:
        """Initialise an empty record collection."""
        self.records: list[dict[str, object]] = []

    def handle(self, logger_name: str, level: str, message: str) -> None:
        """Support the basic handler protocol used during registration."""
        self.records.append({"logger": logger_name, "level": level, "message": message})

    def handle_record(self, record: dict[str, object]) -> None:
        """Capture the emission fields and exception context under test."""
        self.records.append({
            "logger": record.get("logger"),
            "level": record.get("level"),
            "message": record.get("message"),
            "exc_info": record.get("exc_info"),
        })

    def flush(self) -> bool:
        """Report that this in-memory collector has no buffered output."""
        return True


class _SynchronousLogger:
    """Record logging-port messages without backend-specific flush support."""

    def __init__(self) -> None:
        """Start an empty synchronous message record."""
        self.messages: list[str] = []

    # pylint: disable-next=too-many-arguments  # mirrors the logging protocol
    def log(
        self,
        level: int | episodic_logging.LogLevel,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record one message after checking the logging call contract."""
        assert isinstance(level, (int, episodic_logging.LogLevel)), (
            "logging levels must satisfy the integer or LogLevel contract"
        )
        assert exc_info is None, "this test event has no exception metadata"
        assert stack_info is False, "this test event has no stack metadata"
        self.messages.append(message)


class _SupportsFlushHandlers(typ.Protocol):
    """Minimal backend surface needed to drain asynchronous records."""

    def flush_handlers(self) -> bool:
        """Wait for pending records and report whether all handlers flushed."""


def _wait_for_records(
    backend: _SupportsFlushHandlers,
    collector: _RecordCollector,
    *,
    expected_count: int,
    timeout_seconds: float = 2.0,
) -> None:
    """Drain the asynchronous logger until the collector has enough records."""
    deadline = time.monotonic() + timeout_seconds
    while len(collector.records) < expected_count and time.monotonic() < deadline:
        backend.flush_handlers()
        time.sleep(0.01)
    backend.flush_handlers()


@pytest.fixture
def isolated_femtologging() -> cabc.Generator[None]:
    """Reset the process-wide backend manager around each integration case."""
    import femtologging

    femtologging.reset_manager()
    yield
    femtologging.reset_manager()


@pytest.mark.parametrize(
    "logger_factory",
    [episodic_logging.get_logger, episodic_logging.getLogger],
)
def test_logging_port_delivers_records_to_backend(
    isolated_femtologging: None,
    logger_factory: cabc.Callable[[str], episodic_logging.LoggerHandle],
) -> None:
    """Both logger constructors deliver formatted and exception records."""
    import femtologging

    logger_name = "tests.logging.port.integration"
    backend = femtologging.get_logger(logger_name)
    collector = _RecordCollector()
    backend.clear_handlers()
    backend.set_propagate(False)
    backend.add_handler(collector)

    logger = logger_factory(logger_name)
    episodic_logging.log_info(logger, "Loaded %s documents", 3)
    try:
        _raise_logged_exception()
    except RuntimeError:
        episodic_logging.log_exception(logger, "Failed capture %s", "job-2")

    _wait_for_records(backend, collector, expected_count=2)
    assert [
        (record.get("logger"), record.get("level"), record.get("message"))
        for record in collector.records
    ] == [
        (logger_name, "INFO", "Loaded 3 documents"),
        (logger_name, "ERROR", "Failed capture job-2"),
    ], "the public port should deliver formatted records with their logger and level"

    exception_info = collector.records[1].get("exc_info")
    assert isinstance(exception_info, dict), (
        "log_exception should carry active exception metadata to the backend"
    )
    exception_metadata = typ.cast("_ExceptionInfo", exception_info)
    assert exception_metadata.get("type_name") == "RuntimeError", (
        "the backend record should retain the active exception type"
    )
    assert exception_metadata.get("message") == "boom", (
        "the backend record should retain the active exception message"
    )


def test_logger_handle_flushes_queued_records(
    isolated_femtologging: None,
) -> None:
    """The logging handle drains queued records before process exit."""
    import femtologging

    backend = femtologging.get_logger("root")
    collector = _RecordCollector()
    backend.clear_handlers()
    backend.set_propagate(False)
    backend.add_handler(collector)

    logger = episodic_logging.get_logger("root")
    episodic_logging.log_info(logger, "queued event")

    logger.flush()
    assert len(collector.records) == 1, "flush should deliver the queued record"


def test_logger_handle_without_backend_flush_is_already_drained() -> None:
    """Synchronous custom loggers need no backend-specific flush support."""
    backend = _SynchronousLogger()
    logger = episodic_logging.LoggerHandle(backend)

    episodic_logging.log_info(logger, "synchronous event")
    assert logger.flush(), "a backend without queued handlers is already drained"
    assert backend.messages == ["synchronous event"], (
        "the synchronous backend should record the logging-port message"
    )


def _raise_logged_exception() -> None:
    """Raise a representative exception for logging metadata assertions."""
    message = "boom"
    raise RuntimeError(message)
