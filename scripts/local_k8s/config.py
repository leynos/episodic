"""Configuration for the local Kubernetes preview workflow."""

import dataclasses as dc
import pathlib as pl
import tempfile
import typing as typ

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[2]

ContainerEngine = typ.Literal["docker", "podman"]
ClusterProvider = typ.Literal["k3d", "kind"]


@dc.dataclass(frozen=True, slots=True)
class PreviewConfig:
    """User-adjustable local preview settings."""

    cluster_name: str = "episodic-preview"
    namespace: str = "episodic"
    release_name: str = "episodic"
    image_name: str = "localhost/episodic:local"
    image_archive_path: pl.Path = (
        pl.Path(tempfile.gettempdir()) / "episodic-local-image.tar"
    )
    ingress_port: int = 8088
    container_engine: ContainerEngine = "docker"
    cluster_provider: ClusterProvider = "k3d"
    chart_path: pl.Path = REPOSITORY_ROOT / "charts" / "episodic"
    values_path: pl.Path = REPOSITORY_ROOT / "charts" / "episodic" / "values.local.yaml"
    secret_name: str = "episodic-local"  # noqa: S105 - Kubernetes Secret name.
    # Local-preview credentials match the default local Postgres container only.
    # Production deployments must inject real credentials through Kubernetes
    # Secrets or ExternalSecret resources.
    database_url: str = "postgresql+asyncpg://episodic:episodic@postgres:5432/episodic"

    def kube_context(self) -> str:
        """Return the context name the cluster provider creates."""
        if self.cluster_provider == "kind":
            return f"kind-{self.cluster_name}"
        return f"k3d-{self.cluster_name}"
