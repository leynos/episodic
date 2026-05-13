"""Shared helpers for GitHub Actions workflow integration tests."""

from __future__ import annotations

import json
import os
import socket
import subprocess  # noqa: S404
import typing as typ
from shutil import which
from zipfile import ZipFile

import pytest

from tests.utils import podman_socket_path

if typ.TYPE_CHECKING:
    from pathlib import Path


def artifact_server_port() -> str:
    """Reserve a free local port for the act artifact server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return str(sock.getsockname()[1])


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
    port = artifact_server_port()
    cmd = [
        "act",
        "workflow_dispatch",
        "-j",
        job_name,
        "-e",
        str(event_path),
        "-P",
        "ubuntu-latest=catthehacker/ubuntu:act-latest",
        "--container-daemon-socket",
        socket_uri,
        "--artifact-server-addr",
        "127.0.0.1",
        "--artifact-server-port",
        port,
        "--artifact-server-path",
        str(artifact_dir),
        "--json",
        "-b",
    ]
    env = os.environ.copy()
    env["DOCKER_HOST"] = socket_uri
    # Act invocation uses controlled workflow test arguments.
    completed = subprocess.run(  # noqa: S603
        cmd,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    logs = completed.stdout + "\n" + completed.stderr
    return completed.returncode, logs


def read_artifact_json(artifact_dir: Path, filename: str, logs: str) -> dict[str, str]:
    """Load JSON from a workflow artifact file or the artifact zip."""
    json_files = list(artifact_dir.rglob(filename))
    if json_files:
        return json.loads(json_files[0].read_text())

    zip_files = list(artifact_dir.rglob("*.zip"))
    if not zip_files:
        msg = f"artifact zip missing. Logs:\n{logs}"
        raise AssertionError(msg)

    for zip_path in zip_files:
        with ZipFile(zip_path) as zf:
            if filename in zf.namelist():
                return json.loads(zf.read(filename).decode())

    msg = f"{filename} missing in artifact zips. Logs:\n{logs}"
    raise AssertionError(msg)
