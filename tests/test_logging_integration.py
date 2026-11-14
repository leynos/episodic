"""Integration tests for the public logging port and its backend."""

import json
import multiprocessing as mp
import time
import typing as typ

import pytest

from episodic import logging as episodic_logging

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import pathlib as pathlib


_PROBE_CREDENTIAL = "fresh-runtime-secret-marker"
_PROBE_ENTITY_ID = "00000000-0000-0000-0000-000000000007"


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


def _wait_for_record_count(
    collector: _RecordCollector,
    *,
    expected_count: int,
    timeout_seconds: float = 2.0,
) -> None:
    """Wait for async delivery without blocking in the backend's drain call."""
    deadline = time.monotonic() + timeout_seconds
    while len(collector.records) < expected_count and time.monotonic() < deadline:
        time.sleep(0.01)


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

    _wait_for_record_count(collector, expected_count=2)
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


async def _raise_unmapped_profile_error(
    *_args: object,
    **_kwargs: object,
) -> typ.NoReturn:
    """Raise a profile error containing values the diagnostic must redact."""
    import asyncio

    from episodic.canonical.profile_templates.types import ProfileTemplateError

    await asyncio.sleep(0)
    raise ProfileTemplateError(
        _PROBE_CREDENTIAL,
        code=_PROBE_CREDENTIAL,
        entity_id=_PROBE_CREDENTIAL,
    )


def _run_fresh_runtime_error_probe(report_path: pathlib.Path) -> None:
    """Trigger an unmapped API error in a newly configured runtime process."""
    import os
    from unittest import mock

    os.environ.clear()
    os.environ.update({
        "API_AUTHORIZATION_BEARER_TOKEN": "runtime-test-token",
        "API_AUTHORIZATION_PRINCIPAL_ID": "runtime-test-principal",
        "DATABASE_URL": "postgresql://example.test/episodic",
        "EPISODIC_LOG_LEVEL": "ERROR",
        "SOURCE_INTAKE_OBJECT_STORE_ROOT": str(report_path.parent),
    })

    import femtologging
    from falcon import testing

    femtologging.reset_manager()

    import episodic.api.app as api_app
    from episodic.api import runtime as runtime_module
    from episodic.api.resources import series_profiles

    api_app.logger = episodic_logging.get_logger(api_app.__name__)
    backend = femtologging.get_logger(api_app.__name__)
    collector = _RecordCollector()
    backend.clear_handlers()
    backend.set_propagate(True)
    backend.add_handler(collector)
    with mock.patch.object(
        series_profiles,
        "get_entity_with_revision",
        _raise_unmapped_profile_error,
    ):
        app = runtime_module.create_app_from_env()
        response = testing.TestClient(app).simulate_get(
            f"/v1/series-profiles/{_PROBE_ENTITY_ID}",
            headers={"Authorization": "Bearer runtime-test-token"},
        )
    _wait_for_record_count(collector, expected_count=1)

    report_path.write_text(
        json.dumps({
            "status": response.status_code,
            "body": response.json,
            "records": collector.records,
        }),
        encoding="utf-8",
    )


def test_unmapped_api_error_reaches_real_backend(
    tmp_path: pathlib.Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Production startup configures a real handler for redacted API errors."""
    report_path = tmp_path / "runtime-error-probe.json"
    process = mp.get_context("spawn").Process(
        target=_run_fresh_runtime_error_probe,
        args=(report_path,),
    )
    process.start()
    process.join(timeout=15)
    if process.is_alive():
        process.terminate()
        process.join()
        pytest.fail("fresh runtime error probe exceeded 15 seconds")
    assert process.exitcode == 0, "fresh runtime error probe must complete"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    captured = capfd.readouterr()
    assert report["status"] == 500, "unmapped API errors must remain HTTP 500"
    assert report["body"] == {
        "code": "internal_error",
        "message": "Unexpected profile/template error.",
        "details": {},
    }, "the production runtime must preserve the generic client envelope"
    records = typ.cast("list[dict[str, object]]", report["records"])
    assert len(records) == 1, "the real backend must receive one API error"
    record = records[0]
    assert record.get("level") == "ERROR", "unmapped failures use ERROR level"
    message = typ.cast("str", record.get("message"))
    exception_info = record.get("exc_info")
    assert _PROBE_CREDENTIAL not in message, (
        "the backend record must redact source values"
    )
    assert isinstance(exception_info, dict), (
        "the ERROR record must include detached exception data"
    )
    assert _PROBE_CREDENTIAL not in str(exception_info), (
        "detached exception data must not retain source secrets"
    )
    assert "Unmapped profile/template error" in captured.err, (
        "the configured production handler must receive the ERROR record"
    )
    assert _PROBE_CREDENTIAL not in captured.err, (
        "the configured production handler must not leak source values"
    )


def _raise_logged_exception() -> None:
    """Raise a representative exception for logging metadata assertions."""
    message = "boom"
    raise RuntimeError(message)
