# Integrate Episodic with Nile Valley previews

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: IN PROGRESS. The user explicitly approved implementation on
2026-05-21 after reviewing the draft plan and asked Codex to proceed while
keeping this ExecPlan current.

## Purpose and big picture

This work makes Episodic deployable through the Nile Valley preview and GitOps
workflow. After implementation, an operator can build a production-style
container image, install Episodic through a Helm chart, and bring up a local
`k3d` preview environment with one Makefile command. Kubernetes liveness and
readiness probes can observe the service through stable HTTP endpoints, and the
local preview path exercises the same chart shape expected by Nile Valley.

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
  `existingSecretName`,
  `secretEnvFromKeys`, `allowMissingSecret`, optional `externalSecret`,
  optional ingress, configurable non-secret `config`, and health probe values.
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
  py-pglite fixture setup timeouts and one migration BDD timeout, while all
  new health tests passed. Evidence:
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
  `/tmp/nixie-stage1-episodic-nile-valley-integration.out`. Impact: Stage 1
  is ready for CodeRabbit review and commit.

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
  `/tmp/test-stage1-commit-episodic-nile-valley-integration.out`, which
  reported `670 passed, 3 skipped`. Impact: Stage 1 is ready for final
  Markdown gates, CodeRabbit review, and commit.

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
  `/tmp/coderabbit-stage2-episodic-nile-valley-integration.out`, which
  reported `findings: 0`. Impact: Stage 2 is ready to commit.

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
  `/tmp/container-stage3-focused-episodic-nile-valley-integration.out`.
  Impact: validated the image contract by parsing `Dockerfile`, checking the
  runtime constants, and running `uv build --wheel --out-dir
  /tmp/episodic-stage3-dist` successfully in
  `/tmp/uv-build-stage3-episodic-nile-valley-integration.out`; the live Docker
  smoke can be exercised later with `EPISODIC_RUN_DOCKER_TESTS=1`.

- Observation: Stage 3 full validation passed after formatting and lint
  cleanup. Evidence:
  `/tmp/check-fmt-stage3-rerun2-episodic-nile-valley-integration.out`,
  `/tmp/typecheck-stage3-rerun-episodic-nile-valley-integration.out`,
  `/tmp/lint-stage3-rerun-episodic-nile-valley-integration.out`,
  `/tmp/test-stage3-episodic-nile-valley-integration.out`, which reported
  `675 passed, 4 skipped`,
  `/tmp/markdownlint-stage3-episodic-nile-valley-integration.out`,
  `/tmp/nixie-stage3-episodic-nile-valley-integration.out`, and
  `/tmp/coderabbit-stage3-episodic-nile-valley-integration.out`, which
  reported `findings: 0`. Impact: Stage 3 is ready to commit.

- Observation: the initial Stage 4 chart lint and render checks passed, and the
  focused Helm chart tests generated one syrupy snapshot. Evidence:
  `/tmp/helm-lint-stage4-initial-episodic-nile-valley-integration.out`,
  `/tmp/helm-template-stage4-initial-episodic-nile-valley-integration.out`,
  `/tmp/helm-stage4-tests-update-episodic-nile-valley-integration.out`, and
  `/tmp/helm-stage4-tests-episodic-nile-valley-integration.out`. Impact:
  chart structure and local manifest snapshot are ready for full gates.

- Observation: the first Stage 4 formatting gate failed because
  `tests/test_helm_chart_contract.py` needed Ruff formatting. Evidence:
  `/tmp/check-fmt-stage4-episodic-nile-valley-integration.out`. Impact:
  formatted the Helm chart test before continuing with Stage 4 gates.

- Observation: the first Stage 4 lint gate failed because the Helm snapshot
  test imported `SnapshotAssertion` at runtime and had one long assertion
  message. Evidence: `/tmp/lint-stage4-episodic-nile-valley-integration.out`.
  Impact: moved the snapshot assertion import under `TYPE_CHECKING` and
  wrapped the Helm failure message before rerunning gates.

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
  polish concerns: standardise `secretEnvFromKeys`, document secret-name
  resolution priority, add a pod version label, fail clearly for enabled PDBs
  without a constraint, and tighten ingress schema validation. Evidence:
  `/tmp/coderabbit-stage4-rerun-episodic-nile-valley-integration.out`.
  Impact: implemented all five before the final Stage 4 validation pass.

- Observation: the final Stage 4 CodeRabbit pass still found four small
  validation concerns: demonstrate `allowMissingSecret` fallback in default
  `secretEnvFromKeys`, require root schema keys, parse `helm lint` JSON in
  tests, and enforce PDB mutual exclusivity. Evidence:
  `/tmp/coderabbit-stage4-final-episodic-nile-valley-integration.out`.
  Impact: applied all four changes before rerunning focused Helm tests.

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
  `/tmp/coderabbit-stage4-final2-episodic-nile-valley-integration.out`.
  Impact: clarified the narrow `subprocess.run` suppression and expanded the
  probe schema for HTTP headers, TCP host, gRPC probes, and probe-level
  termination grace period.

- Observation: the next Stage 4 CodeRabbit pass found four more small chart
  polish requests: conditionally render optional probe/resource blocks, clarify
  README wording, avoid contradictory PDB defaults, and make the probe schema
  strict at the top level. Evidence:
  `/tmp/coderabbit-stage4-final3-episodic-nile-valley-integration.out`.
  Impact: applied all four changes before rerunning Helm chart validation.

- Observation: the following Stage 4 CodeRabbit pass found only documentation
  and schema consistency issues: clarify the secret-name helper comment, wrap
  the chart README, and make probe handler schemas strict in the same way as
  the top-level probe schema. Evidence:
  `/tmp/coderabbit-stage4-final4-episodic-nile-valley-integration.out`.
  Impact: applied those fixes and reran the focused Helm chart tests, which
  passed with `4 passed` and one accepted snapshot in
  `/tmp/helm-stage4-tests-final4-rerun-episodic-nile-valley-integration.out`.

- Observation: the next Stage 4 CodeRabbit pass found three minor chart
  concerns: keep README wrapping in the exact requested shape and make the
  default `DATABASE_URL` secret key explicitly required even though
  `allowMissingSecret` remains available as a fallback for entries that omit
  `optional`. Evidence:
  `/tmp/coderabbit-stage4-final5-episodic-nile-valley-integration.out`.
  Impact: wrapped the README, set `secretEnvFromKeys.DATABASE_URL.optional` to
  `false`, and reran the focused Helm chart tests with snapshot update in
  `/tmp/helm-stage4-tests-final5-update-episodic-nile-valley-integration.out`.

- Observation: the final Stage 4 CodeRabbit rerun found that the values schema
  did not yet cover every value group consumed by chart templates, and asked
  either for mandatory probes or fallback probe rendering. Evidence:
  `/tmp/coderabbit-stage4-final6-episodic-nile-valley-integration.out`.
  Impact: extended `values.schema.json` for service accounts, pod labels and
  annotations, security contexts, service, resources, PDBs, scheduling values,
  name overrides, and image pull secrets; made container liveness and readiness
  probes mandatory in schema; then reran focused Helm tests in
  `/tmp/helm-stage4-tests-final6-rerun-episodic-nile-valley-integration.out`.

- Observation: the next Stage 4 CodeRabbit rerun found a real Helm template
  bug: `default` treats explicit `false` as empty, so
  `secretEnvFromKeys.*.optional: false` could be overridden by
  `allowMissingSecret: true`. Evidence:
  `/tmp/coderabbit-stage4-final7-episodic-nile-valley-integration.out`.
  Impact: replaced the `default` call with a `hasKey` conditional and added a
  focused Helm test proving an explicit required secret remains
  `optional: false` when the fallback allows missing secrets; the focused chart
  test suite passed with `5 passed` in
  `/tmp/helm-stage4-tests-final7-rerun-episodic-nile-valley-integration.out`.

- Observation: the following Stage 4 CodeRabbit rerun found only readability
  cleanup in the deployment template: use pipe-form `default` for image tag
  fallback and remove unnecessary whitespace-control markers from the optional
  secret conditional. Evidence:
  `/tmp/coderabbit-stage4-final8-episodic-nile-valley-integration.out`.
  Impact: applied both template cleanups and reran focused Helm chart tests
  with `5 passed` in
  `/tmp/helm-stage4-tests-final8-rerun-episodic-nile-valley-integration.out`.

- Observation: Stage 4 final validation passed after the last Helm template
  cleanup. Evidence:
  `/tmp/check-fmt-stage4-final9-episodic-nile-valley-integration.out`,
  `/tmp/typecheck-stage4-final9-episodic-nile-valley-integration.out`,
  `/tmp/lint-stage4-final9-episodic-nile-valley-integration.out`,
  `/tmp/markdownlint-stage4-final9-episodic-nile-valley-integration.out`,
  `/tmp/nixie-stage4-final9-episodic-nile-valley-integration.out`,
  `/tmp/test-stage4-final9-episodic-nile-valley-integration.out`, which
  reported `680 passed, 4 skipped`, and
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
  `/tmp/test-stage5-final-episodic-nile-valley-integration.out`, which
  reported `685 passed, 4 skipped`, and
  `/tmp/coderabbit-stage5-final-episodic-nile-valley-integration.out`, which
  reported `findings: 0`. Impact: Stage 5 is ready to commit.

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
  Wildside HTTP runtime entrypoint consistently, and centralising these values
  avoids string drift while keeping the runtime path unchanged.
  Date/Author: 2026-05-21 / Codex.

- Decision: make the live Docker image smoke test opt-in with
  `EPISODIC_RUN_DOCKER_TESTS=1`. Rationale: the repository gates should remain
  deterministic on agent hosts without a Docker daemon, while still providing
  an executable end-to-end image check for environments that can build and run
  containers. Date/Author: 2026-05-21 / Codex.

## Outcomes and retrospective

This section is intentionally empty while the plan is in draft. During
implementation, record each milestone outcome, CodeRabbit review result, gate
result, and any deviation from this plan.

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

Stage 0 is complete. The user explicitly approved implementation on
2026-05-21. Production files, chart files, Docker files, Makefile targets, and
user-facing guides may now change within the tolerances above.

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

For local preview smoke testing:

```bash
make local-k8s-up | tee /tmp/local-k8s-up-episodic-nile-valley-integration.out
make local-k8s-status | tee /tmp/local-k8s-status-episodic-nile-valley-integration.out
make local-k8s-logs | tee /tmp/local-k8s-logs-episodic-nile-valley-integration.out
make local-k8s-down | tee /tmp/local-k8s-down-episodic-nile-valley-integration.out
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
- `make local-k8s-up` can create or reuse a local `k3d` cluster and deploy the
  chart, or skips with a clear documented reason when required CLIs are absent
  in the test environment.
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

## Artifacts and notes

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
