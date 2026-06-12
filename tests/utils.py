"""Shared utilities for workflow integration tests."""

import os
import socket
from pathlib import Path

import pytest


def podman_socket_path() -> Path:
    """Return the expected Podman socket path."""
    socket_path = Path(f"/run/user/{os.getuid()}/podman/podman.sock")
    if not socket_path.exists():
        pytest.skip(
            "Podman socket not found. "
            "Enable it with `systemctl --user enable --now podman.socket`."
        )
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1.0)
            client.connect(str(socket_path))
    except OSError:
        pytest.skip(
            "Podman socket is not accepting connections. "
            "Enable it with `systemctl --user enable --now podman.socket`."
        )
    return socket_path
