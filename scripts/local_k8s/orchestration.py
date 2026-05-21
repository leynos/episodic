"""High-level local k3d preview orchestration."""

import typing as typ

from scripts.local_k8s import commands
from scripts.local_k8s.validation import ensure_loopback_port_available, require_tools

if typ.TYPE_CHECKING:
    from scripts.local_k8s.config import PreviewConfig

REQUIRED_TOOLS = ["docker", "helm", "k3d", "kubectl"]


def cluster_exists(config: PreviewConfig, runner: commands.Runner) -> bool:
    """Return whether the configured k3d cluster exists."""
    result = runner.run(
        ["k3d", "cluster", "get", config.cluster_name],
        check=False,
    )
    return result.returncode == 0


def up(
    config: PreviewConfig,
    runner: commands.Runner,
    *,
    skip_image: bool = False,
) -> None:
    """Create or update the local preview environment."""
    require_tools(REQUIRED_TOOLS)
    if not cluster_exists(config, runner):
        ensure_loopback_port_available(config.ingress_port)
        runner.run(commands.k3d_cluster_create_command(config))

    if not skip_image:
        runner.run(commands.docker_build_command(config))
        runner.run(commands.k3d_image_import_command(config))

    namespace = runner.run(commands.kubectl_namespace_command(config))
    if namespace.stdout:
        runner.run(
            commands.kubectl_apply_command(config),
            check=True,
            input_text=namespace.stdout,
        )

    secret = runner.run(commands.kubectl_secret_command(config))
    runner.run(
        commands.kubectl_apply_command(config),
        check=True,
        input_text=secret.stdout,
    )
    runner.run(commands.helm_upgrade_command(config))
    print(
        "Episodic preview is available at "
        f"http://episodic.localhost:{config.ingress_port}"
    )


def down(config: PreviewConfig, runner: commands.Runner) -> None:
    """Delete the local preview cluster when it exists."""
    if cluster_exists(config, runner):
        runner.run(commands.k3d_cluster_delete_command(config))
    else:
        print(f"k3d cluster {config.cluster_name!r} does not exist.")


def status(config: PreviewConfig, runner: commands.Runner) -> None:
    """Print Kubernetes resource status for the preview."""
    require_tools(["kubectl"])
    result = runner.run(commands.kubectl_status_command(config))
    print(result.stdout, end="")


def logs(config: PreviewConfig, runner: commands.Runner) -> None:
    """Print recent application logs for the preview."""
    require_tools(["kubectl"])
    result = runner.run(commands.kubectl_logs_command(config))
    print(result.stdout, end="")
