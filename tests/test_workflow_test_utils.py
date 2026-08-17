"""Tests for workflow integration test helpers."""

from tests.test_workflow_utils import (
    _has_unsupported_artifact_protocol,
    artifact_server_addr,
    artifact_server_port,
)


def test_artifact_server_binds_for_rootless_podman_job_containers() -> None:
    """Keep act's artifact server reachable from rootless Podman containers."""
    # The local act artifact server must be reachable from rootless job containers.
    server_addr = artifact_server_addr()
    assert server_addr == "0.0.0.0", (  # noqa: S104  # The wildcard address is a fixed expected value, not a listening configuration.
        f"artifact_server_addr() returned {server_addr!r}, expected '0.0.0.0'."
    )
    port = int(artifact_server_port())
    assert 0 < port < 65536, (
        f"artifact_server_port() returned invalid port {port}; expected 1-65535."
    )


def test_artifact_protocol_detection_is_narrow() -> None:
    """Skip only when the artifact protocol is the sole failed act step."""
    unsupported_logs = (
        '{"level":"error","job":"validate","step":"Upload artifact",'
        r'"msg":"Error decode request body: unknown field \"mime_type\""}'
    )
    assert _has_unsupported_artifact_protocol(unsupported_logs), (
        "Expected the upload-artifact mime_type incompatibility to be recognized."
    )
    assert not _has_unsupported_artifact_protocol(
        '{"level":"error","job":"validate","step":"Upload artifact",'
        r'"msg":"Error decode request body: unknown field \"content_type\""}'
    ), "An unrelated artifact-server error must remain a workflow failure."


def test_artifact_protocol_detection_preserves_other_failed_steps() -> None:
    """A second failed step must prevent an artifact compatibility skip."""
    logs = "\n".join((
        (
            '{"level":"error","job":"validate","step":"Upload artifact",'
            r'"msg":"Error decode request body: unknown field \"mime_type\""}'
        ),
        (
            '{"level":"error","job":"validate","step":"Run validation",'
            '"msg":"validation command failed"}'
        ),
    ))

    assert not _has_unsupported_artifact_protocol(logs), (
        "A separate failed step must remain visible as a workflow failure."
    )
