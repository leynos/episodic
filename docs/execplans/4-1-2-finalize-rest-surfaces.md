# Finalize REST surfaces for previous-phase artefacts

This Execution Plan (ExecPlan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`,
and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: COMPLETE

## Purpose and big picture

This change delivers roadmap item `4.1.2` by hardening every implemented `/v1`
Representational State Transfer (REST) endpoint with three consistent
cross-cutting concerns:

1. **Pagination.** Every list endpoint accepts `limit` and `offset`, validates
   `1 <= limit <= 100` and `offset >= 0`, and returns the documented
   `{items, limit, offset, total}` envelope.
2. **Filtering.** Every list endpoint that exposes a documented filter accepts
   the corresponding query parameter, validates it, and applies it through the
   service/repository contract.
3. **Role enforcement scaffold.** A minimal inbound-adapter-owned
   `AuthorizationPort` and Falcon middleware sit on the request path with a
   permit-all default adapter wired through `ApiDependencies`, returning
   `401 unauthorized` and `403 forbidden` envelope responses when a non-default
   adapter denies. Full Role-Based Access Control (RBAC) and tenancy isolation
   remain roadmap item `5.1`.

It also lands a unified error contract across every endpoint: every 4xx and 5xx
response body is the JSON envelope
`{"code": "<machine-readable>", "message": "<human>", "details": {...}}` per
`docs/episodic-tui-api-design.md` §"Error contract".

This work is API-layer hardening on already implemented canonical resources
(series profiles, episode templates, reference documents, reference document
revisions, reference bindings, resolved bindings, and the structured brief). It
introduces a small additive surface in the domain-port and outbound-adapter
groups so that `total` page counts can be supplied without inventing new
read-model entities. It does **not** add any phase-4.2 or later resources
(episodes, uploads, ingestion-jobs, generation-runs, audio-runs, exports,
voice-previews, WebSocket streams), and it does **not** implement the full
phase-5.1 RBAC and tenancy stack.

Success is observable when:

1. `curl http://.../v1/series-profiles?limit=10&offset=0` returns a JSON
   envelope of the form
   `{"items": [...], "limit": 10, "offset": 0, "total": <int>}`, and supplying
   `limit=0`, `limit=101`, or `offset=-1` returns `400` with body
   `{"code": "validation_error", "message": "...", "details": {"field":`
   `"limit"|"offset", "constraint": "range"}}`.
2. The same envelope shape is returned by `/v1/episode-templates`,
   `/v1/series-profiles/{id}/history`, `/v1/episode-templates/{id}/history`,
   `/v1/series-profiles/{id}/reference-documents`,
   `/v1/series-profiles/{id}/reference-documents/{doc_id}/revisions`,
   `/v1/reference-bindings`, and `/v1/series-profiles/{id}/resolved-bindings`.
3. A `PATCH /v1/series-profiles/{id}` with a stale `expected_revision` returns
   `409` with body
   `{"code": "revision_conflict", "message": "...", "details": {"entity_id":`
   `"<uuid>", "expected_revision": <int>}}` - and the same machine-readable
   `code` appears for the equivalent template, reference-document, and
   reference-binding endpoints.
4. Every existing 400/404/409 response previously returning
   `{"title": "...", "description": "..."}` (Falcon default) now returns the
   documented envelope, and route-versioning tests at
   `tests/test_api_route_versioning.py` are updated accordingly.
5. `/v1/series-profiles` with no `Authorization` header still succeeds while
   the scaffold adapter is permit-all; swapping in a deny-all adapter under
   `ApiDependencies` causes the same request to return `401` with body
   `{"code": "unauthorized", ...}`.
6. `docs/users-guide.md` and `docs/developers-guide.md` document the unified
   envelope, the pagination contract, and the authorization scaffold.
7. `docs/roadmap.md` marks item `4.1.2` done **only after** every gate is
   green and `coderabbit review --agent` reports no unresolved actionable
   concerns.
8. Required quality gates pass in sequence: `make check-fmt`,
   `make markdownlint`, `make nixie`, `make build`, `make lint` (which includes
   `make check-architecture`), `make typecheck`, `make test`, and
   `make check-migrations`.

## Constraints

- Preserve hexagonal architecture invariants per ADR 014
  (`docs/adr/adr-014-hexagonal-architecture-enforcement.md`) and the Hecate
  configuration in `[tool.hecate]` at `pyproject.toml:437-496`. The
  inbound-adapter group is allowed to import only `domain_ports`,
  `application`, and itself (`pyproject.toml:480-486`). The architecture check (
  `make check-architecture` → `hecate check`, invoked by `make lint` via
  `Makefile:73,77-78`) must remain green throughout.
- Domain and application layers must remain framework-agnostic. No Falcon,
  `httpx`, or HTTP-specific types may leak into `episodic.canonical.*`,
  `episodic.generation.*`, or `episodic.llm.*`.
- Repository signature changes must be additive. A new `count_*` Protocol
  method may be added per repository contract; existing list signatures must
  remain backwards-compatible with current call sites until the full migration
  to envelope responses is complete. No existing list method may change its
  return type.
- The error envelope `{code, message, details}` must be applied uniformly
  across every endpoint registered in `episodic/api/app.py`, including health
  endpoints — except that the readiness body `{status, checks}` returned by
  `HealthReadyResource.on_get` (`episodic/api/resources/health.py:52-70`)
  remains structurally distinct because it is a service-status payload, not an
  error. The readiness endpoint's `503` response **does** wrap into the error
  envelope when the cause is a probe exception, not a routine probe failure.
- Authorization scaffold defaults must remain permit-all so existing tests
  continue to pass without rewriting every fixture to inject a token. The
  scaffold's job is to land the seams, not enforce a policy.
- Reuse the existing `parse_pagination` helper
  (`episodic/api/helpers.py:117-135`); do not introduce a parallel
  implementation. Its bounds validation already satisfies the contract; only
  the envelope wrap and `total` value are new.
- Reuse `map_reference_error` (`episodic/api/helpers.py:138-151`) as the
  classification template for the new central error mapper. The existing
  reference-domain helper already discriminates four exception subclasses;
  extend the pattern rather than duplicate it.
- Surface the `error_code` and `entity_id` fields that already live on the
  domain exceptions (`episodic/canonical/profile_templates/types.py:196-232`)
  into the response `details` map. The domain layer is already richer than the
  wire format — the API layer must stop discarding that information.
- Use test-first workflow for every behavioural change:
  - update or add failing tests first,
  - run them to confirm failure,
  - implement the production change,
  - rerun to confirm pass.
- Maintain Falcon ASGI conventions per the existing patterns documented in
  `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md`, and
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`. The in-process
  PostgreSQL fixture stack at `tests/fixtures/database.py:122-203` must
  continue to back integration tests.
- Do not mark `docs/roadmap.md` item `4.1.2` done in a pre-implementation or
  in-progress branch. Mark it done only after all gates, documentation, and
  CodeRabbit review are complete.

## Tolerances (exception triggers)

- Scope: stop and escalate if implementation requires more than 28 production
  files (excluding tests) or more than 1800 net lines of non-test code.
- Public contract: stop and escalate if existing 2xx response bodies for any
  endpoint must change in any way other than gaining the documented `total`
  field on list envelopes. The pagination envelope keys `items`, `limit`,
  `offset` already exist; adding `total` is the only mutation.
- Repository surface: stop and escalate if any existing repository or service
  list method must change its return type (rather than gain an additive
  `count_*` companion method).
- Dependencies: stop and escalate before adding any new runtime or test
  dependency.
- Architecture: stop and escalate if any change would require an inbound
  adapter to import an outbound adapter, or if domain ports must learn about
  HTTP, Falcon, bearer tokens, or `Authorization` headers.
- Iterations: stop and escalate after 3 failed attempts to stabilize the same
  failing test cluster.
- Time: stop and escalate if any single milestone takes longer than 4 hours
  of focused work without producing a green focused-test run.
- Ambiguity: stop and present options if two materially different
  interpretations of any clause in `docs/episodic-tui-api-design.md` §"Error
  contract" or §"Pagination contract" produce different envelope shapes.
- RBAC scope creep: stop and escalate if the authorization scaffold drifts
  beyond a port, a middleware, and a permit-all adapter — specifically, if the
  implementation begins to attach scopes to specific resources, define role
  hierarchies, or wire tenant identifiers. Those belong to roadmap item `5.1`.

## Risks

- Risk: adding `total` requires repository-layer additions across all three
  layers (domain port, application service, SQLAlchemy adapter), which is
  outside a strictly inbound-adapter change. Severity: high. Likelihood: high.
  Mitigation: keep the change strictly additive (`count_*` methods on
  protocols, paralleled in SQLAlchemy adapters; service-layer wrappers return
  `(items, total)` tuples that are *new* wrapper functions, not mutations of
  existing list services). The architecture-check gate (
  `make check-architecture`) will catch any direction violations.

- Risk: legacy tests assert `{"title": "...", "description": "..."}` on
  4xx responses. Severity: medium. Likelihood: high. Mitigation: the test
  coverage survey identifies the canonical sites (
  `tests/test_api_route_versioning.py:21,86,102`; the helper
  `_assert_bad_request_error` at
  `tests/test_reference_document_api_support.py:160`; the body checks at
  `tests/test_binding_resolution_api.py:117-118`;
  `tests/test_profile_template_api.py:107` and similar). Replace the helper and
  let the cascade flow through.

- Risk: `make test` already contains the unrelated `U+FFFE` Hypothesis
  finding in `tests/test_guest_bios_properties.py` (recorded in the 4.1.1
  ExecPlan's Progress section). Severity: low. Likelihood: medium. Mitigation:
  this work must not attempt to fix that unrelated failure; rerun the targeted
  Hypothesis test under a fixed seed if needed and record the failure as
  pre-existing in `Surprises and Discoveries`.

- Risk: history endpoints (`/series-profiles/{id}/history`,
  `/episode-templates/{id}/history`) take no `limit`/`offset` today (
  `episodic/api/handlers.py:87-133`). Adding pagination is a full retrofit
  rather than an envelope wrap. Severity: medium. Likelihood: high. Mitigation:
  treat history pagination as a dedicated milestone (Milestone
  4) with its own repository additions (`list_for_profile_paged`,
  `list_for_template_paged`) and corresponding count helpers; surface `total`
  from those new methods.

- Risk: the resolved-bindings endpoint
  (`/series-profiles/{id}/resolved-bindings`) returns a flat `{items}` list
  today (`episodic/api/resources/resolved_bindings.py:75`) and the underlying
  `resolve_bindings` service performs an in-memory join with no pagination
  affordance. Severity: medium. Likelihood: medium. Mitigation: paginate at the
  API layer (slice the in-memory list, count its length for `total`). Document
  the decision in the Decision Log; if the resolved set grows large enough to
  require service-layer pagination, capture that as a follow-up.

- Risk: the `503 Service Unavailable` body returned by
  `HealthReadyResource.on_get` (`episodic/api/resources/health.py:52-70`)
  diverges from the error envelope because it carries the `checks` map.
  Severity: low. Likelihood: low. Mitigation: explicitly exempt routine
  readiness failures from the envelope rewrite (decision recorded below); only
  probe-raises paths flow through the envelope handler.

- Risk: the central Falcon error handler must be careful not to alter the
  `2xx` resource bodies that already include `items`/`limit`/`offset`.
  Severity: low. Likelihood: low. Mitigation: register the handler only for
  `falcon.HTTPError` and its subclasses (
  `app.add_error_handler(falcon.HTTPError, ...)`), which Falcon dispatches
  before serialization; success responses use `resp.media` directly and are not
  intercepted.

- Risk: the new `AuthorizationPort` could accidentally be imported by domain
  code if it is mistakenly placed under `episodic.canonical`. Severity: medium.
  Likelihood: low. Mitigation: keep the port and the permit-all implementation
  inside `episodic/api/authorization.py` (inbound-adapter group); the
  architecture gate will reject any cross-group reach.

- Risk: CodeRabbit may raise actionable concerns about the centralized
  error handler that conflict with the plan. Severity: low. Likelihood: medium.
  Mitigation: run `coderabbit review --agent` after each major milestone and
  resolve concerns before proceeding.

## Progress

- [x] (2026-05-23T17:30Z) Loaded `leta`, `hexagonal-architecture`,
  `execplans`, and `firecrawl` skills; added the worktree as a leta workspace.
- [x] (2026-05-23T17:30Z) Reviewed `docs/roadmap.md` §4.1.2,
  `docs/episodic-tui-api-design.md` §"Error contract" and §"Pagination
  contract", `docs/adr/adr-009-source-to-script-rest-vertical-slice.md`,
  `docs/adr/adr-014-hexagonal-architecture-enforcement.md`,
  `docs/adr/adr-002-http-service-composition-root.md`, and the prior ExecPlan
  `docs/execplans/4-1-1-introduce-v1-target-api-prefix.md`.
- [x] (2026-05-23T17:30Z) Created context pack `pk_gsp3r7fg` for the Wyvern
  planning team and ran three subagents in parallel (API surface inventory,
  test coverage survey, architecture/hexagonal guard).
- [x] (2026-05-23T17:30Z) Resolved external prior art via WebFetch: Falcon 4
  `App.add_error_handler` and `set_error_serializer` semantics, RFC 9457
  Problem Details (the IETF replacement for RFC 7807; project elects the
  closely-related but domain-specific `{code, message, details}` envelope
  defined in `docs/episodic-tui-api-design.md`), and Falcon ASGI middleware
  conventions for authentication.
- [x] (2026-05-23T17:30Z) Drafted this ExecPlan.
- [x] (2026-05-25T00:00Z) User approved implementation and requested
  `leta` workspace initialization plus CodeRabbit review after each major
  milestone.
- [x] (2026-05-25T00:00Z) Milestone 1: central error envelope wiring and test
  harness updates. Focused red run failed on the previous Falcon
  `{title, description}` bodies; focused green run passed 28 tests in
  `/tmp/4-1-2-m1-green.out`.
- [x] (2026-05-25T00:00Z) Milestone 2: pagination `total` plumbing for
  reference-domain endpoints (additive `count_*` Protocols + SQLAlchemy
  implementations). Focused red run failed on missing `total`; focused green
  run passed 70 tests in `/tmp/4-1-2-m2-green.out`.
- [x] (2026-05-25T00:00Z) Milestone 3: pagination retrofit on series-profile,
  episode-template, and resolved-bindings list endpoints. Focused red run showed
  `/v1/series-profiles` ignoring `limit`; focused green run passed 68 tests in
  `/tmp/4-1-2-m3-green-after-coderabbit-3.out`. CodeRabbit requested stronger
  parameterized assertions and assertion messages in the pagination regression
  test; those were applied, gated, and the final follow-up review returned zero
  findings in `/tmp/4-1-2-m3-coderabbit-followup-3.out`.
- [x] (2026-05-25T00:00Z) Milestone 4: history-endpoint pagination retrofit.
  Focused red run showed the history resources returning only `{items}` and
  ignoring invalid `limit`; focused green run passed 94 profile/history-focused
  tests in `/tmp/4-1-2-m4-green-after-coderabbit-7.out`. CodeRabbit requested
  additional pagination boundary/default coverage, error-detail assertions, and
  clearer test documentation; those were applied, gated, and the final
  follow-up review returned zero findings in
  `/tmp/4-1-2-m4-coderabbit-followup-5.out`.
- [x] (2026-05-25T00:00Z) Milestone 5: filter parameter consistency pass.
  Focused red run showed invalid reference-document `kind` being hidden behind
  a 404 and invalid binding `target_kind` missing field-level details; focused
  green run passed 103 `/v1` API tests in `/tmp/4-1-2-m5-green.out`. The final
  CodeRabbit review returned zero findings in `/tmp/4-1-2-m5-coderabbit.out`.
- [x] (2026-05-25T00:00Z) Milestone 6: authorization scaffold
  (`AuthorizationPort`, middleware, permit-all adapter, `ApiDependencies`
  wiring). Focused red run showed `ApiDependencies` missing authorization
  injection; focused green run passed 111 authorization and `/v1` tests in
  `/tmp/4-1-2-m6-green-after-coderabbit-2.out`. CodeRabbit follow-ups converted
  the port to async, added non-`/v1` bypass and adapter-failure coverage, and
  consolidated denial logging. One requested `BLE001` suppression was not
  applied because Ruff rejects it as an unused `noqa` (
  `/tmp/4-1-2-m6-lint-after-coderabbit-15.out`); the catch-all remains covered
  by `tests/test_api_authorization.py`.
- [x] (2026-05-25T00:00Z) Milestone 7: documentation alignment. Updated the
  users guide REST reference, developers guide error/pagination/filter/auth
  sections, and reusable-reference system-design contract. `make fmt` completed
  in `/tmp/4-1-2-m7-fmt.out`; unrelated formatter churn was restored before the
  commit.
- [x] (2026-05-25T00:00Z) Milestone 8: full gate run plus
  `coderabbit review --agent`; mark roadmap item `4.1.2` done. Final gates are
  complete. `mbake validate Makefile`, `make check-fmt`, `make markdownlint`,
  `make nixie`, `make build`, `make lint`, `make typecheck`, and
  `make check-migrations` passed in `/tmp/4-1-2-*.out`. The first full
  `make test` pass found a stale assertion in `tests/test_lifespan_hooks.py`;
  that test now expects the documented pagination envelope. The rerun passed
  720 tests and 3 skips with only the pre-existing guest-bios `U+FFFE` property
  failure remaining in `/tmp/4-1-2-test-after-lifespan.out`.
  `coderabbit doctor` passed with 9 checks and the final
  `coderabbit review --agent` returned zero findings in
  `/tmp/4-1-2-coderabbit-review.out`; `docs/roadmap.md` now marks `4.1.2`
  complete.

## Surprises and discoveries

- Observation: the project's domain exceptions are already structured with
  `error_code` and `entity_id` attributes (for example,
  `EntityNotFoundError.error_code = "entity_not_found"` and
  `RevisionConflictError.error_code = "revision_conflict"`). Evidence:
  `episodic/canonical/profile_templates/types.py:196-232`. Impact: the API
  layer can attach the existing machine-readable code to the response envelope
  without inventing new mappings.

- Observation: three of the eight list endpoints already emit
  `{items, limit, offset}` but no `total`. Evidence:
  `episodic/api/resources/reference_documents.py:130-136,265-273` and
  `episodic/api/resources/reference_bindings.py:87-93`. Impact: only `total`
  and the documented filters need to be added for these endpoints; the other
  five list endpoints need full envelope retrofits.

- Observation: history endpoints have no pagination affordance at any layer
  — `_SeriesProfileHistoryRepository.list_for_profile(profile_id)` and
  `_EpisodeTemplateHistoryRepository.list_for_template(template_id)` accept no
  `limit`/`offset`. Evidence:
  `episodic/canonical/profile_templates/types.py:296-318`;
  `episodic/canonical/storage/history_repositories.py:146-201`. Impact: history
  pagination requires both new repository signatures and updated service-layer
  wrappers; this is the largest single subtask in the plan.

- Observation: tests pin Falcon's default `{title, description}` body in
  several places. Evidence: `tests/test_api_route_versioning.py:21,86,102`;
  `tests/test_reference_document_api_support.py:160` (the helper
  `_assert_bad_request_error`); `tests/test_binding_resolution_api.py:117`.
  Impact: a single helper rewrite plus targeted assertion updates cascade
  through the suite cleanly.

- Observation: no test asserts a `total` key in any pagination envelope,
  and no test sends an `Authorization` header to any `/v1` endpoint. Evidence:
  zero hits for `"total"` in pagination assertions, zero authentication
  fixtures. Impact: the new test coverage is purely additive — there is nothing
  to delete.

- Observation: there is no existing centralized error handler. Evidence:
  no `add_error_handler` or `set_error_serializer` call in
  `episodic/api/app.py:61-128`. Impact: introducing one is greenfield.

- Observation: the `domain_ports` Hecate group allows imports from
  `domain_ports` only (`pyproject.toml:466`), so any port that references
  HTTP-specific concepts (bearer tokens, scopes) must live outside the domain.
  The `AuthorizationPort` scaffold therefore lives in
  `episodic/api/authorization.py` for this work, with a future migration to
  `episodic/canonical/ports.py` planned alongside roadmap `5.1` when the port
  operates on series and organization identifiers.

- Observation: Falcon ASGI accepts only coroutine error handlers registered via
  `App.add_error_handler`; a synchronous handler raises
  `falcon.errors.CompatibilityError` during app construction. Impact:
  `handle_http_error` is an `async def` even though its work is synchronous.

- Observation: the full `make test` gate for Milestone 1 reproduced the known
  unrelated Hypothesis `U+FFFE` guest-bios failure in
  `tests/test_guest_bios_properties.py::test_enriched_guest_bios_replaces_prior_guest_bios_div`.
  The same run also found two remaining planned assertion updates in
  `tests/test_binding_resolution_api.py`; those were updated to the new
  envelope. Impact: Milestone 1 continues to avoid changing guest-bios
  production code, per the risk inventory.

- Observation: CodeRabbit's Milestone 1 review returned docstring-completeness
  findings for the new public API error helpers plus two defensive parsing
  findings for unusual Falcon status values. Impact: the public docstrings now
  follow the project's NumPy-style convention, `_error_message` falls back on
  unknown status codes, and `_status_code` falls back to `500` if Falcon ever
  supplies an unparsable status string.

- Observation: the follow-up CodeRabbit pass requested Python 3 tuple
  exception syntax in `_status_code`, but the repository targets Python 3.14
  and Ruff formats `except (IndexError, ValueError):` to the PEP 758
  parenthesis-free form `except IndexError, ValueError:`. Impact: the code
  keeps Ruff's formatted Python 3.14 syntax; the style-level requests for
  match/case, private-helper docstrings, and richer test assertion messages
  were applied.

- Observation: CodeRabbit requested `# noqa: BLE001` on the authorization
  middleware catch-all for adapter failures, but Ruff reports that suppression
  as unused because `BLE001` is not active in this project configuration.
  Impact: the code keeps the deterministic lint-clean `except Exception:`
  branch, with behaviour covered by
  `test_authorization_adapter_exception_returns_503`.

- Observation: the final full-suite gate exposed one stale test assertion in
  `tests/test_lifespan_hooks.py::test_create_app_keeps_existing_canonical_routes_working`.
  The route remained available, but the assertion still expected the old
  `{"items": []}` body after roadmap item `4.1.2` intentionally standardized
  list responses on `{items, limit, offset, total}`. Impact: the assertion now
  checks the documented empty pagination envelope, and the focused test passes
  in `/tmp/4-1-2-lifespan-focused.out`.

## Decision log

- Decision: implement `total` via additive `count_*` Protocol methods on
  each repository contract rather than mutating existing `list_*` return types
  or computing counts at the API layer. Rationale: avoids breaking existing
  call sites, preserves the architecture rule (domain-ports group only allows
  imports from itself), and matches the Wyvern architecture guard's
  recommendation. Date/Author: 2026-05-23 / planning team.

- Decision: register a single Falcon error handler in
  `episodic/api/app.py` (`app.add_error_handler(falcon.HTTPError, ...)`) that
  rewrites every `HTTPError` body into the `{code, message, details}` envelope,
  while keeping per-family classification helpers (extending
  `map_reference_error` and adding a profile/template equivalent) in a new
  `episodic/api/errors.py` module. Rationale: Pattern B keeps the dozens of
  `raise falcon.HTTPBadRequest(description=...)` call sites untouched and
  serialization centralized; Pattern A is still required for mapping domain
  exception families to status codes. Date/Author: 2026-05-23 / planning team.

- Decision: place the `AuthorizationPort` Protocol and its `PermitAll`
  default adapter inside `episodic/api/authorization.py`, wire it through
  `ApiDependencies.authorization` (default `PermitAll()`), and install
  `AuthorizationMiddleware` from `episodic/api/app.py`. Rationale: the scaffold
  operates purely on HTTP-request metadata (bearer-token strings, route,
  method) and need not yet know about series or organizations; keeping it
  inbound-adapter-local satisfies the architecture policy and defers the
  domain-port relocation to roadmap `5.1` when tenant identifiers enter the
  picture. Date/Author: 2026-05-23 / planning team.

- Decision: paginate `/v1/series-profiles/{id}/resolved-bindings` at the
  API layer (slice the resolved list, count the slice length plus the remaining
  size for `total`) rather than push pagination into `resolve_bindings`.
  Rationale: the resolved set is built by an in-memory join over
  already-fetched series/template bindings; service-layer pagination would
  invite premature optimization. Date/Author: 2026-05-23 / planning team.

- Decision: exempt the `HealthReadyResource` `503` routine-probe-failure
  body `{status, checks}` from the envelope rewrite. Probe-raises paths (where
  a probe itself throws) still flow through the envelope handler. Rationale:
  the readiness body is a structured status payload consumed by deployment
  platforms, not an error; documented at `docs/developers-guide.md` and
  exercised at `tests/test_health_endpoints.py:24-99`. Date/Author: 2026-05-23
  / planning team.

- Decision: place new filter-parsing helpers next to `parse_pagination` in
  `episodic/api/helpers.py` rather than create a separate
  `episodic/api/filters.py`. Rationale: matches the existing convention (UUID
  parser, pagination parser, payload-dict validator already colocated there); a
  separate module would split a single cohesive set of request-validation
  helpers. Date/Author: 2026-05-23 / planning team.

- Decision: leave `/v1/series-profiles` without additional filters in this
  pass. Rationale: the design documents specify pagination for the collection
  but do not define a series-profile filter parameter; adding one would expand
  the public API beyond the planned REST surface. Date/Author: 2026-05-25 /
  Codex.

- Decision: do not implement `Idempotency-Key` handling, `Retry-After`, or
  `rate_limited` response codes in this ExecPlan. Rationale: those belong to
  ADR 009's vertical-slice work (`/v1/uploads`, `/v1/ingestion-jobs`,
  `/v1/generation-runs`) under roadmap `4.3` and to the broader rate-limiting
  story under roadmap `5.x`; the canonical endpoints covered by `4.1.2` do not
  create side effects that need idempotency replay. Date/Author: 2026-05-23 /
  planning team.

## Outcomes and retrospective

Roadmap item `4.1.2` is implemented. Every canonical `/v1` list endpoint now
uses the documented `{items, limit, offset, total}` envelope, validates
pagination consistently, and applies the documented filters through API helper
parsers. The API layer maps validation, not-found, conflict, unauthorized,
forbidden, and authorization-adapter-failure cases into the
`{code, message, details}` error envelope while preserving the readiness probe
status payload exemption.

The role-enforcement scaffold is in place as an inbound-adapter-local
`AuthorizationPort`, Falcon middleware, and permit-all default adapter wired
through `ApiDependencies`. Deny and failure behaviours are covered by
`tests/test_api_authorization.py`; full RBAC and tenancy policy remain roadmap
item `5.1` as planned.

Evidence:

- Focused milestone suites passed after each implementation slice:
  `/tmp/4-1-2-m1-green.out`, `/tmp/4-1-2-m2-green.out`,
  `/tmp/4-1-2-m3-green-after-coderabbit-3.out`,
  `/tmp/4-1-2-m4-green-after-coderabbit-7.out`, `/tmp/4-1-2-m5-green.out`, and
  `/tmp/4-1-2-m6-green-after-coderabbit-2.out`.
- Final deterministic gates passed for Makefile validation, formatting,
  Markdown linting, Mermaid validation, build, lint plus Hecate architecture
  check, typecheck, and migration drift: `/tmp/4-1-2-mbake.out`,
  `/tmp/4-1-2-check-fmt.out`, `/tmp/4-1-2-markdownlint.out`,
  `/tmp/4-1-2-nixie.out`, `/tmp/4-1-2-build.out`, `/tmp/4-1-2-lint.out`,
  `/tmp/4-1-2-typecheck.out`, and `/tmp/4-1-2-check-migrations.out`.
- Full `make test` rerun reached 720 passed and 3 skipped tests, with only the
  known unrelated guest-bios `U+FFFE` property failure remaining in
  `/tmp/4-1-2-test-after-lifespan.out`.
- `coderabbit doctor` passed 9 checks in `/tmp/4-1-2-coderabbit-doctor.out`.
  The final `coderabbit review --agent` returned zero findings in
  `/tmp/4-1-2-coderabbit-review.out`.

Deviation: the final full-suite gate is not fully green because of the
pre-existing
`tests/test_guest_bios_properties.py::test_enriched_guest_bios_replaces_prior_guest_bios_div`
`U+FFFE` Hypothesis failure. This branch did not touch guest-bios production
code; the failure is recorded as outside `4.1.2` scope.

## Context and orientation

The Falcon Asynchronous Server Gateway Interface (ASGI) application is
assembled by `create_app()` at `episodic/api/app.py:61-128`. Every canonical
resource is mounted under `/v1` and dispatched to one of nine resource classes:

- Series profile resources (`episodic/api/resources/series_profiles.py`):
  `SeriesProfilesResource` (list/create), `SeriesProfileResource` (get/patch),
  `SeriesProfileHistoryResource`, `SeriesProfileBriefResource`.
- Episode template resources
  (`episodic/api/resources/episode_templates.py`): `EpisodeTemplatesResource`
  (list/create), `EpisodeTemplateResource` (get/patch),
  `EpisodeTemplateHistoryResource`.
- Reference document resources
  (`episodic/api/resources/reference_documents.py`):
  `ReferenceDocumentsResource` (list/create per series),
  `ReferenceDocumentResource` (get/patch), `ReferenceDocumentRevisionsResource`
  (list/create revisions per document), `ReferenceDocumentRevisionResource`
  (get one revision by identifier).
- Reference binding resources
  (`episodic/api/resources/reference_bindings.py`): `ReferenceBindingsResource`
  (list/create), `ReferenceBindingResource` (get).
- Resolved bindings: `ResolvedBindingsResource`
  (`episodic/api/resources/resolved_bindings.py`).
- Health probes: `HealthLiveResource`, `HealthReadyResource`
  (`episodic/api/resources/health.py`).

Shared resource bases live at `episodic/api/resources/base.py:46-260` (
`_ResourceBase`, `_GetResourceBase`, `_GetHistoryResourceBase`,
`_CreateResourceBase`, `_UpdateResourceBase`). Shared request handlers live at
`episodic/api/handlers.py:41-257` (`handle_get_entity`, `handle_get_history`,
`handle_create_entity`, `handle_update_entity`). Shared request parsers live at
`episodic/api/helpers.py:54-474` (`parse_uuid`, `require_payload_dict`,
`require_query_params`, `parse_pagination`, `map_reference_error`,
`build_audit_metadata`, `parse_expected_revision`). Response serializers live at
`episodic/api/serializers.py`.

Architecture policy is enforced by the Hecate configuration under
`[tool.hecate]` in `pyproject.toml:437-496`, and checked by
`make check-architecture` (which runs `hecate check`, called transitively from
`make lint` via `Makefile:73,77-78`). The inbound-adapter group covers
`episodic.api`, `episodic.worker.tasks`, and `episodic.worker.topology` (
`pyproject.toml:480-486`) and may only import from the domain-ports,
application, and inbound-adapter groups. New API-layer modules (
`episodic/api/errors.py`, `episodic/api/authorization.py`) automatically
inherit the inbound-adapter classification by virtue of their `episodic.api`
prefix. The repo-local `episodic.architecture` module was removed in commit
`3403ace` when Hecate replaced it; references in earlier ExecPlans (for example,
`4.1.1`'s "ARCH001" mentions) now resolve to the same diagnostic identifier
emitted by Hecate.

Repository contracts of interest:

- `_SeriesProfileRepository.list()` and
  `_EpisodeTemplateRepository.list(series_profile_id=...)` Protocols at
  `episodic/canonical/profile_templates/types.py:273-284`; concrete SQLAlchemy
  implementations at `episodic/canonical/storage/repositories.py:111-118` and
  `:306-319`.
- `_SeriesProfileHistoryRepository.list_for_profile(profile_id)` and
  `_EpisodeTemplateHistoryRepository.list_for_template(template_id)` at
  `episodic/canonical/profile_templates/types.py:296-318`; SQLAlchemy
  implementations at
  `episodic/canonical/storage/history_repositories.py:146-201`.
- `ReferenceDocumentRepository.list_for_series(..., limit, offset)`,
  `ReferenceDocumentRevisionRepository.list_for_document(..., limit, offset)`,
  and `ReferenceBindingRepository.list_for_target(..., limit, offset)` at
  `episodic/canonical/reference_protocols.py:30-122`; concrete SQLAlchemy
  implementations at
  `episodic/canonical/storage/reference_repositories.py:57-261`.

Service-layer wrappers:

- `list_entities_with_revisions` and `list_history` for series profile and
  episode template, at
  `episodic/canonical/profile_templates/services/_generic.py:172-236`.
- `list_reference_documents`, `list_reference_document_revisions`, and
  `list_reference_bindings` under `episodic/canonical/reference_documents/` (
  `documents.py:77-95`, `revisions.py:70-91`, `bindings.py:394-426`).
- `resolve_bindings` under
  `episodic/canonical/reference_documents/resolution.py:295`.

Test harnesses of interest:

- `tests/fixtures/api.py:19-43` (`canonical_api_client`,
  `canonical_api_dependencies`, `canonical_api_async_client`).
- `tests/fixtures/database.py:122-203` (py-pglite stack).
- `tests/conftest.py:22` (plugin registration).
- `tests/test_profile_template_api.py`,
  `tests/test_binding_resolution_api.py`,
  `tests/test_binding_resolution_brief_endpoint.py`,
  `tests/test_reference_document_api_support.py`,
  `tests/test_reference_document_access.py`,
  `tests/test_reference_document_validation.py`,
  `tests/test_reference_document_roundtrip.py`,
  `tests/test_api_route_versioning.py`, `tests/test_health_endpoints.py`,
  `tests/test_lifespan_hooks.py`, `tests/api_fixtures.py`.
- BDD step modules: `tests/steps/test_profile_template_api_steps.py`,
  `tests/steps/test_reference_document_api_steps.py`,
  `tests/steps/test_binding_resolution_steps.py`,
  `tests/steps/test_reference_document_model_steps.py`,
  `tests/steps/test_http_service_scaffold_steps.py`.
- Feature files: `tests/features/profile_template_api.feature`,
  `tests/features/http_service_scaffold.feature` (and adjacent
  reference-document and binding-resolution feature files).

Source documents that govern this work:

- `docs/roadmap.md` §`4.1.2`.
- `docs/episodic-tui-api-design.md` §"Error contract" and §"Pagination
  contract".
- `docs/episodic-podcast-generation-system-design.md` §"Reusable reference
  REST API specification" (lines 1829-1875) and §"Client Experience Layer".
- ADR 002 (`docs/adr/adr-002-http-service-composition-root.md`),
  ADR 009 (`docs/adr/adr-009-source-to-script-rest-vertical-slice.md`), ADR 014
  (`docs/adr/adr-014-hexagonal-architecture-enforcement.md`).
- `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md`,
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`,
  `docs/agentic-systems-with-langgraph-and-celery.md`,
  `docs/langgraph-and-celery-in-hexagonal-architecture.md`.
- Prior ExecPlan `docs/execplans/4-1-1-introduce-v1-target-api-prefix.md`
  for `/v1` routing conventions.

Skills to load on resumption: `leta` for semantic code navigation,
`hexagonal-architecture` for boundary discipline, `execplans` for plan upkeep,
`commit-message` and `pr-creation` for delivery, `en-gb-oxendict` for British
English with Oxford spelling, `firecrawl` for external prior-art lookups.

External prior art that informs this plan:

- Falcon 4 `App.add_error_handler(HTTPError, handler)` (and the equivalent
  `set_error_serializer` hook) is the project's chosen seam for replacing the
  framework's default `{title, description}` body without touching resource
  code.
- RFC 9457 *Problem Details for HTTP APIs* (July 2023, supersedes RFC
  7807) is the closest IETF prior art for a unified error envelope; the
  project's `{code, message, details}` envelope from
  `docs/episodic-tui-api-design.md` shares the machine-readable-code and
  extension-fields intent but uses domain-specific keys, so the response
  `Content-Type` remains `application/json` rather than
  `application/problem+json`. This decision is local to the project and was not
  relitigated by this plan.
- Falcon ASGI middleware best practice for authentication: implement
  `process_request` so the auth check runs before routing overhead, store the
  principal on `req.context`, and short-circuit with `resp.complete = True`
  when denying.

## Plan of work

The work is organized as eight milestones. Each ends with a focused green test
run, a commit, and a CodeRabbit review on the milestone diff before the next
milestone begins.

### Milestone 1: central error envelope wiring

Goal: every 4xx and 5xx response body matches the documented envelope.

Test-first changes:

1. Update `tests/test_reference_document_api_support.py` so the helper
   `_assert_bad_request_error` (line 160) asserts the new envelope shape
   `{"code": "validation_error", "message": "...", "details": {...}}`. The
   helper rewrite cascades through
   `tests/test_reference_document_validation.py`,
   `tests/test_reference_document_access.py`,
   `tests/test_binding_resolution_api.py`, and
   `tests/test_profile_template_api.py`.
2. Update the route-versioning suite at
   `tests/test_api_route_versioning.py:21,86,102` to assert the envelope on the
   unversioned-route `404` responses and `/v1/health/live` `404` responses.
3. Add a new dedicated module `tests/test_api_error_envelope.py` that
   asserts:
   - `400 validation_error` body for invalid UUIDs, invalid pagination
     bounds, missing required payload fields, and missing required query
     parameters;
   - `404 not_found` body for unknown identifiers (including the
     cross-series 404 path);
   - `409 revision_conflict` body with `details.entity_id` and
     `details.expected_revision` for stale optimistic-lock updates on
     series profiles, episode templates, and reference documents;
   - `409 idempotency_conflict` body shape is reserved (the canonical
     endpoints do not yet trigger it; assert mapping invariants but skip
     the actual integration until ADR 009 work lands).

Production changes:

1. Add `episodic/api/errors.py` containing:
   - a dataclass `ErrorEnvelope(code, message, details)`;
   - a single Falcon error handler
     `handle_http_error(req, resp, exc, params)` that converts every
     `falcon.HTTPError` instance into an `ErrorEnvelope` and serializes
     it as the response body;
   - the per-family classification helpers `map_profile_template_error`
     (for `EntityNotFoundError` and `RevisionConflictError` from
     `episodic/canonical/profile_templates/types.py:196-232`) and a
     refactored `map_reference_error` (moved from
     `episodic/api/helpers.py:138-151`) that both raise pre-tagged
     Falcon exceptions carrying the machine-readable code and details.
   - The handler reads a `code` attribute set on `HTTPError.code` by the
     classification helpers; for raw Falcon exceptions raised without a
     code (older call sites still using `falcon.HTTPBadRequest(...)`),
     the handler picks a default from the status code
     (`400 -> validation_error`, `404 -> not_found`,
     `405 -> method_not_allowed`, `409 -> conflict`,
     `422 -> unprocessable_entity`, `500 -> internal_error`).
2. Update `episodic/api/helpers.py` so:
   - `parse_uuid` raises an `HTTPBadRequest` carrying `code=
     "validation_error"` and `details={"field": <name>, "constraint":
     "uuid"}`;
   - `parse_pagination` raises with `details={"field": "limit"|"offset",
     "constraint": "range"|"type"}`;
   - `require_payload_dict` raises with `details={"constraint":
     "object"}`;
   - `require_query_params` raises with `details={"field": <name>,
     "constraint": "required"}`;
   - `parse_expected_revision` raises with `details={"field":
     "expected_revision", "constraint": "positive-integer"}`;
   - `map_reference_error` becomes a thin re-export from
     `episodic/api/errors.py`.
3. Update `handle_update_entity` at `episodic/api/handlers.py:201-204` so
   the caught `RevisionConflictError` is re-raised through
   `map_profile_template_error`, which attaches
   `details={"entity_id": <uuid>, "expected_revision": <int>}`.
4. Register the handler in `episodic/api/app.py` via
   `app.add_error_handler(falcon.HTTPError, handle_http_error)` between the
   middleware setup and the route registrations.
5. Document the envelope and the error code list in
   `docs/developers-guide.md` §"REST error contract".

Go/no-go: focused red-then-green run of `tests/test_api_error_envelope.py`,
`tests/test_api_route_versioning.py`,
`tests/test_reference_document_validation.py`, and
`tests/test_profile_template_api.py`. Commit. Run `coderabbit review --agent`
on the milestone diff; clear actionable findings.

### Milestone 2: pagination `total` for reference-domain endpoints

Goal: the three reference-domain list endpoints already returning
`{items, limit, offset}` also return `total`.

Test-first changes:

1. Extend `tests/api_fixtures.py:160,221` so
   `assert_reference_document_list` and `assert_reference_revision_history`
   assert the presence and value of `total` alongside `items`, `limit`, and
   `offset`.
2. Extend `tests/test_reference_document_api_support.py:134,148-153`
   (bindings list assertions) to require `total`.
3. Add round-trip integration tests in
   `tests/test_reference_document_roundtrip.py` (or a new sibling) that create
   N documents, fetch the first page, assert `total == N` and
   `len(items) == limit`, fetch the last page, and assert
   `len(items) == N % limit`.

Production changes:

1. Add this method to `ReferenceDocumentRepository` Protocol at
   `episodic/canonical/reference_protocols.py:30-39` and its SQLAlchemy
   implementation at
   `episodic/canonical/storage/reference_repositories.py:57-81`.

   ```python
   def count_for_series(
       self,
       owner_series_profile_id: str,
       kind: ReferenceDocumentKind | None,
   ) -> int: ...
   ```

2. Add `count_for_document(self, document_id: str,
   owner_series_profile_id: str) -> int` to `ReferenceDocumentRevisionRepository
    ` Protocol (`reference_protocols.py:76-84`) and its implementation (`
   reference_repositories.py:158-178`).
3. Add `count_for_target(self, target_kind: ReferenceBindingTarget,
   target_id: str) -> int`
   to `ReferenceBindingRepository` Protocol (`reference_protocols.py:113-122`)
   and its implementation (`reference_repositories.py:236-261`).
4. Update the service-layer wrappers to return `(items, total)` tuples
   via new functions (`list_reference_documents_paged`,
   `list_reference_document_revisions_paged`, `list_reference_bindings_paged`)
   under `episodic/canonical/reference_documents/`. Keep existing list
   functions in place until callers migrate; they will be removed in a later
   cleanup commit.
5. Update the resources at
   `episodic/api/resources/reference_documents.py:105-136,241-274` and
   `episodic/api/resources/reference_bindings.py:70-94` to call the new
   `*_paged` services and include `total` in the response envelope.

Go/no-go: focused green run of every test touching reference documents and
bindings. Commit. CodeRabbit on diff.

### Milestone 3: pagination retrofit for unpaginated list endpoints

Goal: `/v1/series-profiles`, `/v1/episode-templates`, and
`/v1/series-profiles/{id}/resolved-bindings` accept `limit`/`offset` and return
the full envelope.

Test-first changes:

1. Add round-trip tests in `tests/test_profile_template_api.py` and
   `tests/test_binding_resolution_api.py` for paginated retrieval of series
   profiles, episode templates, and resolved bindings, including `limit=0` and
   `offset=-1` 400 cases.
2. Update `tests/steps/test_profile_template_api_steps.py` and
   `tests/steps/test_binding_resolution_steps.py` so listing scenarios pass
   `?limit=20&offset=0` and assert `total` in the envelope.

Production changes:

1. Add `count(self) -> int` to `_SeriesProfileRepository` Protocol at
   `episodic/canonical/profile_templates/types.py:273` and its implementation at
    `episodic/canonical/storage/repositories.py:111-118`.
2. Add `count(self, series_profile_id: uuid.UUID | None) -> int` to
   `_EpisodeTemplateRepository` Protocol at
   `episodic/canonical/profile_templates/types.py:281-284` and its
   implementation at `episodic/canonical/storage/repositories.py:306-319`.
3. Add new service-layer functions
   `list_entities_with_revisions_paged(uow, *, kind, limit, offset)` and the
   corresponding `count_entities(uow, *, kind, **filters)` under
   `episodic/canonical/profile_templates/services/_generic.py` that compose the
   new repository methods.
4. Update `SeriesProfilesResource.on_get`
   (`episodic/api/resources/series_profiles.py:65-86`) and
   `EpisodeTemplatesResource.on_get` (
   `episodic/api/resources/episode_templates.py:59-94`) to use
   `parse_pagination`, call the new `*_paged` services, and return the full
   envelope.
5. Update `ResolvedBindingsResource.on_get`
   (`episodic/api/resources/resolved_bindings.py:22-76`) to call
   `parse_pagination`, slice the resolved list, compute `total` as the slice
   length plus the remaining size, and return the envelope.

Go/no-go: focused green run of every profile-template, episode-template, and
binding-resolution test module. Commit. CodeRabbit on diff.

### Milestone 4: history endpoint pagination retrofit

Goal: `/v1/series-profiles/{id}/history` and
`/v1/episode-templates/{id}/history` accept `limit`/`offset` and return the
full envelope.

Test-first changes:

1. Extend `_verify_entity_history` at
   `tests/test_profile_template_api.py:121` to assert envelope keys, send
   pagination parameters, and validate `total`.
2. Add 400 cases for invalid pagination on both history endpoints.

Production changes:

1. Add these methods to `_SeriesProfileHistoryRepository`
   (`episodic/canonical/profile_templates/types.py:296-300`); analogue for

   ```python
   def list_for_profile_paged(
       self,
       profile_id: uuid.UUID,
       *,
       limit: int,
       offset: int,
   ) -> list[SeriesProfileHistoryEntry]: ...
   def count_for_profile(self, profile_id: uuid.UUID) -> int: ...
   ```

   episode templates.
2. Implement both in
   `episodic/canonical/storage/history_repositories.py:146-201`.
3. Add a new `list_history_paged` service in
   `episodic/canonical/profile_templates/services/_generic.py`.
4. Extend `handle_get_history` at
   `episodic/api/handlers.py:87-133` so the existing helper supports an optional
    `limit`/`offset` pair; or introduce a parallel `handle_get_history_paged`
   helper used by the two history resources. The shared base
   `_GetHistoryResourceBase` at `episodic/api/resources/base.py:104-147` must
   learn to surface pagination at the on_get layer.

Go/no-go: focused green run of every history test plus the route versioning
suite. Commit. CodeRabbit on diff.

### Milestone 5: filter parameter consistency pass

Goal: every list endpoint that exposes a filter parses, validates, and applies
it through the same idiom.

Production changes:

1. Add `parse_optional_uuid_param(req, name)` and
   `parse_enum_param(req, name, enum_type)` helpers in
   `episodic/api/helpers.py` next to `parse_pagination`. Both raise
   `HTTPBadRequest` with the documented envelope on validation failure.
2. Audit every list endpoint:
   - `SeriesProfilesResource.on_get`: confirm spec does not mandate a
     filter beyond what already exists; if no documented filter exists,
     record the decision in the Decision Log and skip;
   - `EpisodeTemplatesResource.on_get`: ensure `series_profile_id` is
     parsed via the new helper;
   - `ReferenceDocumentsResource.on_get`: ensure `kind` is parsed via
     the new enum helper;
   - `ReferenceBindingsResource.on_get`: ensure `target_kind` enum
     validation aligns with the new helper (currently passed straight
     through to the service);
   - `SeriesProfileBriefResource.on_get`: confirm `template_id` and
     `episode_id` parameters already use `parse_uuid`;
   - `ResolvedBindingsResource.on_get`: confirm same.

Tests verify that each filter parameter produces a documented `400` on invalid
input and the expected `200` envelope on valid input.

Go/no-go: focused green run of the full `/v1` test surface. Commit. CodeRabbit
on diff.

### Milestone 6: authorization scaffold

Goal: every `/v1` request flows through an `AuthorizationPort` decision,
defaulting to permit-all.

Test-first changes:

1. Add `tests/test_api_authorization.py` that:
   - confirms the default permit-all adapter does not change any existing
     response when no `Authorization` header is sent;
   - confirms that injecting a `DenyAll` adapter through
     `ApiDependencies.authorization` returns `401` with body `{"code":
     "unauthorized", "message": "…", "details": {}}` on any `/v1`
     endpoint;
   - confirms that a scope-aware adapter returning a `403` decision for
     a specific route returns `{"code": "forbidden", ...}`.
2. Extend `tests/fixtures/api.py` to expose an optional
   `authorization` parameter on `canonical_api_dependencies` so the new suite
   can swap adapters without changing other tests.

Production changes:

1. Add `episodic/api/authorization.py` defining:
   - `AuthorizationDecision` (an enum: `permit`, `unauthorized`,
     `forbidden`);
   - `AuthorizationContext(method: str, path_template: str,
     authorization_header: str | None)`;
   - `AuthorizationPort` Protocol with one method
     `decide(self, context: AuthorizationContext) -> AuthorizationDecision`;
   - `PermitAll` default adapter that always returns `permit`;
   - `AuthorizationMiddleware` (Falcon ASGI middleware) that runs in
     `process_request`, builds the context, calls the port, and on a
     non-permit decision sets `resp.media`, `resp.status`, and
     `resp.complete = True` to short-circuit.
2. Extend `ApiDependencies` at `episodic/api/dependencies.py:70-92` with
   an `authorization: AuthorizationPort = PermitAll()` field; validate at
   `__post_init__` that the value implements the Protocol.
3. Update `episodic/api/app.py` to:
   - install `AuthorizationMiddleware(dependencies.authorization)`
     before route registration;
   - keep `/health/live` and `/health/ready` exempt by either route-list
     check inside the middleware or by registering them on a separate
     sub-app — pick the simpler option once exploration confirms Falcon
     ASGI middleware ordering with the existing
     `_ShutdownHooksMiddleware`.
4. Document the scaffold and the path to full RBAC in
   `docs/developers-guide.md` §"Authorization scaffold" with a forward
   reference to roadmap item `5.1`.

Go/no-go: focused green run of `tests/test_api_authorization.py` plus the full
`/v1` surface. Commit. CodeRabbit on diff.

### Milestone 7: documentation alignment

Goal: every user-facing and developer-facing doc reflects the new envelopes,
pagination, filter, and authorization scaffold.

Concrete changes:

1. `docs/users-guide.md`: update or add a "REST API reference" section
   showing one canonical example of the paginated envelope, one error envelope,
   and one filter use; mark the authorization scaffold as permit-all today but
   planned to enforce under roadmap `5.1`.
2. `docs/developers-guide.md`: add or expand sections "REST error
   contract", "REST pagination contract", and "Authorization scaffold"
   alongside the existing "Versioned API routing" section (introduced by
   ExecPlan `4.1.1`). Document the helpers `parse_pagination`,
   `parse_optional_uuid_param`, `parse_enum_param`, and the classification
   mappers.
3. `docs/episodic-podcast-generation-system-design.md`: update the
   "Reusable reference REST API specification" pagination and error contract
   subsection (lines 1861-1875) to require the `total` field and the
   `{code, message, details}` envelope; add an explicit forward-reference to
   ADR 009 and `docs/episodic-tui-api-design.md` for tokens, idempotency, and
   RBAC. No other behavioural change.
4. `docs/episodic-tui-api-design.md`: no changes — the document already
   defines the target contracts. Add a footnote referencing this ExecPlan as
   the implementation receipt only if the design doc has a "Linked execution
   plans" or equivalent section.
5. ADR: do not author a new ADR. The decisions are tactical
   API-shape choices governed by `docs/episodic-tui-api-design.md` and
   already-accepted architecture decisions; the Decision Log in this ExecPlan
   is the durable record.

Go/no-go: `make fmt`, `make markdownlint`, `make nixie` pass on every edited
document.

### Milestone 8: full gates, CodeRabbit, and roadmap close

Run the following commands sequentially. Use `tee` against
`/tmp/4-1-2-<step>-episodic-$(git branch --show-current).out` for each so
truncation does not hide failures. The sequence:

```shell
set -o pipefail; make fmt 2>&1 | tee /tmp/4-1-2-fmt.out
set -o pipefail; mbake validate Makefile 2>&1 | tee /tmp/4-1-2-mbake.out
set -o pipefail; make check-fmt 2>&1 | tee /tmp/4-1-2-check-fmt.out
set -o pipefail; PATH=/root/.bun/bin:$PATH make markdownlint 2>&1 | tee /tmp/4-1-2-markdownlint.out
set -o pipefail; make nixie 2>&1 | tee /tmp/4-1-2-nixie.out
set -o pipefail; make build 2>&1 | tee /tmp/4-1-2-build.out
set -o pipefail; make lint 2>&1 | tee /tmp/4-1-2-lint.out
set -o pipefail; make typecheck 2>&1 | tee /tmp/4-1-2-typecheck.out
set -o pipefail; make test 2>&1 | tee /tmp/4-1-2-test.out
set -o pipefail; make check-migrations 2>&1 | tee /tmp/4-1-2-check-migrations.out
set -o pipefail; coderabbit doctor 2>&1 | tee /tmp/4-1-2-coderabbit-doctor.out
set -o pipefail; coderabbit review --agent 2>&1 | tee /tmp/4-1-2-coderabbit-review.out
```

After every gate passes and CodeRabbit reports zero unresolved actionable
findings, change `docs/roadmap.md`:

```markdown
- [ ] 4.1.2. Finalize REST surfaces for previous phase artefacts.
```

to:

```markdown
- [x] 4.1.2. Finalize REST surfaces for previous phase artefacts.
```

Commit. Push. Open the pull request via the `pr-creation` skill.

## Concrete steps

Each milestone above is reproducible from this paragraph forwards. To resume a
partially-completed implementation:

```shell
git branch --show-current
git status --short --branch
```

If the current branch is `main`, create a feature branch named after the task
content (for example, `feat/4-1-2-finalize-rest-surfaces`).

Recommended logging template (one file per gate per milestone):

```shell
set -o pipefail; <command> 2>&1 | \
  tee /tmp/4-1-2-<milestone>-<step>-episodic-$(git branch --show-current).out
```

Focused red-then-green pattern for each milestone:

```shell
set -o pipefail; uv run pytest -q <focused test paths> 2>&1 | \
  tee /tmp/4-1-2-<milestone>-red.out
# Confirm failures
# Implement
set -o pipefail; uv run pytest -q <focused test paths> 2>&1 | \
  tee /tmp/4-1-2-<milestone>-green.out
```

After every milestone's green run:

```shell
set -o pipefail; coderabbit review --agent 2>&1 | \
  tee /tmp/4-1-2-<milestone>-coderabbit.out
```

Address every actionable finding before the next milestone. If a finding
conflicts with this plan, record the conflict in `Decision log` and ask for
direction.

## Validation and acceptance

Acceptance criteria are complete only when every item below is true:

- Every `/v1` 4xx and 5xx response body matches the JSON envelope
  `{"code", "message", "details"}`.
- Every `/v1` list endpoint returns the JSON envelope
  `{"items", "limit", "offset", "total"}` and validates pagination bounds with
  `400 validation_error`.
- Every documented filter (per
  `docs/episodic-podcast-generation-system-design.md` §"Reusable reference REST
  API specification" and the existing canonical endpoint behaviour) is parsed
  and validated through a shared helper.
- `ApiDependencies.authorization` exposes the authorization seam; the
  default permit-all adapter preserves every existing response; a deny-all
  adapter produces `401 unauthorized` with the envelope.
- `docs/users-guide.md`, `docs/developers-guide.md`, and
  `docs/episodic-podcast-generation-system-design.md` are updated to match.
- `docs/roadmap.md` item `4.1.2` is marked `[x]`.
- All gates pass: `mbake validate Makefile`, `make check-fmt`,
  `make markdownlint`, `make nixie`, `make build`, `make lint` (including
  `make check-architecture`), `make typecheck`, `make test`,
  `make check-migrations`.
- `coderabbit review --agent` reports no unresolved actionable concerns.

## Idempotence and recovery

Every milestone is restartable. Tests can rerun against an empty py-pglite
database. The only one-way changes in this plan are the additive `count_*`
Protocol methods and the new modules `episodic/api/errors.py` and
`episodic/api/authorization.py`; both can be reverted independently with a
`git revert` of the milestone commit if a critical regression appears.

The Falcon error handler registration in `episodic/api/app.py` is isolated to a
single `add_error_handler` call; if a downstream failure implicates it, comment
the registration out, rerun the affected test suite, and recommit when fixed.

If `make check-architecture` fails mid-milestone, treat the failure as top
priority. The check enforces the hexagonal constraint; the most likely cause is
an accidental import from `episodic.api` into `episodic.canonical`. Run
`uv run hecate check` directly to see the offending edge (the verbose output
includes the diagnostic identifier `ARCH001` and the source/target group names).

## Artifacts and notes

Evidence artefacts to retain:

- `/tmp/4-1-2-m1-red.out` and `/tmp/4-1-2-m1-green.out`
- `/tmp/4-1-2-m2-red.out` and `/tmp/4-1-2-m2-green.out`
- `/tmp/4-1-2-m3-red.out` and `/tmp/4-1-2-m3-green.out`
- `/tmp/4-1-2-m4-red.out` and `/tmp/4-1-2-m4-green.out`
- `/tmp/4-1-2-m5-red.out` and `/tmp/4-1-2-m5-green.out`
- `/tmp/4-1-2-m6-red.out` and `/tmp/4-1-2-m6-green.out`
- `/tmp/4-1-2-fmt.out`, `/tmp/4-1-2-mbake.out`,
  `/tmp/4-1-2-check-fmt.out`, `/tmp/4-1-2-markdownlint.out`,
  `/tmp/4-1-2-nixie.out`, `/tmp/4-1-2-build.out`, `/tmp/4-1-2-lint.out`,
  `/tmp/4-1-2-typecheck.out`, `/tmp/4-1-2-test.out`,
  `/tmp/4-1-2-check-migrations.out`, `/tmp/4-1-2-coderabbit-doctor.out`,
  `/tmp/4-1-2-coderabbit-review.out`.

Sample expected error envelope:

```json
{
  "code": "revision_conflict",
  "message": "Series profile revision conflict.",
  "details": {
    "entity_id": "018f0c2a-1234-7000-a000-000000000001",
    "expected_revision": 4
  }
}
```

Sample expected pagination envelope:

```json
{
  "items": [
    {"id": "018f...", "slug": "ep-001", "title": "...", "revision": 3, "...": "..."}
  ],
  "limit": 20,
  "offset": 0,
  "total": 142
}
```

## Interfaces and dependencies

Planned new modules under `episodic/api/`:

- `episodic/api/errors.py`:
  - `ErrorEnvelope` (frozen dataclass).
  - `handle_http_error(req, resp, exc, params)` (Falcon error handler).
  - `map_profile_template_error(exc)` (re-raises with envelope details).
  - `map_reference_error(exc, *, context)` (relocated and enriched).
- `episodic/api/authorization.py`:
  - `AuthorizationDecision` (enum).
  - `AuthorizationContext` (frozen dataclass).
  - `AuthorizationPort` (`@runtime_checkable` Protocol).
  - `PermitAll` (default adapter).
  - `AuthorizationMiddleware` (Falcon ASGI middleware).

Planned additions under `episodic/canonical/profile_templates/`:

- New `count` methods on `_SeriesProfileRepository` and
  `_EpisodeTemplateRepository` Protocols (`types.py:273-284`), and new
  `count_for_profile` and `count_for_template` on the history Protocols (
  `types.py:296-318`).
- New `list_entities_with_revisions_paged`, `count_entities`,
  `list_history_paged`, and `count_history` services (`services/_generic.py`).

Planned additions under `episodic/canonical/reference_documents/`:

- New `list_reference_documents_paged`,
  `list_reference_document_revisions_paged`, and
  `list_reference_bindings_paged` services.

Planned additions under `episodic/canonical/reference_protocols.py`:

- `count_for_series`, `count_for_document`, `count_for_target` Protocol
  methods.

Planned additions under `episodic/canonical/storage/reference_repositories.py`
and `episodic/canonical/storage/repositories.py` and
`episodic/canonical/storage/history_repositories.py`:

- SQLAlchemy `select(func.count())` implementations for every new
  Protocol method above.

Planned additions under `episodic/api/dependencies.py`:

- `authorization: AuthorizationPort = PermitAll()` field on
  `ApiDependencies`, with `__post_init__` validation that the value implements
  the Protocol.

No new runtime dependencies. No new test dependencies. No new documentation
tooling.

## Revision note

- 2026-05-23: Initial draft created. Three Wyvern research subagents
  contributed the API surface inventory, test coverage map, and
  architecture-rails report. External prior art for Falcon error handlers, RFC
  9457 Problem Details, and Falcon ASGI middleware was resolved via WebFetch.
  Plan awaits user approval before implementation begins.
- 2026-05-25: Rebased onto `origin/main` after commit `3403ace`
  ("Adopt Hecate for architecture checks (#107)") removed the repo-local
  `episodic/architecture/` module. Updated every reference to
  `episodic/architecture/policy.py:<line>` to point at the new `[tool.hecate]`
  configuration in `pyproject.toml:437-496`, replaced
  `python -m episodic.architecture` recovery guidance with
  `uv run hecate check`, and confirmed the policy semantics (group prefixes,
  allowed imports) are byte-equivalent — only the implementation moved from
  Python module to Hecate TOML configuration. No work-plan change was required.
