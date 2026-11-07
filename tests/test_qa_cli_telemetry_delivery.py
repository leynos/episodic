"""Delivery tests for the installed command's structured-log telemetry.

Every case runs the real entry point in a fresh interpreter against a stub
HTTP server, so the assertions describe what an operator receives rather than
what an injected sink records. The command has to configure its own logging:
femtologging starts with no handlers, and a sink that writes to a handlerless
logger delivers nothing.
"""

import contextlib
import dataclasses as dc
import http.server
import json
import os
import pathlib
import subprocess  # ruff: ignore[suspicious-subprocess-import]  # The test starts the repository's own entry point.
import sys
import threading
import typing as typ

from tests.qa_cli_fixtures import PAGE, list_arguments

if typ.TYPE_CHECKING:
    import collections.abc as cabc

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ENTRY_POINT = "import sys; from episodic.cli import main; raise SystemExit(main())"
TOKEN = "telemetry-secret-token"  # ruff: ignore[hardcoded-password-string]  # A value a log must not leak.
SPAN = "cli.qa_evaluations.list"
LATENCY = f"{SPAN}.latency_ms"
THROTTLE = {"code": "rate_limited", "message": "Too many requests."}


@dc.dataclass(slots=True)
class _StubApi:
    """A running stub API and the credentials its requests carried."""

    base_url: str
    authorizations: list[str | None] = dc.field(default_factory=list)


def _make_handler(status: int, payload: object, api: _StubApi) -> type:
    """Return a request handler that answers every GET with one body."""

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            api.authorizations.append(self.headers.get("Authorization"))
            body = json.dumps(payload).encode("utf8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(  # ty: ignore[invalid-method-override]  # Mirrors the stdlib signature.
            self,
            message_format: str,
            *args: object,
        ) -> None:
            """Silence the server's own request log."""

    return _Handler


@contextlib.contextmanager
def _stub_api(
    status: int = 200,
    payload: object = PAGE,
) -> cabc.Iterator[_StubApi]:
    """Serve one canned response and yield the API's base URL."""
    api = _StubApi(base_url="")
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _make_handler(status, payload, api),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = typ.cast("tuple[str, int]", server.server_address[:2])
    api.base_url = f"http://{host}:{port}"
    try:
        yield api
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def _run_cli(
    base_url: str,
    *arguments: str,
    log_level: str | None = "INFO",
) -> subprocess.CompletedProcess[str]:
    """Run the installed entry point in a fresh interpreter."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("EPISODIC_")
    }
    if log_level is not None:
        environment["EPISODIC_LOG_LEVEL"] = log_level
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # The argv is the test's own entry point.
        [sys.executable, "-c", ENTRY_POINT, "--base-url", base_url, *arguments],
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        timeout=60,
    )


def _telemetry(stream: str) -> list[dict[str, object]]:
    """Return the structured events a captured stream carried."""
    events: list[dict[str, object]] = []
    for line in stream.splitlines():
        start = line.find("{")
        if start == -1:
            continue
        try:
            decoded = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict) and "event" in decoded:
            events.append(typ.cast("dict[str, object]", decoded))
    return events


def _only(events: list[dict[str, object]], name: str) -> dict[str, object]:
    """Return the single event named ``name``, failing if it is not unique."""
    matching = [event for event in events if event["event"] == name]
    assert len(matching) == 1, f"expected exactly one {name} event in {events}"
    return matching[0]


def test_installed_command_delivers_a_completed_span_and_latency() -> None:
    """A fresh process reports one completed span and one latency observation."""
    with _stub_api() as api:
        result = _run_cli(
            api.base_url,
            "--token",
            TOKEN,
            *list_arguments("--format", "json"),
        )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["total"] == PAGE["total"], (
        "standard output must stay a single JSON document"
    )
    assert api.authorizations == [f"Bearer {TOKEN}"], api.authorizations

    events = _telemetry(result.stderr)
    completed = _only(events, "trace_span_completed")
    assert completed["span_name"] == SPAN, completed
    assert completed["operation"] == SPAN, completed
    assert completed["outcome"] == "success", completed

    latency = _only(events, "metric_latency")
    assert latency["metric_name"] == LATENCY, latency
    assert latency["labels"] == {"outcome": "success"}, latency

    assert TOKEN not in result.stderr, "the credential must not reach the logs"
    assert TOKEN not in result.stdout, "the credential must not reach the output"


def test_installed_command_delivers_a_bounded_failure_observation() -> None:
    """A throttled call reports a failed span and its failure category."""
    with _stub_api(status=429, payload=THROTTLE) as api:
        result = _run_cli(api.base_url, *list_arguments())

    assert result.returncode == 4, result.stderr
    events = _telemetry(result.stderr)
    failed = _only(events, "trace_span_failed")
    assert failed["span_name"] == SPAN, failed
    assert failed["outcome"] == "failed", failed
    assert failed["failure_category"] == "rate_limited", failed

    latency = _only(events, "metric_latency")
    assert latency["labels"] == {
        "outcome": "failed",
        "failure_category": "rate_limited",
    }, latency


def test_default_level_keeps_a_successful_command_silent() -> None:
    """With no level configured, a good run writes nothing to standard error."""
    with _stub_api() as api:
        result = _run_cli(api.base_url, *list_arguments(), log_level=None)

    assert result.returncode == 0, result.stderr
    assert not _telemetry(result.stderr), result.stderr
