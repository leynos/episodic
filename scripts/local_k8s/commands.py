"""Command construction for the local Kubernetes preview workflow."""

import dataclasses as dc
import subprocess
import sys
import typing as typ

from scripts.local_k8s.manifests import (
    local_postgres_manifest as local_postgres_manifest,
)
from scripts.local_k8s.manifests import (
    secret_manifest as secret_manifest,
)

if typ.TYPE_CHECKING:
    from scripts.local_k8s.config import PreviewConfig


class Runner(typ.Protocol):
    """Small command runner interface used by orchestration."""

    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command and return the completed process."""


@dc.dataclass(frozen=True, slots=True)
class CommandRunner:
    """Run shell commands with a narrow, testable interface."""

    dry_run: bool = False

    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command and return the completed process."""
        if self.dry_run:
            print(" ".join(args))
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="",
                stderr="",
            )
        try:
            return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - commands are constructed internally.
                args,
                input=input_text,
                check=check,
                text=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            # Captured output would otherwise vanish into the traceback,
            # leaving the operator with no diagnostic from the failed tool.
            if exc.stdout:
                print(exc.stdout, end="", file=sys.stderr)
            if exc.stderr:
                print(exc.stderr, end="", file=sys.stderr)
            raise


def k3d_cluster_create_command(config: PreviewConfig) -> list[str]:
    """Build the k3d cluster creation command."""
    return [
        "k3d",
        "cluster",
        "create",
        config.cluster_name,
        "--agents",
        "1",
        "--port",
        f"127.0.0.1:{config.ingress_port}:80@loadbalancer",
        "--wait",
    ]


def kind_cluster_config(config: PreviewConfig) -> str:
    """Build the kind cluster config for the local preview."""
    return """\
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
"""


def _kind_command_prefix(config: PreviewConfig) -> list[str]:
    """Return the kind command prefix for the selected container engine."""
    if config.container_engine == "podman":
        return ["env", "KIND_EXPERIMENTAL_PROVIDER=podman", "kind"]
    return ["kind"]


def cluster_create_command(config: PreviewConfig) -> list[str]:
    """Build the cluster creation command for the configured provider."""
    if config.cluster_provider != "kind":
        return k3d_cluster_create_command(config)

    command = [
        *_kind_command_prefix(config),
        "create",
        "cluster",
        "--name",
        config.cluster_name,
        "--config",
        "-",
        "--wait",
        "180s",
    ]
    if config.container_engine != "podman":
        return command
    return [
        "systemd-run",
        "--scope",
        "--user",
        "-p",
        "Delegate=yes",
        *command,
    ]


def cluster_create_input(config: PreviewConfig) -> str | None:
    """Return stdin for cluster creation when the provider needs a config."""
    if config.cluster_provider == "kind":
        return kind_cluster_config(config)
    return None


def k3d_cluster_delete_command(config: PreviewConfig) -> list[str]:
    """Build the k3d cluster deletion command."""
    return ["k3d", "cluster", "delete", config.cluster_name]


def cluster_delete_command(config: PreviewConfig) -> list[str]:
    """Build the cluster deletion command for the configured provider."""
    if config.cluster_provider == "kind":
        return [
            *_kind_command_prefix(config),
            "delete",
            "cluster",
            "--name",
            config.cluster_name,
        ]
    return k3d_cluster_delete_command(config)


def cluster_get_command(config: PreviewConfig) -> list[str]:
    """Build the cluster existence command for the configured provider."""
    if config.cluster_provider == "kind":
        return [*_kind_command_prefix(config), "get", "clusters"]
    return ["k3d", "cluster", "get", config.cluster_name]


def k3d_cluster_get_json_command(config: PreviewConfig) -> list[str]:
    """Build the k3d cluster inspection command with JSON output."""
    return ["k3d", "cluster", "get", config.cluster_name, "-o", "json"]


def cluster_get_json_command(config: PreviewConfig) -> list[str]:
    """Build the provider-specific cluster inspection command."""
    if config.cluster_provider == "kind":
        return [
            config.container_engine,
            "inspect",
            f"{config.cluster_name}-control-plane",
        ]
    return k3d_cluster_get_json_command(config)


def k3d_image_import_command(config: PreviewConfig) -> list[str]:
    """Build the k3d image import command."""
    return [
        "k3d",
        "image",
        "import",
        config.image_name,
        "--cluster",
        config.cluster_name,
    ]


def image_load_command(config: PreviewConfig) -> list[str]:
    """Build the image load/import command for the configured provider."""
    if config.cluster_provider == "kind":
        if config.container_engine == "podman":
            return [
                *_kind_command_prefix(config),
                "load",
                "image-archive",
                str(config.image_archive_path),
                "--name",
                config.cluster_name,
            ]
        return [
            *_kind_command_prefix(config),
            "load",
            "docker-image",
            config.image_name,
            "--name",
            config.cluster_name,
        ]
    return k3d_image_import_command(config)


def image_build_command(config: PreviewConfig) -> list[str]:
    """Build the local container image build command."""
    return [config.container_engine, "build", "--tag", config.image_name, "."]


def image_save_command(config: PreviewConfig) -> list[str] | None:
    """Build the image archive command when the provider needs one."""
    if config.cluster_provider == "kind" and config.container_engine == "podman":
        return [
            config.container_engine,
            "save",
            "--output",
            str(config.image_archive_path),
            config.image_name,
        ]
    return None


docker_build_command = image_build_command


def _kubectl_cmd(config: PreviewConfig) -> list[str]:
    """Return the base kubectl invocation for the preview cluster."""
    return ["kubectl", "--context", config.kube_context()]


def _kubectl_ns_cmd(config: PreviewConfig) -> list[str]:
    """Return a kubectl invocation scoped to the preview namespace."""
    return [
        "kubectl",
        "--context",
        config.kube_context(),
        "--namespace",
        config.namespace,
    ]


def kubectl_namespace_command(config: PreviewConfig) -> list[str]:
    """Build the idempotent namespace creation command."""
    return [
        *_kubectl_cmd(config),
        "create",
        "namespace",
        config.namespace,
        "--dry-run=client",
        "-o",
        "yaml",
    ]


def kubectl_apply_command(config: PreviewConfig) -> list[str]:
    """Build a kubectl apply command for stdin manifests."""
    return [*_kubectl_cmd(config), "apply", "-f", "-"]


def helm_upgrade_command(config: PreviewConfig) -> list[str]:
    """Build the Helm upgrade/install command."""
    return [
        "helm",
        "--kube-context",
        config.kube_context(),
        "upgrade",
        "--install",
        config.release_name,
        str(config.chart_path),
        "--namespace",
        config.namespace,
        "--values",
        str(config.values_path),
        "--wait",
        "--timeout",
        "5m",
    ]


def kubectl_status_command(config: PreviewConfig) -> list[str]:
    """Build the status inspection command."""
    return [
        *_kubectl_ns_cmd(config),
        "get",
        "deploy,svc,ingress,pods",
    ]


def kubectl_logs_command(config: PreviewConfig) -> list[str]:
    """Build the application logs command."""
    return [
        *_kubectl_ns_cmd(config),
        "logs",
        f"deploy/{config.release_name}",
        "--tail",
        "100",
    ]


def kubectl_port_forward_command(config: PreviewConfig) -> list[str]:
    """Build the port-forward command needed for kind's ClusterIP Service."""
    return [
        *_kubectl_ns_cmd(config),
        "port-forward",
        f"svc/{config.release_name}",
        f"{config.ingress_port}:80",
    ]
