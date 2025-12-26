# OpenTofu modules

This directory hosts the reusable OpenTofu modules consumed by the environment
roots in `infra/clusters/`.

| Module               | Purpose                                                     |
| -------------------- | ----------------------------------------------------------- |
| `cert_manager/`      | Install cert-manager and Let's Encrypt issuers.             |
| `cloudnative_pg/`    | Install the CloudNativePG operator and cluster manifests.   |
| `doks/`              | Provision DOKS clusters and node pools.                     |
| `fluxcd/`            | Install Flux controllers and bootstrap GitOps sources.      |
| `observability/`     | Deploy OpenTelemetry Collector, Prometheus, and OpenSearch. |
| `rabbitmq_operator/` | Install the RabbitMQ Kubernetes Operator and clusters.      |
| `traefik/`           | Install the Traefik ingress controller.                     |
| `valkey_operator/`   | Install the Valkey operator for Redis-compatible caching.   |
| `vault_eso/`         | Configure External Secrets Operator to read from Vault.     |
