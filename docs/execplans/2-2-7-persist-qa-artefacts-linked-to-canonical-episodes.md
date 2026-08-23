# Persist QA artefacts linked to canonical episodes

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`,
`Outcomes & Retrospective`, `Conformance Basis`, and `Verification Plan` must
be kept up to date as work proceeds.

Status: DRAFT

## Purpose / big picture

Today the Episodic service can run two quality-assurance (QA) evaluators over a
generated podcast script — Pedante, which checks factual claim support, and
Chrono, which estimates spoken runtime — but their results exist only inside an
in-memory LangGraph state object and vanish when the graph finishes. Nothing is
written to the database, so nobody can ask "what did Pedante say about episode
X last Tuesday?" or "show me every episode whose brand check failed".

After this change, every evaluator invocation can be recorded as a durable **QA
artefact** attached to a canonical episode, and an operator can retrieve those
artefacts two ways:

- over Hypertext Transfer Protocol (HTTP), with
  `GET /v1/episodes/{episode_id}/qa-evaluations`, filtered by `evaluator` and
  `compliance_status`, and
- from a terminal, with a new first-party command-line interface (CLI):
  `episodic qa evaluations list --episode <uuid> --evaluator pedante`.

Success is observable without reading any code: create an episode through the
existing source-to-script slice, run Pedante over its Text Encoding Initiative
(TEI) script, record the result, then see the finding come back through both
the HTTP endpoint and the CLI, filtered by evaluator and by compliance status.

## Constraints

These are hard invariants. Violating one requires escalation, not a workaround.

- Do not wire QA evaluators into the generation-run execution path. Roadmap
  item `2.2.7` is about persistence and retrieval. Gating generation on QA
  outcomes is roadmap item `4.4.1` and is explicitly out of scope here.
- Do not add members to `QualityMode` or `QaStatus` in
  `episodic/canonical/generation_quality.py`. `QaStatus` currently has exactly
  one member, `SKIPPED`, and `episodic/canonical/domain.py` contains
  `_validate_draft_without_qa_metadata` (around line 681) which *requires*
  `qa_status is QaStatus.SKIPPED` whenever
  `quality_mode is QualityMode.DRAFT_WITHOUT_QA`. Widening either enum would
  change generation semantics that Architecture Decision Record (ADR) 017 fixed
  for the no-QA slice. QA compliance is modelled by a *new, separate* enum on
  the artefact.
- Do not duplicate token-usage or cost data. `episodic/cost/` already records
  normalized usage and priced ledger entries per provider call
  (`episodic/cost/recorder.py`, `episodic/cost/storage/models.py`). QA
  artefacts must correlate to that ledger, not re-store token counts.
- Preserve the hexagonal architecture boundaries enforced by Hecate
  (`[tool.hecate]` in `pyproject.toml`, gate `make check-architecture`). Domain
  modules must not import Falcon, SQLAlchemy, LangGraph, `httpx`, or Celery —
  and "must not import" means at *runtime*, including transitively through a
  package barrel, not merely in Hecate's edge report.
- No newly added Hecate prefix may be an ancestor of a prefix declared in a
  later group. Hecate classifies a module by the **first** group whose prefix
  contains it (`hecate/policy.py::first_matching_group`), so an ancestor prefix
  silently steals every descendant from the later group and the gate still
  reports success.
- Preserve the canonical persistence conventions: UUIDv7 primary keys generated
  application-side, `postgresql.UUID(as_uuid=True)` columns,
  `sa.DateTime(timezone=True)` timestamps, `postgresql.JSONB` for structured
  payloads, module-level `sa.Enum(..., values_callable=...)` constants in
  `episodic/canonical/storage/models_base.py`, and hand-written Alembic
  migrations.
- Keep every **new** source file at or under 400 lines (`AGENTS.md`). Ten
  existing modules already exceed it, topped by `episodic/canonical/domain.py`
  at 704 lines, so do not read the limit as a description of the current tree.
  Plan the splits listed under *Module budget* before writing, not after the
  port contract tests are in place.
- All prose is en-GB-oxendict; Markdown prose wraps at 80 columns, code blocks
  at 120.

## Tolerances (exception triggers)

Stop and escalate when any of these is reached.

- Scope: more than **50 files across all categories** (production, test,
  snapshot, feature, documentation), or more than 3200 net added lines of
  production code. The realistic budget is set out under *Module budget* and
  comes to roughly 22 production modules, 16 test artefacts, and 8 documents —
  about 46 files. That is deliberately close to the ceiling: this item is large
  because it introduces the first CLI, and the pre-authorized escalation in
  `Decision log` exists for exactly that reason.
- Interface: any change to `QaStatus`, `QualityMode`, `CanonicalEpisode`,
  `GenerationRun`, or the `LLMPort`/`CostLedgerPort` signatures.
- Dependencies: any new runtime dependency beyond promoting `cyclopts` from the
  `dev` group to `[project.dependencies]`. `httpx` is already a runtime
  dependency.
- Architecture: if `make check-architecture` reports violations in
  *pre-existing* modules, or if the EP-M0 ancestor-prefix guard test fails,
  stop and escalate rather than regrouping unrelated packages.
- Iterations: if a gate (`make check-fmt`, `make typecheck`, `make lint`,
  `make test`) still fails after 3 focused fix attempts, stop and escalate.
- Ambiguity: if the compliance-status taxonomy needs a fifth member, or the
  artefact needs to become mutable beyond the single documented
  errored-supersession rule, stop and present options.
- Runtime: if the new py-pglite tests push `make test` past the 180-second
  per-test timeout in `pyproject.toml`, stop and reduce Hypothesis budgets
  rather than raising the timeout.

## Risks

- Risk: the design document names two tables, `qa_findings` and
  `brand_compliance_results`
  (`docs/episodic-podcast-generation-system-design.md`, Data Model and Storage
  section), whereas this plan proposes `qa_evaluations` + `qa_findings` with
  compliance as a column. Severity: medium. Likelihood: high (it is a
  deliberate deviation). Mitigation: record the deviation in ADR 018, update
  the design document's Data Model bullet in the same change, and trace it in
  `Conformance basis`.
- Risk: `episodic/qa/__init__.py` unconditionally imports the LangGraph
  wrappers, so importing *any* evaluator contract loads `langgraph` and
  `httpx`. Classifying evaluator contracts as domain modules without fixing
  that would make this plan's own constraint decorative. Severity: high.
  Likelihood: certain (verified). Mitigation: `EP-M0` slims the barrel and adds
  an import-purity test. No consumer imports the graph builders through the
  barrel, so the change is contained.
- Risk: `ERRORED` has **no production producer** in this slice, because
  evaluators are not wired into the run path. It is exercised only by the
  recording service's failure entry point and by tests. Severity: low.
  Likelihood: certain. Mitigation: state this plainly in ADR 018 and in the
  developers' guide rather than implying an end-to-end producer exists. The
  status is still worth modelling now because adding a PostgreSQL enum value
  later is a two-deploy operation (`ALTER TYPE ... ADD VALUE` cannot use the
  new value in the same transaction).
- Risk: `rubric_score` is mandated by the roadmap but no evaluator produces one
  today. Severity: low. Likelihood: high. Mitigation: the column is nullable,
  is exercised directly by repository round-trip and property tests (where the
  repository, not an evaluator, is the unit under test), and the absence of a
  producer is stated explicitly in the developers' guide and ADR 018.
- Risk: `make check-migrations` cannot verify what this schema most depends on.
  `episodic/canonical/storage/migration_check.py` uses Alembic
  `compare_metadata`, which does **not** compare `CHECK` constraints or foreign
  key `ondelete` behaviour. Severity: medium. Likelihood: certain. Mitigation:
  verify every `CHECK` and both `ondelete` behaviours with direct
  `pytest.raises(IntegrityError)` cases against py-pglite, listed as explicit
  obligations below. Do not treat a green `check-migrations` as evidence for
  them.
- Risk: py-pglite fixture cost. `migrated_engine` is function-scoped and resets
  the schema plus replays all migrations per test function
  (`tests/fixtures/database.py`), against a 180-second timeout. Severity:
  medium. Likelihood: medium. Mitigation: keep `max_examples` at the
  repository's established 5–6 (see
  `tests/canonical_storage/test_sql_generation_run_property_contract.py`), keep
  generated corpora at 0–12 rows, scope every example by a fresh `episode_id`
  because state accumulates across Hypothesis examples within one function, and
  carry `suppress_health_check=[HealthCheck.function_scoped_fixture]`.
- Risk: Vidai Mock is resolved from `PATH` via `shutil.which("vidaimock")`
  (`tests/steps/generation_orchestration_vidaimock.py`); behavioural tests skip
  locally but fail under `CI=true` when it is absent. Severity: low.
  Likelihood: medium. Mitigation: reuse the existing Pedante Vidai Mock harness
  rather than adding a second one, and keep the new behavioural scenarios able
  to run against a recorded evaluator result when the mock is unavailable.
- Risk: Skylos runs with `[tool.skylos.gate] strict = true` and the recording
  entry points have no production caller by design. Severity: medium.
  Likelihood: high. Mitigation: plan the
  `[[tool.skylos.dead_code.entrypoints]]` rules as part of `EP-M3`, with a
  reason naming roadmap item `4.4.1` as the verified future caller — not as a
  late scramble at the final gate. Note that Skylos scans production targets
  only (`SKYLOS_PRODUCTION_TARGETS ?= alembic episodic openai_test_types.py` in
  the `Makefile`), so a test-only caller does not satisfy it.
- Risk: this item is large for a phase-2 roadmap entry because `RM-2.2.7-b`
  requires a CLI and no CLI exists. The CLI bootstrap alone is five modules, a
  runtime dependency promotion, an entry-point change, an ADR, and a users'
  guide section — while roadmap item `4.6.1` ("**Extend** CLI client") assumes
  a CLI already exists, so the bootstrap is really a roadmap gap. Severity:
  medium. Likelihood: high. Mitigation: the pre-authorized escalation in
  `Decision log` splits the bootstrap into a roadmap addendum item rather than
  letting `EP-M5` sprawl. Take it if `EP-M5` breaches its budget; do not take
  it pre-emptively, because `RM-2.2.7-b` names the CLI.

## Progress

- [ ] EP-M0 Import purity, architecture grouping, and baseline gates.
- [ ] EP-M1 QA artefact domain model, compliance policy, and ports.
- [ ] EP-M2 PostgreSQL persistence adapter, Alembic migration, unit-of-work
      registration, and store observability.
- [ ] EP-M3 Recording and query application services, plus evaluator-result
      mapping for Pedante and Chrono.
- [ ] EP-M4 REST retrieval endpoints filtered by evaluator and compliance
      status.
- [ ] EP-M5 First-party CLI retrieval surface.
- [ ] EP-M6 Documentation, ADRs, and roadmap completion.

## Surprises & discoveries

- Observation: Hecate classifies a module by the **first** configured group
  whose prefix contains it, not the longest or most specific prefix. Evidence:
  `.venv/lib/python3.14/site-packages/hecate/policy.py`, `first_matching_group`
  iterates `groups` in declaration order and returns on the first match. Adding
  the prefix `episodic.llm` to `domain_ports` (declared before
  `outbound_adapter`) therefore reclassifies `episodic.llm.openai_api`,
  `episodic.llm.openai_adapter`, and `episodic.llm.openai_client` out of
  `outbound_adapter` — and `make check-architecture` still exits 0, so the gate
  reports success while the boundary is gone. Impact: this plan must **not** add
  `episodic.llm`. Use `episodic.llm.ports`, which is already grouped, and rely
  on Hecate's re-export index to resolve `from episodic.llm import LLMUsage` in
  `episodic/qa/pedante/types.py`. A guard test is added at `EP-M0`.
- Observation: importing any evaluator contract loads LangGraph and `httpx`.
  Evidence:
  `uv run python -c "import sys, episodic.qa.pedante.types as t;
  print('langgraph' in sys.modules, 'httpx' in sys.modules)"`
  prints `True True`, because `episodic/qa/__init__.py` unconditionally imports
  `.chrono_langgraph` and `.langgraph`, and Python executes a parent package
  on any submodule import. Impact: `EP-M0` removes `build_chrono_graph`,
  `build_pedante_graph`, and `route_after_pedante` from the barrel. A
  repository-wide search confirms no module imports those three names from
  `episodic.qa`; every consumer already imports `episodic.qa.langgraph` or
  `episodic.qa.chrono_langgraph` directly.
- Observation: `except IndexError, ValueError:` (unparenthesized multiple
  exception types) appears in `episodic/api/errors.py:367`,
  `episodic/api/authorization.py:114`,
  `episodic/api/resources/generation_runs.py:270`, and
  `episodic/generation/launcher.py:501`. This is a `SyntaxError` on Python 3.13
  and earlier but is **valid** on Python 3.14 under Python Enhancement Proposal
  (PEP) 758. Evidence:
  `uv run python -c "import ast; ast.parse(open('episodic/api/errors.py').read())"`
  prints `parse OK` under CPython 3.14.4; the same command under CPython 3.12
  raises `SyntaxError: multiple exception types must be parenthesized`. Impact:
  none for this work, but tooling pinned below Python 3.14 will wrongly report
  these files as broken. Do not "fix" them.
- Observation: `[project.scripts]` declares
  `stilyagi = "stilyagi.stilyagi:main"` but no `stilyagi` module exists
  anywhere in the repository. Evidence: `pyproject.toml:31-32`; a
  repository-wide search for `stilyagi` outside `pyproject.toml` returns
  nothing. Impact: the console-script table is currently dead. `EP-M5` replaces
  it with the real `episodic` entry point.
- Observation: the LangGraph structured-planning graph
  (`episodic/orchestration/langgraph.py`, nodes `plan`, `execute`, `finish`)
  and the no-QA generation-run launcher (`episodic/generation/launcher.py`) are
  two parallel subsystems that do not call each other, and neither invokes the
  QA evaluator graphs in `episodic/qa/`. Evidence:
  `InProcessGenerationRunLauncher` contains no import of
  `episodic.orchestration`; no node named `qa`/`evaluate` exists in
  `episodic/orchestration/_graph_state.py` or `langgraph.py`. Impact: confirms
  that recording must be an explicitly invoked application service in this
  roadmap item, not a graph-node side effect.
- Observation: the existing generation event log cannot host QA artefacts.
  Evidence: `SqlAlchemyGenerationRunStore.append_event` calls
  `_require_mutable_run(..., lock=True)`, which raises `RunAlreadyTerminal`
  once a run has finished (`episodic/canonical/storage/generation_runs.py`,
  around lines 93 and 290); `generation_events.generation_run_id` is `NOT NULL`
  with no episode foreign key. QA recording happens after a run completes, or
  with no run at all. Impact: rules out the "just use the event log"
  alternative on evidence, not taste. Record it in ADR 018 so the question is
  not reopened.
- Observation: no repository test runs one contract suite over both an
  in-memory fake and a SQL adapter. Evidence:
  `tests/test_generation_checkpoint_port_contract.py` instantiates
  `InMemoryGenerationRunStore` only. Impact: `INV-FILTER-SOUND` below does not
  claim a precedent that does not exist, and does not use a same-author fake as
  its oracle.
- Observation: `hypothesis.stateful` has no async support in the pinned
  version, and `pytest-asyncio` does not drive the `unittest.TestCase` that
  `RuleBasedStateMachine` runs through. No `RuleBasedStateMachine` exists
  anywhere in this repository. Impact: the replay obligation below uses
  `@given` over a generated operation sequence with a manual async replay,
  following
  `tests/canonical_storage/test_sql_generation_run_property_contract.py`.
- Observation: `episodic/canonical/unit_of_work_protocols.py` does not declare
  `workflow_checkpoints`, although `episodic/canonical/storage/uow.py` assigns
  it. Pre-existing drift. Impact: none for this work, but do not copy the
  omission. Declare `qa_artefacts` on the protocol.

## Decision log

- Decision: model QA artefacts as one `qa_evaluations` parent table plus one
  `qa_findings` child table, with compliance represented as a
  `compliance_status` column, instead of the separate
  `brand_compliance_results` table named in the design document. Rationale:
  only one evaluator that would populate `brand_compliance_results` exists on
  the roadmap (Anthem, item `2.2.4`, unimplemented). Building a second table
  for a producer that does not exist is speculative generality, and it would
  make the roadmap's own requirement — "retrieval … filtered by evaluator and
  compliance status" — a union query across two tables. Recorded as ADR 018;
  the design document's Data Model bullet is updated in the same change.
  Date/Author: 2026-08-23, planning agent. **Deviation status: accepted.** This
  is a deviation from `TDD-DATA`, which names `qa_findings` and
  `brand_compliance_results`. Affected identifiers: `TDD-DATA`, `RM-2.2.7-a`,
  `RM-2.2.7-b`. Downstream impact: `EP-M2`'s schema, `EP-M4`'s filter contract,
  and the design document's Data Model bullet, which `EP-M6` must rewrite to
  name the tables actually created. Upstream document changes required:
  `docs/episodic-podcast-generation-system-design.md` plus a new ADR 018.
  Accepted by leynos, 2026-08-23. `EP-M6` may not be marked complete until both
  upstream edits have landed.
- Decision: keep a child `qa_findings` table rather than a JSONB findings array
  on the evaluation row. Rationale: roadmap items `4.4.1` and `4.4.2` aggregate
  findings across evaluators and drive refinement turns from individual
  findings, so findings need stable identifiers and cross-episode queryability
  within two roadmap items. Recorded with its trade-off in ADR 018: if `EP-M2`
  proves the child table costly, collapsing to a JSONB array is a legitimate
  retreat. Date/Author: 2026-08-23, planning agent.
- Decision: store `compliance_status` rather than deriving it at read time.
  Rationale: `RM-2.2.7-b` requires filtering *and* a correct unpaged `total`. A
  Python-side policy makes `WHERE compliance_status = ...` impossible and turns
  `total` into a full scan with every finding loaded. Date/Author: 2026-08-23,
  planning agent.
- Decision: record `compliance_policy_version` alongside
  `artefact_schema_version`. Rationale: `compliance_status` and
  `QaFinding.is_blocking` are both derived from `_BLOCKING_SUPPORT_LEVELS`, a
  module-private frozenset in `episodic/qa/pedante/types.py`. Changing that set
  puts every historical row out of step with current policy, and the artefact
  schema version does not cover it — one versions the payload *shape*, the
  other the *decision rule*. The raw signal is preserved (`code` stores the
  support level), so re-derivation is a backfill query rather than archaeology,
  but only if each row states which policy produced it. Date/Author:
  2026-08-23, planning agent.
- Decision: keep a single four-member `compliance_status` enum; do not split
  into `lifecycle_status` plus a nullable `verdict`. Rationale: an artefact is
  written only *after* an evaluator returns or fails, so `pending` and
  `running` have no representable state. `superseded` is handled by the
  errored-supersession rule below plus ordering by `evaluated_at`. A single
  column keeps the roadmap's "filtered by … compliance status" unambiguous. The
  split is recorded in ADR 018 as the considered alternative, together with the
  trigger that would justify it: an evaluator that reports partial results.
  Date/Author: 2026-08-23, planning agent.
- Decision: `not_applicable` means "this evaluator renders no compliance
  verdict under the recorded policy version", not "not applicable to this
  episode". Chrono records `not_applicable` today. Rationale: when pacing
  thresholds land, Chrono rows recorded under `compliance_policy_version = 1`
  remain accurate *for that policy*; new rows carry a later policy version and
  a real verdict. Without the policy version this would be a mislabelling that
  forces a backfill; with it, it is a versioned statement. ADR 018 must state
  the semantics in exactly these words. Date/Author: 2026-08-23, planning agent.
- Decision: do not store token usage on the QA artefact. Correlate to the cost
  ledger through `generation_run_id` plus the `provider_response_id` carried in
  `evaluator_metadata`. Rationale: `episodic/cost/` already records normalized
  usage and priced entries per provider call, keyed by `workflow_run_id` and an
  idempotency key built as
  `run:{run_id}:node:{node}:call:{provider_response_id}:attempt:{n}`
  (`episodic/generation/launcher_support.py`). A second copy would drift.
  Date/Author: 2026-08-23, planning agent.
- Decision: artefacts are immutable once recorded, with exactly one exception —
  an artefact whose `compliance_status` is `errored` is provisional and is
  superseded in place by a later successful recording under the same
  idempotency key. Rationale: without the exception, a transient evaluator
  failure permanently marks an episode errored and the successful retry is
  silently discarded as a replay. With unrestricted mutability, the stored
  `compliance_status` and `is_blocking` values could drift away from the policy
  version they record. One narrow, tested exception buys retry correctness
  without losing immutability as a reasoning tool. Date/Author: 2026-08-23,
  planning agent.
- Decision: the CLI is a REST client, not a second database client.
  Rationale: the system design places the CLI in the Client Experience Layer
  alongside the web console, and `docs/episodic-tui-api-design.md` fixes the
  authentication, error, and pagination contracts that clients use. A CLI that
  opened its own unit of work would create a second persistence entry point
  with its own authorization story. Recorded as ADR 019, which also gives
  `episodic.cli` its own Hecate group so the boundary is enforced rather than
  merely intended. Date/Author: 2026-08-23, planning agent.
- Decision: ship only `episodic qa evaluations list` in this slice; do not add
  a `show` sub-command. Rationale: `RM-2.2.7-b` requires filtered retrieval,
  which `list` satisfies. `GET /v1/qa-evaluations/{evaluation_id}` still serves
  the Terminal User Interface (TUI) client. Roadmap item `4.6.1` extends the
  CLI; the top-level noun structure is provisional until a second command group
  lands, and ADR 019 says so. Date/Author: 2026-08-23, planning agent.
- Decision: populate the `qa_evaluator` enum with all six evaluators named in
  the design document (Pedante, Bromide, Chiltern, Anthem, Caesura, Chrono)
  even though four are unimplemented. Rationale: `ALTER TYPE ... ADD VALUE`
  cannot use the new value in the same transaction, so extending a PostgreSQL
  enum later is a two-deploy operation, not one migration. The taxonomy is
  fixed by the design document, so admitting all six now costs one enum
  definition. A parameterized test pins the enum's value set against the
  documented taxonomy so it cannot silently drift. Date/Author: 2026-08-23,
  planning agent.
- Decision: `episodic/canonical/qa_artefact_recording.py` lives in the
  canonical package, not in `episodic/qa/`. Rationale: the module knows both
  sides of the mapping. Hosting it in `episodic/qa/` would make the evaluator
  package depend on `episodic.canonical`, inverting the direction of the
  dependency. The canonical package owns the target types, and the compliance
  policy is a canonical policy rather than an evaluator concept. Date/Author:
  2026-08-23, planning agent.
- Decision (pre-authorized escalation): if `EP-M5` exceeds 6 production
  modules or 500 net production lines, stop and split the CLI **bootstrap** —
  `episodic/cli/__init__.py`, `app.py`, `client.py`, `rendering.py`, ADR 019,
  the `[project.scripts]` change, the `cyclopts` promotion, and the users'
  guide *Getting Started* section — into a new roadmap addendum item `2.2.8`,
  "Bootstrap the first-party CLI client", and mark `2.2.7` as requiring it.
  `2.2.7` then keeps only `episodic/cli/qa.py` and its three feature scenarios.
  Rationale: the bootstrap decides client architecture for every future
  command, which is not a QA-artefact concern; roadmap item `4.6.1` already
  assumes it exists. Taking the split is therefore a correction to the roadmap,
  not a scope dodge. This is pre-authorized so the implementer does not have to
  stop and ask, but it must be recorded in `Decision log` with the measured
  figures when taken. Date/Author: 2026-08-23, planning agent. **Status:
  approved as written.** Splitting the CLI bootstrap out up front was offered
  and declined; `2.2.7` keeps the CLI by default, because `RM-2.2.7-b` names
  it. The escalation stays available on the budget trigger above and does not
  need re-approval when taken — record the measured figures here instead.
  Accepted by leynos, 2026-08-23.
- Decision: place both ADRs in `docs/adr/`, not `docs/`.
  Rationale: `docs/documentation-style-guide.md` says "Place ADRs in the
  `docs/` directory", but every ADR since 001 lives in `docs/adr/` and
  `docs/contents.md` indexes them there. Follow practice; note the discrepancy
  in the style guide's favour is a separate cleanup, not this item's work.
  Date/Author: 2026-08-23, planning agent.
- Decision: do not build an in-memory QA artefact adapter.
  Rationale: `INV-FILTER-SOUND`'s oracle must be independent of the
  implementation. A fake written by the same author from the same spec sentence
  is a second subject, not an oracle, and it would add a module with no
  production consumer for Skylos to flag. Existing API tests already run
  against py-pglite through `canonical_api_client`. Date/Author: 2026-08-23,
  planning agent.

## Outcomes & retrospective

To be completed at `EP-M6`. Before setting this plan to `COMPLETE`, reconcile
every discovery against the artefacts listed in `Conformance basis`: the design
document's Data Model bullet must name the tables actually created, ADR 001's
open item about persisting evaluator results must be discharged by ADR 018, and
`docs/roadmap.md` item `2.2.7` must be marked done.

## Context and orientation

Episodic generates podcast episodes. The canonical record of an episode is a
TEI P5 Extensible Markup Language (XML) document stored in the `episodes`
table. Work that produces or checks that document is organized as a **hexagonal
architecture**: pure domain modules define behaviour and *ports* (Python
`Protocol` classes); *adapters* implement those ports against PostgreSQL,
Falcon (the HTTP framework), OpenAI-compatible providers, and so on.

Terms used throughout:

- **Evaluator** — a QA check over a generated script. Pedante and Chrono are
  implemented; Bromide, Chiltern, Anthem, and Caesura are not.
- **Finding** — one structured problem an evaluator reports.
- **QA artefact** — the durable record of one evaluator invocation: its
  outcome, its findings, and enough metadata to reproduce and audit it. This
  concept does not exist yet; this plan creates it.
- **Compliance status** — whether an evaluation's outcome permits the episode
  to advance. New in this plan.
- **Unit of work (UoW)** — a transaction boundary exposing repositories as
  attributes. See `episodic/canonical/storage/uow.py`.

### Where things are today

Evaluator contracts live in `episodic/qa/`:

- `episodic/qa/pedante/types.py` defines `ClaimKind`, `SupportLevel` (14
  members, 8 of which are in the module-private `_BLOCKING_SUPPORT_LEVELS`
  frozenset), `FindingSeverity` (`low`, `medium`, `high`, `critical`),
  `PedanteFinding` (`claim_id`, `claim_text`, `claim_kind`, `support_level`,
  `severity`, `summary`, `remediation`, `cited_source_ids`, plus an
  `is_blocking` property) and `PedanteEvaluationResult` (`summary`, `findings`,
  `usage: LLMUsage`, `model`, `provider_response_id`, `finish_reason`, plus a
  `requires_revision` property that is true when any finding is blocking).
  There is **no** contract-version constant; `EP-M3` adds one.
- `episodic/qa/chrono.py` defines `ChronoEstimatorConfig` (which does carry
  `estimator_name` and `estimator_version`), `ChronoEstimatorMetadata`
  (`estimator_name`, `estimator_version`, `input_character_count`,
  `spoken_word_count`, `words_per_minute`) and `ChronoRuntimeEstimate`
  (`estimated_seconds`, `metadata`).
- `episodic/qa/langgraph.py` and `episodic/qa/chrono_langgraph.py` wrap each
  evaluator as a one-node LangGraph `StateGraph`. Neither writes to any store.

Canonical persistence lives in `episodic/canonical/`:

- Domain entities are frozen dataclasses in `episodic/canonical/domain.py`.
- Ports are `Protocol` classes, for example
  `episodic/canonical/generation_run_ports.py`.
- SQLAlchemy models live in `episodic/canonical/storage/`, with the declarative
  `Base` and the shared `sa.Enum` constants in
  `episodic/canonical/storage/models_base.py`.
- `episodic/canonical/storage/repository_base.py` provides `_RepositoryBase`
  with `_get_one_or_none`, `_get_many`, `_list_where`, `_list_by_ids`,
  `_list_paginated`, `_get_latest_where`, `_update_where`, and
  `_update_entity_fields`. `SqlAlchemyGenerationRunStore` deliberately does not
  use it, because it needs savepoint-and-requery inserts and row locking; the
  QA store is in the same position.
- `episodic/canonical/storage/uow.py` instantiates every repository inside
  `SqlAlchemyUnitOfWork.__aenter__`; the matching attribute list is declared on
  the `CanonicalUnitOfWork` `Protocol` in
  `episodic/canonical/unit_of_work_protocols.py`.
- Alembic migrations are hand-written under `alembic/versions/`, named
  `YYYYMMDD_NNNNNN_<slug>.py` with `revision` equal to the filename prefix. The
  current head is `20260624_000012` (`add_ingestion_job_owner.py`). Order is
  defined by `down_revision`, not by the date in the filename — two existing
  revisions share the suffix `000009` and run backwards by date.
- `episodic/canonical/generation_persistence.py` holds both conventions:
  `persist_draft_script` deliberately neither commits nor rolls back because
  its caller owns the transaction, while its sibling
  `materialise_episode_from_ingestion` does commit. Pick the one that matches
  who owns the transaction; do not cite the module as if it had one rule.

The HTTP surface lives in `episodic/api/`:

- Routes are registered in `episodic/api/app.py` by `_register_*_routes`
  helpers; every domain route is prefixed `/v1/`.
- `episodic/api/helpers.py` provides `parse_pagination` (limit default 20, max
  100; offset ≥ 0), `parse_enum_param`, `parse_optional_uuid_param`, and
  `require_query_params`.
- List responses use the envelope
  `{"items": [...], "limit": ..., "offset": ..., "total": ...}`, matching
  `docs/episodic-tui-api-design.md`.
- Errors use the repository's own envelope `{"code", "message", "details"}` via
  `episodic/api/errors.py` and
  `app.set_error_serializer(serialize_http_error)` — not RFC 9457
  `application/problem+json`.
- Authorization is coarse: `AuthorizationMiddleware` (in
  `episodic/api/authorization.py`) sets `req.context.principal_id` for `/v1/*`
  requests, and resources then enforce **ownership**. The precedent for
  episode-scoped reads is `episodic/api/resources/episode_tei.py`, whose
  `_has_accessible_draft` requires `run.actor == actor` for the episode's
  `last_generation_run_id`, and which returns not-found — not `401` — when
  `principal_id(req)` is `None`.
- No `decimal.Decimal` value is serialized anywhere in `episodic/`, so no JSON
  handler for it exists. Falcon's default media handler would raise `TypeError`.

There is **no command-line interface**. `cyclopts` is a development-group
dependency used only by `scripts/local_k8s.py`.

Three facts about the gates are easy to discover the hard way:

- `make test` depends on the `crosshair` target, so every test run also
  executes `crosshair check --analysis_kind=PEP316 episodic/qa/chrono.py`.
- `make lint` runs Skylos over production targets only
  (`SKYLOS_PRODUCTION_TARGETS ?= alembic episodic openai_test_types.py`) with
  `[tool.skylos.gate] strict = true`. A symbol called only from `tests/` counts
  as dead.
- `make typecheck` runs `ty` 0.0.32 only. `pyright` is an unused development
  dependency, so do not rely on `pyright`-specific behaviour.

### Skills and documents to load before starting

- Skill `execplans` — this document's format and the discipline for keeping it
  current.
- Skill `hexagonal-architecture` — layer boundaries, port ownership, and the
  layer-specific testing table.
- Skill `python-router`, then `python-data-shapes` (frozen dataclasses and
  tagged unions for the artefact model) and `python-types-and-apis` (port
  `Protocol` design). Load `python-errors-and-logging` when writing the
  evaluator-failure path and the store's narrowed exception handling.
- Skill `python-verification`, then `hypothesis` for the property obligations.
- Skill `python-testing` for pytest fixture and parametrization depth.
- Skill `python-quality-tools` before arguing with Skylos.
- Skill `leta` for symbol navigation; prefer `leta show`/`leta refs` over
  reading whole files.
- Skill `vidai-mock` before touching the behavioural evaluator harness.
- Skill `en-gb-oxendict` and `docs/documentation-style-guide.md` for all prose;
  the ADR template is in that style guide and is long — budget for it.

Repository documents that are prerequisites, not optional reading:

- `AGENTS.md` — code style, quality gates, commit discipline, the 400-line file
  limit.
- `docs/episodic-podcast-generation-system-design.md` — the Quality Assurance
  Stack and Data Model and Storage sections.
- `docs/adr-001-pedante-evaluator-contract.md` — in particular its closing
  item: "If evaluator results are persisted or exposed through an external API,
  record any versioning or compatibility guarantees in a follow-on ADR." ADR
  018 discharges this.
- `docs/adr/adr-006-chrono-spoken-text-semantics.md`,
  `docs/adr/adr-009-source-to-script-rest-vertical-slice.md`,
  `docs/adr/adr-014-hexagonal-architecture-enforcement.md`,
  `docs/adr/adr-015-cost-accounting-ports-and-pricing-engine.md`,
  `docs/adr/adr-017-no-qa-generation-run-execution-and-tei-persistence.md`.
- `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`,
  `docs/testing-async-falcon-endpoints.md`,
  `docs/agentic-systems-with-langgraph-and-celery.md`,
  `docs/langgraph-and-celery-in-hexagonal-architecture.md`,
  `docs/episodic-tui-api-design.md`,
  `docs/complexity-antipatterns-and-refactoring-strategies.md`,
  `docs/repository-layout.md` and `docs/contents.md` (the orientation start
  points named by `AGENTS.md`), `docs/scripting-standards.md`,
  `docs/developers-guide.md`, `docs/users-guide.md`.

## Conformance basis

Upstream artefacts, at the revisions present in the working tree at the time of
writing (commit `5af0638`, "No-QA generation runs and TEI-P5 retrieval
(4.3.2)"):

- `docs/roadmap.md`, item `2.2.7` (`RM-2.2.7`) with its two sub-requirements:
  `RM-2.2.7-a` "Store evaluator findings, runtime estimates, rubric scores, and
  compliance results"; `RM-2.2.7-b` "Enable retrieval via API and CLI filtered
  by evaluator and compliance status".
- `docs/episodic-podcast-generation-system-design.md`, sections *Quality
  Assurance Stack* (`TDD-QA`), *Data Model and Storage* (`TDD-DATA`), *Client
  Experience Layer* (`TDD-CLIENT`), and *QA, Compliance, and Approvals*
  (`TDD-FLOW-QA`).
- `docs/adr-001-pedante-evaluator-contract.md` (`ADR-001`), open item on
  persistence and versioning guarantees.
- `docs/adr/adr-017-no-qa-generation-run-execution-and-tei-persistence.md`
  (`ADR-017`), which fixes `QaStatus.SKIPPED` semantics for the no-QA slice.
- `docs/adr/adr-014-hexagonal-architecture-enforcement.md` (`ADR-014`) and the
  `[tool.hecate]` configuration in `pyproject.toml`.
- `docs/episodic-tui-api-design.md` (`TUI-API`), pagination and error
  contracts.

No Terms of Reference document exists for this repository; the roadmap and the
system design document play that role. Say so rather than inventing one.

Trace links:

```plaintext
ADR-014     -> EP-M0 -> tests/test_architecture_enforcement.py::test_no_prefix_shadows_a_later_group
ADR-014     -> EP-M0 -> tests/test_qa_import_purity.py::test_recording_module_does_not_load_langgraph
RM-2.2.7-a  -> TDD-DATA -> EP-M1 -> tests/test_qa_artefact_domain.py::test_blocking_support_levels_match_documented_set
RM-2.2.7-a  -> TDD-DATA -> EP-M2 -> tests/canonical_storage/test_qa_artefacts.py::test_evaluation_round_trip
RM-2.2.7-a  -> TDD-QA   -> EP-M3 -> tests/test_qa_artefact_recording.py::test_records_pedante_result
RM-2.2.7-b  -> TUI-API  -> EP-M4 -> tests/features/qa_artefact_retrieval.feature (REST scenarios)
RM-2.2.7-b  -> TDD-CLIENT -> EP-M5 -> tests/features/qa_artefact_retrieval.feature (CLI scenarios)
ADR-001(open item) -> EP-M6 -> docs/adr/adr-018-qa-artefact-persistence-contract.md
TDD-DATA(deviation, accepted 2026-08-23) -> EP-M6 -> docs/episodic-podcast-generation-system-design.md (Data Model bullet)
```

## Verification plan

Hypothesis budgets follow the repository precedent in
`tests/canonical_storage/test_sql_generation_run_property_contract.py`:
`max_examples=6`,
`suppress_health_check=[HealthCheck.function_scoped_fixture]`, and every
example scoped by a freshly generated `episode_id` because `migrated_engine`
resets per test *function*, not per example.

### Invariants and lemmas

**INV-BLOCKING-SET.** The set of `SupportLevel` members treated as blocking is
exactly the set documented in ADR 001.

- Method: parameterized test over all 14 `SupportLevel` members, comparing
  `PedanteFinding.is_blocking` against an **independently written literal set**
  in the test module.
- Rationale: this obligation exists because `INV-COMPLIANCE-BLOCKING` below
  cannot see a wrong blocking set — it inherits the set from the code under
  test. Without an independent literal, the property is `f(x) == f(x)`.
- Domain: all 14 members, exhaustively.
- Artefact: `tests/test_qa_artefact_domain.py`.
- Evidence: `uv run pytest tests/test_qa_artefact_domain.py -q`.
- Non-vacuity: the literal set is transcribed from ADR 001, not from
  `episodic/qa/pedante/types.py`. Negative control: flip one member's
  membership in the production frozenset and confirm exactly one parameterized
  case fails.

**INV-COMPLIANCE-BLOCKING.** For any `PedanteEvaluationResult` `r`, the derived
evaluation's `compliance_status` is `NON_COMPLIANT` if and only if at least one
derived `QaFinding` has `is_blocking` true; otherwise `COMPLIANT`.

- Method: property test with Hypothesis over a composite strategy generating
  `PedanteEvaluationResult` values across all 14 `SupportLevel` members and all
  4 `FindingSeverity` members, including the empty-findings case.
- Rationale: this is the mapping's total-function property; paired with
  `INV-BLOCKING-SET` it covers both the rule and the set it consults.
- Domain: 0–8 findings; support level and severity drawn uniformly;
  `cited_source_ids` of length 0–3.
- Artefact: `tests/test_qa_artefact_recording_properties.py`.
- Evidence: `uv run pytest tests/test_qa_artefact_recording_properties.py -q`.
  Before implementation the module under test does not exist, so collection
  fails with `ModuleNotFoundError`.
- Non-vacuity: emit `hypothesis.event()` labels `"blocking present"` and
  `"no blocking finding"`; assert under `--hypothesis-show-statistics` that
  both occur. Negative control: make the policy return `COMPLIANT`
  unconditionally and confirm a counter-example containing a blocking finding.

**INV-MAPPING-FIDELITY.** Projecting a `PedanteEvaluationResult` onto a
`QaEvaluation` preserves every field the projection claims to carry: for the
`i`-th emitted `PedanteFinding`, the `i`-th `QaFinding` has `ordinal == i`,
`code == support_level.value`, `subject_id == claim_id`,
`subject_text == claim_text`, `citations == cited_source_ids`,
`details["claim_kind"] == claim_kind.value`, and matching severity, summary,
remediation, and `is_blocking`.

- Method: property test over generated results.
- Rationale: `INV-FINDING-ORDER` verifies *persistence* order, not *mapping*
  content. Nothing else pins this projection, and it is where a rename silently
  drops data.
- Domain: as `INV-COMPLIANCE-BLOCKING`.
- Artefact: `tests/test_qa_artefact_recording_properties.py`.
- Evidence: as above.
- Non-vacuity: generate at least one finding with empty `cited_source_ids` and
  one with three, and at least one with non-ASCII `claim_text`. Negative
  control: swap `subject_id` and `subject_text` in the mapper and confirm
  failure.

**INV-KEY-DETERMINISM.** The idempotency key derived for an evaluation is a
pure function of
`(evaluator, evaluator_version, compliance_policy_version,
episode TEI content hash, generation_run_id)`,
and contains no clock reading, no random value, and no attempt counter.

- Method: parameterized test plus a property test asserting that two
  independent derivations from equal inputs are equal, and that changing any
  one input changes the key.
- Rationale: `INV-REPLAY-IDEMPOTENT` draws keys from a fixed pool and therefore
  tests the *store*, not the *minter*. A minter that folded in `evaluated_at`
  would defeat replay entirely and no other obligation would notice.
- Domain: all six evaluators; run identifier present and absent; two policy
  versions; two content hashes.
- Artefact: `tests/test_qa_artefact_recording.py`.
- Evidence: `uv run pytest tests/test_qa_artefact_recording.py -q`.
- Non-vacuity: the "changing any input changes the key" half fails for a minter
  that returns a constant; the "equal inputs, equal key" half fails for a
  minter that folds in a clock. Both halves are required. Negative control:
  append `str(evaluated_at)` to the key and confirm the equality half fails.

**INV-FINDING-ORDER.** Findings persisted for an evaluation are returned in the
order the evaluator emitted them, with `ordinal` values exactly `0..n-1`.

- Method: property test over generated finding sequences, against the real
  SQLAlchemy adapter using the py-pglite fixtures.
- Rationale: PostgreSQL returns rows in unspecified order absent `ORDER BY`.
- Domain: 0–12 findings per evaluation, mixed severities.
- Artefact: `tests/canonical_storage/test_qa_artefact_properties.py`.
- Evidence:
  `uv run pytest tests/canonical_storage/test_qa_artefact_properties.py -q`.
- Non-vacuity: include an evaluation whose severities sort differently from
  emission order, so an accidental `ORDER BY severity` is rejected. Because
  insert-in-order plus a seq-scan usually *reproduces* insertion order, force
  physical disorder: after insert, `UPDATE` one middle row's `summary` so
  PostgreSQL relocates it in the heap, then read back. Negative control: drop
  `ORDER BY ordinal` from the adapter query and confirm failure.

**INV-REPLAY-IDEMPOTENT.** Recording twice with the same
`(episode_id, idempotency_key)` creates exactly one `qa_evaluations` row and
one set of `qa_findings` rows, returns the identifier created by the first
call, and returns that row with its findings populated and every field equal to
the stored values.

- Method: `@given` over a generated operation sequence, replayed manually
  against py-pglite. **Not** `hypothesis.stateful` — see
  `Surprises & discoveries`.
- Rationale: replay is a transition property over operation sequences. ADR 017
  establishes replay semantics for generation runs; artefact writes during a
  replayed run must not multiply.
- Domain: 1–8 record operations drawn from a pool of 3 idempotency keys and 2
  episodes, interleaved with list operations; `max_examples=6`; a fresh
  `episode_id` pair per example.
- Artefact: `tests/canonical_storage/test_qa_artefact_replay.py`.
- Evidence:
  `uv run pytest tests/canonical_storage/test_qa_artefact_replay.py -q`.
- Non-vacuity: assert in the example teardown that at least one duplicate key
  was actually replayed. Negative control: **not** "remove the unique
  constraint" — the constraint lives in the database, so removing the adapter's
  handling makes PostgreSQL raise and the test fails for the wrong reason.
  Instead, stub the adapter's post-`IntegrityError` re-select to return the
  caller's candidate and assert the returned identifier differs from the first
  call's. That is precisely what the invariant claims.

**INV-ERRORED-SUPERSEDED.** Recording a successful evaluation under a key whose
stored artefact has `compliance_status = errored` replaces that artefact in
place, keeping its identifier and replacing its findings. Recording under a key
whose stored artefact is any other status returns the stored artefact unchanged.

- Method: parameterized test over the four stored statuses.
- Rationale: without this, a transient failure permanently marks an episode
  errored and every retry is discarded as a replay. This is the one documented
  exception to artefact immutability, so it needs an explicit boundary test.
- Domain: stored status ∈ `{compliant, non_compliant, not_applicable, errored}`
  × incoming status ∈ `{compliant, errored}`.
- Artefact: `tests/canonical_storage/test_qa_artefact_replay.py`.
- Evidence: as above.
- Non-vacuity: the `errored → compliant` case must observe the findings change;
  the `compliant → compliant` case must observe them unchanged. A store that
  always replaces fails the second; one that never replaces fails the first.

**INV-CONSTRAINT-ENFORCED.** Each database constraint rejects the values it
names: `rubric_score` outside `[0, 1]`; negative `runtime_estimate_seconds`;
negative `ordinal`; negative `finding_count`; an evaluation referencing a
non-existent episode.

- Method: parameterized `pytest.raises(IntegrityError)` cases issued as **raw
  SQL** against py-pglite, bypassing `__post_init__`.
- Rationale: `episodic/canonical/storage/migration_check.py` uses Alembic
  `compare_metadata`, which does not compare `CHECK` constraints. A green
  `make check-migrations` is not evidence for any of these. Going through the
  domain constructor would only re-test `__post_init__`.
- Domain: one violating value per constraint, plus one satisfying witness per
  constraint to show the case is reachable.
- Artefact: `tests/canonical_storage/test_qa_artefact_constraints.py`.
- Evidence:
  `uv run pytest tests/canonical_storage/test_qa_artefact_constraints.py -q`.
- Non-vacuity: the satisfying witnesses prove the inserts would otherwise
  succeed, so a rejection cannot be attributed to an unrelated error. Negative
  control: drop one `CHECK` from the migration and confirm exactly one case
  fails.

**INV-EPISODE-LINK.** Deleting an episode deletes its evaluations and their
findings; deleting a generation run sets `qa_evaluations.generation_run_id` to
`NULL` and leaves the evaluation in place.

- Method: parameterized integration test against py-pglite.
- Rationale: "linked to canonical episodes" is the roadmap's own phrasing, and
  the `CASCADE`/`SET NULL` asymmetry is deliberate — a QA artefact outlives the
  run that produced it. `compare_metadata` does not compare `ondelete`, so this
  needs a behavioural test.
- Domain: one episode with 2 evaluations and 3 findings; one run deletion.
- Artefact: `tests/canonical_storage/test_qa_artefacts.py`.
- Evidence: `uv run pytest tests/canonical_storage/test_qa_artefacts.py -q`.
- Non-vacuity: assert row counts before and after each delete. Negative
  control: change `SET NULL` to `CASCADE` in the migration and confirm the run
  case fails.

**INV-FILTER-SOUND.** For any stored corpus and any filter
`(evaluator?, compliance_status?)`, the listed items are exactly those
evaluations matching every supplied predicate, and `total` equals the size of
that same set — not the page length.

- Method: property test against the SQL adapter, with the oracle expressed as
  an **independently written Python predicate over the generated corpus**,
  computed in the test body.
- Rationale: the roadmap's retrieval requirement *is* this predicate; the
  classic defect is computing `total` after `LIMIT`. The oracle must not be a
  second adapter: a fake written by the same author from the same spec sentence
  shares any misreading, so it is a second subject, not an oracle. This
  repository has no existing both-implementations contract test to follow.
- Domain: 0–12 evaluations spanning at least 3 evaluators and all 4 compliance
  statuses; filters drawn from `{None} ∪ Evaluator` × `{None} ∪ Status`.
- Artefact: `tests/canonical_storage/test_qa_artefact_properties.py`.
- Evidence:
  `uv run pytest tests/canonical_storage/test_qa_artefact_properties.py -q`.
- Non-vacuity: classify with `hypothesis.event()` and require corpora that
  produce (a) a row matching the evaluator filter but not the compliance
  filter, (b) the converse, and (c) a row matching both. Without the
  conjunction the test passes trivially. Negative control: drop the compliance
  predicate from the adapter's `WHERE` clause and confirm failure; separately,
  compute `total` from the paged result and confirm failure.

**INV-PAGINATION-PARTITION.** For a fixed filter and the canonical ordering
(`evaluated_at DESC, id DESC`), concatenating pages
`(limit=L, offset=0), (limit=L, offset=L), ...` reproduces the full ordered
result exactly once.

- Method: property test over generated corpora and page sizes.
- Rationale: an unstable sort key silently reorders rows between pages.
- Domain: corpus 0–12, `L` in 1–5, including corpora with identical
  `evaluated_at` values; each example scoped to a fresh `episode_id`.
- Artefact: `tests/canonical_storage/test_qa_artefact_properties.py`.
- Evidence: as above.
- Non-vacuity: require at least one `evaluated_at` tie, classified explicitly;
  without ties the tiebreaker is never exercised. Negative control: remove
  `id DESC` from the `ORDER BY` and confirm a duplicate or omission on a
  tie-containing corpus.

**INV-TIMEZONE.** `evaluated_at` is timezone-aware on construction and equals
its stored value after a round trip.

- Method: parameterized test — a naive datetime is rejected by `__post_init__`;
  aware datetimes in UTC and in a non-UTC offset round-trip to equal instants.
- Rationale: a naive value written to `TIMESTAMPTZ` returns aware and
  session-local, so round-trip equality silently breaks — and the tie
  generation in `INV-PAGINATION-PARTITION` is exactly where it surfaces.
- Artefact: `tests/test_qa_artefact_domain.py` and
  `tests/canonical_storage/test_qa_artefacts.py`.
- Evidence: both suites.
- Non-vacuity: include a `+05:30` offset so a naive-equality implementation
  cannot pass by coincidence.

**INV-JSONB-ROUNDTRIP.** `citations` and `details` round-trip through JSONB
preserving value and Python type: `citations` returns as a `tuple[str, ...]`,
`details` as a mapping, including non-ASCII text, empty containers, and nested
structures.

- Method: property test over generated citation tuples and detail mappings.
- Rationale: JSONB returns `list`, so a mapper that forgets to re-tuple breaks
  `QaEvaluation` equality — which every other round-trip assertion relies on.
- Domain: 0–5 citations of length 0–64 including non-ASCII; `details` nested to
  depth 2.
- Artefact: `tests/canonical_storage/test_qa_artefact_properties.py`.
- Evidence: as above.
- Non-vacuity: assert `isinstance(finding.citations, tuple)` explicitly, not
  just equality — `("a",) == ["a"]` is already false, but an implementation
  that compares element-wise would slip past a weaker assertion.

**INV-COUNT-AGREES.** For every evaluation, the `finding_count` returned by the
list endpoint equals `len(findings)` returned by the detail endpoint.

- Method: behavioural scenario in `tests/features/qa_artefact_retrieval.feature`
  plus a repository-level parameterized test.
- Rationale: this single cross-check kills an entire defect class. A
  `finding_count` computed as `len(evaluation.findings)` over a findings-free
  list projection returns `0` for every row estate-wide, and both the
  serializer snapshot and a row-count assertion would still pass.
- Domain: evaluations with 0, 1, and 3 findings.
- Artefact: `tests/steps/test_qa_artefact_retrieval_steps.py`,
  `tests/canonical_storage/test_qa_artefacts.py`.
- Evidence: `uv run pytest tests/steps/test_qa_artefact_retrieval_steps.py -q`.
- Non-vacuity: the 0-finding case must coexist with a non-zero case in the same
  scenario, so a constant `0` fails and a constant `3` fails.

**INV-ENUM-TAXONOMY.** The value sets of `QaEvaluator`, `QaComplianceStatus`,
and `QaFindingSeverity` are exactly those documented in the system design
document and ADR 018.

- Method: parameterized test against literal expected sets.
- Rationale: the enums are persisted as PostgreSQL types; drift between code
  and database is a two-deploy migration, so the taxonomy must not change by
  accident.
- Artefact: `tests/test_qa_artefact_domain.py`.
- Evidence: `uv run pytest tests/test_qa_artefact_domain.py -q`.
- Non-vacuity: the expected sets are literals in the test, not derived from the
  enums. Negative control: add a member and confirm failure.

**LEM-SERIALIZATION-STABLE.** The JSON representation of an evaluation summary,
an evaluation detail, and a list envelope is stable across changes that do not
intend to alter the wire format.

- Method: `syrupy` snapshots over serializer output for four variants: a
  Pedante evaluation with findings; a Chrono evaluation with a runtime estimate
  and no findings; an errored evaluation; and an evaluation carrying a
  `rubric_score`.
- Rationale: the retrieval contract is consumed by the TUI client, and
  multivariant output-format consistency is exactly what this repository
  reserves `syrupy` for. The fourth variant exists specifically to pin how a
  `decimal.Decimal` reaches JSON.
- Artefact: `tests/test_qa_artefact_serializers.py`,
  `tests/__snapshots__/test_qa_artefact_serializers.ambr`.
- Evidence: `uv run pytest tests/test_qa_artefact_serializers.py -q`; the first
  run without `--snapshot-update` fails because no snapshot exists.
- Non-vacuity: the four variants differ in which optional fields are populated,
  so a serializer emitting a constant shape cannot satisfy all four.

**LEM-CLI-RENDERING.** The CLI's table and JSON renderings of a page of
evaluations are deterministic given the same API payload.

- Method: snapshot tests over the pure rendering functions, with the HTTP
  boundary stubbed by `httpx.MockTransport`, plus behavioural scenarios.
- Rationale: the CLI is the second half of `RM-2.2.7-b`; its output is the
  observable behaviour.
- Artefact: `tests/test_qa_cli.py`, `tests/__snapshots__/test_qa_cli.ambr`.
- Evidence: `uv run pytest tests/test_qa_cli.py -q`.
- Non-vacuity: include an empty page and pages with 0 and 3 findings, so a
  renderer that always prints a fixed header row fails.

### Axioms

These are assumed, not verified. Do not write tests for third-party internals.

- CPython 3.14 provides `uuid.uuid7()` and accepts PEP 758 unparenthesized
  `except` clauses.
- PostgreSQL enforces `UNIQUE`, `CHECK`, and `ON DELETE CASCADE`/`SET NULL` as
  documented, and py-pglite runs a real PostgreSQL server faithful to those
  semantics. `ALTER TYPE ... ADD VALUE` cannot use the new value in the same
  transaction.
- SQLAlchemy 2.x async sessions execute the emitted SQL and map results as
  documented, and expose the originating constraint name on an `IntegrityError`
  through `err.orig.diag.constraint_name` for the `psycopg` driver.
- Alembic applies migrations in `down_revision` order, and
  `compare_metadata` does **not** compare `CHECK` constraints or foreign-key
  `ondelete` behaviour.
- Hecate classifies a module by the first configured group whose prefix
  contains it, and does not record edges to modules outside the configured root
  packages.
- Falcon routes by URI template and invokes `on_get` as documented; `cyclopts`
  binds annotated parameters to command-line arguments as documented.
- `tei-rapporteur` extracts spoken text from TEI P5 as Chrono already relies
  upon (fixed by ADR 006).
- Vidai Mock serves OpenAI-compatible chat completions from the configured
  templates.

Where repository-owned logic sits on top of these — the migration's constraint
definitions, the adapter's `ORDER BY`/`WHERE`/`COUNT` construction, the narrowed
`IntegrityError` handling, the CLI's argument binding — it is verified against
the real interface, not against a mock of it.

### Obligations deliberately not discharged formally

The compliance policy is a two-branch total function; Hypothesis coverage over
the full `SupportLevel` × `FindingSeverity` domain, paired with the independent
blocking-set pin, is exhaustive in the material sense, so bounded model
checking or a prover would add ceremony without additional confidence.
CrossHair is not applied because the artefact mapping contains no arithmetic
contracts of the kind `episodic/qa/chrono.py::_compute_estimated_seconds`
carries; note that `make test` depends on the `crosshair` target, so the
existing Chrono gate still runs. If a numeric normalization is later added to
`rubric_score`, revisit this and add a PEP 316 contract.

## Plan of work

### Stage A — understand and propose (no production changes)

Read `AGENTS.md`, the skills listed above, and the documents in
`Conformance basis`. Run the baseline gates on the untouched tree so later
failures are attributable:

```bash
make check-fmt 2>&1 | tee /tmp/checkfmt-episodic-$(git branch --show-current).out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-$(git branch --show-current).out
make lint      2>&1 | tee /tmp/lint-episodic-$(git branch --show-current).out
make test      2>&1 | tee /tmp/test-episodic-$(git branch --show-current).out
```

Run these sequentially; the repository relies on build caching and parallel
gate runs defeat it.

### Stage B — red tests and feature specification

For each milestone, write the failing test *first*. Where the red failure would
otherwise be an import error that hides the intent, mark the test
`@pytest.mark.xfail(strict=True, reason="...")`, observe the expected failure,
then remove the marker as part of the green step. No `xfail` marker survives
into the final tree.

The behavioural specification for the whole slice lives in
`tests/features/qa_artefact_retrieval.feature`:

```gherkin
Feature: QA artefact persistence and retrieval

  Background:
    Given a canonical episode with a generated TEI draft
    And a recorded Pedante evaluation with 3 findings, one of them blocking
    And a recorded Chrono evaluation with a runtime estimate and no findings
    And a recorded Anthem evaluation that failed to execute

  Scenario: Retrieving every QA evaluation for an episode over HTTP
    When the owner requests the episode's QA evaluations
    Then the response lists 3 evaluations ordered newest first
    And each evaluation reports its evaluator and compliance status

  Scenario: The listed finding count matches the detail representation
    When the owner requests the episode's QA evaluations
    And the owner requests each listed evaluation by identifier
    Then every listed finding count equals the number of findings in its detail response

  Scenario: Filtering QA evaluations by evaluator over HTTP
    When the owner requests the episode's QA evaluations for evaluator "pedante"
    Then the response lists 1 evaluation
    And the evaluation's evaluator is "pedante"

  Scenario: Filtering QA evaluations by compliance status over HTTP
    When the owner requests the episode's QA evaluations with compliance status "non_compliant"
    Then the response lists 1 evaluation
    And the evaluation's compliance status is "non_compliant"

  Scenario: Combining evaluator and compliance filters over HTTP
    When the owner requests the episode's QA evaluations for evaluator "chrono" with compliance status "non_compliant"
    Then the response lists 0 evaluations
    And the response reports a total of 0

  Scenario: Retrieving one QA evaluation with its findings
    When the owner requests the recorded Pedante evaluation by identifier
    Then the response includes the evaluation summary
    And the response includes 3 findings ordered as the evaluator emitted them
    And each finding includes its remediation guidance

  Scenario: A different principal cannot read another owner's QA evaluations
    When a different principal requests the episode's QA evaluations
    Then the response status is 404
    And the error code is "qa_evaluation_not_found"

  Scenario: Rejecting an unknown evaluator filter
    When the owner requests the episode's QA evaluations for evaluator "nonsuch"
    Then the response status is 400
    And the error code is "validation_error"
    And the error details name the "evaluator" field

  Scenario: A successful evaluation supersedes an earlier errored one
    When the Anthem evaluation is recorded again with a successful outcome
    And the owner requests the episode's QA evaluations for evaluator "anthem"
    Then the response lists 1 evaluation
    And the evaluation's compliance status is "compliant"

  Scenario: Listing QA evaluations from the command line
    When the operator runs "episodic qa evaluations list --episode <episode_id>"
    Then the command exits with status 0
    And the output table lists 3 evaluations

  Scenario: Filtering QA evaluations from the command line
    When the operator lists QA evaluations with evaluator "pedante" and status "non_compliant"
    Then the command exits with status 0
    And the output table lists 1 evaluation

  Scenario: Emitting machine-readable output from the command line
    When the operator runs "episodic qa evaluations list --episode <episode_id> --format json"
    Then the command exits with status 0
    And the output parses as JSON with 3 items

  Scenario: Reporting a failed command-line request
    When the operator runs a QA listing for an episode that does not exist
    Then the command exits with status 1
    And the error message names the episode identifier

  Scenario: Reporting an unreachable service from the command line
    When the operator runs a QA listing against an unreachable base URL
    Then the command exits with status 3
    And the error message names the base URL
```

Step definitions go in `tests/steps/test_qa_artefact_retrieval_steps.py`, with
shared setup helpers in the non-test module
`tests/steps/qa_artefact_retrieval_support.py` (the repository's convention:
helper modules in `tests/steps/` do not carry the `test_` prefix).

### Stage C — implementation with verification developed alongside

Each milestone below adds production code only after its red test exists.

### Stage D — refactor, documentation, and wider validation

Split any module approaching 400 lines, then run the full gate set and the
documentation gates (`make markdownlint`, `make nixie`). Run `make nixie`
unsandboxed. Note that `make fmt` can introduce MD013 line-length errors on
long inline code spans in Markdown; keep such spans short or wrap them in
fenced blocks.

## Milestones and plateaus

### EP-M0 — Import purity, architecture grouping, and baseline gates

- Identifier and outcome: `EP-M0`. Importing an evaluator contract no longer
  loads LangGraph, the Hecate group memberships for the modules this plan will
  add are declared, and `make check-architecture` passes for the right reason.
- Requirements and gaps: `ADR-014` conformance for all subsequent milestones.
- Work:
  1. Remove `build_chrono_graph`, `build_pedante_graph`, and
     `route_after_pedante` from `episodic/qa/__init__.py` and its `__all__`.
     Verify first that no module imports those names from the barrel; every
     current consumer already imports `episodic.qa.langgraph` or
     `episodic.qa.chrono_langgraph` directly.
  2. Add `tests/test_qa_import_purity.py`, asserting that after
     `import episodic.canonical.qa_artefact_recording` (once it exists; until
     then, `import episodic.qa.pedante.types`), neither `langgraph` nor `httpx`
     appears in `sys.modules` in a fresh subprocess.
  3. In `pyproject.toml`, extend `[tool.hecate]` group prefixes:
     - `domain_ports`: `episodic.observability`, `episodic.qa.pedante.types`,
       `episodic.qa.chrono`, `episodic.canonical.qa_artefacts`,
       `episodic.canonical.qa_artefact_ports`.
     - `application`: `episodic.qa.langgraph`, `episodic.qa.chrono_langgraph`,
       `episodic.canonical.qa_artefact_recording`,
       `episodic.canonical.qa_artefact_service`.
     - `outbound_adapter`: `episodic.canonical.storage.qa_artefact_models`,
       `episodic.canonical.storage.qa_artefact_mappers`,
       `episodic.canonical.storage.qa_artefacts`.
     - `inbound_adapter`: `episodic.api.resources.qa_artefacts`.
     - New group `cli`, declared last: `prefixes = ["episodic.cli"]`,
       `allowed = ["cli", "domain_ports"]`. This is what actually enforces
       ADR 019 — without it, `inbound_adapter` would let the CLI import the
       application services and the API package.
     Do **not** add `episodic.llm`; use `episodic.llm.ports`, which is already
     grouped. Hecate's re-export index resolves
     `from episodic.llm import LLMUsage` in `episodic/qa/pedante/types.py` to
     `episodic.llm.ports.LLMUsage`.
  4. Add `test_no_prefix_shadows_a_later_group` to
     `tests/test_architecture_enforcement.py`: parse `[tool.hecate].groups` and
     assert no prefix in an earlier group is a dotted-prefix ancestor of any
     prefix in a later group.
- Acceptance evidence: `make check-architecture` exits 0; `uv run pytest
  tests/test_qa_import_purity.py tests/test_architecture_enforcement.py -q`
  passes;
  `uv run pytest tests/test_chrono_langgraph.py
  tests/test_pedante_langgraph.py -q`
  still passes after the barrel change. `EV-M0-arch`.
- Conformance check: confirm no pre-existing module changed group. Run the
  shadowing test *before* and after the prefix edit; it must fail if
  `episodic.llm` is added, which is the point.
- Recovery: revert the `pyproject.toml` and `episodic/qa/__init__.py` hunks.
- Remaining gaps: everything else.
- Compatibility decision: none. `episodic.qa`'s barrel is a pre-1.0,
  application-internal surface with no external consumer; removing three
  re-exports needs no alias.

### EP-M1 — QA artefact domain model, compliance policy, and ports

- Identifier and outcome: `EP-M1`. Pure domain types and a port protocol exist
  and are exercised by unit and property tests. Nothing is persisted yet.
- Requirements and gaps: `RM-2.2.7-a`, `TDD-DATA`, `INV-BLOCKING-SET`,
  `INV-ENUM-TAXONOMY`, `INV-TIMEZONE` (domain half).
- Files added:
  - `episodic/canonical/qa_artefacts.py` — enums, `QaFinding`,
    `QaEvaluationSummary`, `QaEvaluation`, validation.
  - `episodic/canonical/qa_artefact_ports.py` — the repository `Protocol`,
    request objects, and error types.
- Acceptance evidence: `uv run pytest tests/test_qa_artefact_domain.py -q`
  passes and fails before the module exists. `EV-M1-domain`.
- Conformance check: no import of Falcon, SQLAlchemy, LangGraph, or `httpx`,
  transitively included; `make check-architecture` and the import-purity test
  still pass.
- Recovery: the modules are additive and unreferenced; delete to revert.
- Remaining gaps: persistence, services, HTTP, CLI.
- Compatibility decision: none. Pre-1.0, no external consumer.

### EP-M2 — Persistence adapter, migration, unit of work, observability

- Identifier and outcome: `EP-M2`. `qa_evaluations` and `qa_findings` exist in
  PostgreSQL, are reachable as `uow.qa_artefacts`, round-trip through the
  adapter, and emit bounded-cardinality metrics and a structured log line.
  `make check-migrations` reports no drift.
- Requirements and gaps: `RM-2.2.7-a`, `TDD-DATA`, `INV-FINDING-ORDER`,
  `INV-REPLAY-IDEMPOTENT`, `INV-ERRORED-SUPERSEDED`, `INV-CONSTRAINT-ENFORCED`,
  `INV-EPISODE-LINK`, `INV-FILTER-SOUND`, `INV-PAGINATION-PARTITION`,
  `INV-JSONB-ROUNDTRIP`, `INV-COUNT-AGREES` (repository half).
- Files added or changed:
  - `episodic/canonical/storage/models_base.py` — three `sa.Enum` constants.
  - `episodic/canonical/storage/qa_artefact_models.py` — two ORM models.
  - `episodic/canonical/storage/qa_artefact_mappers.py` — record/domain
    mappers, including tuple re-hydration for `citations`.
  - `episodic/canonical/storage/qa_artefact_storage_runtime.py` —
    `QaArtefactStorageRuntime` (clock, uuid factory, metrics), mirroring
    `episodic/canonical/storage/generation_run_storage_runtime.py`.
  - `episodic/canonical/storage/qa_artefacts.py` — `SqlAlchemyQaArtefactStore`.
  - `episodic/canonical/storage/uow.py` — instantiate the store in
    `__aenter__` and document it in the class docstring's `Attributes`.
  - `episodic/canonical/unit_of_work_protocols.py` — declare
    `qa_artefacts: QaArtefactRepository`.
  - `alembic/versions/20260823_000013_add_qa_artefact_tables.py` — hand-written
    migration with `down_revision = "20260624_000012"`.
- Acceptance evidence: `uv run pytest tests/canonical_storage -q` passes and
  `make check-migrations` exits 0. `EV-M2-storage`.
- Conformance check: the ORM models must match the migration, or
  `check-migrations` fails; enum constants live in `models_base.py`; the
  `downgrade` drops tables **before** enum types, because `checkfirst=True` on
  `.drop()` checks existence, not dependency.
- Recovery: `alembic downgrade -1` reverses the migration. `upgrade()` creates
  its enums with `checkfirst=True`, so a partially applied run can be retried.
- Remaining gaps: services, HTTP, CLI.
- Compatibility decision: a new persisted format with no deployed predecessor,
  so no data migration of existing rows is required.

### EP-M3 — Recording and query services, and evaluator-result mapping

- Identifier and outcome: `EP-M3`. Application code can record a Pedante
  result, a Chrono estimate, or an evaluator failure against an episode, and
  can query recorded artefacts with filters and pagination.
- Requirements and gaps: `RM-2.2.7-a`, `TDD-QA`, `INV-COMPLIANCE-BLOCKING`,
  `INV-MAPPING-FIDELITY`, `INV-KEY-DETERMINISM`.
- Files added or changed:
  - `episodic/qa/pedante/types.py` — add `PEDANTE_CONTRACT_VERSION`, citing
    ADR 001 as its source of truth.
  - `episodic/canonical/qa_artefact_recording.py` — pure mapping functions, the
    compliance policy, and the idempotency-key minter.
  - `episodic/canonical/qa_artefact_service.py` — `record_qa_evaluation(uow,
    request)` (composable, does not commit), `get_qa_evaluation`,
    `list_qa_evaluations`, and `QaEvaluationRecorder`, an application service
    holding a `uow_factory` and a clock that opens a unit of work, records, and
    commits. `CostRecorder` is the shape to follow.
  - `pyproject.toml` — `[[tool.skylos.dead_code.entrypoints]]` rules for the
    mapping and recording entry points, with a reason naming roadmap item
    `4.4.1` as the verified future caller.
- Acceptance evidence: the recording, recording-property, and service suites
  pass, and `make lint` is clean including the Skylos gate. `EV-M3-service`.

  ```bash
  uv run pytest tests/test_qa_artefact_recording.py \
      tests/test_qa_artefact_recording_properties.py \
      tests/test_qa_artefact_service.py -q
  ```

- Conformance check: `qa_artefact_recording.py` must not import SQLAlchemy or
  Falcon; the service must not import `episodic.canonical.storage`; the
  import-purity test still passes.
- Recovery: additive modules; delete to revert. No schema change.
- Remaining gaps: HTTP, CLI, documentation.
- Compatibility decision: none.

### EP-M4 — REST retrieval filtered by evaluator and compliance status

- Identifier and outcome: `EP-M4`.
  `GET /v1/episodes/{episode_id}/qa-evaluations` and
  `GET /v1/qa-evaluations/{evaluation_id}` serve owner-scoped artefacts with
  the repository's standard pagination and error envelopes.
- Requirements and gaps: `RM-2.2.7-b` (API half), `TUI-API`,
  `LEM-SERIALIZATION-STABLE`, `INV-COUNT-AGREES`.
- Files added or changed:
  - `episodic/api/episode_access.py` — extract the episode-ownership
    resolution currently inlined as `_has_accessible_draft` in
    `episodic/api/resources/episode_tei.py`, and change that module to use it.
    Do this as a separate atomic refactor commit after the QA resources pass,
    per `AGENTS.md`. Writing a third copy of the check is not acceptable.
  - `episodic/api/resources/qa_artefacts.py` — two resource classes.
  - `episodic/api/serializers.py` — `serialize_qa_evaluation_summary`,
    `serialize_qa_evaluation`, `serialize_qa_finding`.
  - `episodic/api/app.py` — `_register_qa_artefact_routes`.
  - `episodic/api/resources/__init__.py` — export the new resources.
  - `pyproject.toml` — add any unused Falcon `req` parameters to the existing
    `[[tool.skylos.dead_code.entrypoints]]` parameter rule.
- Acceptance evidence: the API, serializer, and behavioural suites pass, and
  the REST scenarios pass. `EV-M4-rest`.

  ```bash
  uv run pytest tests/test_qa_artefact_api.py \
      tests/test_qa_artefact_serializers.py \
      tests/steps/test_qa_artefact_retrieval_steps.py -q
  ```

- Conformance check: pagination bounds match `TUI-API`; the error envelope is
  `{code, message, details}`; a foreign principal receives 404 with code
  `qa_evaluation_not_found`, matching `episode_tei.py`'s
  `episode_tei_not_found` convention.
- Recovery: remove the route registration; the resources become unreachable.
- Remaining gaps: CLI, documentation.
- Compatibility decision: new endpoints under `/v1`; no existing route changes.

### EP-M5 — First-party CLI retrieval surface

- Identifier and outcome: `EP-M5`. `episodic qa evaluations list` exists, is
  installed by `[project.scripts] episodic = "episodic.cli:main"`, and reads
  through the REST API.
- Requirements and gaps: `RM-2.2.7-b` (CLI half), `TDD-CLIENT`,
  `LEM-CLI-RENDERING`.
- Files added or changed:
  - `episodic/cli/__init__.py` — `main()`; the only module that writes to
    standard output or exits.
  - `episodic/cli/app.py` — the `cyclopts.App` and global options.
  - `episodic/cli/qa.py` — the `qa evaluations list` command.
  - `episodic/cli/client.py` — a thin `httpx` client and error translation.
  - `episodic/cli/rendering.py` — pure table and JSON renderers.
  - `pyproject.toml` — replace the dead `stilyagi` script with `episodic`,
    move `cyclopts` from the `dev` group into `[project.dependencies]`, and add
    a `[[tool.skylos.dead_code.entrypoints]]` rule for `episodic.cli.main`
    (reached only through `[project.scripts]`) and for the `cyclopts`
    decorator-registered command functions. `scripts/` is outside
    `SKYLOS_PRODUCTION_TARGETS`, so `scripts/local_k8s.py` is not a precedent
    that these are safe.
- Acceptance evidence: the CLI and behavioural suites pass, the CLI scenarios
  pass, and `uv run episodic qa evaluations list --help` prints usage.
  `EV-M5-cli`.

  ```bash
  uv run pytest tests/test_qa_cli.py \
      tests/steps/test_qa_artefact_retrieval_steps.py -q
  ```

- Conformance check: `make check-architecture` exits 0 with the new `cli`
  group, which allows only `cli` and `domain_ports` — so an accidental import of
  `episodic.api` or `episodic.canonical.qa_artefact_service` fails the gate.
- Budget check: before starting, and again before committing, count the
  production modules and net production lines added under `episodic/cli/`. If
  either exceeds 6 modules or 500 lines, take the pre-authorized escalation in
  `Decision log` and split the bootstrap into roadmap addendum item `2.2.8`
  rather than pressing on.
- Recovery: revert the `[project.scripts]` hunk and delete `episodic/cli/`.
- Remaining gaps: documentation.
- Compatibility decision: the removed `stilyagi` entry point references a
  module that does not exist in this repository, so nothing can depend on it.

### EP-M6 — Documentation, ADRs, and roadmap completion

- Identifier and outcome: `EP-M6`. The decisions are recorded, the guides
  describe the new behaviour, and the roadmap entry is marked done.
- Requirements and gaps: `ADR-001` open item; `TDD-DATA` deviation.
- Files added or changed:
  - `docs/adr/adr-018-qa-artefact-persistence-contract.md` — new, following the
    ADR template in `docs/documentation-style-guide.md`. Must cover: the
    unified `qa_evaluations` + `qa_findings` model; the compliance-status
    taxonomy and the exact meaning of `not_applicable`;
    `artefact_schema_version` and `compliance_policy_version` semantics and
    what each bump obliges; artefact immutability and the single
    errored-supersession exception; the decision not to duplicate usage data
    and the correlation rule to the cost ledger; that `ERRORED` has no
    production producer in this slice; the retention posture; and the
    considered alternatives — the generation event log (rejected on the
    `RunAlreadyTerminal` evidence), a JSONB findings array, a
    `lifecycle_status` plus `verdict` split, and derive-at-read compliance.
    Note that extending `qa_evaluator` later is a two-deploy operation.
  - `docs/adr/adr-019-cli-client-boundary.md` — new. Covers the CLI as a REST
    client, the `cyclopts` choice, the dedicated Hecate group that enforces the
    boundary, authentication via `--token`/environment, output-format policy,
    and an explicit statement that the top-level command noun structure is
    provisional until a second command group lands under roadmap item `4.6.1`.
  - `docs/episodic-podcast-generation-system-design.md` — replace the
    `qa_findings` and `brand_compliance_results` bullet in *Data Model and
    Storage* with the tables actually created; add a QA-artefact paragraph to
    *Quality Assurance Stack* referencing ADR 018.
  - `docs/developers-guide.md` — extend *Quality-assurance evaluators* with a
    QA-artefact persistence subsection (module layout, maintainer rules, the
    versioning obligations, the fact that no evaluator populates `rubric_score`
    yet and that `ERRORED` has no production producer, testing conventions),
    and add a *Command-line interface* section. While there, correct the stale
    reference to `episodic/qa/pedante.py`; that module is now the package
    `episodic/qa/pedante/`.
  - `docs/users-guide.md` — extend *Quality & Compliance* with the retrieval
    behaviour, and add the CLI command with a worked example under *Getting
    Started*.
  - `docs/contents.md` — index both new ADRs.
  - `docs/roadmap.md` — mark `2.2.7` `[x]` and record the delivered outcome in
    the same style as the neighbouring completed items.
- Acceptance evidence: `make markdownlint` and `make nixie` exit 0; the full
  gate set exits 0. `EV-M6-docs`.
- Conformance check: every deviation in `Decision log` appears in an ADR or in
  the design document; no trace link points at a file that does not exist.
- Recovery: documentation-only; revert individually.
- Remaining gaps: none for `2.2.7`. Wiring evaluators into the generation graph
  remains roadmap item `4.4.1`; `generation_iterations` remains unimplemented;
  extending the CLI remains item `4.6.1`.
- Compatibility decision: none.

## Interfaces and dependencies

Be prescriptive. These are the shapes that must exist at the end of the
relevant milestone.

### `episodic/canonical/qa_artefacts.py` (EP-M1)

```python
"""Domain model for durable quality-assurance (QA) artefacts."""

QA_ARTEFACT_SCHEMA_VERSION: int = 1
QA_COMPLIANCE_POLICY_VERSION: int = 1

MAX_FINDINGS_PER_EVALUATION: int = 200
MAX_SUMMARY_CHARS: int = 4096
MAX_REMEDIATION_CHARS: int = 4096
MAX_SUBJECT_TEXT_CHARS: int = 2048
MAX_CODE_CHARS: int = 128
MAX_CITATIONS: int = 100
MAX_CITATION_CHARS: int = 256


class QaEvaluator(enum.StrEnum):
    """Evaluator that produced a QA artefact."""

    PEDANTE = "pedante"
    BROMIDE = "bromide"
    CHILTERN = "chiltern"
    ANTHEM = "anthem"
    CAESURA = "caesura"
    CHRONO = "chrono"


class QaComplianceStatus(enum.StrEnum):
    """Whether an evaluation permits the episode to advance."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    NOT_APPLICABLE = "not_applicable"
    ERRORED = "errored"


class QaFindingSeverity(enum.StrEnum):
    """Severity of one QA finding, mirroring the evaluator taxonomy."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dc.dataclass(frozen=True, slots=True)
class QaFinding:
    """One structured problem reported by an evaluator."""

    id: uuid.UUID
    evaluation_id: uuid.UUID
    ordinal: int
    severity: QaFindingSeverity
    code: str
    summary: str
    remediation: str = ""
    subject_id: str = ""
    subject_text: str = ""
    is_blocking: bool = False
    citations: tuple[str, ...] = ()
    details: JsonMapping = dc.field(default_factory=dict)


@dc.dataclass(frozen=True, slots=True)
class QaEvaluationSummary:
    """One recorded evaluator invocation, without its findings."""

    id: uuid.UUID
    episode_id: uuid.UUID
    evaluator: QaEvaluator
    evaluator_version: str
    artefact_schema_version: int
    compliance_policy_version: int
    compliance_status: QaComplianceStatus
    evaluated_at: dt.datetime
    idempotency_key: str
    finding_count: int
    generation_run_id: uuid.UUID | None = None
    summary: str = ""
    rubric_score: decimal.Decimal | None = None
    runtime_estimate_seconds: int | None = None
    evaluator_metadata: JsonMapping = dc.field(default_factory=dict)
    created_at: dt.datetime | None = None


@dc.dataclass(frozen=True, slots=True)
class QaEvaluation:
    """One recorded evaluator invocation together with its findings."""

    summary_record: QaEvaluationSummary
    findings: tuple[QaFinding, ...] = ()
```

Two types, not one with a sometimes-empty tuple. An empty `findings` tuple on a
single type would mean both "this evaluator produced none" and "the list query
did not load them", and no test can tell those apart at the call site.
`list_evaluations` returns `QaEvaluationSummary`; `get_evaluation` and
`record_evaluation` return `QaEvaluation`.

`__post_init__` validation must reject: a negative `runtime_estimate_seconds`; a
`rubric_score` outside `[0, 1]` after quantizing to four decimal places with
`decimal.ROUND_HALF_EVEN`; an empty `evaluator_version`; an empty
`idempotency_key`; a naive `evaluated_at`; a `finding_count` that disagrees with
`len(findings)` on `QaEvaluation`; ordinals that are not `0..n-1` in order;
and any string or collection exceeding the bounds above. The bounds are not
decoration — `summary`, `subject_text`, `remediation`, `citations`, and
`details` all originate in model output, and `generation_runs` already bounds
its own string columns.

### `episodic/canonical/qa_artefact_ports.py` (EP-M1)

```python
@dc.dataclass(frozen=True, slots=True)
class QaEvaluationListRequest:
    """Filter and page selectors for a QA evaluation listing."""

    episode_id: uuid.UUID
    pagination: Pagination
    evaluator: QaEvaluator | None = None
    compliance_status: QaComplianceStatus | None = None


class QaArtefactRepository(typ.Protocol):
    """Persistence port for QA artefacts linked to canonical episodes."""

    async def record_evaluation(self, evaluation: QaEvaluation) -> QaEvaluation:
        """Persist an evaluation and its findings.

        Returns the stored artefact with its findings populated. A repeat of an
        existing ``(episode_id, idempotency_key)`` returns the stored artefact
        unchanged, except that a stored artefact whose compliance status is
        ``ERRORED`` is superseded in place by a later successful recording,
        keeping its identifier.
        """
        ...

    async def get_evaluation(self, evaluation_id: uuid.UUID) -> QaEvaluation | None:
        """Return one evaluation with its findings, or None."""
        ...

    async def list_evaluations(
        self, request: QaEvaluationListRequest
    ) -> tuple[list[QaEvaluationSummary], int]:
        """Return one filtered page of evaluation summaries and the unpaged total."""
        ...
```

Return `tuple[list[...], int]` to match the repository's existing paged-listing
convention (see `episodic/canonical/reference_documents/documents.py`).

### Versioning semantics (EP-M1, formalized in ADR 018)

`artefact_schema_version` versions the **shape of the payload fields** —
`evaluator_metadata`, `QaFinding.details`, and the interpretation of
`QaFinding.code` — not the table columns, which Alembic versions. Rules:

- Adding a new optional key does **not** bump it.
- Changing the meaning of an existing key, removing a key, or changing the
  vocabulary of `code` **does** bump it.
- The mapper must carry the stored value through; it must never fall back to
  the module default, or a mapper bug silently relabels history as version 1.
- A reader that encounters
  `artefact_schema_version > QA_ARTEFACT_SCHEMA_VERSION` must fail loudly
  rather than misparse it: the API returns `422 unprocessable_entity` with code
  `qa_artefact_schema_unsupported`.
- Stored rows are never rewritten by a bump.

`compliance_policy_version` versions the **decision rule** that produced
`compliance_status` and `QaFinding.is_blocking`. Changing
`_BLOCKING_SUPPORT_LEVELS`, or the mapping from any evaluator's outcome to a
compliance status, obliges a bump. Because `code` preserves the raw support
level, historical rows can be re-derived by a backfill; without the version
column there would be no way to tell a re-derivable row from an authoritative
one.

Both versions are `NOT NULL` and are set explicitly by the recording service.

### Database schema (EP-M2)

```sql
CREATE TABLE qa_evaluations (
    id                        UUID PRIMARY KEY,
    episode_id                UUID NOT NULL REFERENCES episodes (id) ON DELETE CASCADE,
    generation_run_id         UUID     REFERENCES generation_runs (id) ON DELETE SET NULL,
    evaluator                 qa_evaluator NOT NULL,
    evaluator_version         TEXT NOT NULL,
    artefact_schema_version   INTEGER NOT NULL,
    compliance_policy_version INTEGER NOT NULL,
    compliance_status         qa_compliance_status NOT NULL,
    summary                   TEXT NOT NULL DEFAULT '',
    rubric_score              NUMERIC(5, 4),
    runtime_estimate_seconds  INTEGER,
    finding_count             INTEGER NOT NULL DEFAULT 0,
    evaluator_metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key           TEXT NOT NULL,
    evaluated_at              TIMESTAMPTZ NOT NULL,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_qa_evaluations_episode_idempotency_key UNIQUE (episode_id, idempotency_key),
    CONSTRAINT ck_qa_evaluations_rubric_score_unit_interval
        CHECK (rubric_score IS NULL OR (rubric_score >= 0 AND rubric_score <= 1)),
    CONSTRAINT ck_qa_evaluations_runtime_estimate_non_negative
        CHECK (runtime_estimate_seconds IS NULL OR runtime_estimate_seconds >= 0),
    CONSTRAINT ck_qa_evaluations_finding_count_non_negative CHECK (finding_count >= 0)
);

CREATE INDEX ix_qa_evaluations_episode_evaluated_at
    ON qa_evaluations (episode_id, evaluated_at DESC, id DESC);
CREATE INDEX ix_qa_evaluations_episode_evaluator_evaluated_at
    ON qa_evaluations (episode_id, evaluator, evaluated_at DESC, id DESC);

CREATE TABLE qa_findings (
    id            UUID PRIMARY KEY,
    evaluation_id UUID NOT NULL REFERENCES qa_evaluations (id) ON DELETE CASCADE,
    ordinal       INTEGER NOT NULL,
    severity      qa_finding_severity NOT NULL,
    code          TEXT NOT NULL,
    summary       TEXT NOT NULL,
    remediation   TEXT NOT NULL DEFAULT '',
    subject_id    TEXT NOT NULL DEFAULT '',
    subject_text  TEXT NOT NULL DEFAULT '',
    is_blocking   BOOLEAN NOT NULL,
    citations     JSONB NOT NULL DEFAULT '[]'::jsonb,
    details       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_qa_findings_evaluation_ordinal UNIQUE (evaluation_id, ordinal),
    CONSTRAINT ck_qa_findings_ordinal_non_negative CHECK (ordinal >= 0)
);
```

Two indexes, both ending in the full sort key. The canonical listing order is
`evaluated_at DESC, id DESC`; `id` is load-bearing because identifiers are
UUIDv7 and therefore monotonic with creation time, so without it evaluations
sharing an `evaluated_at` can swap between pages.

`ix_qa_evaluations_episode_evaluated_at` serves the unfiltered listing — the
default for both the API and the CLI — and the compliance-filtered listing,
where four status values are filtered off an already-ordered episode scan. No
separate compliance index: at realistic cardinality (tens of evaluations per
episode) it would buy a filter and cost a sort. If compliance filtering ever
dominates, a partial index on `non_compliant` beats a full one.

No index on `qa_findings.severity`: the only query is "all findings for one
evaluation, ordered by ordinal", which the unique constraint's btree on
`(evaluation_id, ordinal)` already serves. Do not add indexes without a
measured query.

Enum constants in `episodic/canonical/storage/models_base.py`, following the
existing `GENERATION_RUN_STATUS` pattern exactly:

```python
QA_EVALUATOR = sa.Enum(
    QaEvaluator,
    name="qa_evaluator",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
QA_COMPLIANCE_STATUS = sa.Enum(
    QaComplianceStatus,
    name="qa_compliance_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
QA_FINDING_SEVERITY = sa.Enum(
    QaFindingSeverity,
    name="qa_finding_severity",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
```

The migration creates each PostgreSQL enum with a local `_enum(name, *values)`
helper returning `postgresql.ENUM(..., create_type=False)` and explicit
`.create(op.get_bind(), checkfirst=True)` calls, exactly as
`alembic/versions/20260624_000010_add_generation_run_tables.py` does. The
`downgrade` drops indexes, then `qa_findings`, then `qa_evaluations`, then the
three enum types — in that order. `checkfirst=True` on `.drop()` checks
existence, not dependency, so dropping an enum while a table still references
it fails mid-transaction.

### `episodic/canonical/storage/qa_artefacts.py` (EP-M2)

`SqlAlchemyQaArtefactStore` follows `SqlAlchemyGenerationRunStore` rather than
`_RepositoryBase`, because it needs savepoint-and-requery inserts. It does
**not** subclass `QaArtefactRepository`; conformance is structural, so a
forgotten method is a type error rather than an inherited no-op body. That
matches `SqlAlchemyGenerationRunStore`.

```python
class SqlAlchemyQaArtefactStore:
    """PostgreSQL-backed QA artefact store."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        runtime: QaArtefactStorageRuntime | None = None,
    ) -> None: ...
```

`QaArtefactStorageRuntime` mirrors
`episodic/canonical/storage/generation_run_storage_runtime.py`: a frozen
dataclass carrying `clock`, `uuid_factory`, and `metrics`, defaulting to
`dt.datetime.now(dt.UTC)`, `uuid.uuid7`, and `NoopMetrics`.

`record_evaluation` must:

1. Open `session.begin_nested()`, add the evaluation and its findings, and
   `flush()`.
2. On `IntegrityError`, inspect `err.orig.diag.constraint_name`. Treat **only**
   `uq_qa_evaluations_episode_idempotency_key` as a replay; re-raise anything
   else, including any `qa_findings` constraint. This narrowing is not
   optional. The service does not commit, so `record_evaluation` runs inside a
   caller's unit of work alongside other pending work; `flush()` flushes the
   whole session, so an unrelated failure would otherwise be caught, rolled
   back to this savepoint (discarding the unrelated change), and — if a row for
   the key happens to exist — reported as a successful replay.
3. Re-select by `(episode_id, idempotency_key)` **with its findings**. If the
   stored artefact's `compliance_status` is `ERRORED` and the incoming one is
   not, delete its findings, update its mutable fields in place, insert the new
   findings, and return the updated artefact keeping the stored identifier.
   Otherwise return the stored artefact unchanged.
4. Emit `_log_event("info", "sql_qa_artefact_store.record_evaluation", ...)`
   with `evaluator`, `episode_id`, and boolean `replayed`/`superseded` flags —
   never finding text.
5. Emit metrics through the runtime's `MetricsPort`, all labels
   bounded-cardinality: `qa_evaluation_recorded{evaluator, compliance_status}`,
   `qa_evaluation_replayed{evaluator, stored_status}`,
   `qa_evaluation_record_failed{evaluator, error_category}`. The prohibition on
   logging finding text is satisfied by choosing labels, not by emitting
   nothing. Without these the 03:00 responder has no signal at all that
   recording is failing; the only observable would be "the table is emptier
   than expected", which nobody alerts on.

`list_evaluations` issues two statements — a
`select(...).order_by(...).limit().offset()` for the page and a
`select(sa.func.count()).select_from(...)` for the total — both built from one
shared private helper, `_evaluation_filters(request)`, returning a list of
criteria. Sharing the helper is what makes `INV-FILTER-SOUND` structurally hard
to break. The page query is single-table because `finding_count` is a stored
column, so no join or correlated subquery is needed.

### `episodic/canonical/qa_artefact_recording.py` (EP-M3)

```python
def compliance_status_for_pedante(
    result: PedanteEvaluationResult,
) -> QaComplianceStatus:
    """Return the compliance status implied by a Pedante result."""


def qa_idempotency_key(
    *,
    evaluator: QaEvaluator,
    evaluator_version: str,
    compliance_policy_version: int,
    tei_content_hash: str,
    generation_run_id: uuid.UUID | None,
) -> str:
    """Derive the deterministic idempotency key for one evaluation."""


def evaluation_from_pedante(
    result: PedanteEvaluationResult,
    *,
    episode_id: uuid.UUID,
    tei_content_hash: str,
    evaluated_at: dt.datetime,
    generation_run_id: uuid.UUID | None = None,
    uuid_factory: cabc.Callable[[], uuid.UUID] = uuid.uuid7,
) -> QaEvaluation:
    """Project a Pedante result onto a persistable QA evaluation."""


def evaluation_from_chrono(...) -> QaEvaluation:
    """Project a Chrono runtime estimate onto a persistable QA evaluation."""


def evaluation_from_failure(
    evaluator: QaEvaluator,
    *,
    episode_id: uuid.UUID,
    evaluator_version: str,
    tei_content_hash: str,
    error_category: str,
    summary: str,
    evaluated_at: dt.datetime,
    generation_run_id: uuid.UUID | None = None,
    uuid_factory: cabc.Callable[[], uuid.UUID] = uuid.uuid7,
) -> QaEvaluation:
    """Record a failed evaluator invocation as an errored QA evaluation."""
```

The key is derived, never passed in:

```plaintext
qa:{evaluator}:v{evaluator_version}:policy:{compliance_policy_version}
:tei:{tei_content_hash}:run:{generation_run_id or '-'}
```

The key is a single line; it is shown wrapped above only to fit the page width.

It contains no clock reading, no random value, and no attempt counter. A key
that folded in `evaluated_at` would defeat replay entirely, and an attempt
counter would grow a row per retry; the errored-supersession rule handles
retries instead. `evaluated_at` is supplied by `QaEvaluationRecorder` from its
injected clock, not by arbitrary callers, so "newest first" means what it says.

Mapping rules, pinned by `INV-MAPPING-FIDELITY`:

- Pedante: `evaluator_version = PEDANTE_CONTRACT_VERSION`;
  `summary = result.summary`; `evaluator_metadata` carries `model`,
  `provider_response_id`, and `finish_reason`; each `PedanteFinding` becomes a
  `QaFinding` with `code = finding.support_level.value`,
  `subject_id = finding.claim_id`, `subject_text = finding.claim_text`,
  `citations = finding.cited_source_ids`,
  `details = {"claim_kind": finding.claim_kind.value}`,
  `is_blocking = finding.is_blocking`, and `ordinal` following emission order.
  `compliance_status` is `NON_COMPLIANT` when any finding is blocking, else
  `COMPLIANT`.
- Chrono: `runtime_estimate_seconds = estimate.estimated_seconds`;
  `evaluator_version = estimate.metadata.estimator_version`;
  `evaluator_metadata` carries the whole `ChronoEstimatorMetadata` projection;
  `findings` is empty; `compliance_status` is `NOT_APPLICABLE`, meaning "this
  evaluator renders no compliance verdict under policy version 1", not "not
  applicable to this episode".
- Failure: `compliance_status = ERRORED`; `evaluator_metadata` carries
  `error_category`; `findings` is empty.

Do not store `LLMUsage` on the artefact. Correlation to the cost ledger is
`generation_run_id` plus `evaluator_metadata["provider_response_id"]`, which
together reconstruct the ledger idempotency key format used in
`episodic/generation/launcher_support.py`.

### HTTP contract (EP-M4)

`GET /v1/episodes/{episode_id}/qa-evaluations`

Query parameters: `evaluator` (optional `QaEvaluator` value),
`compliance_status` (optional `QaComplianceStatus` value), `limit` (default 20,
1–100), `offset` (default 0, ≥ 0). Parse with `parse_enum_param` and
`parse_pagination` from `episodic/api/helpers.py`; do not hand-roll parsers as
`episodic/api/resources/generation_runs.py` was obliged to for its cursor
scheme.

Response `200`:

```json
{
  "items": [
    {
      "id": "0199a0c2-1e2a-7c7f-9a1e-6f0a1b2c3d4e",
      "episode_id": "0199a0c1-0000-7000-8000-000000000001",
      "generation_run_id": "0199a0c1-0000-7000-8000-000000000002",
      "evaluator": "pedante",
      "evaluator_version": "2026-03-24",
      "artefact_schema_version": 1,
      "compliance_policy_version": 1,
      "compliance_status": "non_compliant",
      "summary": "One claim lacks source support.",
      "rubric_score": null,
      "runtime_estimate_seconds": null,
      "finding_count": 1,
      "evaluator_metadata": {"model": "gpt-4.1", "finish_reason": "stop"},
      "evaluated_at": "2026-08-23T10:15:00+00:00"
    }
  ],
  "limit": 20,
  "offset": 0,
  "total": 1
}
```

`GET /v1/qa-evaluations/{evaluation_id}` returns the same object **plus** a
`findings` array. `finding_count` is present in both representations, so a
client can decode one shape; the detail response is a superset of the list
item, which is how every other resource in this repository behaves
(`serialize_generation_run` and `serialize_reference_document` are each used
for both list and detail). Each finding serializes as
`{id, ordinal, severity, code, summary, remediation, subject_id, subject_text,
is_blocking, citations, details}`.

`rubric_score` serializes as a **JSON number** produced by `float(score)`. The
authoritative precision is the column's four decimal places; every value in
`[0, 1]` at four decimal places round-trips exactly through `json.dumps`'s
shortest-repr float formatting. Falcon's default media handler cannot serialize
a `decimal.Decimal` and no handler for one exists anywhere in `episodic/`, so
converting in the serializer is mandatory, not stylistic. The fourth snapshot
variant in `LEM-SERIALIZATION-STABLE` pins it.

Authorization mirrors `episodic/api/resources/episode_tei.py`: resolve the
episode, resolve its `last_generation_run_id`, and require
`run.actor == principal_id(req)`. An episode that does not exist, has no
generation run, or belongs to another principal all return `404` with code
`qa_evaluation_not_found` — never `403`, which would leak existence.

Note a deliberate divergence from `docs/episodic-tui-api-design.md`: an
*unauthenticated* request also receives `404`, because `principal_id(req)` is
`None` and the existing `episode_tei.py` precedent returns not-found in that
case rather than `401 unauthorized`. This plan follows the code, not the
document, so the two episode-scoped read surfaces behave alike. Record the
divergence in ADR 018's *Outstanding decisions* and raise `401` handling as a
separate item rather than fixing it here.

An unknown `evaluator` or `compliance_status` value returns `400` with code
`validation_error` and `details.field` naming the offending parameter, which is
what `parse_enum_param` already produces.

### CLI contract (EP-M5)

```plaintext
episodic [--base-url URL] [--token TOKEN] [--timeout SECONDS] qa evaluations list
    --episode UUID
    [--evaluator {pedante,bromide,chiltern,anthem,caesura,chrono}]
    [--compliance-status {compliant,non_compliant,not_applicable,errored}]
    [--limit N] [--offset N]
    [--format {table,json}]
```

`--base-url` defaults to the `EPISODIC_API_URL` environment variable, then to
`http://127.0.0.1:8000`. `--token` defaults to `EPISODIC_API_TOKEN`; it is sent
as `Authorization: Bearer <token>`. Never echo the token, and never place it in
a rendered table.

Exit codes: `0` success; `1` the API returned an error envelope (print
`message` to standard error, prefixed with the HTTP status); `2` usage error
(left to `cyclopts`); `3` the API was unreachable or timed out; `4` the API
returned `429 rate_limited` (print the `Retry-After` value if present, so a
throttled operator is not told "unknown error"). Because an unauthenticated
request receives `404`, a `404` response with no `EPISODIC_API_TOKEN` set must
add the hint "no API token configured; set EPISODIC_API_TOKEN or pass --token"
— otherwise the commonest setup mistake reads as "that episode does not exist".

`--format table` prints a fixed-width table with columns `EVALUATOR`, `STATUS`,
`FINDINGS`, `EVALUATED AT`, `ID`, followed by a summary line
`3 of 3 evaluations`. `--format json` prints the API envelope verbatim,
pretty-printed with two-space indentation and a trailing newline, so it can be
piped into `jq`.

Keep the `cyclopts.App` construction, the HTTP client, and the renderers in
separate modules. The renderers must be pure functions from a parsed payload to
a string so `syrupy` can snapshot them without a process boundary; only
`episodic/cli/__init__.py` may write to standard output or exit.

## Module budget

Plan the splits before writing. Estimates are calibrated against the modules
each one mirrors: `episodic/canonical/storage/generation_runs.py` is 367 lines,
`generation_run_models.py` 155, `generation_persistence.py` 371,
`alembic/versions/20260624_000010_add_generation_run_tables.py` 194.

| Module                                                       | Estimate      | Split if it grows                                                                                                            |
| ------------------------------------------------------------ | ------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `episodic/canonical/qa_artefacts.py`                         | 280–380       | move the three enums to `qa_artefact_enums.py`                                                                               |
| `episodic/canonical/qa_artefact_ports.py`                    | 90–130        | none expected                                                                                                                |
| `episodic/canonical/storage/qa_artefact_models.py`           | 140–180       | none expected                                                                                                                |
| `episodic/canonical/storage/qa_artefact_mappers.py`          | 90–130        | none expected                                                                                                                |
| `episodic/canonical/storage/qa_artefact_storage_runtime.py`  | 50–60         | none expected                                                                                                                |
| `episodic/canonical/storage/qa_artefacts.py`                 | 350–450       | split reads into `qa_artefact_queries.py` (get, list, `_evaluation_filters`, count), leaving the savepoint write path behind |
| `alembic/versions/20260823_000013_add_qa_artefact_tables.py` | 180–230       | none expected                                                                                                                |
| `episodic/canonical/qa_artefact_recording.py`                | 250–320       | split per evaluator once Bromide or Anthem land                                                                              |
| `episodic/canonical/qa_artefact_service.py`                  | 150–200       | none expected                                                                                                                |
| `episodic/api/resources/qa_artefacts.py`                     | 200–280       | see below                                                                                                                    |
| `episodic/api/episode_access.py`                             | 60–90         | new shared helper                                                                                                            |
| `episodic/cli/*` (5 modules)                                 | 350–500 total | see the pre-authorized escalation                                                                                            |

Two notes that change the work rather than describing it:

- Resolving "does this principal own this episode?" would otherwise be a
  *third* copy of `episodic/api/resources/episode_tei.py`'s
  `_has_accessible_draft`. Extract it to `episodic/api/episode_access.py` and
  have `episode_tei.py` use it, as a separate atomic refactor commit after the
  functional change, per `AGENTS.md`. Do not write the third copy.
- `episodic/canonical/storage/qa_artefacts.py` is the module most likely to
  breach 400 lines, because it carries an idempotent insert, an
  errored-supersession path, a filtered page query, and a count. Decide the
  read/write split at `EP-M2` while the port contract tests are still being
  written; retrofitting it afterwards is rework.

## Concrete steps

Work from the repository root,
`/home/leynos/.lody/repos/github---leynos---episodic/worktrees/c456469d-cdcd-4f92-bc74-871616264ba0`,
on branch `2-2-7-persist-qa-artefacts-linked-to-canonical-episodes.md`.

1. Establish the baseline. Run the four gates sequentially with `tee` as shown
   in Stage A. Expect all four to pass on the unmodified tree.

2. `EP-M0`. Add the shadowing guard test and the import-purity test first, and
   confirm the import-purity test fails:

   ```bash
   uv run pytest tests/test_qa_import_purity.py -q
   ```

   Expect a failure reporting `langgraph` present in `sys.modules`. Then slim
   `episodic/qa/__init__.py`, edit the `[tool.hecate]` groups, and run:

   ```bash
   make check-architecture 2>&1 | tee /tmp/arch-episodic-$(git branch --show-current).out
   uv run pytest tests/test_qa_import_purity.py tests/test_architecture_enforcement.py \
       tests/test_chrono_langgraph.py tests/test_pedante_langgraph.py -q
   ```

   Expect:

   ```plaintext
   hecate: architecture check passed
   ```

   Commit: `Isolate QA evaluator contracts from LangGraph imports`.

3. `EP-M1` red. Add `tests/test_qa_artefact_domain.py` covering
   `INV-BLOCKING-SET`, `INV-ENUM-TAXONOMY`, `INV-TIMEZONE` (domain half), and
   the `__post_init__` rejections. Run:

   ```bash
   uv run pytest tests/test_qa_artefact_domain.py -q
   ```

   Expect
   `ModuleNotFoundError: No module named 'episodic.canonical.qa_artefacts'`.

4. `EP-M1` green. Add `episodic/canonical/qa_artefacts.py` and
   `episodic/canonical/qa_artefact_ports.py`. Re-run, expect passes, run the
   `INV-BLOCKING-SET` negative control, revert it, and commit.

5. `EP-M2` red. Add `tests/canonical_storage/test_qa_artefacts.py`. Run it and
   expect failure because `uow.qa_artefacts` does not exist.

6. `EP-M2` green. Add the enum constants, ORM models, mappers, storage runtime,
   store, unit-of-work registration, protocol attribute, and the migration.
   Then:

   ```bash
   make check-migrations 2>&1 | tee /tmp/migrations-episodic-$(git branch --show-current).out
   uv run pytest tests/canonical_storage -q
   ```

   Expect no drift and a passing storage suite. Add the property, replay, and
   constraint test modules; run each negative control once and observe it fail
   for the intended reason. Verify `alembic downgrade -1` then
   `alembic upgrade head` succeeds, which is the only way the enum-drop
   ordering gets exercised. Commit.

7. `EP-M3`. Red then green for `episodic/canonical/qa_artefact_recording.py`,
   `episodic/canonical/qa_artefact_service.py`, and `PEDANTE_CONTRACT_VERSION`.
   Add the Skylos entry-point rules in the same commit as the code they cover,
   not later. Commit.

8. Milestone gate. Run the full sequence and expect all four to pass:

   ```bash
   make check-fmt && make typecheck && make lint && make test
   ```

   Prefer delegating this run to the `scrutineer` subagent, which executes the
   gates sequentially, captures each to a log under `/tmp`, and returns a
   bounded report. Note `make test` depends on the `crosshair` target, so the
   existing Chrono contract gate runs too.

9. `EP-M4`. Write the REST scenarios of
   `tests/features/qa_artefact_retrieval.feature` and its step module; confirm
   they fail. Add the resources, serializers, and route registration; confirm
   they pass. Generate the `syrupy` snapshots with a first run, read the
   `.ambr` file before committing it, and only then accept it. Commit.

10. `EP-M5`. Add the CLI scenarios; confirm they fail. Add `episodic/cli/`,
    update `[project.scripts]`, move `cyclopts` to runtime dependencies, and run
    `uv sync`. Confirm:

    ```bash
    uv run episodic qa evaluations list --help
    ```

    prints usage, and that `make check-architecture` still passes with the new
    `cli` group. Commit.

11. Milestone gate again (step 8).

12. `EP-M6`. Write both ADRs against the template in
    `docs/documentation-style-guide.md`, update the design document,
    developers' guide, users' guide, `docs/contents.md`, and mark
    `docs/roadmap.md` item `2.2.7` done. Then:

    ```bash
    make fmt
    make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-$(git branch --show-current).out
    make nixie        2>&1 | tee /tmp/nixie-episodic-$(git branch --show-current).out
    ```

    `make fmt` can introduce MD013 violations on long inline code spans; if
    `markdownlint` reports MD013 after formatting, shorten or fence the
    offending span rather than raising the line limit. Run `make nixie`
    unsandboxed. Commit.

13. Final gate. Run step 8 once more, then set this plan's Status to
    `COMPLETE` and fill in `Outcomes & retrospective`.

## Validation and acceptance

Acceptance is behavioural, not structural.

**Red-Green-Refactor evidence to record.** For each milestone, capture the red
command and its failure, the green command and its pass, and the refactor
command and its pass. For example, at `EP-M1`:

```plaintext
$ uv run pytest tests/test_qa_artefact_domain.py -q
ERROR tests/test_qa_artefact_domain.py - ModuleNotFoundError: No module named
'episodic.canonical.qa_artefacts'
1 error in 0.42s
```

then, after adding the module:

```plaintext
$ uv run pytest tests/test_qa_artefact_domain.py -q
..............                                                      [100%]
14 passed in 0.51s
```

**BDD evidence.** The feature file must fail before `EP-M4`/`EP-M5` and pass
after:

```bash
uv run pytest tests/steps/test_qa_artefact_retrieval_steps.py -q
```

**End-to-end acceptance, observed by a human.** With PostgreSQL available and
migrations applied, start the API, create an episode through the existing
source-to-script slice, record a Pedante evaluation, then:

```bash
curl -sS -H "Authorization: Bearer $EPISODIC_API_TOKEN" \
  "http://127.0.0.1:8000/v1/episodes/$EPISODE_ID/qa-evaluations?evaluator=pedante&compliance_status=non_compliant" \
  | jq '{total, first: .items[0].evaluator, findings: .items[0].finding_count}'
```

Expect:

```json
{
  "total": 1,
  "first": "pedante",
  "findings": 1
}
```

and from the terminal:

```bash
EPISODIC_API_TOKEN=$EPISODIC_API_TOKEN \
  uv run episodic qa evaluations list --episode "$EPISODE_ID" --evaluator pedante
```

Expect:

```plaintext
EVALUATOR  STATUS          FINDINGS  EVALUATED AT          ID
pedante    non_compliant          1  2026-08-23T10:15:00Z  0199a0c2-1e2a-7c7f-9a1e-6f0a1b2c3d4e

1 of 1 evaluations
```

Quality criteria (what "done" means):

- Tests: `make test` passes with no skipped new tests other than those gated on
  Vidai Mock availability, and every scenario in
  `tests/features/qa_artefact_retrieval.feature` passes.
- Verification: every obligation in `Verification plan` is discharged by its
  named artefact, and each negative control has been run once and observed to
  fail for the intended reason. Record which controls were run and what they
  reported.
- Lint and typecheck: `make check-fmt`, `make typecheck`, and `make lint` all
  exit 0. `make lint` includes the blocking Skylos dead-code scan; investigate
  every finding rather than suppressing it. Where a symbol is genuinely
  reachable only from future roadmap work, use a typed entry-point rule in
  `[tool.skylos.dead_code]` naming that work, matching methods as
  `type = "method"`.
- Migrations: `make check-migrations` reports no drift, and
  `alembic downgrade -1 && alembic upgrade head` round-trips.
- Documentation: `make markdownlint` and `make nixie` exit 0.
- Performance: no benchmark threshold applies. The two indexes on
  `qa_evaluations` cover the documented filters; do not add further indexes
  without a measured query. Keep `make test` inside the 180-second per-test
  timeout by holding `max_examples` at 5–6.
- Security: the artefact stores evaluator summaries and remediation text, which
  may quote script content. Do not log finding text, do not place it in metric
  labels, and keep the CLI from writing the bearer token to standard output.

Quality method (how we check): run each gate sequentially via `make`,
delegating full gate runs to the `scrutineer` subagent so bulky output stays
out of the working context. When a gate fails, read the cited log under `/tmp`
rather than re-running it; re-run only after applying a fix.

## Idempotence and recovery

Every step is re-runnable. The Alembic migration is the only step that mutates
persistent state; `alembic downgrade -1` reverses it, and `upgrade()` creates
its enums with `checkfirst=True` so a partially applied run can be retried.
Test databases are ephemeral py-pglite instances recreated per test function,
so a failed storage test leaves nothing behind.

`uv sync` after the dependency change is idempotent. If the `episodic` console
script does not appear on `PATH`, re-run `uv sync` and invoke it as
`uv run episodic`.

No step deletes or overwrites tracked content other than the three re-exports
removed from `episodic/qa/__init__.py` and the `stilyagi` entry in
`[project.scripts]`, which references a module that does not exist in this
repository. Confirm both with a repository-wide search before removing them.

Keep `/tmp` logs; they are the evidence trail for this plan. Delete them only
after the retrospective is written.

## Artefacts and notes

Expected `make check-migrations` output at `EP-M2`:

```plaintext
No schema drift detected between models and migrations.
```

Expected Hecate output at `EP-M0`:

```plaintext
hecate: architecture check passed
```

Expected import-purity failure before `EP-M0`'s barrel change:

```plaintext
E  AssertionError: importing episodic.qa.pedante.types loaded ['httpx', 'langgraph']
```

Expected first `syrupy` run at `EP-M4`, before snapshots exist:

```plaintext
E  AssertionError: assert [+ received] == [- snapshot]
   Snapshot 'test_serialize_pedante_evaluation' does not exist!
```

after `uv run pytest tests/test_qa_artefact_serializers.py --snapshot-update`:

```plaintext
4 snapshots generated.
```

Inspect `tests/__snapshots__/test_qa_artefact_serializers.ambr` before
committing it. A snapshot accepted without reading is a test that asserts
whatever the code happened to do.

## Revision note

Revision 2, 2026-08-23. Revised after a six-lens design review.

What changed. `EP-M0` now removes the LangGraph re-exports from
`episodic/qa/__init__.py` and adds an import-purity test, because importing any
evaluator contract was verified to load `langgraph` and `httpx`; it drops the
proposed `episodic.llm` Hecate prefix, which would have silently reclassified
the OpenAI adapters out of `outbound_adapter` while the gate still reported
success, and adds a guard test for that whole class of mistake. The domain
model splits `QaEvaluationSummary` from `QaEvaluation` and adds a stored
`finding_count`, resolving a contract that the previous revision could not have
implemented. `compliance_policy_version` joins `artefact_schema_version`, and
both now have stated semantics rather than a promise to define them later. The
idempotency key gains a derivation rule, artefacts gain a documented
errored-supersession exception, `rubric_score` gains a JSON representation, the
store gains metrics and structured logging and a constraint-name-narrowed
exception handler, the index set is rebuilt around the actual queries, and
`episodic.cli` gains its own Hecate group so ADR 019 is enforced rather than
merely intended. The verification plan drops an infeasible
`RuleBasedStateMachine` and a precedent that does not exist, replaces two
negative controls that would have failed for the wrong reason, and adds seven
obligations — blocking-set independence, mapping fidelity, key determinism,
errored supersession, constraint enforcement, timezone handling, JSONB
round-tripping, count agreement, and enum taxonomy. `EP-M5` drops the `show`
sub-command.

The tolerance was rewritten to count files honestly — the measured budget is
about 46 files, close to the 50 ceiling — and a *Module budget* section now
plans the splits before writing rather than after. `EP-M4` extracts the shared
episode-ownership check into `episodic/api/episode_access.py` instead of adding
a third copy of it. Three gate facts that are easy to discover the hard way are
now stated: `make test` depends on the CrossHair target, Skylos scans
production targets only so a test-only caller counts as dead, and
`make typecheck` runs `ty` alone.

How it affects the remaining work. Scope grew by roughly two modules and a
dozen test cases; nothing has been implemented yet, so all of the above is
still design. `EP-M0` is now the riskiest milestone rather than a formality and
must be completed and gated before `EP-M1` begins. `EP-M5` carries a
pre-authorized escalation: if the CLI bootstrap breaches its budget, split it
into a roadmap addendum item `2.2.8` rather than letting this item sprawl.

Revision 3, 2026-08-23. No design change. The two open questions put to the
reviewer were ruled on and the answers recorded in `Decision log`: the
`brand_compliance_results` deviation from `TDD-DATA` is accepted, with the
upstream document edits it obliges named explicitly; and the CLI stays in scope
for `2.2.7`, with splitting the bootstrap up front offered and declined. The
budget-triggered escalation remains available and needs no further approval.
Neither decision is an open proposal any more, so implementation is not blocked
on them. The plan's Status stays `DRAFT` because the plan as a whole has not
yet been approved for implementation — only these two decisions have.
