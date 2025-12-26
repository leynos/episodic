# Infrastructure

This directory defines the OpenTofu layout and GitOps bootstrap assets for the
infrastructure platform. The workflows under `.github/workflows/` consume these
assets for cluster provisioning and GitOps repository bootstrapping.

## Layout

```plaintext
infra/
  clusters/             # Environment root modules (OpenTofu).
  gitops-template/      # Seeded content for the GitOps repository.
  modules/              # Reusable OpenTofu modules.
```

## Conventions

- Each environment uses its own OpenTofu root under `infra/clusters/<env>`.
- Modules support a render mode that emits Flux-ready manifests into the
  GitOps repository structure.
- Secrets are never committed; SOPS + age encrypts GitOps material and Vault
  stores the key material.

## Validation

GitHub Actions workflows are validated locally with act and pytest. Follow
`docs/local-validation-of-github-actions-with-act-and-pytest.md`.
