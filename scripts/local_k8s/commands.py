"""Command construction for the local k3d preview workflow."""

import dataclasses as dc
import subprocess
import typing as typ

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
        return subprocess.run(  # noqa: S603 - commands are constructed internally.
            args,
            input=input_text,
            check=check,
            text=True,
            capture_output=True,
        )


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


def k3d_cluster_delete_command(config: PreviewConfig) -> list[str]:
    """Build the k3d cluster deletion command."""
    return ["k3d", "cluster", "delete", config.cluster_name]


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


def docker_build_command(config: PreviewConfig) -> list[str]:
    """Build the local Docker image build command."""
    return ["docker", "build", "--tag", config.image_name, "."]


def kubectl_namespace_command(config: PreviewConfig) -> list[str]:
    """Build the idempotent namespace creation command."""
    return [
        "kubectl",
        "--context",
        config.kube_context(),
        "create",
        "namespace",
        config.namespace,
        "--dry-run=client",
        "-o",
        "yaml",
    ]


def kubectl_apply_command(config: PreviewConfig) -> list[str]:
    """Build a kubectl apply command for stdin manifests."""
    return ["kubectl", "--context", config.kube_context(), "apply", "-f", "-"]


def kubectl_secret_command(config: PreviewConfig) -> list[str]:
    """Build the idempotent application Secret creation command."""
    return [
        "kubectl",
        "--context",
        config.kube_context(),
        "--namespace",
        config.namespace,
        "create",
        "secret",
        "generic",
        config.secret_name,
        f"--from-literal=database-url={config.database_url}",
        "--dry-run=client",
        "-o",
        "yaml",
    ]


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
        "kubectl",
        "--context",
        config.kube_context(),
        "--namespace",
        config.namespace,
        "get",
        "deploy,svc,ingress,pods",
    ]


def kubectl_logs_command(config: PreviewConfig) -> list[str]:
    """Build the application logs command."""
    return [
        "kubectl",
        "--context",
        config.kube_context(),
        "--namespace",
        config.namespace,
        "logs",
        f"deploy/{config.release_name}",
        "--tail",
        "100",
    ]
