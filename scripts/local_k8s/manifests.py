"""Rendering and validation for local Kubernetes manifests."""

import json
import re
import typing as typ
import urllib.parse as urlparse

if typ.TYPE_CHECKING:
    from scripts.local_k8s.config import PreviewConfig


def secret_manifest(config: PreviewConfig) -> str:
    """Build the application Secret manifest for one stdin apply.

    The manifest carries the credentials in ``stringData`` so secret
    values never appear in command arguments, which the runner prints in
    dry-run mode and which failed commands may echo to stderr.

    Parameters
    ----------
    config : PreviewConfig
        Preview configuration used to populate the Secret.

    Returns
    -------
    str
        Secret manifest YAML for ``kubectl apply -f -`` on stdin.

    Raises
    ------
    ValueError
        If ``config.secret_name`` or ``config.namespace`` is not a valid
        DNS-1123 label.
    """
    secret_name = config.secret_name
    namespace = config.namespace
    for field_name, value in (
        ("secret_name", secret_name),
        ("namespace", namespace),
    ):
        if _DNS1123_LABEL.fullmatch(value) is None:
            msg = (
                f"{field_name} must be a DNS-1123 label "
                f"(lowercase alphanumerics and hyphens); got {value!r}"
            )
            raise ValueError(msg)

    lines = [
        "apiVersion: v1",
        "kind: Secret",
        "metadata:",
        f"  name: {secret_name}",
        f"  namespace: {namespace}",
        "type: Opaque",
        "stringData:",
        f"  database-url: {_yaml_string(config.database_url)}",
        f"  api-bearer-token: {_yaml_string(config.api_bearer_token)}",
    ]
    if config.openai_api_key:
        # The runtime requires the base URL and key together, so the
        # preview secret only ever writes the pair.
        lines.extend([
            f"  openai-base-url: {_yaml_string(config.openai_base_url)}",
            f"  openai-api-key: {_yaml_string(config.openai_api_key)}",
        ])
    return "\n".join(lines) + "\n"


_DNS1123_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")


def _yaml_string(value: str) -> str:
    """Quote a scalar for the local manifest, escaping control characters."""
    return json.dumps(value)


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
