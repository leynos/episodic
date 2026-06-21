"""Validation helpers for local k3d preview orchestration."""

import shutil
import socket


class LocalK8sValidationError(RuntimeError):
    """Raised when local preview prerequisites are not satisfied."""


def require_tools(tool_names: list[str]) -> dict[str, str]:
    """Resolve required tools or raise with all missing tool names."""
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for tool_name in tool_names:
        path = shutil.which(tool_name)
        if path is None:
            missing.append(tool_name)
        else:
            resolved[tool_name] = path
    if missing:
        missing_text = ", ".join(sorted(missing))
        msg = f"Missing required local preview tools: {missing_text}"
        raise LocalK8sValidationError(msg)
    return resolved


def ensure_loopback_port_available(port: int) -> None:
    """Raise when a loopback TCP port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        # Avoid false negatives from this host's own sockets in TIME_WAIT after
        # recent teardown; this can also ignore those lingering sockets.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            msg = f"Loopback port {port} is not available."
            raise LocalK8sValidationError(msg) from exc
