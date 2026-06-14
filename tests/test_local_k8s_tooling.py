"""Tests for local k3d preview helper contracts."""

import socket
import subprocess
from collections.abc import Callable  # noqa: ICN003, TC003 - requested test shape.

import pytest

from scripts.local_k8s import commands
from scripts.local_k8s.config import PreviewConfig
from scripts.local_k8s.orchestration import cluster_exists, down, logs, status, up
from scripts.local_k8s.validation import (
    LocalK8sValidationError,
    ensure_loopback_port_available,
    require_tools,
)


class RecordingRunner:
    """Test runner that records commands and returns queued results."""

    def __init__(
        self,
        results: list[subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.commands: list[list[str]] = []
        self.input_texts: list[str | None] = []
        self._results = results or []

    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Record a command and return the next queued process result."""
        self.commands.append(args)
        self.input_texts.append(input_text)
        if self._results:
            return self._results.pop(0)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=input_text or "",
            stderr="",
        )


def test_k3d_cluster_create_command_maps_ingress_port() -> None:
    """Build the expected k3d load-balancer port mapping."""
    config = PreviewConfig(cluster_name="demo", ingress_port=9090)

    assert commands.k3d_cluster_create_command(config) == [
        "k3d",
        "cluster",
        "create",
        "demo",
        "--agents",
        "1",
        "--port",
        "127.0.0.1:9090:80@loadbalancer",
        "--wait",
    ]


def test_helm_upgrade_command_uses_local_chart_values() -> None:
    """Build the Helm command used by the preview workflow."""
    config = PreviewConfig(cluster_name="demo", namespace="preview")

    command = commands.helm_upgrade_command(config)

    assert command[:5] == ["helm", "--kube-context", "k3d-demo", "upgrade", "--install"]
    assert "--values" in command, "local values file must be passed to Helm."
    assert str(config.values_path) in command, "local values path must be rendered."


def test_kubectl_secret_command_renders_database_url_literal() -> None:
    """Create the app Secret from the configured local database URL."""
    config = PreviewConfig(database_url="postgresql+asyncpg://user:pass@postgres/db")

    command = commands.kubectl_secret_command(config)

    assert "--from-literal=database-url=postgresql+asyncpg://user:pass@postgres/db" in (
        command
    )


def test_loopback_port_validation_reports_occupied_port() -> None:
    """Reject a local ingress port that is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        occupied_port = listener.getsockname()[1]

        with pytest.raises(LocalK8sValidationError, match=str(occupied_port)):
            ensure_loopback_port_available(occupied_port)


def test_require_tools_reports_all_missing_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report every missing tool rather than failing one at a time."""
    monkeypatch.setattr("shutil.which", lambda _: None)

    with pytest.raises(LocalK8sValidationError, match="docker, helm"):
        require_tools(["helm", "docker"])


def test_cluster_exists_returns_false_for_missing_cluster() -> None:
    """Treat k3d cluster lookup failure as an absent cluster."""
    runner = RecordingRunner([
        subprocess.CompletedProcess(
            args=["k3d"],
            returncode=1,
            stdout="",
            stderr="not found",
        )
    ])

    assert not cluster_exists(PreviewConfig(), runner), (
        "cluster_exists must return False when k3d lookup fails."
    )


def test_down_is_idempotent_when_cluster_is_absent() -> None:
    """Do not attempt deletion when k3d reports the cluster is missing."""
    runner = RecordingRunner([
        subprocess.CompletedProcess(
            args=["k3d"],
            returncode=1,
            stdout="",
            stderr="not found",
        )
    ])

    down(PreviewConfig(cluster_name="missing"), runner)

    assert runner.commands == [["k3d", "cluster", "get", "missing"]], (
        "down must only check existence, not attempt deletion when cluster is absent."
    )


def test_up_bootstraps_postgres_before_installing_chart(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Apply local Postgres manifests before Helm waits on app readiness."""
    monkeypatch.setattr(
        "scripts.local_k8s.orchestration.require_tools",
        lambda _: None,
    )
    monkeypatch.setattr(
        "scripts.local_k8s.orchestration.ensure_loopback_port_available",
        lambda _: None,
    )
    runner = RecordingRunner([
        subprocess.CompletedProcess(args=["k3d"], returncode=1, stdout="", stderr=""),
        subprocess.CompletedProcess(args=["k3d"], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(
            args=["kubectl"],
            returncode=0,
            stdout="apiVersion: v1\nkind: Namespace\n",
            stderr="",
        ),
        subprocess.CompletedProcess(
            args=["kubectl"],
            returncode=0,
            stdout="apiVersion: v1\nkind: Secret\n",
            stderr="",
        ),
    ])

    up(PreviewConfig(cluster_name="demo", ingress_port=9090), runner, skip_image=True)

    command_names = [" ".join(command) for command in runner.commands]
    assert any("k3d cluster create demo" in command for command in command_names), (
        "up must create the missing cluster."
    )
    assert any(
        input_text and "kind: StatefulSet" in input_text
        for input_text in runner.input_texts
    ), "up must apply a local Postgres StatefulSet before Helm installation."
    assert any(
        input_text and "name: postgres" in input_text
        for input_text in runner.input_texts
    ), "up must apply a local Postgres Service matching the preview database URL."
    assert runner.commands[-1][0] == "helm", "Helm must run after dependencies exist."
    banner = capsys.readouterr().out
    assert "Preview URL: http://episodic.localhost:9090" in banner
    assert "Health URL: http://episodic.localhost:9090/health/live" in banner
    assert "Status: make local-k8s-status" in banner
    assert "Logs: make local-k8s-logs" in banner
    assert "Teardown: make local-k8s-down" in banner


def test_up_rejects_existing_cluster_with_conflicting_ingress_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not reuse an existing k3d cluster mapped to a different host port."""
    monkeypatch.setattr(
        "scripts.local_k8s.orchestration.require_tools",
        lambda _: None,
    )
    runner = RecordingRunner([
        subprocess.CompletedProcess(args=["k3d"], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(
            args=["k3d"],
            returncode=0,
            stdout='{"nodes":[{"portMappings":{"80/tcp":[{"HostPort":"8088"}]}}]}',
            stderr="",
        ),
    ])

    with pytest.raises(LocalK8sValidationError, match="ingress port"):
        up(
            PreviewConfig(cluster_name="demo", ingress_port=9090),
            runner,
            skip_image=True,
        )


@pytest.mark.parametrize(
    "command",
    [status, logs],
    ids=["status", "logs"],
)
def test_command_reports_missing_cluster_without_kubectl(
    command: Callable[[PreviewConfig, RecordingRunner], None],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Avoid raw kubectl tracebacks when a command is run before up."""
    monkeypatch.setattr(
        "scripts.local_k8s.orchestration.require_tools",
        lambda _: None,
    )
    runner = RecordingRunner([
        subprocess.CompletedProcess(args=["k3d"], returncode=1, stdout="", stderr=""),
    ])

    command(PreviewConfig(cluster_name="missing"), runner)

    assert runner.commands == [["k3d", "cluster", "get", "missing"]]
    assert "does not exist" in capsys.readouterr().out
