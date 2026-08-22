"""Configuration for the local Kubernetes preview workflow."""

import dataclasses as dc
import os
import pathlib as pl
import tempfile
import typing as typ

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[2]

type ContainerEngine = typ.Literal["docker", "podman"]
type ClusterProvider = typ.Literal["k3d", "kind"]


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
    # Local-preview bearer token for /v1 requests; not a production credential.
    api_bearer_token: str = "local-dev-token"  # noqa: S105 - local-only token.
    openai_base_url: str = "https://api.openai.com/v1"
    # Read at construction so `OPENAI_API_KEY=... make local-k8s-up` wires
    # generation without committing a credential anywhere.
    openai_api_key: str = dc.field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
    )

    def kube_context(self) -> str:
        """Return the context name the cluster provider creates."""
        if self.cluster_provider == "kind":
            return f"kind-{self.cluster_name}"
        return f"k3d-{self.cluster_name}"
