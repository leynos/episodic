# Introduce the `/v1` target API prefix

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`,
and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: COMPLETE

The user approved implementation on 2026-05-20 and asked for the plan to be
kept current as milestones complete.

## Purpose and big picture

Roadmap item `4.1.1` makes `/v1` the target prefix for Episodic's client-facing
representational state transfer (REST) API. After the implementation, clients,
the terminal user interface (TUI), and future source-to-script vertical-slice
endpoints will call canonical resources through `/v1/...` paths. Existing
unversioned canonical API routes are pre-v0.1.0 implementation details and do
not need compatibility preservation.

Success is observable when:

1. `GET /v1/series-profiles`, `POST /v1/series-profiles`,
   `GET /v1/episode-templates`, the reusable-reference endpoints, and the
   binding-resolution endpoints route through the existing Falcon resource
   handlers.
2. The old unversioned canonical API paths return Falcon's normal
   `404 Not Found` response, proving there is no compatibility alias.
3. Operator health checks remain at `GET /health/live` and
   `GET /health/ready`, unless the implementation discovers a documented reason
   to version them.
4. The developers' guide documents version routing, and user-facing endpoint
   examples that describe currently supported API behaviour use `/v1`.
5. The new unit, behavioural, and end-to-end tests fail before the route change
   and pass after the route change.
6. `make check-fmt`, `make typecheck`, `make lint`, `make test`,
   `make markdownlint`, `make nixie`, `make check-migrations`, and
   `coderabbit review --agent` succeed before the implementation is committed.

This work is a routing and contract-alignment change. It does not implement the
future episode, upload, ingestion-job, generation-run, WebSocket, approval,
command-line interface (CLI), or web-console resources described later in phase
4.

## Context and orientation

The active branch for this plan is `4-1-1-introduce-v1-target-api-prefix`.

The canonical Falcon application is assembled in `episodic/api/app.py` by
`create_app()`. That function currently registers health checks and canonical
content routes directly at root paths. `episodic/api/runtime.py` calls
`create_app()` from the Granian composition root without adding a prefix.

The currently implemented canonical API paths are:

- `/series-profiles`
- `/series-profiles/{profile_id}`
- `/series-profiles/{profile_id}/history`
- `/series-profiles/{profile_id}/brief`
- `/series-profiles/{profile_id}/resolved-bindings`
- `/episode-templates`
- `/episode-templates/{template_id}`
- `/episode-templates/{template_id}/history`
- `/series-profiles/{profile_id}/reference-documents`
- `/series-profiles/{profile_id}/reference-documents/{document_id}`
- `/series-profiles/{profile_id}/reference-documents/{document_id}/revisions`
- `/reference-document-revisions/{revision_id}`
- `/reference-bindings`
- `/reference-bindings/{binding_id}`

The target behaviour is to register those canonical content paths under `/v1`.
For example, `/series-profiles` becomes `/v1/series-profiles`, and
`/series-profiles/{profile_id}/brief` becomes
`/v1/series-profiles/{profile_id}/brief`.

Health checks are operator endpoints, not TUI-facing or vertical-slice
resources. Keep `/health/live` and `/health/ready` unversioned so deployment
platforms and readiness probes do not need to know the public API version.

The source documents that govern this work are:

- `docs/roadmap.md`, section `4.1.1`, which requires `/v1` routing and
  developers' guide documentation.
- `docs/episodic-tui-api-design.md`, especially "Current canonical endpoint
  coverage" and "Proposed REST endpoints", which state that the target REST API
  uses `/v1`.
- `docs/adr/adr-009-source-to-script-rest-vertical-slice.md`, which records
  the accepted decision that existing unversioned routes do not need
  preservation before v0.1.0.
- `docs/episodic-podcast-generation-system-design.md`, which links
  architecture decision record (ADR) 009 and already describes the
  source-to-script vertical-slice direction.
- `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md`,
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`, and
  `docs/agentic-systems-with-langgraph-and-celery.md`, which provide the local
  testing and integration background for Falcon, SQLAlchemy, py-pglite,
  LangGraph and Celery.

Use the `leta` skill for semantic code navigation. Use the
`hexagonal-architecture` skill to preserve the rule that the Falcon API layer
is an inbound adapter over domain/application services, not a place for domain
logic or outbound-adapter coupling. Use the `rust-router` skill only if a later
implementation unexpectedly introduces Rust code; this plan does not require
Rust, Verus, Kani or CrossHair changes.

Firecrawl research resolved two external prior-art points. Falcon 4.2 routes
are registered through `app.add_route()` uniform resource identifier (URI)
templates, and unmatched routes fall through to Falcon's normal route-not-found
responder. Microsoft REST API guidance treats REST APIs as resource-oriented
hypertext transfer protocol (HTTP) surfaces, says versioning protects client
compatibility during updates, and recommends `202 Accepted` for long-running
asynchronous operations. These facts support a simple route prefix for the
existing resources and preserve ADR 009's later long-running operation contract
without adding those future endpoints here.

## Constraints

- Do not implement the plan until the user explicitly approves it.
- Keep this task scoped to route prefixing, tests, and documentation for
  already implemented canonical API resources.
- Do not implement future phase-4 resources such as `/v1/episodes`,
  `/v1/uploads`, `/v1/ingestion-jobs`, `/v1/generation-runs`,
  `/v1/voice-previews`, WebSocket streams, CLI commands, approval workflows, or
  web-console flows.
- Preserve health checks at `/health/live` and `/health/ready` unless a
  documented requirement proves they should be versioned.
- Do not preserve compatibility aliases for unversioned canonical API paths.
  The repository is pre-v0.1.0, and ADR 009 deliberately avoids that
  compatibility weight.
- Keep hexagonal architecture boundaries intact. Route registration belongs in
  the inbound Falcon adapter. Domain packages, application services, repository
  ports, SQLAlchemy adapters and large language model (LLM) adapters must not
  learn about HTTP path prefixes.
- Do not introduce a new runtime dependency for this work.
- Use Vidai Mock only for behavioural tests that exercise inference services.
  This route-prefix task should not need Vidai Mock because it does not call an
  `LLMPort`.
- Use property tests only if the implementation introduces a reusable route
  joining or normalisation function with invariants over many path fragments. A
  direct constant prefix does not need Hypothesis.
- Do not mark roadmap item `4.1.1` done in a pre-implementation plan PR.
  Mark it done only after implementation, documentation, gates and review are
  complete.
- Commit only after gates for the current change pass. This planning change is
  documentation-only, so its commit gate is Markdown formatting/linting and
  Mermaid validation, plus any repository-specific checks that prove the docs
  remain healthy.

## Tolerances (exception triggers)

- Scope: stop and escalate if the implementation needs more than 12 production
  files or 900 net lines of non-test code.
- Route behaviour: stop and escalate if any unversioned canonical API path must
  remain live for a client, fixture or deployment dependency.
- Health checks: stop and escalate if tests or deployment documentation show
  that health checks must be available under both root and `/v1` paths.
- Dependencies: stop and escalate before adding any runtime dependency or any
  new test dependency.
- Architecture: stop and escalate if the route-prefix change requires domain,
  application, repository, SQLAlchemy, LLM or worker modules to import from
  `episodic.api`.
- Interface: stop and escalate if resource request or response bodies must
  change to introduce the prefix.
- Tests: stop and escalate after three unsuccessful attempts to stabilise the
  same failing test cluster.
- Ambiguity: stop and present options if there are two materially different
  interpretations of which endpoints are "TUI-facing" after reviewing the
  current code and docs.

## Risks

- Risk: path churn is broad because many tests hard-code unversioned routes.
  Severity: medium. Likelihood: high. Mitigation: introduce or update shared
  test path helpers where that reduces repetition, then update direct tests and
  behaviour-driven development (BDD) steps in one controlled pass.

- Risk: health endpoints could be accidentally moved under `/v1`. Severity:
  medium. Likelihood: medium. Mitigation: add or preserve tests that assert
  `/health/live` and `/health/ready` remain root-level, and add a negative
  assertion for `/v1/health/live` only if the behaviour is stable in Falcon.

- Risk: a route-prefix helper could silently create double slashes or drop
  path parameters. Severity: medium. Likelihood: low. Mitigation: prefer a tiny
  local helper with tests if route registration is refactored; otherwise use
  explicit `/v1/...` literals to avoid hidden path manipulation.

- Risk: behavioural tests may be updated without first proving they fail
  against the old unversioned app. Severity: medium. Likelihood: medium.
  Mitigation: run the targeted API tests after changing tests but before
  changing `episodic/api/app.py`, and record the expected 404 failures in
  `Progress`.

- Risk: documentation could overstate future `/v1` endpoints as implemented.
  Severity: medium. Likelihood: medium. Mitigation: distinguish currently
  implemented `/v1` canonical resources from planned TUI and vertical-slice
  resources in the developers' guide and users' guide.

- Risk: CodeRabbit may report concerns that require design changes. Severity:
  medium. Likelihood: low. Mitigation: run `coderabbit review --agent` after
  the route/test/docs milestone, resolve all actionable concerns, and rerun it
  before moving on.

## Work plan

Begin each milestone by checking the branch and status:

```shell
git branch --show-current
git status --short --branch
```

Use `tee` for long-running gates so truncated terminal output does not hide
failures. The recommended log naming shape is:

```shell
set -o pipefail; make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-$(git branch --show-current).out
```

### Milestone 1: establish the red route-contract tests

Update tests before production code. The goal is to express the new contract
and prove the current app does not satisfy it.

Inspect the existing route tests and fixtures:

```shell
leta show create_app
leta show tests/fixtures/api.py:canonical_api_client
leta show tests/fixtures/api.py:canonical_api_async_client
```

Add or update unit-level route tests in the existing API test area so they
assert:

- each implemented canonical API route is reachable at `/v1/...`;
- the equivalent unversioned canonical path returns `404 Not Found`;
- `/health/live` and `/health/ready` still work at root paths.

Use existing `canonical_api_client` and `canonical_api_async_client` fixtures.
If a shared path helper is introduced for tests, place it near existing API
test support, not in production code.

Update BDD step definitions that exercise canonical API routes so their calls
use `/v1/...`. The most likely files are:

- `tests/steps/test_profile_template_api_steps.py`
- `tests/steps/test_reference_document_api_steps.py`
- `tests/steps/test_binding_resolution_steps.py`
- `tests/steps/test_reference_document_model_steps.py`

Update direct API tests and support helpers as needed:

- `tests/test_profile_template_api.py`
- `tests/test_binding_resolution_api.py`
- `tests/test_reference_document_validation.py`
- `tests/test_reference_document_access.py`
- `tests/test_reference_document_roundtrip.py`
- `tests/test_binding_resolution_brief_endpoint.py`
- `tests/test_reference_document_api_support.py`
- `tests/test_binding_resolution_support.py`

Add syrupy snapshot coverage only where the response shape is contractually
important and not already covered by clear field assertions. Strong candidates
are the structured brief envelope, resolved-binding response, reference
document list envelope, revision envelope, and binding envelope. Do not add
snapshots for volatile identifiers or timestamps unless they are normalised.

Run a focused red test pass:

```shell
set -o pipefail
uv run pytest -q \
  tests/test_profile_template_api.py \
  tests/test_binding_resolution_api.py \
  tests/test_reference_document_validation.py \
  tests/test_reference_document_access.py \
  tests/test_reference_document_roundtrip.py \
  tests/test_binding_resolution_brief_endpoint.py \
  2>&1 | tee /tmp/v1-red-api-tests-episodic-$(git branch --show-current).out
```

Expected result before production changes: assertions that call `/v1/...` fail
with `404 Not Found`, while health checks continue to pass at root paths.
Record the result in `Progress`.

### Milestone 2: prefix existing canonical Falcon routes

Edit `episodic/api/app.py`. Keep `create_app()` as the route factory. Keep
health route registration unchanged:

```python
app.add_route("/health/live", HealthLiveResource())
app.add_route("/health/ready", HealthReadyResource(...))
```

Register every implemented canonical content route under `/v1`. Either use
explicit route strings or a small local helper such as:

```python
def _v1(path: str) -> str:
    return f"/v1{path}"
```

If using a helper, keep it private to `episodic/api/app.py` and add focused
unit coverage for edge cases only if the helper accepts arbitrary input. Do not
move version routing into domain, application or storage modules.

Do not add unversioned aliases. Do not change resource classes, serializers,
request bodies, response bodies or service calls unless a test reveals an
existing bug unrelated to routing. If that happens, record the decision and
consider a separate fix.

Run the focused test pass again:

```shell
set -o pipefail
uv run pytest -q \
  tests/test_profile_template_api.py \
  tests/test_binding_resolution_api.py \
  tests/test_reference_document_validation.py \
  tests/test_reference_document_access.py \
  tests/test_reference_document_roundtrip.py \
  tests/test_binding_resolution_brief_endpoint.py \
  2>&1 | tee /tmp/v1-green-api-tests-episodic-$(git branch --show-current).out
```

Expected result: the new `/v1` assertions pass, unversioned canonical routes
return `404`, and health checks remain available at root paths.

### Milestone 3: align behavioural and runtime coverage

Run the API BDD scenarios that use Falcon route paths:

```shell
set -o pipefail
uv run pytest -q \
  tests/steps/test_profile_template_api_steps.py \
  tests/steps/test_reference_document_api_steps.py \
  tests/steps/test_binding_resolution_steps.py \
  tests/steps/test_reference_document_model_steps.py \
  2>&1 | tee /tmp/v1-bdd-api-tests-episodic-$(git branch --show-current).out
```

Run runtime health coverage to prove Granian/Falcon health behaviour remains
root-level:

```shell
set -o pipefail
uv run pytest -q \
  tests/test_health_endpoints.py \
  tests/test_env_runtime_wiring.py \
  tests/steps/test_http_service_scaffold_steps.py \
  2>&1 | tee /tmp/v1-runtime-tests-episodic-$(git branch --show-current).out
```

If a live Granian BDD test is already covered by `make test`, do not duplicate
long process tests unless local evidence is needed to debug a failure.

### Milestone 4: update documentation

Update `docs/developers-guide.md` with a "Versioned API routing" section near
the Falcon HTTP runtime guidance. It must state:

- `/v1` is the target prefix for client-facing canonical API resources.
- Existing unversioned canonical routes are pre-v0.1.0 implementation details
  and are not compatibility aliases.
- Health checks remain root-level operator endpoints.
- New TUI-facing and vertical-slice endpoints must be registered under `/v1`.
- The decision is aligned with ADR 009 and
  `docs/episodic-tui-api-design.md`.

Update any accepted-ADR or design-reference list in `docs/developers-guide.md`
to include ADR 009 if the guide has such a list.

Update `docs/users-guide.md` so examples for currently implemented API
behaviour use `/v1/...` paths. Be careful not to imply that future phase-4
resources are already implemented.

Update `docs/episodic-podcast-generation-system-design.md` or
`docs/episodic-tui-api-design.md` only if the implementation discovers a
substantive design decision not already captured. Otherwise, leave those design
documents unchanged because they already identify `/v1` as the target.

Do not mark `docs/roadmap.md` item `4.1.1` complete until the implementation,
documentation and gates have passed. At the end of the approved implementation
branch, change:

```markdown
- [ ] 4.1.1. Introduce `/v1` as the target API prefix.
```

to:

```markdown
- [x] 4.1.1. Introduce `/v1` as the target API prefix.
```

### Milestone 5: run gates and review

Run formatting first:

```shell
set -o pipefail; make fmt 2>&1 | tee /tmp/fmt-episodic-$(git branch --show-current).out
```

Then run gates sequentially:

```shell
set -o pipefail; mbake validate Makefile 2>&1 | tee /tmp/mbake-episodic-$(git branch --show-current).out
set -o pipefail; make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-$(git branch --show-current).out
set -o pipefail; PATH=/root/.bun/bin:$PATH make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-$(git branch --show-current).out
set -o pipefail; make nixie 2>&1 | tee /tmp/nixie-episodic-$(git branch --show-current).out
set -o pipefail; make build 2>&1 | tee /tmp/build-episodic-$(git branch --show-current).out
set -o pipefail; make lint 2>&1 | tee /tmp/lint-episodic-$(git branch --show-current).out
set -o pipefail; make typecheck 2>&1 | tee /tmp/typecheck-episodic-$(git branch --show-current).out
set -o pipefail; make test 2>&1 | tee /tmp/test-episodic-$(git branch --show-current).out
set -o pipefail; make check-migrations 2>&1 | tee /tmp/check-migrations-episodic-$(git branch --show-current).out
set -o pipefail; coderabbit doctor 2>&1 | tee /tmp/coderabbit-doctor-episodic-$(git branch --show-current).out
set -o pipefail; coderabbit review --agent 2>&1 | tee /tmp/coderabbit-review-episodic-$(git branch --show-current).out
```

Clear every actionable CodeRabbit concern before proceeding. If CodeRabbit
raises a concern that conflicts with this plan, record the conflict in
`Decision Log` and ask for direction.

After all gates pass, commit with a file-based commit message. Do not use
`git commit -m`.

## Validation and expected evidence

For the approved implementation, the minimum final validation evidence is:

- Focused route tests show `/v1` canonical resources pass and unversioned
  canonical resources return `404`.
- API BDD scenarios pass with `/v1` paths.
- Runtime health tests pass at root health paths.
- `mbake validate Makefile` passes.
- `make check-fmt` passes.
- `make markdownlint` passes.
- `make nixie` passes.
- `make build` passes.
- `make lint` passes.
- `make typecheck` passes.
- `make test` passes.
- `make check-migrations` passes.
- `coderabbit doctor` passes.
- `coderabbit review --agent` reports no unresolved actionable concerns.

The final implementation should include short transcripts in this plan's
`Progress` section, for example:

```plaintext
2026-05-19T10:20:00+02:00: `make test` passed. Log:
`/tmp/test-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
```

## Progress

- [x] 2026-05-19T00:56:00+02:00: Loaded `leta`,
  `hexagonal-architecture`, `execplans`, `firecrawl`, `commit-message`,
  `pr-creation`, and `en-gb-oxendict-style` skills for planning, research,
  branch, commit and PR work.
- [x] 2026-05-19T00:56:00+02:00: Created a `leta` workspace for the current
  repository.
- [x] 2026-05-19T00:56:00+02:00: Renamed the local branch from
  `feat/v1apiexecplan` to `4-1-1-introduce-v1-target-api-prefix`.
- [x] 2026-05-19T00:56:00+02:00: Created context pack `pk_p7rbuu6y` for the
  Wyvern planning team.
- [x] 2026-05-19T01:02:00+02:00: Gathered Wyvern findings for documentation
  scope, route/test scope and PR/readiness constraints.
- [x] 2026-05-19T01:04:00+02:00: Used Firecrawl to confirm Falcon route
  registration behaviour and REST API versioning prior art.
- [x] 2026-05-19T01:07:00+02:00: Drafted this pre-implementation ExecPlan.
- [x] 2026-05-20T13:34:49+02:00: User approved implementation and asked for
  this ExecPlan to be kept current with decisions, findings, observations and
  progress.
- [x] 2026-05-20T13:38:00+02:00: Updated the focused API tests and shared
  test helpers to call `/v1/...` canonical paths before changing production
  routing. The focused red run failed as expected with 28 failures and one pass
  because `/v1/series-profiles` returned Falcon `404 Not Found`. Log:
  `/tmp/v1-red-api-tests-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T13:43:00+02:00: Prefixed canonical Falcon API route
  registrations in `episodic/api/app.py` under `/v1`, leaving `/health/live` and
  `/health/ready` unchanged at the root.
- [x] 2026-05-20T13:45:00+02:00: Added explicit route-versioning contract
  coverage in `tests/test_api_route_versioning.py` for unversioned canonical
  route `404` responses and for `/v1/health/live` remaining unregistered.
- [x] 2026-05-20T13:46:00+02:00: Re-ran the focused API test pass with the
  route table changed. Result: 44 passed in 94.21 seconds. Log:
  `/tmp/v1-green-api-tests-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T13:51:00+02:00: Addressed CodeRabbit's route-versioning
  coverage concerns by adding positive `/v1` route-registration assertions and
  positive root health assertions. `tests/test_api_route_versioning.py` passed
  with 31 tests in 67.21 seconds. Log:
  `/tmp/v1-route-versioning-tests-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T13:57:00+02:00: Re-ran `coderabbit review --agent` after
  the route and test milestone. Result: `review_completed` with zero findings.
  Log:
  `/tmp/coderabbit-review-after-route-coverage-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T13:59:00+02:00: Ran API BDD step-module coverage after
  updating the step paths to `/v1`. Result: 4 passed in 8.76 seconds. Log:
  `/tmp/v1-bdd-api-tests-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T13:59:00+02:00: Ran runtime health and HTTP scaffold
  coverage. Result: 10 passed and 1 skipped in 8.40 seconds, with health
  endpoints still root-level. Log:
  `/tmp/v1-runtime-tests-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] Update API BDD steps and direct API tests to use `/v1`.
- [x] 2026-05-20T14:13:00+02:00: Re-ran `coderabbit review --agent` after
  clearing readability concerns in `tests/test_api_route_versioning.py`. Result:
  `review_completed` with zero findings. Log:
  `/tmp/coderabbit-review-after-test-readability-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T14:14:00+02:00: Updated `docs/developers-guide.md` with
  versioned API routing guidance, added ADR 009 to the accepted-design list,
  and updated currently implemented endpoint examples in
  `docs/developers-guide.md` and `docs/users-guide.md` to use `/v1`.
- [x] 2026-05-20T14:32:00+02:00: Cleared CodeRabbit's documentation and test
  readability concerns. The latest `coderabbit review --agent` completed with
  zero findings. Log:
  `/tmp/coderabbit-review-after-route-docstring-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] Update developers' guide and users' guide.
- [x] 2026-05-20T14:34:00+02:00: Marked roadmap item `4.1.1` done after
  implementation, focused tests, documentation updates, and milestone
  CodeRabbit reviews completed.
- [x] 2026-05-20T14:36:00+02:00: Ran `make fmt`. Result: passed. The command
  attempted unrelated Markdown wrapping in older documents; that unrelated
  formatter churn was reverted, leaving only task-scoped files changed. Log:
  `/tmp/fmt-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T14:38:00+02:00: Ran `mbake validate Makefile`,
  `make check-fmt`, `make markdownlint`, `make nixie`, and `make build`.
  Results: all passed. Logs:
  `/tmp/mbake-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  `/tmp/check-fmt-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  `/tmp/markdownlint-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  `/tmp/nixie-episodic-4-1-1-introduce-v1-target-api-prefix.out`, and
  `/tmp/build-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T14:42:00+02:00: Ran `make lint`. The first run found two
  issues in the new route-versioning test file. After moving the Falcon
  `testing` import under `TYPE_CHECKING` and making string concatenation
  explicit, the rerun passed. Log:
  `/tmp/lint-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T14:43:00+02:00: Ran `make typecheck`. Result: passed. Log:
  `/tmp/typecheck-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T14:50:00+02:00: Ran `make test`. Result: 662 passed and
  3 skipped in 325.31 seconds. Log:
  `/tmp/test-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T14:56:00+02:00: Ran `make check-migrations`. Result:
  passed. Log:
  `/tmp/check-migrations-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T14:57:00+02:00: Ran `coderabbit doctor`. Result: 9 passed,
  0 warnings, 0 failed. Log:
  `/tmp/coderabbit-doctor-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-20T15:03:49+02:00: Ran final `coderabbit review --agent`.
  It first requested removal of the redundant Python 3.14 future import from
  `tests/test_api_route_versioning.py`; after removal and a successful
  `make lint` rerun, the final review completed with zero findings. Log:
  `/tmp/coderabbit-review-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] Run focused tests, full gates and CodeRabbit review.
- [x] Mark roadmap item `4.1.1` done after implementation and gates pass.
- [x] 2026-05-22T19:05:00+02:00: Verified CodeRabbit follow-up findings with
  Wyvern and scribe agents. Still-valid issues were limited to brittle
  route-registration assertions, missing negative coverage for
  `/v1/health/ready`, missing unversioned write-route coverage, one stale
  user-guide route example, and first-use acronym definitions in this ExecPlan.
- [x] 2026-05-22T19:31:00+02:00: Addressed the still-valid follow-up findings
  by narrowing route-versioning coverage to representative route families,
  asserting route registration as non-`404`, adding `/v1/health/ready` and
  unversioned write-route negative coverage, and fixing the stale documentation
  examples. `tests/test_api_route_versioning.py` passed with 8 tests. Log:
  `/tmp/route-versioning-review-fixes-final-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-22T19:58:00+02:00: Re-ran validation after the follow-up fixes.
  `make check-fmt`, `make markdownlint`, `make nixie`, `make typecheck`, and
  `make lint` passed. `make test` passed with 669 tests and 3 skipped. Logs:
  `/tmp/check-fmt-review-fixes-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  `/tmp/markdownlint-review-fixes-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  `/tmp/nixie-review-fixes-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  `/tmp/typecheck-review-fixes-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  `/tmp/lint-review-fixes-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  and
  `/tmp/test-review-fixes-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-22T20:03:00+02:00: Ran
  `coderabbit review --agent` after the follow-up fixes. Result:
  `review_completed` with zero findings. Log:
  `/tmp/coderabbit-review-followup-fixes-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-22T21:17:00+02:00: Verified the latest failed-check findings
  with Wyvern and scribe agents. The `/v1/health/ready` and users-guide path
  findings were stale. The still-valid issues were route contract tests relying
  only on status codes and remaining first-use acronym expansions in this
  ExecPlan. Added response payload assertions to
  `tests/test_api_route_versioning.py` and expanded the remaining acronyms.
  `tests/test_api_route_versioning.py` passed with 8 tests. Log:
  `/tmp/route-versioning-contract-behaviour-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-22T21:28:00+02:00: Ran follow-up gates for the contract
  behaviour assertions. `make check-fmt`, `make markdownlint`,
  `make typecheck`, and `make lint` passed. `make test` reached the updated
  route-versioning tests successfully, then failed later in
  `tests/test_guest_bios_properties.py::test_enriched_guest_bios_preserves_entry_order`
  because Hypothesis generated the XML-forbidden character `U+FFFE` in an
  unrelated guest biography payload. The single-test rerun reproduced the same
  failure. Logs:
  `/tmp/check-fmt-contract-behaviour-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  `/tmp/markdownlint-contract-behaviour-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  `/tmp/typecheck-contract-behaviour-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  `/tmp/lint-contract-behaviour-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  `/tmp/test-contract-behaviour-episodic-4-1-1-introduce-v1-target-api-prefix.out`,
  and
  `/tmp/guest-bios-property-validation-failure-episodic-4-1-1-introduce-v1-target-api-prefix.out`.
- [x] 2026-05-22T21:31:00+02:00: Attempted
  `coderabbit review --agent` after the contract behaviour fixes. CodeRabbit
  returned a recoverable rate-limit error before review analysis began. Log:
  `/tmp/coderabbit-review-contract-behaviour-episodic-4-1-1-introduce-v1-target-api-prefix.out`.

## Surprises and discoveries

- `docs/episodic-tui-api-design.md` and ADR 009 already describe `/v1` as the
  target API, but `docs/developers-guide.md` and `docs/users-guide.md` still
  contain unversioned examples for currently implemented canonical endpoints.
- The Falcon route table is centralised in `episodic/api/app.py`; no separate
  route grouping abstraction currently exists.
- Existing API tests and BDD step files hard-code many route paths, so the
  implementation will be mostly coordinated test and documentation churn plus a
  small production route-table change.
- CodeRabbit CLI is available in this environment, and `coderabbit doctor`
  was reported healthy by the Wyvern planning team.

## Decision Log

- 2026-05-19: Keep health endpoints unversioned. Rationale: roadmap item
  `4.1.1` covers TUI-facing and vertical-slice endpoints, while health checks
  are operator endpoints documented for runtime readiness and liveness.
- 2026-05-19: Do not preserve unversioned canonical API aliases. Rationale:
  ADR 009 and the TUI API design explicitly state that existing unversioned
  routes are pre-v0.1.0 implementation details with no compatibility obligation.
- 2026-05-19: Do not use Vidai Mock for this route-prefix implementation.
  Rationale: the change does not exercise inference services. Existing
  inference-backed behavioural tests continue to use Vidai Mock where relevant.
- 2026-05-19: Do not mark roadmap item `4.1.1` done in this plan-only branch.
  Rationale: the roadmap checkbox should reflect delivered implementation, not
  pre-implementation planning.

## Outcomes and retrospective

The implementation shipped the `/v1` target prefix for the existing canonical
Falcon API resources without adding unversioned compatibility aliases. Root
health checks remain available at `/health/live` and `/health/ready`, while
`/v1/health/live` returns `404`.

The route-prefix approach stayed inside the planned inbound-adapter boundary:
production changes were limited to Falcon route registration and docstring
examples in the API adapter package. Domain, application, repository,
SQLAlchemy, LLM, and worker modules did not learn about HTTP path prefixes.

The work updated direct API tests, shared API fixtures, BDD step modules,
developer and user documentation, and the roadmap checkbox. Full repository
gates passed, and CodeRabbit review completed with zero findings after
addressing its test coverage and readability suggestions.
