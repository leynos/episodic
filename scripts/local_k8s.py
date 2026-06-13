#!/usr/bin/env python3
"""Cyclopts CLI for the local Episodic Kubernetes preview."""

import cyclopts

from scripts.local_k8s.commands import CommandRunner
from scripts.local_k8s.config import ClusterProvider, ContainerEngine, PreviewConfig
from scripts.local_k8s.orchestration import down as preview_down
from scripts.local_k8s.orchestration import logs as preview_logs
from scripts.local_k8s.orchestration import status as preview_status
from scripts.local_k8s.orchestration import up as preview_up

app = cyclopts.App(help="Manage the local Episodic Kubernetes preview.")


def _config(
    cluster: str,
    namespace: str,
    ingress_port: int,
    engine: ContainerEngine,
    provider: ClusterProvider,
) -> PreviewConfig:
    """Build preview configuration from common CLI flags."""
    return PreviewConfig(
        cluster_name=cluster,
        namespace=namespace,
        ingress_port=ingress_port,
        container_engine=engine,
        cluster_provider=provider,
    )


@app.command
def up(
    cluster: str = "episodic-preview",
    namespace: str = "episodic",
    ingress_port: int = 8088,
    engine: ContainerEngine = "docker",
    provider: ClusterProvider = "k3d",
    skip_image: bool = False,
    dry_run: bool = False,
) -> None:
    """Create or update the local preview."""
    preview_up(
        _config(cluster, namespace, ingress_port, engine, provider),
        CommandRunner(dry_run=dry_run),
        skip_image=skip_image,
    )


@app.command
def down(
    cluster: str = "episodic-preview",
    namespace: str = "episodic",
    ingress_port: int = 8088,
    engine: ContainerEngine = "docker",
    provider: ClusterProvider = "k3d",
    dry_run: bool = False,
) -> None:
    """Delete the local preview cluster."""
    preview_down(
        _config(cluster, namespace, ingress_port, engine, provider),
        CommandRunner(dry_run=dry_run),
    )


@app.command
def status(
    cluster: str = "episodic-preview",
    namespace: str = "episodic",
    ingress_port: int = 8088,
    engine: ContainerEngine = "docker",
    provider: ClusterProvider = "k3d",
    dry_run: bool = False,
) -> None:
    """Inspect preview Kubernetes resources."""
    preview_status(
        _config(cluster, namespace, ingress_port, engine, provider),
        CommandRunner(dry_run=dry_run),
    )


@app.command
def logs(
    cluster: str = "episodic-preview",
    namespace: str = "episodic",
    ingress_port: int = 8088,
    engine: ContainerEngine = "docker",
    provider: ClusterProvider = "k3d",
    dry_run: bool = False,
) -> None:
    """Show recent application logs."""
    preview_logs(
        _config(cluster, namespace, ingress_port, engine, provider),
        CommandRunner(dry_run=dry_run),
    )


if __name__ == "__main__":
    app()
