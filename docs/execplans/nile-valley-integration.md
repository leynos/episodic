# Integrate Episodic with Nile Valley previews

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`,
and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: COMPLETE for the rootless Podman and kind live-preview follow-up. The
user explicitly approved implementation on 2026-05-21. A 2026-06-12 review
found Docker and local `k3d` live-path gaps; the first follow-up pass addressed
those findings with tests, implementation, documentation, validation, and
CodeRabbit review. A 2026-06-13 live validation pass found that this host can
run the preview with rootless Podman and kind, not `k3d`; the local Kubernetes
tooling now drives that validated path while preserving the Docker plus `k3d`
defaults.

## Purpose and big picture

This work makes Episodic deployable through the Nile Valley preview and GitOps
workflow. After implementation, an operator can build a production-style
container image, install Episodic through a Helm chart, and bring up a local
Kubernetes preview environment with one Makefile command. The default local
path remains Docker plus `k3d`; rootless Podman hosts can use kind as a
provider. Kubernetes liveness and readiness probes can observe the service
through stable HTTP endpoints, and the local preview path exercises the same
chart shape expected by Nile Valley.

Success is observable when `make local-k8s-up` creates or reuses a local
cluster, deploys the Episodic chart, and prints a preview URL whose
`/health/live` endpoint returns HTTP `200`. The chart can be rendered with Nile
Valley-compatible values, the container runs as a non-root user, and the
repository quality gates pass.

## Constraints

- Implementation is approved as of 2026-05-21. Continue milestone by
  milestone, and stop only when a tolerance threshold is reached or a
  constraint would be violated.
- Preserve the hexagonal architecture invariants from the
  `hexagonal-architecture` skill. Domain modules must not import Falcon,
  Granian, Docker, Helm, Kubernetes, `k3d`, or other infrastructure concerns.
- Use the `leta` skill for code navigation and refactoring. Use textual search
  only for configuration, documentation, literal strings, or non-code files.
- Use the `rust-router` skill before any Rust implementation. This plan does
  not currently require Rust code; introduce a Rust extension or Verus proof
  only if a substantive invariant cannot be expressed and tested cleanly in
  Python.
- Keep `episodic/api/app.py` as a Falcon application factory. Runtime
  environment parsing and concrete adapter construction remain in composition
  roots such as `episodic/api/runtime.py`.
- Treat `/health/live` and `/health/ready` as the canonical health contract.
  These paths already exist in Episodic and match Nile Valley's example chart
  probe contract.
- Define health semantics behind a domain-owned health observation port. The
  Falcon resource may adapt that port, but the domain port must not depend on
  Falcon response objects, Kubernetes probe shapes, or HTTP status codes.
- The container image must run the HTTP server as the deployed Wildside runtime
  entrypoint by starting Granian against
  `episodic.api.runtime:create_app_from_env`. Do not add a second production
  entrypoint that bypasses the HTTP health server.
- Build the container as a multi-stage image and run it as a non-root user with
  stable liveness and readiness checks.
- Align the Helm chart with Nile Valley values conventions:
  `existingSecretName`, `secretEnvFromKeys`, `allowMissingSecret`, optional
  `externalSecret`, optional ingress, configurable non-secret `config`, and
  health probe values.
- Provide local `k3d` orchestration through Python code using Cyclopts and
  Makefile targets named `local-k8s-up`, `local-k8s-down`, `local-k8s-status`,
  and `local-k8s-logs`.
- Use Vidai Mock for behavioural tests of inference services. This preview
  slice should not call live model providers; if any behavioural test exercises
  `LLMPort` or generation services, it must use the existing Vidai Mock
  fixtures.
- Add unit tests with `pytest`, behavioural tests with `pytest-bdd`, snapshot
  tests with `syrupy` where rendered output needs format stability, and
  end-to-end tests for externally observable workflows such as CLI behaviour,
  Helm rendering, container health, and live HTTP network boundaries.
- Use property tests with Hypothesis or CrossHair when introducing an invariant
  over a range of inputs, such as secret-key mapping, health aggregation, or
  Kubernetes name validation.
- Update `docs/users-guide.md`, `docs/developers-guide.md`, the relevant
  architecture/design document, and any Architecture Decision Record (ADR)
  needed to preserve substantive decisions.
- Run validation commands sequentially, not in parallel. Capture long command
  output with `tee` under `/tmp`, for example
  `/tmp/test-episodic-nile-valley-integration.out`.
- Run `coderabbit review --agent` after each major implementation milestone and
  clear all concerns before moving to the next milestone.
- Commit after each approved milestone only after that milestone's gate passes.

## Tolerances

- Scope tolerance: stop and escalate if the implementation exceeds 45 changed
  files or 3500 net new lines before the first working local preview is
  demonstrated.
- Dependency tolerance: stop and escalate before adding any new runtime
  dependency beyond Cyclopts and local preview helpers, or before adding any
  dependency that conflicts with Python `>=3.14`.
- Public contract tolerance: stop and escalate if the existing canonical API
  routes must change, or if `/health/live` and `/health/ready` cannot remain
  backwards compatible.
- Architecture tolerance: stop and escalate if the health observation port
  cannot be introduced without weakening `make check-architecture`.
- Tooling tolerance: stop and escalate if local preview requires privileged
  host changes beyond Docker, `k3d`, `kubectl`, and Helm availability.
- Cluster tolerance: stop and escalate before deleting any non-Episodic
  cluster, namespace, Docker image, or Kubernetes resource.
- Test tolerance: stop and escalate after three failed attempts to stabilize
  the same subprocess, container, Helm rendering, or `k3d` test failure.
- Ambiguity tolerance: stop and ask for direction if "Wildside runtime
  entrypoint" requires a service name, package name, or command-line interface
  that conflicts with current Episodic naming.

## Risks

- Risk: Episodic already has health endpoints, but readiness semantics live in
  `episodic/api/dependencies.py` rather than a domain-owned port. Severity:
  medium. Likelihood: high. Mitigation: first add a domain health observation
  protocol and tests, then adapt existing `ReadinessProbe` wiring through that
  port without changing the external HTTP payload.

- Risk: the repository has no existing Dockerfile, Helm chart, or local `k3d`
  implementation. Severity: medium. Likelihood: high. Mitigation: mirror the
  Corbusier chart and local-k8s structure, prune it to Episodic's actual
  Postgres-backed HTTP service, and add small tests around each helper rather
  than landing one large toolchain change.

- Risk: Python 3.14 images and dependency installation can make container
  builds slow or brittle. Severity: medium. Likelihood: medium. Mitigation: use
  a multi-stage wheel build, copy only required project files into the build
  context, and keep `.dockerignore` aggressive.

- Risk: local `k3d` previews may fail on machines where ports are occupied or
  required CLIs are absent. Severity: medium. Likelihood: medium. Mitigation:
  add validation helpers, loopback port selection with bounded retry, clear
  errors for missing executables, and idempotent status/down commands.

- Risk: Helm `ExternalSecret` support can couple the chart to one secret
  backend. Severity: medium. Likelihood: medium. Mitigation: make
  `externalSecret` values-driven, disabled by default, and compatible with
  `external-secrets.io/v1beta1` without hard-coding a concrete store name.

- Risk: adding a chart and local orchestration increases the quality-gate
  surface beyond the current Makefile. Severity: medium. Likelihood: high.
  Mitigation: add focused validation targets and keep the existing gates
  `make check-fmt`, `make typecheck`, `make lint`, and `make test` green.

## Progress

- [x] (2026-05-21T09:42:32Z) Loaded the requested `leta`, `rust-router`, and
  `hexagonal-architecture` skills, and created a Leta workspace for this
  worktree.
- [x] (2026-05-21T09:42:32Z) Loaded the `execplans`, `firecrawl-mcp`,
  `pr-creation`, and `commit-message` workflows needed for this planning branch.
- [x] (2026-05-21T09:42:32Z) Renamed the branch to
  `nile-valley-integration`.
- [x] (2026-05-21T09:42:32Z) Used Wyvern agents to inspect local Episodic
  conventions and Corbusier, Ghillie, and Nile Valley prior art.
- [x] (2026-05-21T09:42:32Z) Used Firecrawl to verify the Nile Valley example
  chart contract and current upstream documentation for Helm, `k3d`, and
  Cyclopts.
- [x] (2026-05-21T09:42:32Z) Drafted this approval-gated ExecPlan.
- [x] (2026-05-21T10:38:00Z) Received explicit user approval to implement the
  planned functionality.
- [x] (2026-05-21T10:55:00Z) Implemented Stage 1: domain-owned health
  observation port, readiness probe adapter preservation, and focused unit and
  Falcon adapter tests.
- [x] (2026-05-21T11:25:00Z) Ran Stage 1 validation gates: `make check-fmt`,
  `make typecheck`, `make lint`, `make test`, `make markdownlint`, and
  `make nixie`.
- [x] (2026-05-21T11:45:00Z) Ran Stage 1 CodeRabbit review, addressed both
  findings, and reran focused health tests.
- [x] (2026-05-21T12:05:00Z) Reran Stage 1 final gates after CodeRabbit fixes:
  `make check-fmt`, `make typecheck`, `make lint`, and `make test`.
- [x] (2026-05-21T12:10:00Z) Reran Stage 1 Markdown gates after ExecPlan
  updates: `make markdownlint` and `make nixie`.
- [x] (2026-05-21T12:25:00Z) Addressed the second Stage 1 CodeRabbit review
  findings in `tests/test_health_observation.py`, including assertion context
  and a lint-compatible cast for the non-async callable case.
- [x] (2026-05-21T12:35:00Z) Reran Stage 1 commit gates after the second
  CodeRabbit cleanup: `make check-fmt`, `make typecheck`, `make lint`, and
  `make test`.
- [x] (2026-05-21T12:45:00Z) Ran final Stage 1 Markdown gates and CodeRabbit
  review before committing Stage 1; CodeRabbit reported zero findings.
- [x] (2026-05-21T12:50:00Z) Prepared Stage 1 for commit after final
  validation and CodeRabbit review.
- [x] (2026-05-21T13:05:00Z) Committed Stage 1 as `592ff12` after a clean
  `git diff --check`.
- [x] (2026-05-21T13:10:00Z) Started Stage 2 runtime hardening by making the
  Granian factory target, interface, and container HTTP bind port explicit in
  `episodic.api.runtime`.
- [x] (2026-05-21T13:35:00Z) Completed Stage 2 runtime hardening validation:
  focused runtime tests, full code gates, full test suite, Markdown gates, and
  CodeRabbit review passed.
- [x] (2026-05-21T13:45:00Z) Started Stage 3 container image work: added a
  multi-stage Dockerfile, `.dockerignore`, and container contract tests,
  including an opt-in Docker smoke test guarded by `EPISODIC_RUN_DOCKER_TESTS`.
- [x] (2026-05-21T14:25:00Z) Completed Stage 3 container validation: focused
  container contract tests, wheel build validation, full code gates, full test
  suite, Markdown gates, and CodeRabbit review passed. The Docker daemon was
  not available in this environment, so the live image smoke test remains
  documented as an opt-in skip.
- [x] (2026-05-21T14:40:00Z) Started Stage 4 Helm chart implementation with
  Nile Valley-aligned values for config, existing Secret references,
  ExternalSecret, ingress, non-root pod security, and health probes.
- [x] (2026-05-21T16:40:00Z) Completed Stage 4 Helm chart validation after
  focused chart tests, full code gates, full test suite, Markdown gates, and a
  clean CodeRabbit review.
- [x] (2026-05-21T16:50:00Z) Started Stage 5 local `k3d` orchestration with a
  Cyclopts CLI, Makefile targets, command-building helpers, prerequisite
  validation, and focused helper tests.
- [x] (2026-05-21T17:15:00Z) Completed Stage 5 local preview tooling
  validation after full code gates, full tests, Markdown gates, and a clean
  CodeRabbit review.
- [x] (2026-05-21T17:25:00Z) Started Stage 6 documentation updates for the
  local `k3d` design, user-facing container and Helm behaviour, maintainer
  conventions, and architecture design notes.
- [x] (2026-05-21T18:27:00Z) Completed Stage 6 documentation validation after
  Markdown linting, Mermaid validation, and a clean CodeRabbit review.
- [x] (2026-05-21T18:50:00Z) Completed final validation and CodeRabbit review
  for the full branch. The final `make test` rerun reported
  `685 passed, 4 skipped`, and CodeRabbit reported `findings: 0`.
- [x] (2026-06-12T17:41:00Z) Started review follow-up for the Docker,
  Postgres bootstrap, local `k3d` idempotence, CLI behavioural coverage, and
  Helm ConfigMap rollout findings.
- [x] (2026-06-12T17:41:00Z) Added red-stage focused tests that reproduced the
  missing Docker COPY source, missing local Postgres bootstrap, incomplete
  success banner, ingress-port mismatch reuse, missing-cluster status/logs
  behaviour, local preview CLI surface, and missing ConfigMap checksum rollout.
- [x] (2026-06-12T17:41:00Z) Implemented the review fixes and reran the focused
  review suite, which reported `22 passed, 1 skipped`.
- [x] (2026-06-12T19:55:00Z) Fixed the host-specific workflow-test failure by
  making `act` tests skip when the configured Podman socket exists but is not
  accepting connections.
- [x] (2026-06-12T20:05:00Z) Completed full review-fix validation:
  `make check-fmt`, `make typecheck`, `make lint`, and `make test` passed; the
  final full test run reported `694 passed, 3 skipped`.
- [x] (2026-06-12T20:35:00Z) Ran CodeRabbit review for the follow-up, addressed
  the subprocess timeout and lint-suppression comment findings in the new local
  preview BDD test, and reran CodeRabbit to `findings: 0`.
- [x] (2026-06-13T13:20:00Z) Started the rootless Podman and kind live-preview
  follow-up. Focused red tests captured the Dockerfile dependency-layout gap
  and the missing provider/engine abstraction in `scripts/local_k8s`.
- [x] (2026-06-13T13:35:00Z) Reworked the Dockerfile to resolve dependencies in
  the uv builder stage, copy the populated virtual environment into the
  non-root runtime stage, install builder tools for source builds, and set
  `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` for Python 3.14 PyO3 dependencies.
  `podman build --tag localhost/episodic:local .` succeeded on this host.
- [x] (2026-06-13T13:55:00Z) Added `docker`/`podman` engine and `k3d`/`kind`
  provider selection to the local preview config, Cyclopts CLI, command
  builders, orchestration, and focused tests.
- [x] (2026-06-13T14:15:00Z) Live
      `uv run scripts/local_k8s.py up --engine podman --provider kind` created
      the kind cluster but failed at image loading:
      kind's `load docker-image` path did not see the rootless Podman image
      store. The implementation now saves the Podman image to a `/tmp` archive
      and loads it with `kind load image-archive`.
- [x] (2026-06-13T14:35:00Z) The next live run loaded the image and started the
  pod, but it crash-looped because the copied virtual environment's console
  scripts still pointed at `/src/.venv/bin/python`. The Dockerfile now builds
  the venv at `/app/.venv` in the builder stage and copies it to the same path
  in the runtime stage so the Granian entrypoint shebang remains valid.
- [x] (2026-06-13T14:55:00Z) The corrected
      `uv run scripts/local_k8s.py up --engine podman --provider kind` run
      succeeded after recreating the kind
      cluster without host-port mappings. `kubectl get pods` showed Episodic
      and Postgres both `1/1 Running`;
      `curl -i -fsS http://127.0.0.1:8088/health/live` and `/health/ready`
      through `kubectl port-forward svc/episodic 8088:80` both returned HTTP
      `200`.
- [x] (2026-06-13T15:00:00Z) Live
      `uv run scripts/local_k8s.py status --engine podman --provider kind`
      reported the Deployment, Service, Ingress,
      and pods, and
      `uv run scripts/local_k8s.py logs --engine podman --provider kind`
      returned Granian startup logs from the running application pod.
- [x] (2026-06-13T15:20:00Z) Added Makefile variables
      `LOCAL_K8S_ENGINE` and `LOCAL_K8S_PROVIDER` so the validated Podman/kind
      path can be driven through `make local-k8s-up` while preserving
      Docker/`k3d` defaults.
- [x] (2026-06-13T15:55:00Z) Full validation passed after fixing the rootless
      Podman `act` artefact server binding: `make check-fmt`, `make typecheck`,
      `make lint`, `make test` (`704 passed, 1 skipped`), `make markdownlint`,
      and `make nixie`.
- [x] (2026-06-13T16:20:00Z) CodeRabbit review found only assertion-message
      and docstring hygiene issues in the new rootless Podman/kind tests.
      Addressed those findings and reran the focused coverage:
      `/tmp/coderabbit-focused-kind-podman-episodic-nile-valley-integration.out`
      reported `10 passed`.
- [x] (2026-06-13T16:35:00Z) Post-CodeRabbit gates passed:
      `make check-fmt`, `make typecheck`, `make lint`, and `make test`
      (`704 passed, 1 skipped`). Two subsequent CodeRabbit reruns stalled in
      remote sandbox setup after `preparing_sandbox`; both were stopped after
      no findings were emitted.
- [x] (2026-06-13T14:40:00Z) Fresh goal-audit live validation passed on the
      current `42901d4` branch head: `uv run scripts/local_k8s.py up --engine
      podman --provider kind` reported the preview ready, `kubectl
      port-forward svc/episodic 8088:80` exposed the service, and both
      `/health/live` and `/health/ready` returned HTTP `200`. Status showed
      Episodic and Postgres `1/1 Running`; logs showed Granian listening on
      `0.0.0.0:8080`. The preview cluster was then torn down successfully.

## Surprises & discoveries

- Observation: Episodic already exposes `GET /health/live` and
  `GET /health/ready` through `episodic/api/resources/health.py`, and Granian
  can already boot `episodic.api.runtime:create_app_from_env`. Evidence:
  `docs/adr/adr-002-http-service-composition-root.md`,
  `tests/test_health_endpoints.py`, and
  `tests/steps/test_http_service_scaffold_steps.py`. Impact: the HTTP work is
  not a new endpoint scaffold. It is a refactor and hardening step that moves
  health semantics behind a domain port while preserving the current probe
  contract.

- Observation: Nile Valley's README describes a multi-application preview
  workflow where applications supply Helm charts, and its example chart uses
  `existingSecretName`, `secretEnvFromKeys`, `allowMissingSecret`, session
  secret values, and `/health/live` plus `/health/ready` probes. Evidence:
  Firecrawl scrape of `https://github.com/leynos/nile-valley` and
  `deploy/charts/example-app/values.yaml`. Impact: the Episodic chart should
  match the example-app contract unless a documented Episodic-specific need
  requires an extension.

- Observation: Corbusier has the richer local `k3d` orchestration pattern,
  including Cyclopts commands, dependency bootstrap, Docker image import, Helm
  install, status, logs, and success banners. Evidence: the Wyvern prior-art
  brief and local reference files under `/tmp/corbusier-ref/scripts/local_k8s`.
  Impact: mirror Corbusier's structure for the local preview toolchain, but
  keep dependencies limited to Episodic's actual Postgres and HTTP needs.

- Observation: Ghillie provides the closer Python container precedent: a
  multi-stage wheel build, non-root runtime user, and container `HEALTHCHECK`.
  Evidence: the Wyvern prior-art brief and `/tmp/ghillie-ref/Dockerfile`.
  Impact: use Ghillie for Python image mechanics and Corbusier for Kubernetes
  chart and local preview shape.

- Observation: the first focused Stage 1 test run failed because
  `episodic.canonical.health.HealthObserver` incorrectly inherited from
  `collections.abc.Protocol`. Evidence:
  `/tmp/health-stage1-episodic-nile-valley-integration.out`. Impact: corrected
  the protocol base to `typing.Protocol`; no design change was needed.

- Observation: the second focused Stage 1 test run exposed that awaiting inside
  a generator expression produced an async generator instead of a tuple of
  checks. Evidence:
  `/tmp/health-stage1-rerun-episodic-nile-valley-integration.out`. Impact:
  changed `ProbeHealthObserver.observe()` to build observations with an
  explicit loop, which keeps sequential readiness semantics clear and avoids
  hidden task scheduling.

- Observation: the focused Stage 1 rerun passed after the protocol and async
  aggregation fixes. Evidence:
  `/tmp/health-stage1-rerun2-episodic-nile-valley-integration.out` reported
  `13 passed`. Impact: the domain health port and Falcon adapter preservation
  are ready for full milestone gates.

- Observation: the first full Stage 1 `make test` run reported three
  py-pglite fixture setup timeouts and one migration BDD timeout, while all new
  health tests passed. Evidence:
  `/tmp/test-stage1-episodic-nile-valley-integration.out`. Impact: reran the
  failing tests directly; three passed immediately and the migration BDD test
  passed on a second isolated run. A full `make test` rerun then passed with
  `666 passed, 3 skipped` in
  `/tmp/test-stage1-rerun-full-episodic-nile-valley-integration.out`.

- Observation: Stage 1 non-test gates passed after formatting and type
  narrowing fixes. Evidence:
  `/tmp/check-fmt-stage1-rerun4-episodic-nile-valley-integration.out`,
  `/tmp/typecheck-stage1-rerun3-episodic-nile-valley-integration.out`,
  `/tmp/lint-stage1-rerun-episodic-nile-valley-integration.out`,
  `/tmp/markdownlint-stage1-episodic-nile-valley-integration.out`, and
  `/tmp/nixie-stage1-episodic-nile-valley-integration.out`. Impact: Stage 1 is
  ready for CodeRabbit review and commit.

- Observation: CodeRabbit returned two trivial Stage 1 findings: expand the
  `episodic.canonical.health` module docstring and broaden
  `tests/test_health_observation.py` coverage for false returns, iterable
  construction, non-async callables, and mixed aggregation. Evidence:
  `/tmp/coderabbit-stage1-episodic-nile-valley-integration.out`. Impact:
  implemented both requests; focused health tests then reported `17 passed` in
  `/tmp/health-stage1-coderabbit-fixes-episodic-nile-valley-integration.out`.

- Observation: the final Stage 1 code gates passed after the CodeRabbit fixes
  and import-sort cleanup. Evidence:
  `/tmp/check-fmt-stage1-final2-episodic-nile-valley-integration.out`,
  `/tmp/typecheck-stage1-final2-episodic-nile-valley-integration.out`,
  `/tmp/lint-stage1-final2-episodic-nile-valley-integration.out`, and
  `/tmp/test-stage1-final-episodic-nile-valley-integration.out`, which reported
  `670 passed, 3 skipped`. Impact: only final Markdown gates and a clean
  CodeRabbit rerun remain before the Stage 1 commit.

- Observation: the final Stage 1 Markdown gates passed after this ExecPlan was
  updated with validation evidence. Evidence:
  `/tmp/markdownlint-stage1-final2-episodic-nile-valley-integration.out` and
  `/tmp/nixie-stage1-final2-episodic-nile-valley-integration.out`. Impact:
  Stage 1 is ready for final CodeRabbit review and commit.

- Observation: the final CodeRabbit pass found two remaining trivial test
  concerns: bare assertions in `tests/test_health_observation.py` lacked
  descriptive messages, and its suggested inline `typ.cast("Any", ...)`
  conflicted with `ty` and Ruff when applied literally. Evidence:
  `/tmp/coderabbit-stage1-final-episodic-nile-valley-integration.out`,
  `/tmp/typecheck-stage1-commit-episodic-nile-valley-integration.out`, and
  `/tmp/lint-stage1-commit2-episodic-nile-valley-integration.out`. Impact:
  added assertion messages and used a local
  `typ.cast("dict[str, typ.Any]", ...)` mapping to exercise runtime validation
  while satisfying the repository's type and lint rules.

- Observation: the Stage 1 commit gates passed after that final cleanup.
  Evidence:
  `/tmp/check-fmt-stage1-commit3-episodic-nile-valley-integration.out`,
  `/tmp/typecheck-stage1-commit3-episodic-nile-valley-integration.out`,
  `/tmp/lint-stage1-commit3-episodic-nile-valley-integration.out`, and
  `/tmp/test-stage1-commit-episodic-nile-valley-integration.out`, which reported
  `670 passed, 3 skipped`. Impact: Stage 1 is ready for final Markdown gates,
  CodeRabbit review, and commit.

- Observation: final Stage 1 Markdown gates and CodeRabbit review passed after
  the last ExecPlan update. Evidence:
  `/tmp/markdownlint-stage1-commit-episodic-nile-valley-integration.out`,
  `/tmp/nixie-stage1-commit-episodic-nile-valley-integration.out`, and
  `/tmp/coderabbit-stage1-commit-episodic-nile-valley-integration.out`, which
  reported `findings: 0`. Impact: Stage 1 can be committed.

- Observation: Stage 2 did not require a new HTTP entrypoint because
  `episodic.api.runtime:create_app_from_env` already booted Falcon through
  Granian. Evidence: `tests/steps/test_http_service_scaffold_steps.py` and the
  focused run in `/tmp/runtime-stage2-episodic-nile-valley-integration.out`,
  which reported `9 passed`. Impact: made the entrypoint contract explicit as
  runtime constants for later Docker and Helm wiring instead of introducing a
  second wrapper command.

- Observation: Stage 2 full validation passed after the runtime contract
  constants and behavioural test update. Evidence:
  `/tmp/check-fmt-stage2-episodic-nile-valley-integration.out`,
  `/tmp/typecheck-stage2-episodic-nile-valley-integration.out`,
  `/tmp/lint-stage2-episodic-nile-valley-integration.out`,
  `/tmp/test-stage2-episodic-nile-valley-integration.out`, which reported
  `671 passed, 3 skipped`,
  `/tmp/markdownlint-stage2-episodic-nile-valley-integration.out`,
  `/tmp/nixie-stage2-episodic-nile-valley-integration.out`, and
  `/tmp/coderabbit-stage2-episodic-nile-valley-integration.out`, which reported
  `findings: 0`. Impact: Stage 2 is ready to commit.

- Observation: the first Stage 3 formatting gate failed because
  `tests/test_container_image_contract.py` needed Ruff formatting. Evidence:
  `/tmp/check-fmt-stage3-episodic-nile-valley-integration.out`. Impact:
  formatted the test file with `uv run ruff format` before continuing with the
  Stage 3 gates.

- Observation: the first Stage 3 lint gate failed on the new container contract
  test for import ordering, the intentional `0.0.0.0` container bind host, and
  partial Docker executable paths in the opt-in smoke test. Evidence:
  `/tmp/lint-stage3-episodic-nile-valley-integration.out`. Impact: sorted the
  imports, documented the intentional container bind, and used the resolved
  Docker executable path when the smoke test is enabled.

- Observation: Docker was not available or not reachable in this execution
  environment. Evidence: `command -v docker >/dev/null 2>&1 && docker version`
  produced no output, and the opt-in smoke test skipped in
  `/tmp/container-stage3-focused-episodic-nile-valley-integration.out`. Impact:
  validated the image contract by parsing `Dockerfile`, checking the runtime
  constants, and running `uv build --wheel --out-dir /tmp/episodic-stage3-dist`
  successfully in `/tmp/uv-build-stage3-episodic-nile-valley-integration.out`;
  the live Docker smoke can be exercised later with
  `EPISODIC_RUN_DOCKER_TESTS=1`.

- Observation: Stage 3 full validation passed after formatting and lint
  cleanup. Evidence:
  `/tmp/check-fmt-stage3-rerun2-episodic-nile-valley-integration.out`,
  `/tmp/typecheck-stage3-rerun-episodic-nile-valley-integration.out`,
  `/tmp/lint-stage3-rerun-episodic-nile-valley-integration.out`,
  `/tmp/test-stage3-episodic-nile-valley-integration.out`, which reported
  `675 passed, 4 skipped`,
  `/tmp/markdownlint-stage3-episodic-nile-valley-integration.out`,
  `/tmp/nixie-stage3-episodic-nile-valley-integration.out`, and
  `/tmp/coderabbit-stage3-episodic-nile-valley-integration.out`, which reported
  `findings: 0`. Impact: Stage 3 is ready to commit.

- Observation: the initial Stage 4 chart lint and render checks passed, and the
  focused Helm chart tests generated one syrupy snapshot. Evidence:
  `/tmp/helm-lint-stage4-initial-episodic-nile-valley-integration.out`,
  `/tmp/helm-template-stage4-initial-episodic-nile-valley-integration.out`,
  `/tmp/helm-stage4-tests-update-episodic-nile-valley-integration.out`, and
  `/tmp/helm-stage4-tests-episodic-nile-valley-integration.out`. Impact: chart
  structure and local manifest snapshot are ready for full gates.

- Observation: the first Stage 4 formatting gate failed because
  `tests/test_helm_chart_contract.py` needed Ruff formatting. Evidence:
  `/tmp/check-fmt-stage4-episodic-nile-valley-integration.out`. Impact:
  formatted the Helm chart test before continuing with Stage 4 gates.

- Observation: the first Stage 4 lint gate failed because the Helm snapshot
  test imported `SnapshotAssertion` at runtime and had one long assertion
  message. Evidence: `/tmp/lint-stage4-episodic-nile-valley-integration.out`.
  Impact: moved the snapshot assertion import under `TYPE_CHECKING` and wrapped
  the Helm failure message before rerunning gates.

- Observation: the Stage 4 lint rerun then caught a Python 3.14 lazy
  annotation cleanup where the `SnapshotAssertion` annotation no longer needed
  quotes. Evidence:
  `/tmp/lint-stage4-rerun-episodic-nile-valley-integration.out`. Impact:
  removed the annotation quotes and continued validation.

- Observation: Stage 4 CodeRabbit review reported seven chart concerns: make
  rollout strategy explicit, tighten the probe schema, add default resource
  requests and limits, support per-secret optional flags, support PDB
  `maxUnavailable`, document ExternalSecret ownership semantics, and confirm
  the Helm subprocess lint suppression. Evidence:
  `/tmp/coderabbit-stage4-episodic-nile-valley-integration.out`. Impact:
  implemented chart changes for the substantive findings, added chart README
  documentation for ExternalSecret lifecycle behaviour, and regenerated the
  local manifest snapshot.

- Observation: the Stage 4 CodeRabbit rerun reported five remaining chart
  polish concerns: standardize `secretEnvFromKeys`, document secret-name
  resolution priority, add a pod version label, fail clearly for enabled PDBs
  without a constraint, and tighten ingress schema validation. Evidence:
  `/tmp/coderabbit-stage4-rerun-episodic-nile-valley-integration.out`. Impact:
  implemented all five before the final Stage 4 validation pass.

- Observation: the final Stage 4 CodeRabbit pass still found four small
  validation concerns: demonstrate `allowMissingSecret` fallback in default
  `secretEnvFromKeys`, require root schema keys, parse `helm lint` JSON in
  tests, and enforce PDB mutual exclusivity. Evidence:
  `/tmp/coderabbit-stage4-final-episodic-nile-valley-integration.out`. Impact:
  applied all four changes before rerunning focused Helm tests.

- Observation: Helm 4.0.4 does not support `helm lint --output json`, so the
  CodeRabbit suggestion to parse machine-readable lint output is not valid for
  the installed Helm CLI. Evidence:
  `/tmp/helm-stage4-tests-final-update-episodic-nile-valley-integration.out`.
  Impact: kept `helm lint` text output but parse the failure count with a
  regular expression instead of matching the full output string.

- Observation: the Stage 4 precommit CodeRabbit pass found a real bug in the
  pod `app.kubernetes.io/version` label fallback order, plus Helm NOTES access
  guidance and README wrapping requests. Evidence:
  `/tmp/coderabbit-stage4-precommit-episodic-nile-valley-integration.out`.
  Impact: fixed image tag precedence, added ingress/port-forward notes, and
  wrapped chart README prose.

- Observation: the second Stage 4 precommit CodeRabbit pass found only a Helm
  subprocess comment clarity issue and missing optional Kubernetes probe fields
  in the values schema. Evidence:
  `/tmp/coderabbit-stage4-final2-episodic-nile-valley-integration.out`. Impact:
  clarified the narrow `subprocess.run` suppression and expanded the probe
  schema for HTTP headers, TCP host, gRPC probes, and probe-level termination
  grace period.

- Observation: the next Stage 4 CodeRabbit pass found four more small chart
  polish requests: conditionally render optional probe/resource blocks, clarify
  README wording, avoid contradictory PDB defaults, and make the probe schema
  strict at the top level. Evidence:
  `/tmp/coderabbit-stage4-final3-episodic-nile-valley-integration.out`. Impact:
  applied all four changes before rerunning Helm chart validation.

- Observation: the following Stage 4 CodeRabbit pass found only documentation
  and schema consistency issues: clarify the secret-name helper comment, wrap
  the chart README, and make probe handler schemas strict in the same way as
  the top-level probe schema. Evidence:
  `/tmp/coderabbit-stage4-final4-episodic-nile-valley-integration.out`. Impact:
  applied those fixes and reran the focused Helm chart tests, which passed with
  `4 passed` and one accepted snapshot in
  `/tmp/helm-stage4-tests-final4-rerun-episodic-nile-valley-integration.out`.

- Observation: the next Stage 4 CodeRabbit pass found three minor chart
  concerns: keep README wrapping in the exact requested shape and make the
  default `DATABASE_URL` secret key explicitly required even though
  `allowMissingSecret` remains available as a fallback for entries that omit
  `optional`. Evidence:
  `/tmp/coderabbit-stage4-final5-episodic-nile-valley-integration.out`. Impact:
  wrapped the README, set `secretEnvFromKeys.DATABASE_URL.optional` to `false`,
  and reran the focused Helm chart tests with snapshot update in
  `/tmp/helm-stage4-tests-final5-update-episodic-nile-valley-integration.out`.

- Observation: the final Stage 4 CodeRabbit rerun found that the values schema
  did not yet cover every value group consumed by chart templates, and asked
  either for mandatory probes or fallback probe rendering. Evidence:
  `/tmp/coderabbit-stage4-final6-episodic-nile-valley-integration.out`. Impact:
  extended `values.schema.json` for service accounts, pod labels and
  annotations, security contexts, service, resources, PDBs, scheduling values,
  name overrides, and image pull secrets; made container liveness and readiness
  probes mandatory in schema; then reran focused Helm tests in
  `/tmp/helm-stage4-tests-final6-rerun-episodic-nile-valley-integration.out`.

- Observation: the next Stage 4 CodeRabbit rerun found a real Helm template
  bug: `default` treats explicit `false` as empty, so
  `secretEnvFromKeys.*.optional: false` could be overridden by
  `allowMissingSecret: true`. Evidence:
  `/tmp/coderabbit-stage4-final7-episodic-nile-valley-integration.out`. Impact:
  replaced the `default` call with a `hasKey` conditional and added a focused
  Helm test proving an explicit required secret remains `optional: false` when
  the fallback allows missing secrets; the focused chart test suite passed with
  `5 passed` in
  `/tmp/helm-stage4-tests-final7-rerun-episodic-nile-valley-integration.out`.

- Observation: the following Stage 4 CodeRabbit rerun found only readability
  cleanup in the deployment template: use pipe-form `default` for image tag
  fallback and remove unnecessary whitespace-control markers from the optional
  secret conditional. Evidence:
  `/tmp/coderabbit-stage4-final8-episodic-nile-valley-integration.out`. Impact:
  applied both template cleanups and reran focused Helm chart tests with
  `5 passed` in
  `/tmp/helm-stage4-tests-final8-rerun-episodic-nile-valley-integration.out`.

- Observation: Stage 4 final validation passed after the last Helm template
  cleanup. Evidence:
  `/tmp/check-fmt-stage4-final9-episodic-nile-valley-integration.out`,
  `/tmp/typecheck-stage4-final9-episodic-nile-valley-integration.out`,
  `/tmp/lint-stage4-final9-episodic-nile-valley-integration.out`,
  `/tmp/markdownlint-stage4-final9-episodic-nile-valley-integration.out`,
  `/tmp/nixie-stage4-final9-episodic-nile-valley-integration.out`,
  `/tmp/test-stage4-final9-episodic-nile-valley-integration.out`, which reported
  `680 passed, 4 skipped`, and
  `/tmp/coderabbit-stage4-final9-episodic-nile-valley-integration.out`, which
  reported `findings: 0`. Impact: Stage 4 is ready to commit.

- Observation: the first Stage 5 focused implementation added
  `scripts/local_k8s.py`, a `scripts/local_k8s/` helper package, Cyclopts in
  the dev dependency group, and Makefile targets for `local-k8s-up`,
  `local-k8s-down`, `local-k8s-status`, and `local-k8s-logs`. Evidence:
  `/tmp/local-k8s-stage5-focused-rerun-episodic-nile-valley-integration.out`
  reported `5 passed`, and
  `/tmp/local-k8s-stage5-help-rerun-episodic-nile-valley-integration.out`
  rendered the CLI command surface. Impact: Stage 5 is ready for broader code
  gates and CodeRabbit review before commit.

- Observation: the first Stage 5 CodeRabbit review found only clarity issues:
  add assertion messages to local-k8s helper tests, document that the default
  database URL uses local-preview credentials only, and explain the
  `SO_REUSEADDR` port-probe trade-off. Evidence:
  `/tmp/coderabbit-stage5-episodic-nile-valley-integration.out`. Impact:
  applied all three suggestions and reran focused local-k8s tests with
  `5 passed` in
  `/tmp/local-k8s-stage5-coderabbit-rerun-episodic-nile-valley-integration.out`.

- Observation: Stage 5 final validation passed after CodeRabbit cleanup.
  Evidence: `/tmp/check-fmt-stage5-final-episodic-nile-valley-integration.out`,
  `/tmp/typecheck-stage5-final-episodic-nile-valley-integration.out`,
  `/tmp/lint-stage5-final-episodic-nile-valley-integration.out`,
  `/tmp/markdownlint-stage5-final-episodic-nile-valley-integration.out`,
  `/tmp/nixie-stage5-final-episodic-nile-valley-integration.out`,
  `/tmp/test-stage5-final-episodic-nile-valley-integration.out`, which reported
  `685 passed, 4 skipped`, and
  `/tmp/coderabbit-stage5-final-episodic-nile-valley-integration.out`, which
  reported `findings: 0`. Impact: Stage 5 is ready to commit.

- Observation: Stage 6 documentation now includes
  `docs/local-k3d-preview-design.md`, user-guide deployment and local preview
  commands, developer-guide container/Helm/local-k8s conventions, and a system
  design note tying the health port to the Falcon adapter and Nile Valley
  deployment surface. Evidence:
  `/tmp/markdownlint-stage6-docs-episodic-nile-valley-integration.out`,
  `/tmp/nixie-stage6-docs-episodic-nile-valley-integration.out`, and
  `/tmp/coderabbit-stage6-docs-episodic-nile-valley-integration.out`, which
  reported `findings: 0`. Impact: Stage 6 is ready to commit.

- Observation: the first final `make test` pass found a latent guest-bio
  property-test instability unrelated to the Nile Valley implementation.
  Hypothesis generated XML noncharacters such as `U+FFFE` and `U+1FFFE`, which
  `tei_rapporteur` correctly rejects during XML emission. Evidence:
  `/tmp/test-final-episodic-nile-valley-integration.out` failed one property
  test, and
  `/tmp/guest-bios-properties-rerun2-episodic-nile-valley-integration.out`
  passed after constraining the property strategy to XML-compatible text.
  Impact: keep the final validation loop open and rerun the full gates after
  committing the test-stability fix.

- Observation: the 2026-06-12 review correctly found that the Dockerfile still
  copied the non-existent `stilyagi` directory, and that the local preview
  could not become ready because no Postgres dependency was deployed in the
  `k3d` cluster. Evidence:
  `/tmp/review-fixes-red-episodic-nile-valley-integration.out` reproduced the
  missing COPY source, local Postgres bootstrap, ingress-port mismatch,
  status/logs, and ConfigMap checksum failures. Impact: removed the stale COPY
  line, added a Docker COPY-source contract test, made `local-k8s-up` apply a
  local-only Postgres Service and StatefulSet before Helm, and added focused
  tests plus a pytest-bdd CLI scenario.

- Observation: the first full review-fix `make test` run reached the end of
  the suite but failed two pre-existing `act` workflow tests because this host
  has a stale or unreachable Podman socket at
  `/run/user/1000/podman/podman.sock`. Evidence:
  `/tmp/test-review-fixes-episodic-nile-valley-integration.out`. Impact: made
  the shared workflow test helper verify that the Podman UNIX socket accepts
  connections before invoking `act`, matching the existing skip behaviour for
  missing `act` or missing sockets. The final full test run reported
  `694 passed, 3 skipped` in
  `/tmp/test-review-fixes3-episodic-nile-valley-integration.out`.

- Observation: CodeRabbit's follow-up review found only test hygiene issues in
  the new local preview BDD step: add subprocess timeouts and justify the
  static-argument `subprocess.run` suppressions. Evidence:
  `/tmp/coderabbit-review-fixes-episodic-nile-valley-integration.out`,
  `/tmp/coderabbit-review-fixes2-episodic-nile-valley-integration.out`, and
  `/tmp/coderabbit-review-fixes3-episodic-nile-valley-integration.out`. Impact:
  added 30-second subprocess timeouts, clarified the `# noqa: S603` comments,
  reran focused BDD coverage, and got CodeRabbit to `findings: 0`.

- Observation: this host has Helm at `/usr/bin/helm`, but Docker, `k3d`, and
  `kubectl` are missing from `PATH`. Evidence: the 2026-06-12 tool check printed
  `docker=missing`, `k3d=missing`, `kubectl=missing`, and
  `helm=/usr/bin/helm`. Impact: the live `make local-k8s-up` acceptance path
  cannot run in this worktree environment; the branch relies on structural,
  Helm, CLI, and orchestration tests until a Docker-capable host can run the
  preview end to end.

- Observation (2026-06-13): the "missing tools" framing was incomplete. This
  host has rootless Podman and Helm; `k3d` and `kubectl` were then installed.
  Re-testing showed the live path is blocked by implementation and host facts,
  not merely by absent binaries. See the three entries below and the new "Local
  preview on rootless Podman" section for the validated path.

- Observation (2026-06-13): the image cannot build, independent of the earlier
  `stilyagi` fix. `pyproject.toml` declares two `git+https` dependencies
  (`femtologging` and `tei-rapporteur`); the Dockerfile resolves all
  dependencies with `pip install <wheel>` in the git-less `python:3.14-slim`
  runtime stage, so the build fails with `Cannot find command 'git'`. Evidence:
  `podman build .` on this host. Neither base image ships git
  (`python:3.14-slim` and the `uv` builder both lack it). This was masked
  because earlier validation only ran the builder-stage `uv build --wheel`
  (which packages the local project without resolving deps), the contract test
  only parses Dockerfile text, and the opt-in Docker smoke test never ran.
  Impact: resolve dependencies in the builder stage (which can install git) and
  copy the populated venv into the runtime stage, or add git to the runtime
  stage; prefer the former to keep the runtime slim and honour `uv.lock`.

- Observation (2026-06-13): k3d/k3s cannot run under rootless Podman on this
  host. With `DOCKER_HOST`/`DOCKER_SOCK` pointed at the rootless Podman socket
  and a DNS-enabled `k3d` network, nodes boot but the server dies with
  `level=fatal msg="Error: failed to find cpuset cgroup (v2)"`. Rootless
  delegation here is `cpu memory pids` only; delegating `cpuset`/`io` requires
  a root-written `/etc/systemd/system/user@.service.d/delegate.conf` plus
  `systemctl daemon-reload` — a privileged host change that hits the plan's
  tooling tolerance. `--kubelet-arg=feature-gates=KubeletInUserNamespace=true`
  does not help, because k3s checks for the cpuset controller before the
  kubelet starts. Evidence: `podman logs k3d-<cluster>-server-0`.

- Observation (2026-06-13): kind (kubeadm + containerd) does run under rootless
  Podman with no privileged host change. It does not require the `cpuset`
  controller; the default `cpu` delegation plus a
  `systemd-run --scope --user -p Delegate=yes` wrapper suffices. A cluster
  reached Ready in ~18s, the local Postgres bootstrap from
  `scripts.local_k8s.commands.local_postgres_manifest` became `1/1 Running` with
  `pg_isready` accepting connections, and `helm upgrade --install` against the
  chart was accepted by the Kubernetes 1.36 API server (Deployment, Service,
  ConfigMap, Ingress all created; the pod `DATABASE_URL` resolved from the
  `episodic-local` Secret with `optional: false`). The only failure was the
  episodic pod itself, blocked on the broken image build above, not on any
  manifest or wiring defect. The precise, reproducible steps are in the "Local
  preview on rootless Podman" section.

- Observation (2026-06-13): when the Podman socket is live, the repository's
  `act` workflow tests also need an artefact server reachable from rootless job
  containers. Evidence:
  `/tmp/workflow-act-rootless-artifacts-episodic-nile-valley-integration-rerun.out`
  passed after binding the artefact server to `0.0.0.0` with a concrete free
  port instead of advertising port `0`. Impact: the helper still skips on hosts
  without a usable Podman socket, but a live rootless Podman host now exercises
  the workflow tests successfully.

- Observation (2026-06-13): the post-fix CodeRabbit review first returned five
  test-hygiene findings: add NumPy-style docstrings to the kind
  `RecordingRunner` methods and add assertion messages in the new local
  Kubernetes and workflow helper tests. Evidence:
  `/tmp/coderabbit-kind-podman-episodic-nile-valley-integration.out`. Impact:
  addressed all five findings, reran the focused coverage, and then reran the
  code gates.

- Observation (2026-06-13): two CodeRabbit reruns after the hygiene fixes
  stalled in remote sandbox setup after emitting `preparing_sandbox` and no
  findings. Evidence:
  `/tmp/coderabbit-kind-podman-episodic-nile-valley-integration-rerun.out` and
  `/tmp/coderabbit-kind-podman-episodic-nile-valley-integration-rerun2.out`.
  Impact: recorded the tool-side stall and relied on the completed CodeRabbit
  findings plus the focused and full local gates for the final commit decision.

## Decision log

- Decision: keep `/health/live` and `/health/ready` as the external health
  URLs. Rationale: these endpoints already exist in Episodic, are documented in
  ADR-002, and match the Nile Valley example chart's probe defaults.
  Date/Author: 2026-05-21 / Codex.

- Decision: introduce a domain-owned health observation port instead of moving
  readiness logic deeper into the Falcon adapter. Rationale: the user
  explicitly asked to decouple health semantics from HTTP, and the hexagonal
  architecture skill requires the domain to own ports while adapters translate
  transport-specific details. Date/Author: 2026-05-21 / Codex.

- Decision: model the implementation on Corbusier for Helm and local `k3d`,
  and on Ghillie for Python container mechanics. Rationale: Corbusier is the
  stronger Nile Valley-aligned chart and orchestration reference, while Ghillie
  demonstrates a production-style Python image pattern. Date/Author: 2026-05-21
  / Codex.

- Decision: keep Vidai Mock as a conditional requirement rather than forcing
  it into health-only behavioural tests. Rationale: the requested preview work
  does not inherently call inference services. If implementation touches
  generation or `LLMPort` behaviour, behavioural tests must use Vidai Mock.
  Date/Author: 2026-05-21 / Codex.

- Decision: start implementation with the health port milestone and preserve
  the current `ReadinessProbe` construction API during the first change.
  Rationale: existing runtime wiring and tests already depend on
  `ReadinessProbe(name, check)`, so keeping that small API stable lets the
  Falcon adapter move to a domain observer without expanding the public change
  surface. Date/Author: 2026-05-21 / Codex.

- Decision: expose the Granian factory target, interface, and default
  container HTTP bind port as constants in the runtime composition root.
  Rationale: later Dockerfile, Helm, and local preview code need to use the
  Wildside HTTP runtime entrypoint consistently, and centralizing these values
  avoids string drift while keeping the runtime path unchanged. Date/Author:
  2026-05-21 / Codex.

- Decision: make the live Docker image smoke test opt-in with
  `EPISODIC_RUN_DOCKER_TESTS=1`. Rationale: the repository gates should remain
  deterministic on agent hosts without a Docker daemon, while still providing
  an executable end-to-end image check for environments that can build and run
  containers. Date/Author: 2026-05-21 / Codex.

- Decision: bootstrap local Postgres from the Python preview orchestration
  instead of adding a chart dependency. Rationale: the dependency is
  local-only, should not become part of the production Helm release, and must
  use the same idempotent `kubectl apply` flow as namespace and Secret setup.
  Date/Author: 2026-06-12 / Codex.

- Decision: keep GitHub Actions `act` workflow tests optional on hosts without
  a usable Podman socket, including stale socket-file cases. Rationale: these
  tests require a working container daemon, and treating an unreachable socket
  as a hard failure makes normal `make test` results depend on local daemon
  state rather than workflow correctness. Date/Author: 2026-06-12 / Codex.

- Decision: add `--engine` and `--provider` selection to the local Kubernetes
  preview toolchain, keeping Docker plus `k3d` as the default and supporting
  rootless Podman plus kind as the validated path on this host. Rationale:
  `k3d` requires privileged cgroup delegation under rootless Podman here, while
  kind runs without host-level changes and satisfies the plan's local preview
  acceptance criteria. Date/Author: 2026-06-13 / Codex.

## Outcomes and retrospective

Episodic now has a production-oriented Nile Valley integration surface. The
implemented branch adds a domain-owned health observation port, preserves the
Falcon `/health/live` and `/health/ready` HTTP contract, makes the Granian
factory runtime explicit, adds a non-root multi-stage container image, provides
a Nile Valley-aligned Helm chart, and exposes a Cyclopts-driven local `k3d`
preview workflow through Makefile targets.

The work also adds focused tests for the health port, Falcon health adapter,
runtime command contract, Dockerfile contract, Helm chart rendering and
snapshot output, local `k3d` helper behaviour, and the guest-bio property-test
stability discovery found during final validation. Documentation now covers the
local preview design, user-facing deployment workflow, developer conventions,
and system-design placement of the health port and deployment adapters.

The 2026-06-12 review follow-up removed the stale `COPY stilyagi` Dockerfile
line, added a Docker COPY-source regression test, bootstraps local-only
Postgres before Helm waits for readiness, rejects reused clusters with
mismatched ingress ports, improves `status` and `logs` missing-cluster output,
prints the required preview banner fields, rolls pods on ConfigMap changes, and
adds behavioural coverage for the local preview CLI surface.

Original final validation evidence:
`/tmp/check-fmt-guest-bios-property3-episodic-nile-valley-integration.out`,
`/tmp/typecheck-guest-bios-property-episodic-nile-valley-integration.out`,
`/tmp/lint-guest-bios-property-episodic-nile-valley-integration.out`,
`/tmp/markdownlint-guest-bios-property-episodic-nile-valley-integration.out`,
`/tmp/test-final-rerun-episodic-nile-valley-integration.out`, and
`/tmp/coderabbit-final-episodic-nile-valley-integration.out`. The final test
run reported `685 passed, 4 skipped`; the final CodeRabbit review reported
`findings: 0`.

Review follow-up validation evidence:
`/tmp/check-fmt-review-fixes6-episodic-nile-valley-integration.out`,
`/tmp/typecheck-review-fixes6-episodic-nile-valley-integration.out`,
`/tmp/lint-review-fixes6-episodic-nile-valley-integration.out`,
`/tmp/test-review-fixes3-episodic-nile-valley-integration.out`,
`/tmp/markdownlint-review-fixes-final2-episodic-nile-valley-integration.out`,
`/tmp/nixie-review-fixes-final2-episodic-nile-valley-integration.out`,
`/tmp/local-k8s-bdd-comments-episodic-nile-valley-integration.out`, and
`/tmp/coderabbit-review-fixes3-episodic-nile-valley-integration.out`. The final
full test run reported `694 passed, 3 skipped`; the final CodeRabbit review
reported `findings: 0`.

Rootless Podman/kind follow-up validation evidence:
`/tmp/local-k8s-up-kind-podman-episodic-nile-valley-integration-rerun5.out`,
`/tmp/local-k8s-status-kind-podman-episodic-nile-valley-integration.out`,
`/tmp/local-k8s-logs-kind-podman-episodic-nile-valley-integration.out`,
`/tmp/local-k8s-up-kind-podman-goal-audit.out`,
`/tmp/local-k8s-health-live-kind-podman-goal-audit.out`,
`/tmp/local-k8s-health-ready-kind-podman-goal-audit.out`,
`/tmp/local-k8s-status-kind-podman-goal-audit.out`,
`/tmp/local-k8s-logs-kind-podman-goal-audit.out`,
`/tmp/local-k8s-down-kind-podman-goal-audit.out`,
`/tmp/check-fmt-kind-podman-episodic-nile-valley-integration-post-coderabbit.out`,
`/tmp/typecheck-kind-podman-episodic-nile-valley-integration-post-coderabbit.out`,
`/tmp/lint-kind-podman-episodic-nile-valley-integration-post-coderabbit.out`,
`/tmp/test-kind-podman-episodic-nile-valley-integration-post-coderabbit.out`,
`/tmp/markdownlint-kind-podman-episodic-nile-valley-integration-final.out`,
`/tmp/nixie-kind-podman-episodic-nile-valley-integration.out`,
`/tmp/coderabbit-focused-kind-podman-episodic-nile-valley-integration.out`, and
`/tmp/coderabbit-kind-podman-episodic-nile-valley-integration.out`. The final
full test run reported `704 passed, 1 skipped`. CodeRabbit's completed
post-follow-up review findings were addressed; two later reruns stalled in
remote sandbox setup before emitting findings.

On 2026-06-13, with rootless Podman plus freshly installed `k3d`, `kind`, and
`kubectl`, `uv run scripts/local_k8s.py up --engine podman --provider kind`
built the image, loaded it into kind through an image archive, deployed local
Postgres, installed the Helm chart, and reached a ready preview. Through
`kubectl port-forward svc/episodic 8088:80`, both `/health/live` and
`/health/ready` returned HTTP `200`. The `k3d` path additionally requires a
privileged cgroup-delegation change on this host, so the implemented live path
uses kind for rootless Podman while retaining the original Docker plus `k3d`
default. See the next section for the validated, reproducible steps and the
implementation details.

## Local preview on rootless Podman

This section records the validated path for running the local preview on a
rootless Podman host (for example this Rocky 10 worktree), discovered during
the 2026-06-13 review and now represented in `scripts/local_k8s` through
`--engine podman --provider kind`.

### Why kind, not k3d, on rootless Podman

k3d runs k3s nodes as containers, and k3s fatally requires the `cpuset` cgroup
v2 controller (`level=fatal msg="Error: failed to find cpuset cgroup (v2)"`).
Rootless delegation on this host is `cpu memory pids` only. Delegating `cpuset`
and `io` needs a root-owned `/etc/systemd/system/user@.service.d/delegate.conf`
with `Delegate=cpu cpuset io memory pids` followed by
`systemctl daemon-reload` — a privileged host change that the plan's tooling
tolerance says to escalate on. `KubeletInUserNamespace=true` does not avoid it,
because k3s checks for cpuset before the kubelet starts. kind (kubeadm +
containerd) does not require cpuset and runs unprivileged via a
`systemd-run --scope --user` wrapper.

### Host prerequisites (one-time, unprivileged)

```bash
# Rootless Podman API socket (k3d/kind talk to it over the Docker-compat API).
systemctl --user enable --now podman.socket

# kind tails `podman logs`; the rootless default log relay can race kind's
# readiness watcher, so pin a file-based log driver.
mkdir -p ~/.config/containers
printf '[containers]\nlog_driver = "k8s-file"\n' >> ~/.config/containers/containers.conf
```

cgroup v2 must be present (`/sys/fs/cgroup/cgroup.controllers` exists) and
systemd should be 252 or newer so the `cpu` controller is delegated to the user
manager by default. Both hold on this host (systemd 257).

### Create the cluster

```bash
export KIND_EXPERIMENTAL_PROVIDER=podman

cat > /tmp/kind-episodic.yaml <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
EOF

systemd-run --scope --user -p "Delegate=yes" \
  kind create cluster --name episodic-preview \
  --config /tmp/kind-episodic.yaml --wait 180s
# kube context: kind-episodic-preview
```

### Build and load the image

The production image builds on this host after resolving dependencies in the uv
builder stage and copying the populated virtual environment into the runtime
stage. Source builds currently require `build-essential`, and `tei-rapporteur`
requires `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` while its PyO3 dependency
catches up with Python 3.14.

Rootless Podman and kind need an image archive handoff on this host.
`kind load docker-image localhost/episodic:local --name episodic-preview`
reports the local image as absent even after `podman image inspect` succeeds,
while `podman save` followed by `kind load image-archive` works.

```bash
podman build --tag localhost/episodic:local .
podman save --output /tmp/episodic-local-image.tar localhost/episodic:local
KIND_EXPERIMENTAL_PROVIDER=podman \
  kind load image-archive /tmp/episodic-local-image.tar \
  --name episodic-preview
```

### Deploy the chart and dependency

```bash
export KIND_EXPERIMENTAL_PROVIDER=podman
CTX=kind-episodic-preview
NS=episodic

kubectl --context "$CTX" create namespace "$NS" \
  --dry-run=client -o yaml | kubectl --context "$CTX" apply -f -

kubectl --context "$CTX" -n "$NS" create secret generic episodic-local \
  --from-literal=database-url='postgresql+asyncpg://episodic:episodic@postgres:5432/episodic' \
  --dry-run=client -o yaml | kubectl --context "$CTX" apply -f -

# Local-only Postgres dependency (Service + StatefulSet).
uv run --group dev python -c \
  'from scripts.local_k8s.commands import local_postgres_manifest; \
   from scripts.local_k8s.config import PreviewConfig; \
   print(local_postgres_manifest(PreviewConfig(namespace="episodic")))' \
  | kubectl --context "$CTX" apply -f -

helm --kube-context "$CTX" upgrade --install episodic charts/episodic \
  -n "$NS" --values charts/episodic/values.local.yaml --wait --timeout 5m
```

### Reach the service

The chart Service is `ClusterIP`, and its Ingress uses the `traefik` class,
which kind does not install by default. The reliable local check is a
port-forward. Newly created kind clusters intentionally do not map host port
8088, because that would prevent `kubectl port-forward` from binding the same
operator-facing port.

```bash
kubectl --context kind-episodic-preview -n episodic \
  port-forward svc/episodic 8088:80 &
curl -fsS http://127.0.0.1:8088/health/live
curl -fsS http://127.0.0.1:8088/health/ready
```

### Tear down

```bash
KIND_EXPERIMENTAL_PROVIDER=podman kind delete cluster --name episodic-preview
```

### Implementation status

`scripts/local_k8s` now has explicit engine and provider selection. Use
`make local-k8s-up LOCAL_K8S_ENGINE=podman LOCAL_K8S_PROVIDER=kind` for this
validated rootless path. The Makefile retains the Docker plus `k3d` default
when no variables are supplied.

## Context and orientation

Episodic is a Python 3.14 service with Falcon ASGI endpoints and Granian as the
HTTP process runtime. `episodic/api/app.py` registers routes and receives an
`ApiDependencies` object. `episodic/api/runtime.py` reads environment
configuration, builds SQLAlchemy-backed dependencies, and returns the Falcon
application for Granian. Health endpoints currently live in
`episodic/api/resources/health.py`, and tests cover both in-memory ASGI calls
and a live Granian subprocess.

The repository enforces hexagonal boundaries with `episodic/architecture`.
Composition roots may wire concrete adapters, but domain and port modules must
not import infrastructure. New health semantics should therefore live in a
domain-facing module such as `episodic/health.py` or
`episodic/canonical/health.py`, while the Falcon resource converts domain
observations into HTTP status codes and JSON.

There is no current Dockerfile, Helm chart, or local-k8s orchestration in
Episodic. There is an `infra/` tree containing cluster and GitOps template
documentation, but no deployable chart for the application. The implementation
will add new packaging and local preview files instead of modifying an existing
chart.

Nile Valley is the shared infrastructure repository for ephemeral previews. It
expects applications to supply Helm charts. Its example chart exposes
values-driven configuration for non-secret environment variables, externally
managed Secrets, optional session-key mounting, optional ingress, non-root pod
security, and Kubernetes HTTP probes.

Corbusier and Ghillie are the closest implementation references. Corbusier
shows the chart, local `k3d` command shape, and operator-style preview flow.
Ghillie shows a Python image built as a wheel in one stage and installed into a
non-root runtime stage.

## Plan of work

Stage 0 is complete. The user explicitly approved implementation on 2026-05-21.
Production files, chart files, Docker files, Makefile targets, and user-facing
guides may now change within the tolerances above.

Stage 1 introduces the health observation port. Add fail-first unit tests for a
domain health observation type and aggregation behaviour. Implement a small
domain-owned protocol and default observer that represents check names and
statuses without HTTP concepts. Adapt `ReadinessProbe` and
`HealthReadyResource` so the current JSON payload and status-code behaviour do
not change. Update `episodic/architecture/policy.py` if the new module needs
classification, and add architecture tests for the boundary. If the aggregation
rules span multiple checks or failure modes, add Hypothesis tests.

Stage 2 hardens the Falcon and Granian runtime path. Keep
`episodic.api.runtime:create_app_from_env` as the production factory target and
make sure the container command can run it through Granian. Extend existing
`pytest` and `pytest-bdd` health tests only as needed to prove the domain port
is used and the external contract remains unchanged. Do not change the public
health payload unless a test and documentation update explicitly justify it.

Stage 3 adds the container image. Add `.dockerignore`, `Dockerfile`, and any
small runtime wrapper needed for signal handling. Use a multi-stage Python
build that creates a wheel, installs it into a slim runtime image, creates a
non-root user, exposes port `8080`, and starts Granian with the factory target.
Add a Docker health check that calls `/health/live` on localhost. Add tests or
scripts that validate the Dockerfile's command contract without requiring a
full push to a registry. Add an end-to-end container smoke test if Docker is
available; otherwise document the skip condition clearly.

Stage 4 adds the Helm chart. Create `charts/episodic/Chart.yaml`,
`charts/episodic/values.yaml`, `charts/episodic/values.local.yaml`,
`charts/episodic/values.schema.json`, chart templates, and chart README or
NOTES as appropriate. Include Deployment, Service, ConfigMap, optional Ingress,
optional ExternalSecret, optional PodDisruptionBudget, ServiceAccount, and
helpers. Match Nile Valley's values conventions for `existingSecretName`,
`allowMissingSecret`, `secretEnvFromKeys`, `externalSecret`, `config`, and HTTP
probes. Add snapshot tests with syrupy or stable text snapshots for rendered
Helm manifests where output format stability matters, and run `helm lint` and
`helm template` in validation.

Stage 5 adds local `k3d` orchestration. Add `scripts/local_k8s.py` and a
`scripts/local_k8s/` package modelled on Corbusier's command split:
configuration, validation, `k3d`, Kubernetes helpers, deployment helpers, and
orchestration. Use Cyclopts for the command line. Add Makefile targets
`local-k8s-up`, `local-k8s-down`, `local-k8s-status`, and `local-k8s-logs` that
run the script through `uv`. The `up` command should validate required tools,
create or reuse a named cluster, choose or validate a loopback ingress port,
build and import the local image unless skipped, create the application Secret,
install the Helm chart with local values, wait for readiness, and print a
concise success banner. Unit tests should cover validation helpers, port
selection, command construction, secret decoding, and idempotent
cluster-not-found behaviour. Behavioural or end-to-end tests should cover the
CLI surface and a live preview when required tools are available.

Stage 6 updates documentation and decisions. Add
`docs/local-k3d-preview-design.md` describing the Nile Valley integration,
container design, chart values, local workflow, and operational expectations.
Update `docs/users-guide.md` with service health endpoints, container/runtime
configuration, and local preview commands. Update `docs/developers-guide.md`
with maintainer-facing conventions for chart changes, local-k8s tooling, and
validation. Update the relevant architecture document with the health port and
adapter split. Add an ADR if implementation settles a durable decision such as
the health observation port contract or the chart/Nile Valley values contract.

Stage 7 runs full validation, CodeRabbit review, commits, and push/PR updates.
Run each gate sequentially with `tee`, clear `coderabbit review --agent`
concerns, and commit the milestone. Push `nile-valley-integration` to
`origin/nile-valley-integration`. Update this ExecPlan after each milestone so
the branch history records the actual path taken.

## Concrete steps

All commands run from the repository root:

```plaintext
/home/leynos/.lody/repos/github---leynos---episodic/worktrees/1504541e-1283-45d0-8f23-3255689bb4a2
```

Before implementation, confirm the branch and that this plan is approved:

```bash
git branch --show-current
git status --short
```

Expected branch:

```plaintext
nile-valley-integration
```

For code navigation during implementation, start with:

```bash
leta files | head -n 260
leta grep "Health|Readiness|create_app|create_app_from_env" \
  "episodic/api|tests" -k function,method,class --head 120
```

For the health-port milestone, write or update tests first:

```bash
UV_ENV="PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools"
$UV_ENV uv run pytest tests/test_health_endpoints.py -v \
  | tee /tmp/health-tests-episodic-nile-valley-integration.out
```

For the Falcon/Granian behavioural milestone:

```bash
UV_ENV="PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools"
$UV_ENV uv run pytest tests/test_http_service_scaffold.py -v \
  | tee /tmp/http-bdd-episodic-nile-valley-integration.out
```

For chart rendering and linting, add Makefile helpers where appropriate and run
the underlying commands directly while the helpers are still being developed:

```bash
helm lint charts/episodic \
  | tee /tmp/helm-lint-episodic-nile-valley-integration.out
helm template episodic charts/episodic --values charts/episodic/values.local.yaml \
  | tee /tmp/helm-template-episodic-nile-valley-integration.out
```

For local preview smoke testing with the default Docker plus `k3d` path:

```bash
make local-k8s-up | tee /tmp/local-k8s-up-episodic-nile-valley-integration.out
make local-k8s-status | tee /tmp/local-k8s-status-episodic-nile-valley-integration.out
make local-k8s-logs | tee /tmp/local-k8s-logs-episodic-nile-valley-integration.out
make local-k8s-down | tee /tmp/local-k8s-down-episodic-nile-valley-integration.out
```

For the validated rootless Podman plus kind path on this host:

```bash
make local-k8s-up LOCAL_K8S_ENGINE=podman LOCAL_K8S_PROVIDER=kind \
  | tee /tmp/local-k8s-up-kind-podman-episodic-nile-valley-integration.out
make local-k8s-status LOCAL_K8S_ENGINE=podman LOCAL_K8S_PROVIDER=kind \
  | tee /tmp/local-k8s-status-kind-podman-episodic-nile-valley-integration.out
make local-k8s-logs LOCAL_K8S_ENGINE=podman LOCAL_K8S_PROVIDER=kind \
  | tee /tmp/local-k8s-logs-kind-podman-episodic-nile-valley-integration.out
make local-k8s-down LOCAL_K8S_ENGINE=podman LOCAL_K8S_PROVIDER=kind \
  | tee /tmp/local-k8s-down-kind-podman-episodic-nile-valley-integration.out
```

For required final validation, run these sequentially:

```bash
make check-fmt | tee /tmp/check-fmt-episodic-nile-valley-integration.out
make typecheck | tee /tmp/typecheck-episodic-nile-valley-integration.out
make lint | tee /tmp/lint-episodic-nile-valley-integration.out
make test | tee /tmp/test-episodic-nile-valley-integration.out
make markdownlint | tee /tmp/markdownlint-episodic-nile-valley-integration.out
make nixie | tee /tmp/nixie-episodic-nile-valley-integration.out
```

After each major milestone:

```bash
coderabbit review --agent
git status --short
git diff --check
```

Use file-based commit messages:

```bash
COMMIT_MSG_DIR=$(mktemp -d)
cat > "$COMMIT_MSG_DIR/COMMIT_MSG.md" << 'ENDOFMSG'
Implement <milestone summary>

Explain what changed and why in wrapped Markdown prose.
ENDOFMSG
git commit -F "$COMMIT_MSG_DIR/COMMIT_MSG.md"
rm -rf "$COMMIT_MSG_DIR"
```

## Validation and acceptance

The feature is accepted when all of the following are true:

- `GET /health/live` returns HTTP `200` with the existing liveness payload.
- `GET /health/ready` returns HTTP `200` when all configured observations are
  healthy and HTTP `503` when any configured observation fails.
- Health semantics are represented by a domain-owned port and adapted by the
  Falcon HTTP layer without framework imports in domain modules.
- The Docker image builds, runs as a non-root user, exposes port `8080`, starts
  the Granian factory target, and passes its container health check.
- `helm lint charts/episodic` succeeds.
- `helm template episodic charts/episodic --values charts/episodic/values.local.yaml`
  renders Deployment, Service, ConfigMap, optional Ingress, optional
  ExternalSecret, and probe configuration matching the documented values.
- `make local-k8s-up` can create or reuse a local cluster and deploy the chart,
  or skips with a clear documented reason when required CLIs are absent in the
  test environment. Docker plus `k3d` remains the default; rootless Podman
  hosts can use kind through `LOCAL_K8S_ENGINE=podman LOCAL_K8S_PROVIDER=kind`.
- The local preview success banner includes the preview URL, health URL, status
  command, logs command, and teardown command.
- Unit tests cover the health port, health aggregation, Falcon adapter
  behaviour, local preview validation helpers, and command construction.
- Behavioural tests cover the live Granian health contract and the local
  preview CLI surface. Any behavioural test that invokes inference uses Vidai
  Mock.
- Snapshot tests cover rendered output where the exact manifest or CLI output
  shape is part of the contract.
- Property tests or CrossHair checks cover any newly introduced input
  invariants that range over names, ports, secret mappings, or health
  observations.
- `make check-fmt`, `make typecheck`, `make lint`, and `make test` all
  succeed.
- Documentation and ADR updates describe the user-visible behaviour,
  maintainer-facing practices, and durable design decisions.
- `coderabbit review --agent` has no unresolved concerns for the completed
  milestone.

## Idempotence and recovery

The local-k8s commands must be safe to repeat. `local-k8s-up` should reuse an
existing cluster when its ingress port matches the requested configuration, and
it should fail clearly when the requested port conflicts with the existing
cluster. `local-k8s-down` should return success when the target cluster is
already absent. `local-k8s-status` and `local-k8s-logs` should report a missing
cluster or namespace without mutating unrelated resources.

The preview tooling must operate only on the configured cluster name,
namespace, Helm release, and image tag. It must not delete unnamed clusters,
prune Docker globally, or modify unrelated Kubernetes namespaces.

If Helm install fails after creating a cluster, rerun `make local-k8s-status`
and inspect `/tmp/local-k8s-up-episodic-nile-valley-integration.out`. Fix the
chart or runtime issue, then rerun `make local-k8s-up`. Use
`make local-k8s-down` only to remove the configured local preview cluster.

If a quality gate fails after formatting or docs changes, update this ExecPlan
with the failure and remediation before continuing. If a tolerance threshold is
hit, stop implementation and ask for direction.

## Artefacts and notes

Primary project files to inspect before implementation:

- `episodic/api/app.py`
- `episodic/api/runtime.py`
- `episodic/api/dependencies.py`
- `episodic/api/resources/health.py`
- `episodic/architecture/policy.py`
- `tests/test_health_endpoints.py`
- `tests/test_env_runtime_wiring.py`
- `tests/test_http_service_scaffold.py`
- `tests/steps/test_http_service_scaffold_steps.py`
- `Makefile`
- `pyproject.toml`
- `docs/adr/adr-002-http-service-composition-root.md`
- `docs/adr/adr-014-hexagonal-architecture-enforcement.md`

Prior-art files reviewed during planning:

- Corbusier `Dockerfile`
- Corbusier `charts/corbusier/values.yaml`
- Corbusier `charts/corbusier/templates/deployment.yaml`
- Corbusier `charts/corbusier/templates/externalsecret.yaml`
- Corbusier `scripts/local_k8s.py`
- Corbusier `scripts/local_k8s/orchestration.py`
- Corbusier `scripts/local_k8s/deployment.py`
- Corbusier `scripts/local_k8s/validation.py`
- Ghillie `Dockerfile`

Firecrawl sources used during planning:

- <https://github.com/leynos/nile-valley>
- <https://raw.githubusercontent.com/leynos/nile-valley/main/deploy/charts/example-app/values.yaml>
- <https://k3d.io/stable/usage/commands/k3d_cluster_create/>
- <https://helm.sh/docs/topics/charts/>
- <https://cyclopts.readthedocs.io/en/latest/>

## Interfaces and dependencies

The health domain port should be small and transport-free. The exact names may
be adjusted during implementation, but the final public shape should be close
to:

```python
import collections.abc as cabc
import dataclasses as dc
import enum


class HealthStatus(enum.StrEnum):
    OK = "ok"
    ERROR = "error"


@dc.dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    status: HealthStatus


class HealthObserver(cabc.Protocol):
    async def observe(self) -> tuple[HealthCheck, ...]:
        """Return current health checks without transport-specific metadata."""
```

The Falcon adapter should remain responsible for mapping this transport-free
state to the existing JSON contract:

```json
{
  "status": "ok",
  "checks": [
    {
      "name": "database",
      "status": "ok"
    }
  ]
}
```

The Docker runtime command should be equivalent to:

```bash
granian episodic.api.runtime:create_app_from_env \
  --interface asgi \
  --factory \
  --host 0.0.0.0 \
  --port 8080
```

The Helm chart should expose these value groups:

```yaml
image: {}
service: {}
ingress: {}
config: {}
existingSecretName: ""
allowMissingSecret: true
secretEnvFromKeys: {}
externalSecret:
  enabled: false
container:
  livenessProbe:
    httpGet:
      path: /health/live
      port: http
  readinessProbe:
    httpGet:
      path: /health/ready
      port: http
```

The local preview CLI should expose these commands:

```bash
uv run scripts/local_k8s.py up
uv run scripts/local_k8s.py down
uv run scripts/local_k8s.py status
uv run scripts/local_k8s.py logs
```

The Python dependency plan is:

- Add `cyclopts` for local preview command parsing.
- Reuse the standard library and small internal helpers for subprocess
  validation where possible.
- Do not add Kubernetes Python client dependencies unless shelling out to
  `kubectl`, `helm`, and `k3d` proves insufficient.

## Revision note

Initial draft created from local Episodic inspection, Wyvern agent findings,
Corbusier and Ghillie prior art, and Firecrawl-verified Nile Valley, Helm,
`k3d`, and Cyclopts documentation. The remaining work is approval, followed by
milestone-by-milestone implementation with this plan kept current.
