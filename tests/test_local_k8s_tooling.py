"""Tests for local k3d preview helper contracts."""

import subprocess

import pytest

from scripts.local_k8s import commands
from scripts.local_k8s.config import PreviewConfig
from scripts.local_k8s.orchestration import cluster_exists, down
from scripts.local_k8s.validation import LocalK8sValidationError, require_tools


class RecordingRunner:
    """Test runner that records commands and returns queued results."""

    def __init__(
        self,
        results: list[subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.commands: list[list[str]] = []
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
