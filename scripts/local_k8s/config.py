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
    """User-adjustable local preview settings.

    Defaults target a local k3d cluster and Docker engine, the ``episodic``
    namespace and Helm release, and the repository's own chart and
    ``values.local.yaml`` overlay. ``openai_base_url`` and ``openai_api_key``
    are read from the ``OPENAI_BASE_URL`` and ``OPENAI_API_KEY`` environment
    variables at construction time (``openai_base_url`` falls back to
    ``https://api.openai.com/v1`` when unset), so setting the key before
    running ``make local-k8s-up`` wires generation without committing a
    credential anywhere.

    The Kubernetes Secret generated for the preview always writes
    ``database-url`` and ``api-bearer-token``. The ``openai-base-url``/
    ``openai-api-key`` pair is written together only when ``openai_api_key``
    is non-empty, since the runtime requires the pair or neither. Secret
    values travel via stdin ``stringData``, never as command arguments.

    Attributes
    ----------
    cluster_name : str
        Name of the local cluster created by the configured provider.
    namespace : str
        Kubernetes namespace the preview release is installed into.
    release_name : str
        Helm release name for the preview deployment.
    image_name : str
        Tag applied to the locally built image before it is loaded into the
        cluster.
    image_archive_path : pathlib.Path
        Filesystem path used to stage the built image archive before it is
        imported into the cluster.
    ingress_port : int
        Host port the preview's ingress is exposed on.
    container_engine : ContainerEngine
        Container engine used to build and load the preview image
        (``"docker"`` or ``"podman"``).
    cluster_provider : ClusterProvider
        Local cluster provider used to create the preview cluster
        (``"k3d"`` or ``"kind"``).
    chart_path : pathlib.Path
        Path to the Helm chart deployed for the preview.
    values_path : pathlib.Path
        Path to the chart values overlay applied on top of the chart
        defaults.
    secret_name : str
        Name of the Kubernetes Secret written for the preview.
    database_url : str
        Connection string for the local-preview-only Postgres container;
        not a production credential.
    api_bearer_token : str
        Bearer token accepted by ``/v1`` requests against the preview; not
        a production credential.
    openai_base_url : str
        OpenAI-compatible base URL for generation requests, read from
        ``OPENAI_BASE_URL`` and falling back to
        ``https://api.openai.com/v1`` when that variable is unset.
    openai_api_key : str
        OpenAI API key for generation requests, read from
        ``OPENAI_API_KEY`` at construction time and defaulting to the
        empty string when that variable is unset.

    Examples
    --------
    With ``OPENAI_API_KEY`` set in the environment, the preview Secret
    gains the paired ``openai-base-url``/``openai-api-key`` keys:

    >>> import os
    >>> os.environ["OPENAI_API_KEY"] = "sk-example"
    >>> config = PreviewConfig()
    >>> bool(config.openai_api_key)
    True

    With ``OPENAI_API_KEY`` absent, the pair is omitted from the Secret:

    >>> os.environ.pop("OPENAI_API_KEY", None)
    >>> config = PreviewConfig()
    >>> config.openai_api_key
    ''
    """

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
    openai_base_url: str = dc.field(
        default_factory=lambda: os.environ.get(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
    )
    # Read at construction so `OPENAI_API_KEY=... make local-k8s-up` wires
    # generation without committing a credential anywhere. repr=False keeps
    # the credential out of the dataclass representation.
    openai_api_key: str = dc.field(
        repr=False,
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""),
    )

    def kube_context(self) -> str:
        """Return the context name the cluster provider creates."""
        if self.cluster_provider == "kind":
            return f"kind-{self.cluster_name}"
        return f"k3d-{self.cluster_name}"
