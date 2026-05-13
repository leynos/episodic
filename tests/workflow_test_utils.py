"""Shared helpers for GitHub Actions workflow integration tests."""

import json
import os
import subprocess  # noqa: S404
import typing as typ
from shutil import which
from zipfile import ZipFile

import pytest

from tests.utils import podman_socket_path

if typ.TYPE_CHECKING:
    from pathlib import Path


def artifact_server_port() -> str:
    """Ask act to bind the artifact server to an ephemeral local port."""
    return "0"


def _ensure_string_dict(value: object, _filename: str) -> dict[str, str]:
    """Return a mapping with str keys and str values, or raise with diagnostics."""
    if not isinstance(value, dict):
        msg = f"Expected a mapping[str, str], got {type(value).__name__}"
        raise AssertionError(msg)  # noqa: TRY004 - test helper assertion contract.
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            msg = f"Expected a string key, got {type(key).__name__}"
            raise AssertionError(msg)  # noqa: TRY004 - test helper assertion contract.
        if not isinstance(item, str):
            msg = f"Expected a string value for key {key!r}, got {type(item).__name__}"
            raise AssertionError(msg)  # noqa: TRY004 - test helper assertion contract.
        result[key] = item
    return result


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
        return _ensure_string_dict(
            json.loads(json_files[0].read_text(encoding="utf-8")),
            filename,
        )

    zip_files = list(artifact_dir.rglob("*.zip"))
    if not zip_files:
        msg = f"artifact zip missing. Logs:\n{logs}"
        raise AssertionError(msg)

    for zip_path in zip_files:
        with ZipFile(zip_path) as zf:
            if filename in zf.namelist():
                return _ensure_string_dict(
                    json.loads(zf.read(filename).decode(encoding="utf-8")),
                    filename,
                )

    msg = f"{filename} missing in artifact zips. Logs:\n{logs}"
    raise AssertionError(msg)
