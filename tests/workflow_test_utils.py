"""Shared helpers for GitHub Actions workflow integration tests."""

import json
import os
import socket
import subprocess  # noqa: S404
import typing as typ
import uuid
from shutil import which
from zipfile import ZipFile

import pytest

from tests.utils import podman_socket_path

ACT_RUNNER_IMAGE = "catthehacker/ubuntu:act-latest"

if typ.TYPE_CHECKING:
    from pathlib import Path


def artifact_server_port() -> str:
    """Return a currently free host port for act's artifact server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return str(listener.getsockname()[1])


def artifact_server_addr() -> str:
    """Bind act's artifact server where rootless Podman containers can reach it."""
    return "0.0.0.0"  # noqa: S104 - local test server must accept job containers.


def _ensure_string_kv(key: object, item: object) -> tuple[str, str]:
    """Assert *key* and *item* are both strings and return them typed."""
    if not isinstance(key, str):
        msg = f"Expected a string key, got {type(key).__name__}"
        raise AssertionError(msg)  # noqa: TRY004
    if not isinstance(item, str):
        msg = f"Expected a string value for key {key!r}, got {type(item).__name__}"
        raise AssertionError(msg)  # noqa: TRY004
    return key, item


def _ensure_string_dict(value: object, _filename: str) -> dict[str, str]:
    """Return a mapping with str keys and str values, or raise with diagnostics."""
    if not isinstance(value, dict):
        msg = f"Expected a mapping[str, str], got {type(value).__name__}"
        raise AssertionError(msg)  # noqa: TRY004
    result: dict[str, str] = {}
    for key, item in value.items():
        k, v = _ensure_string_kv(key, item)
        result[k] = v
    return result


def _timeout_output_part_to_text(part: bytes | str) -> str:
    """Decode one partial subprocess timeout output fragment."""
    if isinstance(part, bytes):
        return part.decode(encoding="utf-8", errors="replace")
    return part


def _format_timeout_output(exc: subprocess.TimeoutExpired) -> str:
    """Join any partial stdout/stderr captured before the timeout."""
    return "\n".join(
        _timeout_output_part_to_text(part)
        for part in (exc.output, exc.stderr)
        if part is not None
    )


def _run_preflight_container(
    podman_path: str,
    socket_uri: str,
    container_name: str,
) -> subprocess.CompletedProcess[str]:
    """Run the preflight container; call pytest.skip and raise on timeout."""
    cmd = [
        podman_path,
        "--remote",
        "--url",
        socket_uri,
        "run",
        "--rm",
        "--name",
        container_name,
        "--entrypoint",
        "/bin/true",
        ACT_RUNNER_IMAGE,
    ]
    try:
        return subprocess.run(  # noqa: S603
            cmd,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.skip(
            "act runner backend timed out starting "
            f"{ACT_RUNNER_IMAGE}: {_format_timeout_output(exc)}"
        )
        raise  # unreachable; satisfies type-checkers that don't model pytest.skip


def _cleanup_preflight_container(
    podman_path: str,
    socket_uri: str,
    container_name: str,
) -> None:
    """Force-remove a stalled preflight container."""
    subprocess.run(  # noqa: S603
        [podman_path, "--remote", "--url", socket_uri, "rm", "-f", container_name],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def _ensure_act_runner_backend(socket_uri: str) -> None:
    """Skip workflow tests when the local act runner backend cannot start."""
    podman_path = which("podman")
    if podman_path is None:
        pytest.skip("podman is required to preflight the act runner backend.")
    container_name = f"episodic-act-preflight-{uuid.uuid4()}"
    completed = _run_preflight_container(podman_path, socket_uri, container_name)
    if completed.returncode == 0:
        return
    _cleanup_preflight_container(podman_path, socket_uri, container_name)
    pytest.skip(
        "act runner backend cannot start "
        f"{ACT_RUNNER_IMAGE}: {completed.stderr or completed.stdout}"
    )


def _run_act_subprocess(cmd: list[str], env: dict[str, str]) -> tuple[int, str]:
    """Execute act and return (returncode, combined_logs); raise on timeout."""
    try:
        completed = subprocess.run(  # noqa: S603
            cmd,
            text=True,
            capture_output=True,
            env=env,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        msg = (
            f"act timed out after {exc.timeout} seconds for command {cmd!r}.\n"
            f"Partial output:\n{_format_timeout_output(exc)}"
        )
        raise AssertionError(msg) from exc
    return completed.returncode, completed.stdout + "\n" + completed.stderr


def run_act(
    *,
    job_name: str,
    artifact_dir: Path,
    event_path: Path,
) -> tuple[int, str]:
    """Run act for the workflow and return the exit code and logs."""
    if which("act") is None:
        pytest.skip("act is required to run workflow integration tests.")
    socket_path = podman_socket_path()
    socket_uri = f"unix://{socket_path}"
    _ensure_act_runner_backend(socket_uri)
    port = artifact_server_port()
    cmd = [
        "act",
        "workflow_dispatch",
        "-j",
        job_name,
        "-e",
        str(event_path),
        "-P",
        f"ubuntu-latest={ACT_RUNNER_IMAGE}",
        "--container-daemon-socket",
        socket_uri,
        "--artifact-server-addr",
        artifact_server_addr(),
        "--artifact-server-port",
        port,
        "--artifact-server-path",
        str(artifact_dir),
        "--json",
        "-b",
    ]
    env = os.environ.copy()
    env["DOCKER_HOST"] = socket_uri
    return _run_act_subprocess(cmd, env)


def _find_in_zips(
    zip_files: list[Path],
    filename: str,
    logs: str,
) -> dict[str, str]:
    """Search artifact zip files for *filename* and return its parsed JSON."""
    for zip_path in zip_files:
        with ZipFile(zip_path) as zf:
            if filename in zf.namelist():
                return _ensure_string_dict(
                    json.loads(zf.read(filename).decode(encoding="utf-8")),
                    filename,
                )

    msg = f"{filename} missing in artifact zips. Logs:\n{logs}"
    raise AssertionError(msg)


def read_artifact_json(artifact_dir: Path, filename: str, logs: str) -> dict[str, str]:
    """Load JSON from a workflow artifact file or the artifact zip."""
    json_files = sorted(artifact_dir.rglob(filename))
    if json_files:
        return _ensure_string_dict(
            json.loads(json_files[0].read_text(encoding="utf-8")),
            filename,
        )
    zip_files = sorted(artifact_dir.rglob("*.zip"))
    if not zip_files:
        msg = f"artifact zip missing. Logs:\n{logs}"
        raise AssertionError(msg)
    return _find_in_zips(zip_files, filename, logs)
