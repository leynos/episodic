"""High-level local Kubernetes preview orchestration."""

import json
import typing as typ

from scripts.local_k8s import commands
from scripts.local_k8s.validation import (
    LocalK8sValidationError,
    ensure_loopback_port_available,
    require_tools,
)

if typ.TYPE_CHECKING:
    import subprocess

    from scripts.local_k8s.config import PreviewConfig


def _required_tools(config: PreviewConfig, *, include_image: bool = True) -> list[str]:
    """Return the CLI tools needed for the selected local preview mode."""
    tools = ["helm", "kubectl", config.cluster_provider]
    if include_image or config.cluster_provider == "kind":
        tools.append(config.container_engine)
    if config.cluster_provider == "kind" and config.container_engine == "podman":
        tools.append("systemd-run")
    return sorted(set(tools))


def cluster_exists(config: PreviewConfig, runner: commands.Runner) -> bool:
    """Return whether the configured local preview cluster exists."""
    result = runner.run(
        commands.cluster_get_command(config),
        check=False,
    )
    if config.cluster_provider == "kind":
        return config.cluster_name in result.stdout.splitlines()
    return result.returncode == 0


def _collect_host_ports(value: object) -> set[int]:
    """Return host ports from k3d JSON without depending on one exact schema."""
    if isinstance(value, dict):
        ports: set[int] = set()
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in {"hostport", "host_port"}:
                try:
                    ports.add(int(typ.cast("str | int", item)))
                except TypeError:
                    pass
                except ValueError:
                    pass
            ports.update(_collect_host_ports(item))
        return ports
    if isinstance(value, list):
        ports: set[int] = set()
        for item in value:
            ports.update(_collect_host_ports(item))
        return ports
    return set()


def _ensure_existing_cluster_ingress_port(
    config: PreviewConfig,
    runner: commands.Runner,
) -> None:
    """Fail clearly when an existing cluster uses a different ingress port."""
    result = runner.run(commands.cluster_get_json_command(config))
    try:
        cluster_data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        msg = (
            f"Could not inspect {config.cluster_provider} cluster "
            f"{config.cluster_name!r} as JSON."
        )
        raise LocalK8sValidationError(msg) from exc

    host_ports = _collect_host_ports(cluster_data)
    if config.cluster_provider == "kind":
        if config.ingress_port in host_ports:
            msg = (
                f"kind cluster {config.cluster_name!r} maps host port "
                f"{config.ingress_port}; delete and recreate it so the preview "
                "can use kubectl port-forward on that port."
            )
            raise LocalK8sValidationError(msg)
        ensure_loopback_port_available(config.ingress_port)
        return

    if config.ingress_port in host_ports:
        return

    if host_ports:
        msg = (
            f"{config.cluster_provider} cluster {config.cluster_name!r} exists, "
            f"but its ingress port mapping is {sorted(host_ports)!r}, "
            f"not {config.ingress_port}."
        )
    else:
        msg = (
            f"{config.cluster_provider} cluster {config.cluster_name!r} exists, "
            "but no ingress port mapping could be found."
        )
    raise LocalK8sValidationError(msg)


def _print_success_banner(config: PreviewConfig) -> None:
    """Print the operator commands needed after a successful preview install."""
    if config.cluster_provider == "kind":
        preview_url = f"http://127.0.0.1:{config.ingress_port}"
        lines = [
            "Episodic preview is ready.",
            f"Preview URL: {preview_url}",
            f"Health URL: {preview_url}/health/live",
            "Port forward: " + " ".join(commands.kubectl_port_forward_command(config)),
            "Status: make local-k8s-status",
            "Logs: make local-k8s-logs",
            "Teardown: make local-k8s-down",
        ]
    else:
        preview_url = f"http://episodic.localhost:{config.ingress_port}"
        lines = [
            "Episodic preview is ready.",
            f"Preview URL: {preview_url}",
            f"Health URL: {preview_url}/health/live",
            "Status: make local-k8s-status",
            "Logs: make local-k8s-logs",
            "Teardown: make local-k8s-down",
        ]
    print("\n".join(lines))


def _print_missing_cluster(config: PreviewConfig) -> None:
    """Tell the operator the preview has not been created yet."""
    print(f"{config.cluster_provider} cluster {config.cluster_name!r} does not exist.")


def _print_command_result_or_error(
    result: subprocess.CompletedProcess[str],
) -> None:
    """Print captured command output without exposing a Python traceback."""
    output = result.stdout if result.returncode == 0 else result.stderr
    if output:
        print(output, end="")


def up(
    config: PreviewConfig,
    runner: commands.Runner,
    *,
    skip_image: bool = False,
) -> None:
    """Create or update the local preview environment."""
    require_tools(_required_tools(config, include_image=not skip_image))
    if cluster_exists(config, runner):
        _ensure_existing_cluster_ingress_port(config, runner)
    else:
        ensure_loopback_port_available(config.ingress_port)
        runner.run(
            commands.cluster_create_command(config),
            input_text=commands.cluster_create_input(config),
        )

    if not skip_image:
        runner.run(commands.image_build_command(config))
        image_save = commands.image_save_command(config)
        if image_save is not None:
            if not getattr(runner, "dry_run", False):
                config.image_archive_path.unlink(missing_ok=True)
            runner.run(image_save)
        runner.run(commands.image_load_command(config))

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
    runner.run(
        commands.kubectl_apply_command(config),
        check=True,
        input_text=commands.local_postgres_manifest(config),
    )
    runner.run(commands.helm_upgrade_command(config))
    _print_success_banner(config)


def down(config: PreviewConfig, runner: commands.Runner) -> None:
    """Delete the local preview cluster when it exists."""
    if cluster_exists(config, runner):
        runner.run(commands.cluster_delete_command(config))
    else:
        _print_missing_cluster(config)


def status(config: PreviewConfig, runner: commands.Runner) -> None:
    """Print Kubernetes resource status for the preview."""
    require_tools(_required_tools(config, include_image=False))
    if not cluster_exists(config, runner):
        _print_missing_cluster(config)
        return
    result = runner.run(commands.kubectl_status_command(config), check=False)
    _print_command_result_or_error(result)


def logs(config: PreviewConfig, runner: commands.Runner) -> None:
    """Print recent application logs for the preview."""
    require_tools(_required_tools(config, include_image=False))
    if not cluster_exists(config, runner):
        _print_missing_cluster(config)
        return
    result = runner.run(commands.kubectl_logs_command(config), check=False)
    _print_command_result_or_error(result)
