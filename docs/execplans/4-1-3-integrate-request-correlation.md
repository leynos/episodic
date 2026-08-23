# Integrate request correlation across HTTP, tasks, and outbound provider calls (4.1.3)

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, `Outcomes & Retrospective`, `Conformance Basis`, and
`Verification Plan` must be kept up to date as work proceeds.

Status: DRAFT — revised after a six-lens design review. See
`Design review outcomes`.

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
request, echoed back to the caller in a response header, written into the log
lines the request produces, copied onto any Celery task the request publishes,
and sent as an HTTP header on every outbound provider call the request makes
from within the request context.

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
same identifier on the response, so the `401` the caller saw can be matched to
the log line the service wrote:

```bash
curl -i -H 'Authorization: Bearer wrong' http://127.0.0.1:8000/v1/series-profiles
```

```http
HTTP/1.1 401 Unauthorized
X-Correlation-ID: 019b3c9d61aa7d2f9e1b2c3d4e5f6071
```

The denial log line today reads exactly this, at `DEBUG`, and reaches nobody
because logging is never configured in the container:

```plaintext
Authorization denied with AuthorizationDecision.UNAUTHORIZED for GET /v1/series-profiles.
```

After EP-M3b it reads this, at `WARNING`, on the container's standard error:

```plaintext
Authorization denied with AuthorizationDecision.UNAUTHORIZED for GET /v1/series-profiles. correlation_id=019b3c9d61aa7d2f9e1b2c3d4e5f6071
```

Those two facts — that the denial path logs at `DEBUG` through a call the
logging helpers do not cover, and that femtologging is never configured at all
in the deployed image — are the difference between this feature working and
this feature being theatre. Both are fixed by this plan; see Decisions D5 and
D6.

And a request that reaches the inference provider causes the provider to receive
the same value on the wire:

```plaintext
POST /v1/chat/completions
X-Correlation-ID: 019b3c9d5f7a7c1e8f0a1b2c3d4e5f60
```

## Design review outcomes

This plan was stress-tested by a six-lens design-review panel before
implementation: structural integrity, alternatives, scaling and observability,
contracts, failure modes and operations, and long-term viability. The review
falsified four premises of the first draft. Each is recorded under
`Surprises & discoveries` with its evidence, and each changed the plan:

1. `make check-architecture` cannot enforce the boundary the plan claimed it
   enforced. Constraint C2 is reworded and a real mechanism is added.
2. Not every log call funnels through the `episodic/logging.py` helpers — 29 of
   48 call sites bypass them, including the authorization denial the roadmap
   names. EP-M3b now schedules that edit and the plan no longer claims complete
   coverage.
3. `import falcon_correlate` registers the Celery signal handlers globally, at
   import time. `configure_celery_correlation(app)` is declarative, not
   load-bearing, so INV-4a's original negative control was unfalsifiable.
4. `episodic/observability.py` is 399 lines against a **blocking** 400-line
   Pylint limit, so the planned edit would fail `make lint`. EP-M3a now splits
   the module first.

The panel also rejected two fixes that looked correct and are not. Both are
recorded so nobody re-proposes them.

## Constraints

Hard invariants. Violating one of these requires escalation, not a workaround.

- **C1. `create_app` stays pure.** `episodic/api/app.py:304` must not read
  environment variables or construct infrastructure. ADR 002
  (`docs/adr/adr-002-http-service-composition-root.md`) makes
  `episodic/api/runtime.py` the only module that reads configuration for the
  HTTP service. Correlation configuration arrives through `ApiDependencies`,
  already validated, so `create_app` cannot raise a configuration error.
- **C2. Hexagonal boundaries hold, and this is a review obligation, not a gate.**
  Domain and application modules must not import `falcon_correlate`, `falcon`,
  or `httpx`. Be clear about what enforces this: `hecate` checks
  **internal** package edges only. `include_external_packages` defaults to
  `False` (`hecate/config.py:91`) and `[tool.hecate]` at `pyproject.toml:785`
  does not set it, so `make check-architecture` sees **zero** third-party
  imports and would pass a domain module that imported `httpx` directly. The
  seam described in D2 is therefore the only real mechanism, backed by the
  import-cost test in INV-9.
- **C3. The correlation identifier never enters the domain.** No domain entity,
  port signature, or persisted record gains a request correlation field. ADR 015
  (`docs/adr/adr-015-upload-and-idempotency-ports.md:170`) already records that
  "correlation to a specific request belongs in logs and trace context".
- **C4. Untrusted callers cannot choose their identifier, and no caller can
  choose an arbitrary string.** An incoming correlation header is honoured only
  when the request arrives from a configured trusted source. The default
  trusted-source list is empty. Independently of trust, an accepted identifier
  is sanitized at the episodic seam before it reaches a log line, a response
  header, or an outbound request. See D9.
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
- **C8. No module exceeds 400 lines.** `pyproject.toml:221` sets
  `max-module-lines = 400` and `too-many-lines` is enabled at
  `pyproject.toml:408`, so this is a blocking `make lint` failure, not a style
  preference. `episodic/observability.py` is currently at 399.

## Tolerances (exception triggers)

- **Scope.** If the change touches more than 36 files or more than 2,400 net
  lines of code and documentation, stop and escalate. The budget rose from the
  first draft because EP-M3a (splitting `episodic/observability.py`) and
  EP-M3b (routing 29 bypassing log call sites) were not costed originally.
- **Interface.** If any port protocol in `episodic/canonical/ports.py`,
  `episodic/llm/ports.py`, `episodic/cost/ports.py`, or
  `episodic/metrics_ports.py` must change signature, stop and escalate. This
  plan expects zero port changes.
- **Dependencies.** `falcon-correlate` is the only new dependency this plan
  authorizes. If a second one appears necessary, stop and escalate.
- **Iterations.** If a single failing test is not green after four focused
  attempts, stop, write the findings into `Surprises & discoveries`, and
  escalate.
- **Upstream library defects.** If `falcon-correlate` must be patched or
  monkey-patched to satisfy a requirement, stop and escalate; the correct
  response is an upstream issue and a revised pin, not a local shim. Two such
  issues are already identified and listed under EP-M0.
- **Ambiguity.** If the operator-facing header contract admits two readings that
  produce materially different deployments, stop and present the options.
- **Deviation.** D10 proposes an addition beyond the roadmap's literal wording.
  If the reviewer rejects it, stop before EP-M5 and re-plan that milestone.

## Risks

- **Risk R1: `falcon-correlate` is an unpublished single-author dependency on a
  security-relevant trust boundary.**
  Upstream cut **`v0.1.0`** on 2026-08-23 in response to this plan's first
  draft, resolving to `caea7a6ac804f851f7226ccf9acb3d256cc2d5d4` — the exact
  commit every empirical finding in this plan was probed against, so none of
  them needs re-verifying. That removes the worst of the original risk: the pin
  is now a deliberate semantic boundary rather than a date-chosen Dependabot
  bump, and there is a real GitHub release. Verified:
  `uv run --with "falcon-correlate @ git+...@v0.1.0"` installs and reports
  version `0.1.0`.
  What remains: the package is still absent from PyPI (`GET
  https://pypi.org/pypi/falcon-correlate/json` returns
  `{"message": "Not Found"}`), it has one author, and `0.1.0` is an alpha-status
  release carrying the trust decision described in R2 and the private-attribute
  coupling described in R6. A Git tag is also mutable in a way a commit is not.
  Severity: low. Likelihood: low.
  Mitigation: pin `@v0.1.0`. `uv.lock` records the **resolved commit**, so a
  moved tag would show up as a lockfile change in review rather than silently
  altering behaviour — check that the locked revision is `caea7a6a` when
  committing EP-M0. State the supply-chain posture in ADR-018 in a sentence
  rather than a footnote, and record a dated review item so the pin has an
  upgrade trigger rather than ageing silently.

- **Risk R2: the trusted-source model does not survive the deployment topology.**
  This replaces the first draft's R2, which aimed at the wrong hazard. Three
  compounding facts:
  1. `docs/infrastructure-design.md:40,46` puts **Traefik** in front on DOKS.
     Falcon's `remote_addr` is the TCP peer, so the address seen is a Traefik
     **pod** IP drawn from the cluster pod CIDR. Pod IPs change on every
     rollout, restart, or autoscale event, and both node pools autoscale
     (`docs/infrastructure-design.md:155`). There is no stable narrow range an
     operator can configure.
  2. The only stable superset is the cluster-wide pod CIDR, which trusts
     **every pod in every namespace**. `charts/episodic/templates/` contains no
     NetworkPolicy and `infra/gitops-template/platform/traefik/kustomization.yaml`
     is an empty `resources: []` placeholder, so any pod can reach the Service.
  3. Unlike `X-Forwarded-For`, which a proxy generates, `X-Correlation-ID` is
     relayed **verbatim**. Traefik does not strip or rewrite it, and
     `charts/episodic/values.yaml:89` has `ingress.annotations: {}` with no
     Traefik `Middleware` custom resource anywhere in the tree. So the moment
     the ingress is trusted, every internet client controls the value.
  Severity: high. Likelihood: high if the feature is enabled as documented.
  Mitigation: keep the empty default; make sanitization unconditional (D9) so
  that trusting the ingress cannot yield a hostile value; ship a Traefik
  `Middleware` in the chart that overwrites the header at the edge (EP-M7), so
  that "trust the ingress" means what an operator would assume; and say in the
  users' guide, in as many words, that listing the pod CIDR is not a supported
  configuration.
  Note in passing: Granian **does** populate `scope["client"]` — verified,
  `granian/asgi.py:147` dereferences `scope['client'][0]` unguarded — so
  Falcon's `'127.0.0.1'` fallback does not fire under the deployed server. That
  was the first draft's stated hazard and it is largely theoretical here. The
  fallback case is still covered by INV-1 because `falcon.testing` omits
  `scope['client']` when `remote_addr` is not supplied, making it free to test.

- **Risk R3: an `rpc://` Celery result backend silently disables propagation.**
  `falcon_correlate.celery.propagate_correlation_id_to_celery` returns without
  writing `properties["correlation_id"]` when the active application's result
  backend URI starts with `rpc://`, because Celery's RPC backend uses that AMQP
  property to route results. `EPISODIC_CELERY_RESULT_BACKEND` is
  operator-supplied, so an operator can disable correlation without any signal.
  A second-order hazard: the library consults `celery.current_app.backend`, a
  process-global lookup evaluated per publish, **not** the application being
  published on. In a process holding two Celery applications, or in the API
  process where `current_app` is a lazily created default, the guard may consult
  the wrong application entirely.
  Severity: medium. Likelihood: low.
  Mitigation: refuse to start unless `EPISODIC_CELERY_ALLOW_UNCORRELATED_RPC_BACKEND=true`
  is set, so a degraded deployment is a recorded, reviewable choice rather than
  a warning nobody reads three weeks later. Assert on `app.backend.as_uri()`,
  matching what the library actually checks, rather than on the raw environment
  string. Cover both branches with INV-4c.

- **Risk R4: femtologging cannot carry ambient structured context.**
  `femtologging.log_context` is thread-local, and empirically its fields do not
  reach records emitted by `femtologging.get_logger(...)` at all — a callable
  formatter observes `metadata.key_values == {}` inside a `log_context` block.
  Holding a thread-local context across an `await` would also leak between
  concurrent asyncio requests.
  Severity: high. Likelihood: certain.
  Mitigation: Decision D5. Two apparent escapes were tested and rejected; see
  `Surprises & discoveries`.

- **Risk R5: Celery verification is vacuous by default in two distinct ways.**
  First, with `task_always_eager=True` Celery never publishes, so
  `before_task_publish` does not fire, and the task body runs in the caller's
  own context, so the correlation variable is already set regardless of whether
  any integration exists. Second, `configure_celery_correlation(app)` is not
  what wires anything — `import falcon_correlate` registers the handlers
  globally at import time, so deleting the call changes nothing observable.
  Severity: high. Likelihood: high — the roadmap text asks for "Celery
  eager-mode tests", which invites the first mistake, and the second is
  invisible without reading the library's module footer.
  Mitigation: obligations INV-4a, INV-4b, and INV-4c, each with a negative
  control that has been checked against the library's actual behaviour.

- **Risk R6: the trust check reads a private attribute of the library.**
  `falcon_correlate/middleware.py:161,170` accesses
  `self._config._parsed_networks`. An upstream refactor of that private field
  would break trust evaluation **silently**: `if not self._config._parsed_networks:
  return False` would become a permanent deny rather than an error.
  Severity: medium. Likelihood: low, rising on every pin bump.
  Mitigation: INV-1 must assert the `accepted-incoming` case against a real
  CIDR, not only the deny cases, so a fail-closed regression is caught at the
  gate.

- **Risk R7: injected `httpx` clients bypass correlation.**
  `OpenAICompatibleLLMAdapter` accepts a caller-supplied client
  (`episodic/llm/openai_api/adapter.py:130`), and every existing adapter test
  fixture injects one (`tests/fixtures/llm.py:160-190`), as does
  `tests/steps/no_qa_generation_slice_support.py:215`.
  Severity: medium. Likelihood: certain without a fix.
  Mitigation: D10 adds `correlate_client(client)`, a one-line retrofit using an
  httpx event hook, so the hole can be **closed** rather than documented. The
  no-QA slice's chaos header is set post-construction at line 256, so that call
  site can adopt it without losing chaos injection.

- **Risk R8: correlation identifiers are unbounded and unescaped.**
  `falcon_correlate`'s `_get_incoming_header_value` only calls `.strip()`. With
  `validate_incoming_ids` disabled and a trusted source, an arbitrary string
  reaches the context variable. Verified end to end against Granian: a
  **60,000-byte** `X-Correlation-ID` was accepted, stored, and echoed in full.
  Verified separately: the value `abc method=GET path=/admin principal_id=root`
  round-trips intact, and because D5 appends the identifier as the **last**
  logfmt field, an injected pair wins in a last-wins parser such as Loki's
  `| logfmt`. That is audit-trail forgery plus a log-volume amplification
  primitive, and under EP-M5 the same string crosses an external trust boundary
  to the inference provider.
  Severity: high. Likelihood: medium.
  Mitigation: D9 — sanitize unconditionally at the episodic seam, before the
  value can reach a log line, a response header, or an outbound request.

- **Risk R9: nothing observes correlation silently failing.**
  Every diagnostic the library emits goes to a standard-library logger with no
  handler. The most important one — "Correlation ID failed validation,
  generating new ID", the signal that a trusted ingress supplied a bad
  identifier — is at `DEBUG` and is dropped entirely. Nothing counts accepted
  against regenerated identifiers. The two most likely production failures are
  both silent: an ingress range that stopped matching after a reschedule, and an
  `rpc://` backend disabling task propagation.
  Severity: medium. Likelihood: high.
  Mitigation: D11 adds a bounded-cardinality `correlation_id_source` counter
  over exactly the four classes INV-1 already partitions.

- **Risk R10: `transport=` silently disables environment proxies and TLS
  settings.**
  `httpx/_client.py:1399`: `allow_env_proxies = trust_env and transport is None`,
  and `_client.py:1442` returns a supplied transport unchanged. The adapter
  today constructs a bare `httpx.AsyncClient()`, which honours `HTTPS_PROXY`,
  `NO_PROXY`, `verify`, and `limits`. Once a transport is supplied, **all of
  those are silently ignored**. A deployment behind an egress proxy would lose
  provider connectivity with no error.
  Severity: medium. Likelihood: low today, certain the day an egress proxy
  appears.
  Mitigation: `build_correlated_async_client` constructs the inner
  `httpx.AsyncHTTPTransport` explicitly and forwards `verify`, `limits`, and
  `proxy` to it; the factory signature does not accept kwargs that httpx would
  discard. See D12 and INV-10.

- **Risk R11: correlation ends silently at three concurrency boundaries.**
  Measured: a gevent greenlet receives a **fresh empty** context, not a copy of
  its spawner's — the opposite of `asyncio.create_task`. So `gevent.spawn` loses
  the identifier. Subinterpreters
  (`episodic/concurrent_interpreters.py:118-144`) cannot carry contextvars at
  all. `asyncio.to_thread` does preserve it. Separately, Celery's **prefork**
  pool copies no context whatsoever: every task in a worker child runs in the
  same context, so a missed `task_postrun` leaks a stale identifier into every
  later task in that child — logs that actively lie, which is worse than no
  correlation.
  Severity: medium. Likelihood: medium.
  Mitigation: AXIOM-9 states the pool semantics; INV-4d covers the prefork
  sequential-leak case; the developers' guide names the three boundaries.

- **Risk R12: `episodic/observability.py` is one line under a blocking limit.**
  The file is 399 lines and C8's limit is 400, enforced by an enabled
  `too-many-lines` Pylint rule. The originally planned edit would have failed
  `make lint` immediately.
  Severity: low, now that it is known. Likelihood: certain if unaddressed.
  Mitigation: EP-M3a splits the module before EP-M3b touches it, and renames the
  roughly twenty Skylos entry-point rules that name `episodic.observability.*`
  symbols in lockstep.

## Progress

- [ ] EP-M0 Pin `falcon-correlate` at `v0.1.0`; file two upstream issues.
- [ ] EP-M1 Correlation seam, sanitization, and runtime configuration.
- [ ] EP-M2 Falcon ASGI middleware wiring ahead of authorization.
- [ ] EP-M3a Split `episodic/observability.py` below the 400-line limit.
- [ ] EP-M3b Bootstrap logging and carry the identifier into log lines.
- [ ] EP-M4 Celery publish and worker propagation.
- [ ] EP-M5 Outbound provider-call correlation.
- [ ] EP-M6a Header-contract behavioural scenarios (no inference server).
- [ ] EP-M6b Provider echo-back scenario against Vidai Mock.
- [ ] EP-M7 Documentation, ADR, Traefik middleware, roadmap tick.

## Surprises & discoveries

Findings established by probing the runtime, not by reading documentation. Each
has been verified; do not re-litigate them without new evidence.

- **Observation:** `except OSError, RuntimeError, TypeError, ValueError:` at
  `episodic/api/authorization.py:114` and the three similar clauses at
  `episodic/api/errors.py:367`,
  `episodic/api/resources/generation_runs.py:270`, and
  `episodic/generation/launcher.py:501` are **valid**, not Python 2 relics.
  **Evidence:** PEP 758 removed the parenthesis requirement in Python 3.14, and
  `uv run python -m compileall -q` over all four files exits zero.
  **Impact:** do not "fix" them. This is a recurring false positive.

- **Observation:** `femtologging.log_context` fields never reach records emitted
  by `femtologging.get_logger(...)`.
  **Evidence:** a callable formatter installed through
  `StreamHandlerBuilder.stderr().with_formatter(fn)` observes
  `metadata.key_values == {}` inside `with log_context(correlation_id="abc123")`.
  `FemtoLogger` has no structured-field API at all.
  **Impact:** drives Decision D5.

- **Observation:** two apparent escapes from the femtologging limitation were
  tested and both fail, for reasons worth recording.
  **Evidence:** `StdlibHandlerAdapter` builds a real `logging.LogRecord` and
  does run standard-library filters — but on the femtologging **worker thread**,
  where the request's context variables are invisible. A probe filter observed
  `is_main=False`, `cv.get() is None`, and emitted `correlation_id=-`. That is a
  silent-wrong-value trap, not an error. `PythonCallbackFilterBuilder` genuinely
  works — the callback runs on the producer thread with the caller's context and
  its mutations do reach `metadata.key_values` — but femtologging **rejects
  handler filters** outright (`config.py:176`), logger filters **do not
  cascade** to child loggers, and the default formatter does not render
  `key_values`. So there is no single attach point.
  **Impact:** confirms D5's shape while correcting the first draft's stated
  rationale, which said only "it is a `logging.Filter` and only works with the
  standard library".

- **Observation:** D5's coverage claim in the first draft was false. **29 of 48**
  logging call sites in `episodic/` bypass the three helpers.
  **Evidence:** 19 calls through `log_info`/`log_warning`/`log_error`; 29 direct
  `logger.*` calls. The most damaging are
  `episodic/api/authorization.py:176` — the authorization denial, which the
  roadmap names explicitly — and `episodic/llm/openai_api/utils.py:108-111`
  (`_log_error_event`), the structured provider-error path that fires on exactly
  the provider timeouts this plan exists to correlate.
  **Impact:** EP-M3b now schedules both edits, and the plan no longer claims
  complete coverage.

- **Observation:** the authorization denial logs at `DEBUG` through a direct
  `logger.log` call, and the first draft's marquee transcript was fabricated.
  **Evidence:** `episodic/api/authorization.py:171-179` reads
  `logger.log(LogLevel.DEBUG, f"Authorization denied with {decision} for
  {context.method} {context.path}.")`. `log_warning` is used only on the 503
  adapter-failure path at line 115. No `authorization_denied method=... path=...`
  message exists anywhere in the codebase.
  **Impact:** the `Purpose` section now quotes the real message. EP-M3b promotes
  the denial to `WARNING` through a helper.

- **Observation:** `episodic/api/errors.py` and `episodic/api/resources/*.py`
  emit **no** log calls at all.
  **Evidence:** grep across both.
  **Impact:** the roadmap's "error and resource logs" clause is vacuously
  satisfied today. Say so rather than implying coverage.

- **Observation:** `import falcon_correlate` imports Celery and registers three
  signal handlers globally, at import time.
  **Evidence:** `falcon_correlate/celery.py` calls `_maybe_connect_celery_signals()`
  at module scope and `__init__.py` imports `.celery`. Probe: `celery in
  sys.modules` goes `False` → `True`, and `before_task_publish.receivers` gains
  `falcon_correlate.celery.propagate_correlation_id_to_celery`.
  `configure_celery_correlation(app)` ignores `app` entirely; its own docstring
  says "signal registration remains global".
  **Impact:** INV-4a's negative control is now signal disconnection, not
  deleting the call. D4 records that the call is declarative.

- **Observation:** importing a **submodule** does not avoid that side effect.
  Two reviewers independently proposed `from falcon_correlate.middleware_utils
  import correlation_id_var` as a fix, on the correct observation that
  `middleware_utils` itself imports nothing third-party. It does not work.
  **Evidence:** Python executes a package's `__init__` before any submodule, so
  the probe showed `celery in sys.modules: True` and one registered receiver
  after importing `falcon_correlate.middleware_utils` alone. Measured cost:
  **86.8 ms** warm for the package import, of which `celery.utils.dispatch`
  is 63.3 ms.
  **Impact:** this fix is rejected. See D3 for the alternative that was
  considered and why it was not taken either.

- **Observation:** `episodic/observability.py` is **399** lines against a
  blocking 400-line limit.
  **Evidence:** `wc -l` gives 399; `pyproject.toml:221` sets
  `max-module-lines = 400` and `too-many-lines` is enabled at line 408.
  **Impact:** EP-M3a exists because of this.

- **Observation:** in Celery eager mode `before_task_publish` does not fire and
  `task.request.correlation_id` is `None`.
  **Evidence:** a probe with `task_always_eager=True` recorded zero
  `before_task_publish` firings and `{'ctxvar': 'OUTER', 'req_cid': None}` from
  inside the task body; with the ambient variable unset the same task saw
  `{'ctxvar': None, 'req_cid': None}`.
  **Impact:** drives Risk R5 and the INV-4 split.

- **Observation:** the `rpc://` guard is real and observable.
  **Evidence:** with `Celery(backend="rpc://")` current,
  `propagate_correlation_id_to_celery(properties={"correlation_id": "task-id-original"})`
  leaves the value untouched while an active correlation identifier is set; with
  `backend="cache+memory://"` the same call rewrites it.
  **Impact:** drives Risk R3 and INV-4c.

- **Observation:** Falcon runs `process_response` for every middleware component
  even when an earlier component sets `resp.complete = True`, and
  `falcon.asgi.App` defaults to `independent_middleware=True`.
  **Evidence:** `falcon/asgi/app.py:540-599`, plus an end-to-end probe: with the
  correlation middleware registered first, an authorization short-circuit still
  produced a `401` carrying `X-Correlation-ID`, the value matched what the
  authorization middleware observed, and the context variable was reset
  afterwards. Falcon also wraps **each** `process_response` in its own
  `try/except` (`app.py:594-599`), so one raising component does not abort the
  rest of the stack.
  **Impact:** makes the roadmap's denial-correlation requirement satisfiable,
  and confirms D4.

- **Observation:** `Request.remote_addr` is the peer address and is not
  spoofable through headers.
  **Evidence:** `falcon/asgi/request.py:539-547` returns `access_route[-1]`, and
  `access_route` appends the ASGI scope `client` to the **end** of any
  `Forwarded` / `X-Forwarded-For` / `X-Real-IP` list. Probe with an
  `X-Forwarded-For` header present confirmed `remote_addr` still resolved to the
  scope client.
  **Impact:** `trusted_sources` correctly means "ingress or proxy source
  ranges", and no `X-Forwarded-For` parsing is needed. The security problem is
  R2, not spoofing.

- **Observation:** an identifier of 60,000 bytes is accepted and echoed in full,
  and a logfmt-injection payload round-trips intact.
  **Evidence:** verified against Granian with `validator=None` and a trusted
  source: `echoed header len: 60000`, total response 180,267 bytes; and
  `req.context.correlation_id == "abc method=GET path=/admin principal_id=root"`.
  **Impact:** drives Risk R8 and Decision D9.

- **Observation:** response splitting is not reachable **given Granian**, but the
  protection is not in the application.
  **Evidence:** Falcon does not sanitize header values — `set_header` only does
  `str(value)`. Inbound CR/LF is rejected by Granian with `400`; outbound CR/LF
  raises `RuntimeError: Unsupported ASGI message` and yields `500`. A tab is
  accepted and round-trips.
  **Impact:** record it as a transport-layer defence, not an application
  guarantee. D9's sanitizer makes it an application guarantee too.

- **Observation:** the correlation identifier deliberately outlives the request.
  **Evidence:** `episodic/generation/launcher.py:160` uses
  `asyncio.create_task`, which copies the context. Probe: the background task
  still saw `req-123` after the request task had reset the variable and
  returned.
  **Impact:** this is what makes INV-8 possible at all — the provider call
  happens after the response is sent. It is stated as AXIOM-10 rather than left
  implicit, because moving `_run_task` to a thread pool or a Celery task would
  kill INV-8 with no other symptom. A **resumed** run after a restart has no
  originating request and therefore no identifier; the users' guide must say so.

- **Observation:** gevent greenlets get a fresh empty context; Celery's prefork
  pool copies no context at all.
  **Evidence:** a `gevent.pool.Pool(128)` run of 1000 tasks through the real
  worker handlers produced zero cross-talk, but a spawned greenlet showed
  `gr_context is None` and did not inherit its spawner's value. A sequential
  prefork simulation with one suppressed `task_postrun` showed task D reading
  task C's stale identifier. `grep -rn "copy_context\|contextvars"` across
  `celery/app/trace.py` and `celery/concurrency/*.py` returns nothing.
  **Impact:** AXIOM-9, Risk R11, INV-4d.

- **Observation:** Vidai Mock templates **can** read request headers, so INV-8 is
  implementable — but the engine is **Tera**, not Jinja2.
  **Evidence:** `{{ __tera_context }}` dumps a request-scoped context containing
  `headers`, `json`, `model`, `path_segments`, `query`, `request_id`. An
  echo-back template using
  `{{ headers['x-correlation-id'] | default(value='ABSENT') }}` rendered the
  supplied identifier, and `ABSENT` without it.
  **Impact:** four constraints that would otherwise cost the implementer hours
  are recorded in EP-M6b.

- **Observation:** `hypothesis.event()` cannot enforce class coverage.
  **Evidence:** it feeds the `--hypothesis-show-statistics` report only and
  never fails a run. A module-level counter plus a follow-on assertion is
  unsafe here because `pytest-xdist` is a dev dependency and the two tests can
  land in different worker processes, so the guard would silently pass on an
  empty counter.
  **Impact:** INV-1's mechanism is now `@example` anchors, which Hypothesis
  always executes.

- **Observation:** a **fresh** `contextvars.Context()` cannot express INV-4b's
  decisive witness.
  **Evidence:** `contextvars.Context()` sees `None` for an ambient value,
  whereas `copy_context()` sees it. Since the witness requires an ambient
  identifier *different* from the message's, it must be set **inside** the
  isolated context. Verified that mutations persist across sequential `ctx.run`
  calls on the same `Context`, and that `reset(token)` succeeds when the token
  was created in an earlier `ctx.run` on that same `Context` — which matters
  because the library stores its reset tokens in a second context variable, so
  prerun and postrun must share a context or the cleanup returns early and the
  test passes vacuously in the wrong direction.
  **Impact:** INV-4b now specifies the exact `ctx.run` sequence.

- **Observation:** `**client_kwargs: object` fails the pinned typechecker.
  **Evidence:** the exact signature run under the repository's own
  `ty==0.0.32` produced `Found 18 diagnostics`, all
  `invalid-argument-type: Expected 'bool', found 'object'`; `pyright` agrees.
  **Impact:** D12 replaces it with explicit parameters. Note also that `ty`
  0.0.32 does **not** yet enforce `Unpack`-typed `**kwargs`, so the `TypedDict`
  variant would document intent without buying gate enforcement — a further
  argument for explicit parameters.

- **Observation:** `AsyncCorrelationIDTransport` is not an
  `httpx.AsyncBaseTransport` at runtime.
  **Evidence:** `falcon_correlate/httpx.py:200-203` sets
  `_AsyncBaseTransport = object` outside `TYPE_CHECKING`;
  `isinstance(t, httpx.AsyncBaseTransport)` is `False`, yet
  `AsyncClient(transport=t)` works by duck typing and the header lands. Its
  `aclose()` does delegate to the wrapped transport, so there is no
  connection-pool leak.
  **Impact:** works today, brittle if httpx ever adds a runtime check. Note it
  in ADR-018.

## Decision log

- **D1. Pin `falcon-correlate` to the `v0.1.0` tag.**
  Rationale: the first draft could only pin a commit, because the project had no
  tags and is not on PyPI. Upstream cut `v0.1.0` on 2026-08-23, and it resolves
  to the same commit this plan was researched against, so the pin is now both
  reproducible and semantically meaningful. This differs deliberately from the
  `femtologging` and `tei-rapporteur` commit pins at `pyproject.toml:14,21` and
  matches the existing `df12-python-lints @ ...@v0.2.0` tag pin in the
  development group; prefer a tag whenever upstream offers one. What the
  library actually buys is the part that is hardest to get right and carries an
  upstream test suite: the context-variable token lifecycle with its
  mismatched-token and invalid-token guards, CIDR host-bits validation, and the
  `rpc://` guard. An in-repository equivalent was costed at roughly 160-200
  lines; the tests would be episodic-owned either way. The dependency is
  defensible principally because the same author maintains both repositories,
  making the "upstream issue and a revised pin" escape hatch real rather than
  notional.
  Date/Author: 2026-08-23, planning agent.

- **D2. Introduce `episodic/request_correlation.py` as the single seam.**
  Rationale: exactly one module imports `falcon_correlate`, so the rest of the
  codebase depends on an episodic-owned surface. This matters more than the
  first draft realized, because C2's gate does not exist — the seam is the only
  mechanism. The name says "request" to keep it distinct from the domain
  `correlation_id`, which identifies a generation run or workflow (see
  `episodic/orchestration/_planning_orchestrator.py:148`, where it is passed as
  `workflow_run_id`). A `Protocol` port with an adapter was considered and
  rejected as over-engineering: the thing behind the seam is a context variable
  and a header name, there is no second implementation, and no test double is
  needed because a test can simply set the variable.
  Date/Author: 2026-08-23, planning agent.

- **D3. Accept the library's import side effect rather than owning the context
  variable.**
  Rationale: the review established that importing `falcon_correlate` costs
  86.8 ms and pulls in Celery, and that `episodic/logging.py` importing the seam
  would push that cost onto every domain module and every pytest collection.
  Two fixes were evaluated. Importing the submodule does not work (Python runs
  the package `__init__` first). Owning the context variable in episodic and
  passing it via `CorrelationIDMiddlewareASGI(correlation_id_context_var=...)`
  **does** work — verified end to end, including trust acceptance, regeneration,
  and post-request reset — but the library's Celery handlers and httpx
  transports read their **own** module-level variable, so episodic would have to
  reimplement both integrations. That directly contradicts the roadmap, which
  names `falcon-correlate` for all three. So: use the library's variable,
  import the package root, and record the cost as AXIOM-8. Mitigation is
  INV-9, which pins the import cost so a future regression is visible. If the
  cost later proves unacceptable, owning the variable is the documented escape,
  and it is a known-working design rather than speculation.
  Date/Author: 2026-08-23, planning agent.

- **D4. The correlation middleware is registered first, and the Celery call is
  declarative.**
  Rationale: Falcon executes `process_request` in registration order, so
  registering ahead of `AuthorizationMiddleware` (`episodic/api/app.py:307`)
  guarantees the identifier exists before any authorization decision is logged.
  Because `process_response` runs in reverse, the same choice makes the
  correlation middleware the last to touch the response, so the header is echoed
  and the variable reset after every other component finishes. Separately,
  `configure_celery_correlation(app)` in the worker composition root is retained
  as an explicit statement of intent, but the plan and ADR must say plainly that
  it is **not** what enables propagation — the import is. Publishing correlates
  from any process that has imported the seam, including the web tier, which is
  what the roadmap wants; it just happens for a different reason than the
  roadmap's wording implies.
  Date/Author: 2026-08-23, planning agent.

- **D5. Correlation reaches femtologging by message decoration, and the
  bypassing call sites are routed through the helpers.**
  Rationale: `ContextualLogFilter` is a `logging.Filter` and cannot see request
  context on the femtologging path; the two apparent escapes fail as recorded
  under `Surprises & discoveries`. Message decoration inside `log_info`,
  `log_warning`, and `log_error` is the cheapest working option — measured at
  106 ns against a 2623 ns emit, about 4%, constant whether or not an identifier
  is active. The first draft then claimed this gave complete coverage. It does
  not: 29 of 48 call sites bypass the helpers. EP-M3b therefore also (a) adds
  `log_debug` to `episodic/logging.py`, (b) routes
  `episodic/api/authorization.py:_log_authorization_denial` through
  `log_warning` — promoting it from `DEBUG`, which is correct on its own merits
  for an audit-relevant event — and (c) adds `correlation_id` as a structured
  field to `episodic/llm/openai_api/utils.py:_log_error_event`, which already
  emits JSON and so gets a real field rather than a decorated string. The
  remaining bypassing sites are listed in `Residual gaps` rather than silently
  implied to be covered.
  Alternatives rejected: a `LoggerAdapter`-style wrapper at `get_logger` was the
  strongest rival — one choke point covering direct calls too — but it must
  reimplement the `_SupportsConvenienceLog` / `_SupportsLogMethod` duck typing
  already in `episodic/logging.py`, changes the return type of `get_logger`
  across thirteen module bindings, and muddies the `getLogger`/`get_logger`
  re-export contract. Reconsider it if the bypassing-site list grows.
  Date/Author: 2026-08-23, revised after design review.

- **D6. Bootstrap logging in both composition roots.**
  Rationale: this is a prerequisite, not an adjacent nicety. `configure_logging`
  is referenced only by its own definition, its docstring, and
  `tests/test_logging.py`; `Dockerfile:42` runs Granian directly with no logging
  setup. Verified: an unconfigured femtologging logger writes nothing to stdout
  or stderr. Without this, EP-M3b produces zero operator-visible output, both of
  the plan's own headline risk mitigations (the `rpc://` and loopback warnings)
  emit no bytes, and INV-3 passes only because it asserts against a recording
  fake that is wired in tests and never in the container. The first draft
  spotted the gap and used it as an argument *for* decoration rather than
  concluding that a roughly fifteen-line bootstrap is load-bearing. EP-M3b calls
  `configure_logging` from `create_app_from_env` and `create_celery_app_from_env`,
  reading a level from `EPISODIC_LOG_LEVEL`.
  Date/Author: 2026-08-23, added after design review.

- **D7. `episodic/observability.py` carries the identifier in a reserved
  non-label key.**
  Rationale: that module uses the standard library directly, so the identifier
  can be added to its structured payloads. But it must **not** be merged into
  the `labels` mapping. The module's own docstring calls `MetricsPort` a
  "bounded-cardinality metrics sink", and
  `docs/episodic-podcast-generation-system-design.md:485-486` restricts labels
  to "adapter, provider, model, execution mode, outcome category, and error
  category only". A per-request UUID is the highest-cardinality value in the
  system, and `docs/infrastructure-design.md:46` targets Prometheus and Loki via
  an OpenTelemetry Collector — the moment a processor maps log attributes to
  labels, merging it into the label dict is a cardinality bomb. So emit it under
  a distinct `trace_context` key, and state in ADR-018 that `correlation_id`
  must never be exported as a metric label. Note honestly that these records are
  emitted at `INFO` to a standard-library logger, so until D6's bootstrap also
  configures the standard library they remain unobservable; the tracer spans are
  the more useful carrier.
  Date/Author: 2026-08-23, revised after design review.

- **D8. `episodic/request_correlation.py` owns the default header constant.**
  Rationale: `falcon_correlate` exports `DEFAULT_HEADER_NAME` from
  `middleware_config`, and it is **not** in the package `__all__` — an
  undeclared export. Re-exporting through the episodic seam keeps the import in
  one place, and a test pins the value to the literal `"X-Correlation-ID"`, so
  an upstream change is caught at the gate. That pinning test is load-bearing,
  not belt and braces.
  Date/Author: 2026-08-23, planning agent.

- **D9. Sanitize identifiers unconditionally at the seam.**
  Rationale: Risk R8 shows that trust and validation are not sufficient — a
  60,000-byte identifier and a logfmt-injection payload both round-trip today
  when validation is disabled. Rather than rely on an optional upstream
  validator, `episodic/request_correlation.py` supplies the middleware with a
  validator that **always** applies a hard contract:
  `^[A-Za-z0-9_-]{1,64}$`. `API_CORRELATION_VALIDATE_INCOMING` then selects
  only whether the *additional* UUID-shape check applies, and can never relax
  below the hard contract. This closes the log-forgery, log-amplification, and
  outbound-header-injection vectors in one place, and makes the response-header
  safety an application guarantee rather than an accident of Granian's parser.
  The generated identifier (a UUIDv7 hex string) satisfies the contract by
  construction.
  Date/Author: 2026-08-23, added after design review.

- **D10. The adapter correlates the client it owns, and injected clients can be
  retrofitted.**
  Rationale: the roadmap says "wrap *owned* `httpx.AsyncClient` instances", and
  `_owns_client` (`episodic/llm/openai_api/adapter.py:135-136`) already
  distinguishes them. Injecting a client at the composition root instead would
  invert that ownership and need a matching shutdown hook. So the owned client
  is built through `build_correlated_async_client`. Risk R7 remains, because
  every existing adapter fixture injects a client — which would make INV-5
  untestable against the real code path. Two additions fix that: an optional
  `transport` field on `OpenAICompatibleLLMConfig` lets a test exercise the
  **real owned-client path** with `httpx.MockTransport` and no monkeypatching;
  and `correlate_client(client)`, a one-line retrofit that appends an httpx
  request event hook, lets an injecting caller opt in. The event hook was
  verified: it injects when an identifier is active, does nothing when it is
  not, and does not clobber a caller-set header. `tests/steps/no_qa_generation_slice_support.py`
  sets its chaos header post-construction at line 256, so it can adopt
  `correlate_client` and keep chaos injection.
  **This is an addition beyond the roadmap's literal wording**, which names only
  `falcon-correlate` transport support. The transport remains the mechanism for
  owned clients; the event hook covers the injected case the transport
  structurally cannot reach. Flagged for reviewer acceptance under `Tolerances`.
  Date/Author: 2026-08-23, revised after design review.

- **D11. Emit a bounded correlation-source counter.**
  Rationale: Risk R9 — the two most likely production failures are silent. One
  counter, `correlation_id_source`, with exactly four permanently bounded label
  values (`generated`, `accepted`, `rejected_untrusted`, `rejected_invalid`),
  makes both detectable: `rejected_untrusted` climbing to 100% is precisely the
  signal that an ingress reschedule broke the trusted range, and `accepted`
  stuck at zero is the signal that an operator's CIDR never matched. INV-1
  already partitions generated cases into exactly these four classes, so this
  promotes a test-only classification to a runtime signal at no design cost.
  Date/Author: 2026-08-23, added after design review.

- **D12. `build_correlated_async_client` takes explicit parameters and builds
  its inner transport explicitly.**
  Rationale: `**client_kwargs: object` fails `ty` with 18 errors, and — worse,
  because no typechecker reports it — httpx silently discards `verify`, `cert`,
  `proxy`, `limits`, `http1`, `http2`, and `trust_env` whenever a transport is
  supplied. An operator writing `verify="/etc/ssl/corp-ca.pem"` would get the
  system store with no error, and any egress-proxy deployment would lose
  connectivity (Risk R10). The factory therefore takes named parameters and
  constructs `httpx.AsyncHTTPTransport(verify=..., limits=..., proxy=...)`
  itself before wrapping it, so those settings are honoured rather than
  discarded.
  Date/Author: 2026-08-23, added after design review.

## Outcomes & retrospective

To be completed at EP-M7. Before setting this plan to `COMPLETE`, reconcile
every discovery against `docs/roadmap.md`,
`docs/episodic-podcast-generation-system-design.md`,
`docs/episodic-tui-api-design.md`, `docs/infrastructure-design.md`, and ADR-018,
and record any remaining deviation here.

## Context and orientation

Read this section if you have never worked in this repository.

Episodic is a podcast-generation system written in Python 3.14 and managed with
`uv`. It follows hexagonal architecture: a pure domain, ports declared as
`typing.Protocol` classes, and adapters that implement those ports. The
`hecate` tool checks the internal boundaries; `pyproject.toml:785-864` lists the
groups. Read C2 before relying on it — it does not check third-party imports.

The pieces you will touch:

- **The HTTP service.** `episodic/api/app.py` holds `create_app(dependencies)`
  at line 304, a pure factory that builds a `falcon.asgi.App`, registers
  middleware from line 307, sets an error serializer, and adds routes. It must
  never read the environment; ADR 002 reserves that for
  `episodic/api/runtime.py`, whose `create_app_from_env()` is the Granian
  factory target named at line 59. `episodic/api/runtime_config.py` defines the
  frozen `RuntimeConfig` and `_load_runtime_config(environ)`, which reads
  `UPPER_SNAKE_CASE` variables and raises `RuntimeConfigurationError`.
  `episodic/api/dependencies.py` defines `ApiDependencies`, the typed bag of
  constructed ports that `create_app` receives. `_build_llm_port` is at
  `episodic/api/runtime.py:77` and the `ApiDependencies(...)` construction is at
  line 272.
- **Authorization.** `episodic/api/authorization.py` guards paths under `/v1/`
  and writes denial envelopes directly onto the response with
  `resp.complete = True` rather than raising `falcon.HTTPError`. Its denial path
  is `_log_authorization_denial` at line 171, which logs at `DEBUG` through a
  direct `logger.log` call. `log_warning` appears only on the 503
  adapter-failure path at line 115.
- **The workers.** `episodic/worker/runtime.py` holds `WorkerRuntimeConfig`,
  `load_runtime_config(environ)` reading `EPISODIC_CELERY_*` variables, and
  `create_celery_app(...)` at line 257. The `celery` command-line tool targets
  `episodic.worker.runtime:create_celery_app_from_env`
  (`docs/developers-guide.md:434-444`).
- **The inference adapter.** `episodic/llm/openai_api/adapter.py` defines
  `OpenAICompatibleLLMAdapter`, a hand-written `httpx` client for
  OpenAI-compatible endpoints. It does **not** use the `openai` SDK. It accepts
  an optional `client` and tracks ownership in `_owns_client` at line 136.
- **Logging.** `episodic/logging.py` wraps `femtologging`, exposing
  `get_logger`, `configure_logging`, and the `log_info` / `log_warning` /
  `log_error` helpers. `episodic/observability.py` separately uses the standard
  library for its metrics and tracing adapters, and is 399 lines.

The library you are integrating, `falcon-correlate`, is another `leynos`
project. Its public surface is exported from `falcon_correlate/__init__.py`:

- `CorrelationIDMiddlewareASGI` — Falcon ASGI middleware. `process_request`
  picks an incoming header value when the request comes from a trusted source
  and passes validation, otherwise generates one; it sets
  `req.context.correlation_id` and the `correlation_id_var` context variable.
  `process_response` echoes the header and resets the variable. It accepts a
  `correlation_id_context_var` parameter, which this plan does not use — see D3.
- `CorrelationIDConfig` — a frozen dataclass with `header_name`,
  `trusted_sources`, `generator`, `validator`, and `echo_header_in_response`,
  validating IP addresses and CIDR ranges at construction and rejecting a CIDR
  with host bits set. Its `from_kwargs` classmethod mirrors those keywords.
- `correlation_id_var` — a `contextvars.ContextVar[str | None]`.
- `default_uuid7_generator`, `default_uuid_validator` — the default factory and
  a UUID-shape validator accepting versions 1 to 8, hyphenated or hex-only.
- `configure_celery_correlation(app)` — idempotent, and **not** what registers
  the signals; see D4.
- `AsyncCorrelationIDTransport(wrapped_transport, header_name)` — an httpx
  transport that injects the header before delegating and leaves an
  already-present header alone.

Two exports must **not** be used: `ContextualLogFilter` and
`RECOMMENDED_LOG_FORMAT` assume the standard-library logging stack. See D5.

Relevant reading, in priority order: `docs/roadmap.md:606-626`;
`docs/episodic-podcast-generation-system-design.md:2033-2044`;
`docs/adr/adr-002-http-service-composition-root.md`;
`docs/adr/adr-003-celery-worker-scaffold.md`;
`docs/adr/adr-014-hexagonal-architecture-enforcement.md`;
`docs/infrastructure-design.md` for the Traefik and DOKS topology behind Risk
R2; `docs/developers-guide.md` for the lint pipeline, the versioned routing and
error contracts at lines 280-339, worker launch at 434-444, and the Vidai Mock
policy at 805 and 1140-1780; `docs/testing-async-falcon-endpoints.md`;
`docs/episodic-tui-api-design.md` for the error contract; and
`docs/documentation-style-guide.md` for the ADR template.

Relevant skills: `hexagonal-architecture`; `python-router` then
`python-errors-and-logging`; `python-testing` and `hypothesis`; `leta` for
navigation; `vidai-mock` for the behavioural inference double.

## Conformance basis

- Roadmap: `docs/roadmap.md`, item 4.1.3 at lines 606-626, as of commit
  `5af0638`. **RM-4.1.3**, with sub-requirements **RM-4.1.3.a** through
  **RM-4.1.3.g** in the order the roadmap lists them: a. dependency pin;
  b. middleware before authorization; c. runtime configuration; d. Celery
  propagation; e. outbound `httpx` wrapping; f. Falcon, Celery-eager, and
  `MockTransport` tests; g. users' and developers' guide documentation.
- Design: `docs/episodic-podcast-generation-system-design.md:2033-2044`,
  **DD-CORR**.
- ADRs constraining the approach: **ADR-002**, **ADR-003**, **ADR-014**,
  **ADR-015**.
- New ADR at EP-M7: **ADR-018**,
  `docs/adr/adr-018-request-correlation-propagation.md`. Number 018 is the next
  free value: 016 and 017 are taken, and 015 is already triple-booked across
  `adr-015-upload-and-idempotency-ports.md`,
  `adr-015-cost-accounting-ports-and-pricing-engine.md`, and
  `adr-015-generation-run-port-split.md`. That collision is pre-existing and is
  **not** this plan's to fix.
- No Terms of Reference document exists; the roadmap item and the
  design-document paragraph are the governing statements.

Trace links:

```plaintext
RM-4.1.3.a -> EP-M0  -> tests::test_request_correlation_settings::test_default_header_is_pinned
RM-4.1.3.c -> EP-M1  -> tests::test_runtime_configuration::test_correlation_settings_from_environment
RM-4.1.3.b -> EP-M2  -> tests::test_api_request_correlation::test_denied_request_echoes_header
RM-4.1.3.b -> EP-M3b -> tests::test_api_request_correlation::test_denial_log_carries_identifier
RM-4.1.3.d -> EP-M4  -> tests::test_worker_request_correlation::test_publish_writes_active_identifier
RM-4.1.3.e -> EP-M5  -> tests::test_llm_openai_adapter_correlation::test_owned_client_sends_header
RM-4.1.3.f -> EP-M6a -> tests/features/request_correlation.feature
RM-4.1.3.f -> EP-M6b -> tests/features/request_correlation_provider.feature
RM-4.1.3.g -> EP-M7  -> docs/users-guide.md, docs/developers-guide.md, ADR-018
```

## Verification plan

### Axioms

Treated as given. Do not verify third-party internals; do verify
episodic-owned logic against the real interface.

- **AXIOM-1.** `CorrelationIDMiddlewareASGI` selects a trusted and valid
  incoming identifier or generates one, sets `req.context.correlation_id` and
  `correlation_id_var`, and echoes and resets in `process_response`.
- **AXIOM-2.** Falcon executes `process_request` in registration order and
  `process_response` in reverse, runs every registered `process_response` even
  when an earlier component sets `resp.complete = True`, wraps each in its own
  `try/except`, and defaults `falcon.asgi.App` to `independent_middleware=True`.
- **AXIOM-3.** `Request.remote_addr` is `access_route[-1]`, the ASGI scope
  `client` address, falling back to `'127.0.0.1'` when the scope omits it.
  Granian populates it; `falcon.testing` omits it unless `remote_addr` is given.
- **AXIOM-4.** Celery fires `before_task_publish` only on a real publish, and
  fires `task_prerun` and `task_postrun` around every execution including eager
  execution.
- **AXIOM-5.** `propagate_correlation_id_to_celery` writes
  `properties["correlation_id"]` when an identifier is active, except when
  `celery.current_app.backend.as_uri()` begins with `rpc://`.
- **AXIOM-6.** `httpx.AsyncClient(transport=...)` routes every request through
  the supplied transport; `httpx.MockTransport` observes the fully built
  request; and httpx **discards** `verify`, `cert`, `proxy`, `limits`, `http1`,
  `http2`, and `trust_env` whenever a transport is supplied.
- **AXIOM-7.** Python 3.14 provides `uuid.uuid7()`.
- **AXIOM-8.** `import falcon_correlate` imports Celery and registers three
  signal handlers globally at import time, costing about 86.8 ms warm. This is
  process-global and idempotent via stable dispatch identifiers.
- **AXIOM-9.** A gevent greenlet receives a fresh empty `contextvars.Context`,
  so correlation is isolated per task but is **not** inherited across
  `gevent.spawn`. Celery's prefork pool copies no context, so every task in a
  worker child shares one context. Subinterpreters cannot carry context
  variables; `asyncio.to_thread` and `asyncio.create_task` do.
- **AXIOM-10.** `asyncio.create_task` copies the current context, so the
  background generation task launched at `episodic/generation/launcher.py:160`
  retains the request's correlation identifier after the response is sent. INV-8
  depends on this.
- **AXIOM-11.** femtologging records emitted through `get_logger(...)` do not
  carry `log_context` fields, and femtologging emits nothing at all until
  `basicConfig` is called.

### Obligations

**INV-1 — Response and request context agree; untrusted callers cannot choose
the identifier; and no identifier violates the hard contract.**

- Obligation: for every request, `req.context.correlation_id` matches
  `^[A-Za-z0-9_-]{1,64}$`; when echoing is enabled the response carries exactly
  one header of the configured name whose value equals it; and that value equals
  a caller-supplied header value **only if** `remote_addr` falls inside a
  configured trusted source *and* the supplied value satisfies the hard contract
  *and*, when `validate_incoming_ids` is set, the UUID-shape check.
- Method: property test with Hypothesis, plus parameterized boundary tests.
- Rationale: the statement quantifies over header values, remote addresses, and
  configurations; the trust and sanitization rules are the security-relevant
  parts and deserve generated adversarial input.
- Domain: header values drawn from valid UUIDs (hyphenated, hex-only, mixed
  case), malformed strings, empty and whitespace-only strings, strings of 65 and
  60,000 characters, strings containing CR, LF, tab, space, `=`, and non-ASCII;
  remote addresses inside and outside the configured ranges, plus the
  unset-scope case reachable by omitting `remote_addr`; configurations varying
  `validate_incoming_ids` and `echo_response_header`.
- Artefact: `tests/test_api_request_correlation_properties.py`, driving
  `falcon.testing.TestClient(create_app(deps))` with
  `simulate_get(..., headers=..., remote_addr=...)`.
- Evidence: `uv run pytest tests/test_api_request_correlation_properties.py`.
  Before EP-M2 the module fails at import; after EP-M2 it passes.
- Non-vacuity: **do not** use `hypothesis.event()` as an enforcement mechanism —
  it only feeds the statistics report and never fails a run, and a module-level
  counter is unsafe because `pytest-xdist` can place the counter and its
  assertion in different processes. Instead pin one representative of each of
  the four classes (`accepted-incoming`, `rejected-untrusted`,
  `rejected-invalid`, `no-incoming-header`) with `@example`, which Hypothesis
  always executes, classify inside the body, and assert the class-specific
  postcondition. Set `@settings(max_examples=100, deadline=None)` explicitly, as
  every other property module in this repository does, because each
  `simulate_get` spins an event loop and the suite timeout is 180 s. The
  `accepted-incoming` anchor must use a **real** CIDR so that a fail-closed
  regression in the library's private `_parsed_networks` access (Risk R6) breaks
  the test. The negative control is configuring `trusted_sources=("0.0.0.0/0",)`:
  the `rejected-untrusted` assertion must then fail.

**INV-2 — The identifier survives authorization denial.**

- Obligation: a request that `AuthorizationMiddleware` rejects with `401` or
  `403` still carries the correlation header on the response.
- Method: parameterized test over the denial statuses.
- Rationale: the specific outcome RM-4.1.3.b asks for, depending on AXIOM-2
  rather than on anything episodic controls.
- Domain: missing `Authorization` header (401), wrong bearer token (401), and an
  authorization port that raises (503).
- Artefact: `tests/test_api_request_correlation.py`.
- Evidence: `uv run pytest tests/test_api_request_correlation.py -k denial`.
- Non-vacuity: the same test asserts the header is *absent* when
  `echo_response_header` is false, proving the assertion can fail. Registering
  the correlation middleware after `AuthorizationMiddleware` is the seeded fault
  that must break INV-3's companion log assertion.

**INV-3 — The logging helpers carry the active identifier, and the denial log is
among them.**

- Obligation: `log_debug`, `log_info`, `log_warning`, and `log_error` append
  exactly one space-separated `correlation_id=<id>` suffix when
  `current_correlation_id()` returns a value, and leave the message
  byte-identical when it returns `None`. After EP-M3b the authorization denial
  log is emitted through `log_warning` and therefore carries the identifier.
- Method: parameterized unit tests against a recording fake logger, plus one
  integration assertion that captures the real denial line.
- Rationale: a finite, fully enumerable partition — identifier present or
  absent, across four helpers, with and without template arguments.
- Domain: all four helpers; templates with zero and several `%s` placeholders;
  identifier present and absent; a template whose arguments already contain the
  literal `correlation_id=`.
- Artefact: `tests/test_logging.py`, plus
  `tests/test_api_request_correlation.py::test_denial_log_carries_identifier`.
- Evidence: `uv run pytest tests/test_logging.py`.
- Non-vacuity: the absent-identifier case is the witness that the suffix is
  conditional. State the contract precisely so the edge case is testable: the
  helper appends exactly one suffix **regardless of message content**, so assert
  `message.endswith(f" correlation_id={cid}")` and
  `message.count(" correlation_id=") == 1` only where the template does not
  itself contain the token; where it does, assert only the `endswith` clause and
  document that a duplicate token in caller-supplied text is acceptable. The
  integration assertion is what makes this non-vacuous overall: the unit tests
  use a fake logger that is always wired, whereas the integration test proves
  the real path emits.

**INV-4 — Celery propagation.** Split into four obligations because neither the
eager path nor the call site establishes what the first draft assumed.

- **INV-4a — publish writes the active identifier.**
  Obligation: with an identifier active and a non-`rpc://` result backend,
  publishing a task sets `properties["correlation_id"]`.
  Method: contract-level test against the real Celery signal, using a non-eager
  application on a `memory://` broker so a genuine publish occurs.
  Domain: identifier active and absent.
  Artefact: `tests/test_worker_request_correlation.py`.
  Evidence: `uv run pytest tests/test_worker_request_correlation.py -k publish`.
  Non-vacuity: the identifier-absent case must leave Celery's own task-identifier
  value in place. The seeded fault is **not** deleting
  `configure_celery_correlation(app)` — that changes nothing, because the import
  already registered the handler (AXIOM-8), and any earlier test in the same
  process would have triggered it anyway. Use instead a fixture that calls
  `celery.signals.before_task_publish.disconnect(dispatch_uid="falcon_correlate.celery.propagate_correlation_id_to_celery")`
  and assert the positive case then fails.

- **INV-4b — the worker restores the identifier from the message.**
  Obligation: given a task request carrying `correlation_id`, the worker-side
  handler makes that value visible for the duration of the task and restores the
  previous value afterwards.
  Method: parameterized unit test driven through a single shared
  `contextvars.Context`.
  Rationale: this removes the eager-mode vacuity of Risk R5.
  Domain: message identifier present, absent, and non-string; the ambient
  identifier set to a **different** value before the handler runs.
  Artefact: `tests/test_worker_request_correlation.py`.
  Evidence:
  `uv run pytest tests/test_worker_request_correlation.py -k worker_context`.
  Non-vacuity: a **fresh** `contextvars.Context()` cannot express the decisive
  witness, because it cannot see an ambient value at all. Use one `Context` and
  drive it in sequence, setting the ambient value inside it:

  ```python
  ctx = contextvars.Context()
  ctx.run(lambda: correlation_id_var.set("AMBIENT"))
  ctx.run(setup_correlation_id_in_worker, task=fake_task)
  assert ctx.run(correlation_id_var.get) == "FROM-MESSAGE"
  ctx.run(clear_correlation_id_in_worker)
  assert ctx.run(correlation_id_var.get) == "AMBIENT"
  ```

  Sharing one `Context` is mandatory, not stylistic: the library stores its
  reset tokens in a second context variable, so a prerun and postrun in
  different contexts would make the cleanup return early and the test would pass
  vacuously in the wrong direction.

- **INV-4c — the `rpc://` interaction is explicit, and eager mode does not
  pretend.**
  Obligation: with an `rpc://` result backend the publish handler leaves
  `properties["correlation_id"]` untouched, and the worker composition root
  refuses to start unless the operator has set the acknowledgement variable.
  With `task_always_eager=True`, `before_task_publish` does not fire.
  Method: parameterized unit tests plus one explicit regression test.
  Domain: result backend `cache+memory://` and `rpc://`; acknowledgement
  variable set and unset; `task_always_eager` true.
  Artefact: `tests/test_worker_request_correlation.py`.
  Evidence: `uv run pytest tests/test_worker_request_correlation.py -k "rpc or eager"`.
  Non-vacuity: activate the application under test with `app.set_current()`
  around the `rpc://` assertions, because the library consults
  `celery.current_app`, not the application the test built — otherwise the
  branch tested depends on whichever application happened to be current. The
  eager counter is demonstrably capable of being non-zero because INV-4a's
  non-eager case fires exactly once.

- **INV-4d — no identifier leaks between sequential tasks in a prefork child.**
  Obligation: running three tasks back to back in one shared context — with an
  identifier, without one, then with a different one — leaves no stale value
  visible to any of them.
  Method: parameterized sequential-execution test in a single `Context`.
  Rationale: AXIOM-9 says prefork copies no context, so the token stack is the
  only thing preventing a leak; INV-4b tests the greenlet model and proves
  nothing here.
  Domain: the three-task sequence, plus one run with `task_postrun` suppressed.
  Artefact: `tests/test_worker_request_correlation.py`.
  Evidence: `uv run pytest tests/test_worker_request_correlation.py -k prefork`.
  Non-vacuity: the suppressed-`task_postrun` run must **fail** the no-leak
  assertion, pinning the failure mode as a known, documented hazard rather than
  an untested hope. Assert the observed stale value explicitly.

**INV-5 — Outbound provider calls carry the identifier.**

- Obligation: when the adapter owns its client and an identifier is active,
  every outbound request carries the configured header with that value; when no
  identifier is active the header is absent; and a header the caller already set
  is not overwritten. `correlate_client` produces the same behaviour on an
  injected client.
- Method: parameterized unit tests using `httpx.MockTransport`.
- Rationale: `MockTransport` observes the fully built request, the real contract
  boundary, and RM-4.1.3.f names the technique.
- Domain: identifier present and absent; the default header name and a
  configured non-default name; a caller-set header of the same name; owned and
  retrofitted-injected clients.
- Artefact: `tests/test_llm_openai_adapter_correlation.py`.
- Evidence: `uv run pytest tests/test_llm_openai_adapter_correlation.py`.
- Non-vacuity: the first draft left three competing test designs; there is now
  one. Construct the adapter with `client=None` and
  `OpenAICompatibleLLMConfig(transport=httpx.MockTransport(handler))`, which
  exercises the **real owned-client path** end to end with no monkeypatching —
  necessary because every existing fixture in `tests/fixtures/llm.py:160-190`
  injects a client and so cannot reach that path at all. Add a separate
  three-line test that `build_correlated_async_client` wraps the supplied
  transport. The absent-identifier and caller-set cases prove the header is
  conditional and non-clobbering. Reverting the adapter to a bare
  `httpx.AsyncClient()` is the seeded fault.

**INV-6 — Configuration is validated at construction, in both composition
roots.**

- Obligation: `CorrelationSettings.__post_init__` rejects an empty header name,
  a malformed IP address or CIDR range, a CIDR range with host bits set, and the
  reserved names `traceparent` and `tracestate`, raising
  `CorrelationConfigurationError` before any application object is built.
- Method: parameterized unit tests.
- Rationale: a finite partition of malformed inputs, guarding against a service
  that boots and then rejects traffic. Validation must live in `__post_init__`,
  not in the loader and not in a `to_middleware_config()` call made from
  `create_app`; otherwise C1 is violated (`create_app` becomes able to raise a
  configuration error) and the settings type is not self-validating despite
  EP-M2 relying on exactly that.
- Domain: empty and whitespace-only header names; `traceparent`; `tracestate`;
  `10.0.0.5/24` (host bits set); `not-an-ip`; a valid mixed IPv4/IPv6 list; an
  empty list; whitespace and trailing commas in the list; a bare string passed
  as `trusted_sources`, which upstream rejects with `TypeError` rather than
  `ValueError`.
- Artefact: `tests/test_request_correlation_settings.py`.
- Evidence: `uv run pytest tests/test_request_correlation_settings.py`.
- Non-vacuity: the valid-list case must construct successfully, proving the
  rejection is selective. Catch **both** `TypeError` and `ValueError` when
  translating: upstream raises `TypeError` when `trusted_sources` is a bare
  string or contains a non-string, and the first draft translated only
  `ValueError`, so that case would have escaped as a bare `TypeError`. Include a
  case asserting that a list (rather than a tuple) is coerced, because a frozen
  dataclass does not coerce sequences and an uncoerced list makes the
  "hashable" settings object raise `TypeError: unhashable type: 'list'`.

**INV-7 — The operator-facing configuration surface is stable.**

- Obligation: the resolved settings for representative environment mappings
  match a recorded snapshot.
- Method: `syrupy` snapshot test.
- Rationale: RM-4.1.3.g makes this an operator contract.
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
- Method: `pytest-bdd` scenario driving the Falcon app through
  `httpx.ASGITransport` against a live Vidai Mock server that echoes the
  received header back inside its completion.
- Rationale: `docs/developers-guide.md:805` requires behavioural tests that
  exercise real `LLMPort` inference paths to use Vidai Mock rather than pure
  mocks. This is the only obligation that observes the whole chain at once.
- Domain: one happy path.
- Artefact: `tests/features/request_correlation_provider.feature` with
  `tests/steps/test_request_correlation_provider_steps.py`.
- Evidence: run

  ```bash
  uv run pytest tests/steps/test_request_correlation_provider_steps.py -v
  ```

- Non-vacuity: assert that the provider-observed value **equals** the response
  header value, not merely that both are present; two independently generated
  identifiers would fail. This obligation silently depends on AXIOM-10 — the
  provider call happens on a background task after the response is sent — so if
  it starts failing, check whether `_run_task` moved off `asyncio.create_task`
  before suspecting the correlation code.

**INV-9 — The seam's import cost does not regress.**

- Obligation: importing `episodic.request_correlation` costs no more than an
  agreed budget, and importing `episodic.logging` does not pull in `httpx` or
  `falcon`.
- Method: a targeted import test asserting on `sys.modules` membership.
- Rationale: C2 has no gate (see the constraint text), and D3 knowingly accepts
  a Celery import. Pinning that boundary is the only mechanism that keeps a
  future edit from quietly adding `httpx` or `falcon` to the domain import
  graph.
- Domain: a subprocess importing `episodic.logging` alone.
- Artefact: `tests/test_request_correlation_imports.py`.
- Evidence: `uv run pytest tests/test_request_correlation_imports.py`.
- Non-vacuity: assert `"celery" in sys.modules` as well, so the test documents
  the accepted cost rather than pretending it is absent, and would fail loudly
  if a future change made the assertion obsolete in either direction.

**INV-10 — The client factory honours transport-level settings.**

- Obligation: `build_correlated_async_client(verify=..., limits=..., proxy=...)`
  applies those settings to the inner transport rather than discarding them.
- Method: parameterized unit test asserting on the constructed transport's
  configuration.
- Rationale: AXIOM-6 — httpx silently discards these whenever a transport is
  supplied, and the factory always supplies one (Risk R10). Nothing else in the
  system would report the loss.
- Domain: default construction; an explicit `verify` path; explicit `limits`; an
  explicit `proxy`.
- Artefact: `tests/test_request_correlation_client.py`.
- Evidence: `uv run pytest tests/test_request_correlation_client.py`.
- Non-vacuity: implement the factory naively (passing the settings to
  `AsyncClient` alongside `transport=`) and confirm the test fails; that is
  precisely the silent bug the obligation exists to catch.

### Residual gaps

- **Twenty-six logging call sites still bypass the helpers** after EP-M3b closes
  the three that matter most. They are in `episodic/concurrent_interpreters.py`
  (8), `episodic/canonical/storage/migration_check.py` (7),
  `episodic/generation/chapter_marker_generator.py` (4),
  `episodic/worker/runtime.py` (2), `episodic/qa/chrono.py` (2),
  `episodic/qa/chrono_langgraph.py` (2), and one each in
  `episodic/canonical/storage/uow.py`, `episodic/canonical/services.py`, and
  `episodic/canonical/ingestion_service.py`. Migrating them is mechanical but
  outside this item's budget; record it as a follow-up.
- **`episodic/api/errors.py` and `episodic/api/resources/*.py` log nothing**, so
  the roadmap's "error and resource logs" clause is vacuously satisfied. Stated,
  not hidden.
- **WebSocket connections will carry no identifier.**
  `CorrelationIDMiddlewareASGI` defines only `process_request` and
  `process_response`, not the `_ws` hooks Falcon dispatches WebSocket requests
  through. No WebSocket code exists in `episodic/` today, but
  `docs/episodic-tui-api-design.md` specifies a WebSocket event stream — exactly
  where an operator would most want correlation. Record in ADR-018.
- **The identifier is header-only and invisible to a terminal user.** The error
  envelope at `docs/episodic-tui-api-design.md:383-394` has no correlation
  field, so a user filing a bug report cannot quote the value. Coordinate adding
  one with `docs/execplans/4-1-2-finalize-rest-surfaces.md`, which is already
  reworking that envelope; landing two conflicting envelopes would be worse than
  waiting.
- **`Access-Control-Expose-Headers` is not set** and no CORS middleware exists.
  A browser client could not read the header. Note it so whoever adds CORS does
  not rediscover it.
- **Upstream cannot accept one header name and echo another**, nor accept a list
  of candidate inbound headers. If Episodic ever moves behind Envoy or
  ingress-nginx — both of which mint `x-request-id` — the ingress access log and
  the application log would not join. That is an upstream feature request, not a
  configuration change. Record in ADR-018.
- **`WorkerRuntimeConfig` gains no correlation field.** See EP-M1; this is
  deliberate.
- Behaviour under a real RabbitMQ broker and a real Granian process is not
  exercised; the Celery obligations use `memory://` and the HTTP obligations use
  the ASGI transport. This is the existing project convention.

## Plan of work

### Stage A — orient (no code changes)

Read `docs/roadmap.md:606-626`,
`docs/episodic-podcast-generation-system-design.md:2033-2044`, ADR 002, ADR 003,
ADR 014, and `docs/infrastructure-design.md`. Then read the modules named in
`Context and orientation`. Use `leta show <symbol>` rather than reading whole
files. Read this plan's `Surprises & discoveries` in full before writing code;
it will save you a day.

### Stage B — red

Write the failing test first. Where a test cannot yet import the module under
construction, that import failure **is** the red state; do not stub the module.
Where a test can be written against an existing importable surface, mark it
`@pytest.mark.xfail(strict=True, reason="...")`, observe the expected failure,
then remove the marker in the green step. No `xfail` may survive into the final
tree.

### Stage C — implement

Take the milestones in order. Each ends with all four gates green and a commit.

### Stage D — refactor and document

Fold documentation, ADR, chart changes, and the roadmap tick into EP-M7, then
run the whole gate suite once more.

## Milestones and plateaus

### EP-M0 — Pin the dependency

- **Outcome:** `falcon_correlate` is installable, importable, and its default
  header name is pinned by a test.
- **Requirements:** RM-4.1.3.a.
- **Before editing:** file two upstream issues, both identified by the design
  review and both explicitly the correct response under `Tolerances` rather than
  local shims:
  1. `_current_result_backend_uses_rpc()` recomputes a startup-time property on
     **every** publish, at about 2 µs, dominated by `importlib.import_module`
     and `current_app` proxy resolution. Cache it.
  2. The same function consults `celery.current_app` rather than resolving the
     application from the signal's `sender`, so in a process holding two
     applications it checks the wrong one.
- **Edits:** `pyproject.toml`, `[project].dependencies`: insert in alphabetical
  position between `"falcon>=4.3.1,<5.0"` and `"femtologging @ ..."` the line
  `"falcon-correlate @ git+https://github.com/leynos/falcon-correlate@v0.1.0"`.
  Run `make build` and commit the `uv.lock` change. Confirm the locked revision
  is `caea7a6ac804f851f7226ccf9acb3d256cc2d5d4`; that is the commit every
  finding in this plan was probed against, and a different value means the tag
  moved (Risk R1).
- **Acceptance evidence:**

  ```bash
  uv run python -c "import importlib.metadata as md; print(md.version('falcon-correlate'))"
  uv run python -c "import falcon_correlate; print(falcon_correlate.__all__)"
  ```

  prints `0.1.0`, then a list containing `CorrelationIDMiddlewareASGI`,
  `configure_celery_correlation`, and `AsyncCorrelationIDTransport`.
- **Conformance check:** one new dependency, authorized by `Tolerances`.
- **Recovery:** revert `pyproject.toml` and `uv.lock`, rerun `make build`.
- **Compatibility decision:** none required.

### EP-M1 — The correlation seam and its configuration

- **Outcome:** one episodic-owned module exposes the settings type, the loader,
  the sanitizer, the ambient read, the middleware factory, and the client
  factory; the API composition root can read the configuration.
- **Requirements:** RM-4.1.3.c; discharges INV-6, INV-7, INV-9, INV-10.
- **New file:** `episodic/request_correlation.py`. Public surface:

  ```python
  DEFAULT_CORRELATION_HEADER_NAME: str
  CORRELATION_ID_PATTERN: re.Pattern[str]   # ^[A-Za-z0-9_-]{1,64}$

  class CorrelationConfigurationError(ValueError): ...

  @dc.dataclass(frozen=True, slots=True)
  class CorrelationSettings:
      header_name: str = DEFAULT_CORRELATION_HEADER_NAME
      trusted_sources: tuple[str, ...] = ()
      validate_incoming_ids: bool = True
      echo_response_header: bool = True

      def __post_init__(self) -> None: ...
      def _to_middleware_config(self) -> CorrelationIDConfig: ...

  def load_correlation_settings(
      environ: cabc.Mapping[str, str] | None = None,
  ) -> CorrelationSettings: ...

  def current_correlation_id() -> str | None: ...

  def build_correlation_middleware(settings: CorrelationSettings) -> object: ...

  def build_correlated_async_client(
      *,
      header_name: str = DEFAULT_CORRELATION_HEADER_NAME,
      transport: httpx.AsyncBaseTransport | None = None,
      timeout: httpx.Timeout | float | None = None,
      base_url: httpx.URL | str = "",
      verify: ssl.SSLContext | str | bool = True,
      limits: httpx.Limits | None = None,
      proxy: httpx.Proxy | str | None = None,
  ) -> httpx.AsyncClient: ...

  def correlate_client(
      client: httpx.AsyncClient,
      *,
      header_name: str = DEFAULT_CORRELATION_HEADER_NAME,
  ) -> httpx.AsyncClient: ...

  def configure_celery_correlation(app: Celery) -> Celery: ...
  ```

  Notes for the implementer:

  - `build_correlation_middleware` returns `object` deliberately. `add_middleware`
    accepts anything exposing the hooks, and keeping the concrete
    `falcon_correlate` class out of the signature is what preserves D2. The
    first draft had `create_app` import `CorrelationIDMiddlewareASGI` directly,
    which would have been a second import site and a violation of D2 by the
    plan's own code snippet.
  - `_to_middleware_config` is **private** and called from `__post_init__`, so
    validation happens at construction (INV-6) and `create_app` cannot raise
    (C1). Cache the built config on the instance with `object.__setattr__`.
  - The validator passed to `CorrelationIDConfig` always enforces
    `CORRELATION_ID_PATTERN` (D9), and additionally `default_uuid_validator`
    when `validate_incoming_ids` is set. `validate_incoming_ids` can never relax
    below the hard contract.
  - `__post_init__` must coerce `trusted_sources` to a tuple with
    `object.__setattr__`, mirroring `ApiDependencies.__post_init__` at
    `episodic/api/dependencies.py:117`; a frozen dataclass does not coerce
    sequences and an uncoerced list makes the instance unhashable.
  - Translation must catch **both** `TypeError` and `ValueError`.
  - Reject `traceparent` and `tracestate` as header names with a message
    pointing at the deferred OpenTelemetry work: a bare UUID hex in a
    `traceparent` header is syntactically invalid trace context that collectors
    will drop.
  - `configure_celery_correlation` is a thin re-export narrowed to `Celery`;
    upstream's type parameter is unbounded, so `configure_celery_correlation(42)`
    would typecheck.
  - `build_correlated_async_client` constructs
    `httpx.AsyncHTTPTransport(verify=..., limits=..., proxy=...)` itself before
    wrapping, per D12 and Risk R10.
  - Keep the module under 400 lines (C8) and give every public symbol a
    NumPy-style docstring.
- **Environment variables:**

  | Variable | Default | Meaning |
  | --- | --- | --- |
  | `API_CORRELATION_HEADER_NAME` | `X-Correlation-ID` | Header read inbound and written outbound. |
  | `API_CORRELATION_TRUSTED_SOURCES` | empty | Ingress or proxy IP addresses and CIDR ranges. Empty trusts nothing. Read Risk R2 before setting. |
  | `API_CORRELATION_VALIDATE_INCOMING` | `true` | Whether a trusted caller's identifier must additionally be a well-formed UUID. Cannot relax the hard contract. |
  | `API_CORRELATION_ECHO_RESPONSE_HEADER` | `true` | Whether to write the header on responses. |

  Parse booleans in the style of `episodic/worker/runtime.py:_parse_bool`. Strip
  whitespace and ignore empty entries when splitting, so
  `"10.0.0.0/8, 192.168.1.0/24,"` parses to two entries.
- **Wiring:** `episodic/api/runtime_config.py` gains
  `correlation: CorrelationSettings = dc.field(default_factory=CorrelationSettings)`
  on `RuntimeConfig`, documented in the class docstring, set in
  `_load_runtime_config`, with `CorrelationConfigurationError` translated to
  `RuntimeConfigurationError`.
- **Deliberately not wired: `WorkerRuntimeConfig`.** The first draft added the
  field there. Three reasons not to. Nothing reads it — the `rpc://` check uses
  `result_backend` and no worker task constructs an LLM adapter, as this plan's
  own Scope records. `API_`-prefixed variables in a process whose namespace is
  `EPISODIC_CELERY_*` mislabels ownership. And most concretely, it is a live
  bug: `load_runtime_config` wraps construction in
  `except ValueError as exc: raise RuntimeError("RabbitMQ-backed worker
  configuration is invalid.")` at `episodic/worker/runtime.py:227-229`, and
  `CorrelationConfigurationError` subclasses `ValueError` — so a bad CIDR range
  would be reported to the operator as a broker problem. Add the field when the
  first worker-side task builds an adapter, and hoist the call out of that
  `try:` when you do.
- **Red tests:** `tests/test_request_correlation_settings.py`,
  `tests/test_request_correlation_client.py`,
  `tests/test_request_correlation_imports.py`, and new cases in
  `tests/test_runtime_configuration.py`.
- **Acceptance evidence:** run

  ```bash
  uv run pytest tests/test_request_correlation_settings.py \
    tests/test_request_correlation_client.py \
    tests/test_request_correlation_imports.py \
    tests/test_runtime_configuration.py -v
  ```

  It fails before the module exists and passes after.
- **Conformance check:** `make check-architecture` passes — but note C2: it
  proves less than it appears to. INV-9 is the real check.
- **Recovery:** delete the module and revert the config file.
- **Compatibility decision:** none. `RuntimeConfig` is application-internal and
  pre-1.0, and every one of its construction sites is keyword-based (verified),
  so a trailing defaulted field breaks nothing.

### EP-M2 — Middleware wiring

- **Outcome:** every HTTP request carries a sanitized identifier on
  `req.context`, the response echoes it when configured, denials carry it, and
  untrusted callers cannot choose it.
- **Requirements:** RM-4.1.3.b; discharges INV-1 and INV-2.
- **Edits:**
  - `episodic/api/dependencies.py`: append
    `correlation: CorrelationSettings = dc.field(default_factory=CorrelationSettings)`
    to `ApiDependencies`. **Append at the end** — the dataclass is
    `frozen=True, slots=True` with fourteen construction sites, and inserting
    elsewhere shifts positional arguments. No `__post_init__` validation is
    needed because `CorrelationSettings` validates itself (EP-M1); this is true
    only because INV-6 moved validation into `__post_init__`.
  - `episodic/api/app.py`, in `create_app` before line 307: register the
    correlation middleware **before** the authorization middleware:

    ```python
    # Authorization logs its denials, so the identifier must exist first.
    app.add_middleware(build_correlation_middleware(dependencies.correlation))
    app.add_middleware(AuthorizationMiddleware(dependencies.authorization))
    ```

  - `episodic/api/runtime.py`, in the `ApiDependencies(...)` construction at
    line 272: pass `correlation=config.correlation`.
  - `episodic/api/runtime.py`: warn when a loopback address appears in the
    trusted-source list (Risk R2). This warning only becomes visible after
    EP-M3b's bootstrap; that ordering is deliberate and noted here so the
    implementer does not conclude the warning is broken.
- **Red tests:** `tests/test_api_request_correlation.py` and
  `tests/test_api_request_correlation_properties.py`.
- **Acceptance evidence:**

  ```bash
  uv run pytest tests/test_api_request_correlation.py \
    tests/test_api_request_correlation_properties.py -v
  ```

  Expect the denial cases to show the header on `401` and `403` responses.
- **Conformance check:** ADR 002 still holds — `create_app` reads no environment
  and, because of INV-6, cannot raise a configuration error either.
- **Recovery:** remove the `add_middleware` call and the `ApiDependencies` field.
- **Compatibility decision:** none.

### EP-M3a — Split `episodic/observability.py`

- **Outcome:** the module is comfortably under the 400-line limit, so EP-M3b can
  edit it.
- **Requirements:** prerequisite for RM-4.1.3.b; discharges C8.
- **Rationale:** the file is 399 lines and `too-many-lines` is an enabled,
  blocking Pylint rule. This milestone exists solely because the first draft
  costed the edit at zero.
- **Edits:** split into `episodic/observability.py` (ports and shared types),
  `episodic/observability_metrics.py`, and `episodic/observability_tracing.py`,
  or extract the `Noop*` adapters — whichever yields the cleaner seam. Then
  rename the roughly twenty Skylos entry-point rules naming
  `episodic.observability.*` symbols at `pyproject.toml` lines ~825-850 **in
  lockstep**; a stale rule is a blocking `make lint` failure just as surely as
  an oversized module.
- **Acceptance evidence:** `make lint` passes and no file exceeds 400 lines:

  ```bash
  find episodic -name '*.py' -exec wc -l {} + | sort -rn | head -5
  ```

- **Conformance check:** pure refactor; no behaviour change, no port change.
  Existing observability tests pass unmodified.
- **Recovery:** `git revert` the milestone commit.
- **Compatibility decision:** none. These are application-internal modules; move
  the symbols and update every importer together rather than leaving an alias
  module behind.

### EP-M3b — Bootstrap logging and carry the identifier

- **Outcome:** the service actually logs, and the log lines a request produces
  carry its identifier.
- **Requirements:** RM-4.1.3.b; discharges INV-3.
- **Edits:**
  - `episodic/logging.py`: add `log_debug`, and a private helper that appends a
    space-separated `correlation_id=<id>` field to a formatted message when
    `current_correlation_id()` returns a value. Call it from all four helpers
    immediately after `_format_message`.
  - `episodic/api/runtime.py` and `episodic/worker/runtime.py`: call
    `configure_logging(environ.get("EPISODIC_LOG_LEVEL"))` at the top of
    `create_app_from_env` and `create_celery_app_from_env` (D6). Without this
    the milestone delivers nothing observable and both of this plan's headline
    risk warnings emit no bytes.
  - `episodic/api/authorization.py:171-179`: route `_log_authorization_denial`
    through `log_warning`, promoting it from `DEBUG`. An authorization denial is
    an audit-relevant event; `DEBUG` was the wrong level independently of this
    feature.
  - `episodic/llm/openai_api/utils.py:108-111`: add
    `correlation_id=current_correlation_id()` to `_log_error_event`'s JSON
    payload when one is active. This path already emits structured JSON, so it
    gets a real field rather than a decorated string — and it is the provider
    error path the `Purpose` section names.
  - `episodic/observability_metrics.py` and `episodic/observability_tracing.py`:
    include the identifier under a reserved `trace_context` key, **not** merged
    into the `labels` mapping (D7).
- **Red tests:** new cases in `tests/test_logging.py`; the integration
  assertion in `tests/test_api_request_correlation.py`; updated observability
  tests.
- **Acceptance evidence:** `uv run pytest tests/test_logging.py -v`, then run
  the service and confirm a denial produces, on standard error:

  ```plaintext
  Authorization denied with AuthorizationDecision.UNAUTHORIZED for GET /v1/series-profiles. correlation_id=019b3c9d61aa7d2f9e1b2c3d4e5f6071
  ```

- **Conformance check:** confined to infrastructure and adapter modules; no
  domain module gains a dependency. Verify with INV-9.
- **Recovery:** revert the helper and its call sites.
- **Compatibility decision:** none. Log text has no external consumer. If a
  snapshot captures a log line, update it deliberately and note it under
  `Surprises & discoveries`.

### EP-M4 — Celery propagation

- **Outcome:** a task published while a request is in flight carries the
  identifier on the wire; the worker restores it around execution and does not
  leak it between tasks; and an `rpc://` backend cannot silently disable it.
- **Requirements:** RM-4.1.3.d; discharges INV-4a through INV-4d.
- **Edits:**
  - `episodic/worker/runtime.py`, in `create_celery_app` after
    `app.conf.update(...)` and before `register_scaffold_tasks`: call
    `configure_celery_correlation(app)`, imported through the seam. Comment that
    this is declarative — the handlers are already registered by import (AXIOM-8)
    — so nobody later "fixes" a call that appears to do nothing.
  - In the same function: when `app.backend.as_uri()` begins with `rpc://`,
    raise unless `EPISODIC_CELERY_ALLOW_UNCORRELATED_RPC_BACKEND` is true, and
    log a warning when it is. Assert on `app.backend.as_uri()`, not the raw
    environment string, so the check matches what the library actually consults
    (Risk R3).
- **Red tests:** `tests/test_worker_request_correlation.py`, structured exactly
  as INV-4a through INV-4d prescribe. Read those obligations before writing a
  line of test code; both of the obvious test designs are vacuous.
- **Acceptance evidence:**

  ```bash
  uv run pytest tests/test_worker_request_correlation.py -v
  ```

- **Conformance check:** ADR 003 still holds; `episodic/worker/tasks.py` is
  unchanged.
- **Recovery:** remove the call and the guard.
- **Compatibility decision:** the AMQP `correlation_id` property is a wire
  format shared with any deployed worker. Overwriting it is the library's
  documented behaviour and is safe here because no deployed consumer reads it:
  `episodic/worker/tasks.py` carries its own domain `correlation_id` inside the
  task payload, and the `rpc://` guard protects the only Celery feature that
  depends on the property. Record in ADR-018.

### EP-M5 — Outbound provider calls

- **Outcome:** the inference provider receives the identifier on every request
  the adapter makes with its own client, and an injected client can be
  retrofitted.
- **Requirements:** RM-4.1.3.e; discharges INV-5.
- **Reviewer gate:** D10 adds `correlate_client` beyond the roadmap's literal
  wording. Confirm acceptance before starting.
- **Edits:**
  - `episodic/llm/openai_api/`: add
    `correlation_header_name: str = DEFAULT_CORRELATION_HEADER_NAME` and
    `transport: httpx.AsyncBaseTransport | None = None` to
    `OpenAICompatibleLLMConfig`. Add a `correlation_header_name` check to
    `_llm_config_checks` (`utils.py:139-174`) and to the
    `_OpenAIConfigForValidation` protocol, because upstream raises
    `ValueError("header_name must not be empty or whitespace")` from a
    third-party constructor that the class docstring's `Raises` section
    attributes to config validation.
  - `episodic/llm/openai_api/adapter.py:135`: build the owned client through
    `build_correlated_async_client(header_name=config.correlation_header_name,
    transport=config.transport)`. Leave `_owns_client` untouched. Extend the
    `client` parameter docstring with the ownership contract: an injected client
    is the caller's responsibility, and a caller wanting correlation should use
    `correlate_client` or `build_correlated_async_client`.
  - `episodic/api/runtime.py:77`, in `_build_llm_port`: pass
    `correlation_header_name=config.correlation.header_name`.
  - `tests/steps/no_qa_generation_slice_support.py:215`: wrap the injected
    client with `correlate_client`, closing Risk R7 at the repository's only
    injected-client site. Its chaos header is set at line 256, after
    construction, so nothing is lost.
- **Red tests:** `tests/test_llm_openai_adapter_correlation.py`, following
  INV-5's single prescribed design.
- **Acceptance evidence:**

  ```bash
  uv run pytest tests/test_llm_openai_adapter_correlation.py -v
  ```

- **Conformance check:** `episodic.llm.openai_api` remains an outbound adapter.
- **Recovery:** revert the edits.
- **Compatibility decision:** none; both new config fields are defaulted and
  every construction site is keyword-based (verified).

### EP-M6a — Header-contract scenarios

- **Outcome:** the operator-facing header contract is observed end to end,
  without needing an inference server.
- **Requirements:** RM-4.1.3.f.
- **Rationale for the split:** the first draft's single EP-M6 spanned HTTP,
  provider calls, and a live subprocess. These four scenarios hit `/health/live`
  and a protected endpoint only, so this milestone leaves the repository in a
  valid gated state on a machine with no `vidaimock` binary.
- **New file:** `tests/features/request_correlation.feature`:

  ```gherkin
  Feature: Request correlation at the HTTP boundary

    Background:
      Given the HTTP service trusts correlation identifiers from the test ingress

    Scenario: A generated correlation identifier is echoed to the caller
      When an anonymous client requests a health endpoint
      Then the response carries a correlation header
      And the correlation header value satisfies the identifier contract

    Scenario: A trusted ingress may supply the correlation identifier
      When the ingress requests a health endpoint with correlation identifier "0195f1d2-3c4b-7a8d-9e0f-112233445566"
      Then the response correlation header equals "0195f1d2-3c4b-7a8d-9e0f-112233445566"

    Scenario: An untrusted client cannot choose the correlation identifier
      When an untrusted client requests a health endpoint with correlation identifier "0195f1d2-3c4b-7a8d-9e0f-112233445566"
      Then the response correlation header does not equal "0195f1d2-3c4b-7a8d-9e0f-112233445566"

    Scenario: A hostile identifier from a trusted ingress is rejected
      When the ingress requests a health endpoint with correlation identifier "abc method=GET path=/admin principal_id=root"
      Then the response correlation header does not contain "principal_id"
      And the correlation header value satisfies the identifier contract

    Scenario: A denied request still carries the correlation identifier
      When an unauthorized client requests a protected endpoint
      Then the response status is 401
      And the response carries a correlation header
  ```

- **New file:** `tests/steps/test_request_correlation_steps.py`. Drive the app
  through `httpx.ASGITransport(app=create_app(dependencies))` with
  `base_url="http://testserver"`, following `tests/fixtures/api.py:79-93`. To
  simulate an untrusted peer, use `httpx.ASGITransport(client=("203.0.113.9",
  5000))` — this is how the untrusted scenario is expressible at all, and the
  first draft did not say so. Note that `tests/steps/test_*_steps.py` modules are
  exempt from the future-annotations lint
  (`docs/developers-guide.md`, §Linting).
- **Acceptance evidence:**

  ```bash
  uv run pytest tests/steps/test_request_correlation_steps.py -v
  ```

  Expect five scenarios passing, with no skips — nothing here needs a binary.
- **Recovery:** additive; delete the files.
- **Compatibility decision:** none.

### EP-M6b — Provider echo-back scenario

- **Outcome:** the identifier is observed crossing the provider boundary.
- **Requirements:** RM-4.1.3.f; discharges INV-8.
- **New files:** `tests/features/request_correlation_provider.feature` with a
  single scenario, and
  `tests/steps/test_request_correlation_provider_steps.py`. Reuse
  `find_free_port` and `start_vidaimock_process` from
  `tests/steps/generation_orchestration_vidaimock.py`.
- **Four constraints established by probing Vidai Mock. Ignore these and you
  will lose hours:**
  1. The template engine is **Tera**, not Jinja2. `{{ __tera_context }}` dumps
     the request context. Header keys are **lowercased**, and access must use
     bracket syntax because dotted access cannot express a hyphen:
     `{{ headers['x-correlation-id'] | default(value='ABSENT') }}`. Since the
     header name is configurable, write the template using `header_name.lower()`.
  2. Templates are loaded once at start-up; there is **no hot reload**. Write the
     config and template before `start_vidaimock_process`, as the existing
     helpers already do.
  3. The echoed value must be embedded in a **valid draft payload**. The
     source-to-script slice parses the completion content as a draft-script JSON
     document (`_VALID_DRAFT` at
     `tests/steps/no_qa_generation_slice_support.py:35-42`); returning the bare
     identifier as `content` fails draft parsing before the assertion is
     reached. Put it in the title or a turn's text and extract it from the
     persisted draft or TEI.
  4. Build the adapter with `client=None` so the **owned**, correlated client is
     exercised, or wrap an injected client with `correlate_client`. Reusing
     `configure_vidaimock`'s wiring unchanged would inject a bare client and the
     scenario would fail for the wrong reason.
- **Acceptance evidence:**

  ```bash
  uv run pytest tests/steps/test_request_correlation_provider_steps.py -v
  ```

  One scenario passing, or one skip with `vidaimock executable not found in
  PATH` on a machine without the binary. CI installs a pinned binary and fails
  hard if it is missing.
- **Recovery:** additive; delete the files.
- **Compatibility decision:** none.

### EP-M7 — Documentation, ADR, chart, roadmap

- **Outcome:** an operator can configure and debug correlation without reading
  the source, and cannot accidentally adopt the dangerous configuration.
- **Requirements:** RM-4.1.3.g.
- **Edits:**
  - **New:** `docs/adr/adr-018-request-correlation-propagation.md`, following
    the section order at `docs/documentation-style-guide.md:414-491`. Record
    D2, D4, D5, D6, D7, D9, D10, D12; the import side effect (AXIOM-8); the
    `rpc://` interaction and the AMQP property compatibility argument; the
    trusted-source security model and why the pod CIDR is not supported; that
    `correlation_id` must never become a metric label; the single-header-name
    and WebSocket limitations; the runtime non-`isinstance` transport; and the
    exit condition for D5's message decoration — a femtologging release that
    carries ambient structured context. State plainly that the HTTP request
    correlation identifier is distinct from the domain `correlation_id`, and
    reference ADR 015.
  - `docs/users-guide.md`: the four environment variables; the identifier
    contract; that `API_CORRELATION_TRUSTED_SOURCES` means *the ingress or proxy
    source range, not the end client's address*; that listing the cluster pod
    CIDR is **not supported** because it trusts every pod (Risk R2); that the
    honest options are to have Traefik overwrite the header at the edge or to
    trust nothing and accept generated-only identifiers; that a long-running
    generation run keeps the identifier of the request that started it, while a
    run resumed after a restart has none; and the `curl -i` transcripts from
    `Purpose`.
  - `docs/developers-guide.md`: the `episodic.request_correlation` seam; the
    rule that `falcon_correlate` is imported in exactly one module and why C2's
    gate does not enforce it; why `ContextualLogFilter` is unused, including the
    two rejected escapes; the Celery eager-mode trap and the import-time signal
    registration, so nobody writes the vacuous test; the three concurrency
    boundaries where correlation ends (`gevent.spawn`, subinterpreters, threads
    not created via `asyncio.to_thread`); that `correlation_id` is appended last
    in logfmt; and the local debugging workflow.
  - `charts/episodic/`: add a Traefik `Middleware` and reference it from the
    Ingress, overwriting `X-Correlation-ID` at the edge so that trusting the
    ingress means what an operator would assume (Risk R2, and the mitigation
    that makes the trusted-source feature safe to enable at all).
  - `docs/infrastructure-design.md`: record the topology facts the trust
    decision depends on — that the peer address is a Traefik pod IP, and that
    no NetworkPolicy currently restricts pod-to-Service traffic despite line 157
    claiming otherwise.
  - `docs/episodic-podcast-generation-system-design.md:2033-2044`: replace the
    "still needs a dedicated request-correlation workstream" paragraph with what
    now exists, linking to ADR 018.
  - `docs/contents.md`: index ADR 018.
  - `docs/roadmap.md:606`: tick 4.1.3 to `[x]`.
- **Acceptance evidence:** `make markdownlint`, `make spelling`, and `make nixie`
  pass, then the full gate suite.
- **Conformance check:** every discovery in this plan is reflected upstream; no
  unrecorded deviation remains.
- **Recovery:** `git revert`.
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
sequential runs. Capture output, because long output is truncated:

```bash
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-$(git branch --show-current).out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-$(git branch --show-current).out
make lint      2>&1 | tee /tmp/lint-episodic-$(git branch --show-current).out
make test      2>&1 | tee /tmp/test-episodic-$(git branch --show-current).out
```

Run a focused test during red-green work:

```bash
uv run pytest tests/test_request_correlation_settings.py -v
```

Fix formatting before committing:

```bash
make fmt
```

Commit after each milestone, naming the milestone and the roadmap item.

## Validation and acceptance

**Definition of done.**

- Tests: `make test` passes with no skips other than the Vidai Mock skip in
  EP-M6b on a machine lacking the binary, and every obligation is discharged by
  a named artefact.
- Verification: INV-1 through INV-10 each have a passing artefact **and** a
  recorded non-vacuity check. An obligation whose non-vacuity check was not
  performed is not discharged. Three of the first draft's controls were
  unfalsifiable; check each one you write against the behaviour it claims to
  detect.
- Lint and typecheck: `make check-fmt`, `make typecheck`, and `make lint` exit
  zero. `make lint` includes `hecate`, Ruff, both Pylint passes (including the
  blocking 400-line limit), `ambrleaks`, and the blocking Skylos scan. The
  realistic Skylos trip is the **parameter** category, not `dead_code`:
  `build_correlated_async_client`'s `transport`, `verify`, `limits`, and `proxy`
  are supplied only by tests, and `tests` is outside `SKYLOS_PRODUCTION_TARGETS`.
  Pre-authorize a `type = "parameter"` entry-point rule naming the verified test
  caller, as `AGENTS.md` requires.
- Documentation: `make markdownlint`, `make spelling`, and `make nixie` pass.
- Security: the trusted-source default is empty; sanitization is unconditional;
  INV-1's `rejected-invalid` class is exercised with a logfmt-injection payload
  and a 60,000-character value.

**Manual acceptance.** Start the service trusting nothing and run the two
`curl -i` commands from `Purpose`. Both responses must carry the header. Confirm
the denial log line appears on standard error with the identifier appended —
this is the check that would have caught the first draft's central defect.
Repeat with `API_CORRELATION_ECHO_RESPONSE_HEADER=false` and confirm the header
disappears while the log lines still carry the identifier.

**Red-Green-Refactor evidence.** For each milestone record the red command and
its expected failure, the green command and result, and the gate commands after
refactoring. Paste short transcripts into `Artefacts and notes`.

## Idempotence and recovery

Every step is re-runnable. `make build` is idempotent. Test files are additive.
Edits to existing files are additive fields, two `add_middleware` calls, one
`configure_celery_correlation` call, two `configure_logging` calls, the logging
helper changes, and the EP-M3a refactor; each is reversible with `git revert` of
the milestone commit. Nothing writes to a database, migrates a schema, or
changes a persisted format.

If `uv sync` fails fetching the pinned revision, confirm network access to
`github.com` and that the `v0.1.0` tag still exists; the repository is public,
so no credential is required.

## Artefacts and notes

To be filled in during implementation with red and green transcripts per
milestone.

## Interfaces and dependencies

At the end of EP-M5 the public surface of `episodic/request_correlation.py` is
as specified under EP-M1.

`ApiDependencies`, `RuntimeConfig`, and `OpenAICompatibleLLMConfig` each gain
trailing defaulted fields as specified in their milestones. `WorkerRuntimeConfig`
gains nothing.

Dependency added to `pyproject.toml`:

```plaintext
falcon-correlate @ git+https://github.com/leynos/falcon-correlate@v0.1.0
```

No port protocol changes: `episodic/canonical/ports.py`, `episodic/llm/ports.py`,
`episodic/cost/ports.py`, and `episodic/metrics_ports.py` are untouched.
EP-M3b changes implementations of `MetricsPort` and `TracerPort`, which is not a
signature change.
