# Add `PricingCataloguePort` pricing-source discovery (2.5.2)

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & discoveries`, `Decision log`,
`Outcomes & retrospective`, `Conformance basis`, and `Verification plan` must
be kept up to date as work proceeds.

Status: DRAFT (expert design review applied; awaiting user approval)

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
describes one snapshot; it is *pinned* because it is versioned in Git and
carries its own `retrieved_at` and `effective_from` instants. The *catalogue*
answers "which snapshot prices this subject at this instant?". *OpenAPI* is the
standard machine-readable description of an HTTP API; its `info` object may
carry vendor extensions whose names start with `x-`. *SLA4OAI* (Service Level
Agreements for OpenAPI) is a sister specification: an OpenAPI document points
at an SLA4OAI document with `info.x-sla`, and the SLA4OAI *plans* document
describes named service plans, each with optional pricing, *quotas* (usage
allowances, optionally with an *overage* price for usage beyond the allowance),
and *rates* (throughput limits). An *evaluator service* is a quality-assurance
evaluator (for example Pedante) deployed as a standalone HTTP service rather
than as an in-process LangGraph node. *Discovery* is finding a pricing source's
current document; *ingestion* is turning that document into a snapshot;
*vendoring* is copying a fetched document byte for byte into the repository so
it can be reviewed and pinned like a rate card.

What exists today. `PricingCataloguePort.resolve(subject, *, at=None)` (in
`episodic/cost/ports.py`) is implemented by `FilePricingCatalogue`
(`episodic/cost/pricing_catalogue/file_loader.py`), which loads every card in
the directory at construction, so a malformed card stops the process at
start-up, and picks the card with the greatest `effective_from` not after the
requested instant. `CostRecorder` (`episodic/cost/recorder.py`) persists the
chosen snapshot through `PricingSnapshotRepository.ensure` before it pins a run
or records a call. The only production `CostRecorder` is built in
`episodic/api/runtime.py`, and the LangGraph orchestration code receives it by
injection, so the catalogue is already the one source of truth for internal
LangGraph billing.

What is missing:

- Nothing reads a real SLA4OAI document. The `sla4oai_plan` source kind
  exists, but an "SLA4OAI card" today is a handwritten Episodic rate card whose
  own YAML text is stored as the "source document"; no plans document is ever
  parsed, and the stored text is not the evaluator's published terms.
- Nothing understands `info.x-sla`.
- A pinned card that no call has used yet is not in the database. If the file
  is later deleted, nothing records that the price was ever in force.

After this change an operator can do three new things, and nothing they do
today changes.

First, they can run the discovery tool against an evaluator's OpenAPI document:

```bash
uv run python scripts/vendor_sla4oai_plan.py \
  --openapi-uri https://pedante.internal.example/openapi.json \
  --plan metered --provider-name pedante-service --model default \
  --operation evaluate --sla-path /evaluations --sla-method post \
  --output-directory config/pricing-snapshots
```

The tool fetches `openapi.json`, follows `info.x-sla` (a relative reference is
resolved against the URI the OpenAPI document was actually retrieved from),
fetches the plans document under strict safety rules, validates that plan
`metered` can be priced exactly, and writes two files: the plans document byte
for byte under `config/pricing-snapshots/sla4oai/`, and a small card that binds
it to a priced subject. The operator reviews both in a pull request.

Second, once the card is deployed, the catalogue resolves
`helper_service/pedante-service/default/evaluate` to a snapshot whose
`source_kind` is `sla4oai_plan`, whose rates come from the plan's overage
prices, and whose source document is the evaluator's plans document byte for
byte. A plan whose price cannot be represented exactly by today's engine (an
included quota, a flat fee, custom pricing, a sub-cent per-request price) is
refused at start-up with an error naming the card, the plan, and the metric,
rather than mispricing calls later.

Third, every card the running catalogue loaded, used or not, is persisted to
`pricing_snapshots` shortly after the API process starts, so the database keeps
a complete history of the prices that were in force. The API builds a pricing
catalogue only when an LLM is configured, exactly as today, so archival runs
only in those deployments (D7).

No production code records evaluator (`helper_service`) calls yet; evaluators
still run in-process and their model calls are billed as LLM calls. This item
makes evaluator pricing ingestible and reviewable now, and leaves the live,
runtime discovery path for externalized evaluators to a follow-up roadmap item
(D1).

This item closes the outstanding decision recorded in
`docs/adrs/adr-0028-content-addressed-pricing-snapshots.md` about whether
`plan_name` and snapshot listing belong on the catalogue port (decided: the
plan name is hashed provenance in `source_metadata`; no listing is added to
`PricingCataloguePort`), and confirms that the one-type `PricingSnapshot`
survives SLA4OAI normalization (schema version 1 is unchanged; D3).

## Constraints

- `PricingSnapshot` schema version 1, its canonical form, and every pinned
  content-hash vector in
  `tests/__snapshots__/test_cost_pricing_snapshot_hash.ambr` must not change.
  The `pricing_snapshots` table must not change: no column, constraint, index,
  or migration is added by this item.
- `PricingCataloguePort.resolve(subject, *, at=None) -> PricingSnapshot` keeps
  its signature and contract, and stays a pure in-memory query: it performs no
  file, network, or database input/output.
- Rate-card behaviour is unchanged: the same snapshot for every subject and
  instant, and the same start-up failure for a malformed rate card. Rate cards
  keep their existing loader (`_UniqueKeyLoader`); the strict decoders added
  here apply to SLA4OAI documents only.
- The domain stays pure (hexagonal dependency rule). Modules in the Hecate
  `domain_ports` group may import only `domain_ports` and `logging_port`
  modules: no `httpx`, `yaml`, JSON decoding of external input, `pathlib`
  input/output, or `sqlalchemy`. File reading and YAML or JSON decoding live in
  the outbound adapter package `episodic.cost.pricing_catalogue`; the archival
  service lives in a module registered in the `application` group.
- The service makes no outbound HTTP request for pricing. Network access for
  discovery happens only in the operator-run tool under `scripts/`.
- No code file may exceed 400 lines (`AGENTS.md`).
  `episodic/cost/pricing_catalogue/_document.py` and
  `episodic/cost/recorder.py` are at 389 lines; `_document.py` may only shrink
  or gain a dispatch of a few lines, and `recorder.py` must not change.
- `episodic/cost/engine.py` must not change. Rounding, quota and overage
  accounting, flat fees, and settlement belong to `2.5.3` and later items. This
  item must not accept any price it cannot reproduce exactly with the existing
  engine; it refuses such documents at load time instead (D4).
- Every production symbol must have a production caller in the milestone that
  adds it, so the blocking Skylos gate passes at every plateau. Skylos scans
  `alembic` and `episodic` (`[tool.df12_skylos] roots`); `scripts/` is outside
  its roots.
- `pyyaml` moves from the `dev` dependency group to `[project].dependencies`,
  because production code already imports `yaml` and today receives it only
  transitively through `langchain-core`. No other dependency change is
  authorized.
- The handwritten `sla4oai_plan` card form is retired (D9). Stored rows of that
  kind, including those converted by migration `20261110_000017`, remain valid
  and readable; only the authoring format changes.
- Historical documents stay untouched: the `2.4.4` and `2.5.1` ExecPlans, and
  the bodies of ADR-015 and ADR-028 except for the amendment banners and
  `## Amendments` sections that `docs/documentation-style-guide.md` permits.
- Implementation begins only after the user approves this plan, including the
  scope decision in D1 and the proposed follow-up roadmap item.

If satisfying the objective requires violating a constraint, do not proceed.
Document the conflict in `Decision log` and escalate.

## Tolerances (exception triggers)

The comparison base is `d0bdabe3` (`origin/main` when this branch was cut).
Count with:

```bash
git diff --numstat d0bdabe3...HEAD -- . ':(exclude)docs/execplans/*'
```

Classify whole files by purpose. `*.py` and `*.feature` files, including tests,
the discovery tool, and its tests, are code. `*.md` files are documentation.
Everything else is configuration: `pyproject.toml`, `uv.lock`, `ambrleaks.toml`,
`typos.local.toml`, YAML under `config/`, test fixture YAML and JSON, and
`.ambr` snapshot files. Generated `typos.toml` is excluded. `uv.lock` counts
toward the file limit but its lines are excluded from the configuration line
count, because moving `pyyaml` rewrites lock metadata mechanically. All limits
are net lines (additions minus deletions). ExecPlan files are excluded from
every count, including this file.

Historical evidence: the `2.5.1` ExecPlan stated a per-milestone limit of 45
files and 2,500 net lines. The delivered squash commit `d0bdabe3` changed 96
non-ExecPlan files: 75 code files for 7,789 net lines, 10 documentation files
for 777 net lines, and 10 configuration files for 166 net lines. Its plan
records no escalation or budget revision, and does not say whether the limit
was per milestone or cumulative. It also records about 20 review rounds, most
of them hardening input validation. The lessons applied here are that pricing
work in this repository is test-heavy (about 60 percent of the code lines were
tests), that input-parsing surfaces attract review-driven growth, and that
budgets must state cumulative limits explicitly. The expert review of the first
draft of this plan cut its scope (no runtime HTTP, no history listing, no
migration) partly because the first draft's estimate already met its own file
limit before any review round.

Estimate, traced from `Plan of work`: about 1,500 net lines of production code
(amount helpers 80, strict decoders 220, SLA4OAI document model and parser 380
across two modules, plan pricing 260, SLA card loading 200, archival service
and start-up hook 140, discovery tool 300 split across a script and a support
package) and about 2,700 net lines of tests, so 4,200 lines. The budget adds 20
percent contingency for review hardening.

- Files: if the cumulative change touches more than 65 non-ExecPlan files,
  stop and escalate with a proposed split. (A count of the files this plan
  names comes to about 54: 13 production, 6 tool, 3 tool-test, about 16
  main-suite test and behavioural, about 7 configuration and fixture, and 9
  documentation files.)
- Code: if code exceeds 5,000 net lines cumulatively, if EP-M2 exceeds 2,200
  net lines (it lands the decoders, model, parser, pricing, and card loader
  together, because each is the others' only production caller), or if any
  other milestone exceeds 1,500 net lines, stop and escalate.
- Configuration: if configuration exceeds 450 net lines (most of it SLA4OAI
  test fixtures), stop and escalate.
- Documentation: if documentation exceeds 900 net lines, stop and escalate.
- Interface: if any REST, Celery task, or LangGraph checkpoint payload shape
  must change, or `PricingCataloguePort.resolve` must change, stop and
  escalate. Internal Python signatures inside `episodic.cost`,
  `episodic.api.app`, and the API composition root may change.
- Persisted format: if any change to `pricing_snapshots` or the canonical form
  appears necessary, stop and escalate.
- Dependencies: if any dependency change beyond moving `pyyaml` appears
  necessary, stop and escalate.
- Architecture: if Hecate needs a new group or a new allowed edge between
  groups, stop and escalate. Adding module prefixes to existing groups is
  expected and authorized.
- Pricing: if any test can pass only by changing `episodic/cost/engine.py` or
  by accepting a price the engine cannot reproduce exactly, stop and escalate.
- Iterations: if a gate still fails after three focused fix attempts, stop and
  record the evidence in `Surprises & discoveries`.
- Time: if a milestone exceeds one working day of agent time, record progress
  and escalate.
- Ambiguity: if a real evaluator's SLA4OAI document needs a feature this plan
  refuses (draft 1.0 dialect, globbed paths, included quotas, flat fees, custom
  pricing, a currency outside the minor-unit table) to be priced, stop and
  present options; do not widen the parser silently.

## Risks

- Risk: SLA4OAI has two incompatible dialects in circulation, and the
  specification's own samples contradict its prose. Severity: high. Likelihood:
  high. Evidence: the research specification 0.10.0 (2023) uses
  `info.x-sla: <uri>`, a numeric `context.version`, global defaults that plans
  override, and per-limit `cost.overage`; its official `petstore-plans.yml`
  sample uses `context.sla` instead of `context.version` and string periods
  such as `secondly`; its JSON examples are not valid JSON (`"overage: {`) and
  §5.2.15 swaps `unit` and `amount`. The 1.0.0 draft (2020) has a root version
  key named `sla` in its prose but `sla4oas` in its JSON Schema, a `base` plan
  that others inherit, `x-sla: {$ref: ...}` in examples,
  `pricing.cost: "custom"` as a string, `max: "unlimited"`, a special `default`
  path, and no overage concept at all. Mitigation: ingest only the research
  dialect (D5), accept both `context.version` and `context.sla` as its version
  marker, refuse the draft dialect with a named error (it can never yield a
  per-unit price), and write the fixtures from the specification with every
  correction recorded in a comment.
- Risk: PyYAML's YAML 1.1 resolvers corrupt prices and keys. Severity: high.
  Likelihood: certain if unmitigated. Evidence from the review probes against
  PyYAML 6.0.3: `0.0001` loads as a binary float; `1e-4`, `1.5e4`, and `1E+2`
  load as strings (YAML 1.1 floats need a dot and a signed exponent); `017`
  loads as 15 and `0x1A` as 26; `1:30` loads as 90; keys `on`, `yes`, and `no`
  load as booleans and collide; `2016-01-12` loads as a date; a 395-byte alias
  bomb expands to about 387 million nodes on a full walk. Mitigation: D6's
  strict decoders, a resolution truth table, and an exactness property.
- Risk: sub-cent per-request prices floor to zero in today's engine.
  Severity: high. Likelihood: high (the specification's own example charges
  0.0001 per request). Evidence: `MeteredRate(1, 100)` priced for one request is
  `1 * 1 // 100 == 0` (`episodic/cost/engine.py`). Mitigation: D4 refuses a
  request-denominated rate whose reduced `per_units` exceeds 1.
- Risk: following `info.x-sla` and redirects in the discovery tool is a
  server-side request forgery vector, and httpx defaults are unsafe for it.
  Severity: medium (an operator runs the tool and reviews the output).
  Likelihood: low. Evidence from the review probes against httpx 0.28.1: URL
  userinfo becomes an `Authorization: Basic` header; a prefix origin check is
  bypassed by `https://allowed.example@evil.example/`; `urlsplit` and
  `httpx.URL` disagree on hosts containing `。`; one 64 KiB gzip chunk decodes
  to 67 MB before a streamed cap sees it; per-operation timeouts never fire on
  a body trickling one byte every 9 seconds. Mitigation: D8's fetch rules and
  the OB-7 truth table.
- Risk: start-up archival writes to the database during application start-up.
  Severity: medium. Likelihood: low. Mitigation: D7 makes it best-effort, one
  short transaction per snapshot, outside any request, with failures logged and
  counted rather than aborting start-up; `CostRecorder` still persists any
  snapshot it uses, so archival never gates billing.
- Risk: retiring the handwritten `sla4oai_plan` card form breaks an operator's
  private card. Severity: low. Likelihood: low (no SLA card ships, and the
  users' guide gives no worked example of one). Mitigation: the loader refuses
  the old form with a conversion hint naming the discovery tool, and the users'
  guide documents the change.
- Risk: Vidai Mock 0.3.1 cannot serve the OpenAPI or SLA4OAI documents.
  Severity: low. Likelihood: certain. Evidence: a planning probe showed custom
  providers answer `405 Method Not Allowed` (`allow: POST`) to `GET`, with or
  without `method` or `methods` keys. Mitigation: D10.
- Risk: duplication gates flag the strict YAML loader beside
  `_UniqueKeyLoader`, or the two card parsers. Severity: low. Likelihood:
  medium. Mitigation: the strict loader subclasses `_UniqueKeyLoader` and
  reuses its duplicate-key constructor; shared field helpers stay in
  `_document.py` and are imported, not copied.

## Progress

- [x] (2026-11-22 20:30Z) Branch renamed, Lody session titled, skills loaded
  (`execplans`, `hexagonal-architecture`, `python-router`, `codegraph-mcp`,
  `firecrawl-mcp`, `vidai-mock`, `logisphere-design-review`). CodeGraph MCP
  failed to connect; reconnaissance used direct reads.
- [x] (2026-11-22 20:40Z) Wyvern reconnaissance of code, documentation, and
  test infrastructure completed.
- [x] (2026-11-22 20:45Z) Firecrawl research of the SLA4OAI research
  specification 0.10.0, the 1.0.0 draft, RFC 3986 base-URI rules, and recent
  prior art (APIs.io publishing SLA4OAI documents, November 2026) completed.
- [x] (2026-11-22 20:50Z) Vidai Mock 0.3.1 probe: `GET` routes unsupported.
- [x] (2026-11-22 21:30Z) First draft written (runtime discovery design).
- [x] (2026-11-22 22:40Z) Expert design review by four reviewers (structure
  and contracts; failure modes and scale with a pre-mortem; alternatives and
  viability; protocol, security, and verification). All four returned "Revise".
  Findings applied; see `Decision log` D1 to D11 and the revision note.
- [x] (2026-11-22 21:45Z) Closing confirmation review: "Proceed with
  conditions"; all conditions applied to D4, D7, D8, OB-1, OB-2, OB-4, OB-6,
  the tolerances, and EP-M1 to EP-M6.
- [ ] Plan approved by the user, including D1 and the follow-up roadmap item.
- [ ] `EP-M1` Exact amount helpers extracted, behaviour preserved.
- [ ] `EP-M2` Vendored SLA4OAI plans priced through the catalogue.
- [ ] `EP-M3` Every refusal is specific, typed, and property-tested.
- [ ] `EP-M4` Loaded snapshots archived at start-up.
- [ ] `EP-M5` Operator discovery tool vendors plans through `info.x-sla`.
- [ ] `EP-M6` Behavioural scenarios, documentation, ADR, and roadmap.

## Surprises & discoveries

- Observation: `PricingCataloguePort` already exists; the roadmap wording
  "add `PricingCataloguePort`" predates `2.4.4`. Evidence:
  `episodic/cost/ports.py`; ADR-015 introduced it. Impact: the Protocol is
  preserved; this item adds ingestion and discovery behind it.
- Observation: Vidai Mock 0.3.1 custom providers reject `GET`.
  Evidence: a provider with `matcher: "^/openapi\\.yaml$"` and `response_body`
  returned `405 Method Not Allowed`, `allow: POST`, with no method key and with
  `method: "GET"` or `methods: ["GET"]`, under `--isolated`. Impact: D10.
- Observation: `pyyaml` is declared only in the `dev` dependency group, yet
  `episodic/cost/pricing_catalogue/_document.py` imports `yaml` in production.
  Evidence: `pyproject.toml` `[dependency-groups].dev`; `uv.lock` lists
  `langchain-core` as the only runtime dependent. Impact: declared directly.
- Observation: the SLA4OAI specifications disagree with themselves (root key
  `sla` versus `sla4oas`; `context.version` versus `context.sla`; invalid JSON
  examples; `currency: "euro"`, which is not ISO 4217). Evidence: SLA4OAI
  research specification §5.2.2, §5.2.5, §5.2.15 and its `petstore-plans.yml`
  sample; the 1.0.0 draft and its schema; API Evangelist, "Service Level
  Agreements Come Back Around As SLA4OAI", 3 November 2026. Impact: D5.
- Observation: no production code records `helper_service` usage. Every
  production `service_kind` outside `episodic/cost` is `PricedService.LLM`
  (`episodic/generation/launcher_persistence.py:159`,
  `episodic/orchestration/_planning_orchestrator.py:297-315`), and the design
  document says evaluators are externalized only "when scale or cost management
  warrants". Impact: D1, D10.
- Observation: `CostRecorder` calls `resolve` inside the generation success
  unit of work, after `append_event` has taken `SELECT ... FOR UPDATE` on the
  run row (`launcher_persistence.py:74-104`, `generation_runs.py:292`), and
  py-pglite serves one backend at a time
  (`tests/test_cost_snapshot_concurrency.py:106`). Impact: any database or
  network work inside `resolve` would hold the run lock and could hang tests or
  self-deadlock; `resolve` stays pure (Constraints) and archival runs at
  start-up (D7).
- Observation: the deferral of `list_revisions` and a subject index is recorded
  in the `2.5.1` ExecPlan (`2-5-1-immutable-pricing-snapshots.md:907`), not in
  ADR-028, which defers only "catalogue listing". Impact: neither is needed by
  the revised design; ADR-0029 records that they stay deferred to the runtime
  discovery item.
- Observation: `make fmt` recreated `.venv` on CPython 3.15 free-threaded and
  failed because `psycopg-binary` 3.3.6 has no wheel for it. Evidence:
  `/tmp/fmt-episodic-2-5-2-pricing-catalogue-port-for-pricing-source-discovery.out`
  during planning. Impact: `Concrete steps` exports `UV_PYTHON=3.14`.

## Decision log

- D1. Decision: discovery is an operator-run, authoring-time step, and
  ingestion is a start-up step; the service performs no runtime HTTP discovery
  in this item. The discovery tool resolves `info.x-sla`, fetches the plans
  document safely, and vendors it with a card. The catalogue ingests vendored
  plans at start-up exactly as it loads rate cards. Live runtime discovery for
  externalized evaluators becomes a proposed follow-up roadmap item, "2.5.6.
  Add runtime OpenAPI `info.x-sla` discovery for externalized evaluator
  services", whose prerequisite is an item that externalizes an evaluator and
  records `helper_service` usage. Adding that item to `docs/roadmap.md`
  requires the user's approval of this plan. No roadmap item externalizes an
  evaluator today, so the proposed `2.5.6` states that prerequisite in prose
  rather than as a `Requires` link; the user may prefer to add an
  externalization item as well (open question for approval). Rationale: the
  roadmap says "support **future** … discovery", and the design document
  conditions it on evaluators being externalized; no evaluator is, and nothing
  records evaluator calls. All four reviewers found that the first draft's
  runtime discovery (lazy refresh inside `resolve`, a history transaction,
  fail-soft fallback, first-seen deduplication) would run network and database
  work inside the caller's row-locked transaction, could hang py-pglite tests
  and self-deadlock in production, dated first revisions after the calls they
  had to price, raced across processes, and could not pass the Skylos gate
  because its code had no production caller. Vendoring makes every price change
  a reviewed pull request, keeps `retrieved_at` and `effective_from` fixed in
  Git (so content-hash deduplication is free), keeps `resolve` pure, and needs
  no new settings, port, migration, or deployment change. It honours the design
  document's "pins immutable pricing snapshots … exactly as it pins provider
  rate cards today" and "the fetched document is stored verbatim". Trade-off
  accepted: a published price change is picked up only when an operator re-runs
  the tool and deploys. Alternative rejected: the first draft's runtime
  discovery, preserved in this plan's history (commit `27555eb7`) as input to
  the follow-up item.
- D2. Decision: an SLA4OAI card is a small wrapper YAML card in
  `config/pricing-snapshots/` that points at a vendored plans document in the
  `sla4oai/` subdirectory:

  ```yaml
  schema_version: 1
  service_kind: helper_service
  provider_name: pedante-service
  model: default
  operation: evaluate
  source_kind: sla4oai_plan
  retrieved_at: "2026-11-20T09:15:00Z"
  sla4oai:
    document: sla4oai/pedante-service-2026-11-20.yaml
    media_type: application/yaml
    plan: metered
    sla_operation:
      path: /evaluations
      method: post
  source_metadata:
    openapi_uri: https://pedante.internal.example/openapi.json
    sla_uri: https://pedante.internal.example/sla/plans.yaml
  ```

  `currency` and `rates` must be absent: they are derived from the document, so
  there is one source of truth. `effective_from` is optional, as for rate
  cards. The document path must be relative, must not contain `..`, and must
  resolve inside the card directory's `sla4oai/` subdirectory after symlink
  resolution. Because the catalogue globs `*.yaml` and `*.yml` non-recursively,
  vendored documents in `sla4oai/` are never mistaken for cards. Rationale:
  reviewable, pinned, and the snapshot's `source_document` is the evaluator's
  published plans document, not an Episodic wrapper.
- D3. Decision: an ingested plan becomes a schema-version-1 `PricingSnapshot`
  with `service_kind=helper_service`, `source_kind=sla4oai_plan`, the subject
  from the card, the vendored document as `source_document` (its declared media
  type without parameters), and `source_metadata` holding the card's operator
  provenance plus three loader-written keys that cannot be re-derived from the
  document: `sla4oai_plan`, `sla4oai_path`, and `sla4oai_method`. Values that
  can be re-derived from the document (dialect, deferred terms, fees) are not
  stored; `effective_plan_terms` re-derives them on demand. Operator keys may
  not use the `sla4oai_` prefix. The recorded `sla_uri` is the resolved
  reference before any redirect, so signed or rotating redirect targets never
  enter the hash. Rationale: closes ADR-028's outstanding decision without a
  persisted-format change, and records exactly what `2.5.3` needs to re-derive
  quota terms from a pinned snapshot (the plan and the bound operation).
  Hashing derivable values would mean a parser fix mints new revisions while
  old rows keep wrong derived values. Alternative rejected: a schema-version-2
  snapshot with quota fields; it changes the canonical form and every vector,
  and the quota semantics belong to `2.5.3`.
- D4. Decision: the catalogue accepts a plan only if every quota limit that
  applies to the bound operation can be priced exactly, per call, by today's
  engine; otherwise the card is refused at start-up. The only metric this item
  prices is `requests` (unit `request`): evaluators bill per request, and
  nothing produces any other helper-service metric. The `requests` limit is
  priceable when, after merging (D5): exactly one limit object applies;
  `custom` is absent or false; `max` is `0`; it carries `cost.overage` with a
  positive integer `overage` and a finite, non-negative `cost`; and the reduced
  rate has `per_units == 1`, so every request costs a whole number of minor
  units and the engine's per-call truncation never loses money. A zero `cost`
  is a valid, exact price (free requests). Any quota limit on the bound
  operation for another metric, with or without a cost, refuses the plan,
  because usage beyond it could not be priced. The plan's `pricing` must not be
  `custom` (either `custom: true` or `cost: "custom"`) and its `cost` must be
  absent or zero. A throughput limit (`rates`) on the bound operation that
  carries any `cost` is refused; one without a cost is ignored. A plan with no
  `requests` quota for the bound operation is refused. `{overage: N, cost: C}`
  is read as `C` major units per `N` requests, pro rata: with
  `(p, q) = decimal_fraction(C * 10**exponent)`, the rate is
  `MeteredRate.reduced(p, q * N)`, as `_parse_rate` in `_document.py` already
  builds card rates. Checks run in a fixed order (dialect, plan existence, plan
  pricing, path and method matching, metric set, limit shape, rate
  granularity), so each refused document reports one deterministic reason.
  Error ownership: the domain raises `Sla4OaiPricingError` naming the plan,
  operation, metric, JSON pointer, and reason, but never a file path;
  `_sla4oai_card.py` re-raises it as
  `PricingCatalogueError(f"{path}: …") from exc`, keeping
  `FilePricingCatalogue`'s documented error contract. Rationale: the engine
  raises nothing for a metric it can price, so the only safe refusal point is
  load time; failing at record time would roll back an already-paid draft
  (ADR-028 known risk) as an `unexpected` failure. Token, character, and
  millisecond rates would reintroduce per-call truncation (0.002 USD per 1,000
  tokens becomes `MeteredRate(1, 5000)`, and a 3,000-token call floors to 0);
  they wait for `2.5.3`'s rounding decision. Included quotas, flat fees,
  sub-cent request prices, and per-period settlement all need `2.5.3` metering
  or later settlement work.
- D5. Decision: ingest only the research dialect (SLA4OAI 0.10.0), identified
  by a `context` object carrying `version` or `sla` (number or string,
  normalized to a string) and `type: plans`. A document with a root `sla` or
  `sla4oas` key is the 1.0.0 draft and is refused with
  `Sla4OaiUnsupportedDialectError`, because the draft has no per-unit price.
  Merging is field by field for `pricing` (global, then plan) and per
  `(path, method, metric)` key for `quotas` and `rates`; when a global
  `pricing` field is set and the plan's `pricing` object omits it, the two
  readings of "override" (whole object versus field) disagree, and the plan is
  refused as ambiguous. Paths match exactly; if any globbed path (containing
  `*`) would match the bound path, the plan is refused. A method key matches
  exactly or via `all`; if both exist for one metric at any level, the plan is
  refused. Keys unused for pricing (`infrastructure`, `metrics`, `guarantees`,
  `configuration`, `availability`) are kept verbatim in the stored document and
  not validated. Rationale: Episodic's own evaluators will author their
  documents, so one dialect is enough, and refusing ambiguity is cheaper than
  guessing.
- D6. Decision: SLA4OAI documents are decoded strictly in
  `episodic/cost/pricing_catalogue/_decoding.py`. JSON (`application/json`) uses
  `json.loads` with `parse_float=decimal.Decimal`, a `parse_constant` that
  raises (no `NaN` or `Infinity`), and an `object_pairs_hook` that rejects
  duplicate keys. YAML (`application/yaml`) uses a `_UniqueKeyLoader` subclass
  whose implicit resolvers are replaced by the YAML 1.2 core schema subset: null
  (`~`, `null`, empty), booleans `true` and `false` only, decimal integers
  only, and floats with an optional signed or unsigned exponent constructed as
  finite `decimal.Decimal`; no timestamp, sexagesimal, octal, hexadecimal, merge
  (`<<`), or value resolution. The loader rejects anchors and aliases,
  explicit tags, non-string mapping keys, and NUL characters. Text must be
  strict UTF-8 without a byte-order mark. Parsers check types strictly
  (`type(value) is bool`; numbers are `int` or `Decimal`, never `str`).
  Rationale: exact prices and unambiguous keys; no alias bombs.
- D7. Decision: the API archives every snapshot the running catalogue loaded,
  in the background, shortly after the process starts. A new application
  service, `archive_pricing_snapshots` in `episodic/cost/pricing_archive.py`,
  calls `PricingSnapshotRepository.ensure` for each snapshot in its own short
  unit of work, commits, logs one summary line (persisted and reused counts),
  and on a snapshot-level failure (for example a tampered stored row) logs the
  snapshot's subject and content hash with the error category, increments a
  counter, and continues with the next snapshot. It stops at the first
  connection-class failure, because every later snapshot would wait out the
  same outage. `FilePricingCatalogue` gains a query,
  `loaded_snapshots() -> tuple[PricingSnapshot, ...]`. Lifecycle:
  `create_app_from_env` builds the catalogue in its LLM-configured branch,
  passes it into `_build_generation_launcher` (which today builds it
  internally), and only in that branch registers a start-up hook and a matching
  shutdown hook. The start-up hook, run by a new
  `_StartupHooksMiddleware.process_startup` in `episodic/api/app.py` (symmetric
  with the existing `_ShutdownHooksMiddleware`), only launches archival as a
  tracked background task wrapped in one `asyncio.timeout` (30 seconds), so
  start-up completes immediately even when the database is unreachable, and
  readiness keeps reporting the database as it does today. The shutdown hook
  cancels and awaits that task, and is ordered before `engine.dispose`.
  `ApiDependencies` (in `episodic/api/dependencies.py`) gains `startup_hooks`,
  validated in `__post_init__` exactly as `shutdown_hooks` is. Deployments
  without an LLM build no catalogue today and archive nothing; building a
  catalogue there would add a new start-up failure mode on a malformed card,
  which the Constraints forbid. Rationale: delivers "persist pricing snapshots
  for historical reference" for cards no call has used, without touching
  `resolve`, the request path, or start-up latency. Archival is idempotent by
  content hash (`ensure` inserts with `ON CONFLICT DO NOTHING` and re-reads by
  hash), so many processes starting at once only reuse rows. Best-effort is
  correct because the recorder still persists every snapshot it prices.
- D8. Decision: the discovery tool is `scripts/vendor_sla4oai_plan.py` (a
  Cyclopts command) with its logic in `scripts/sla4oai_vendoring/` and tests in
  `scripts/tests/`. It runs in the project environment and imports the
  catalogue's decoder and card loader to validate its output before writing.
  Fetch rules: parse every URI with `httpx.URL`; refuse userinfo, references
  containing whitespace, control characters, or backslashes, and non-`https`
  schemes (unless `--allow-insecure-http` for loopback testing); canonicalize
  origins as `(scheme, IDNA-encoded lowercase host, explicit or default port)`
  and require every fetched URI and redirect hop to match the OpenAPI
  document's origin or an `--allow-origin`; follow at most three redirects
  manually; send `Accept-Encoding: identity` and refuse any other
  `Content-Encoding`; refuse an oversized `Content-Length` early and cap the
  streamed body (1 MiB for the OpenAPI document, 262,144 bytes for the plans
  document, matching the source-document limit); require a UTF-8 charset when
  one is declared; wrap the whole chain in one `asyncio.timeout` (default 30
  seconds); use a dedicated client with no auth, no cookies, and TLS
  verification on. `info.x-sla` is accepted as a string or as
  `{"$ref": string}` in OpenAPI 3.x and Swagger 2.0 documents; an OpenAPI 3.2
  `$self` base is refused. Relative references resolve against the final
  retrieval URI of the OpenAPI document (RFC 3986 §5.1.3), after rejecting
  references that `urljoin`'s non-strict parsing would misread (for example
  `https:evil/p`). The tool stages its output in a temporary copy of the output
  directory and validates the whole staged directory with
  `FilePricingCatalogue`, so duplicate subject and `effective_from` pairs are
  caught as well as malformed cards; only then does it rename the new files
  into place, and it never overwrites an existing file. When a card for the
  same subject already exists, `--effective-from` is required and must be later
  than that subject's latest existing card and not in the past, so a new
  revision never silently replaces the old one for past instants. The Cyclopts
  options are a frozen dataclass (as `ClusterOpts` in `scripts/local_k8s.py`),
  so Ruff's argument-count rules do not fire. Deviation from
  `docs/scripting-standards.md`, recorded: the standard asks for a PEP 723
  inline-metadata block and a `uv run --script` shebang, which a tool that
  imports `episodic` cannot meet; like `scripts/local_k8s.py`, it runs in the
  project environment with `uv run python`. `scripts/` is inside Ruff, `ty`,
  and pytest scope, and the editable install puts the repository root on
  `sys.path`, so `scripts.sla4oai_vendoring` imports resolve. Rationale:
  `info.x-sla` discovery is executable and tested end to end now, while network
  code stays outside the service, outside the Skylos roots, and under operator
  review. A CLI subcommand was rejected because the `cli` Hecate group may not
  import the catalogue adapter (a new allowed edge, out of tolerance).
- D9. Decision: retire the handwritten `sla4oai_plan` card form. A card with
  `source_kind: sla4oai_plan` must carry an `sla4oai` block and no `rates` or
  `currency`; the old form fails with a `PricingCatalogueError` that names the
  file and points at the discovery tool and the users' guide. The existing test
  `test_crlf_plan_document_is_stored_verbatim` in
  `tests/test_cost_pricing_catalogue_v1.py`, which relied on the old form, is
  rewritten to vendor a CRLF plans document, so its obligation survives.
  Rationale: one way to author an SLA snapshot, and the stored document is
  always the evaluator's own. No SLA card ships, so no deployed catalogue
  breaks.
- D10. Decision: behavioural scenarios use Vidai Mock for the inference path
  that exists, an LLM chat completion through the OpenAI-compatible adapter
  priced from an archived rate card, and record evaluator calls directly as
  `ProviderCallRecord` values, stating in the step text that no production
  producer exists yet. The discovery tool's scenarios serve documents from
  loopback `http.server.ThreadingHTTPServer` fixtures (standard library) over
  real sockets; its unit tests use `httpx.MockTransport`, as the LLM adapter
  tests do. Rationale: Vidai Mock 0.3.1 cannot answer `GET`, and routing a
  made-up evaluator client through Vidai Mock would test only test code.
- D11. Decision: the minor-unit exponent comes from an explicit table in
  `episodic/cost/pricing_amounts.py` (`USD`, `EUR`, `GBP`, each 2). A missing
  `pricing.currency` defaults to `USD`, as the specification states; any other
  currency, including the specification's own `"euro"`, is refused with an
  error naming it. Rationale: SLA4OAI prices are in major units; a wrong
  exponent misprices by orders of magnitude. Widening the table is a reviewed
  one-line change.

## Outcomes & retrospective

Not started. Record per-milestone outcomes, the final size counts against the
tolerances, and lessons here.

## Context and orientation

Episodic is a Python 3.14 service that generates podcast scripts with LangGraph
workflows and accounts for what each Large Language Model (LLM) or
Text-to-Speech (TTS) call costs. Cost accounting lives in `episodic/cost/`. The
package follows hexagonal architecture: domain value objects and ports are pure
modules; application services orchestrate ports; outbound adapters talk to
PostgreSQL, files, or HTTP. The Hecate checker (`make check-architecture`,
configured under `[tool.hecate]` in `pyproject.toml`) enforces which module
groups may import which. Hecate assigns a module to the *first* group whose
prefix matches on a dotted boundary, and does not check modules no group
matches, so every new module must be registered under a prefix explicitly.

Modules this plan touches, with their sizes at the comparison base:

- `episodic/cost/pricing_snapshot.py` (262 lines): `PricingSnapshot` and its
  validators. Domain. Not modified.
- `episodic/cost/pricing_snapshot_values.py` (246 lines): `MeteredRate`,
  `SourceDocument` (at most 262,144 UTF-8 bytes), `PricingSubject`,
  `PricedService`, `UsageUnit`. Domain. Not modified.
- `episodic/cost/pricing_snapshot_ports.py` (123 lines):
  `PricingSnapshotRepository` (`ensure`, `get`). Domain. Not modified.
- `episodic/cost/engine.py` (104 lines) and `episodic/cost/recorder.py` (389
  lines). Not modified.
- `episodic/cost/pricing_catalogue/file_loader.py` (178 lines),
  `_document.py` (389 lines), `_yaml_loader.py` (57 lines), `_errors.py`: the
  card adapter. Outbound adapter (`episodic.cost.pricing_catalogue`).
- `episodic/api/app.py`: Falcon ASGI app and `_ShutdownHooksMiddleware`.
  Inbound adapter.
- `episodic/api/runtime.py`: the API composition root
  (`create_app_from_env`, `_build_generation_launcher`).
- `episodic/api/dependencies.py`: `ApiDependencies`, including the validated
  `shutdown_hooks` tuple.
- `pyproject.toml`: Hecate groups, Skylos entry points
  (`[[tool.skylos.dead_code.entrypoints]]`), and the duplication allow-list
  (`[tool.duplication_gate]`).

New modules:

- `episodic/cost/pricing_amounts.py` (domain): `decimal_fraction`, extracted
  from `_document.py`; `MINOR_UNIT_EXPONENTS`; `major_amount_rate`.
- `episodic/cost/sla4oai_document.py` (domain): frozen dataclasses
  `Sla4OaiDocument`, `Sla4OaiPlan`, `PlanPricing`, `LimitKey`, `Limit`,
  `Overage`; `Sla4OaiDocumentError` and `Sla4OaiUnsupportedDialectError`.
- `episodic/cost/sla4oai_parsing.py` (domain): `parse_sla4oai_document(data)`
  with JSON-pointer locations in every error. Split from the model up front to
  stay under 400 lines.
- `episodic/cost/sla4oai_pricing.py` (domain): `PlanBinding`,
  `effective_plan_terms`, `plan_rates`, and `Sla4OaiPricingError`.
- `episodic/cost/pricing_archive.py` (application):
  `archive_pricing_snapshots`.
- `episodic/cost/pricing_catalogue/_decoding.py` (adapter): strict decoders.
- `episodic/cost/pricing_catalogue/_sla4oai_card.py` (adapter): SLA card
  loading.
- `scripts/vendor_sla4oai_plan.py` and `scripts/sla4oai_vendoring/` (tool).

Tests follow existing conventions. Unit tests are `tests/test_cost_*.py`.
Behavioural tests pair `tests/features/<name>.feature` with
`tests/steps/test_<name>_steps.py`, step definitions in a module registered as
a plugin in `tests/conftest.py`, and support modules under `tests/steps/`.
Syrupy snapshots live in `tests/__snapshots__/`. Hypothesis strategies for
snapshots live in `tests/pricing_snapshot_hash_strategies.py`; settings are per
test (`deadline=None` for pricing tests), with no global profile. Database
tests use `session_factory` from `tests/fixtures/database.py` (py-pglite, one
backend at a time). Vidai Mock is started by `tests/steps/vidaimock_harness.py`
with `--isolated`; CI pins 0.3.1. Script tests live in `scripts/tests/`.
`ambrleaks` scans `tests/`, so fixture URLs or digests may need
`ambrleaks.toml` entries.

### Signposted documentation

- `docs/roadmap.md` §2.5 for this item and its neighbours `2.5.3` to `2.5.5`.
- `docs/episodic-podcast-generation-system-design.md`: the ports list around
  lines 850-871, the pricing catalogue narrative around lines 1545-1594
  (`info.x-sla`, `GET /sla/plans.yaml`, "the fetched document is stored
  verbatim"), and the service-path note around lines 393-396.
- `docs/adrs/adr-0015-cost-accounting-ports-and-pricing-engine.md` (its
  `source_kind` passage still calls `sla4oai_plan` "reserved") and
  `docs/adrs/adr-0028-content-addressed-pricing-snapshots.md` (non-goals at
  lines 283-284, outstanding decisions at 328-332).
- `docs/execplans/2-5-1-immutable-pricing-snapshots.md` for snapshot design
  history and lessons (Hecate first-match, file-size pressure, rebases dropping
  allow-list entries, review-driven validation growth).
- `docs/cost-management-in-langgraph-agentic-systems.md` for the cost model's
  motivation (it has no discovery content).
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` and
  `docs/agentic-systems-with-langgraph-and-celery.md` for why LangGraph nodes
  reach pricing only through injected ports.
- `docs/async-sqlalchemy-with-pg-and-falcon.md` for the unit-of-work pattern
  the archival hook uses; `docs/testing-async-falcon-endpoints.md` for testing
  Falcon lifespan hooks; `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`
  for the archival tests.
- `docs/complexity-antipatterns-and-refactoring-strategies.md` before
  splitting the parser or the card loader.
- `docs/femtologging-users-guide.md` for the archival log lines.
- `docs/scripting-standards.md` before writing the discovery tool (Cyclopts,
  `pathlib`, `cuprum` if any external command is run, `cmd-mox`).
- `docs/tei-rapporteur-users-guide.md` is not relevant to this item.
- `docs/developers-guide.md` §"Cost accounting and pricing snapshots" and the
  Hecate module groups; `docs/users-guide.md` §"Pricing snapshots";
  `docs/documentation-style-guide.md` for the ADR format.

### Signposted skills

- `execplans` for maintaining this document.
- `hexagonal-architecture` for port placement and the dependency rule.
- `python-router`, then `python-data-shapes` (frozen dataclasses for the
  SLA4OAI model), `python-types-and-apis`, `python-errors-and-logging` (the
  error hierarchy, `raise ... from ...`), `python-testing`, and `hypothesis`.
- `vidai-mock` for the LLM inference scenario.
- `skylos` and `python-quality-tools` when the dead-code or duplication gates
  report findings.
- `en-gb-oxendict-style` for documentation; `mapsplice` for adding the
  follow-up roadmap item.
- `firecrawl-mcp` if a specification question arises during implementation.

## Conformance basis

Upstream artefacts at the comparison base `d0bdabe3`:

- Roadmap `docs/roadmap.md` item `2.5.2`, bullets RM-1 (load pinned provider
  rate cards for internal LangGraph billing), RM-2 (support future OpenAPI
  `info.x-sla` discovery and SLA4OAI plan ingestion for standalone evaluator
  services), and RM-3 (persist pricing snapshots for historical reference).
- System design: DES-PORTS (`PricingCataloguePort` "loads pinned provider rate
  cards … can later discover evaluator OpenAPI and SLA4OAI documents if those
  evaluators are externalized") and DES-SLA (the evaluator contract:
  `info.x-sla`, relative URIs permitted, the plans document pinned "exactly as
  it pins provider rate cards today" and "stored verbatim").
- ADR-015 (cost-accounting port family) and ADR-028 (content-addressed
  snapshots): ADR028-NG-1 (SLA4OAI fetching, parsing, and `info.x-sla`
  discovery deferred to `2.5.2`), ADR028-NG-2 (catalogue listing and selection
  beyond effective dating deferred to `2.5.2`), ADR028-OD-1 (whether
  `plan_name` and listing belong on the port).
- Governing standards: `AGENTS.md`, `docs/documentation-style-guide.md`,
  `docs/scripting-standards.md`, and the Hecate and Skylos configuration in
  `pyproject.toml`.
- No Terms of Reference or separate technical design document exists for this
  item beyond the system design.

Trace links:

```plaintext
RM-1 -> DES-PORTS -> D7 -> EP-M1, EP-M4
     -> feature "A Vidai Mock completion is priced from an archived rate card"
RM-2 -> DES-SLA, ADR028-NG-1 -> D1..D6, D8, D9, D11 -> EP-M2, EP-M3, EP-M5
     -> feature "A vendored metered plan prices evaluator requests"
     -> feature "The discovery tool vendors a plan through a relative info.x-sla"
RM-3 -> D7 -> EP-M4 -> feature "An unused rate card is archived at start-up"
ADR028-NG-2 -> D1 (listing deferred to the follow-up item) -> ADR-0029 -> EP-M6
ADR028-OD-1 -> D3 -> ADR-0029 -> EP-M6
```

Deviation from DES-SLA, recorded for acceptance: the design document describes
the catalogue fetching evaluator documents itself. This plan moves fetching to
an operator-run tool until an evaluator is externalized (D1). ADR-0029 records
the deviation, and the design document is updated in EP-M6.

## Verification plan

### Axioms

- AXIOM-1: `json.loads` calls `parse_float` with the literal text of every
  JSON number containing a fraction or exponent, calls `parse_constant` for
  `NaN`, `Infinity`, and `-Infinity`, and passes every object's key-value
  pairs, in order, to `object_pairs_hook`.
- AXIOM-2: a PyYAML `SafeLoader` subclass whose `yaml_implicit_resolvers` is
  replaced on the subclass resolves plain scalars only through the replacement
  resolvers, and constructors registered on the subclass do not affect
  `SafeLoader` or `_UniqueKeyLoader`.
- AXIOM-3: `urllib.parse.urljoin` implements RFC 3986 §5.2 resolution in its
  non-strict form: a reference whose scheme equals the base scheme is treated
  as relative, and leading whitespace is stripped. The tool rejects such
  references before joining rather than relying on this behaviour.
- AXIOM-4: `httpx.AsyncClient(follow_redirects=False)` returns 3xx responses
  with their `Location` header unchanged; `httpx.MockTransport` invokes its
  handler for every request; refusing any `Content-Encoding` other than
  `identity` before reading prevents decompression ahead of the size cap.
- AXIOM-5: the SLA4OAI research specification 0.10.0 and the 1.0.0 draft, as
  retrieved on 2026-11-22, define the shapes recorded in `Risks`; the fixtures
  derived from them, with corrections recorded, are the contract.
- AXIOM-6: `PricingSnapshot.__post_init__`, `MeteredRate.reduced`, and the
  content hash behave as pinned by the `2.5.1` vectors; this plan does not
  re-verify them.
- AXIOM-7: Falcon's ASGI app calls each middleware's `process_startup` once,
  before serving requests, when the server sends the lifespan startup event.

### Obligations

- OB-1 (exact amounts). For every decimal string `s` in plain or exponent form
  (`0.0001`, `1e-4`, `1.0E-4`, `5`, `0`) within range and every supported
  currency, decoding `s` through either strict decoder and then
  `major_amount_rate(value, n, unit, currency)` yields a rate equal to
  `Fraction(s) * 10**exponent / n` in lowest terms. Out-of-range values make
  the domain helper raise `AmountRangeError` (a `ValueError` subclass in
  `pricing_amounts.py`), which the SLA4OAI parser turns into
  `Sla4OaiDocumentError` and `_document.py` turns into its existing rate-card
  message, byte for byte. Method: Hypothesis property with the independent
  oracle `fractions.Fraction(text)`, generating both notations and both media
  types, plus named examples. Non-vacuity: `hypothesis.event` classifies zero,
  integral, fractional, exponent-form, and out-of-range inputs, and the test
  asserts each class occurred; a seeded fault that decodes YAML with plain
  `SafeLoader` fails the property on `0.1` and on `1e-4`. Artefact:
  `tests/test_cost_pricing_amounts_properties.py`.
- OB-2 (strict decoding). The YAML decoder resolves exactly the YAML 1.2 core
  subset in D6 and refuses every other construct named there; the JSON decoder
  refuses duplicates and non-finite constants. Method: a parameterized truth
  table, one row per construct with its expected value or error (`0.0001`,
  `1e-4`, `017`, `0x1A`, `1:30`, `on`, `yes`, `2016-01-12`, `.inf`, `.nan`,
  `~`, an alias, `<<`, `!!binary`, a non-string key, a NUL, a byte-order mark,
  duplicate keys, and a JSON integer longer than 4,300 digits, which makes
  `json.loads` raise a bare `ValueError` that the decoder must wrap); plus a
  round-trip property: any generated JSON-compatible value (recursive strategy
  over string-keyed dictionaries, lists, strings, integers, finite decimals,
  booleans, and `None`) rendered with `json.dumps` decodes to an equal value
  through both decoders. Non-vacuity: the strategy classifies nesting depth and
  leaf types, and each class must occur; removing the alias-rejection override
  must fail the alias row. Artefacts: `tests/test_cost_pricing_decoding.py` and
  `tests/test_cost_pricing_decoding_properties.py`.
- OB-3 (merge precedence and ambiguity). For generated global defaults and
  plans, the effective limit for each `(path, method, metric)` is the plan's if
  present, else the global default's; `all` applies only when no exact method
  exists, and both together are refused; pricing merges field by field and is
  refused when a global field is set and the plan's `pricing` omits it. Method:
  Hypothesis property whose oracle is an explicit dictionary lookup over a
  flattened table (not the implementation's nested shape), plus the
  specification's `petstore-plans.yml` sample (corrected) as a named case that
  must be refused as ambiguous. Non-vacuity: classify which level wins and
  which refusal fires; every class must occur.
- OB-4 (fail-closed pricing). For any plan, `plan_rates` returns a `requests`
  rate if and only if every D4 condition holds, and otherwise refuses with the
  first failing reason in D4's fixed check order. Method: Hypothesis property
  over generated limits with an oracle that checks the D4 conditions directly,
  in the same order; seeded-fault named cases, each of which must be refused
  for its own reason: `max: 20` with a 0.01 overage, a throughput limit
  carrying a cost, two limits for `requests`, `0.0001` per request, `0.05` per
  10 requests, `pricing.cost: "custom"`, `custom: true`, `pricing.cost: 50`,
  `max: "unlimited"`, a second metric such as `animalTypes` or `input_tokens`
  on the bound operation, a free cap (`max: 5`, no cost) on another metric, no
  `requests` quota at all, and a globbed path matching the bound path. A zero
  `cost` must be accepted as a free, exact price. Non-vacuity: both outcomes
  and every refusal reason must occur across the run.
- OB-5 (verbatim, stable documents). Loading a vendored document stores its
  text byte for byte, including CRLF line endings, non-ASCII text, and no
  trailing newline; a byte-order mark is refused; loading the same card twice
  yields the same content hash; changing one character of the document changes
  the hash. A syrupy snapshot pins the canonical form and content hash of the
  snapshot built from the metered fixture. Method: named tests plus the
  snapshot. Non-vacuity: the fixture must contain `\r\n` and a non-ASCII
  character (asserted before loading).
- OB-6 (archival). Archiving the same loaded snapshots any number of times
  leaves exactly one row per distinct content hash; a snapshot-level failure
  (for example a tampered stored row) is logged and counted, and the remaining
  snapshots are still archived; a connection-class failure stops archival after
  one attempt; archival never opens a unit of work while another is open;
  start-up completes within one second even when the unit-of-work factory
  blocks forever; and shutdown cancels an unfinished archival task before the
  engine is disposed. Method: py-pglite tests through `session_factory`,
  reusing the `_tamper_stored_rates` helper, each wrapped in
  `asyncio.timeout(10)` so a nested-session hang fails fast; a Falcon lifespan
  test with a fake factory that blocks forever, asserting that start-up
  completes and that shutdown cancels the task. Non-vacuity: the tamper case
  must show a logged failure and a persisted sibling, and the blocking-factory
  case must show the factory was entered. The existing
  `tests/test_lifespan_hooks.py::test_runtime_lifespan_shuts_down_generation_before_database`
  patches `_build_generation_launcher` with a bare `object()` unit-of-work
  factory; it is updated for the new catalogue argument and hook ordering in
  the same commit.
- OB-7 (discovery tool URI and fetch policy). A finite truth table over
  reference forms (string, `{"$ref"}`, `./`, `../`, absolute, protocol-relative,
  `https:evil/p`, leading whitespace, backslash) and refusal classes
  (userinfo, foreign origin, `。` host, IDNA host, explicit `:443`, trailing
  dot, non-`https` scheme, a fourth redirect, foreign redirect hop,
  `Content-Encoding: gzip`, oversized `Content-Length`, oversized streamed
  body, non-UTF-8 charset, a trickling body against the total deadline,
  `$self`), each with the expected resolved URI or typed refusal, using
  `httpx.MockTransport` recording every request. Non-vacuity: for every
  refusal, the transport log shows the refused URI was never requested; for the
  trickling case, the deadline fires within the configured bound. A loopback
  end-to-end test repeats the relative reference, redirect, and foreign-origin
  cases over real sockets, with a second listening server that must record zero
  requests, and a positive control in which `--allow-origin` lets it receive
  exactly one.
- OB-8 (unchanged rate-card behaviour). Every existing pricing test passes
  unchanged except `test_crlf_plan_document_is_stored_verbatim`, rewritten per
  D9, and the lifespan-ordering test updated per OB-6; the pinned hash vectors
  are byte-for-byte unchanged. Method: the existing suites plus
  `git diff d0bdabe3 -- tests/__snapshots__/test_cost_pricing_snapshot_hash.ambr`.

The change introduces no lemma that needs a formal prover: the arithmetic in
OB-1 is the existing `MeteredRate.reduced` composed with an exact power-of-ten
scaling, and the remaining obligations are finite truth tables or properties
with independent oracles. CrossHair is not added because the critical functions
take recursive mappings whose symbolic exploration would be unbounded; the
Hypothesis oracles are a better fit.

## Plan of work

Each milestone follows Red-Green-Refactor: write the smallest failing test
first (with `@pytest.mark.xfail(strict=True, reason=...)` where a red run must
be recorded, removing the marker in the green step), make it pass with the
smallest change, then refactor with the focused tests and wider gates green.
Every milestone lands its production callers with its code, so the Skylos gate
passes at each plateau. After each milestone run, sequentially, `make fmt`,
`make check-fmt`, `make typecheck`, `make lint`, and `make test`, each through
`tee` (see `Concrete steps`), and commit only when all pass.

### EP-M1: Exact amount helpers extracted, behaviour preserved

Assigned: RM-1 (no behaviour change). Plateau: rate cards parse through the
shared amount helper; nothing else changes.

1. Create `episodic/cost/pricing_amounts.py` with `decimal_fraction` and
   `AmountRangeError(ValueError)` (from `_is_representable_amount`,
   `_decimal_amount`, and `_amount_fraction` in `_document.py`). The helper
   raises `AmountRangeError` without a file path; `_document.py` catches it and
   calls `_fail(path, <existing message>)`, so every rate-card error message
   stays byte-identical. `_document.py` imports the helper and shrinks.
   `MINOR_UNIT_EXPONENTS` and `major_amount_rate` land in EP-M2 with their
   caller, so Skylos never sees them unused.
2. Register the module in Hecate `domain_ports`.
3. Tests: leave the existing rate-card tests untouched (they are the
   behaviour-preservation evidence) and add new tests for the extracted
   function, including OB-1's named examples and the `AmountRangeError` cases.

Acceptance: existing card tests pass unchanged; gates pass. Recovery: revert
the commit. Remaining gaps: no SLA4OAI ingestion.

### EP-M2: Vendored SLA4OAI plans priced through the catalogue

Assigned: RM-2. Plateau: a card with an `sla4oai` block loads a vendored
research-dialect plan and prices it; anything outside the narrow accepted
subset is refused with a generic `Sla4OaiPricingError` ("unsupported …"), which
the card loader re-raises as a `PricingCatalogueError` naming the card (D4).
Nothing misprices.

1. Add `_decoding.py` (D6), `sla4oai_document.py`, `sla4oai_parsing.py`,
   `sla4oai_pricing.py` (D3, D4, D5, D11), and `_sla4oai_card.py` (D2), and
   dispatch from `_document.load_snapshot` on `source_kind` (a few lines).
   `PlanTerms` holds only what `plan_rates` reads; quota and fee fields that
   only `2.5.3` would use are not modelled now (AGENTS.md, deferred
   implementation). Tests assert that each `PricingCatalogueError` raised for
   an SLA card has the domain error as its `__cause__`.
2. Retire the handwritten form (D9) and rewrite the one dependent test.
3. Register the domain modules in Hecate `domain_ports`. Move `pyyaml` into
   `[project].dependencies` and run `uv lock`.
4. Fixtures: `tests/fixtures/sla4oai/metered-plans.yaml` (CRLF, non-ASCII),
   `metered-plans.json`, `petstore-plans-research.yaml` (corrected, with a
   comment listing corrections), and `draft-1-0-plans.yaml`.
5. Tests (red first): card loading happy path, verbatim document, path
   escapes (`..`, absolute, symlink out of `sla4oai/`), forbidden `rates` and
   `currency`, reserved metadata prefix, OB-5, and the syrupy snapshot
   `tests/__snapshots__/test_cost_sla4oai_card.ambr`.

Acceptance: `uv run pytest tests/test_cost_sla4oai_card.py -q` passes; gates
pass; hash vectors unchanged. Recovery: revert the milestone commits. Remaining
gaps: refusals are generic.

### EP-M3: Every refusal is specific, typed, and property-tested

Assigned: RM-2. Plateau: each D4 and D5 refusal has its own typed error and
message; OB-1 to OB-4 are discharged.

1. Replace the generic refusal with typed errors and JSON-pointer locations
   for every D4 and D5 case, including the draft-dialect refusal.
2. Tests: OB-1, OB-2, OB-3, and OB-4 properties and truth tables.

Acceptance: the property suites pass with their classification assertions.
Recovery: revert. Remaining gaps: archival and discovery.

### EP-M4: Loaded snapshots archived at start-up

Assigned: RM-3 (and RM-1: rate cards are most of the archived content).
Plateau: an API with an LLM configured persists every loaded card in the
background shortly after start-up.

1. Add `FilePricingCatalogue.loaded_snapshots()`.
2. Add `episodic/cost/pricing_archive.py` (D7), registered in Hecate
   `application`. Logging uses `episodic.logging`; the failure counter uses the
   existing metrics port. It distinguishes connection-class failures (stop)
   from snapshot-level failures (log, count, continue).
3. Add `startup_hooks` to `ApiDependencies` in `episodic/api/dependencies.py`,
   validated in `__post_init__` as `shutdown_hooks` is, and
   `_StartupHooksMiddleware.process_startup` in `episodic/api/app.py`. Move
   catalogue construction from `_build_generation_launcher` into the
   LLM-configured branch of `create_app_from_env`, pass the catalogue in, and
   register there the start-up hook (launch the bounded background task) and a
   shutdown hook (cancel and await it) ordered before `engine.dispose`. Update
   `tests/test_lifespan_hooks.py` for the new argument and ordering.
4. Add Skylos entry-point rules for `_StartupHooksMiddleware.process_startup`
   and its `scope` and `event` parameters, mirroring the existing
   `process_shutdown` entries in `pyproject.toml`.
5. Tests (red first): OB-6, including the blocking-factory lifespan test
   through Falcon's ASGI test client.

Acceptance: starting the app against py-pglite stores every card in a temporary
card directory, a second start stores nothing new, and start-up completes
within one second when the database never answers. Recovery: revert; the hooks
are additive. Remaining gaps: discovery tool.

### EP-M5: Operator discovery tool vendors plans through `info.x-sla`

Assigned: RM-2. Plateau: an operator can vendor a plan end to end.

1. Read `docs/scripting-standards.md`. Add `scripts/vendor_sla4oai_plan.py`
   (Cyclopts entry point with a frozen options dataclass) and
   `scripts/sla4oai_vendoring/` (reference resolution, origin policy, fetcher,
   writer) under the D8 rules, recording the PEP 723 deviation in the module
   docstring.
2. Tests (red first) in `scripts/tests/test_vendor_sla4oai_plan.py` and
   sibling modules: OB-7 truth table with `httpx.MockTransport`; loopback
   end-to-end tests over real sockets; writer tests that refuse to overwrite,
   require `--effective-from` when a card for the subject exists, refuse an
   `--effective-from` that is in the past or not later than the subject's
   latest card, and reject a staged directory that `FilePricingCatalogue`
   refuses as ambiguous; and a test that the written card loads and prices.

Acceptance: the loopback test vendors a plan whose card loads and prices.
Recovery: revert; the tool is standalone. Remaining gaps: behavioural scenarios
and documentation.

### EP-M6: Behavioural scenarios, documentation, ADR, and roadmap

Assigned: all. Plateau: the item is complete.

1. Add `tests/features/pricing_source_discovery.feature` (below) with
   `tests/steps/test_pricing_source_discovery_steps.py`, step definitions in
   `tests/steps/pricing_source_discovery_step_definitions.py` registered in
   `tests/conftest.py`, and support in
   `tests/steps/pricing_source_discovery_support.py`. The Vidai Mock scenario
   reuses the provider configuration in
   `tests/steps/pricing_snapshots_vidaimock.py`. Because
   `tests.steps.pricing_snapshots_step_definitions` is registered as a global
   plugin (`tests/conftest.py`), steps whose text already exists there (the
   8-minor-unit card, the Vidai Mock server, "the run's ledger entry costs N
   minor units") bind to those existing definitions and their `pricing_context`
   fixture; the new module defines only step texts that are unique, so
   `tests/features/pricing_snapshots.feature` keeps its bindings.
2. Write `docs/adrs/adr-0029-pricing-source-discovery-and-sla4oai-ingestion.md`
   recording D1 to D11 and the DES-SLA deviation (check the next free number
   first; renumber if upstream took it). Add amendment banners and
   `## Amendments` entries to ADR-015 (`sla4oai_plan` is no longer reserved)
   and ADR-028 (outstanding decision closed; listing deferred to the
   follow-up), and list ADR-0029 in `docs/contents.md`.
3. Update `docs/episodic-podcast-generation-system-design.md` (pricing
   catalogue: vendored SLA4OAI plans, the accepted subset, archival, the
   deferred runtime discovery, and a reference to ADR-0029),
   `docs/users-guide.md` (SLA card format, the discovery tool, what is and is
   not priced and why, the retired handwritten form, and archival behaviour:
   database writes shortly after start-up, the summary log line, the failure
   counter's name, and what happens when the database is down),
   `docs/developers-guide.md` (module map, Hecate registrations, decoder rules,
   `startup_hooks` and `_StartupHooksMiddleware` alongside the shutdown hooks,
   the new Skylos entry points, the scripting-standards deviation, test
   fixtures, and why Vidai Mock does not serve documents), and
   `docs/repository-layout.md` (`config/pricing-snapshots/sla4oai/`,
   `scripts/sla4oai_vendoring/`).
4. Mark `2.5.2` done in `docs/roadmap.md` and, if the user approved it, add
   the follow-up item `2.5.6` with `mapsplice`.
5. Run `make fmt`, `make markdownlint`, and `make nixie` as well as the code
   gates.

Feature specification (`tests/features/pricing_source_discovery.feature`):

```gherkin
Feature: Pricing-source discovery
  The pricing catalogue loads pinned rate cards and vendored SLA4OAI plans,
  refuses any price it cannot reproduce exactly, and archives every snapshot
  it loads so historical costs stay explainable.

  Scenario: An unused rate card is archived at start-up
    Given rate cards for gpt-4o-mini and claude-haiku
    When the API process starts
    Then both rate cards are stored as pricing snapshots
    And starting the API process again stores no new pricing snapshot

  Scenario: A Vidai Mock completion is priced from an archived rate card
    Given a gpt-4o-mini rate card charging 8 minor units per million cached input tokens
    And the API process has started and archived its rate cards
    And a Vidai Mock server reporting 2000000 prompt tokens of which 1000000 are cached and 500000 completion tokens
    When a generation run completes a chat completion through the OpenAI-compatible adapter and records its cost
    Then the run's ledger entry costs 53 minor units
    And the ledger entry references the archived snapshot

  Scenario: A vendored metered plan prices evaluator requests
    Given a vendored SLA4OAI plans document whose "metered" plan charges 0.01 USD per request with no included quota
    And an SLA4OAI card binding that plan to evaluator "pedante-service" operation "evaluate"
    When a generation run records one evaluator request directly, because no evaluator client exists yet
    Then the run's ledger entry costs 1 minor unit
    And the stored snapshot's source document is the vendored plans document byte for byte
    And the stored snapshot records plan "metered", path "/evaluations", and method "post"

  Scenario: A revised vendored plan becomes a new revision without repricing pinned runs
    Given a generation run pinned to the evaluator's "metered" plan at 0.01 USD per request
    When a revised plan at 0.02 USD per request is vendored with a later effective date
    Then the pinned run still prices one request at 1 minor unit
    And a new run after the effective date prices one request at 2 minor units

  Scenario: A plan with an included quota is refused at start-up
    Given a vendored plan "pro" including 20 requests per second with overage at 0.01 USD per request
    When the pricing catalogue loads
    Then loading fails naming the card, plan "pro", metric "requests", and an included quota

  Scenario: A draft 1.0 SLA4OAI document is refused at start-up
    Given a vendored SLA4OAI 1.0.0 draft document
    When the pricing catalogue loads
    Then loading fails naming the card and the unsupported draft dialect

  Scenario: The discovery tool vendors a plan through a relative info.x-sla
    Given an evaluator serving an OpenAPI document whose info.x-sla is "./sla/plans.yaml"
    When the operator runs the discovery tool for plan "metered"
    Then a card and the plans document are written under the output directory
    And the written card loads and prices one request at 1 minor unit

  Scenario: The discovery tool refuses an x-sla reference to another origin
    Given an evaluator whose OpenAPI document points info.x-sla at a second server
    When the operator runs the discovery tool without allowing that origin
    Then the tool fails naming the refused origin
    And the second server receives no request
    And running the tool again with that origin allowed sends it exactly one request
```

The arithmetic is checked: 0.01 USD per request is `MeteredRate(1, 1)`, so one
request costs 1 minor unit, and 0.02 USD gives 2. The Vidai Mock usage costs 53
minor units under the same card as the existing
`tests/features/pricing_snapshots.feature` scenario.

Acceptance: `make test` runs the eight scenarios green; Markdown gates pass;
`docs/roadmap.md` shows `- [x] 2.5.2.`.

## Milestones and plateaus

- EP-M1 ends with a behaviour-preserving extraction.
- EP-M2 ends with vendored plans priced end to end, refusing everything
  outside a narrow subset.
- EP-M3 ends with specific refusals and the property evidence.
- EP-M4 ends with start-up archival.
- EP-M5 ends with the discovery tool.
- EP-M6 ends with behavioural evidence, documentation, and the roadmap tick.

No milestone adds compatibility machinery. The retired handwritten card form
gets a clear error, not a parallel reader (D9), and every caller of a changed
internal signature changes in the same commit.

## Concrete steps

Run from the repository root (any checkout of this branch):

```bash
git branch --show-current
# 2-5-2-pricing-catalogue-port-for-pricing-source-discovery
BR=$(git branch --show-current)
export UV_PYTHON=3.14
make fmt 2>&1 | tee /tmp/fmt-episodic-$BR.out
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-$BR.out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-$BR.out
make lint 2>&1 | tee /tmp/lint-episodic-$BR.out
make test 2>&1 | tee /tmp/test-episodic-$BR.out
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-$BR.out
make nixie 2>&1 | tee /tmp/nixie-episodic-$BR.out
```

Run gates sequentially, never in parallel. `UV_PYTHON=3.14` stops `make` from
recreating `.venv` on a newer free-threaded interpreter, where `psycopg-binary`
has no wheel (observed during planning). Local `make test` needs `vidaimock`
0.2.8 or later on `PATH` (CI pins 0.3.1). Timeouts above 180 seconds in pytest
are usually host contention; re-run the affected suite alone before believing
them.

Focused red-green loops, for example:

```bash
uv run pytest tests/test_cost_sla4oai_card.py -q
# red:   ImportError, or 1 xfailed (strict) before the module exists
# green: N passed
```

## Validation and acceptance

The item is accepted when all of the following hold:

1. `make check-fmt`, `make typecheck`, `make lint`, and `make test` pass on the
   final commit, and `make markdownlint` and `make nixie` pass.
2. The eight scenarios in `tests/features/pricing_source_discovery.feature`
   pass, including the Vidai Mock-backed completion.
3. The discovery tool's loopback tests pass over real sockets.
4. Existing suites pass unchanged except the test rewritten under D9 and the
   lifespan-ordering test updated under OB-6, and
   `git diff d0bdabe3 -- tests/__snapshots__/test_cost_pricing_snapshot_hash.ambr`
   prints nothing.
5. `resolve` performs no input/output: a test resolving through a catalogue
   whose card directory has been deleted after construction still succeeds.
6. Size counts are within `Tolerances` and recorded in
   `Outcomes & retrospective`.

## Idempotence and recovery

Every step is a commit; reverting a commit restores the previous plateau. No
migration is added. Archival is idempotent by content hash, so repeated
start-ups write nothing new. The discovery tool never overwrites a file and
writes through temporary files and a rename, so an interrupted run leaves at
most a stray temporary file. If a gate run is interrupted, re-run it; gates do
not mutate tracked files except `make fmt` and `make spelling` (commit a
regenerated `typos.toml` separately if it changes for unrelated reasons).

## Artefacts and notes

Research-dialect metered plan, the shape this item prices (fixture
`tests/fixtures/sla4oai/metered-plans.yaml`, abridged):

```yaml
context:
  id: pedante-service-plans
  version: "0.10"
  api: https://pedante.internal.example/openapi.json
  type: plans
pricing:
  currency: USD
plans:
  metered:
    quotas:
      /evaluations:
        post:
          requests:
            - max: 0
              cost:
                overage:
                  overage: 1
                  cost: 0.01
```

The fixture sets a global `pricing.currency` and gives plan `metered` no
`pricing` object of its own, so D5's field-wise ambiguity rule does not apply.

Research specification example that this item refuses (an included quota with a
sub-cent overage and a flat fee):

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

Sources: <https://sla4oai.specs.governify.io/Specification.html>,
<https://github.com/isa-group/SLA4OAI-Specification/blob/main/versions/1.0.0-Draft.md>,
and RFC 3986 §5.1.3 (the base URI is the retrieval URI after redirects).

## Interfaces and dependencies

Domain (`episodic/cost/pricing_amounts.py`):

```python
MINOR_UNIT_EXPONENTS: cabc.Mapping[str, int]


def decimal_fraction(amount: decimal.Decimal) -> tuple[int, int]: ...


def major_amount_rate(
    amount: decimal.Decimal, per_units: int, unit: UsageUnit, currency: str
) -> MeteredRate: ...
```

Domain (`episodic/cost/sla4oai_pricing.py`):

```python
@dc.dataclass(frozen=True, slots=True)
class PlanBinding:
    plan: str
    path: str
    method: str


def effective_plan_terms(
    document: Sla4OaiDocument, binding: PlanBinding
) -> PlanTerms: ...


def plan_rates(
    terms: PlanTerms,
) -> tuple[CurrencyCode, cabc.Mapping[str, MeteredRate]]: ...
```

Application (`episodic/cost/pricing_archive.py`):

```python
async def archive_pricing_snapshots(
    snapshots: cabc.Iterable[PricingSnapshot],
    open_unit_of_work: cabc.Callable[[], CanonicalUnitOfWork],
    *,
    metrics: MetricsPort,
) -> None: ...
```

Adapter (`episodic/cost/pricing_catalogue/file_loader.py`, added query):

```python
def loaded_snapshots(self) -> tuple[PricingSnapshot, ...]: ...
```

Inbound adapter (`episodic/api/app.py` and `episodic/api/dependencies.py`):
`ApiDependencies.startup_hooks`, a validated tuple of async callables run in
order by `_StartupHooksMiddleware.process_startup`. The archival start-up hook
only launches a bounded background task; a matching shutdown hook cancels it
before `engine.dispose`.

`PricingCataloguePort`, `PricingSnapshotRepository`, `CostRecorder`, and
`PricingEngine` are unchanged.

Dependencies: `pyyaml` moves from the `dev` group to runtime dependencies.
`httpx` and `cyclopts` (already runtime dependencies) are used by the discovery
tool. No other change. Hecate: register `episodic.cost.pricing_amounts`,
`episodic.cost.sla4oai_document`, `episodic.cost.sla4oai_parsing`, and
`episodic.cost.sla4oai_pricing` in `domain_ports`, and
`episodic.cost.pricing_archive` in `application`. The new adapter modules fall
under the existing `episodic.cost.pricing_catalogue` prefix. The exact names of
the unit-of-work and metrics protocols in the archival signature follow what
`episodic.canonical.unit_of_work_protocols` and `episodic.metrics_ports` export
at implementation time.

## Revision note

- 2026-11-22 (first draft, commit `27555eb7`): runtime discovery design with a
  discovering catalogue, an HTTP fetcher in the service, first-seen
  deduplication, revision listing, and an index migration.
- 2026-11-22 (this revision): applied an expert design review in which all
  four reviewers returned "Revise". The service no longer fetches anything:
  discovery moved to an operator-run tool that vendors plans (D1, D8), and
  ingestion happens at start-up from vendored documents (D2). Removed
  `PricingSourcePort`, `DiscoveringPricingCatalogue`, `list_revisions`, the
  index migration, and three settings. Added start-up archival (D7), strict
  decoders (D6), a fail-closed priced subset including the sub-cent rule (D4),
  research-dialect-only ingestion (D5), the retirement of the handwritten card
  form (D9), and an honest use of Vidai Mock (D10). Tolerances shrank, and
  milestones became vertical slices so the Skylos gate passes at every plateau.
- 2026-11-22 (closing review): a fifth reviewer confirmed the rewrite and
  returned "Proceed with conditions". Applied: archival runs as a bounded
  background task launched from a start-up hook and cancelled on shutdown,
  built only where an LLM is configured (D7); SLA4OAI pricing is limited to the
  `requests` metric, so per-call truncation cannot lose money, and
  `required_unit_for` is dropped (D4); domain errors carry no file path and the
  card loader re-raises them (D4); `AmountRangeError` keeps rate-card messages
  byte-identical (EP-M1); the discovery tool validates the whole staged
  directory and records its scripting-standards deviation (D8); the file budget
  rose to 65 and EP-M2's line budget to 2,200 after a recount; behavioural
  steps reuse the existing global definitions; documentation obligations gained
  the start-up hook and archival behaviour. Remaining work: user approval
  (including D1 and the follow-up item), then EP-M1.
