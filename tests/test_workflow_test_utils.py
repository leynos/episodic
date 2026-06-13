"""Tests for workflow integration test helpers."""

from tests.workflow_test_utils import artifact_server_addr, artifact_server_port


def test_artifact_server_binds_for_rootless_podman_job_containers() -> None:
    """Keep act's artifact server reachable from rootless Podman containers."""
    # The local act artifact server must be reachable from rootless job containers.
    server_addr = artifact_server_addr()
    assert server_addr == "0.0.0.0", (  # noqa: S104
        f"artifact_server_addr() returned {server_addr!r}, expected '0.0.0.0'."
    )
    port = int(artifact_server_port())
    assert 0 < port < 65536, (
        f"artifact_server_port() returned invalid port {port}; expected 1-65535."
    )
