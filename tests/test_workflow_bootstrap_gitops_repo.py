"""Workflow integration tests for the GitOps bootstrap workflow."""

from __future__ import annotations

import json
import os
import socket
import subprocess  # noqa: S404
from pathlib import Path
from shutil import which
from zipfile import ZipFile

import pytest

EVENT = Path("tests/fixtures/bootstrap_gitops_repo.event.json")


def podman_socket() -> Path:
    """Return the expected Podman socket path."""
    socket = Path(f"/run/user/{os.getuid()}/podman/podman.sock")
    assert socket.exists(), (
        "Podman socket not found. "
        "Enable it with `systemctl --user enable --now podman.socket`."
    )
    return socket


def artifact_server_port() -> str:
    """Reserve a free local port for the act artifact server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return str(sock.getsockname()[1])


def run_act(*, artifact_dir: Path) -> tuple[int, str]:
    """Run act for the workflow and return the exit code and logs."""
    if which("act") is None:
        pytest.skip("act is required to run workflow integration tests.")

    socket = podman_socket()
    socket_uri = f"unix://{socket}"
    port = artifact_server_port()
    cmd = [
        "act",
        "workflow_dispatch",
        "-j",
        "bootstrap",
        "-e",
        str(EVENT),
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
    # Act invocation uses static arguments in this test.
    completed = subprocess.run(  # noqa: S603
        cmd,
        text=True,
        capture_output=True,
        env=env,
    )
    logs = completed.stdout + "\n" + completed.stderr
    return completed.returncode, logs


def read_artifact_json(artifact_dir: Path, filename: str, logs: str) -> dict[str, str]:
    """Load JSON from a workflow artifact file or the artifact zip."""
    json_files = list(artifact_dir.rglob(filename))
    if json_files:
        return json.loads(json_files[0].read_text())

    zip_files = list(artifact_dir.rglob("*.zip"))
    assert zip_files, f"artifact zip missing. Logs:\n{logs}"

    for zip_path in zip_files:
        with ZipFile(zip_path) as zf:
            if filename in zf.namelist():
                return json.loads(zf.read(filename).decode())

    pytest.fail(f"{filename} missing in artifact zips. Logs:\n{logs}")


@pytest.mark.act
def test_bootstrap_gitops_repo_workflow(tmp_path: Path) -> None:
    """Assert that the bootstrap workflow produces a success result."""
    artifact_dir = tmp_path / "act-artifacts"
    code, logs = run_act(artifact_dir=artifact_dir)
    assert code == 0, f"act failed:\n{logs}"

    data = read_artifact_json(artifact_dir, "bootstrap-result.json", logs)
    assert data["status"] == "ok"
    assert data["execution_mode"] == "validate"
