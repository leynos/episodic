"""Configuration for the local k3d preview workflow."""

import dataclasses as dc
import pathlib as pl

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[2]


@dc.dataclass(frozen=True, slots=True)
class PreviewConfig:
    """User-adjustable local preview settings."""

    cluster_name: str = "episodic-preview"
    namespace: str = "episodic"
    release_name: str = "episodic"
    image_name: str = "episodic:local"
    ingress_port: int = 8088
    chart_path: pl.Path = REPOSITORY_ROOT / "charts" / "episodic"
    values_path: pl.Path = REPOSITORY_ROOT / "charts" / "episodic" / "values.local.yaml"
    secret_name: str = "episodic-local"  # noqa: S105 - Kubernetes Secret name.
    # Local-preview credentials match the default local Postgres container only.
    # Production deployments must inject real credentials through Kubernetes
    # Secrets or ExternalSecret resources.
    database_url: str = "postgresql+asyncpg://episodic:episodic@postgres:5432/episodic"

    def kube_context(self) -> str:
        """Return the context name k3d creates for this cluster."""
        return f"k3d-{self.cluster_name}"
