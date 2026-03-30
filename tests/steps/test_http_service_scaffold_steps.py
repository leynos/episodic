"""Behavioural tests for the Falcon-on-Granian HTTP service scaffold."""

from __future__ import annotations

import dataclasses as dc
import os
import shutil
import socket
import subprocess  # noqa: S404 - required to start a local Granian server
import time
import typing as typ

import httpx
import pytest
from pytest_bdd import given, scenario, then, when

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path


@dc.dataclass(slots=True)
class HttpServiceScaffoldBDDContext:
    """Shared state between Granian behavioural steps."""

    base_url: str = ""
    database_url: str = ""
    process: subprocess.Popen[str] | None = None
    live_payload: dict[str, object] | None = None
    ready_payload: dict[str, object] | None = None
    log_path: Path | None = None
    log_handle: typ.TextIO | None = None


@pytest.fixture
def http_service_scaffold_context(
    migrated_database_url: str,
    tmp_path: Path,
) -> cabc.Iterator[HttpServiceScaffoldBDDContext]:
    """Share state between HTTP service scaffold steps and stop Granian."""
    context = HttpServiceScaffoldBDDContext(
        database_url=migrated_database_url,
        log_path=tmp_path / "granian-http-service-scaffold.log",
    )
    yield context
    if context.process is not None:
        context.process.terminate()
        try:
            context.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            context.process.kill()
            context.process.wait(timeout=5)
    if context.log_handle is not None:
        context.log_handle.close()


@scenario(
    "../features/http_service_scaffold.feature",
    "Granian serves the Falcon health endpoints",
)
def test_granian_serves_health_endpoints() -> None:
    """Run the Falcon-on-Granian health scenario."""


def _find_free_port() -> int:
    """Bind to an ephemeral port and return its number before releasing it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


_GRANIAN_STARTUP_TIMEOUT_SECONDS = 10.0
_GRANIAN_PROBE_INTERVAL_SECONDS = 0.2


def _read_granian_log(context: HttpServiceScaffoldBDDContext) -> str:
    """Return captured Granian output for debugging."""
    if context.log_path is None or not context.log_path.exists():
        return "<no Granian log captured>"
    return context.log_path.read_text(encoding="utf-8")


def _wait_for_health_endpoint(
    context: HttpServiceScaffoldBDDContext,
    path: str,
) -> dict[str, object]:
    """Poll a health endpoint until it returns HTTP 200 or times out."""
    deadline = time.monotonic() + _GRANIAN_STARTUP_TIMEOUT_SECONDS
    last_error = ""
    with httpx.Client(base_url=context.base_url, timeout=0.5) as client:
        while time.monotonic() < deadline:
            if context.process is not None and context.process.poll() is not None:
                msg = (
                    "Granian exited before the health endpoint became ready.\n"
                    f"{_read_granian_log(context)}"
                )
                raise RuntimeError(msg)
            try:
                response = client.get(path)
            except httpx.HTTPError as exc:
                last_error = str(exc)
                time.sleep(_GRANIAN_PROBE_INTERVAL_SECONDS)
                continue
            if response.status_code == 200:
                payload = response.json()
                return typ.cast("dict[str, object]", payload)
            last_error = f"unexpected status {response.status_code}: {response.text}"
            time.sleep(_GRANIAN_PROBE_INTERVAL_SECONDS)

    msg = (
        f"Timed out waiting for {path}. Last error: {last_error}\n"
        f"{_read_granian_log(context)}"
    )
    raise RuntimeError(msg)


@given("a Granian Falcon HTTP service is running")
def given_granian_service_running(
    http_service_scaffold_context: HttpServiceScaffoldBDDContext,
) -> None:
    """Launch Granian against the runtime factory target."""
    granian_path = shutil.which("granian")
    if granian_path is None:
        msg = "granian executable not found in PATH"
        raise RuntimeError(msg)

    port = _find_free_port()
    http_service_scaffold_context.base_url = f"http://127.0.0.1:{port}"
    if http_service_scaffold_context.log_path is None:
        msg = "Granian log path was not initialized."
        raise RuntimeError(msg)
    http_service_scaffold_context.log_handle = (
        http_service_scaffold_context.log_path.open("w", encoding="utf-8")
    )
    env = {
        **os.environ,
        "DATABASE_URL": http_service_scaffold_context.database_url,
    }
    http_service_scaffold_context.process = subprocess.Popen(  # noqa: S603
        [
            granian_path,
            "episodic.api.runtime:create_app_from_env",
            "--interface",
            "asgi",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=http_service_scaffold_context.log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )


@when("an operator checks the health endpoints")
def when_operator_checks_health_endpoints(
    http_service_scaffold_context: HttpServiceScaffoldBDDContext,
) -> None:
    """Poll the live service until both health endpoints respond."""
    http_service_scaffold_context.live_payload = _wait_for_health_endpoint(
        http_service_scaffold_context,
        "/health/live",
    )
    http_service_scaffold_context.ready_payload = _wait_for_health_endpoint(
        http_service_scaffold_context,
        "/health/ready",
    )


@then("the liveness endpoint reports that the application is up")
def then_liveness_reports_application_up(
    http_service_scaffold_context: HttpServiceScaffoldBDDContext,
) -> None:
    """Assert the liveness contract exposed over real HTTP."""
    assert http_service_scaffold_context.live_payload == {
        "status": "ok",
        "checks": [{"name": "application", "status": "ok"}],
    }


@then("the readiness endpoint reports that the database is ready")
def then_readiness_reports_database_ready(
    http_service_scaffold_context: HttpServiceScaffoldBDDContext,
) -> None:
    """Assert the readiness contract exposed over real HTTP."""
    assert http_service_scaffold_context.ready_payload == {
        "status": "ok",
        "checks": [{"name": "database", "status": "ok"}],
    }
