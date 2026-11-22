# Add `PricingCataloguePort` pricing-source discovery (2.5.2)

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & discoveries`, `Decision log`,
`Outcomes & retrospective`, `Conformance basis`, and `Verification plan` must
be kept up to date as work proceeds.

Status: DRAFT (awaiting design review)

Branch: `2-5-2-pricing-catalogue-port-for-pricing-source-discovery`

Roadmap item: `2.5.2` in `docs/roadmap.md`.

## Purpose / big picture

Roadmap item `2.5.2` asks Episodic to "add `PricingCataloguePort` for
pricing-source discovery":

1. load pinned provider rate cards for internal LangGraph billing;
2. support future OpenAPI `info.x-sla` discovery and SLA4OAI plan ingestion
   for standalone evaluator services; and
3. persist pricing snapshots for historical reference.

Some terms first. A *pricing snapshot* (`PricingSnapshot` in
`episodic/cost/pricing_snapshot.py`) is an immutable value that says what one
*priced subject* costs: the service kind, provider, model, and operation, plus
exact fractional rates per usage metric. Its identity is a SHA-256 *content
hash* over a canonical JSON form, so a stored row can never silently change
meaning. A *rate card* is a YAML file under `config/pricing-snapshots/` that
describes one snapshot. A *catalogue* answers "which snapshot prices this
subject at this instant?". *OpenAPI* is the standard machine-readable
description of an HTTP API; its `info` object may carry vendor extensions
whose names start with `x-`. *SLA4OAI* (Service Level Agreements for OpenAPI)
is a sister specification: an OpenAPI document points at an SLA4OAI document
with `info.x-sla`, and the SLA4OAI *plans* document describes named service
plans, each with optional pricing, quotas (usage allowances, optionally with an
*overage* price for usage beyond the allowance), and rate limits. An *evaluator
service* is a quality-assurance evaluator (for example Pedante) deployed as a
standalone HTTP service rather than as an in-process LangGraph node.
*Discovery* is the act of finding and fetching a pricing source's current
documents and turning them into snapshots.

Today the port already exists, but only half of the roadmap item is true.
`PricingCataloguePort.resolve(subject, *, at=None)` (in
`episodic/cost/ports.py`) is implemented by `FilePricingCatalogue`
(`episodic/cost/pricing_catalogue/file_loader.py`), which loads every rate
card at construction and picks the card with the greatest `effective_from`
that is not after the requested instant. `CostRecorder`
(`episodic/cost/recorder.py`) persists the chosen snapshot through
`PricingSnapshotRepository.ensure` before it pins a run or records a call. What
is missing:

- There is no notion of more than one pricing source. The catalogue *is* the
  directory of cards, so an evaluator service's published prices cannot be
  added without replacing it.
- Nothing fetches or parses OpenAPI or SLA4OAI documents. The
  `sla4oai_plan` source kind exists, but an "SLA4OAI card" today is a
  hand-written Episodic rate card whose own YAML text is stored as the source
  document; no real SLA4OAI document is ever read.
- Snapshots are persisted only when a call is priced. A discovered remote
  document that was never used is lost, and because `retrieved_at` is part of
  the content hash, naively re-fetching an unchanged remote document would mint
  a new snapshot row on every fetch.
- `PricingSnapshotRepository` cannot list the stored revisions of a subject,
  so there is no way to recognize "this remote document is unchanged since we
  first saw it" or to fall back to the last known price when an evaluator is
  unreachable. ADR-028 deferred `list_revisions` and a subject lookup index to
  this item.

After this change an operator can observe the following. With no new
configuration, Episodic behaves exactly as before: the same rate cards price
the same calls, and a malformed card still stops the process at start-up. In
addition, on the first pricing resolution of each process the catalogue
persists every loaded rate card, so the database holds every card the
deployment has ever shipped even if no call used it. When the operator lists a
standalone evaluator in a new *evaluator pricing binding* file, for example:

```yaml
schema_version: 1
evaluators:
  - name: pedante-service
    openapi_uri: https://pedante.internal.example/openapi.json
    plan: pro
    allowed_origins:
      - https://pedante.internal.example
    subject:
      provider_name: pedante-service
      model: default
      operation: evaluate
    sla_operation:
      path: /evaluations
      method: post
```

the catalogue fetches `openapi.json`, follows `info.x-sla` (relative URIs are
resolved against the URI the OpenAPI document was actually retrieved from),
fetches the SLA4OAI plans document, extracts plan `pro`, and resolves
`helper_service/pedante-service/default/evaluate` to a snapshot whose
`source_kind` is `sla4oai_plan` and whose source document is the plans
document byte for byte. That snapshot is persisted at discovery time. If the
document has not changed since a previous discovery, the previously stored
snapshot is reused with its original timestamps, so no duplicate row appears.
If the evaluator is unreachable, the catalogue keeps pricing from the last
persisted revision and emits a warning; if it has never been seen, resolution
fails with `LookupError` exactly as a missing rate card does today.

This item closes two outstanding decisions recorded in
`docs/adrs/adr-0028-content-addressed-pricing-snapshots.md`: whether
`plan_name` and snapshot listing belong on the catalogue port (decided: plan
name is provenance in `source_metadata`; listing belongs on the snapshot
repository, not on `PricingCataloguePort`) and whether the one-type
`PricingSnapshot` survives SLA4OAI normalization (decided: yes, schema version
1 is unchanged; see `Decision log` D3 and D4).

## Constraints

- `PricingSnapshot` schema version 1, its canonical form, and every pinned
  content-hash vector in `tests/__snapshots__/test_cost_pricing_snapshot_hash.ambr`
  must not change. The persisted format of `pricing_snapshots` rows must not
  change; the only schema change authorized is an additive, non-unique index
  (see EP-M2).
- `PricingCataloguePort.resolve(subject, *, at=None) -> PricingSnapshot` keeps
  its signature and its contract: effective-dated selection, `LookupError` for
  an unpriced subject. `CostRecorder` and every caller keep working without
  change.
- With no evaluator binding configured, observable pricing behaviour must be
  identical to the comparison base: the same snapshot for every subject and
  instant, the same start-up failure for a malformed card.
- The domain must stay pure (hexagonal dependency rule). Modules registered in
  the Hecate `domain_ports` group may import only `domain_ports` and
  `logging_port` modules: no `httpx`, `yaml`, `sqlalchemy`, or file I/O. YAML
  and JSON decoding and all network I/O live in outbound adapters under
  `episodic.cost.pricing_catalogue` (already in the `outbound_adapter` group).
  Application services that orchestrate ports live in a module registered in
  the `application` group.
- No new code file may exceed 400 lines (`AGENTS.md`). `recorder.py` and
  `pricing_catalogue/_document.py` are at 389 lines; do not grow them.
- The PricingEngine's floor-per-metric rounding and its handling of rates are
  owned by `2.5.3`. This plan must not change `episodic/cost/engine.py`.
- Quota and overage accounting, flat subscription fees, and per-period
  settlement are owned by `2.5.3` and later items. This plan must not price
  any usage it cannot price exactly with the existing engine; it must fail
  closed instead (see D4).
- Network access is opt-in. No outbound HTTP request may be made unless an
  evaluator binding names the URI, and only to origins the binding allows.
- The new runtime YAML dependency is authorized: `pyyaml` moves from the `dev`
  dependency group to `[project].dependencies`, because production code already
  imports `yaml` and today only receives it transitively through
  `langchain-core`. No other new runtime or development dependency is
  authorized.
- Stored snapshot identifiers keep the existing store's `uuid.uuid7`
  factory; do not introduce a new identifier scheme.
- Historical documents must stay untouched: the `2.4.4` and `2.5.1` ExecPlans,
  and the bodies of ADR-015 and ADR-028 except for amendment banners and
  `## Amendments` sections permitted by `docs/documentation-style-guide.md`.
- Implementation begins only after the user approves this plan.

If satisfying the objective requires violating a constraint, do not proceed.
Document the conflict in `Decision log` and escalate.

## Tolerances (exception triggers)

The comparison base is `origin/main` at the commit this branch forks from
(`d0bdabe3`). Count with:

```bash
git diff --numstat d0bdabe3...HEAD -- . ':(exclude)docs/execplans/*'
```

Classify whole files by purpose: `*.py` and `*.feature` files, including tests,
test fixtures written in Python, and Alembic revisions, are code; `*.md` files
are documentation; everything else (`pyproject.toml`, `uv.lock`,
`ambrleaks.toml`, `typos.local.toml`, YAML under `config/`, `charts/`,
`.github/`, and test fixture YAML or `.ambr` snapshot files) is configuration,
except that generated `typos.toml` is excluded. All limits are net lines
(additions minus deletions). ExecPlan files are excluded from every count,
including this file.

Historical evidence: the `2.5.1` ExecPlan stated a per-milestone limit of 45
files and 2,500 net lines. The delivered squash commit `d0bdabe3` changed 96
non-ExecPlan files: 75 code files for 7,789 net lines, 10 documentation files
for 777 net lines, and 10 configuration files for 166 net lines. No escalation
or budget revision is recorded in that plan, and whether the limit was meant
per milestone or cumulatively is not stated. The lesson taken here is that
pricing work in this repository is test-heavy (roughly 60 percent of the code
lines were tests) and that cumulative budgets must be stated explicitly.

The estimate for this item, traced from the modules in `Plan of work`: about
2,000 net lines of production code (two domain modules of about 300 lines,
two extracted helpers of about 120 lines, two port and value modules of about
250 lines, two application services of about 500 lines, the HTTP fetcher and
binding loader of about 450 lines, store and telemetry extensions of about
150 lines, a migration of about 60 lines, runtime wiring of about 100 lines)
and about 3,000 net lines of tests. That is 5,000 lines; the budget adds 15
percent contingency.

- Files: if the cumulative change touches more than 60 non-ExecPlan files,
  stop and escalate with a proposed split.
- Code: if code exceeds 5,750 net lines cumulatively, or any single milestone
  exceeds 2,000 net lines, stop and escalate.
- Configuration: if configuration exceeds 300 net lines, stop and escalate.
- Documentation: if documentation exceeds 900 net lines, stop and escalate.
- Interface: if any REST, Celery task, or LangGraph checkpoint payload shape
  must change, or `PricingCataloguePort.resolve` must change, stop and
  escalate. Internal Python signatures inside `episodic.cost` and its direct
  composition roots may change.
- Persisted format: if any change to the `pricing_snapshots` columns,
  constraints, or the canonical form appears necessary, stop and escalate.
- Dependencies: if any dependency beyond moving `pyyaml` into runtime
  dependencies appears necessary (for example an OpenAPI parser, `respx`, or
  `pytest-httpserver`), stop and escalate.
- Architecture: if Hecate needs a new group or a new allowed edge between
  groups, stop and escalate. Adding module prefixes to existing groups is
  expected and authorized.
- Rounding and pricing: if any test can pass only by changing
  `episodic/cost/engine.py`, stop and escalate; that is `2.5.3` work.
- Iterations: if a gate still fails after three focused fix attempts, stop and
  record the evidence in `Surprises & discoveries`.
- Time: if a milestone exceeds one working day of agent time, record progress
  and escalate.
- Ambiguity: if an SLA4OAI document in the wild needs a feature this plan
  rejects (globbed paths, `custom` pricing, a currency outside the minor-unit
  table) to be priced, stop and present options; do not widen the parser
  silently.

## Risks

- Risk: SLA4OAI has two incompatible dialects in circulation. The research
  specification (version 0.10.0, 2023) uses `x-sla: <uri>`, a `context.version`
  field, object periods `{amount, unit}`, and global defaults that plans
  override. The 1.0.0 draft (2020, on GitHub) uses a root version key whose
  name disagrees between its prose (`sla:`) and its JSON Schema (`sla4oas:`),
  string periods (`second`), a `base` plan that other plans inherit, and
  `x-sla: {$ref: <uri>}` in examples. Severity: high. Likelihood: high.
  Mitigation: accept exactly these documented shapes, detect the dialect
  explicitly, record it in `source_metadata["sla_dialect"]`, and reject
  anything ambiguous (for example both `sla` and `sla4oas` root keys) with an
  error that names the JSON path. Test both dialects with fixtures copied from
  the specifications.
- Risk: PyYAML's `SafeLoader` constructs `0.0001` as a binary float, losing
  exactness before the price reaches `MeteredRate`. Severity: high.
  Likelihood: certain if unmitigated. Mitigation: the adapter decodes with a
  loader subclass that constructs floats as `decimal.Decimal` from the scalar
  text; JSON documents go through the same loader. A property test asserts
  that any decimal string round-trips exactly into the rate fraction.
- Risk: following `info.x-sla` and HTTP redirects is a server-side request
  forgery vector: a compromised or misconfigured evaluator could point the
  worker at an internal metadata endpoint. Severity: high. Likelihood: low.
  Mitigation: every fetched URI and every redirect hop must match an origin
  the binding lists; only `https` is accepted unless the binding lists an
  `http` origin explicitly; responses are capped at the 262,144-byte
  source-document limit while streaming; at most three redirects; no
  credentials or cookies are sent.
- Risk: discovered snapshots hash `retrieved_at`, so naive re-discovery mints a
  new row per fetch and unbounded table growth. Severity: medium. Likelihood:
  certain if unmitigated. Mitigation: first-seen deduplication through
  `PricingSnapshotRepository.list_revisions` and the pure
  `has_same_pricing_content` predicate (D5), backed by a subject index.
- Risk: pricing an SLA4OAI plan with the current engine would charge every
  request at the overage price even inside an included quota, overstating cost.
  Severity: high. Likelihood: high for any realistic plan. Mitigation: D4 maps
  only metrics whose price is exactly a per-unit charge from the first unit;
  every quota-bearing metric is deliberately absent from `rates`, so the
  existing engine raises `UnknownPricedMetricError` instead of mispricing.
- Risk: Vidai Mock 0.3.1 cannot serve the OpenAPI or SLA4OAI documents. A probe
  during planning showed custom providers answer `405 Method Not Allowed`
  (`allow: POST`) to `GET`, with or without `method` or `methods` keys.
  Severity: medium. Likelihood: certain. Mitigation: serve pricing documents
  from a loopback `http.server.ThreadingHTTPServer` fixture (standard library,
  no new dependency) and keep Vidai Mock for the evaluator's inference call in
  the behavioural scenario (D9).
- Risk: lazy discovery on the first `resolve` adds network latency to the
  first priced call of a process, and concurrent first calls could stampede.
  Severity: low. Likelihood: medium. Mitigation: a single-flight
  `asyncio.Lock` around refresh, a per-request timeout (default 10 seconds),
  and a refresh interval (default 3,600 seconds) after which a refresh is
  attempted but failures keep the previous view.
- Risk: the discovery application service needs a unit of work to persist
  snapshots, which couples the catalogue to storage lifetimes. Severity:
  medium. Likelihood: medium. Mitigation: depend on a narrow
  `PricingSnapshotHistoryFactory` callable (an async context manager yielding
  a `PricingSnapshotRepository` and committing on success), built in the
  composition root from the existing `UowFactory`.
- Risk: duplication gates flag the extracted effective-date selection or the
  two YAML loaders. Severity: low. Likelihood: medium. Mitigation: extract
  shared logic first (EP-M1) so `FilePricingCatalogue` and the new catalogue
  call one function; add a reasoned allow-list entry only for intentional
  parallel structure.

## Progress

- [x] (2026-11-22 20:30Z) Branch renamed, Lody session titled, skills loaded
  (`execplans`, `hexagonal-architecture`, `python-router`, `codegraph-mcp`,
  `firecrawl-mcp`, `vidai-mock`, `logisphere-design-review`). CodeGraph MCP
  failed to connect; reconnaissance used direct reads.
- [x] (2026-11-22 20:40Z) Wyvern reconnaissance of code, documentation, and
  test infrastructure completed.
- [x] (2026-11-22 20:45Z) Firecrawl research of the SLA4OAI 0.10.0 research
  specification, the 1.0.0 draft, RFC 3986 base-URI rules, and recent prior
  art (APIs.io publishing SLA4OAI documents) completed.
- [x] (2026-11-22 20:50Z) Vidai Mock 0.3.1 probe: `GET` routes unsupported.
- [x] (2026-11-22 21:30Z) Initial draft written.
- [ ] Design review by an expert panel applied.
- [ ] Plan approved by the user.
- [ ] `EP-M1` Pure SLA4OAI ingestion and shared selection helpers.
- [ ] `EP-M2` Discovery ports, snapshot revision listing, and subject index.
- [ ] `EP-M3` Discovering catalogue and SLA4OAI pricing source.
- [ ] `EP-M4` HTTP fetcher, binding loader, and runtime wiring.
- [ ] `EP-M5` Behavioural scenarios, documentation, ADR, and roadmap closure.

## Surprises & discoveries

- Observation: `PricingCataloguePort` already exists; the roadmap wording
  "add `PricingCataloguePort`" predates `2.4.4`.
  Evidence: `episodic/cost/ports.py` defines it; `docs/adrs/adr-0015-*.md`
  introduced it. Impact: this item extends the port's backing rather than
  adding the Protocol; the Protocol signature is preserved (Constraints).
- Observation: Vidai Mock 0.3.1 custom providers reject `GET`.
  Evidence: a provider with `matcher: "^/openapi\\.yaml$"` and
  `response_body` returned `405 Method Not Allowed`, `allow: POST`, both with
  no method key and with `method: "GET"` or `methods: ["GET"]`, under
  `--isolated`. Impact: D9.
- Observation: `pyyaml` is declared only in the `dev` dependency group, yet
  `episodic/cost/pricing_catalogue/_document.py` imports `yaml` in production.
  Evidence: `pyproject.toml` `[dependency-groups].dev`; `uv.lock` shows
  `langchain-core` as the only runtime dependent of `pyyaml`. Impact: this
  plan declares it directly (Constraints).
- Observation: the SLA4OAI specification text and its JSON Schema disagree on
  the 1.0.0 root key (`sla` versus `sla4oas`), and the research specification's
  own example uses `currency: "euro"`, which is not an ISO 4217 code.
  Evidence: SLA4OAI research specification §5.2.5; API Evangelist, "Service
  Level Agreements Come Back Around As SLA4OAI", 3 November 2026. Impact:
  accept both root keys (but not both at once) and reject non-ISO currencies.
- Observation: LangGraph billing reaches the catalogue only through an injected
  `CostRecorderPort`; the only production `CostRecorder` is built in
  `episodic/api/runtime.py::_build_generation_launcher`, and the graph builder
  and planning orchestrator default `cost_recorder` to `None`.
  Evidence: `episodic/orchestration/_graph_builder.py:57`,
  `_planning_orchestrator.py:60`. Impact: D8.

## Decision log

- D1. Decision: keep `PricingCataloguePort.resolve` unchanged and add pricing
  sources behind it. A new driven port, `PricingSourcePort`, has one method,
  `discover(*, at) -> PricingDiscovery`, returning the snapshots a source
  currently publishes. A new application service,
  `DiscoveringPricingCatalogue`, implements `PricingCataloguePort` over a tuple
  of sources. `FilePricingCatalogue` keeps implementing `PricingCataloguePort`
  and also implements `PricingSourcePort`.
  Rationale: the recorder is the port's only consumer and needs only
  resolution; putting listing or discovery on `PricingCataloguePort` would
  force every consumer to depend on operations it never calls (interface
  segregation). `FilePricingCatalogue` stays a complete catalogue for offline
  tooling and tests, and is not a compatibility shim: it is the rate-card
  source. Alternative rejected: replacing `FilePricingCatalogue` with a
  rate-card source class and rewriting every test that constructs it; that
  churns about a dozen test modules for no behavioural gain.
- D2. Decision: effective-date selection moves into a pure domain function,
  `select_effective_snapshot(snapshots, subject, at)`, in
  `episodic/cost/pricing_selection.py`, with `reject_ambiguous_snapshots`
  enforcing that no two snapshots share a subject and `effective_from`. Both
  catalogues call it.
  Rationale: one selection rule, one place to test it, and no duplication
  finding.
- D3. Decision: an ingested SLA4OAI plan becomes a schema-version-1
  `PricingSnapshot` with `service_kind=helper_service`,
  `source_kind=sla4oai_plan`, the subject taken from the binding, the plans
  document as the verbatim `source_document`, and provenance in
  `source_metadata`: `openapi_uri`, `sla_uri` (the final retrieval URI),
  `sla_plan`, `sla_dialect` (`research_0_10` or `draft_1_0`), and
  `sla_context_id`. The OpenAPI document itself is not stored; only its URI.
  Rationale: closes ADR-028's outstanding decision without a persisted-format
  change. The plan name is part of the hashed metadata, so two plans never
  share a snapshot. Alternative rejected: a schema-version-2 snapshot with
  quota fields; that changes the canonical form and every vector, and the
  quota semantics belong to `2.5.3`, which has not been designed.
- D4. Decision: only metrics priced exactly per unit from the first unit enter
  `rates`. For the binding's operation, a quota limit whose metric has an
  overage price and whose `max` is absent or zero becomes
  `MeteredRate(cost_minor, overage_units)`. A metric with a positive `max`, a
  `custom: true` limit, or no overage price is a *deferred metric*: it is left
  out of `rates` and listed, sorted and comma-separated, in
  `source_metadata["sla_deferred_metrics"]`. A plan-level fee is recorded as
  `sla_plan_fee` (decimal string in major units) and `sla_billing` (the
  SLA4OAI billing period) and is never priced per call. `pricing.custom: true`
  is rejected. Rate limits (`rates` in SLA4OAI) are throughput limits, not
  prices, and are ignored for pricing.
  Rationale: the existing engine raises `UnknownPricedMetricError` for a
  metric absent from `rates`, so a quota-bearing metric fails closed instead
  of being charged at the overage price from the first request. `2.5.3` will
  read the deferred terms from the pinned source document through the typed
  parser this plan adds. Alternative rejected: pricing at the overage rate and
  documenting the overstatement; a budget alarm built on overstated costs is
  wrong in a way nobody notices.
- D5. Decision: discovered snapshots use first-seen deduplication. A
  discovered snapshot's `retrieved_at` and `effective_from` are both the fetch
  instant. Before persisting, the catalogue reads
  `PricingSnapshotRepository.list_revisions(subject)` and, if the latest
  stored revision has the same pricing content
  (`has_same_pricing_content`: every hashed field except `retrieved_at` and
  `effective_from` is equal), reuses that stored snapshot instead.
  Rationale: one row per distinct published document, stable pins across
  restarts, and an honest "first seen at" date. Alternative rejected: deriving
  timestamps from HTTP `Last-Modified`, which servers set inconsistently.
- D6. Decision: `PricingSnapshotRepository` gains
  `list_revisions(subject) -> tuple[PricingSnapshot, ...]`, ordered by
  `effective_from` (unset first), then `retrieved_at`, then `content_hash`,
  each verified against its stored content hash. A new Alembic revision adds a
  non-unique index `ix_pricing_snapshots_subject` on
  `(service_kind, provider_name, model, operation)`.
  Rationale: ADR-028 deferred exactly this listing and index to `2.5.2`; it
  serves deduplication and the outage fallback.
- D7. Decision: discovery is lazy and single-flight. `DiscoveringPricingCatalogue`
  refreshes on its first `resolve`, and again on a `resolve` after
  `refresh_interval` (default 3,600 seconds, setting
  `PRICING_DISCOVERY_REFRESH_SECONDS`). Each source keeps its last good view.
  A refresh persists every discovered snapshot (rate cards included) in one
  history transaction. A failing remote source falls back to its subjects'
  latest persisted revisions and logs a warning with the source name and
  failure category; a source that has never succeeded and has nothing
  persisted contributes nothing, so its subjects raise `LookupError`.
  Rationale: the API composition root is synchronous, so start-up discovery
  would need a new lifecycle hook; lazy refresh fits the existing `async`
  resolve path. Persisting rate cards on refresh delivers "persist pricing
  snapshots for historical reference" for cards that no call used.
  Alternative considered: an explicit operator refresh command; the CLI is an
  HTTP API client, so this would add a REST surface (out of tolerance).
- D8. Decision: a single composition helper,
  `build_pricing_catalogue(config, uow_factory, *, http_client)`, in a new
  module `episodic/api/pricing_runtime.py` (registered in the
  `composition_root` group), builds the catalogue every `CostRecorder`
  receives. Only the API runtime builds a recorder today; wiring a recorder
  into worker-built LangGraph graphs is out of scope.
  Rationale: "internal LangGraph billing" reaches the catalogue only through
  the recorder; one builder keeps any future composition root consistent.
- D9. Decision: behavioural and end-to-end tests serve OpenAPI and SLA4OAI
  documents from a loopback `ThreadingHTTPServer` fixture and use Vidai Mock
  for the evaluator's inference call; adapter unit tests use
  `httpx.MockTransport`, which the LLM adapter tests already use.
  Rationale: Vidai Mock 0.3.1 cannot answer `GET`; the standard-library server
  exercises the real socket, redirect, and header paths without a new
  dependency.
- D10. Decision: the minor-unit exponent comes from a small explicit table in
  `episodic/cost/pricing_amounts.py` (`USD`, `EUR`, `GBP`, each 2). Any other
  currency in an SLA4OAI document is rejected with an error naming it.
  Rationale: SLA4OAI prices are in major units, while snapshots are in minor
  units; a wrong exponent misprices by orders of magnitude. Widening the table
  is a reviewed one-line change.

## Outcomes & retrospective

Not started. Record per-milestone outcomes, the final size counts against the
tolerances, and lessons here.

## Context and orientation

Episodic is a Python 3.14 service that generates podcast scripts with
LangGraph workflows and accounts for what each Large Language Model (LLM) or
Text-to-Speech (TTS) call costs. Cost accounting lives in `episodic/cost/`.
The package follows hexagonal architecture: domain value objects and ports are
pure modules; application services orchestrate ports; outbound adapters talk
to PostgreSQL, files, or HTTP. The Hecate checker (`make check-architecture`,
configured under `[tool.hecate]` in `pyproject.toml`) enforces which module
groups may import which. Hecate assigns a module to the *first* group whose
prefix matches and does not check modules no group matches, so every new
module must be registered under a prefix explicitly.

The modules this plan touches, with their current sizes:

- `episodic/cost/ports.py` (301 lines): `PricingCataloguePort`,
  `CostLedgerPort`, `MeteringPort`, ledger value objects. Domain.
- `episodic/cost/pricing_snapshot.py` (262 lines): `PricingSnapshot` and its
  validators, including the private `_METRIC_UNITS` table that fixes the unit
  of known metrics. Domain.
- `episodic/cost/pricing_snapshot_values.py` (246 lines): `MeteredRate`,
  `SourceDocument` (at most 262,144 UTF-8 bytes), `PricingSubject`,
  `PricedService`, `UsageUnit`. Domain.
- `episodic/cost/pricing_snapshot_hash.py` (192 lines): canonical form and
  content hash. Domain. Not modified.
- `episodic/cost/pricing_snapshot_ports.py` (123 lines):
  `PricingSnapshotRepository` (`ensure`, `get`) and its errors. Domain.
- `episodic/cost/primitives.py` (54 lines): `PricingSourceKind`,
  `CostAccountingError`, identifiers, `validate_currency_code`. Domain.
- `episodic/cost/engine.py` (104 lines): `PricingEngine.price`. Domain. Not
  modified.
- `episodic/cost/recorder.py` (389 lines): `CostRecorder`. Application. Not
  modified.
- `episodic/cost/pricing_catalogue/file_loader.py` (178 lines),
  `_document.py` (389 lines), `_yaml_loader.py` (57 lines), `_errors.py`:
  the rate-card adapter. Outbound adapter.
- `episodic/cost/storage/pricing_snapshot_store.py` (281 lines) and
  `pricing_snapshot_telemetry.py` (195 lines): the SQLAlchemy repository and
  its instrumentation wrapper. Outbound adapter.
- `episodic/cost/storage/models.py` (217 lines): `PricingSnapshotRecord`.
- `episodic/api/runtime.py` and `episodic/api/runtime_config.py`: the API
  composition root and its settings (`PRICING_SNAPSHOT_DIRECTORY`).
- `episodic/canonical/storage/uow.py`: the unit of work exposing
  `uow.pricing_snapshots`.

The new modules this plan adds:

- `episodic/cost/pricing_amounts.py` (domain): decimal-string to exact
  fraction conversion, extracted from `_document.py`, plus the minor-unit
  exponent table and `major_amount_rate`.
- `episodic/cost/pricing_selection.py` (domain): `select_effective_snapshot`,
  `reject_ambiguous_snapshots`, `has_same_pricing_content`.
- `episodic/cost/sla4oai_document.py` (domain): typed SLA4OAI model and
  `parse_sla4oai_document`, plus `sla_reference_of` for OpenAPI documents.
- `episodic/cost/sla4oai_pricing.py` (domain): `effective_plan_terms` and
  `snapshot_from_plan`.
- `episodic/cost/pricing_discovery_ports.py` (domain): `PricingDocument`,
  `PricingDocumentFetcherPort`, `PricingSourcePort`, `PricingDiscovery`,
  `EvaluatorPricingBinding`, `PricingSnapshotHistoryFactory`, and the
  discovery errors.
- `episodic/cost/pricing_discovery.py` (application): `Sla4OaiPricingSource`.
- `episodic/cost/discovering_catalogue.py` (application):
  `DiscoveringPricingCatalogue`.
- `episodic/cost/pricing_catalogue/http_fetcher.py` (outbound adapter):
  `HttpPricingDocumentFetcher`.
- `episodic/cost/pricing_catalogue/_decoding.py` (outbound adapter): the
  exact-number YAML and JSON decoder.
- `episodic/cost/pricing_catalogue/evaluator_bindings.py` (outbound adapter):
  `load_evaluator_bindings(path)`.
- `episodic/api/pricing_runtime.py` (composition root):
  `build_pricing_catalogue`.
- `alembic/versions/<date>_000018_index_pricing_snapshot_subjects.py`.

Tests follow existing conventions. Unit tests are `tests/test_cost_*.py`.
Behavioural tests pair `tests/features/<name>.feature` with
`tests/steps/test_<name>_steps.py`, step definitions in a module registered as
a plugin in `tests/conftest.py`, and support modules under `tests/steps/`.
Syrupy snapshots live in `tests/__snapshots__/`. Hypothesis strategies for
snapshots live in `tests/pricing_snapshot_hash_strategies.py`; Hypothesis
settings are per test (`@settings(...)`, `deadline=None` for pricing tests),
with no global profile. Database tests use the `session_factory` fixture from
`tests/fixtures/database.py` (py-pglite). Vidai Mock is started by
`tests/steps/vidaimock_harness.py` with `--isolated`; CI pins version 0.3.1.
`ambrleaks` scans `tests/` for secrets, so any new fixture URL or digest may
need an `ambrleaks.toml` allow entry.

### Signposted documentation

- `docs/roadmap.md` §2.5 for the item text and its neighbours `2.5.3` to
  `2.5.5`.
- `docs/episodic-podcast-generation-system-design.md`: the ports list around
  lines 850-871 ("loads pinned provider rate cards ... can later discover
  evaluator OpenAPI and SLA4OAI documents"), the pricing catalogue narrative
  around lines 1545-1594 (`info.x-sla`, `GET /sla/plans.yaml`, "the fetched
  document is stored verbatim"), and the service-path note around lines
  393-396.
- `docs/adrs/adr-0015-cost-accounting-ports-and-pricing-engine.md` and its
  addenda; `docs/adrs/adr-0028-content-addressed-pricing-snapshots.md`
  (non-goals at lines 283-284 and outstanding decisions at 328-332 are closed
  here).
- `docs/execplans/2-5-1-immutable-pricing-snapshots.md` for the snapshot
  design history and its lessons (Hecate first-match, file-size pressure,
  rebases dropping allow-list entries).
- `docs/cost-management-in-langgraph-agentic-systems.md` for the cost model's
  motivation (it has no discovery content).
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` and
  `docs/agentic-systems-with-langgraph-and-celery.md` for port placement and
  why nodes depend only on ports.
- `docs/async-sqlalchemy-with-pg-and-falcon.md` and
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` for the store and its
  tests.
- `docs/testing-async-falcon-endpoints.md` (no endpoint changes; read for
  composition-root testing patterns).
- `docs/complexity-antipatterns-and-refactoring-strategies.md` before
  splitting the parser.
- `docs/femtologging-users-guide.md` for the discovery warning logs.
- `docs/tei-rapporteur-users-guide.md` is not relevant to this item.
- `docs/developers-guide.md` §"Cost accounting and pricing snapshots" and
  §Hecate module groups; `docs/users-guide.md` §"Pricing snapshots";
  `docs/documentation-style-guide.md` for ADR format; `docs/scripting-standards.md`
  only if a helper script is added (none is planned).

### Signposted skills

- `execplans` for maintaining this document.
- `hexagonal-architecture` for port placement and the dependency rule.
- `python-router`, then `python-types-and-apis` (Protocols, `NewType`),
  `python-data-shapes` (frozen dataclasses, tagged dialects),
  `python-errors-and-logging` (error hierarchy, `raise ... from ...`),
  `python-concurrency` (the single-flight lock), `python-testing`, and
  `hypothesis`.
- `vidai-mock` for the behavioural scenario's inference call.
- `skylos` and `python-quality-tools` when the dead-code or duplication gates
  report findings.
- `en-gb-oxendict-style` for documentation.
- `firecrawl-mcp` if a specification question arises during implementation.

## Conformance basis

Upstream artefacts, at the comparison base `d0bdabe3`:

- Roadmap `docs/roadmap.md` item `2.5.2`, bullets RM-1 (load pinned provider
  rate cards for internal LangGraph billing), RM-2 (support future OpenAPI
  `info.x-sla` discovery and SLA4OAI plan ingestion for standalone evaluator
  services), and RM-3 (persist pricing snapshots for historical reference).
- System design: DES-PORTS (`PricingCataloguePort` "loads pinned provider rate
  cards ... can later discover evaluator OpenAPI and SLA4OAI documents"),
  DES-SLA (the evaluator contract: `info.x-sla`, relative URIs permitted, plans
  document fetched and pinned "exactly as it pins provider rate cards today",
  "stored verbatim").
- ADR-015 (cost-accounting port family) and ADR-028 (content-addressed
  snapshots), in particular ADR028-NG-1 (SLA4OAI fetching and `info.x-sla`
  discovery deferred to `2.5.2`), ADR028-NG-2 (catalogue listing and selection
  deferred to `2.5.2`), ADR028-OD-1 (whether `plan_name` and listing belong on
  the port).
- Governing standards: `AGENTS.md`, `docs/documentation-style-guide.md`, the
  Hecate groups in `pyproject.toml`.
- No Terms of Reference or separate technical design document exists for this
  item beyond the system design.

Trace links:

```plaintext
RM-1 -> DES-PORTS -> D1, D2, D8 -> EP-M1, EP-M3, EP-M4 -> pricing_source_discovery.feature "Rate cards price exactly as before"
RM-2 -> DES-SLA, ADR028-NG-1 -> D3, D4, D9, D10 -> EP-M1, EP-M3, EP-M4 -> pricing_source_discovery.feature "An evaluator call is billed from its discovered plan"
RM-3 -> ADR028-NG-2 -> D5, D6, D7 -> EP-M2, EP-M3 -> pricing_source_discovery.feature "Rediscovering an unchanged plan reuses the stored snapshot"
ADR028-OD-1 -> D1, D3 -> ADR-0029 -> EP-M5
```

## Verification plan

### Axioms

- AX-1: PyYAML's `SafeLoader` resolves plain scalars by the YAML 1.1 implicit
  resolvers; subclass constructors registered for a tag replace the base
  constructor for that subclass only.
- AX-2: `urllib.parse.urljoin(base, reference)` implements RFC 3986 §5.2
  reference resolution for `http` and `https` URIs, including `./` and `../`
  segments.
- AX-3: `httpx.AsyncClient` with `follow_redirects=False` returns 3xx
  responses with their `Location` header unchanged, and `httpx.MockTransport`
  invokes its handler for every request the client sends.
- AX-4: PostgreSQL orders `NULLS FIRST` as written and a non-unique btree index
  does not change query results.
- AX-5: The SLA4OAI research specification 0.10.0 and the 1.0.0 draft, as
  retrieved on 2026-11-22, define the shapes listed in `Risks`. The fixtures
  copied from them are the contract; documents in the wild that differ are
  out of scope (Tolerances, Ambiguity).
- AX-6: `PricingSnapshot.__post_init__` and the content hash behave as pinned
  by the `2.5.1` vectors; this plan does not re-verify them.

### Obligations

- OB-1 (exact amounts): for every decimal string `s` with at most 30 decimal
  places and every supported currency, `major_amount_rate(s, units, unit,
  currency)` equals `MeteredRate.reduced(Decimal(s) * 10**exponent as an exact
  fraction, units)`; no binary float is ever constructed. Method: Hypothesis
  property over generated decimal strings (`st.decimals(allow_nan=False,
  allow_infinity=False, places=...)` rendered with `format(d, "f")`) through
  the real decoder and the real rate builder, plus named examples `0.0001`,
  `5`, `1e-6`, and `0`. Non-vacuity: record `hypothesis.event` for
  zero, integral, and fractional amounts and assert each class occurs; a
  seeded fault that decodes with plain `SafeLoader` must fail the property for
  `0.1`. Artefact: `tests/test_cost_pricing_amounts_properties.py`.
- OB-2 (selection equivalence): `select_effective_snapshot` returns, for any
  set of snapshots without ambiguous identities, the snapshot with the
  greatest `effective_from` not after `at` (unset counts as the earliest
  instant) among those with the requested subject, and raises `LookupError`
  when none qualifies. `FilePricingCatalogue.resolve` and
  `DiscoveringPricingCatalogue.resolve` agree on every input. Method:
  Hypothesis property with an independent oracle (sort then filter), and a
  differential property running both catalogues over the same generated card
  set. Non-vacuity: classify hits, misses, unset-`effective_from` winners and
  future-dated exclusions; a mutation that uses `<` instead of `<=` must fail.
  Artefact: `tests/test_cost_pricing_selection_properties.py`.
- OB-3 (first-seen deduplication): for any sequence of discoveries of
  documents drawn from a small pool, the number of persisted revisions for a
  subject equals the number of *changes* in pricing content along the
  sequence, every resolved snapshot's `retrieved_at` is the instant its
  content first appeared since the previous change, and re-running the same
  sequence persists nothing new. Method: Hypothesis `RuleBasedStateMachine`
  over an in-memory repository fake that implements `ensure`, `get`, and
  `list_revisions` with the same ordering, with rules `discover(document)`,
  `advance_clock`, `restart_process` (new catalogue, same repository). Non-
  vacuity: assert that runs include both reuse and change transitions; a
  mutation that compares content hashes instead of `has_same_pricing_content`
  must fail. Artefact: `tests/test_cost_discovering_catalogue_state.py`.
- OB-4 (`has_same_pricing_content` is exactly "equal hash after normalizing
  time fields"): for any two valid snapshots `a` and `b`,
  `has_same_pricing_content(a, b)` holds if and only if replacing both
  snapshots' `retrieved_at` and `effective_from` with one fixed instant gives
  equal content hashes. Method: Hypothesis property reusing
  `snapshot_twin` and `sensitivity_snapshot` strategies. Non-vacuity: classify
  equal and unequal outcomes; both must occur.
- OB-5 (plan merge precedence): for any global defaults, `base` plan, and named
  plan, the effective limit for each `(path, method, metric)` key is the named
  plan's if present, else the `base` plan's (draft dialect), else the global
  default's (research dialect), and `all` applies only when no exact method
  limit exists. Method: Hypothesis property over generated limit tables with an
  oracle written as an explicit three-level lookup; named examples for each
  dialect copied from the specifications. Non-vacuity: classify which level
  wins; every level must win at least once.
- OB-6 (fail-closed quota handling): for any plan, a metric is in `rates` if
  and only if its effective limit has an overage price and `max` is absent or
  zero; every other bound metric appears in `sla_deferred_metrics`; and pricing
  usage of a deferred metric with `PricingEngine` raises
  `UnknownPricedMetricError`. Method: Hypothesis property plus a named
  regression with the SLA4OAI `pro` plan (`max: 20`, overage `0.0001`).
  Non-vacuity: both partitions must be non-empty across the run.
- OB-7 (reference resolution and origin policy): `info.x-sla` given as a
  string or as `{"$ref": ...}` resolves against the final retrieval URI after
  redirects; any hop or resolved URI outside `allowed_origins`, any scheme
  other than `https` (unless an `http` origin is explicitly allowed), more
  than three redirects, or a body over 262,144 bytes is refused with a typed
  `PricingDocumentFetchError` subclass and no further request. Method:
  parameterized examples over a finite truth table (each refusal class, each
  reference form, `./`, `../`, absolute, protocol-relative) with
  `httpx.MockTransport` recording every request; the loopback-server end-to-end
  test repeats the redirect and relative-reference cases over a real socket.
  Non-vacuity: the transport log must show the refused URI was never
  requested.
- OB-8 (persistence): `list_revisions` returns every stored snapshot for the
  subject in the documented order, verifies each hash, and raises
  `PricingSnapshotIntegrityError` for a tampered row; the migration creates and
  drops only the index. Method: py-pglite tests through `session_factory`,
  reusing `_tamper_stored_rates`; a migration test that upgrades, inspects
  `pg_indexes`, and downgrades. Non-vacuity: the tamper test must fail if
  verification is skipped.
- OB-9 (unchanged default behaviour): with no evaluator bindings, every
  existing pricing test passes unchanged, and the behavioural scenario
  "Rate cards price exactly as before" shows identical ledger costs. Method:
  run the existing suite and the new scenario.
- OB-10 (single flight): concurrent first `resolve` calls trigger exactly one
  discovery per source. Method: an `asyncio.gather` example with a fetcher fake
  that counts calls and blocks on an `asyncio.Event`; non-vacuity: the fake
  must observe at least two waiting resolvers before release.

The change introduces no lemma that needs a formal prover: the arithmetic in
OB-1 is the existing `MeteredRate.reduced` composed with an exact power-of-ten
scaling, and the remaining obligations are covered by property and stateful
testing with explicit oracles. CrossHair is not added because the critical
functions take recursive mappings whose symbolic exploration would be
unbounded; the Hypothesis oracles are a stronger fit.

## Plan of work

Each milestone follows Red-Green-Refactor: write the smallest failing test
first (using `@pytest.mark.xfail(strict=True, reason=...)` where a red run must
be recorded, and removing the marker in the green step), make it pass with the
smallest change, then refactor with the focused tests and wider gates green.
After each milestone run, in order and sequentially, `make fmt`,
`make check-fmt`, `make typecheck`, `make lint`, and `make test`, piping each
through `tee` to `/tmp/<action>-episodic-2-5-2-pricing-catalogue-port-for-pricing-source-discovery.out`.
Commit each milestone (and smaller steps) only after all gates pass.

### EP-M1: Pure SLA4OAI ingestion and shared selection helpers

Assigned: RM-1, RM-2. Plateau: domain functions exist and are fully tested;
nothing calls the SLA4OAI ones yet, and `FilePricingCatalogue` uses the
extracted selection helper with unchanged behaviour.

1. Extract `episodic/cost/pricing_amounts.py` from `_document.py`
   (`_is_representable_amount`, `_decimal_amount`, `_amount_fraction`) as
   public `decimal_fraction(text)` plus `MINOR_UNIT_EXPONENTS` and
   `major_amount_rate(amount, per_units, unit, currency)`. `_document.py`
   imports the helper, shrinking below its current 389 lines. Register the
   module in Hecate `domain_ports`.
2. Make `_METRIC_UNITS` reachable as a public query,
   `required_unit_for(metric) -> UsageUnit | None`, in
   `episodic/cost/pricing_snapshot.py`, so the SLA4OAI mapper can refuse a
   rated metric with no known unit.
3. Add `episodic/cost/pricing_selection.py` with
   `select_effective_snapshot`, `reject_ambiguous_snapshots`, and
   `has_same_pricing_content`; rewrite `FilePricingCatalogue.resolve` and
   `_reject_duplicates` to call them. Existing
   `tests/test_cost_pricing_catalogue_*.py` must pass unchanged. Register the
   module in `domain_ports`.
4. Add `episodic/cost/sla4oai_document.py`: frozen dataclasses
   `Sla4OaiDocument` (`dialect`, `context_id`, `context_type`, `plans`,
   `defaults`), `Sla4OaiPlan` (`pricing`, `quotas`), `PlanPricing` (`cost` as
   `Decimal`, `currency`, `billing`, `is_custom`), `LimitKey` (`path`,
   `method`, `metric`), `Limit` (`max`, `period`, `overage`, `is_custom`), and
   `Overage` (`units`, `cost`); `parse_sla4oai_document(data)` raising
   `Sla4OaiDocumentError` with a JSON-pointer location; and
   `sla_reference_of(openapi)` accepting `info.x-sla` as a string or
   `{"$ref": string}`. Globbed paths (containing `*`) are parsed and kept, and
   rejected only when the bound operation would need one. `context.type`
   must be `plans`.
5. Add `episodic/cost/sla4oai_pricing.py`: `effective_plan_terms(document,
   plan_name)` (OB-5) and `snapshot_from_plan(...)` (D3, D4, D10).
6. Tests (red first): `tests/test_cost_pricing_amounts*.py`,
   `tests/test_cost_pricing_selection*.py`, `tests/test_cost_sla4oai_document.py`
   (both dialects, every rejection, location in every error message),
   `tests/test_cost_sla4oai_pricing.py`, the OB-1, OB-2, OB-4, OB-5, OB-6
   properties, and a syrupy snapshot `tests/__snapshots__/test_cost_sla4oai_pricing.ambr`
   pinning the canonical document and content hash of snapshots built from the
   two specification fixtures (multivariant output consistency across
   dialects). Fixtures: `tests/fixtures/sla4oai/research-0-10-plans.yaml`,
   `draft-1-0-plans.yaml`, `openapi-x-sla-string.json`,
   `openapi-x-sla-ref.yaml`.

Acceptance: `uv run pytest tests/test_cost_pricing_selection.py
tests/test_cost_sla4oai_pricing.py -q` passes; the full gates pass;
`git diff d0bdabe3 -- tests/__snapshots__/test_cost_pricing_snapshot_hash.ambr`
is empty. Conformance check: no domain module imports `yaml`, `httpx`, or
`pathlib`. Recovery: each step is a separate commit; revert the last commit to
return to the previous plateau. Remaining gaps: nothing fetches documents.

### EP-M2: Discovery ports, snapshot revision listing, and subject index

Assigned: RM-3. Plateau: the ports exist; the store can list revisions; the
index is deployed by migration; nothing discovers yet.

1. Add `episodic/cost/pricing_discovery_ports.py` (domain): `PricingDocument`
   (`requested_uri`, `retrieval_uri`, `media_type`, `text`, `data`,
   `retrieved_at`); `PricingDocumentFetcherPort.fetch(uri, *, allowed_origins)`;
   `PricingDiscovery` (`source_name`, `snapshots`); `PricingSourcePort`
   (`name` property and `discover(*, at)`); `EvaluatorPricingBinding` with
   validation (names, `https` or explicitly allowed origins, path starts with
   `/`, method in the SLA4OAI method set or `all`); `PricingSnapshotHistoryFactory`
   (a callable returning an async context manager that yields a
   `PricingSnapshotRepository`); and errors `PricingDiscoveryError`
   (subclass of `CostAccountingError`), `PricingDocumentFetchError` with
   subclasses for transport, status, size, media type, origin, and redirect
   limit failures, and `Sla4OaiDocumentError`.
2. Add `list_revisions(subject)` to `PricingSnapshotRepository`, implement it
   in `SqlAlchemyPricingSnapshotStore` (verifying each row as `get` does) and
   in `InstrumentedPricingSnapshotRepository` (same span and counter pattern
   as `get`), and add it to every in-memory fake used by tests.
3. Add `__table_args__` index `ix_pricing_snapshots_subject` to
   `PricingSnapshotRecord` and the Alembic revision
   `<date>_000018_index_pricing_snapshot_subjects.py` (`down_revision =
   "20261110_000017"`), spelling the index out in the revision as
   `20261020_000015` does, with a definition test that reads the deployed
   index back from PostgreSQL.
4. Tests: store tests for ordering, empty results, and tamper refusal; a
   migration upgrade and downgrade test; protocol conformance tests in
   `tests/test_cost_ports_protocols.py`.

Acceptance: `make check-migrations` passes; the new store tests pass under
py-pglite. Recovery: revert the milestone commits; the downgrade drops only
the index. Remaining gaps: nothing uses the ports.

### EP-M3: Discovering catalogue and SLA4OAI pricing source

Assigned: RM-1, RM-2, RM-3. Plateau: the application services are complete and
tested against fakes; runtime still constructs `FilePricingCatalogue`.

1. Add `FilePricingCatalogue.name` and `discover(*, at)` returning its loaded
   cards, so it satisfies `PricingSourcePort`.
2. Add `episodic/cost/pricing_discovery.py` (application):
   `Sla4OaiPricingSource(binding, fetcher)`. `discover` fetches the OpenAPI
   document, reads `sla_reference_of`, resolves it with `urljoin` against
   `retrieval_uri`, fetches the plans document with the binding's allowed
   origins, parses, merges, and builds one snapshot with `at` as both
   timestamps. Register in Hecate `application`.
3. Add `episodic/cost/discovering_catalogue.py` (application):
   `DiscoveringPricingCatalogue(sources, history, *, now, refresh_interval,
   logger)` implementing `PricingCataloguePort` with the D5 and D7 behaviour,
   rejecting a refresh in which two sources publish the same subject and
   `effective_from` (`PricingDiscoveryError` naming both sources). Register in
   `application`. Logging uses `episodic.logging` (femtologging) with the
   source name, binding subject, and failure category; never the document.
4. Tests (red first): example tests for each D7 branch (first success, reuse,
   change, failure with fallback, failure without history, interval not yet
   elapsed, cross-source collision), OB-3 state machine, OB-10 single flight,
   and the OB-2 differential property against `FilePricingCatalogue`.

Acceptance: the new tests and the full gates pass. Conformance check: the two
application modules import only domain ports and `episodic.logging`.
Recovery: revert the milestone commits. Remaining gaps: no HTTP adapter, no
runtime wiring.

### EP-M4: HTTP fetcher, binding loader, and runtime wiring

Assigned: RM-1, RM-2. Plateau: production runtime builds the discovering
catalogue; with no bindings it behaves exactly as before.

1. Add `episodic/cost/pricing_catalogue/_decoding.py`: `_ExactNumberLoader`
   (subclass of the existing `_UniqueKeyLoader`) constructing
   `tag:yaml.org,2002:float` as `decimal.Decimal(scalar_text)`, and
   `decode_pricing_document(text, media_type)` that accepts
   `application/json`, `application/yaml`, `application/x-yaml`, `text/yaml`,
   `application/vnd.oai.openapi`, and `application/vnd.oai.openapi+json`
   (each optionally with parameters), rejecting other media types.
2. Add `episodic/cost/pricing_catalogue/http_fetcher.py`:
   `HttpPricingDocumentFetcher(client: httpx.AsyncClient, *, timeout,
   max_redirects=3, clock)`. It sends `Accept` for YAML and JSON, never sends
   credentials, follows redirects manually checking each hop's origin,
   streams the body and aborts beyond 262,144 bytes, decodes strict UTF-8, and
   maps every `httpx` exception to a `PricingDocumentFetchError` subclass with
   `raise ... from ...`.
3. Add `episodic/cost/pricing_catalogue/evaluator_bindings.py`:
   `load_evaluator_bindings(path) -> tuple[EvaluatorPricingBinding, ...]`,
   strict schema version 1 with unknown-key and duplicate-name rejection,
   errors naming the file (as `PricingCatalogueError`).
4. Add `episodic/api/pricing_runtime.py` with `build_pricing_catalogue` (D8);
   add `PRICING_EVALUATOR_BINDINGS` (optional path),
   `PRICING_DISCOVERY_REFRESH_SECONDS` (default 3600), and
   `PRICING_DISCOVERY_TIMEOUT_SECONDS` (default 10) to `runtime_config.py`;
   switch `_build_generation_launcher` to the new builder; close the
   `httpx.AsyncClient` in the existing shutdown hook. Register the new module
   in Hecate `composition_root`. Move `pyyaml` to runtime dependencies and run
   `uv lock`.
5. Tests (red first): `tests/test_cost_pricing_http_fetcher.py` (OB-7 truth
   table with `httpx.MockTransport`), `tests/test_cost_pricing_decoding.py`
   (exact decimals, duplicate keys, media types, invalid UTF-8),
   `tests/test_cost_evaluator_bindings.py`, runtime configuration tests, and
   an end-to-end test `tests/test_pricing_discovery_loopback.py` that starts a
   loopback `ThreadingHTTPServer` serving an OpenAPI document with a relative
   `info.x-sla`, a redirect, and a plans document, then resolves through the
   real fetcher, the real catalogue, and a py-pglite repository, and asserts
   the stored row's `source_document_content` equals the served bytes.

Acceptance: the loopback end-to-end test passes; with
`PRICING_EVALUATOR_BINDINGS` unset the runtime makes no HTTP request (asserted
with a transport that fails on any request). Recovery: revert the milestone
commits; runtime falls back to the EP-M3 plateau. Remaining gaps: behavioural
scenarios and documentation.

### EP-M5: Behavioural scenarios, documentation, ADR, and roadmap closure

Assigned: all. Plateau: the item is complete.

1. Add `tests/features/pricing_source_discovery.feature` (below) with
   `tests/steps/test_pricing_source_discovery_steps.py`, step definitions in
   `tests/steps/pricing_source_discovery_step_definitions.py` registered in
   `tests/conftest.py`, and support in
   `tests/steps/pricing_source_discovery_support.py`. The evaluator inference
   call goes to Vidai Mock (an isolated provider config written at runtime, as
   `tests/steps/pricing_snapshots_vidaimock.py` does); pricing documents come
   from the loopback server.
2. Write `docs/adrs/adr-0029-pricing-source-discovery.md` recording D1 to D10
   (check the next free number first; renumber if upstream took it), add
   amendment banners and `## Amendments` entries to ADR-015 (`sla4oai_plan` is
   no longer reserved) and ADR-028 (outstanding decisions closed), and list
   the ADR in `docs/contents.md`.
3. Update `docs/episodic-podcast-generation-system-design.md` (pricing
   catalogue section: sources, discovery, deduplication, fallback, deferred
   metrics, reference to ADR-0029), `docs/users-guide.md` (evaluator binding
   file format, the three settings, fallback behaviour, what is and is not
   priced), `docs/developers-guide.md` (module map, Hecate registrations, test
   fixtures: loopback server, SLA4OAI fixtures, why Vidai Mock does not serve
   documents), and `docs/repository-layout.md`.
4. Mark `2.5.2` done in `docs/roadmap.md`.
5. Run `make fmt`, `make markdownlint`, and `make nixie` as well as the code
   gates.

Feature specification (`tests/features/pricing_source_discovery.feature`):

```gherkin
Feature: Pricing-source discovery
  The pricing catalogue combines pinned rate cards with prices that
  standalone evaluator services publish through OpenAPI and SLA4OAI, and it
  persists every snapshot it discovers so historical costs stay explainable.

  Scenario: Rate cards price exactly as before
    Given a gpt-4o-mini rate card charging 8 minor units per million cached input tokens
    And no evaluator pricing bindings
    When a generation run records a call with 1000000 input tokens and 1000000 cached input tokens
    Then the run's ledger entry costs 23 minor units
    And the rate card's snapshot is stored even though it was discovered before any call

  Scenario: An evaluator call is billed from its discovered plan
    Given an evaluator service whose OpenAPI document links its SLA4OAI plans with a relative info.x-sla reference
    And the "metered" plan charges 0.01 USD per request with no included quota
    And an evaluator pricing binding for that service and plan
    And a Vidai Mock server answering the evaluator's inference call
    When a generation run records one evaluator request
    Then the run's ledger entry costs 1 minor unit
    And the stored snapshot's source document is the served plans document byte for byte
    And the stored snapshot records the plan name and the resolved SLA URI

  Scenario: Rediscovering an unchanged plan reuses the stored snapshot
    Given an evaluator pricing binding whose plan has already been discovered and stored
    When the catalogue refreshes after its refresh interval
    Then no new pricing snapshot is stored
    And the resolved snapshot keeps its original retrieval time

  Scenario: A changed plan becomes a new revision without repricing pinned runs
    Given a generation run pinned to the evaluator's "metered" plan at 0.01 USD per request
    When the evaluator publishes 0.02 USD per request and the catalogue refreshes
    Then two revisions of the evaluator's snapshot are stored
    And the pinned run still prices one request at 1 minor unit
    And a new run prices one request at 2 minor units

  Scenario: An unreachable evaluator keeps pricing from its last stored plan
    Given an evaluator pricing binding whose plan has already been discovered and stored
    When the evaluator's OpenAPI document returns HTTP 503 and the catalogue refreshes
    Then the evaluator subject still resolves to the stored snapshot
    And a discovery warning names the evaluator and the failure category

  Scenario: A plan with an included quota is not priced per call
    Given the "pro" plan includes 20 requests per second with overage at 0.0001 USD per request
    And an evaluator pricing binding for that plan
    When a generation run records one evaluator request
    Then recording fails with an unknown priced metric error for "requests"
    And the stored snapshot lists "requests" as a deferred metric

  Scenario: An x-sla reference to another origin is refused
    Given an evaluator whose OpenAPI document points info.x-sla at an origin the binding does not allow
    When the catalogue refreshes
    Then no request is made to the other origin
    And the evaluator subject does not resolve
```

Acceptance: `make test` runs the seven scenarios green; markdown gates pass;
`docs/roadmap.md` shows `- [x] 2.5.2.`.

## Milestones and plateaus

- EP-M1 ends with pure, tested domain functions and an unchanged runtime.
- EP-M2 ends with ports, a revision listing, and an index migration.
- EP-M3 ends with the application services tested against fakes.
- EP-M4 ends with production wiring that is a no-op without bindings.
- EP-M5 ends with behavioural evidence, documentation, and the roadmap tick.

No milestone adds compatibility machinery: `FilePricingCatalogue` keeps its
role as the rate-card source and offline catalogue (D1), and every caller of a
changed internal signature changes in the same commit.

## Concrete steps

Run from the repository root
(`/home/leynos/.lody/repos/github---leynos---episodic/worktrees/0ed919ec-9413-4296-9ea2-15794325aa55`
during planning; any checkout of the branch works):

```bash
git branch --show-current
# 2-5-2-pricing-catalogue-port-for-pricing-source-discovery
BR=$(git branch --show-current)
make fmt 2>&1 | tee /tmp/fmt-episodic-$BR.out
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-$BR.out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-$BR.out
make lint 2>&1 | tee /tmp/lint-episodic-$BR.out
make test 2>&1 | tee /tmp/test-episodic-$BR.out
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-$BR.out
make nixie 2>&1 | tee /tmp/nixie-episodic-$BR.out
```

Run gates sequentially, never in parallel. If editing `pyproject.toml` makes
`make` recreate `.venv` on the wrong interpreter, set `UV_PYTHON=3.14` for the
gates. Local `make test` needs `vidaimock` 0.2.8 or later on `PATH` (0.3.1 is
pinned in CI). Timeouts above 180 seconds in pytest are usually host
contention; re-run the affected suite alone before believing them.

Focused red-green loops, for example:

```bash
uv run pytest tests/test_cost_sla4oai_pricing.py -q
# red:   1 failed (xfail strict) / ImportError before the module exists
# green: N passed
```

## Validation and acceptance

The item is accepted when all of the following hold:

1. `make check-fmt`, `make typecheck`, `make lint`, and `make test` pass on the
   final commit, and `make markdownlint` and `make nixie` pass.
2. The seven scenarios in `tests/features/pricing_source_discovery.feature`
   pass, including the Vidai Mock-backed evaluator call.
3. `tests/test_pricing_discovery_loopback.py` passes over a real socket.
4. The existing pricing suites, including
   `tests/features/pricing_snapshots.feature`, pass without modification
   other than fakes gaining `list_revisions`.
5. The pinned hash vectors are byte-for-byte unchanged:
   `git diff d0bdabe3 -- tests/__snapshots__/test_cost_pricing_snapshot_hash.ambr`
   prints nothing.
6. The size counts in `Tolerances` are within budget and recorded in
   `Outcomes & retrospective`.

## Idempotence and recovery

Every step is a commit; reverting a commit restores the previous plateau. The
migration only adds an index and its downgrade only drops it, so it can be
applied and rolled back repeatedly. Discovery itself is idempotent by D5:
repeating a refresh against unchanged documents writes nothing. If a gate run
is interrupted, re-run it; gates do not mutate tracked files except `make fmt`
and `make spelling` (commit a regenerated `typos.toml` separately if it changes
for unrelated reasons).

## Artefacts and notes

SLA4OAI research specification 0.10.0 example (plans with quota and overage),
which becomes `tests/fixtures/sla4oai/research-0-10-plans.yaml`:

```yaml
plans:
  pro:
    pricing:
      cost: 50
    quotas:
      /pets:
        get:
          requests:
            - max: 20
              period:
                amount: 1
                unit: second
              cost:
                overage:
                  overage: 1
                  cost: 0.0001
```

SLA4OAI 1.0.0 draft example (root version key, `base` plan, string periods):

```yaml
sla: 1.0.0
context:
  id: petstore-sample
  type: plans
  api:
    $ref: ./petstore-service.yml
  provider: ISAGroup
plans:
  base:
    availability: R/00:00:00Z/23:00:00Z
  pro:
    pricing:
      cost: 5
      currency: EUR
      billing: monthly
```

Sources: <https://sla4oai.specs.governify.io/Specification.html>,
<https://github.com/isa-group/SLA4OAI-Specification/blob/main/versions/1.0.0-Draft.md>,
RFC 3986 §5.1.3 (base URI from the retrieval URI, after redirects).

## Interfaces and dependencies

Domain (`episodic/cost/pricing_discovery_ports.py`):

```python
@dc.dataclass(frozen=True, slots=True)
class PricingDocument:
    requested_uri: str
    retrieval_uri: str
    media_type: str
    text: str
    data: cabc.Mapping[str, object]
    retrieved_at: dt.datetime


@typ.runtime_checkable
class PricingDocumentFetcherPort(typ.Protocol):
    async def fetch(
        self, uri: str, *, allowed_origins: frozenset[str]
    ) -> PricingDocument: ...


@dc.dataclass(frozen=True, slots=True)
class PricingDiscovery:
    source_name: str
    snapshots: tuple[PricingSnapshot, ...]


@typ.runtime_checkable
class PricingSourcePort(typ.Protocol):
    @property
    def name(self) -> str: ...

    async def discover(self, *, at: dt.datetime) -> PricingDiscovery: ...


type PricingSnapshotHistoryFactory = cabc.Callable[
    [], contextlib.AbstractAsyncContextManager[PricingSnapshotRepository]
]
```

Domain (`episodic/cost/pricing_snapshot_ports.py`, added method):

```python
async def list_revisions(
    self, subject: PricingSubject
) -> tuple[PricingSnapshot, ...]: ...
```

Domain (`episodic/cost/pricing_selection.py`):

```python
def select_effective_snapshot(
    snapshots: cabc.Iterable[PricingSnapshot],
    subject: PricingSubject,
    at: dt.datetime,
) -> PricingSnapshot: ...

def has_same_pricing_content(a: PricingSnapshot, b: PricingSnapshot) -> bool: ...
```

Application (`episodic/cost/discovering_catalogue.py`):

```python
class DiscoveringPricingCatalogue:
    def __init__(
        self,
        sources: tuple[PricingSourcePort, ...],
        history: PricingSnapshotHistoryFactory,
        *,
        now: cabc.Callable[[], dt.datetime],
        refresh_interval: dt.timedelta = dt.timedelta(hours=1),
    ) -> None: ...

    async def resolve(
        self, subject: PricingSubject, *, at: dt.datetime | None = None
    ) -> PricingSnapshot: ...
```

Dependencies: `httpx` (already a runtime dependency) for the fetcher; `pyyaml`
moves from the `dev` group to runtime dependencies. No other dependency
changes. Hecate: register `episodic.cost.pricing_amounts`,
`episodic.cost.pricing_selection`, `episodic.cost.sla4oai_document`,
`episodic.cost.sla4oai_pricing`, and `episodic.cost.pricing_discovery_ports`
in `domain_ports`; `episodic.cost.pricing_discovery` and
`episodic.cost.discovering_catalogue` in `application`;
`episodic.api.pricing_runtime` in `composition_root`. The new adapter modules
are already covered by the `episodic.cost.pricing_catalogue` prefix.

## Revision note

- 2026-11-22: initial draft from reconnaissance, specification research, and a
  Vidai Mock capability probe. Awaiting design review.
