# Instrument cost accounting with per-call usage metering

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`,
and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: COMPLETE

## Purpose / big picture

Roadmap item `2.4.4` makes every Large Language Model (LLM) call inside the
Episodic generation orchestrator auditable and priceable. After this change,
each provider call placed by a LangGraph node (planner, show-notes executor,
guest-bios executor, and the LLM-backed evaluator nodes Pedante, Bromide,
Chiltern, Anthem, and Caesura) records a hierarchical ledger entry that names
the model used, the normalised token usage, the pinned pricing snapshot, and
the computed cost in integer minor currency units. A maintainer can resume any
historical generation run, list its ledger entries, and explain the bill in
full without consulting provider dashboards.

Plain-language glossary for terms used throughout:

- **Usage metering** records how much of each priced metric (input tokens,
  output tokens, cached input tokens, reasoning tokens, …) a provider reported
  for one call.
- **Pricing snapshot** is an immutable copy of a provider's rate card or an
  SLA4OAI plan document, content-hashed and pinned by a `pricing_snapshot_id`
  so historical bills stay reproducible. SLA4OAI is the "Service Level
  Agreements for OpenAPI" extension defined at
  [`isa-group/SLA4OAI-Specification`](https://github.com/isa-group/SLA4OAI-Specification);
  the initial implementation uses provider rate cards, not SLA4OAI.
- **Pricing engine** is the deterministic function
  `(snapshot, usage, operation, billing_period) → priced cost in minor units`.
- **Ledger entry** is a row in `cost_ledger_entries` with a `scope`
  (`task | provider_call | internal_estimate | fixed_allocation`), an
  idempotency key, and the cost roll-up.
- **Idempotency key** is the workflow-scoped string that prevents retries from
  inserting duplicate ledger rows.

Success is observable in these behaviours:

1. A maintainer can run the structured generation orchestration end-to-end
   against the Vidai Mock provider, then query `cost_ledger_entries` and see a
   `task` roll-up entry whose `computed_cost_minor` equals the sum of the child
   `provider_call` rows, each pinned to a known `pricing_snapshot_id`.
2. Retrying the same workflow step (same `workflow_run_id`, `node_name`,
   `retry_attempt`) does not produce a duplicate ledger row; the unique
   `idempotency_key` index causes `record_call` to return the existing row.
3. Pedante's evaluator call appears as a `provider_call` ledger row attributed
   to its underlying LLM model, with `workflow_node = "pedante"`, not as an
   opaque evaluator-specific charge.
4. `make check-fmt`, `make typecheck`, `make lint` (including
   `make check-architecture`), and `make test` all succeed after each milestone.
5. Hecate enforces that `episodic.cost.ports` and `episodic.cost.engine` live
   in the `domain_ports` group and that adapters in `episodic.cost.storage` and
   `episodic.cost.pricing_catalogue` live in `outbound_adapter`. The recorder
   collaborator in `episodic.cost.recorder` and the existing
   `episodic.orchestration` package are pinned to `application`.
6. A behavioural scenario expressed with `pytest-bdd` (this repository's
   Python equivalent of `rstest-bdd`) demonstrates an operator triggering a
   structured generation run and observing both the planner ledger entry and
   the show-notes executor ledger entry, totalled into a task roll-up.
7. The roadmap entry `2.4.4` in `docs/roadmap.md` is checked off only after
   implementation, documentation, validation, the CodeRabbit review pass, and
   the commit gate all succeed.

## Constraints

These invariants must hold throughout implementation; violation requires
escalation, not workarounds.

- The domain `LLMUsage` value object in `episodic/llm/ports.py` remains a
  three-field record (`input_tokens`, `output_tokens`, `total_tokens`).
  Provider-specific details (cached tokens, reasoning tokens, audio tokens,
  cache writes) MUST be normalised into a separate
  `ProviderCallUsage.usage_metrics: Mapping[str, int]` envelope rather than
  added as optional fields on `LLMUsage`.
- `episodic.cost.ports` and `episodic.cost.engine` MUST NOT import
  SQLAlchemy, Falcon, Celery, LangGraph, `httpx`, or any provider Software
  Development Kit (SDK). Hecate enforcement covers this; the plan adds the
  prefixes to `[tool.hecate]` in `pyproject.toml`.
- `PricingEngine` MUST be pure: no I/O, no clock reads, no catalogue
  fetches. The caller resolves a `PricingSnapshot` and passes it in.
- `episodic.orchestration` MUST be pinned to the Hecate `application` group
  before any cost recorder code calls into it. Adding the group is part of
  Milestone B.
- Currency values cross port boundaries as integer minor units only. No
  `float`, no `Decimal` over the wire. `CurrencyCode` is a validated newtype
  wrapping an ISO 4217 three-letter code.
- Budget enforcement (reserve → commit → release semantics for `BudgetPort`)
  is out of scope for this slice. A later roadmap item owns it. This plan may
  only leave clean seams.
- Service-oriented SLA4OAI fetching is out of scope; the pricing catalogue
  loads pinned provider rate cards from on-disk YAML in this slice. The port
  shape MUST accommodate the future SLA4OAI variant without further port churn
  (`PricingSnapshot.source_kind` distinguishes `provider_rate_card` from
  `sla4oai_plan`).
- TTS cost tracking is out of scope. The ledger schema reserves
  `provider_type = "tts"` for a later slice but only `provider_type = "llm"` and
  `provider_type = "internal"` are exercised here.
- Documentation MUST use British English with Oxford spelling, as defined by
  the `en-gb-oxendict` skill and `docs/documentation-style-guide.md`.
- The existing `_sum_usage` helper in `episodic/orchestration/_usage.py`
  remains the authoritative way to roll `LLMUsage` totals into the
  orchestration result DTO. The cost ledger pipeline runs alongside it, not in
  place of it.

## Tolerances (exception triggers)

- **Scope:** if implementation requires changes to more than 25 production
  files or 1800 net lines of code (test files excluded), stop and escalate.
- **Interface:** if `LLMPort.generate`, `LLMRequest`, or the public
  `LLMUsage` field set must change to ship this slice, stop and escalate.
- **Dependencies:** if any new external runtime dependency is required
  beyond what `pyproject.toml` already declares, stop and escalate. Adding
  test-only fixtures behind the existing dev-dependency group is allowed.
- **Hecate:** if any new Hecate group is needed beyond extending the
  existing `domain_ports`, `application`, `outbound_adapter`, and
  `composition_root` prefix lists, stop and escalate.
- **Migrations:** if more than two Alembic revisions are needed for the
  ledger, snapshot, counter, and run-pin tables, stop and escalate. The initial
  expectation is one revision.
- **Iterations:** if `make test` still fails after three consecutive
  good-faith fix attempts on the same milestone, stop and escalate.
- **Time:** if any milestone takes more than six working hours of agent
  time without observable progress, stop and escalate.
- **Ambiguity:** if multiple valid interpretations exist and the choice
  materially affects ledger correctness, idempotency, or auditability, stop and
  present options.

## Risks

Each risk records severity, likelihood, and mitigation.

- Risk: provider streaming responses omit `usage` from intermediate chunks,
  so the adapter records partial or zero usage on the ledger. Severity: high.
  Likelihood: medium. Mitigation: the OpenAI-compatible adapter MUST request
  usage on streams (`stream_options.include_usage = true` on Chat Completions;
  the `response.completed` terminal event on the Responses API) and emit
  `ProviderCallUsage` exactly once at stream completion. The ledger entry
  carries a `usage_complete: bool` flag; incomplete calls block task roll-up
  unless an explicit `force_finalize` flag is set.

- Risk: duplicate ledger rows on retry inflate bills.
  Severity: high. Likelihood: medium. Mitigation: a unique index on
  `cost_ledger_entries.idempotency_key` combined with
  `INSERT … ON CONFLICT DO NOTHING RETURNING id` and a follow-up
  `SELECT … WHERE idempotency_key = …` on conflict. The recorder computes keys
  from `(workflow_run_id, node_name, retry_attempt, logical_call_id)`; see
  Decision Log entry on retry-attempt inclusion.

- Risk: pricing snapshot drift across a long-running suspended workflow
  changes the bill mid-run. Severity: medium. Likelihood: medium. Mitigation:
  pin `(provider_name, billing_period_key) → pricing_snapshot_id` on the new
  `run_pricing_pins` side table at run start. Every `record_call` reads from
  the pin; the catalogue is consulted only on cache miss.

- Risk: clock skew on billing period boundaries causes the same workflow
  to span two billing periods inside one run. Severity: low. Likelihood: low.
  Mitigation: `billing_period_key` derives from the run-start timestamp
  obtained from an injected `Clock` port; subsequent calls inherit the run's
  period. The `Clock` port already exists as the `MonotonicClockPort` /
  `wallclock` collaborators used by the workflow checkpoint store, so no new
  port is introduced.

- Risk: providers return no `usage` field (older or self-hosted endpoints),
  leaving the ledger blank or crashing. Severity: medium. Likelihood: low.
  Mitigation: the adapter falls back to the deterministic tokenizer-style
  estimate already used for pre-flight budget validation
  (`_estimate_token_count` in `episodic/llm/openai_adapter.py`). The ledger
  entry records `usage_source = "estimated"` so reports can warn.

- Risk: concurrent evaluator branches contend on `cost_ledger_entries`
  inserts under high fan-out. Severity: low. Likelihood: low. Mitigation: the
  table is append-only with a unique index on `idempotency_key`; task roll-ups
  are computed once at run completion via a single `record_task_rollup` insert.
  No denormalised parent row is maintained, so there is no hot row.

- Risk: cached input tokens (OpenAI `prompt_tokens_details.cached_tokens`,
  Anthropic `cache_read_input_tokens`) are silently dropped by the adapter
  normalisation, producing incorrect cost. Severity: medium. Likelihood:
  medium. Mitigation: the canonical usage vocabulary is documented in the
  design doc and enforced by adapter normalisation; tests assert that an OpenAI
  response with `cached_tokens` populates
  `usage_metrics["cached_input_tokens"]` and that the pricing engine applies a
  separate rate to that metric when the snapshot includes it.

- Risk: writing the ledger inside the LangGraph node breaks the hexagonal
  layering by giving graph code a direct cost-port dependency. Severity:
  medium. Likelihood: high without mitigation. Mitigation: the `CostRecorder`
  collaborator lives in `episodic.cost.recorder` (application layer) and is
  injected into the orchestrator at the composition root. The LangGraph nodes
  call into the orchestrator's existing collaborator interface, not into
  `CostLedgerPort` directly.

## Progress

Update this list with every stopping point. Add timestamps.

- [x] Milestone A — research and design alignment (no code changes beyond
  this ExecPlan). Completed 2026-06-04: user approval to proceed moved this
  plan into execution, ADR-015 was drafted in Proposed status, and the system
  design now documents provider-rate-card pricing snapshots plus
  `run_pricing_pins`.
- [x] Milestone B — domain DTOs, ports, and pricing engine, plus Hecate
  group extensions and the first ADR draft. Completed 2026-06-04: added
  `episodic.cost` ports, `PricingEngine`, `CostRecorder`, Hecate group
  extensions, `ProviderCallUsage`, and focused Stage B tests. The focused tests
  first failed with `ModuleNotFoundError: No module named 'episodic.cost'`,
  then passed after implementation. CodeRabbit's Stage B follow-up completed
  with zero findings.
- [x] Milestone C — concrete adapters: SQLAlchemy ledger and metering
  counters, file-backed pricing catalogue loader, OpenAI adapter enhancement to
  populate `ProviderCallUsage`. Completed 2026-06-04: added storage, metering,
  catalogue, and OpenAI usage tests; implemented the cost storage models and
  adapters, file-backed catalogue, bundled sample pricing snapshots, OpenAI
  usage metadata normalization, and the cost-accounting Alembic revision pulled
  forward from Stage E. Deterministic gates and CodeRabbit passed with zero
  findings before commit.
- [x] Milestone D — orchestrator integration: `CostRecorder` collaborator,
  LangGraph wiring through the orchestrator's existing finish path, run pricing
  pins, and the structured-planning behavioural scenario. Completed
  2026-06-04: added provider-call usage propagation through planner/action
  DTOs, optional cost-recorder wiring for the structured orchestrator and
  LangGraph direct finish path, ledger pin/aggregate adapter methods, exact
  pinned-snapshot retrieval, and focused orchestrator, graph, storage,
  recorder, and BDD tests. All reported CodeRabbit concerns were cleared; the
  final follow-up emitted no findings but did not print the usual terminal
  `complete` JSON line.
- [x] Milestone E — Alembic migration, py-pglite-backed integration tests,
  documentation updates, CodeRabbit review, roadmap tick. Completed
  2026-06-04: the migration and py-pglite tests were completed in earlier
  milestones to satisfy migration gates; Stage E accepted ADR-015, updated
  operator and maintainer documentation, recorded the system-design
  cross-reference, ticked roadmap item `2.4.4`, passed the final gates, and
  completed the final CodeRabbit review with zero findings.

## Surprises & discoveries

Document unexpected findings here as they occur. Each entry should record the
observation, evidence, and impact.

(none yet)

- Observation: the design document already described `PricingCataloguePort`,
  `CostLedgerPort`, `MeteringPort`, and immutable `pricing_snapshots`, but it
  did not name the `run_pricing_pins` table that prevents rate-card drift
  during a suspended workflow. Evidence:
  `docs/episodic-podcast-generation-system-design.md` sections "Orchestration
  ports and adapters", "Cost accounting and budget enforcement", and the
  data-model bullets. Impact: Stage A added `run_pricing_pins` to the design
  document before production implementation so the data model and ADR align.

- Observation: CodeRabbit Stage A review found four minor Oxford spelling
  issues in ADR-015: three headings using "Normalised metrics" and one
  "normalisation" instance. Evidence: `coderabbit review --agent` completed on
  2026-06-04 with four minor findings, all in
  `docs/adr/adr-015-cost-accounting-ports-and-pricing-engine.md`. Impact: the
  ADR now uses Oxford-preferred `-ize` spelling: "Normalized metrics" and
  "normalization".

- Observation: the follow-up CodeRabbit review reported ADR-015 hard-wrap
  concerns in sections that were already wrapped by the current formatted
  working tree, plus one long footnote anchor path. Evidence: local
  `awk 'length($0) > 80'` output showed only the design-document footnote path
  exceeded 80 columns. Impact: the footnote now names the design section in
  prose and links the document path without the long anchor.

- Observation: the third CodeRabbit Stage A review completed with zero
  findings. Evidence:
  `/tmp/coderabbit-stage-a-third-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  ended with `{"type":"complete","status":"review_completed","findings":0}`.
  Impact: Stage A is ready to commit.

- Observation: Stage B focused tests reached the intended red state before
  implementation. Evidence:
  `/tmp/test-stage-b-red-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  showed `ModuleNotFoundError: No module named 'episodic.cost'` for the new
  pricing-engine and port-contract tests. Impact: the tests proved the new
  package and API surface were absent before implementation.

- Observation: Stage B focused tests passed after implementation. Evidence:
  `/tmp/test-stage-b-focused-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  ended with `9 passed in 0.55s`. Impact: the new pricing engine properties,
  cost-port protocol conformance, and optional
  `LLMResponse.provider_call_usage` compatibility are covered before the full
  gates run.

- Observation: Stage B local gates passed before CodeRabbit review. Evidence:
  `/tmp/check-fmt-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `355 files already formatted`;
  `/tmp/typecheck-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `All checks passed!`;
  `/tmp/lint-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  Hecate passed, Ruff passed, and Pylint rated the code `10.00/10`;
  `/tmp/test-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `815 passed, 1 skipped`;
  `/tmp/markdownlint-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `Summary: 0 error(s)`; and
  `/tmp/nixie-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  all diagrams validated. Impact: deterministic gates are clear before
  requesting CodeRabbit.

- Observation: the first Stage B CodeRabbit review found 14 concerns: three
  major findings for broad file-level Pylint disables and 11 trivial findings
  for terse module or public-method docstrings. Evidence:
  `/tmp/coderabbit-stage-b-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  ended with `{"type":"complete","status":"review_completed","findings":14}`.
  Impact: the implementation now uses narrow inline suppressions only where
  protocol-shaped signatures require them, and the cost package, pricing
  engine, ports, and recorder expose fuller NumPy-style documentation.

- Observation: Stage B deterministic gates passed again after the CodeRabbit
  fixes. Evidence:
  `/tmp/check-fmt-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `355 files already formatted`;
  `/tmp/typecheck-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `All checks passed!`;
  `/tmp/lint-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  Hecate passed, Ruff passed, and Pylint rated the code `10.00/10`; and
  `/tmp/test-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `815 passed, 1 skipped in 395.98s`. Impact: the Python gates remain clear
  before the Stage B CodeRabbit follow-up review.

- Observation: Stage B documentation gates and CodeRabbit follow-up passed
  after the plan update and documentation fixes. Evidence:
  `/tmp/markdownlint-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `Summary: 0 error(s)`;
  `/tmp/nixie-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  all diagrams validated; and
  `/tmp/coderabbit-stage-b-rerun-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  ended with `{"type":"complete","status":"review_completed","findings":0}`.
  Impact: Stage B is ready for an atomic commit.

- Observation: the repository's migration drift checker compares the full
  Alembic-applied database schema against `Base.metadata`. Evidence:
  `episodic/canonical/storage/migration_check.py` calls
  `compare_metadata(ctx, Base.metadata)`, and Alembic's environment imports the
  same metadata from `episodic.canonical.storage`. Impact: Stage C must add the
  cost-accounting Alembic revision alongside the ORM models rather than waiting
  until Stage E, otherwise `make check-migrations` cannot pass before the Stage
  C CodeRabbit review.

- Observation: Stage C focused tests reached the intended red state before
  implementation. Evidence:
  `/tmp/test-stage-c-red-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  showed `ModuleNotFoundError` for `episodic.cost.storage` and
  `episodic.cost.pricing_catalogue`. Impact: the storage and catalogue adapters
  were absent before implementation.

- Observation: Stage C focused tests passed after implementation. Evidence:
  `/tmp/test-stage-c-focused-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  ended with `11 passed in 12.76s`. Impact: the new SQLAlchemy ledger,
  metering counters, file pricing catalogue, and OpenAI provider-call usage
  normalization are covered before the full gate sequence.

- Observation: Stage C added the cost-accounting Alembic revision, SQLAlchemy
  models, and PostgreSQL adapters in the same milestone so migration drift
  stays visible to `make check-migrations`. Evidence:
  `/tmp/migrations-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  applied revision `20260601_000009` and completed the metadata comparison
  without drift. Impact: future cost schema changes must update both the
  storage models and Alembic migration chain before CodeRabbit review.

- Observation: Stage C's metering idempotency path must insert the audit event
  before incrementing the counter. Evidence: CodeRabbit identified the previous
  counter-first shape as a race where a crash between the counter update and
  event insert could double-count replayed idempotency keys. Impact:
  `SqlAlchemyMeteringCounterStore.consume` now wins or loses the idempotency
  event insert first; only the winner increments the counter, and duplicate
  callers return the existing event total.

- Observation: Stage C deterministic gates and CodeRabbit review passed after
  the storage race and schema-review findings were resolved. Evidence:
  `/tmp/check-fmt-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `366 files already formatted`;
  `/tmp/typecheck-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `All checks passed!`;
  `/tmp/lint-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  Hecate passed, Ruff passed, and Pylint rated the code `10.00/10`;
  `/tmp/test-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `826 passed, 1 skipped in 441.76s`;
  `/tmp/markdownlint-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `Summary: 0 error(s)`;
  `/tmp/nixie-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  all diagrams validated; and
  `/tmp/coderabbit-stage-c-retry6-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  ended with `{"type":"complete","status":"review_completed","findings":0}`.
  Impact: Stage C is ready for an atomic commit, and Stage D can rely on the
  cost-storage ports being backed by tested adapters.

- Observation: Stage D exposed that `run_pricing_pins` keyed only by
  `(workflow_run_id, provider_name, billing_period_key)` cannot safely pin a
  run that uses two models from the same provider. Evidence: the orchestrator
  pins both the planning model and execution model for a structured run, and
  both are currently OpenAI models with distinct pricing snapshots. Impact: the
  Stage C schema and storage adapter now key pins by
  `(workflow_run_id, provider_name, model, operation, billing_period_key)`.

- Observation: Stage D focused tests passed after the orchestrator, LangGraph,
  recorder, and pin-key changes. Evidence:
  `/tmp/test-stage-d-focused-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  ended with `8 passed in 11.26s`. Impact: the direct structured orchestrator,
  direct LangGraph finish path, ledger run-pin storage, and provider-call
  aggregate read are covered before full gates and CodeRabbit.

- Observation: Stage D deterministic gates passed after refreshing the affected
  orchestration snapshots. Evidence:
  `/tmp/check-fmt-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `367 files already formatted`;
  `/tmp/typecheck-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `All checks passed!`;
  `/tmp/lint-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  Hecate passed, Ruff passed, and Pylint rated the code `10.00/10`;
  `/tmp/migrations-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  applies revision `20260601_000009` and completes metadata comparison;
  `/tmp/test-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `830 passed, 1 skipped in 427.21s`; and the documentation gates report
  Markdown lint with `Summary: 0 error(s)` and all diagrams validated. Impact:
  the Stage D diff is ready for CodeRabbit review.

- Observation: Stage D exposed a subtle pinning bug in `CostRecorder`: when a
  run already had a pricing pin, the recorder resolved the latest catalogue
  entry for the provider/model/operation tuple and only replaced the snapshot
  identifier if it differed. Evidence: local review of
  `episodic/cost/recorder.py` showed the pinned id was applied with
  `dataclasses.replace` after resolving the current catalogue row. Impact:
  `PricingCataloguePort` now exposes `get_snapshot(pricing_snapshot_id)`,
  `FilePricingCatalogue` retrieves exact immutable snapshots by id, and
  `tests/test_cost_recorder.py` verifies that a pinned old snapshot's rates are
  used after catalogue drift.

- Observation: the structured generation BDD story now exercises the Stage D
  cost-recorder integration. Evidence:
  `/tmp/test-bdd-cost-ledger-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  ended with `2 passed in 0.58s` after adding the feature step that observes
  planner and show-notes provider-call entries plus the task roll-up
  finalization. Impact: the behavioural coverage required by this milestone is
  now present before the final deterministic gates and CodeRabbit review.

- Observation: the first Stage D CodeRabbit review found one trivial test-fake
  clarity issue. Evidence:
  `/tmp/coderabbit-stage-d-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  ended with `{"type":"complete","status":"review_completed","findings":1}`
  and identified an empty async `pin_run_pricing` stub in
  `tests/test_generation_orchestration_langgraph_costs.py`. Impact: the fake
  now has an explicit no-op assignment so the stub is visibly intentional.

- Observation: Stage D deterministic gates passed again after the CodeRabbit
  test-fake fix. Evidence:
  `/tmp/check-fmt-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `368 files already formatted`;
  `/tmp/typecheck-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `All checks passed!`;
  `/tmp/lint-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  Hecate passed, Ruff passed, and Pylint rated the code `10.00/10`;
  `/tmp/test-langgraph-costs-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `1 passed in 0.11s`; and
  `/tmp/test-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `832 passed, 1 skipped in 416.48s`. Impact: the Stage D diff is ready for a
  CodeRabbit follow-up review.

- Observation: the Stage D CodeRabbit follow-up review found one more trivial
  test-maintenance issue. Evidence:
  `/tmp/coderabbit-stage-d-rerun2-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  ended with `{"type":"complete","status":"review_completed","findings":1}`
  and asked for the graph cost test to derive its expected total from fixture
  helpers instead of hardcoding `38`. Impact: the test now narrows the
  fixture usage values and computes the expected total from the planner and
  action fixture DTOs.

- Observation: Stage D deterministic gates passed after the fixture-derived
  expected total change. Evidence:
  `/tmp/check-fmt-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `368 files already formatted`;
  `/tmp/typecheck-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `All checks passed!`;
  `/tmp/lint-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  Hecate passed, Ruff passed, and Pylint rated the code `10.00/10`;
  `/tmp/test-langgraph-costs-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `1 passed in 0.11s`; and
  `/tmp/test-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `832 passed, 1 skipped in 413.55s`. Impact: the Stage D diff is ready for
  another CodeRabbit follow-up review.

- Observation: the next Stage D CodeRabbit review found three test
  maintainability concerns: a helper docstring in
  `tests/test_cost_recorder.py`, assertion messages in
  `tests/test_cost_recorder.py`, and assertion messages in
  `tests/test_generation_orchestration_langgraph_costs.py`. Evidence:
  `/tmp/coderabbit-stage-d-rerun4-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  ended with `{"type":"complete","status":"review_completed","findings":3}`.
  Impact: the helper now uses a Numpy-style docstring, and the affected tests
  now explain their expected conditions on failure.

- Observation: Stage D deterministic gates passed after the CodeRabbit
  assertion-message and docstring fixes. Evidence:
  `/tmp/test-stage-d-coderabbit-fixes-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `2 passed in 0.12s`;
  `/tmp/check-fmt-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `368 files already formatted`;
  `/tmp/typecheck-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `All checks passed!`;
  `/tmp/lint-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  Hecate passed, Ruff passed, and Pylint rated the code `10.00/10`;
  `/tmp/migrations-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  completed successfully through Alembic revision `20260601_000009`;
  `/tmp/test-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `832 passed, 1 skipped in 410.54s`;
  `/tmp/markdownlint-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `Summary: 0 error(s)`; and
  `/tmp/nixie-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `All diagrams validated successfully!`. Impact: all deterministic Stage D
  gates passed before the final CodeRabbit follow-up.

- Observation: the final Stage D CodeRabbit follow-up emitted no findings but
  did not include the usual terminal completion object. Evidence:
  `/tmp/coderabbit-stage-d-rerun5-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  contains `review_context`, setup, `summarizing`, and `tools_completed`
  events, with no `finding` events, and the command exited successfully via the
  shell pipeline. Impact: all reported CodeRabbit concerns are cleared, but the
  review evidence is weaker than prior milestones because the tool omitted the
  final `{"type":"complete", ...}` summary.

- Observation: Stage E did not need another Alembic revision. Evidence: the
  cost-accounting migration was pulled forward into Stage C, updated in Stage D
  for the wider `run_pricing_pins` key, and `make check-migrations` passed
  after that schema correction. Impact: Stage E only needs documentation,
  roadmap closure, gates, and CodeRabbit validation.

- Observation: Stage E deterministic gates passed after the documentation and
  roadmap updates. Evidence:
  `/tmp/check-fmt-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `368 files already formatted`;
  `/tmp/typecheck-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `All checks passed!`;
  `/tmp/lint-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  Hecate passed, Ruff passed, and Pylint rated the code `10.00/10`;
  `/tmp/migrations-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  completed successfully through Alembic revision `20260601_000009`;
  `/tmp/test-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `832 passed, 1 skipped in 408.86s`;
  `/tmp/markdownlint-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  reports `Summary: 0 error(s)`; and
  `/tmp/nixie-episodic-2-4-4-cost-accounting-and-usage-metering.out` reports
  `All diagrams validated successfully!`. Impact: the final branch state is
  ready for the Stage E CodeRabbit review.

- Observation: the final Stage E CodeRabbit retry completed with zero findings
  after one prior Stage E run timed out after `tools_completed`. Evidence:
  `/tmp/coderabbit-stage-e-rerun-episodic-2-4-4-cost-accounting-and-usage-metering.out`
  ended with `{"type":"complete","status":"review_completed","findings":0}`.
  Impact: all CodeRabbit concerns reported during the work are cleared, and
  the final branch state has external-review coverage.

## Decision log

Record every significant decision with rationale and timestamp.

- Decision: extend `LLMResponse` with an optional
  `provider_call_usage: ProviderCallUsage | None` field rather than replacing
  `LLMUsage`. Rationale: `LLMUsage` is a stable three-field DTO consumed by
  `_sum_usage`, Pedante results, the orchestration result DTO, and property
  tests. Provider-specific details (cached tokens, reasoning tokens) belong in
  a separate envelope so the canonical aggregate stays arithmetically clean and
  the public port surface stays small. Wyvern review explicitly flagged
  shrinking `LLMUsage` as the most painful long-term lock-in. Date/Author:
  2026-05-29, plan author.

- Decision: include `retry_attempt` in the idempotency-key composition for
  `record_call`. Rationale: ledger entries should be queryable per attempt so a
  workflow's audit log explains every billable provider interaction, not only
  the successful outcome. Collapsing attempts would also hide retry-driven cost
  spikes. See risk on retry duplication for the uniqueness guarantee.
  Date/Author: 2026-05-29, plan author.

- Decision: introduce `run_pricing_pins` as its own table now rather than
  waiting for the `generation_runs` table from roadmap item `2.6.1`. Rationale:
  the run-pricing pin is the only sound mitigation for snapshot drift across a
  suspended workflow, and `2.4.4` cannot block on `2.6.1`. The pin's primary
  key is the workflow run identifier emitted by the orchestrator's
  `correlation_id`, so the table backfills cleanly when `GenerationRunPort`
  lands. Date/Author: 2026-05-29, plan author.

- Decision: ship `MeteringPort` as a port plus a stub adapter in this
  slice even though no caller consumes it yet. Rationale: defining the
  atomic-consumption contract now fixes the signature before `BudgetPort`
  lands. The stub adapter uses this Postgres shape:

  ```sql
  INSERT ...
  ON CONFLICT (counter_key, billing_period_key)
  DO UPDATE SET consumed = metering_counters.consumed + EXCLUDED.delta
  RETURNING consumed
  ```

  Its semantics are correct from day one. Wyvern review recommended the
  stub-now path. Date/Author: 2026-05-29, plan author.

- Decision: place `CostRecorder` in a new `episodic.cost.recorder` module
  pinned to the Hecate `application` group, not inside
  `episodic.orchestration`. Rationale: keeping the recorder out of
  orchestration prevents evaluator/orchestration code from depending on
  `CostLedgerPort` directly. The recorder collaborator is the only client of
  the cost ports, and the orchestrator depends on the recorder via an injected
  callable, not via concrete type. Date/Author: 2026-05-29, plan author.

- Decision: aggregate-on-read for task roll-ups during the run, and write
  a single `record_task_rollup` row at run completion. Rationale: maintaining a
  denormalised parent row creates a write-hot row under fan-out. The single
  final insert keeps the historical audit-trail row available without
  contention. The roll-up read query uses the `(generation_run_id, scope)`
  partial index. Date/Author: 2026-05-29, plan author.

- Decision: usage is carried across ports as `Mapping[str, int]` keyed by
  a fixed canonical vocabulary: `input_tokens`, `output_tokens`,
  `cached_input_tokens`, `cache_write_tokens`, `reasoning_tokens`,
  `audio_input_tokens`, `audio_output_tokens`. Rationale: this vocabulary
  covers the OpenAI Chat Completions and Responses shapes and the Anthropic
  Messages shape per the research report. New metrics extend the vocabulary
  without changing port signatures. Date/Author: 2026-05-29, plan author.

- Decision: treat the user's 2026-06-04 request to proceed with this ExecPlan
  as explicit approval for the execution phase. Rationale: the `execplans`
  skill requires an approval gate between drafting and implementation. The user
  explicitly asked to proceed with the planned functionality and to keep this
  plan updated. Date/Author: 2026-06-04, implementing agent.

- Decision: constrain the Stage B additivity property test to rates that are
  exact minor units per token, represented as multiples of one million in
  `rates_minor_per_metric`. Rationale: the pricing engine stores integer minor
  units and provider rates are expressed per one million units. Independent
  integer division on arbitrary fractional minor-unit rates cannot be perfectly
  additive, so the property test uses exact rates to verify the algebraic
  invariant without smuggling in a rounding policy that belongs to catalogue
  design. Date/Author: 2026-06-04, implementing agent.

- Decision: pull the cost-accounting Alembic revision forward into Stage C.
  Rationale: the local gate requires `make check-migrations` after each
  milestone, and the migration drift checker treats newly imported ORM models
  without matching migrations as a hard failure. Stage E still owns final
  documentation, acceptance, and roadmap closure. Date/Author: 2026-06-04,
  implementing agent.

- Decision: make ledger parent references `ON DELETE SET NULL` and pricing
  snapshot references `ON DELETE RESTRICT`. Rationale: deleting a parent
  roll-up must not cascade away auditable provider-call entries, while deleting
  a pricing snapshot that priced historical entries or run pins would destroy
  the explanation for persisted costs. Date/Author: 2026-06-04, implementing
  agent.

- Decision: let a database trigger, not ORM-only state, own
  `metering_counters.updated_at` changes. Rationale: the counter is mutated by
  PostgreSQL upserts, so relying on ORM `onupdate` would leave timestamps stale
  on the hot path. Date/Author: 2026-06-04, implementing agent.

- Decision: defer foreign-key indexes for `parent_cost_entry_id` and
  `pricing_snapshot_id` until concrete lookup queries need them. Rationale:
  Stage C adds the run-level and partial roll-up indexes required by current
  reads; extra FK indexes would add write cost without a demonstrated query
  path. Date/Author: 2026-06-04, implementing agent.

- Decision: key `run_pricing_pins` by provider, model, operation, and billing
  period rather than provider and period alone. Rationale: one workflow can use
  a planning model and an execution model from the same provider, and their
  rate-card rows are model- and operation-specific. A provider-only pin would
  either overwrite one rate card or reuse the wrong snapshot for a later call.
  Date/Author: 2026-06-04, implementing agent.

## Outcomes & retrospective

Fill in at each milestone close and at completion.

- Stage A completed on 2026-06-04. The repository now has a proposed ADR for
  cost accounting ports and deterministic pricing, and the system design names
  the run-pricing pin table needed for reproducible suspended workflow bills.

- Stage B completed on 2026-06-04. The repository now has cost-accounting
  domain ports, immutable pricing value objects, a deterministic pricing
  engine, an application-level cost recorder, Hecate group coverage, focused
  tests, and an optional `LLMResponse.provider_call_usage` envelope that leaves
  `LLMUsage` unchanged.

- Stage C completed on 2026-06-04. The repository now has SQLAlchemy-backed
  cost ledger and metering adapters, file-backed pricing catalogue loading,
  sample provider rate-card snapshots, OpenAI usage normalization, and an
  Alembic revision validated against py-pglite.

- Stage D completed on 2026-06-04. Structured orchestration now carries
  provider-call usage through planner and action DTOs, optionally records costs
  through `CostRecorder`, pins run pricing by provider/model/operation, and
  writes task roll-ups after direct generation runs complete.

- Stage E completed on 2026-06-04. ADR-015 is accepted, the users' and
  developers' guides describe the implemented cost-accounting behaviour, the
  roadmap marks item `2.4.4` complete, all final gates passed, and the final
  CodeRabbit review completed with zero findings.

## Context and orientation

This plan touches the following areas of the repository. Read these before
making any change.

- `docs/roadmap.md` — the source of the roadmap item itself. Section 2.4 is
  "LangGraph orchestration and cost accounting" and the unchecked item is
  `2.4.4`.
- `docs/episodic-podcast-generation-system-design.md` — section "Cost
  accounting and budget enforcement" around line 1311, section "Orchestration
  ports and adapters" around line 769, the data-model bullets for
  `cost_ledger_entries`, `pricing_snapshots`, `metering_counters`,
  `budget_limits`, and `budget_usage` around line 1490, and the Quality
  Assurance Stack notes around line 327.
- `docs/cost-management-in-langgraph-agentic-systems.md` — supplementary
  background on token accounting, retries, anomaly handling, and feedback loops
  in LangGraph + Celery systems.
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` — the
  authoritative discussion of how orchestration code stays within the hexagonal
  layering. Pay attention to the rule that LangGraph nodes invoke ports, not
  adapters.
- `docs/adr/adr-014-hexagonal-architecture-enforcement.md` — explains how
  Hecate enforces the import direction. This slice extends the existing
  `[tool.hecate]` groups; it does not introduce new groups.
- `docs/developers-guide.md` — orchestration maintainer rules near line
  992 ("Keep model-tier selection in `GenerationOrchestrationConfig`; do not
  couple this slice to pricing-ledger or budget-reservation persistence"). That
  guidance flips when this plan lands: the ledger is now wired in.
- `docs/users-guide.md` — operator-facing documentation. The ledger
  surface and pricing-snapshot management are described here.

Existing code surfaces this plan integrates with:

- `episodic/llm/ports.py` defines `LLMRequest`, `LLMResponse`, `LLMUsage`,
  `LLMTokenBudget`, and `LLMPort`. This plan adds the optional
  `provider_call_usage` field to `LLMResponse` and a new `ProviderCallUsage`
  dataclass in `episodic/llm/ports.py`. The three-field public `LLMUsage` shape
  is unchanged.
- `episodic/llm/openai_adapter.py` is the only concrete `LLMPort`
  implementation today. It already normalises usage at the boundary; this plan
  extends the normalisation to populate `ProviderCallUsage` with the canonical
  metric vocabulary listed above.
- `episodic/orchestration/_usage.py` already sums `LLMUsage` across
  planner and action results into `GenerationOrchestrationResult.total_usage`.
  The recorder hooks into the orchestrator's finish path; `_sum_usage` stays
  the source of truth for the in-memory aggregate.
- `episodic/orchestration/_planning_orchestrator.py` and
  `episodic/orchestration/langgraph.py` are the orchestration seams; the
  recorder is injected at composition time (in `episodic/api/runtime.py` and
  `episodic/worker/runtime.py`).
- `episodic/canonical/storage/` is where SQLAlchemy lives. New cost
  adapters live in a sibling `episodic/cost/storage/` package so the canonical
  and cost storage modules stay separate.
- `pyproject.toml` `[tool.hecate]` already declares the
  `domain_ports`, `application`, `inbound_adapter`, `outbound_adapter`, and
  `composition_root` groups. This plan adds new prefixes inside the existing
  groups; it does not introduce new groups.
- `episodic/qa/pedante/__init__.py` is the first LLM-backed evaluator.
  Pedante already passes `LLMUsage` through its result DTO. This plan reuses
  the existing `LLMResponse.provider_call_usage` field to attach the
  evaluator-node ledger entry without changing the public Pedante contract.

Skills the implementer should load before each milestone:

- `hexagonal-architecture` — port and adapter discipline.
- `execplans` — formatting and revision rules for this living document.
- `testing-sqlalchemy-with-pytest-and-py-pglite` — integration test
  pattern for the SQLAlchemy ledger and metering counter adapters.
- `testing-async-falcon-endpoints` — only if an HTTP surface is added
  (this slice does not, but the recorder integration may touch the composition
  root in `episodic/api/runtime.py`).
- `vidai-mock` — behavioural test driver for orchestration scenarios.
- `en-gb-oxendict` — documentation language.
- `documentation-style-guide` — ADR and design-doc formatting.

## Plan of work

This work proceeds through five stages. Each stage ends with the gated
validation pass described in the "Validation and acceptance" section.

### Stage A — Research and design alignment (no code)

This stage publishes the design decisions captured in the Decision Log and
Constraints sections above, and updates the cost-accounting and orchestration
sections of `docs/episodic-podcast-generation-system-design.md` to reference
this plan and the new `run_pricing_pins` table. No production source changes.
The deliverable is this ExecPlan in `APPROVED` status and a stub
`docs/adr/adr-015-cost-accounting-ports-and-pricing-engine.md` in `Proposed`
status.

The author then drafts the canonical metric vocabulary and the
`PricingSnapshot.source_kind` discriminator in ADR-015, with explicit worked
examples for OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages
usage payloads.

### Stage B — Ports, DTOs, and pricing engine

This stage adds the domain types under a new `episodic/cost/` package and
extends the Hecate configuration.

1. Add `episodic/cost/__init__.py` and `episodic/cost/ports.py` containing
   the protocols, value objects, and exceptions:

   ```python
   # episodic/cost/ports.py
   import dataclasses as dc
   import enum
   import typing as typ

   class LedgerScope(enum.StrEnum):
       TASK = "task"
       PROVIDER_CALL = "provider_call"
       INTERNAL_ESTIMATE = "internal_estimate"
       FIXED_ALLOCATION = "fixed_allocation"

   class PricingModel(enum.StrEnum):
       PAYG = "payg"
       QUOTA_OVERAGE = "quota_overage"
       SUBSCRIPTION_ALLOCATED = "subscription_allocated"

   class PricingSourceKind(enum.StrEnum):
       PROVIDER_RATE_CARD = "provider_rate_card"
       SLA4OAI_PLAN = "sla4oai_plan"

   class UsageSource(enum.StrEnum):
       PROVIDER = "provider"
       ESTIMATED = "estimated"

   PricingSnapshotId = typ.NewType("PricingSnapshotId", str)
   CostLedgerEntryId = typ.NewType("CostLedgerEntryId", str)
   IdempotencyKey   = typ.NewType("IdempotencyKey", str)
   CurrencyCode     = typ.NewType("CurrencyCode", str)
   BillingPeriodKey = typ.NewType("BillingPeriodKey", str)
   MeteringCounterKey = typ.NewType("MeteringCounterKey", str)

   @dc.dataclass(frozen=True, slots=True)
   class PricingSnapshot:
       pricing_snapshot_id: PricingSnapshotId
       provider_name: str
       model: str
       operation: str
       source_kind: PricingSourceKind
       currency: CurrencyCode
       billing_period_key: BillingPeriodKey
       rates_minor_per_metric: typ.Mapping[str, int]  # minor units per 1M units of metric
       source_metadata: typ.Mapping[str, str]
       content_hash: str
       retrieved_at: str  # ISO 8601 UTC

   @dc.dataclass(frozen=True, slots=True)
   class PricedCall:
       computed_cost_minor: int
       currency: CurrencyCode
       is_estimated: bool

   @dc.dataclass(frozen=True, slots=True)
   class ProviderCallLedgerEntry:
       idempotency_key: IdempotencyKey
       parent_cost_entry_id: CostLedgerEntryId | None
       scope: LedgerScope
       provider_type: str               # "llm" | "internal" | "tts" (tts unused here)
       provider_name: str
       workflow_node: str
       operation: str
       pricing_snapshot_id: PricingSnapshotId
       usage: typ.Mapping[str, int]
       usage_source: UsageSource
       usage_complete: bool
       computed_cost_minor: int
       currency: CurrencyCode
       pricing_model: PricingModel
       retry_attempt: int
       billing_period_key: BillingPeriodKey
       workflow_run_id: str
       recorded_at: str                 # ISO 8601 UTC

   @dc.dataclass(frozen=True, slots=True)
   class TaskRollupLedgerEntry:
       idempotency_key: IdempotencyKey
       workflow_run_id: str
       workflow_node: str | None        # None for the run-level roll-up
       computed_cost_minor: int
       currency: CurrencyCode
       billing_period_key: BillingPeriodKey
       recorded_at: str

   @typ.runtime_checkable
   class CostLedgerPort(typ.Protocol):
       async def record_call(self, entry: ProviderCallLedgerEntry) -> CostLedgerEntryId: ...
       async def record_task_rollup(self, rollup: TaskRollupLedgerEntry) -> CostLedgerEntryId: ...

   @typ.runtime_checkable
   class PricingCataloguePort(typ.Protocol):
       async def resolve(
           self,
           provider_name: str,
           model: str,
           operation: str,
           billing_period_key: BillingPeriodKey,
       ) -> PricingSnapshot: ...

   @typ.runtime_checkable
   class MeteringPort(typ.Protocol):
       async def consume(
           self,
           counter_key: MeteringCounterKey,
           billing_period_key: BillingPeriodKey,
           delta: int,
           idempotency_key: IdempotencyKey,
       ) -> int: ...
   ```

2. Add `episodic/cost/engine.py` with the deterministic `PricingEngine`:

   ```python
   @dc.dataclass(frozen=True, slots=True)
   class PricingEngine:
       def price(
           self,
           snapshot: PricingSnapshot,
           usage: typ.Mapping[str, int],
           operation: str,
           billing_period_key: BillingPeriodKey,
           *,
           is_estimated: bool = False,
       ) -> PricedCall: ...
   ```

   `PricingEngine.price` sums
   `Σ rates_minor_per_metric[m] * usage[m] / 1_000_000` for every metric
   present in both the snapshot and the usage map. Unknown usage metrics raise
   `UnknownPricedMetricError` so silent under-billing is impossible. Operation
   mismatches raise `OperationMismatchError`.

3. Add `episodic/cost/recorder.py` (application-layer). Its public surface is
   `CostRecorder` with `record_provider_call(...)`, `record_task_rollup(...)`,
   and `pin_run_pricing(...)`. The recorder takes `CostLedgerPort`,
   `PricingCataloguePort`, `PricingEngine`, and an injected `Clock`
   collaborator at construction time.

4. Add a new `episodic/llm/ports.py` field. Append a `ProviderCallUsage`
   dataclass and an optional `provider_call_usage` field to `LLMResponse`,
   keeping backwards compatibility with existing tests:

   ```python
   @dc.dataclass(frozen=True, slots=True)
   class ProviderCallUsage:
       usage_metrics: typ.Mapping[str, int]   # canonical vocabulary
       usage_source: UsageSource              # provider | estimated
       usage_complete: bool
       provider_response_id: str
       finish_reason: str | None
       started_at: str
       latency_ms: int
   ```

   Note: `UsageSource` and the canonical vocabulary live in
   `episodic.cost.ports`; the LLM port imports the enum but not the ledger
   types, keeping the layering clean.

5. Extend `pyproject.toml` `[tool.hecate]`:

   - `domain_ports` gains `episodic.cost.ports` and `episodic.cost.engine`.
   - `application` gains `episodic.cost.recorder` and `episodic.orchestration`
     (the orchestration package is currently un-grouped — pinning it here is
     a pre-existing oversight this slice corrects).
   - `outbound_adapter` gains `episodic.cost.storage` and
     `episodic.cost.pricing_catalogue`.
   - `composition_root` is unchanged.

6. Property tests in `tests/test_cost_pricing_engine_properties.py` use
   Hypothesis to verify:

   - `price(snapshot, usage_a + usage_b, …).computed_cost_minor ==
     price(snapshot, usage_a, …).computed_cost_minor +
     price(snapshot, usage_b, …).computed_cost_minor` (additivity in usage).
   - Pricing is monotone in each metric (`usage_a[m] ≤ usage_b[m]` implies
     `cost_a ≤ cost_b`).
   - Zero usage produces zero cost.
   - Unknown metrics raise `UnknownPricedMetricError`.

7. Unit tests in `tests/test_cost_ports_protocols.py` mirror the
   `tests/test_port_contracts.py` pattern (introduced in ADR-014) and assert
   that the concrete stub adapters added in Stage C satisfy the
   `@runtime_checkable` protocols structurally.

### Stage C — Concrete adapters

This stage builds the persistent and provider-side concretions.

1. `episodic/cost/storage/__init__.py` plus models. Add SQLAlchemy models for
   `cost_ledger_entries`, `pricing_snapshots`, `metering_counters`, and
   `run_pricing_pins` mirroring the design-doc field set:

   - `cost_ledger_entries`: `id UUIDv7 PK`, `idempotency_key TEXT UNIQUE`,
     `parent_cost_entry_id UUID NULL FK`, `scope TEXT`, `provider_type TEXT`,
     `provider_name TEXT`, `workflow_node TEXT`, `operation TEXT`,
     `pricing_snapshot_id UUID FK`, `usage JSONB`, `usage_source TEXT`,
     `usage_complete BOOLEAN`, `computed_cost_minor BIGINT`, `currency CHAR(3)`,
     `pricing_model TEXT`, `retry_attempt INT`, `billing_period_key TEXT`,
     `workflow_run_id TEXT INDEX`, `recorded_at TIMESTAMPTZ`. Add a partial
     index on `(workflow_run_id, scope)`.
   - `pricing_snapshots`: `id UUID PK`, `provider_name TEXT`, `model TEXT`,
     `operation TEXT`, `source_kind TEXT`, `currency CHAR(3)`,
     `billing_period_key TEXT`, `rates_minor_per_metric JSONB`,
     `source_metadata JSONB`, `content_hash TEXT UNIQUE`,
     `retrieved_at TIMESTAMPTZ`, `effective_from TIMESTAMPTZ NULL`.
   - `metering_counters`: `counter_key TEXT`, `billing_period_key TEXT`,
     `consumed BIGINT`, `updated_at TIMESTAMPTZ`, PK `(counter_key,
     billing_period_key)`, plus an audit-side `metering_counter_events`
     table keyed by `(idempotency_key)` to prove atomic dedup.
   - `run_pricing_pins`: PK `(workflow_run_id, provider_name,
     billing_period_key)`, `pricing_snapshot_id UUID FK`, `pinned_at
     TIMESTAMPTZ`.

2. `SqlAlchemyCostLedgerStore` and `SqlAlchemyMeteringCounterStore` implement
   the ports. `record_call` is
   `INSERT … ON CONFLICT (idempotency_key) DO NOTHING RETURNING id`; on `None`
   returned, follow up with
   `SELECT id FROM cost_ledger_entries WHERE idempotency_key = …` and return
   that id. `consume` uses this Postgres shape:

   ```sql
   INSERT ...
   ON CONFLICT (counter_key, billing_period_key)
   DO UPDATE SET consumed = metering_counters.consumed + EXCLUDED.consumed
   RETURNING consumed
   ```

   Metering-counter events provide an audit trail keyed by `idempotency_key`
   for replay safety.

3. `FilePricingCatalogue` in `episodic/cost/pricing_catalogue/file_loader.py`
   loads YAML pricing snapshots from a configurable directory (default
   `config/pricing-snapshots/`). Snapshots are content-hashed at load time; the
   loader caches them in-process keyed by `pricing_snapshot_id`. `resolve`
   selects the latest snapshot matching
   `(provider_name, model, operation, billing_period_key)` whose
   `effective_from <= now`. A bundled
   `config/pricing-snapshots/openai-2026-05.yaml` and
   `config/pricing-snapshots/anthropic-2026-05.yaml` ship as documented
   examples.

4. `episodic/llm/openai_adapter.py` normalises `ProviderCallUsage`:

   - OpenAI Chat Completions: `usage.prompt_tokens` →
     `input_tokens`; `completion_tokens` → `output_tokens`;
     `prompt_tokens_details.cached_tokens` → `cached_input_tokens` (when
     present); `completion_tokens_details.reasoning_tokens` →
     `reasoning_tokens`; audio variants → `audio_input_tokens` and
     `audio_output_tokens`.
   - OpenAI Responses: `usage.input_tokens` and `usage.output_tokens` map
     directly; `input_tokens_details.cached_tokens` →
     `cached_input_tokens`; `output_tokens_details.reasoning_tokens` →
     `reasoning_tokens`.
   - Anthropic Messages (forthcoming adapter): `input_tokens`,
     `output_tokens`, `cache_read_input_tokens` →
     `cached_input_tokens`, `cache_creation_input_tokens` →
     `cache_write_tokens`.
   - The streaming path sets `stream_options.include_usage = true` for Chat
     Completions and reads `usage` from the terminal `response.completed`
     event for Responses, then emits `ProviderCallUsage(usage_complete=True)`.
     If the stream terminates without a usage payload, the adapter emits
     `ProviderCallUsage(usage_metrics=…, usage_source=ESTIMATED,
     usage_complete=False, finish_reason="incomplete")` using
     `_estimate_token_count` for the input estimate and the configured
     `max_output_tokens` for the output ceiling. Tests cover both paths.

5. Unit tests under `tests/test_cost_storage_*` use py-pglite per
   `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` and verify idempotent
   inserts, on-conflict dedup, monotone counter consumption, and the
   partial-index roll-up query.

### Stage D — Orchestrator integration

This stage wires the recorder into the structured planning orchestrator and the
LangGraph generation graph.

1. `episodic/cost/recorder.py` gains:

   - `pin_run_pricing(workflow_run_id, providers, billing_period_key)` —
     resolves and persists `run_pricing_pins` rows for every provider used
     by the run.
   - `record_provider_call(workflow_run_id, workflow_node, retry_attempt,
     logical_call_id, provider_name, model, operation, response, request)`
     — looks up the pinned snapshot, prices via `PricingEngine`, and
     inserts the `ProviderCallLedgerEntry`.
   - `finalize_run(workflow_run_id, workflow_node)` — aggregates entries
     by reading `cost_ledger_entries` filtered on `workflow_run_id` and
     inserts the task roll-up. The roll-up's `idempotency_key` is
     `run:<workflow_run_id>:rollup` so re-running `finalize_run` is safe.

2. `episodic/orchestration/_planning_orchestrator.py` gains an optional
   `cost_recorder: CostRecorder | None` constructor argument. When present,
   `orchestrate` pins pricing at the start of the run, records a provider call
   after the planner returns, records one per action after each tool execution
   returns, and finalises the run roll-up after `build_generation_result`
   returns. The orchestrator continues to compute and return the in-memory
   `total_usage` aggregate; ledger writes are a side channel.

3. `episodic/orchestration/langgraph.py` gains the same optional argument
   on `build_generation_orchestration_graph(...)`. The `finish_callback` seam
   is reused so the LangGraph wrapper does not need to import the recorder type
   directly.

4. `episodic/qa/pedante/__init__.py` already returns `LLMResponse` via the
   structured planning path; no change to Pedante itself is required. When the
   evaluator runs as a tool executor (added in a later slice), the recorder
   receives a `workflow_node = "pedante"` provider call entry attributed to the
   underlying LLM model.

5. Composition root updates in `episodic/api/runtime.py` and
   `episodic/worker/runtime.py` build the cost ports and the recorder alongside
   the existing UoW wiring. The composition root is the only place that imports
   concrete `SqlAlchemyCostLedgerStore`, `SqlAlchemyMeteringCounterStore`,
   `FilePricingCatalogue`, and `PricingEngine` together.

6. Behavioural scenario at `tests/features/cost_accounting.feature` plus
   step definitions in `tests/steps/test_cost_accounting_steps.py`. The
   scenario runs `StructuredPlanningOrchestrator.orchestrate` against Vidai
   Mock (two responses: planner JSON and show-notes JSON), then asserts that two
   `provider_call` rows and one `task` roll-up row land in
   `cost_ledger_entries`, with `computed_cost_minor` equal to the sum of the
   two child rows.

### Stage E — Migration, documentation, validation

1. Alembic revision `20260601_000009_add_cost_accounting_schema.py` adds
   `cost_ledger_entries`, `pricing_snapshots`, `metering_counters`,
   `metering_counter_events`, and `run_pricing_pins`, plus the partial index on
   `cost_ledger_entries(workflow_run_id, scope)`. `make check-migrations`
   validates parity with the SQLAlchemy models.

2. Documentation updates:

   - `docs/episodic-podcast-generation-system-design.md` — minor edits in
     the "Cost accounting and budget enforcement" section pointing to
     ADR-015 and the `run_pricing_pins` table.
   - `docs/adr/adr-015-cost-accounting-ports-and-pricing-engine.md` —
     status flips from `Proposed` to `Accepted` at the end of this
     stage. Records the port shape, the canonical metric vocabulary, the
     idempotency-key composition, the run-pin strategy, and the streaming
     usage contract.
   - `docs/developers-guide.md` — extend the orchestration maintainer
     rules with a new "Cost recorder" subsection. Remove the obsolete
     instruction that says model-tier selection must not couple to
     pricing-ledger persistence; replace it with the new rule that
     orchestration recorders may only depend on `episodic.cost.recorder`,
     not on `episodic.cost.ports` directly.
   - `docs/users-guide.md` — add an operator-facing "Cost accounting"
     section describing where ledger entries live, how to manage pricing
     snapshot files, and how to read per-run roll-ups.
   - `docs/roadmap.md` — tick `2.4.4` only after all gates pass.

3. CodeRabbit review runs `coderabbit review --agent` at the end of each
   milestone, and a final review at the end of Stage E. All concerns are
   resolved before the roadmap tick.

## Concrete steps

State the exact commands to run from the worktree root. Update this section as
work proceeds.

1. Confirm the working tree is clean and on the branch
   `2-4-4-cost-accounting-and-usage-metering`:

   ```bash
   git branch --show-current
   git status
   ```

2. Run the full gate after each milestone, teeing the output for later
   review per the agent guidance in `~/.claude/CLAUDE.md`:

   ```bash
   make check-fmt    2>&1 | tee /tmp/check-fmt-episodic-$(git branch --show-current).out
   make typecheck    2>&1 | tee /tmp/typecheck-episodic-$(git branch --show-current).out
   make lint         2>&1 | tee /tmp/lint-episodic-$(git branch --show-current).out
   make check-migrations 2>&1 | tee /tmp/migrations-episodic-$(git branch --show-current).out
   make test         2>&1 | tee /tmp/test-episodic-$(git branch --show-current).out
   ```

3. After Stage B, run only the new property and protocol tests for a
   fast feedback cycle:

   ```bash
   uv run pytest -v tests/test_cost_pricing_engine_properties.py \
                    tests/test_cost_ports_protocols.py
   ```

4. After Stage C, run the storage integration tests under py-pglite:

   ```bash
   uv run pytest -v tests/test_cost_storage_ledger.py \
                    tests/test_cost_storage_metering.py \
                    tests/test_cost_pricing_catalogue_file_loader.py
   ```

5. After Stage D, run the behavioural cost-accounting scenario:

   ```bash
   uv run pytest -v -k cost_accounting tests/features tests/steps
   ```

6. After Stage E, run the full gate sequence (step 2) one last time and
   request `coderabbit review --agent`.

## Validation and acceptance

The change is acceptable when all of the following hold:

- `make check-fmt`, `make typecheck`, `make lint`, `make check-migrations`,
  and `make test` all succeed against the final branch state.
- The behavioural scenario `tests/features/cost_accounting.feature`
  fails on the current `main` (because the recorder does not yet exist) and
  passes on the branch after Stage D.
- The property tests in `tests/test_cost_pricing_engine_properties.py`
  pass with the default Hypothesis health-check budget and use no manual
  `assume(...)` predicates that mask actual failures.
- `make check-architecture` (delegated by `make lint`) reports zero
  Hecate violations for the new prefixes, and importing `episodic.cost.ports`
  from `episodic.orchestration` is permitted whilst importing
  `episodic.cost.storage` from `episodic.orchestration` is rejected.
- A maintainer can run the structured planning scenario end-to-end
  against Vidai Mock and `psql` against `cost_ledger_entries` to see the
  expected row shape, with `computed_cost_minor` parity between the task
  roll-up row and the sum of its child `provider_call` rows.
- ADR-015 is committed and referenced from the design document.
- The roadmap entry `2.4.4` is checked off only after every gate above
  has passed and CodeRabbit has cleared its concerns.

Quality method:

- Continuous Integration runs the same `make check-fmt`, `make typecheck`,
  `make lint`, `make check-migrations`, and `make test` invocations the
  implementer ran locally.
- The CodeRabbit pass uses `coderabbit review --agent` and must report
  zero outstanding concerns before the roadmap tick.

## Idempotence and recovery

All steps are repeatable. The Alembic revision adds tables with no data
movement; rolling back drops the new tables only. Pricing snapshot files on
disk are immutable artefacts; reloading them is a no-op once content hashes
match. The ledger and counter inserts are idempotent by construction
(`ON CONFLICT DO NOTHING` and `ON CONFLICT DO UPDATE … RETURNING`
respectively). If a behavioural scenario is interrupted mid-run, rerunning it
produces the same ledger row count because every insert is keyed by a
deterministic idempotency key.

## Artifacts and notes

Key transcripts and snapshots produced during implementation are stored under
`/tmp/<action>-episodic-<branch>.out` for review per the agent guidance in
`~/.claude/CLAUDE.md`. The behavioural scenario emits a Syrupy snapshot under
`tests/__snapshots__/test_cost_accounting_steps.ambr` pinning the expected
ledger row shape.

## Interfaces and dependencies

The following symbols MUST exist with the stated module path and signature
shape at the end of Stage B. Later stages add adapters and collaborators; the
public ports remain frozen.

In `episodic.cost.ports`:

```python
class LedgerScope(enum.StrEnum): ...
class PricingModel(enum.StrEnum): ...
class PricingSourceKind(enum.StrEnum): ...
class UsageSource(enum.StrEnum): ...

@dc.dataclass(frozen=True, slots=True)
class PricingSnapshot: ...

@dc.dataclass(frozen=True, slots=True)
class PricedCall: ...

@dc.dataclass(frozen=True, slots=True)
class ProviderCallLedgerEntry: ...

@dc.dataclass(frozen=True, slots=True)
class TaskRollupLedgerEntry: ...

@typ.runtime_checkable
class CostLedgerPort(typ.Protocol):
    async def record_call(self, entry: ProviderCallLedgerEntry) -> CostLedgerEntryId: ...
    async def record_task_rollup(self, rollup: TaskRollupLedgerEntry) -> CostLedgerEntryId: ...

@typ.runtime_checkable
class PricingCataloguePort(typ.Protocol):
    async def resolve(
        self,
        provider_name: str,
        model: str,
        operation: str,
        billing_period_key: BillingPeriodKey,
    ) -> PricingSnapshot: ...

@typ.runtime_checkable
class MeteringPort(typ.Protocol):
    async def consume(
        self,
        counter_key: MeteringCounterKey,
        billing_period_key: BillingPeriodKey,
        delta: int,
        idempotency_key: IdempotencyKey,
    ) -> int: ...
```

In `episodic.cost.engine`:

```python
@dc.dataclass(frozen=True, slots=True)
class PricingEngine:
    def price(
        self,
        snapshot: PricingSnapshot,
        usage: typ.Mapping[str, int],
        operation: str,
        billing_period_key: BillingPeriodKey,
        *,
        is_estimated: bool = False,
    ) -> PricedCall: ...

class UnknownPricedMetricError(ValueError): ...
class OperationMismatchError(ValueError): ...
```

In `episodic.cost.recorder`:

```python
@dc.dataclass(slots=True)
class CostRecorder:
    ledger: CostLedgerPort
    catalogue: PricingCataloguePort
    engine: PricingEngine
    clock: WallClockPort

    async def pin_run_pricing(
        self,
        *,
        workflow_run_id: str,
        providers: tuple[str, ...],
        billing_period_key: BillingPeriodKey | None = None,
    ) -> None: ...

    async def record_provider_call(
        self,
        *,
        workflow_run_id: str,
        workflow_node: str,
        retry_attempt: int,
        logical_call_id: str,
        provider_name: str,
        model: str,
        operation: str,
        response: LLMResponse,
    ) -> CostLedgerEntryId: ...

    async def finalize_run(
        self,
        *,
        workflow_run_id: str,
        workflow_node: str | None = None,
    ) -> CostLedgerEntryId: ...
```

In `episodic.llm.ports`:

```python
@dc.dataclass(frozen=True, slots=True)
class ProviderCallUsage:
    usage_metrics: typ.Mapping[str, int]
    usage_source: UsageSource
    usage_complete: bool
    provider_response_id: str
    finish_reason: str | None
    started_at: str
    latency_ms: int

@dc.dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    provider_response_id: str
    finish_reason: str | None
    usage: LLMUsage
    provider_call_usage: ProviderCallUsage | None = None
```

External dependencies introduced by this slice: none. The existing `pyyaml`,
`sqlalchemy`, `hypothesis`, `pytest-bdd`, and `py-pglite` declarations cover
the new code.

## References

- Roadmap entry `2.4.4` in `docs/roadmap.md`.
- Design document section "Cost accounting and budget enforcement" in
  `docs/episodic-podcast-generation-system-design.md`.
- Supplementary supplement
  `docs/cost-management-in-langgraph-agentic-systems.md`.
- Hexagonal layering rules
  `docs/langgraph-and-celery-in-hexagonal-architecture.md`.
- ADR-014 (hexagonal architecture enforcement, prior art for ADR-015).
- Skills: `hexagonal-architecture`, `execplans`,
  `testing-sqlalchemy-with-pytest-and-py-pglite`, `vidai-mock`,
  `en-gb-oxendict`, `documentation-style-guide`.
- Prior art links surfaced during planning research:
  - [SLA4OAI 1.0.0-Draft](https://github.com/isa-group/SLA4OAI-Specification/blob/main/versions/1.0.0-Draft.md)
  - [OpenAI prompt caching usage](https://developers.openai.com/api/docs/guides/prompt-caching)
  - [Anthropic prompt-caching usage fields](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
  - [LangChain `UsageMetadata`](https://reference.langchain.com/python/langchain-core/messages/ai/UsageMetadata)
  - [LangSmith cost tracking](https://docs.langchain.com/langsmith/cost-tracking)
  - [OpenMeter usage event deduplication](https://openmeter.io/blog/usage-deduplication)
