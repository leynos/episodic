# Local k3d preview and Nile Valley integration design

This document records how Episodic integrates with Nile Valley preview and
GitOps workflows.

## Scope

The integration provides four deployable surfaces:

- a Falcon ASGI health surface served through the Granian runtime entrypoint;
- a production container image that runs as a non-root user;
- a Helm chart under `charts/episodic`; and
- local `k3d` preview orchestration under `scripts/local_k8s.py`.

The design follows the existing hexagonal boundary. Health semantics live in
`episodic.canonical.health`; the Falcon adapter maps those observations to the
HTTP JSON contract and status codes. Container, Helm, and local Kubernetes
files remain deployment adapters and do not introduce domain dependencies on
infrastructure.

## Runtime contract

The production HTTP process is:

```shell
granian episodic.api.runtime:create_app_from_env --interface asgi --factory --host 0.0.0.0 --port 8080
```

The runtime requires `DATABASE_URL`. The `/health/live` endpoint reports that
the process has booted, while `/health/ready` reports infrastructure readiness.
The current readiness observer checks database connectivity and returns
`503 Service Unavailable` when the check fails.

## Container image

The Dockerfile builds an Episodic wheel in a builder stage and installs it into
a slim runtime stage. The runtime stage:

- exposes port `8080`;
- runs Granian with the factory target above;
- creates and uses a non-root `episodic` user; and
- declares a `HEALTHCHECK` against `http://127.0.0.1:8080/health/live`.

Docker smoke tests are opt-in because agent environments may not expose a
Docker daemon. Set `EPISODIC_RUN_DOCKER_TESTS=1` when validating a live image
locally.

## Helm chart

`charts/episodic` is the application chart consumed by Nile Valley preview and
GitOps workflows. The chart renders Deployment, Service, ConfigMap, optional
Ingress, optional ExternalSecret, optional PodDisruptionBudget, and
ServiceAccount resources.

Values follow the Nile Valley example chart conventions:

- `config` holds non-secret environment variables;
- `existingSecretName` reuses an operator-managed Kubernetes Secret;
- `secretEnvFromKeys` maps environment variable names to Secret keys;
- `allowMissingSecret` is the fallback optional flag for Secret keys;
- `externalSecret` renders External Secrets Operator resources; and
- `container.livenessProbe` and `container.readinessProbe` default to the
  Episodic health endpoints.

`secretEnvFromKeys` uses object entries. This preserves explicit
`optional: false` values even when `allowMissingSecret` is `true`.

## Local preview

The local preview command surface is:

```shell
make local-k8s-up
make local-k8s-status
make local-k8s-logs
make local-k8s-down
```

The Make targets call `uv run --group dev scripts/local_k8s.py`. The CLI uses
Cyclopts and delegates to small helper modules for configuration, validation,
command construction, and orchestration.

`local-k8s-up` validates the required tools, creates or reuses the configured
`k3d` cluster, builds and imports the local image unless skipped, creates the
application namespace and Secret, installs the chart with
`charts/episodic/values.local.yaml`, and waits for Helm readiness.

The default preview values are intentionally local-only:

- cluster: `episodic-preview`;
- namespace: `episodic`;
- image: `episodic:local`;
- ingress host: `episodic.localhost`;
- ingress port: `8088`; and
- Secret name: `episodic-local`.

The default database URL contains local development credentials that match the
expected local Postgres container. Production and shared preview environments
must inject real credentials through Kubernetes Secrets or ExternalSecret
resources.

## Validation

Chart output is validated by `tests/test_helm_chart_contract.py` using Helm
linting, Helm template rendering, and a syrupy snapshot for the local manifest.
Local preview helper behaviour is validated by
`tests/test_local_k8s_tooling.py`, which covers command construction,
prerequisite validation, and idempotent missing-cluster handling without
requiring a live Kubernetes cluster.

Full milestone validation uses:

```shell
make check-fmt
make typecheck
make lint
make markdownlint
make nixie
make test
```
