# Scaffold Falcon HTTP services on Granian

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: COMPLETE

## Purpose and big picture

Roadmap item `1.5.1` is the missing transport-runtime scaffold for the
canonical-content API. Falcon 4.2.x is already present and the current code
serves profile, template, and reusable-reference routes from
`episodic/api/app.py`, but the service still lacks three pieces required by the
roadmap and the system design:

1. health endpoints that can be used by operators and deployment platforms,
2. a typed composition root for injecting port adapters into the HTTP layer,
   and
3. a Granian runtime entrypoint that can boot the Falcon ASGI application in a
   production-style process.

After this work, a developer or operator will be able to start the service
through Granian, call liveness and readiness endpoints, and extend the HTTP
layer by supplying port adapters through an explicit dependency object rather
than by importing adapter implementations directly into resources. This keeps
the inbound HTTP adapter aligned with the hexagonal boundary rules in
`docs/episodic-podcast-generation-system-design.md`.

Success is observable in eight ways:

1. `episodic/api/app.py` still builds the Falcon ASGI application, but now
   does so from a typed dependency object rather than a lone `uow_factory`
   callable.
2. `GET /health/live` returns `200 OK` whenever the Falcon application has
   booted successfully.
3. `GET /health/ready` returns `200 OK` when the configured readiness probes
   pass and `503 Service Unavailable` when a configured probe fails.
4. Existing canonical API routes still work through the new composition root.
5. Granian can boot the application via a documented factory target.
6. Unit and integration tests written with `pytest` fail first and then pass
   for dependency wiring, health resources, and runtime configuration.
7. Behavioural tests written with `pytest-bdd` start a real Granian process
   and verify the health endpoints over HTTP.
8. Documentation, an Architecture Decision Record (ADR), and
   `docs/roadmap.md` are updated only after all quality gates are green.

## Constraints

- Preserve the hexagonal architecture invariants from the
  `hexagonal-architecture` skill:
  - domain modules must not import Falcon, Granian, SQLAlchemy engine
    construction, or other transport/runtime concerns;
  - ports remain owned by the domain or application layer;
  - inbound adapters depend on ports, never on concrete outbound adapters; and
  - outbound adapters do not call inbound adapters directly.
- Keep `episodic/api/app.py` as a Falcon application factory, not as an
  environment-parsing or engine-construction module. Runtime assembly belongs
  in a separate composition-root module.
- Preserve existing route contracts for series profiles, episode templates,
  reusable reference documents, and bindings. This task is scaffolding, not an
  API redesign.
- Make the dependency-injection seam explicit and typed. Avoid untyped
  `dict[str, object]` service registries or module-level globals.
- Health endpoints must remain infrastructural. They must not perform domain
  mutations or embed business logic.
- Use test-first workflow for each stage: add or update tests first, confirm
  they fail, implement the corresponding production code, then rerun the same
  tests.
- Use `pytest` for unit/integration tests and `pytest-bdd` for behavioural
  tests.
- Use Vidai Mock for behavioural testing of inference services. This roadmap
  item does not expose or call an inference service, so the plan must not
  invent a synthetic inference endpoint solely to exercise Vidai Mock. If the
  implementation unexpectedly adds an HTTP path that calls `LLMPort`, that
  path's behavioural coverage must use Vidai Mock.
- Record the composition-root and health-contract decisions in a new ADR under
  `docs/adr/`.
- Update `docs/users-guide.md` for user-visible service behaviour,
  `docs/developers-guide.md` for runtime and testing practice, and
  `docs/episodic-podcast-generation-system-design.md` for design alignment.
- Mark roadmap item `1.5.1` done only after the implementation, tests, docs,
  and quality gates are complete.

## Tolerances

- Scope tolerance: stop and escalate if `1.5.1` expands beyond roughly 14
  files or 1000 net new lines before a working vertical slice exists.
- Dependency tolerance: stop and escalate if the runtime requires new external
  dependencies beyond `granian` itself.
- Contract tolerance: stop and escalate if preserving existing
  `episodic.api.create_app(...)` call sites requires a broad API break that
  cannot be handled by a compatibility shim or a mechanical repo-wide update.
- Runtime tolerance: stop and escalate if Granian cannot boot a Falcon factory
  cleanly without import-time side effects that would make testing brittle.
- Health tolerance: stop and escalate if readiness checks require a new durable
  database schema or any destructive migration.
- Behavioural-test tolerance: stop and escalate after three failed attempts to
  stabilise the same Granian subprocess or BDD scenario.

## Risks

- Risk: the current Falcon app factory accepts only `UowFactory`, and many
  tests construct it directly. Moving to a richer dependency object may create
  widespread fixture churn. Severity: medium. Likelihood: high. Mitigation:
  centralise the new dependency object in one module, update shared fixtures in
  `tests/conftest.py` early, and keep the migration mechanical.

- Risk: readiness checks can accidentally couple the inbound HTTP layer to
  SQLAlchemy engine details. Severity: medium. Likelihood: medium. Mitigation:
  model readiness as injected probe callables or a small typed readiness
  dependency rather than importing engine/session creation into resources.

- Risk: subprocess-based Granian tests may be flaky if ports collide or the
  process startup wait is too short. Severity: medium. Likelihood: medium.
  Mitigation: use free-port discovery, bounded startup polling, captured logs,
  and deterministic teardown in `pytest-bdd` steps.

- Risk: environment parsing for the runtime entrypoint may spread across the
  codebase and weaken the composition-root boundary. Severity: medium.
  Likelihood: medium. Mitigation: keep all runtime configuration parsing in one
  dedicated module and keep `app.py` pure.

- Risk: the urge to add too many future adapter slots could over-design the
  scaffold. Severity: low. Likelihood: medium. Mitigation: add only the hooks
  that are immediately justified by the roadmap and current design, namely the
  canonical unit-of-work seam, future inference-service hook, and readiness
  probes.

## Progress

- [x] (2026-03-28 00:00Z) Investigated the roadmap, existing ExecPlan pattern,
  current Falcon app factory, test fixtures, and design documents.
- [x] (2026-03-28 00:00Z) Confirmed the current state: Falcon 4.2.x is already
  wired for canonical routes, `granian` is absent from `pyproject.toml`, no
  health endpoints exist, and the only HTTP dependency seam is `UowFactory`.
- [x] (2026-03-30 00:00Z) Stage A: add fail-first unit, integration, and
  behavioural tests for the new HTTP scaffold.
- [x] (2026-03-30 00:00Z) Stage B: introduce the typed HTTP dependency object
  and health resources.
- [x] (2026-03-30 00:00Z) Stage C: add the Granian runtime composition root and
  runtime configuration parsing.
- [x] (2026-03-30 00:00Z) Stage D: finish the Granian behavioural harness and
  verify the health contract over real HTTP.
- [x] (2026-03-30 00:00Z) Stage E: update ADRs, design/user/developer docs, and
  roadmap state.
- [x] (2026-03-30 00:00Z) Stage F: run the full validation gates and record the
  delivery outcome.

## Surprises & Discoveries

- Observation: `episodic/api/app.py` already exposes a valid Falcon ASGI app
  factory and wires all currently implemented canonical-content routes. Impact:
  `1.5.1` is an additive scaffold, not a rewrite of the existing API adapter.

- Observation: `episodic/api/types.py` currently defines only `UowFactory` and
  `JsonPayload`. Impact: a richer dependency-injection seam needs a new typed
  module or a meaningful expansion of the existing type surface.

- Observation: `tests/conftest.py` already provides a shared
  `canonical_api_client` fixture that builds the Falcon app with
  `create_app(lambda: SqlAlchemyUnitOfWork(session_factory))`. Impact: this
  fixture is the main migration point for the new dependency object.

- Observation: no existing route or test mentions `health`, and no runtime
  entrypoint or server command is exposed in `pyproject.toml`. Impact: the
  runtime path, health contract, and operator guidance are all net-new.

- Observation: py-pglite-backed runtime tests became reliable only when the
  dedicated runtime database fixture fully disposed its migration engine before
  yielding the database URL. Impact: live-process and runtime-factory tests now
  use a dedicated `migrated_database_url` fixture instead of sharing a
  long-lived migrated engine.

- Observation: the project already documents Vidai Mock usage for inference
  services, but this roadmap item does not invoke `LLMPort`. Impact: the plan
  should state explicitly that Vidai Mock remains the rule for inference-facing
  work without forcing it into this transport-only slice.

## Decision Log

- Decision: keep `episodic/api/app.py` as the transport assembly module and add
  a separate runtime composition-root module, expected to live at
  `episodic/api/runtime.py`. Rationale: this preserves a clean boundary between
  Falcon route wiring and environment-specific adapter construction.
  Date/Author: 2026-03-28 / Codex.

- Decision: introduce a typed HTTP dependency object rather than extending the
  current function signature with a long list of callables. Rationale: the
  repo's lint and typing rules strongly prefer explicit contracts over open
  dictionaries, and a typed dependency object gives one stable seam for future
  inbound routes. Date/Author: 2026-03-28 / Codex.

- Decision: implement two health endpoints, `GET /health/live` and
  `GET /health/ready`, rather than a single overloaded endpoint. Rationale: the
  roadmap asks for health endpoints in the plural, and separate liveness and
  readiness checks match the deployment model described in the design document.
  Date/Author: 2026-03-28 / Codex.

- Decision: do not add a fake inference endpoint purely to involve Vidai Mock
  in `1.5.1`. Rationale: that would expand scope beyond transport scaffolding
  and would not satisfy the roadmap more honestly than a direct statement that
  no inference service is exercised in this slice. Date/Author: 2026-03-28 /
  Codex.

## Outcomes & Retrospective

Outcome:

- the Falcon API now boots through Granian via
  `episodic.api.runtime:create_app_from_env`;
- health endpoints exist and are covered both in memory and over a live
  Granian subprocess;
- the HTTP layer now receives its unit-of-work seam and readiness probes
  through `ApiDependencies`;
- the design, user, and developer documentation now describe the runtime and
  health contract; and
- `docs/roadmap.md` now marks `1.5.1` complete.

Retrospective:

- keeping `app.py` pure and moving environment parsing into `runtime.py`
  preserved the inbound adapter boundary cleanly;
- the dedicated runtime-process fixture mattered for py-pglite stability; and
- the new typed dependency object provides a small but durable extension seam
  for future injected ports such as `LLMPort`.

Validation outcome:

- `make fmt`
- `make check-fmt`
- `make lint`
- `make typecheck`
- `make test` (`292 passed`, `2 skipped`)
- `make markdownlint`
- `make nixie`

## Context and orientation

This section describes the relevant current state so a novice can navigate the
repository before making changes.

### Existing HTTP adapter

`episodic/api/app.py` defines
`create_app(uow_factory: UowFactory) -> falcon.asgi.App`. It constructs a
Falcon ASGI application and registers the currently implemented routes for:

- `/series-profiles`
- `/series-profiles/{profile_id}`
- `/series-profiles/{profile_id}/history`
- `/series-profiles/{profile_id}/brief`
- `/episode-templates`
- `/episode-templates/{template_id}`
- `/episode-templates/{template_id}/history`
- reusable reference-document and binding routes

No health route exists today.

### Current dependency seam

`episodic/api/types.py` defines:

- `UowFactory`, a callable returning `CanonicalUnitOfWork`
- `JsonPayload`, the JSON response/request alias used by Falcon resources

Every existing resource stores `self._uow_factory` and passes it into shared
handler functions. There is no typed place to inject other future port
adapters, such as `LLMPort` or readiness probes.

### Current tests

`tests/conftest.py` defines `canonical_api_client`, which imports
`episodic.api.create_app` and constructs a `falcon.testing.TestClient` using a
`SqlAlchemyUnitOfWork` built from the shared test `session_factory`. This is
the primary seam to update once the dependency object changes.

The current API tests are mostly synchronous Falcon client tests. For the new
health and runtime work, use `httpx.AsyncClient` with `httpx.ASGITransport` for
in-memory ASGI checks, following `docs/testing-async-falcon-endpoints.md`,
while keeping the existing synchronous client fixture working for the current
route tests unless there is a compelling reason to migrate them.

### Runtime gap

`pyproject.toml` currently includes `falcon>=4.2,<5.0`, but does not include
`granian`. There is also no runtime module that reads environment
configuration, constructs the SQLAlchemy session factory, or exposes a Granian
factory target.

The system design says HTTP services run on Falcon 4.2.x on Granian, so this
task closes the gap between the design and the codebase.

## Stage A: add fail-first tests for the scaffold

Create the tests before touching production code.

1. Add a new `pytest` module, suggested name
   `tests/test_http_service_scaffold.py`, that covers:
   - app-factory route registration for the health routes;
   - the dependency object's validation or construction rules;
   - readiness response behaviour for both success and probe failure; and
   - runtime configuration parsing for required environment, especially
     `DATABASE_URL`.
2. Extend `tests/conftest.py` only as needed to provide:
   - an app fixture built from the new dependency object; and
   - an `httpx.AsyncClient` fixture using `ASGITransport` for async Falcon
     requests.
3. Add a new behavioural feature file,
   `tests/features/http_service_scaffold.feature`, with at least one scenario:
   "Granian serves the Falcon health endpoints".
4. Add the matching BDD steps in
   `tests/steps/test_http_service_scaffold_steps.py`. The steps should:
   - provision a temporary database URL from the existing py-pglite-backed test
     harness or another repo-native ephemeral database fixture;
   - find a free port;
   - launch `granian` against the new runtime factory target; and
   - poll `/health/live` and `/health/ready` until both succeed or the process
     times out.
5. Run the targeted tests and confirm they fail before production changes.

Expected red-phase examples:

```plaintext
E   AttributeError: module 'episodic.api' has no attribute 'ApiDependencies'
E   AssertionError: expected route '/health/live' to exist
E   RuntimeError: Granian target 'episodic.api.runtime:create_app_from_env' not found
```

## Stage B: introduce typed dependencies and health resources

Implement the minimum production code needed to satisfy the new tests while
keeping boundaries clean.

1. Add a new typed dependency module, likely `episodic/api/dependencies.py`.
   Use frozen dataclasses or Protocols rather than open dictionaries. The
   contract should cover:
   - the required canonical `uow_factory`;
   - an optional future inference-service hook, likely for `LLMPort` or an
     `LLMPort` factory; and
   - a readiness-probe collection or small readiness interface.
2. Add a new Falcon resource module, likely `episodic/api/resources/health.py`,
   containing separate resources for liveness and readiness. Keep these
   resources thin; they should call injected readiness checks and translate the
   result into Falcon responses.
3. Update `episodic/api/app.py` so `create_app(...)` receives the typed
   dependency object, registers the health resources, and passes the dependency
   object's `uow_factory` into existing canonical resources.
4. Update `episodic/api/__init__.py` and any public imports or doctests needed
   so the package remains internally consistent.
5. Update shared test fixtures to use the new dependency object. If a small
   compatibility wrapper is the least risky way to keep existing call sites
   working during the migration, that is acceptable, but remove it if it
   becomes dead weight before the task is complete.

The result of Stage B should be an in-memory Falcon app that serves the health
routes and still supports the current canonical endpoints.

## Stage C: add the Granian runtime composition root

Once the in-memory app factory is stable, add the production-style runtime
assembly.

1. Add `granian` to `pyproject.toml` as the only new runtime dependency for
   this slice.
2. Create a runtime module, expected at `episodic/api/runtime.py`, that:
   - reads required environment configuration, at minimum `DATABASE_URL`;
   - constructs the async SQLAlchemy engine and `async_sessionmaker`;
   - creates the canonical `SqlAlchemyUnitOfWork` factory;
   - constructs the readiness probe(s), starting with a lightweight database
     connectivity check; and
   - returns the Falcon app by calling `episodic.api.create_app(...)`.
3. Expose a Granian-friendly factory target such as
   `episodic.api.runtime:create_app_from_env`.
4. Keep import-time side effects minimal. Environment parsing and adapter
   construction should happen inside the factory, not at module import time.

During this stage, keep the composition root as the only place where the HTTP
adapter knows about concrete SQLAlchemy and runtime concerns.

## Stage D: finish the Granian behavioural harness

With the runtime module in place, make the behaviour test prove the end-to-end
deployment path.

1. Update the BDD steps so they launch the Granian CLI using the factory
   target:

```shell
granian episodic.api.runtime:create_app_from_env --interface asgi --factory
```

1. Pass the temporary `DATABASE_URL` to the subprocess environment.
2. Wait for liveness first, then readiness, and capture stderr/stdout to a
   temporary log file for debugging.
3. Assert the response bodies are deterministic enough for operators to rely
   on. A suitable minimal shape is:

```json
{
  "status": "ok",
  "checks": [
    {"name": "application", "status": "ok"}
  ]
}
```

and

```json
{
  "status": "ok",
  "checks": [
    {"name": "database", "status": "ok"}
  ]
}
```

1. If the implementation chooses a different but equally clear response body,
   update the unit tests, behavioural tests, user guide, and ADR together so
   the contract stays consistent.

Vidai Mock note: if this stage remains a pure health/runtime scaffold, Vidai
Mock is not exercised. If an inference-facing HTTP route appears during the
implementation, add Vidai Mock-backed behavioural coverage before marking the
task complete.

## Stage E: documentation, ADR, and roadmap updates

After the code and tests are green, update the documentation set.

1. Add a new ADR at `docs/adr/adr-002-http-service-composition-root.md`
   describing:
   - the typed dependency object;
   - the choice of health endpoint contract; and
   - why the Granian factory target lives in a separate runtime module.
2. Update `docs/episodic-podcast-generation-system-design.md`:
   - add the new ADR to the accepted decision records list; and
   - refresh the HTTP-service language so the design matches the implemented
     scaffold.
3. Update `docs/users-guide.md` with the user-visible service behaviour:
   - how to start the HTTP service through Granian; and
   - what `/health/live` and `/health/ready` mean.
4. Update `docs/developers-guide.md` with maintainer-facing guidance:
   - where the composition root lives;
   - how to add new port adapters to the dependency object;
   - how to run the health/runtime behavioural tests; and
   - when Vidai Mock is required for future inference-facing HTTP work.
5. Update `docs/roadmap.md` and mark `1.5.1` done only after all gates listed
   in Stage F pass.

## Stage F: run the full validation gates

Run every required gate sequentially from repository root. Do not run
`make typecheck` and `make test` in parallel in this repository because the
shared `.venv` bootstrap can race.

Use `tee` so truncated command output can still be inspected.

```shell
set -o pipefail; make fmt 2>&1 | tee /tmp/execplan-1-5-1-make-fmt.log
set -o pipefail; make check-fmt 2>&1 | tee /tmp/execplan-1-5-1-make-check-fmt.log
set -o pipefail; make typecheck 2>&1 | tee /tmp/execplan-1-5-1-make-typecheck.log
set -o pipefail; make lint 2>&1 | tee /tmp/execplan-1-5-1-make-lint.log
set -o pipefail; make test 2>&1 | tee /tmp/execplan-1-5-1-make-test.log
set -o pipefail; PATH=/root/.bun/bin:$PATH make markdownlint 2>&1 | tee /tmp/execplan-1-5-1-make-markdownlint.log
set -o pipefail; make nixie 2>&1 | tee /tmp/execplan-1-5-1-make-nixie.log
```

If any gate fails, fix the issue and rerun the failed command before advancing
to the next stage.

## Concrete steps

Run from repository root.

- Inspect the current HTTP adapter, types, and test fixtures.

```shell
sed -n '1,220p' episodic/api/app.py
sed -n '1,220p' episodic/api/types.py
sed -n '360,460p' tests/conftest.py
```

- Find the current route and resource modules.

```shell
rg --files episodic/api tests | rg "api|feature|steps|conftest"
```

- Add fail-first tests for health routing, runtime configuration, and Granian
  subprocess boot.

- Implement the dependency object, health resources, and runtime factory.

- Update the design, user, developer, and ADR documents.

- Mark roadmap item `1.5.1` done only after all tests and gates pass.

## Acceptance evidence to capture during implementation

Keep concise evidence snippets in the completed plan or implementation notes.

Examples:

```plaintext
tests/test_http_service_scaffold.py::test_health_live_route_returns_200 PASSED
tests/test_http_service_scaffold.py::test_readiness_returns_503_when_probe_fails PASSED
tests/steps/test_http_service_scaffold_steps.py::test_granian_serves_health_endpoints PASSED
```

```plaintext
$ curl -sS http://127.0.0.1:8101/health/live
{"status":"ok","checks":[{"name":"application","status":"ok"}]}
```

```plaintext
$ curl -sS http://127.0.0.1:8101/health/ready
{"status":"ok","checks":[{"name":"database","status":"ok"}]}
```

```plaintext
make check-fmt: PASS
make typecheck: PASS
make lint: PASS
make test: PASS
make markdownlint: PASS
make nixie: PASS
```
