# Episodic Helm chart

This chart deploys the Episodic HTTP service for Nile Valley preview and
GitOps workflows.

The chart supports non-secret environment variables through `config`, existing
Kubernetes Secrets through `existingSecretName`, and External Secrets Operator
resources through `externalSecret`.

`secretEnvFromKeys` maps environment variable names to keys inside the
resolved Secret. Each entry uses the object form:

```yaml
secretEnvFromKeys:
  DATABASE_URL:
    key: database-url
    optional: false
```

When `optional` is omitted, the chart falls back to `allowMissingSecret`.

`externalSecret.creationPolicy` defaults to `Owner`. With this setting, the
target Secret rendered by `templates/externalsecret.yaml` through
`include "episodic.secretName" .` is owned by the ExternalSecret and is
deleted when that ExternalSecret is removed. Use `Merge` or `None` when the
Secret lifecycle should be managed outside this release.
