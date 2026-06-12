"""Command construction for the local k3d preview workflow."""

import dataclasses as dc
import subprocess
import typing as typ
import urllib.parse as urlparse

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


def k3d_cluster_get_json_command(config: PreviewConfig) -> list[str]:
    """Build the k3d cluster inspection command with JSON output."""
    return ["k3d", "cluster", "get", config.cluster_name, "-o", "json"]


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


def _yaml_string(value: str) -> str:
    """Quote a simple scalar for the local manifest."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def local_postgres_manifest(config: PreviewConfig) -> str:
    """Build the local-only Postgres dependency manifest."""
    database_url = urlparse.urlsplit(config.database_url)
    database_name = database_url.path.lstrip("/") or "episodic"
    username = urlparse.unquote(database_url.username or "episodic")
    credential = urlparse.unquote(database_url.password or "episodic")
    service_name = database_url.hostname or "postgres"
    port = database_url.port or 5432
    # The local preview uses literal credentials so the dependency can be
    # created with one stdin apply. Shared previews must use ExternalSecret.
    return f"""\
apiVersion: v1
kind: Service
metadata:
  name: {service_name}
  namespace: {config.namespace}
  labels:
    app.kubernetes.io/name: {service_name}
    app.kubernetes.io/part-of: episodic-preview
spec:
  ports:
    - name: postgres
      port: {port}
      targetPort: postgres
  selector:
    app.kubernetes.io/name: {service_name}
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {service_name}
  namespace: {config.namespace}
  labels:
    app.kubernetes.io/name: {service_name}
    app.kubernetes.io/part-of: episodic-preview
spec:
  serviceName: {service_name}
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: {service_name}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: {service_name}
        app.kubernetes.io/part-of: episodic-preview
    spec:
      containers:
        - name: postgres
          image: postgres:16-alpine
          ports:
            - name: postgres
              containerPort: 5432
          env:
            - name: POSTGRES_DB
              value: {_yaml_string(database_name)}
            - name: POSTGRES_USER
              value: {_yaml_string(username)}
            - name: POSTGRES_PASSWORD
              value: {_yaml_string(credential)}
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
          readinessProbe:
            exec:
              command:
                - pg_isready
                - -U
                - {_yaml_string(username)}
                - -d
                - {_yaml_string(database_name)}
            initialDelaySeconds: 5
            periodSeconds: 5
            timeoutSeconds: 3
          volumeMounts:
            - name: postgres-data
              mountPath: /var/lib/postgresql/data
      volumes:
        - name: postgres-data
          emptyDir: {{}}
"""


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
