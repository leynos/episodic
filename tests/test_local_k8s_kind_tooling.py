"""Tests for local kind preview helper contracts."""

import subprocess
import tempfile
from pathlib import Path

import pytest

from scripts.local_k8s import commands
from scripts.local_k8s.config import PreviewConfig
from scripts.local_k8s.orchestration import cluster_exists, down, up
from scripts.local_k8s.validation import LocalK8sValidationError


class RecordingRunner:
    """Test runner that records commands and returns queued results."""

    def __init__(
        self,
        results: list[subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        """Create a recording runner with optional pre-seeded results.

        Parameters
        ----------
        results
            Completed process results returned in order before the runner falls
            back to a default successful result.

        Returns
        -------
        None
            Initialisation records command and input history containers.
        """
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
        """Record a command and return the next queued process result.

        Parameters
        ----------
        args
            Command arguments submitted by the orchestration layer.
        check
            Whether the caller expected a checked command. The recording runner
            records this contract but does not raise on non-zero results.
        input_text
            Optional stdin text supplied to the command.

        Returns
        -------
        subprocess.CompletedProcess[str]
            The next pre-seeded result, or a default successful result echoing
            ``input_text`` as stdout when no pre-seeded results remain.
        """
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


def test_kind_cluster_create_command_uses_rootless_podman_scope() -> None:
    """Build the kind command validated for rootless Podman previews."""
    config = PreviewConfig(
        cluster_name="demo",
        ingress_port=9090,
        container_engine="podman",
        cluster_provider="kind",
    )

    command = commands.cluster_create_command(config)

    assert command == [
        "systemd-run",
        "--scope",
        "--user",
        "-p",
        "Delegate=yes",
        "env",
        "KIND_EXPERIMENTAL_PROVIDER=podman",
        "kind",
        "create",
        "cluster",
        "--name",
        "demo",
        "--config",
        "-",
        "--wait",
        "180s",
    ]
    cluster_config = commands.cluster_create_input(config)

    assert cluster_config is not None
    assert "kind: Cluster" in cluster_config
    assert "extraPortMappings" not in cluster_config, (
        "kind previews must use kubectl port-forward rather than host-port "
        "mappings that would occupy the operator-facing preview port."
    )


def test_podman_build_save_and_kind_image_load_commands() -> None:
    """Use Podman archives to bridge the local image into kind."""
    image_archive_path = Path(tempfile.gettempdir()) / "demo-image.tar"
    config = PreviewConfig(
        cluster_name="demo",
        image_name="episodic:local",
        container_engine="podman",
        cluster_provider="kind",
        image_archive_path=image_archive_path,
    )

    assert commands.image_build_command(config) == [
        "podman",
        "build",
        "--tag",
        "episodic:local",
        ".",
    ]
    assert commands.image_save_command(config) == [
        "podman",
        "save",
        "--output",
        str(image_archive_path),
        "episodic:local",
    ]
    assert commands.image_load_command(config) == [
        "env",
        "KIND_EXPERIMENTAL_PROVIDER=podman",
        "kind",
        "load",
        "image-archive",
        str(image_archive_path),
        "--name",
        "demo",
    ]


def test_kind_helm_upgrade_command_uses_kind_context() -> None:
    """Use the kind-created kube context for Helm and kubectl commands."""
    config = PreviewConfig(cluster_name="demo", cluster_provider="kind")

    assert config.kube_context() == "kind-demo"
    assert commands.helm_upgrade_command(config)[:3] == [
        "helm",
        "--kube-context",
        "kind-demo",
    ]


def test_kind_cluster_exists_checks_cluster_names() -> None:
    """Treat kind's cluster list as the source of truth for existence."""
    runner = RecordingRunner([
        subprocess.CompletedProcess(
            args=["kind"],
            returncode=0,
            stdout="other\ndemo\n",
            stderr="",
        )
    ])

    assert cluster_exists(
        PreviewConfig(cluster_name="demo", cluster_provider="kind"),
        runner,
    ), "kind cluster list containing the name must count as existing."


def test_kind_down_is_idempotent_when_cluster_is_absent() -> None:
    """Do not attempt deletion when kind reports the cluster is missing."""
    runner = RecordingRunner([
        subprocess.CompletedProcess(
            args=["kind"],
            returncode=0,
            stdout="other\n",
            stderr="",
        )
    ])
    config = PreviewConfig(cluster_name="missing", cluster_provider="kind")

    down(config, runner)

    assert runner.commands == [["kind", "get", "clusters"]], (
        "down must be idempotent: only check existence, not attempt deletion "
        "when the kind cluster is absent."
    )


def test_kind_up_uses_podman_and_bootstraps_postgres(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Drive the validated rootless Podman + kind preview path."""
    monkeypatch.setattr(
        "scripts.local_k8s.orchestration.require_tools",
        lambda _: None,
    )
    monkeypatch.setattr(
        "scripts.local_k8s.orchestration.ensure_loopback_port_available",
        lambda _: None,
    )
    runner = RecordingRunner([
        subprocess.CompletedProcess(args=["kind"], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(args=["kind"], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(
            args=["podman"], returncode=0, stdout="", stderr=""
        ),
        subprocess.CompletedProcess(
            args=["podman"], returncode=0, stdout="", stderr=""
        ),
        subprocess.CompletedProcess(args=["kind"], returncode=0, stdout="", stderr=""),
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
    config = PreviewConfig(
        cluster_name="demo",
        ingress_port=9090,
        container_engine="podman",
        cluster_provider="kind",
        image_archive_path=tmp_path / "episodic-local.tar",
    )
    config.image_archive_path.write_text("stale archive", encoding="utf-8")

    up(config, runner)

    assert runner.commands[0] == [
        "env",
        "KIND_EXPERIMENTAL_PROVIDER=podman",
        "kind",
        "get",
        "clusters",
    ]
    assert runner.commands[1][0:5] == [
        "systemd-run",
        "--scope",
        "--user",
        "-p",
        "Delegate=yes",
    ]
    assert "KIND_EXPERIMENTAL_PROVIDER=podman" in runner.commands[1]
    assert runner.input_texts[1] is not None
    assert "kind: Cluster" in runner.input_texts[1]
    assert runner.commands[2][0] == "podman"
    assert runner.commands[3][0:3] == [
        "podman",
        "save",
        "--output",
    ]
    assert runner.commands[4][0:4] == [
        "env",
        "KIND_EXPERIMENTAL_PROVIDER=podman",
        "kind",
        "load",
    ]
    assert any(
        input_text and "kind: StatefulSet" in input_text
        for input_text in runner.input_texts
    ), "kind up must apply the local Postgres dependency."
    assert runner.commands[-1][0:3] == ["helm", "--kube-context", "kind-demo"]
    banner = capsys.readouterr().out
    assert "Preview URL: http://127.0.0.1:9090" in banner
    assert "Port forward:" in banner
    assert not config.image_archive_path.exists(), (
        "stale temporary image archives must be removed before Podman saves a "
        "fresh archive."
    )


def test_kind_up_rejects_existing_cluster_with_host_port_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject kind clusters created with the old host-port mapping model."""
    monkeypatch.setattr(
        "scripts.local_k8s.orchestration.require_tools",
        lambda _: None,
    )
    runner = RecordingRunner([
        subprocess.CompletedProcess(
            args=["kind"],
            returncode=0,
            stdout="demo\n",
            stderr="",
        ),
        subprocess.CompletedProcess(
            args=["podman"],
            returncode=0,
            stdout='[{"HostConfig":{"PortBindings":{"30080/tcp":[{"HostPort":"8088"}]}}}]',
            stderr="",
        ),
    ])

    with pytest.raises(LocalK8sValidationError, match="port-forward"):
        up(
            PreviewConfig(
                cluster_name="demo",
                container_engine="podman",
                cluster_provider="kind",
            ),
            runner,
            skip_image=True,
        )
