from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from shutil import which
from zipfile import ZipFile

EVENT = Path("tests/fixtures/provision_doks.event.json")


def podman_socket() -> Path:
    socket = Path(f"/run/user/{os.getuid()}/podman/podman.sock")
    assert socket.exists(), (
        "Podman socket not found. "
        "Enable it with `systemctl --user enable --now podman.socket`."
    )
    return socket


def run_act(*, artifact_dir: Path) -> tuple[int, str]:
    if which("act") is None:
        raise AssertionError("act is required to run workflow integration tests.")

    socket = podman_socket()
    socket_uri = f"unix://{socket}"
    cmd = [
        "act",
        "workflow_dispatch",
        "-j",
        "provision",
        "-e",
        str(EVENT),
        "-P",
        "ubuntu-latest=catthehacker/ubuntu:act-latest",
        "--container-daemon-socket",
        socket_uri,
        "--artifact-server-path",
        str(artifact_dir),
        "--json",
        "-b",
    ]
    env = os.environ.copy()
    env["DOCKER_HOST"] = socket_uri
    completed = subprocess.run(cmd, text=True, capture_output=True, env=env)
    logs = completed.stdout + "\n" + completed.stderr
    return completed.returncode, logs


def read_artifact_json(artifact_dir: Path, filename: str, logs: str) -> dict[str, str]:
    json_files = list(artifact_dir.rglob(filename))
    if json_files:
        return json.loads(json_files[0].read_text())

    zip_files = list(artifact_dir.rglob("*.zip"))
    assert zip_files, f"artifact zip missing. Logs:\n{logs}"

    for zip_path in zip_files:
        with ZipFile(zip_path) as zf:
            if filename in zf.namelist():
                return json.loads(zf.read(filename).decode())

    raise AssertionError(f"{filename} missing in artifact zips. Logs:\n{logs}")


def test_provision_doks_workflow(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "act-artifacts"
    code, logs = run_act(artifact_dir=artifact_dir)
    assert code == 0, f"act failed:\n{logs}"

    data = read_artifact_json(artifact_dir, "provision-result.json", logs)
    assert data["status"] == "ok"
    assert data["execution_mode"] == "validate"
