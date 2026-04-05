"""Behavioural tests for the Falcon-on-Granian HTTP service scaffold."""

from __future__ import annotations

import dataclasses as dc
import os
import shutil
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


def _require_granian_process(
    context: HttpServiceScaffoldBDDContext,
) -> subprocess.Popen[str]:
    """Return the running Granian process or fail with a clear error."""
    if context.process is None:
        msg = "Granian process has not been started."
        raise RuntimeError(msg)
    return context.process


def _read_granian_listening_ports(
    process: subprocess.Popen[str],
    lsof_path: str,
) -> list[int]:
    """Inspect a Granian process and return any listening TCP ports."""
    result = subprocess.run(  # noqa: S603 - trusted local diagnostic command
        [
            lsof_path,
            "-Pan",
            "-a",
            "-p",
            str(process.pid),
            "-iTCP",
            "-sTCP:LISTEN",
            "-Fn",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in {0, 1}:
        msg = (
            "Failed to inspect Granian listening sockets.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
        raise RuntimeError(msg)

    ports: list[int] = []
    for line in result.stdout.splitlines():
        if not line.startswith("n"):
            continue
        _, _, port = line[1:].rpartition(":")
        if port.isdigit():
            ports.append(int(port))
    return ports


def _wait_for_granian_port(context: HttpServiceScaffoldBDDContext) -> int:
    """Poll the Granian process until it binds an ephemeral listening port."""
    process = _require_granian_process(context)
    lsof_path = shutil.which("lsof")
    if lsof_path is None:
        pytest.skip("Granian BDD tests require the `lsof` executable in PATH.")

    deadline = time.monotonic() + _GRANIAN_STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            msg = (
                "Granian exited before binding a listening port.\n"
                f"{_read_granian_log(context)}"
            )
            raise RuntimeError(msg)

        listening_ports = _read_granian_listening_ports(process, lsof_path)
        if listening_ports:
            return listening_ports[0]

        time.sleep(_GRANIAN_PROBE_INTERVAL_SECONDS)

    msg = (
        "Timed out waiting for Granian to bind an ephemeral port.\n"
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
        pytest.skip("granian executable not found in PATH")

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
            "0",
        ],
        env=env,
        stdout=http_service_scaffold_context.log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    port = _wait_for_granian_port(http_service_scaffold_context)
    http_service_scaffold_context.base_url = f"http://127.0.0.1:{port}"


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


def _assert_health_check_ok(
    payload: dict[str, object] | None,
    kind: str,
    check_name: str,
) -> None:
    """Assert a health endpoint payload contains a named check with status ok."""
    assert payload is not None, f"Expected the {kind} payload to be captured."
    assert payload.get("status") == "ok", f"Expected {kind} status to be ok."
    checks = typ.cast("list[dict[str, object]]", payload.get("checks", []))
    assert any(
        check.get("name") == check_name and check.get("status") == "ok"
        for check in checks
    ), f"Expected a {check_name} health check with status ok."


@then("the liveness endpoint reports that the application is up")
def then_liveness_reports_application_up(
    http_service_scaffold_context: HttpServiceScaffoldBDDContext,
) -> None:
    """Assert the liveness contract exposed over real HTTP."""
    _assert_health_check_ok(
        http_service_scaffold_context.live_payload,
        "liveness",
        "application",
    )


@then("the readiness endpoint reports that the database is ready")
def then_readiness_reports_database_ready(
    http_service_scaffold_context: HttpServiceScaffoldBDDContext,
) -> None:
    """Assert the readiness contract exposed over real HTTP."""
    _assert_health_check_ok(
        http_service_scaffold_context.ready_payload,
        "readiness",
        "database",
    )
