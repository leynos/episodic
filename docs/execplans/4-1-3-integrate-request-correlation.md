# Integrate request correlation across HTTP, tasks, and outbound provider calls (4.1.3)

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, `Outcomes & Retrospective`, `Conformance Basis`, and
`Verification Plan` must be kept up to date as work proceeds.

Status: DRAFT

## Purpose / big picture

Today an operator who sees a failure in Episodic cannot follow one HTTP request
through the system. The Falcon HTTP service, the Celery workers, and the
outbound calls to the OpenAI-compatible inference provider each log
independently, and nothing ties those three streams together. When a generation
run fails, the only way to correlate a `401` denial, a worker traceback, and a
provider timeout is to guess from timestamps.

After this change, every request that enters the HTTP service carries a single
**request correlation identifier**. A "request correlation identifier" is a
short opaque string, by default a UUID version 7 hex value, that identifies one
inbound HTTP request and everything that request causes to happen. It is
created by the service (or accepted from a trusted ingress), attached to the
request, echoed back to the caller in a response header, written into every log
line the request produces, copied onto any Celery task the request publishes,
and sent as an HTTP header on every outbound provider call the request makes.

Success is observable like this. Start the service, send a request, and read the
response header:

```bash
curl -i http://127.0.0.1:8000/health/live
```

```http
HTTP/1.1 200 OK
X-Correlation-ID: 019b3c9d5f7a7c1e8f0a1b2c3d4e5f60
content-type: application/json
```

Send a request that is denied, and observe that the denial still carries the
same identifier, so the `401` the caller saw can be matched to the warning in
the service log:

```bash
curl -i -H 'Authorization: Bearer wrong' http://127.0.0.1:8000/v1/series-profiles
```

```http
HTTP/1.1 401 Unauthorized
X-Correlation-ID: 019b3c9d61aa7d2f9e1b2c3d4e5f6071
```

```plaintext
authorization_denied method=GET path=/v1/series-profiles correlation_id=019b3c9d61aa7d2f9e1b2c3d4e5f6071
```

And a request that reaches the inference provider causes the provider to receive
the same value on the wire:

```plaintext
POST /v1/chat/completions
X-Correlation-ID: 019b3c9d5f7a7c1e8f0a1b2c3d4e5f60
```

## Scope and roadmap relationship

This plan implements roadmap item **4.1.3**, "Integrate request correlation
across HTTP, tasks, and outbound provider calls", recorded at
`docs/roadmap.md:606-626`. That item requires 1.5.1 (Falcon services on Granian,
already complete) and 1.5.2 (Celery workers with RabbitMQ, already complete).

In scope:

1. Adding `leynos/falcon-correlate` as an application dependency at a pinned
   Git revision.
2. A single episodic-owned configuration and access seam for the request
   correlation identifier.
3. Wiring `CorrelationIDMiddlewareASGI` into the Falcon composition root ahead
   of the authorization middleware.
4. Runtime configuration for header name, trusted ingress ranges, incoming-ID
   validation, and response-header echoing.
5. Correlation identifiers in the log lines emitted through
   `episodic/logging.py` and `episodic/observability.py`.
6. Celery publish-time and worker-side propagation configured in the worker
   composition root.
7. Correlation headers on outbound `httpx` traffic owned by the
   OpenAI-compatible LLM adapter.
8. Unit, property, behavioural, and snapshot tests, plus users' guide,
   developers' guide, design document, and ADR updates.

Explicitly **not** in scope, and why:

- **Renaming or re-using the existing domain `correlation_id` field.** Several
  domain objects already carry a field named `correlation_id`
  (`episodic/worker/tasks.py:86`, `episodic/orchestration/generation.py:171`,
  `episodic/asyncio_tasks.py:23`). In those places the value identifies a
  *generation run or workflow*, not an HTTP request; see
  `episodic/orchestration/_planning_orchestrator.py:148`, where it is passed as
  `workflow_run_id`. This plan introduces a *separate* infrastructure concept
  and must not conflate the two. Seeding the domain field from the HTTP request
  identifier is a plausible future change but is deliberately excluded here.
- **OpenTelemetry or W3C `traceparent` propagation.** `docs/infrastructure-design.md`
  places OpenTelemetry at the collector layer only, and no `opentelemetry-*`
  package is a project dependency. Adding distributed tracing is separate work.
- **RFC 7807 `application/problem+json` error bodies.** Tracked separately by
  `docs/execplans/4-1-2-finalize-rest-surfaces.md`.
- **Correlation for worker-originated provider calls.** No Celery task currently
  constructs an LLM adapter; `episodic/worker/tasks.py` registers only the two
  diagnostic scaffold tasks. When domain tasks arrive they must build their
  clients through the factory this plan introduces.

## Constraints

Hard invariants. Violating one of these requires escalation, not a workaround.

- **C1. `create_app` stays pure.** `episodic/api/app.py:303` must not read
  environment variables or construct infrastructure. ADR 002
  (`docs/adr/adr-002-http-service-composition-root.md`) makes
  `episodic/api/runtime.py` the only module that reads configuration for the
  HTTP service. Correlation configuration must therefore arrive through
  `ApiDependencies`.
- **C2. Hexagonal boundaries hold.** `make check-architecture` runs `hecate`
  against the groups declared at `pyproject.toml:785-864`. Domain and
  application modules (`episodic.canonical.domain`, `episodic.orchestration`,
  and the rest) must not import `falcon_correlate`, `falcon`, or `httpx`.
- **C3. The correlation identifier never enters the domain.** No domain entity,
  port signature, or persisted record gains a request correlation field. ADR 015
  (`docs/adr/adr-015-upload-and-idempotency-ports.md:170`) already records that
  "correlation to a specific request belongs in logs and trace context".
- **C4. Untrusted callers cannot choose their identifier.** An incoming
  correlation header is honoured only when the request arrives from a configured
  trusted source. The default configuration trusts nothing.
- **C5. Secrets stay out of representations.** Any new `RuntimeConfig` field
  that could carry sensitive data uses `dc.field(repr=False)`, matching
  `episodic/api/runtime_config.py:66-72`. Correlation settings are not secret,
  so this is expected to be a no-op, but the rule still applies.
- **C6. All four gates pass at every milestone.** `make check-fmt`,
  `make typecheck`, `make lint`, and `make test` must succeed before each
  milestone is recorded as complete.
- **C7. No new runtime dependency beyond `falcon-correlate`.** The plan must not
  introduce `structlog`, `respx`, `opentelemetry-*`, or `uuid-utils`. Python
  3.14 provides `uuid.uuid7()`, so `falcon-correlate`'s `uuid-utils` fallback is
  excluded by its own environment marker (`python_version < "3.14"`).

## Tolerances (exception triggers)

- **Scope.** If the change touches more than 30 files or more than 1,800 net
  lines of code and documentation, stop and escalate.
- **Interface.** If any port protocol in `episodic/canonical/ports.py`,
  `episodic/llm/ports.py`, or `episodic/cost/ports.py` must change signature,
  stop and escalate. This plan expects zero port changes.
- **Dependencies.** `falcon-correlate` is the only new dependency this plan
  authorizes. If a second one appears necessary, stop and escalate.
- **Iterations.** If a single failing test is not green after four focused
  attempts, stop, write the findings into `Surprises & discoveries`, and
  escalate.
- **Upstream library defects.** If `falcon-correlate` must be patched or
  monkey-patched to satisfy a requirement, stop and escalate; the correct
  response is an upstream issue and a revised pin, not a local shim.
- **Ambiguity.** If the operator-facing header contract admits two readings that
  produce materially different deployments, stop and present the options.

## Risks

- **Risk R1: `falcon-correlate` has no tagged release.**
  `https://github.com/leynos/falcon-correlate` has zero tags and zero GitHub
  releases, and the name is not registered on PyPI (`GET
  https://pypi.org/pypi/falcon-correlate/json` returns `{"message": "Not
  Found"}`). The dependency must be pinned to a commit.
  Severity: medium. Likelihood: certain.
  Mitigation: pin the exact commit SHA in the PEP 508 direct reference, exactly
  as the repository already does for `femtologging` and `tei-rapporteur`
  (`pyproject.toml:14,21`). Record the SHA and the date it was chosen in
  `Decision log` so a future upgrade is a deliberate act.

- **Risk R2: trusting `127.0.0.1` silently trusts everything.**
  Falcon's ASGI `Request.remote_addr` returns the last element of
  `access_route`, and `access_route` appends the ASGI scope `client` value —
  "if the 'client' field is not available, it will default to `'127.0.0.1'`"
  (`falcon/asgi/request.py:463-479`, `539-547`). If a deployment lists
  `127.0.0.1` in the trusted sources and the ASGI server does not populate
  `scope["client"]`, every request becomes trusted and any caller can choose its
  own correlation identifier.
  Severity: high. Likelihood: medium.
  Mitigation: default the trusted-source list to empty; document the hazard
  prominently in the users' guide; add an explicit test that an unset scope
  client is not trusted under a production-shaped configuration; and warn at
  startup when the loopback address is configured as trusted.

- **Risk R3: an `rpc://` Celery result backend silently disables propagation.**
  `falcon_correlate.celery.propagate_correlation_id_to_celery` returns without
  writing `properties["correlation_id"]` when the active application's result
  backend URI starts with `rpc://`, because Celery's RPC backend uses that AMQP
  property to route results. `WorkerRuntimeConfig.result_backend`
  (`episodic/worker/runtime.py:65`) is operator-supplied through
  `EPISODIC_CELERY_RESULT_BACKEND`, so an operator can disable correlation
  without any signal.
  Severity: medium. Likelihood: low.
  Mitigation: emit a startup warning from `create_celery_app` when the result
  backend begins with `rpc://`; document the interaction; and cover both
  branches with a test.

- **Risk R4: femtologging cannot carry ambient structured context.**
  Episodic logs through `femtologging` (`episodic/logging.py:20`).
  `femtologging.log_context` is documented as a *thread-local* stack, and
  empirically its fields do not reach records emitted by
  `femtologging.get_logger(...)` at all — a callable formatter observes
  `metadata.key_values == {}` both inside and outside a `log_context` block.
  Holding a thread-local context across an `await` in an asyncio service would
  also leak between concurrent requests.
  Severity: high. Likelihood: certain.
  Mitigation: do not use `log_context` or `falcon_correlate.ContextualLogFilter`
  for the femtologging path. Instead decorate the message inside the existing
  `episodic/logging.py` helpers, which every caller already funnels through.
  See `Decision log` D5.

- **Risk R5: the eager-mode Celery test is vacuous by construction.**
  With `task_always_eager=True`, Celery never publishes, so
  `before_task_publish` does not fire, and the task body runs in the caller's
  own context, so `correlation_id_var` is already set regardless of whether any
  integration exists. A naive eager test passes against an unwired application.
  Severity: high. Likelihood: high — the roadmap text asks for "Celery
  eager-mode tests", which invites exactly this mistake.
  Mitigation: design the Celery tests as described in `Verification plan`
  obligations INV-4a and INV-4b, with an explicit negative control.

- **Risk R6: middleware ordering regressions are invisible.**
  Nothing currently asserts the order of `app.add_middleware` calls in
  `episodic/api/app.py:305-318`. A later edit could move the correlation
  middleware after authorization, silently removing the identifier from denial
  logs.
  Severity: medium. Likelihood: medium.
  Mitigation: assert the concrete observable consequence (a denial response
  carries the header and the denial log carries the identifier) rather than the
  ordering itself.

- **Risk R7: injected `httpx` clients bypass correlation.**
  `OpenAICompatibleLLMAdapter` accepts a caller-supplied client
  (`episodic/llm/openai_api/adapter.py:130`), and
  `tests/steps/no_qa_generation_slice_support.py:217` supplies one so it can set
  the `X-Vidai-Chaos-Drop` header. Injected clients will not carry correlation
  headers unless the caller builds them through the new factory.
  Severity: low. Likelihood: high.
  Mitigation: state the ownership contract in the adapter docstring and the
  developers' guide: the adapter correlates the client it owns; a caller that
  injects a client owns that decision and should use
  `build_correlated_async_client`.

## Progress

- [ ] EP-M0 Pin `falcon-correlate` and prove it imports.
- [ ] EP-M1 Correlation seam and runtime configuration.
- [ ] EP-M2 Falcon ASGI middleware wiring ahead of authorization.
- [ ] EP-M3 Correlation identifiers in logs.
- [ ] EP-M4 Celery publish and worker propagation.
- [ ] EP-M5 Outbound provider-call correlation.
- [ ] EP-M6 Behavioural, property, and snapshot coverage.
- [ ] EP-M7 Documentation, ADR, and roadmap tick.

## Surprises & discoveries

Findings established while drafting this plan, each with its evidence, so the
implementer does not have to rediscover them.

- **Observation:** `except OSError, RuntimeError, TypeError, ValueError:` at
  `episodic/api/authorization.py:114` and the three similar clauses at
  `episodic/api/errors.py:367`,
  `episodic/api/resources/generation_runs.py:270`, and
  `episodic/generation/launcher.py:501` are **valid**, not Python 2 relics.
  **Evidence:** PEP 758 removed the parenthesis requirement for `except` with
  multiple exception types in Python 3.14, and
  `uv run python -m compileall -q` over all four files exits zero.
  **Impact:** do not "fix" them; the project targets `requires-python = ">=3.14"`.

- **Observation:** `femtologging.log_context` fields never reach records emitted
  by `femtologging.get_logger(...)`.
  **Evidence:** installing a callable formatter through
  `StreamHandlerBuilder.stderr().with_formatter(fn)` and logging inside
  `with log_context(correlation_id="abc123")` yields
  `metadata.key_values == {}`.
  **Impact:** drives Decision D5; `falcon_correlate.ContextualLogFilter` and
  `RECOMMENDED_LOG_FORMAT` are unusable on the femtologging path.

- **Observation:** in Celery eager mode `before_task_publish` does not fire and
  `task.request.correlation_id` is `None`.
  **Evidence:** a probe application with `task_always_eager=True` recorded zero
  `before_task_publish` firings and `{'ctxvar': 'OUTER', 'req_cid': None}` from
  inside the task body; with the ambient variable unset the same task saw
  `{'ctxvar': None, 'req_cid': None}`.
  **Impact:** drives Risk R5 and the split Celery obligations INV-4a/INV-4b.

- **Observation:** the `rpc://` guard is real and observable.
  **Evidence:** with `Celery(backend="rpc://")` current,
  `propagate_correlation_id_to_celery(properties={"correlation_id": "task-id-original"})`
  leaves the value untouched while an active correlation ID is set; with
  `backend="cache+memory://"` the same call rewrites it to the correlation ID.
  **Impact:** drives Risk R3 and obligation INV-4c.

- **Observation:** Falcon runs `process_response` for every middleware component
  even when an earlier component sets `resp.complete = True`.
  **Evidence:** `falcon/asgi/app.py:540-594` — the `process_request` loop breaks
  on `resp.complete`, but `mw_resp_stack` (or `dependent_mw_resp_stack`) already
  holds every `process_response` callable and is iterated unconditionally.
  **Impact:** the correlation header is echoed on authorization denials, which
  is what makes the roadmap's "denial ... logs share the same request
  identifier" requirement satisfiable.

- **Observation:** `Request.remote_addr` is the peer address, not a
  header-derived client address that an attacker could spoof.
  **Evidence:** `falcon/asgi/request.py:539-547` returns `access_route[-1]`, and
  `access_route` appends the ASGI scope `client` to the end of any
  `Forwarded` / `X-Forwarded-For` / `X-Real-IP` list.
  **Impact:** `trusted_sources` correctly means "ingress or proxy source
  ranges", matching the roadmap wording, and no `X-Forwarded-For` parsing is
  needed. The `'127.0.0.1'` fallback in the same docstring is what makes Risk R2
  real.

- **Observation:** `episodic.logging.configure_logging` is never called from a
  production entry point.
  **Evidence:** the only references are its own definition, its docstring
  example, and `tests/test_logging.py`.
  **Impact:** message decoration (Decision D5) works regardless of logging
  configuration, which is a further reason to prefer it over handler-level
  filters. Bootstrapping logging at start-up is a real gap but belongs to a
  separate roadmap item.

## Decision log

- **D1. Pin `falcon-correlate` to commit
  `caea7a6ac804f851f7226ccf9acb3d256cc2d5d4`.**
  Rationale: the project is not on PyPI and has no tags or releases, so a commit
  pin is the only reproducible option. This mirrors the existing
  `femtologging` and `tei-rapporteur` pins at `pyproject.toml:14,21`. The commit
  is the `main` HEAD observed on 2026-08-23 and contains the ASGI middleware,
  the Celery signal integration, and the `httpx` transports this plan needs.
  Date/Author: 2026-08-23, planning agent.

- **D2. Introduce `episodic/request_correlation.py` as the single seam.**
  Rationale: exactly one module imports `falcon_correlate`'s context variable
  and configuration types, so the rest of the codebase depends on an
  episodic-owned surface. The name deliberately says "request" to keep it
  distinct from the domain `correlation_id` described under Scope. The module
  sits ungrouped in the `hecate` configuration, following the precedent of
  `episodic/observability.py` and `episodic/logging.py`.
  Date/Author: 2026-08-23, planning agent.

- **D3. Configuration lives in one loader shared by both composition roots.**
  Rationale: the HTTP service and the workers must agree on the header name or
  a task-published provider call would use a different header from the request
  that caused it. `load_correlation_settings(environ)` is called by
  `episodic/api/runtime_config.py` and by `episodic/worker/runtime.py`.
  Date/Author: 2026-08-23, planning agent.

- **D4. The correlation middleware is registered first.**
  Rationale: Falcon executes `process_request` in registration order, so
  registering ahead of `AuthorizationMiddleware`
  (`episodic/api/app.py:306`) guarantees the identifier exists before any
  authorization decision is logged. Because `process_response` runs in reverse,
  the same choice also makes the correlation middleware the last to touch the
  response, so the header is echoed and the context variable is reset after
  every other component has finished.
  Date/Author: 2026-08-23, planning agent.

- **D5. Correlation reaches femtologging by message decoration, not by filter.**
  Rationale: `falcon_correlate.ContextualLogFilter` is a `logging.Filter` and
  only works with the standard library. femtologging's own `log_context` is
  thread-local and, as the evidence under `Surprises & discoveries` shows, does
  not reach records emitted through `get_logger`. Every episodic log call
  already funnels through `log_info`, `log_warning`, or `log_error` in
  `episodic/logging.py`, so appending a space-separated
  `correlation_id=<id>` field inside those three helpers gives complete
  coverage with a three-function change and no call-site churn. The field is
  appended only when a correlation identifier is active, so non-request
  logging is unchanged.
  Alternatives rejected: threading an explicit argument through every call site
  (large, easy to forget); wrapping each emit in `log_context` (does not work);
  migrating episodic to the standard library so the filter applies (far outside
  this item's scope).
  Date/Author: 2026-08-23, planning agent.

- **D6. `episodic/observability.py` gains the identifier through `extra=`.**
  Rationale: that module uses the standard library directly
  (`logging.getLogger(__name__)`, `extra={...}`), so the identifier can simply
  be added to the existing structured payloads of `StructuredLogMetrics` and
  `StructuredLogTracer`. This is more reliable than attaching
  `ContextualLogFilter`, because episodic never installs a standard-library
  handler for the filter to hang from.
  Date/Author: 2026-08-23, planning agent.

- **D7. The LLM adapter correlates the client it owns.**
  Rationale: the roadmap says "wrap *owned* `httpx.AsyncClient` instances". The
  adapter already distinguishes owned from injected clients via `_owns_client`
  (`episodic/llm/openai_api/adapter.py:135-136`) and only closes the former.
  Extending `OpenAICompatibleLLMConfig` with a `correlation_header_name` and
  building the owned client through `build_correlated_async_client` preserves
  that ownership contract and avoids a client leak that would follow from
  injecting a client at the composition root without also registering a
  shutdown hook for it.
  Date/Author: 2026-08-23, planning agent.

- **D8. `episodic/request_correlation.py` owns the default header constant.**
  Rationale: `falcon_correlate` exports `DEFAULT_HEADER_NAME` from
  `falcon_correlate.middleware_config`, not from its package root. Re-exporting
  it through the episodic seam keeps the import in one place, and a test pins
  the value to the literal `"X-Correlation-ID"` so an upstream change to the
  default is caught at the gate rather than in production.
  Date/Author: 2026-08-23, planning agent.

## Outcomes & retrospective

To be completed at EP-M7. Before setting this plan to `COMPLETE`, reconcile
every discovery against `docs/roadmap.md`,
`docs/episodic-podcast-generation-system-design.md`, and the ADR written in
EP-M7, and record any remaining deviation here.

## Context and orientation

Read this section if you have never worked in this repository.

Episodic is a podcast-generation system written in Python 3.14 and managed with
`uv`. It follows hexagonal architecture: a pure domain, ports declared as
`typing.Protocol` classes, and adapters that implement those ports. The
`hecate` tool enforces the boundaries; `pyproject.toml:785-864` lists the groups
and what each may import. `docs/adr/adr-014-hexagonal-architecture-enforcement.md`
explains the policy, and the `hexagonal-architecture` skill gives the general
pattern.

The pieces you will touch:

- **The HTTP service.** `episodic/api/app.py` holds `create_app(dependencies)`,
  a pure factory that builds a `falcon.asgi.App`, registers middleware, sets an
  error serializer, and adds routes. It must never read the environment; ADR 002
  (`docs/adr/adr-002-http-service-composition-root.md`) reserves that for
  `episodic/api/runtime.py`, whose `create_app_from_env()` is the Granian
  factory target named at `episodic/api/runtime.py:59`.
  `episodic/api/runtime_config.py` defines the frozen `RuntimeConfig` dataclass
  and `_load_runtime_config(environ)`, which reads `UPPER_SNAKE_CASE`
  environment variables and raises `RuntimeConfigurationError` on bad input.
  `episodic/api/dependencies.py` defines `ApiDependencies`, the typed bag of
  already-constructed ports that `create_app` receives.
- **Authorization.** `episodic/api/authorization.py` guards paths under `/v1/`
  and writes its own denial envelopes directly onto the response with
  `resp.complete = True`, rather than raising a `falcon.HTTPError`. Its denial
  path calls `log_warning`.
- **The workers.** `episodic/worker/runtime.py` holds `WorkerRuntimeConfig`,
  `load_runtime_config(environ)` (reading `EPISODIC_CELERY_*` variables), and
  `create_celery_app(config, dependencies, topology)`, which builds the `Celery`
  application and calls `register_scaffold_tasks`. The `celery` command-line tool
  is pointed at `episodic.worker.runtime:create_celery_app_from_env`, as
  documented in `docs/developers-guide.md:434-444`.
- **The inference adapter.** `episodic/llm/openai_api/adapter.py` defines
  `OpenAICompatibleLLMAdapter`, a hand-written `httpx` client for
  OpenAI-compatible endpoints. It does not use the `openai` SDK. It accepts an
  optional `client` and tracks ownership in `_owns_client`.
- **Logging.** `episodic/logging.py` wraps `femtologging`, exposing
  `get_logger`, `configure_logging`, and the `log_info` / `log_warning` /
  `log_error` helpers that format a percent-style template and emit it.
  `episodic/observability.py` separately uses the standard library for its
  metrics and tracing adapters.

The library you are integrating, `falcon-correlate`, is another `leynos`
project. Its public surface is exported from `falcon_correlate/__init__.py`:

- `CorrelationIDMiddlewareASGI` — Falcon ASGI middleware. Its
  `process_request` picks an incoming header value when the request comes from a
  trusted source and passes validation, otherwise generates a new identifier; it
  then sets `req.context.correlation_id` and the `correlation_id_var` context
  variable. Its `process_response` echoes the header and resets the context
  variable.
- `CorrelationIDConfig` — a frozen dataclass with `header_name`,
  `trusted_sources`, `generator`, `validator`, and `echo_header_in_response`.
  It validates IP addresses and CIDR ranges at construction time and rejects a
  CIDR with host bits set.
- `correlation_id_var` — a `contextvars.ContextVar[str | None]`, the ambient
  read point.
- `default_uuid7_generator`, `default_uuid_validator` — the default identifier
  factory and a UUID-shape validator accepting versions 1 to 8 in either
  hyphenated or hex-only form.
- `configure_celery_correlation(app)` — idempotently connects
  `before_task_publish`, `task_prerun`, and `task_postrun` handlers.
- `AsyncCorrelationIDTransport(wrapped, header_name)` — an
  `httpx.AsyncBaseTransport` that injects the header before delegating, and
  leaves an already-present header alone.

Two exports must **not** be used here: `ContextualLogFilter` and
`RECOMMENDED_LOG_FORMAT` assume the standard-library logging stack, which
episodic does not use for application logging. See Decision D5.

Relevant reading, in priority order:

- `docs/roadmap.md:606-626` — the requirement text.
- `docs/episodic-podcast-generation-system-design.md:2033-2044` — the existing
  design statement for this work.
- `docs/adr/adr-002-http-service-composition-root.md` — why `create_app` is pure.
- `docs/adr/adr-003-celery-worker-scaffold.md` — the worker composition root.
- `docs/adr/adr-014-hexagonal-architecture-enforcement.md` — the `hecate` policy.
- `docs/developers-guide.md` — the lint pipeline (§Linting), versioned routing
  and error contract (lines 280-339), worker launch (434-444), and the Vidai
  Mock behavioural-testing policy (805, 1140-1780).
- `docs/testing-async-falcon-endpoints.md` — the async endpoint testing patterns.
- `docs/agentic-systems-with-langgraph-and-celery.md` — the worker/orchestration
  boundary.
- `docs/documentation-style-guide.md` — required ADR sections and file naming.

Relevant skills: `hexagonal-architecture` for boundary questions,
`python-router` and then `python-errors-and-logging` for the logging work,
`python-testing` and `hypothesis` for the test design, `leta` for navigation,
and `vidai-mock` for the behavioural inference double.

## Conformance basis

Upstream artefacts and the identifiers this plan traces from.

- Roadmap: `docs/roadmap.md`, item 4.1.3 at lines 606-626, as of commit
  `5af0638`. Referred to below as **RM-4.1.3**, with sub-requirements
  **RM-4.1.3.a** through **RM-4.1.3.g** in the order the roadmap lists them:
  a. dependency pin; b. middleware before authorization; c. runtime
  configuration; d. Celery propagation; e. outbound `httpx` wrapping; f. Falcon,
  Celery-eager, and `MockTransport` tests; g. users' and developers' guide
  documentation.
- Design: `docs/episodic-podcast-generation-system-design.md:2033-2044`,
  referred to as **DD-CORR**.
- ADRs constraining the approach: **ADR-002** (HTTP composition root),
  **ADR-003** (Celery worker scaffold), **ADR-014** (hexagonal enforcement),
  **ADR-015** (correlation belongs in logs and trace context, not the domain).
- New ADR to be written in EP-M7: **ADR-018**, `docs/adr/adr-018-request-correlation-propagation.md`.
  Number 018 is the next free value: 016 and 017 are taken, and 015 is already
  triple-booked across `adr-015-upload-and-idempotency-ports.md`,
  `adr-015-cost-accounting-ports-and-pricing-engine.md`, and
  `adr-015-generation-run-port-split.md`. That collision is pre-existing and is
  **not** this plan's to fix; note it and move on.
- No Terms of Reference document exists for this work; the roadmap item and the
  design-document paragraph are the governing statements.

Trace links:

```plaintext
RM-4.1.3.a -> EP-M0 -> tests::test_request_correlation_settings::test_falcon_correlate_default_header_is_pinned
RM-4.1.3.c -> DD-CORR -> EP-M1 -> tests::test_runtime_configuration::test_correlation_settings_from_environment
RM-4.1.3.b -> ADR-002 -> EP-M2 -> tests::test_api_request_correlation::test_denied_request_echoes_correlation_header
RM-4.1.3.b -> DD-CORR -> EP-M3 -> tests::test_logging::test_helpers_append_active_correlation_id
RM-4.1.3.d -> ADR-003 -> EP-M4 -> tests::test_worker_request_correlation::test_publish_writes_active_correlation_id
RM-4.1.3.e -> EP-M5 -> tests::test_llm_openai_adapter_correlation::test_owned_client_sends_correlation_header
RM-4.1.3.f -> EP-M6 -> tests/features/request_correlation.feature
RM-4.1.3.g -> EP-M7 -> docs/users-guide.md, docs/developers-guide.md, ADR-018
```

## Verification plan

### Axioms

These are treated as given. Do not write tests that verify third-party
internals; do verify episodic-owned logic against the real interface.

- **AXIOM-1.** `falcon_correlate.CorrelationIDMiddlewareASGI` implements the Falcon
  ASGI middleware contract, selects a trusted and valid incoming identifier or
  generates one, sets `req.context.correlation_id` and `correlation_id_var`,
  and echoes and resets in `process_response`.
- **AXIOM-2.** Falcon executes middleware `process_request` in registration order
  and `process_response` in reverse, and runs every registered
  `process_response` even when an earlier component sets `resp.complete = True`
  (`falcon/asgi/app.py:540-594`).
- **AXIOM-3.** `Request.remote_addr` is `access_route[-1]`, which is the ASGI scope
  `client` address, falling back to `'127.0.0.1'` when the scope omits it
  (`falcon/asgi/request.py:463-479,539-547`).
- **AXIOM-4.** Celery fires `before_task_publish` only on a real publish, and fires
  `task_prerun` and `task_postrun` around every execution, including eager
  execution.
- **AXIOM-5.** `falcon_correlate.celery.propagate_correlation_id_to_celery` writes
  `properties["correlation_id"]` when an identifier is active, except when the
  current application's result backend URI begins with `rpc://`.
- **AXIOM-6.** `httpx.AsyncClient(transport=...)` routes every request through the
  supplied transport, and `httpx.MockTransport` observes the fully built request
  including headers.
- **AXIOM-7.** Python 3.14 provides `uuid.uuid7()`, so
  `default_uuid7_generator` never needs the `uuid_utils` fallback here.
- **AXIOM-8.** `femtologging` records emitted through `get_logger(...)` do not
  carry `log_context` fields. Established empirically; recorded under
  `Surprises & discoveries`. If a future `femtologging` bump changes this,
  Decision D5 must be revisited.

### Obligations

**INV-1 — Response and request context agree, and untrusted callers cannot
choose the identifier.**

- Obligation: for every request, `req.context.correlation_id` is a non-empty
  string; when echoing is enabled the response carries exactly one header of the
  configured name whose value equals `req.context.correlation_id`; and that
  value equals a caller-supplied header value **only if** the request's
  `remote_addr` falls inside a configured trusted source *and* the supplied
  value passes the configured validator.
- Method: property test with Hypothesis, plus parameterized boundary tests.
- Rationale: the statement quantifies over incoming header values, remote
  addresses, and configurations, which examples alone cannot cover; the trust
  rule is the security-relevant part and deserves generated adversarial input.
- Domain: header values drawn from valid UUIDs (hyphenated and hex-only, mixed
  case), malformed strings, empty and whitespace-only strings, over-long
  strings, and strings containing CR or LF; remote addresses drawn from inside
  and outside the configured CIDR ranges, plus the unset-scope case;
  configurations varying `validate_incoming_ids` and `echo_response_header`.
- Artefact: `tests/test_api_request_correlation_properties.py`, driving
  `falcon.testing.TestClient(create_app(deps))` with
  `simulate_get(..., headers=..., remote_addr=...)`.
- Evidence: `uv run pytest tests/test_api_request_correlation_properties.py`.
  Before EP-M2 the module fails at import because the settings type does not
  exist; after EP-M2 it passes.
- Non-vacuity: use `hypothesis.event()` to classify each generated case as
  `accepted-incoming`, `rejected-untrusted`, `rejected-invalid`, or
  `no-incoming-header`, and assert with `hypothesis.target`-free explicit
  counters that all four classes occur across the run; a run in which
  `accepted-incoming` never occurs is a verification failure, not a pass. The
  negative control is a seeded mutation that removes the trust check by
  configuring `trusted_sources` to `("0.0.0.0/0",)`: the `rejected-untrusted`
  assertion must then fail.

**INV-2 — The identifier survives authorization denial.**

- Obligation: a request that `AuthorizationMiddleware` rejects with `401` or
  `403` still carries the correlation header on the response, and the warning
  logged by the denial path carries the same identifier.
- Method: parameterized test over the denial statuses, plus one behavioural
  scenario.
- Rationale: this is the specific outcome RM-4.1.3.b asks for, and it depends on
  AXIOM-2 rather than on anything episodic controls, so it must be observed rather
  than assumed.
- Domain: missing `Authorization` header (401), wrong bearer token (401), and an
  authorization port that raises (503).
- Artefact: `tests/test_api_request_correlation.py`.
- Evidence: `uv run pytest tests/test_api_request_correlation.py -k denial`.
- Non-vacuity: the same test asserts the header is *absent* when
  `echo_response_header` is false, proving the assertion can fail. Registering
  the correlation middleware after `AuthorizationMiddleware` is the seeded fault
  that must break the log assertion.

**INV-3 — Every message emitted through the episodic logging helpers carries
the active identifier, and only when one is active.**

- Obligation: `log_info`, `log_warning`, and `log_error` append exactly one
  space-separated `correlation_id=<id>` suffix when
  `current_correlation_id()` returns a value, and leave the message
  byte-identical when it returns `None`.
- Method: parameterized unit tests against a recording fake logger.
- Rationale: a finite, fully enumerable partition — identifier present or
  absent, across three helpers, with and without template arguments.
- Domain: all three helpers; templates with zero and with several `%s`
  placeholders; identifier present and absent; a template whose arguments
  already contain the substring `correlation_id=`.
- Artefact: `tests/test_logging.py`, extending the existing fake-logger fixtures.
- Evidence: `uv run pytest tests/test_logging.py`.
- Non-vacuity: the absent-identifier case is the witness that the suffix is
  conditional; deleting the conditional must make it fail.

**INV-4 — Celery propagation.** Split into three obligations because the eager
path cannot establish the publish path (Risk R5).

- **INV-4a — publish writes the active identifier.**
  Obligation: when a correlation identifier is active and the application's
  result backend is not `rpc://`, publishing a task sets
  `properties["correlation_id"]` to that identifier.
  Method: contract-level test against the real Celery signal, using a
  non-eager application on a `memory://` broker so a genuine publish occurs.
  Rationale: this is the only configuration in which the mechanism actually
  runs; asserting it in eager mode would assert nothing.
  Domain: identifier active and absent; result backend `cache+memory://` and
  `rpc://`.
  Artefact: `tests/test_worker_request_correlation.py`.
  Evidence: `uv run pytest tests/test_worker_request_correlation.py -k publish`.
  Non-vacuity: the identifier-absent case must leave Celery's own task-id value
  in place, and the `rpc://` case must do the same; both are witnesses that the
  positive assertion can fail. Removing the
  `configure_celery_correlation(app)` call is the seeded fault that must break
  the positive case.

- **INV-4b — the worker restores the identifier from the message.**
  Obligation: given a task request carrying `correlation_id`, the worker-side
  handler makes that value visible through `current_correlation_id()` for the
  duration of the task and restores the previous value afterwards.
  Method: parameterized unit test executed inside a fresh
  `contextvars.Context`, so no ambient value can leak in.
  Rationale: running in a copied context is what removes the vacuity described
  in Risk R5 — without it the assertion passes even with no integration.
  Domain: a message correlation identifier present, absent, and non-string;
  nested tasks; the ambient identifier set to a *different* value before the
  handler runs.
  Artefact: `tests/test_worker_request_correlation.py`.
  Evidence:
  `uv run pytest tests/test_worker_request_correlation.py -k worker_context`.
  Non-vacuity: the "ambient set to a different value" case is the decisive
  witness. Assert that inside the task the value is the *message's* identifier
  and not the ambient one, and that after `task_postrun` the ambient value is
  restored exactly. A test that merely asserts "the value is set" would pass
  vacuously and must not be written.

- **INV-4c — eager mode does not silently pretend to propagate.**
  Obligation: with `task_always_eager=True`, `before_task_publish` does not
  fire, and the plan's documentation says so.
  Method: a single explicit regression test asserting zero firings.
  Rationale: this pins the surprising behaviour so a future reader does not
  write the vacuous test Risk R5 warns about.
  Domain: `create_celery_app` with `task_always_eager=True`.
  Artefact: `tests/test_worker_request_correlation.py`.
  Evidence: `uv run pytest tests/test_worker_request_correlation.py -k eager`.
  Non-vacuity: the companion non-eager case in INV-4a fires exactly once, so
  the counter is demonstrably capable of being non-zero.

**INV-5 — Outbound provider calls carry the identifier.**

- Obligation: when the adapter owns its client and a correlation identifier is
  active, every outbound request carries the configured header with that value;
  when no identifier is active the header is absent; and a header the caller
  already set is not overwritten.
- Method: parameterized unit tests using `httpx.MockTransport`, following the
  pattern already established at `tests/test_llm_openai_adapter_success.py:47`.
- Rationale: `MockTransport` observes the fully built request, which is the
  real contract boundary; RM-4.1.3.f names this technique explicitly.
- Domain: identifier present and absent; the default header name and a
  configured non-default name; a caller-set header of the same name.
- Artefact: `tests/test_llm_openai_adapter_correlation.py`.
- Evidence:
  `uv run pytest tests/test_llm_openai_adapter_correlation.py`.
- Non-vacuity: the absent-identifier case proves the header is conditional, and
  the caller-set case proves the transport does not clobber. Reverting the
  adapter to a bare `httpx.AsyncClient()` is the seeded fault that must break
  the positive case.

**INV-6 — Configuration is validated at start-up, not at first request.**

- Obligation: `load_correlation_settings` rejects an empty header name, a
  malformed IP address or CIDR range, and a CIDR range with host bits set, by
  raising `RuntimeConfigurationError` before the application is built.
- Method: parameterized unit tests.
- Rationale: a finite partition of malformed inputs; the failure mode this
  guards against is a service that boots and then rejects traffic.
- Domain: empty and whitespace-only header names; `10.0.0.5/24` (host bits
  set); `not-an-ip`; a valid mixed IPv4/IPv6 list; an empty list; whitespace
  and trailing commas in the list.
- Artefact: `tests/test_request_correlation_settings.py`.
- Evidence: `uv run pytest tests/test_request_correlation_settings.py`.
- Non-vacuity: the valid-list case must construct successfully, proving the
  rejection is selective rather than blanket.

**INV-7 — The operator-facing configuration surface is stable.**

- Obligation: the resolved settings for a set of representative environment
  mappings match a recorded snapshot, so a change to defaults or parsing is
  visible in review.
- Method: `syrupy` snapshot test.
- Rationale: RM-4.1.3.g makes this an operator contract; multivariant
  environment-to-settings resolution is exactly what snapshots are for.
- Domain: empty environment (all defaults); a fully specified production-shaped
  environment; a header-name override only.
- Artefact: `tests/test_request_correlation_settings.py` with
  `tests/__snapshots__/test_request_correlation_settings.ambr`.
- Evidence: `uv run pytest tests/test_request_correlation_settings.py`, then
  `make lint`, which runs `ambrleaks` over the snapshot directory.
- Non-vacuity: the three variants must differ from one another in the recorded
  snapshot; identical variants would indicate the environment is not being read.

**INV-8 — End-to-end observability through a real inference server.**

- Obligation: a request to the source-to-script slice produces a response header
  and a provider-side request header carrying the same identifier.
- Method: `pytest-bdd` behavioural scenario driving the Falcon app through
  `httpx.ASGITransport` against a live Vidai Mock inference server.
- Rationale: `docs/developers-guide.md:805` requires behavioural tests that
  exercise real `LLMPort` inference paths to use Vidai Mock rather than pure
  mocks. This is the only obligation that observes the whole chain at once.
- Domain: one happy path and one denial path.
- Artefact: `tests/features/request_correlation.feature` with
  `tests/steps/test_request_correlation_steps.py`, reusing
  `tests/steps/generation_orchestration_vidaimock.py`'s
  `start_vidaimock_process` and `find_free_port` helpers.
- Evidence: `uv run pytest tests/steps/test_request_correlation_steps.py -v`.
- Non-vacuity: the scenario asserts the provider-observed header equals the
  response header value, not merely that both are present; two independently
  generated identifiers would fail. The test skips when the `vidaimock` binary
  is absent locally and fails hard when `CI` is set, matching
  `tests/steps/generation_orchestration_vidaimock.py:152-156`.

### Residual gaps

- Behaviour under a real RabbitMQ broker and a real Granian process is not
  exercised by this plan; the Celery obligations use `memory://` and the HTTP
  obligations use the ASGI transport. This is the existing project convention
  and is accepted.
- Concurrency is verified only indirectly. The context variable is per-context
  by construction, and the plan deliberately avoids the thread-local
  `log_context` that would break under asyncio interleaving, but no test drives
  many simultaneous in-flight requests. If a future change reintroduces
  thread-local state, add a concurrency obligation.
- The `'127.0.0.1'` fallback described in AXIOM-3 is exercised through
  `falcon.testing`'s omission of `remote_addr`; whether Granian always populates
  `scope["client"]` in the target deployment is not verified here. The mitigation
  is the empty default plus the start-up warning, not a test.

## Plan of work

### Stage A — orient (no code changes)

Read `docs/roadmap.md:606-626`,
`docs/episodic-podcast-generation-system-design.md:2033-2044`, ADR 002, ADR 003,
and ADR 014. Then read `episodic/api/app.py`, `episodic/api/runtime.py`,
`episodic/api/runtime_config.py`, `episodic/api/dependencies.py`,
`episodic/api/authorization.py`, `episodic/worker/runtime.py`,
`episodic/llm/openai_api/adapter.py`, and `episodic/logging.py`. Use
`leta show <symbol>` rather than reading whole files.

Confirm the working tree is clean and the branch is
`4-1-3-integrate-request-correlation.md`.

### Stage B — red

For each milestone, write the failing test first. Where a test cannot yet import
the module under construction, that import failure **is** the red state and is
acceptable; do not stub the module to make the import succeed. Where a test can
be written against an existing importable surface, mark it
`@pytest.mark.xfail(strict=True, reason="...")`, observe the expected failure,
then remove the marker as part of the green step. No `xfail` marker may survive
into the final tree.

### Stage C — implement

Take the milestones in order. Each ends with all four gates green and a commit.

### Stage D — refactor and document

Fold the documentation, ADR, and roadmap tick into EP-M7, then run the whole
gate suite once more.

## Milestones and plateaus

### EP-M0 — Pin the dependency

- **Outcome:** `falcon_correlate` is installable, importable, and its default
  header name is pinned by a test.
- **Requirements:** RM-4.1.3.a.
- **Edits:**
  - `pyproject.toml`, `[project].dependencies`: insert, in the existing
    alphabetical position between `"falcon>=4.3.1,<5.0"` and
    `"femtologging @ ..."`, the line
    `"falcon-correlate @ git+https://github.com/leynos/falcon-correlate@caea7a6ac804f851f7226ccf9acb3d256cc2d5d4"`.
  - Run `make build` (which runs `uv sync --group dev`) so `uv.lock` updates.
    Commit the lockfile change.
- **Acceptance evidence:**

  ```bash
  uv run python -c "import falcon_correlate; print(falcon_correlate.__all__)"
  ```

  prints a list containing `CorrelationIDMiddlewareASGI`,
  `configure_celery_correlation`, and `AsyncCorrelationIDTransport`.
- **Conformance check:** no public interface, trust boundary, or persisted
  format changes. One new dependency, authorized by `Tolerances`.
- **Recovery:** revert `pyproject.toml` and `uv.lock`, rerun `make build`.
- **Remaining gaps:** nothing is wired yet.
- **Compatibility decision:** none required.

### EP-M1 — The correlation seam and its configuration

- **Outcome:** one episodic-owned module exposes the settings type, the loader,
  the ambient read function, and the correlated-client factory; both composition
  roots can read the configuration from the environment.
- **Requirements:** RM-4.1.3.c; discharges INV-6 and INV-7.
- **New file:** `episodic/request_correlation.py`. Its public surface must be
  exactly:

  ```python
  DEFAULT_CORRELATION_HEADER_NAME: str

  @dc.dataclass(frozen=True, slots=True)
  class CorrelationSettings:
      header_name: str = DEFAULT_CORRELATION_HEADER_NAME
      trusted_sources: tuple[str, ...] = ()
      validate_incoming_ids: bool = True
      echo_response_header: bool = True

      def to_middleware_config(self) -> CorrelationIDConfig: ...

  class CorrelationConfigurationError(ValueError): ...

  def load_correlation_settings(
      environ: cabc.Mapping[str, str] | None = None,
  ) -> CorrelationSettings: ...

  def current_correlation_id() -> str | None: ...

  def build_correlated_async_client(
      *,
      header_name: str = DEFAULT_CORRELATION_HEADER_NAME,
      transport: httpx.AsyncBaseTransport | None = None,
      **client_kwargs: object,
  ) -> httpx.AsyncClient: ...
  ```

  Notes for the implementer:

  - `DEFAULT_CORRELATION_HEADER_NAME` is assigned from
    `falcon_correlate.middleware_config.DEFAULT_HEADER_NAME`. This is the only
    import of that symbol in the repository (Decision D8).
  - `to_middleware_config()` returns
    `CorrelationIDConfig.from_kwargs(header_name=..., trusted_sources=...,
    validator=default_uuid_validator if self.validate_incoming_ids else None,
    echo_header_in_response=self.echo_response_header)`. Let
    `CorrelationIDConfig` raise on malformed ranges and translate the
    `ValueError` into `CorrelationConfigurationError` with a message naming the
    offending environment variable.
  - `current_correlation_id()` returns `correlation_id_var.get()`. It exists so
    that no other episodic module imports `falcon_correlate` directly.
  - `build_correlated_async_client` wraps `transport` (defaulting to a fresh
    `httpx.AsyncHTTPTransport()`) in `AsyncCorrelationIDTransport` and returns
    an `httpx.AsyncClient(transport=wrapped, **client_kwargs)`.
  - Keep the module under 400 lines and give every public symbol a NumPy-style
    docstring, per `AGENTS.md`.
- **Environment variables**, all `UPPER_SNAKE_CASE`, matching the convention in
  `episodic/api/runtime_config.py`:

  | Variable | Default | Meaning |
  | --- | --- | --- |
  | `API_CORRELATION_HEADER_NAME` | `X-Correlation-ID` | Header read on the way in and written on the way out. |
  | `API_CORRELATION_TRUSTED_SOURCES` | empty | Comma-separated IP addresses or CIDR ranges of the ingress or proxy tier. Empty means trust nothing. |
  | `API_CORRELATION_VALIDATE_INCOMING` | `true` | Whether a trusted caller's identifier must be a well-formed UUID. |
  | `API_CORRELATION_ECHO_RESPONSE_HEADER` | `true` | Whether to write the header on responses. |

  Parse booleans with the same tolerant reader style used by
  `episodic/worker/runtime.py:_parse_bool`. Strip whitespace and ignore empty
  entries when splitting the trusted-source list, so
  `"10.0.0.0/8, 192.168.1.0/24,"` parses to two entries.
- **Wiring:**
  - `episodic/api/runtime_config.py`: add
    `correlation: CorrelationSettings = dc.field(default_factory=CorrelationSettings)`
    to `RuntimeConfig`, document it in the class docstring's `Attributes`
    section, and set it in `_load_runtime_config` from
    `load_correlation_settings(environment)`. Translate
    `CorrelationConfigurationError` into `RuntimeConfigurationError` so the
    module's existing error contract is preserved.
  - `episodic/worker/runtime.py`: add
    `correlation: CorrelationSettings = dc.field(default_factory=CorrelationSettings)`
    to `WorkerRuntimeConfig` and populate it in `load_runtime_config`.
- **Red tests:** `tests/test_request_correlation_settings.py` covering INV-6 and
  INV-7; new cases in `tests/test_runtime_configuration.py` following the
  existing dict-passing pattern at `tests/test_runtime_configuration.py:11-84`.
- **Acceptance evidence:** run

  ```bash
  uv run pytest tests/test_request_correlation_settings.py \
    tests/test_runtime_configuration.py -v
  ```

  It fails before the module exists and passes after.
- **Conformance check:** `make check-architecture` passes. The new module is
  ungrouped in `pyproject.toml`'s `[tool.hecate]` configuration, following the
  precedent of `episodic/observability.py` and `episodic/logging.py`. If
  `hecate` reports the module as unclassified, add it to no group rather than
  inventing one, and record the outcome in `Surprises & discoveries`.
- **Recovery:** delete the module and revert the two config files.
- **Remaining gaps:** nothing reads the settings yet.
- **Compatibility decision:** none. `RuntimeConfig` and `WorkerRuntimeConfig`
  are application-internal, pre-1.0, and gain defaulted fields, so no caller
  breaks and no shim is warranted.

### EP-M2 — Middleware wiring

- **Outcome:** every HTTP request carries an identifier on `req.context`, the
  response echoes it when configured, denials carry it, and untrusted callers
  cannot choose it.
- **Requirements:** RM-4.1.3.b; discharges INV-1 and INV-2.
- **Edits:**
  - `episodic/api/dependencies.py`: add
    `correlation: CorrelationSettings = dc.field(default_factory=CorrelationSettings)`
    to `ApiDependencies`, ahead of the existing defaulted fields' validation in
    `__post_init__`. No new validation is needed; `CorrelationSettings`
    validates itself.
  - `episodic/api/app.py`, in `create_app` at line 305: register the correlation
    middleware **before** the authorization middleware:

    ```python
    app.add_middleware(
        CorrelationIDMiddlewareASGI(
            config=dependencies.correlation.to_middleware_config()
        )
    )
    app.add_middleware(AuthorizationMiddleware(dependencies.authorization))
    ```

    Add a comment explaining *why* the order matters — that authorization logs
    its denials and must therefore run after the identifier exists — not *what*
    the line does.
  - `episodic/api/runtime.py`, in `create_app_from_env`: pass
    `correlation=config.correlation` into the `ApiDependencies(...)` construction
    at line 277.
- **Red tests:** `tests/test_api_request_correlation.py` and
  `tests/test_api_request_correlation_properties.py`.
- **Acceptance evidence:**

  ```bash
  uv run pytest tests/test_api_request_correlation.py tests/test_api_request_correlation_properties.py -v
  ```

  Expect the denial cases to show the header on `401` and `403` responses.
- **Conformance check:** ADR 002 still holds — `create_app` reads no
  environment. `make check-architecture` passes.
- **Recovery:** remove the `add_middleware` call and the `ApiDependencies` field.
- **Remaining gaps:** the identifier is not yet in logs, tasks, or provider
  calls.
- **Compatibility decision:** none.

### EP-M3 — Correlation in logs

- **Outcome:** every log line emitted while a request is in flight carries the
  identifier.
- **Requirements:** RM-4.1.3.b (the "denial, error, and resource logs share the
  same request identifier" clause); discharges INV-3.
- **Edits:**
  - `episodic/logging.py`: add a private helper that appends a
    space-separated `correlation_id=<id>` field to a formatted message
    when `current_correlation_id()` returns a value, and returns the
    message unchanged otherwise. Call it from `log_info`, `log_warning`, and `log_error`
    immediately after `_format_message`. Import `current_correlation_id` from
    `episodic.request_correlation`.
  - `episodic/observability.py`: include `correlation_id` in the `extra=`
    payloads of `StructuredLogMetrics._emit_value`,
    `StructuredLogMetrics.increment_counter`,
    `StructuredLogMetrics.observe_latency_ms`, and the span lifecycle records
    emitted by `StructuredLogTracer`, using `current_correlation_id()` and
    omitting the key when it is `None`.
- **Red tests:** new cases in `tests/test_logging.py`; a new case in whichever
  module currently covers `StructuredLogTracer` and `StructuredLogMetrics`.
- **Acceptance evidence:** `uv run pytest tests/test_logging.py -v` plus the
  observability test module. Then confirm the end-to-end shape by running the
  denial test from EP-M2 and inspecting a captured log line, which must read
  like:

  ```plaintext
  authorization_denied method=GET path=/v1/series-profiles correlation_id=019b3c9d61aa7d2f9e1b2c3d4e5f6071
  ```

- **Conformance check:** the change is confined to two ungrouped infrastructure
  modules; no domain module gains a dependency.
- **Recovery:** revert the helper and its three call sites.
- **Remaining gaps:** tasks and provider calls.
- **Compatibility decision:** none. Log text is not an interface with an
  external consumer; if a snapshot test captures a log line, update the
  snapshot deliberately and note it in `Surprises & discoveries`.

### EP-M4 — Celery propagation

- **Outcome:** a task published while a request is in flight carries the
  identifier on the wire, and the worker restores it around execution.
- **Requirements:** RM-4.1.3.d; discharges INV-4a, INV-4b, INV-4c.
- **Edits:**
  - `episodic/worker/runtime.py`, in `create_celery_app` immediately after the
    `app.conf.update(...)` block and before `register_scaffold_tasks`: call
    `configure_celery_correlation(app)`. Import it through
    `episodic.request_correlation`, which should re-export it so that
    `falcon_correlate` remains imported in exactly one place.
  - In the same function, when `config.result_backend` begins with `rpc://`,
    emit a warning through `log_warning` explaining that Celery's RPC result
    backend reserves the AMQP `correlation_id` property, so request correlation
    will not reach workers. Reference Risk R3.
  - Also warn when `config.correlation.trusted_sources` contains a loopback
    address, per Risk R2. Put this warning in the API composition root
    (`episodic/api/runtime.py`) rather than the worker, since it is an
    HTTP-boundary concern.
- **Red tests:** `tests/test_worker_request_correlation.py`, structured exactly
  as INV-4a, INV-4b, and INV-4c prescribe. Read those obligations before writing
  a line of test code; the naive eager test they warn against is the default
  mistake here.
- **Acceptance evidence:**

  ```bash
  uv run pytest tests/test_worker_request_correlation.py -v
  ```

  Expect the publish case to show `properties["correlation_id"]` rewritten under
  a `cache+memory://` backend and left alone under `rpc://`.
- **Conformance check:** ADR 003 still holds; `create_celery_app` remains the
  single worker composition root. `episodic.worker.tasks` is unchanged.
- **Recovery:** remove the `configure_celery_correlation` call and the warnings.
- **Remaining gaps:** provider calls.
- **Compatibility decision:** the AMQP `correlation_id` property is a wire
  format shared with any already-deployed worker. Overwriting it is the
  library's documented behaviour and is safe here because no deployed consumer
  reads it: `episodic/worker/tasks.py` carries its own domain `correlation_id`
  inside the task payload, and the `rpc://` guard protects the only Celery
  feature that depends on the property. Record this reasoning in ADR-018.

### EP-M5 — Outbound provider calls

- **Outcome:** the inference provider receives the identifier on every request
  the adapter makes with its own client.
- **Requirements:** RM-4.1.3.e; discharges INV-5.
- **Edits:**
  - `episodic/llm/openai_api/` config module: add
    `correlation_header_name: str = DEFAULT_CORRELATION_HEADER_NAME` to
    `OpenAICompatibleLLMConfig`, with a docstring entry.
  - `episodic/llm/openai_api/adapter.py:135`: replace
    `self._client = client if client is not None else httpx.AsyncClient()` with
    a construction that, in the owned case, calls
    `build_correlated_async_client(header_name=config.correlation_header_name)`.
    Leave `_owns_client` semantics untouched. Extend the class docstring's
    `client` parameter description to state the ownership contract from Risk R7:
    an injected client is the caller's responsibility, and callers who want
    correlation on an injected client should build it with
    `build_correlated_async_client`.
  - `episodic/api/runtime.py:81`, in `_build_llm_port`: pass
    `correlation_header_name=config.correlation.header_name` into
    `OpenAICompatibleLLMConfig(...)`.
- **Red tests:** `tests/test_llm_openai_adapter_correlation.py`, using
  `httpx.MockTransport` in the style of
  `tests/test_llm_openai_adapter_success.py:47`. Because the adapter now builds
  its own transport, the test supplies the mock through
  `build_correlated_async_client(transport=httpx.MockTransport(handler))` for
  the injected case and asserts the owned case by patching the default transport
  factory — or, more simply, by asserting on the request the mock server
  receives in the behavioural test. Prefer the explicit factory route; keep the
  patching to a minimum.
- **Acceptance evidence:**

  ```bash
  uv run pytest tests/test_llm_openai_adapter_correlation.py -v
  ```

- **Conformance check:** `episodic.llm.openai_api` remains an outbound adapter
  and imports only the episodic seam plus `httpx`. `make check-architecture`
  passes.
- **Recovery:** revert the three edits.
- **Remaining gaps:** behavioural coverage and documentation.
- **Compatibility decision:** none. `OpenAICompatibleLLMConfig` gains a
  defaulted field; every existing construction site keeps working.

### EP-M6 — Behavioural, property, and snapshot coverage

- **Outcome:** the whole chain is observed end to end against a live inference
  server.
- **Requirements:** RM-4.1.3.f; discharges INV-8 and completes INV-1 and INV-7.
- **New file:** `tests/features/request_correlation.feature`:

  ```gherkin
  Feature: Request correlation across HTTP, tasks, and provider calls

    Background:
      Given a Vidai Mock inference server is running
      And the HTTP service trusts correlation identifiers from the test ingress

    Scenario: A generated correlation identifier is echoed to the caller
      When an anonymous client requests a health endpoint
      Then the response carries a correlation header
      And the correlation header value is a well-formed identifier

    Scenario: A trusted ingress may supply the correlation identifier
      When the ingress requests a health endpoint with correlation identifier "0195f1d2-3c4b-7a8d-9e0f-112233445566"
      Then the response correlation header equals "0195f1d2-3c4b-7a8d-9e0f-112233445566"

    Scenario: An untrusted client cannot choose the correlation identifier
      When an untrusted client requests a health endpoint with correlation identifier "0195f1d2-3c4b-7a8d-9e0f-112233445566"
      Then the response correlation header does not equal "0195f1d2-3c4b-7a8d-9e0f-112233445566"

    Scenario: A malformed identifier from a trusted ingress is replaced
      When the ingress requests a health endpoint with correlation identifier "not-a-correlation-id"
      Then the response correlation header does not equal "not-a-correlation-id"
      And the correlation header value is a well-formed identifier

    Scenario: A denied request still carries the correlation identifier
      When an unauthorized client requests a protected endpoint
      Then the response status is 401
      And the response carries a correlation header

    Scenario: Provider calls carry the caller's correlation identifier
      When a draft script is generated through the inference provider
      Then the provider received the same correlation identifier as the response header
  ```

- **New file:** `tests/steps/test_request_correlation_steps.py`. Reuse
  `find_free_port` and `start_vidaimock_process` from
  `tests/steps/generation_orchestration_vidaimock.py`. Drive the app through
  `httpx.ASGITransport(app=create_app(dependencies))` with
  `base_url="http://testserver"`, following `tests/fixtures/api.py:79-93`. To
  observe the provider-side header, configure the Vidai Mock response template
  to echo the received `X-Correlation-ID` back in the completion body, so the
  assertion reads a value that genuinely crossed the wire rather than one the
  test already knows.
  Note that `tests/steps/test_*_steps.py` modules are exempt from the
  future-annotations lint (`docs/developers-guide.md`, §Linting), because
  `pytest-bdd` evaluates step annotations at runtime.
- **Acceptance evidence:**

  ```bash
  uv run pytest tests/steps/test_request_correlation_steps.py -v
  ```

  Expect six scenarios passing, or six skips with
  `vidaimock executable not found in PATH` on a machine without the binary.
- **Conformance check:** trace links in `Conformance basis` are current.
- **Recovery:** the feature and step files are additive; delete them.
- **Remaining gaps:** documentation.
- **Compatibility decision:** none.

### EP-M7 — Documentation, ADR, roadmap

- **Outcome:** an operator can configure and debug correlation without reading
  the source.
- **Requirements:** RM-4.1.3.g.
- **Edits:**
  - **New:** `docs/adr/adr-018-request-correlation-propagation.md`. Follow the
    section order mandated by `docs/documentation-style-guide.md:414-491`:
    Status, Date, Context and Problem Statement, Decision Drivers, Options
    Considered, Decision Outcome, Known Risks and Limitations. Record Decisions
    D2, D4, D5, D7, the `rpc://` interaction, and the trusted-source security
    model. State plainly that the HTTP request correlation identifier is
    distinct from the domain `correlation_id` and reference ADR 015.
  - `docs/users-guide.md`: add an operator-facing section giving the four
    environment variables, the default header name, the meaning of
    `API_CORRELATION_TRUSTED_SOURCES` as *the ingress or proxy source range,
    not the end client's address*, and an explicit warning that listing a
    loopback address can make every request trusted when the ASGI server does
    not report a peer address (Risk R2). Include the `curl -i` transcript from
    `Purpose / big picture`.
  - `docs/developers-guide.md`: add the internal contract — the
    `episodic.request_correlation` seam, the rule that `falcon_correlate` is
    imported in exactly one module, the reason `ContextualLogFilter` is unused
    (Decision D5), the local debugging workflow, and the Celery eager-mode trap
    from Risk R5 so nobody writes the vacuous test later.
  - `docs/episodic-podcast-generation-system-design.md:2033-2044`: replace the
    "still needs a dedicated request-correlation workstream" paragraph with a
    description of what now exists, linking to ADR 018.
  - `docs/contents.md`: index ADR 018 and this ExecPlan.
  - `docs/roadmap.md:606`: tick 4.1.3 to `[x]`.
- **Acceptance evidence:** `make markdownlint`, `make spelling`, and `make nixie`
  pass, then the full gate suite.
- **Conformance check:** every discovery in this plan is reflected upstream; no
  unrecorded deviation remains.
- **Recovery:** documentation edits are reversible with `git revert`.
- **Remaining gaps:** none.
- **Compatibility decision:** none.

## Concrete steps

Run everything from the repository root,
`/home/leynos/.lody/repos/github---leynos---episodic/worktrees/d18130de-405b-4adf-a88f-ccf6940c7394`.

Confirm the branch:

```bash
git branch --show-current
```

```plaintext
4-1-3-integrate-request-correlation.md
```

Install dependencies after editing `pyproject.toml`:

```bash
make build
```

Run the four gates. Do **not** run them in parallel; the build cache rewards
sequential runs. Capture output for review, because long output is truncated in
the terminal:

```bash
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-$(git branch --show-current).out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-$(git branch --show-current).out
make lint      2>&1 | tee /tmp/lint-episodic-$(git branch --show-current).out
make test      2>&1 | tee /tmp/test-episodic-$(git branch --show-current).out
```

Run a single focused test during red-green work:

```bash
uv run pytest tests/test_request_correlation_settings.py -v
```

Fix formatting before committing:

```bash
make fmt
```

Commit after each milestone, with a message naming the milestone and the
roadmap item.

## Validation and acceptance

**Definition of done.**

- Tests: `make test` passes with no skips other than the Vidai Mock skips on a
  machine lacking the binary, and every obligation in `Verification plan` is
  discharged by a named artefact.
- Verification: INV-1 through INV-8 each have a passing artefact **and** a
  recorded non-vacuity check. An obligation whose non-vacuity check was not
  performed is not discharged.
- Lint and typecheck: `make check-fmt`, `make typecheck`, and `make lint` all
  exit zero. `make lint` includes `hecate` architecture checks, Ruff, both
  Pylint passes, `ambrleaks` over the snapshots, and the blocking Skylos
  dead-code scan. If Skylos reports the new public functions as dead because
  their only callers are composition roots, add a typed entry-point rule under
  `[tool.skylos.dead_code]` naming the fully qualified symbol and the verified
  runtime caller, as `AGENTS.md` requires — do not use the allow-list unless an
  entry-point rule cannot express the boundary.
- Documentation: `make markdownlint`, `make spelling`, and `make nixie` pass.
- Security: the trusted-source default is empty, and INV-1's
  `rejected-untrusted` class is exercised.

**Manual acceptance.** Start the service with correlation configured to trust
nothing and run the two `curl -i` commands from `Purpose / big picture`. Both
responses must carry an `X-Correlation-ID` header. Repeat with
`API_CORRELATION_ECHO_RESPONSE_HEADER=false` and confirm the header disappears
while the log lines still carry the identifier.

**Red-Green-Refactor evidence.** For each milestone record: the red command and
its expected failure; the green command and the passing result; and the gate
commands after refactoring. Paste short transcripts into `Artefacts and notes`.

## Idempotence and recovery

Every step is re-runnable. `make build` is idempotent. Test files are additive.
The only edits to existing files are additive fields, one `add_middleware` call,
one `configure_celery_correlation` call, and three logging helper call sites;
each is reversible with `git revert` of the milestone commit. Nothing in this
plan writes to a database, migrates a schema, or changes a persisted format.

If `uv sync` fails while fetching the pinned commit, confirm network access to
`github.com` and that the SHA still exists on `main`; the repository is public,
so no credential is required.

## Artefacts and notes

To be filled in during implementation with the red and green transcripts for
each milestone.

## Interfaces and dependencies

At the end of EP-M5 the following must exist.

In `episodic/request_correlation.py`:

```python
DEFAULT_CORRELATION_HEADER_NAME: str

@dc.dataclass(frozen=True, slots=True)
class CorrelationSettings:
    header_name: str = DEFAULT_CORRELATION_HEADER_NAME
    trusted_sources: tuple[str, ...] = ()
    validate_incoming_ids: bool = True
    echo_response_header: bool = True

    def to_middleware_config(self) -> CorrelationIDConfig: ...

class CorrelationConfigurationError(ValueError): ...

def load_correlation_settings(
    environ: cabc.Mapping[str, str] | None = None,
) -> CorrelationSettings: ...

def current_correlation_id() -> str | None: ...

def build_correlated_async_client(
    *,
    header_name: str = DEFAULT_CORRELATION_HEADER_NAME,
    transport: httpx.AsyncBaseTransport | None = None,
    **client_kwargs: object,
) -> httpx.AsyncClient: ...

def configure_celery_correlation[CeleryAppT](app: CeleryAppT) -> CeleryAppT: ...
```

In `episodic/api/dependencies.py`, `ApiDependencies` gains:

```python
correlation: CorrelationSettings = dc.field(default_factory=CorrelationSettings)
```

In `episodic/api/runtime_config.py`, `RuntimeConfig` gains the same field, and
in `episodic/worker/runtime.py`, `WorkerRuntimeConfig` gains it too.

In `episodic/llm/openai_api/`, `OpenAICompatibleLLMConfig` gains:

```python
correlation_header_name: str = DEFAULT_CORRELATION_HEADER_NAME
```

Dependency added to `pyproject.toml`:

```plaintext
falcon-correlate @ git+https://github.com/leynos/falcon-correlate@caea7a6ac804f851f7226ccf9acb3d256cc2d5d4
```

No port protocol changes. No new dependency other than the one above.
