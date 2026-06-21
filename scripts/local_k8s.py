#!/usr/bin/env python3
"""Cyclopts CLI for the local Episodic Kubernetes preview."""

import dataclasses
import typing as typ

import cyclopts

from scripts.local_k8s.commands import CommandRunner
from scripts.local_k8s.config import ClusterProvider, ContainerEngine, PreviewConfig
from scripts.local_k8s.orchestration import down as preview_down
from scripts.local_k8s.orchestration import logs as preview_logs
from scripts.local_k8s.orchestration import status as preview_status
from scripts.local_k8s.orchestration import up as preview_up

app = cyclopts.App(help="Manage the local Episodic Kubernetes preview.")


@dataclasses.dataclass
class ClusterOpts:
    """Shared cluster-targeting options for every preview command."""

    cluster: str = "episodic-preview"
    namespace: str = "episodic"
    ingress_port: int = 8088
    engine: ContainerEngine = "docker"
    provider: ClusterProvider = "k3d"


def _config(opts: ClusterOpts) -> PreviewConfig:
    """Build preview configuration from common CLI flags."""
    return PreviewConfig(
        cluster_name=opts.cluster,
        namespace=opts.namespace,
        ingress_port=opts.ingress_port,
        container_engine=opts.engine,
        cluster_provider=opts.provider,
    )


@app.command
def up(
    opts: typ.Annotated[ClusterOpts, cyclopts.Parameter(name="")],
    skip_image: bool = False,
    dry_run: bool = False,
) -> None:
    """Create or update the local preview."""
    preview_up(
        _config(opts),
        CommandRunner(dry_run=dry_run),
        skip_image=skip_image,
    )


@app.command
def down(
    opts: typ.Annotated[ClusterOpts, cyclopts.Parameter(name="")],
    dry_run: bool = False,
) -> None:
    """Delete the local preview cluster."""
    preview_down(
        _config(opts),
        CommandRunner(dry_run=dry_run),
    )


@app.command
def status(
    opts: typ.Annotated[ClusterOpts, cyclopts.Parameter(name="")],
    dry_run: bool = False,
) -> None:
    """Inspect preview Kubernetes resources."""
    preview_status(
        _config(opts),
        CommandRunner(dry_run=dry_run),
    )


@app.command
def logs(
    opts: typ.Annotated[ClusterOpts, cyclopts.Parameter(name="")],
    dry_run: bool = False,
) -> None:
    """Show recent application logs."""
    preview_logs(
        _config(opts),
        CommandRunner(dry_run=dry_run),
    )


if __name__ == "__main__":
    app()
