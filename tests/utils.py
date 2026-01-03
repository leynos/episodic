"""Shared utilities for workflow integration tests."""

from __future__ import annotations

import os
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
    return socket_path
