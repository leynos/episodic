# Persist QA artefacts linked to canonical episodes

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, `Outcomes & Retrospective`, `Conformance Basis`, and
`Verification Plan` must be kept up to date as work proceeds.

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
  `GET /v1/episodes/{episode_id}/qa-evaluations?evaluator=pedante&compliance_status=non_compliant`,
  and
- from a terminal, with a new first-party command-line interface (CLI):
  `episodic qa evaluations list --episode <uuid> --evaluator pedante --compliance-status non_compliant`.

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
  `qa_status is QaStatus.SKIPPED` whenever `quality_mode is
  QualityMode.DRAFT_WITHOUT_QA`. Widening either enum would change generation
  semantics that Architecture Decision Record (ADR) 017 fixed for the no-QA
  slice. QA compliance is modelled by a *new, separate* enum on the artefact.
- Do not duplicate token-usage or cost data. `episodic/cost/` already records
  normalized usage and priced ledger entries per provider call
  (`episodic/cost/recorder.py`, `episodic/cost/storage/models.py`). QA
  artefacts must correlate to that ledger, not re-store token counts.
- Preserve the hexagonal architecture boundaries enforced by Hecate
  (`[tool.hecate]` in `pyproject.toml`, gate `make check-architecture`). Domain
  modules must not import Falcon, SQLAlchemy, LangGraph, `httpx`, or Celery.
- Preserve the canonical persistence conventions: UUIDv7 primary keys generated
  application-side, `postgresql.UUID(as_uuid=True)` columns,
  `sa.DateTime(timezone=True)` timestamps, `postgresql.JSONB` for structured
  payloads, module-level `sa.Enum(..., values_callable=...)` constants in
  `episodic/canonical/storage/models_base.py`, and hand-written Alembic
  migrations.
- Keep every source file at or under 400 lines (`AGENTS.md`).
- All prose is en-GB-oxendict; Markdown prose wraps at 80 columns, code blocks
  at 120.

## Tolerances (exception triggers)

Stop and escalate when any of these is reached.

- Scope: more than 30 changed or added files, or more than 2500 net added lines
  of production code (tests and documentation excluded).
- Interface: any change to `QaStatus`, `QualityMode`, `CanonicalEpisode`,
  `GenerationRun`, or the `LLMPort`/`CostLedgerPort` signatures.
- Dependencies: any new runtime dependency beyond promoting `cyclopts` from the
  `dev` group to `[project.dependencies]` and adding `httpx` to the CLI's
  runtime needs (`httpx` is already a runtime dependency).
- Architecture: if adding the new module prefixes to `[tool.hecate]` causes
  `make check-architecture` to report violations in *pre-existing* modules,
  stop and escalate rather than silently regrouping unrelated packages.
- Iterations: if a gate (`make check-fmt`, `make typecheck`, `make lint`,
  `make test`) still fails after 3 focused fix attempts, stop and escalate.
- Ambiguity: if the compliance-status taxonomy needs a fifth member to model a
  real evaluator outcome, stop and present options.

## Risks

- Risk: the design document names two tables, `qa_findings` and
  `brand_compliance_results` (`docs/episodic-podcast-generation-system-design.md`,
  Data Model and Storage section), whereas this plan proposes
  `qa_evaluations` + `qa_findings` with compliance as a column.
  Severity: medium. Likelihood: high (it is a deliberate deviation).
  Mitigation: record the deviation in ADR 018, update the design document's
  Data Model bullet in the same change, and trace it in `Conformance basis`.
- Risk: `episodic/qa/` is not classified in any `[tool.hecate]` group, so the
  evaluator contracts are currently unenforced. Adding new grouped modules that
  import from `episodic.qa` may surface violations.
  Severity: medium. Likelihood: medium.
  Mitigation: Milestone `EP-M0` adds the group prefixes and runs
  `make check-architecture` *before* any dependent code is written, so the
  grouping decision is settled while it is cheap to change.
- Risk: no application CLI exists at all. `[project.scripts]` declares only
  `stilyagi = "stilyagi.stilyagi:main"`, which points at a package that is not
  present in this repository. Building the first CLI is more work than "add a
  command".
  Severity: medium. Likelihood: high.
  Mitigation: `EP-M5` is scoped to a single command group over the existing
  Representational State Transfer (REST) surface, with the boundary decision
  recorded in ADR 019. The dead `stilyagi` entry point is replaced, not
  extended.
- Risk: `rubric_score` is mandated by the roadmap but no evaluator produces one
  today, so a column could be added that nothing exercises end to end.
  Severity: low. Likelihood: high.
  Mitigation: the column is nullable, is exercised directly by repository
  round-trip and property tests (where the repository, not an evaluator, is the
  unit under test), and the absence of a producer is stated explicitly in the
  developers' guide and ADR 018 rather than glossed over.
- Risk: py-pglite fidelity. Filter, ordering, and pagination invariants are
  verified against py-pglite rather than a production PostgreSQL server.
  Severity: low. Likelihood: low.
  Mitigation: py-pglite runs real PostgreSQL (`docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`);
  `make check-migrations` additionally compares migrations against
  `Base.metadata` so schema drift is caught independently.
- Risk: Vidai Mock is resolved from `PATH` via `shutil.which("vidaimock")`
  (`tests/steps/generation_orchestration_vidaimock.py`); behavioural tests skip
  locally but fail under `CI=true` when it is absent.
  Severity: low. Likelihood: medium.
  Mitigation: reuse the existing Pedante Vidai Mock harness rather than adding
  a second one, and keep the new behavioural scenario able to run against a
  recorded evaluator result when the mock is unavailable.

## Progress

- [ ] EP-M0 Orientation, architecture grouping, and baseline gates.
- [ ] EP-M1 QA artefact domain model, compliance policy, and ports.
- [ ] EP-M2 PostgreSQL persistence adapter, Alembic migration, unit-of-work
      registration.
- [ ] EP-M3 Recording and query application services, plus evaluator-result
      mapping for Pedante and Chrono.
- [ ] EP-M4 REST retrieval endpoints filtered by evaluator and compliance
      status.
- [ ] EP-M5 First-party CLI retrieval surface.
- [ ] EP-M6 Documentation, ADRs, and roadmap completion.

## Surprises & discoveries

- Observation: `except IndexError, ValueError:` (unparenthesized multiple
  exception types) appears in `episodic/api/errors.py:367`,
  `episodic/api/authorization.py:114`,
  `episodic/api/resources/generation_runs.py:270`, and
  `episodic/generation/launcher.py:501`. This is a `SyntaxError` on Python 3.13
  and earlier but is **valid** on Python 3.14 under Python Enhancement Proposal
  (PEP) 758.
  Evidence: `uv run python -c "import ast; ast.parse(open('episodic/api/errors.py').read())"`
  prints `parse OK` under CPython 3.14.4; the same command under the system
  CPython 3.12 raises `SyntaxError: multiple exception types must be
  parenthesized`.
  Impact: none for this work, but any tooling pinned below Python 3.14 will
  mis-report these files as broken. Do not "fix" them.
- Observation: `[project.scripts]` declares `stilyagi = "stilyagi.stilyagi:main"`
  but no `stilyagi` module exists anywhere in the repository.
  Evidence: `pyproject.toml:31-32`; a repository-wide search for `stilyagi`
  outside `pyproject.toml` returns nothing.
  Impact: the console-script table is currently dead. `EP-M5` replaces it with
  the real `episodic` entry point.
- Observation: the LangGraph structured-planning graph
  (`episodic/orchestration/langgraph.py`, nodes `plan`, `execute`, `finish`)
  and the no-QA generation-run launcher (`episodic/generation/launcher.py`) are
  two parallel subsystems that do not call each other, and neither invokes the
  QA evaluator graphs in `episodic/qa/`.
  Evidence: `InProcessGenerationRunLauncher` contains no import of
  `episodic.orchestration`; no node named `qa`/`evaluate` exists in
  `episodic/orchestration/_graph_state.py` or `langgraph.py`.
  Impact: confirms that recording must be an explicitly invoked application
  service in this roadmap item, not a graph-node side effect.

## Decision log

- Decision: model QA artefacts as one `qa_evaluations` parent table plus one
  `qa_findings` child table, with compliance represented as a
  `compliance_status` column, instead of the separate
  `brand_compliance_results` table named in the design document.
  Rationale: only one evaluator that would populate `brand_compliance_results`
  exists on the roadmap (Anthem, item `2.2.4`, unimplemented). Building a second
  table for a producer that does not exist is speculative generality, and it
  would make the roadmap's own requirement — "retrieval ... filtered by
  evaluator and compliance status" — a union query across two tables. One
  evaluation record per invocation, carrying a compliance status, satisfies
  every evaluator uniformly. Recorded as ADR 018; the design document's Data
  Model bullet is updated in the same change.
  Date/Author: 2026-08-23, planning agent.
- Decision: do not store token usage on the QA artefact. Correlate to the cost
  ledger through `generation_run_id` plus the `provider_response_id` already
  carried in `evaluator_metadata`.
  Rationale: `episodic/cost/` already records normalized usage and priced
  entries per provider call, keyed by `workflow_run_id` and an idempotency key
  built as `run:{run_id}:node:{node}:call:{provider_response_id}:attempt:{n}`
  (`episodic/generation/launcher_support.py`). A second copy would drift.
  Date/Author: 2026-08-23, planning agent.
- Decision: the CLI is a REST client, not a second database client.
  Rationale: the system design places the CLI in the Client Experience Layer
  alongside the web console, and `docs/episodic-tui-api-design.md` fixes the
  authentication, error, and pagination contracts that clients use. A CLI that
  opened its own unit of work would create a second persistence entry point
  with its own authorization story. Recorded as ADR 019.
  Date/Author: 2026-08-23, planning agent.
- Decision: populate the `qa_evaluator` enum with all six evaluators named in
  the design document (Pedante, Bromide, Chiltern, Anthem, Caesura, Chrono)
  even though four are unimplemented.
  Rationale: adding a PostgreSQL enum value requires a migration. The taxonomy
  is fixed by the design document, so admitting all six now costs one enum
  definition and avoids four future migrations. A parameterized test pins the
  enum's value set against the documented taxonomy so it cannot silently drift.
  Date/Author: 2026-08-23, planning agent.
- Decision: record failed evaluator invocations as artefacts with
  `compliance_status = errored`.
  Rationale: it gives the fourth status a real producer, so the compliance
  filter is exercised across its whole range rather than two of four values,
  and it makes evaluator failures auditable instead of invisible.
  Date/Author: 2026-08-23, planning agent.

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
- `episodic/qa/chrono.py` defines `ChronoEstimatorConfig`,
  `ChronoEstimatorMetadata` (`estimator_name`, `estimator_version`,
  `input_character_count`, `spoken_word_count`, `words_per_minute`) and
  `ChronoRuntimeEstimate` (`estimated_seconds`, `metadata`).
- `episodic/qa/langgraph.py` and `episodic/qa/chrono_langgraph.py` wrap each
  evaluator as a one-node LangGraph `StateGraph`. Neither writes to any store;
  both only return an in-memory state delta.

Canonical persistence lives in `episodic/canonical/`:

- Domain entities are frozen dataclasses in `episodic/canonical/domain.py`
  (`CanonicalEpisode`, `GenerationRun`, `GenerationEvent`, ...).
- Ports are `Protocol` classes, for example
  `episodic/canonical/generation_run_ports.py`.
- SQLAlchemy models live in `episodic/canonical/storage/`, with the declarative
  `Base` and the shared `sa.Enum` constants in
  `episodic/canonical/storage/models_base.py`.
- `episodic/canonical/storage/repository_base.py` provides `_RepositoryBase`
  with `_get_one_or_none`, `_get_many`, `_list_where`, `_list_by_ids`,
  `_list_paginated`, `_get_latest_where`, `_update_where`, and
  `_update_entity_fields`.
- `episodic/canonical/storage/uow.py` instantiates every repository inside
  `SqlAlchemyUnitOfWork.__aenter__`; the matching attribute list is declared on
  the `CanonicalUnitOfWork` `Protocol` in
  `episodic/canonical/unit_of_work_protocols.py`.
- Alembic migrations are hand-written under `alembic/versions/`, named
  `YYYYMMDD_NNNNNN_<slug>.py` with `revision` equal to the filename prefix. The
  current head is `20260624_000012` (`add_ingestion_job_owner.py`). Order is
  defined by `down_revision`, not by the date in the filename.

The HTTP surface lives in `episodic/api/`:

- Routes are registered in `episodic/api/app.py` by `_register_*_routes`
  helpers; every domain route is prefixed `/v1/`.
- `episodic/api/helpers.py` provides `parse_pagination` (limit default 20, max
  100; offset ≥ 0), `parse_enum_param`, `parse_optional_uuid_param`, and
  `require_query_params`.
- List responses use the envelope `{"items": [...], "limit": ..., "offset": ...,
  "total": ...}`, matching `docs/episodic-tui-api-design.md`.
- Errors use the repository's own envelope `{"code", "message", "details"}` via
  `episodic/api/errors.py` and `app.set_error_serializer(serialize_http_error)`
  — not RFC 9457 `application/problem+json`.
- Authorization is coarse: `AuthorizationMiddleware` (in
  `episodic/api/authorization.py`) sets `req.context.principal_id` for `/v1/*`
  requests, and resources then enforce **ownership**. The closest precedent for
  episode-scoped reads is `episodic/api/resources/episode_tei.py`, whose
  `_has_accessible_draft` requires `run.actor == actor` for the episode's
  `last_generation_run_id`.
- The cleanest list-plus-filter exemplar is
  `episodic/api/resources/reference_documents.py`, `ReferenceDocumentsResource.on_get`.

There is **no command-line interface**. `cyclopts` is a development-group
dependency used only by `scripts/local_k8s.py`.

### Skills and documents to load before starting

- Skill `execplans` — this document's format and the discipline for keeping it
  current.
- Skill `hexagonal-architecture` — layer boundaries, port ownership, and the
  layer-specific testing table.
- Skill `python-router`, then `python-data-shapes` (frozen dataclasses and
  tagged unions for the artefact model) and `python-types-and-apis` (port
  `Protocol` design). Load `python-errors-and-logging` when writing the
  evaluator-failure path.
- Skill `python-verification`, then `hypothesis` for the property obligations
  listed below.
- Skill `python-testing` for pytest fixture and parametrization depth.
- Skill `leta` for symbol navigation; prefer `leta show`/`leta refs` over
  reading whole files.
- Skill `vidai-mock` before touching the behavioural evaluator harness.
- Skill `en-gb-oxendict` and `docs/documentation-style-guide.md` for all prose.

Repository documents that are prerequisites, not optional reading:

- `AGENTS.md` — code style, quality gates, commit discipline.
- `docs/episodic-podcast-generation-system-design.md` — the Quality Assurance
  Stack and Data Model and Storage sections.
- `docs/adr-001-pedante-evaluator-contract.md` — in particular its closing
  item: "If evaluator results are persisted or exposed through an external
  API, record any versioning or compatibility guarantees in a follow-on ADR."
  ADR 018 discharges this.
- `docs/adr/adr-006-chrono-spoken-text-semantics.md`,
  `docs/adr/adr-009-source-to-script-rest-vertical-slice.md`,
  `docs/adr/adr-015-cost-accounting-ports-and-pricing-engine.md`,
  `docs/adr/adr-017-no-qa-generation-run-execution-and-tei-persistence.md`.
- `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`,
  `docs/testing-async-falcon-endpoints.md`,
  `docs/agentic-systems-with-langgraph-and-celery.md`,
  `docs/langgraph-and-celery-in-hexagonal-architecture.md`,
  `docs/episodic-tui-api-design.md`, `docs/scripting-standards.md`,
  `docs/developers-guide.md`, `docs/users-guide.md`, `docs/contents.md`.

## Conformance basis

Upstream artefacts, at the revisions present in the working tree at the time of
writing (commit `5af0638`, "No-QA generation runs and TEI-P5 retrieval (4.3.2)"):

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
- `docs/episodic-tui-api-design.md` (`TUI-API`), pagination contract and error
  contract.

No Terms of Reference document exists for this repository; the roadmap and the
system design document play that role. Say so rather than inventing one.

Trace links:

```plaintext
RM-2.2.7-a -> TDD-DATA -> EP-M1 -> tests/test_qa_artefact_domain.py::test_compliance_status_for_pedante_result
RM-2.2.7-a -> TDD-DATA -> EP-M2 -> tests/canonical_storage/test_qa_artefacts.py::test_evaluation_round_trip
RM-2.2.7-a -> TDD-QA   -> EP-M3 -> tests/test_qa_artefact_recording.py::test_records_pedante_result
RM-2.2.7-b -> TUI-API  -> EP-M4 -> tests/features/qa_artefact_retrieval.feature (REST scenarios)
RM-2.2.7-b -> TDD-CLIENT -> EP-M5 -> tests/features/qa_artefact_retrieval.feature (CLI scenarios)
ADR-001(open item) -> EP-M6 -> docs/adr/adr-018-qa-artefact-persistence-contract.md
TDD-DATA(deviation) -> EP-M6 -> docs/episodic-podcast-generation-system-design.md (Data Model bullet)
```

## Verification plan

### Invariants and lemmas

**INV-COMPLIANCE-BLOCKING.** For any `PedanteEvaluationResult` `r`, the
recorded evaluation's `compliance_status` is `NON_COMPLIANT` if and only if at
least one derived `QaFinding` has `is_blocking` true; otherwise it is
`COMPLIANT`. Equivalently, the derived status agrees with
`r.requires_revision`.

- Method: property test with Hypothesis over a composite strategy generating
  `PedanteEvaluationResult` values across all 14 `SupportLevel` members and all
  4 `FindingSeverity` members, including the empty-findings case.
- Rationale: the mapping is a total function over a small but combinatorial
  domain that example tests would sample thinly, and getting the blocking-set
  membership wrong is the most likely defect.
- Domain: finding counts 0–8; `SupportLevel` drawn uniformly from
  `SupportLevel`; severity drawn uniformly; `cited_source_ids` of length 0–3.
- Artefact: `tests/test_qa_artefact_recording_properties.py`.
- Evidence: `uv run pytest tests/test_qa_artefact_recording_properties.py -q`.
  Before implementation the module under test does not exist, so collection
  fails with `ModuleNotFoundError: episodic.qa.recording`.
- Non-vacuity: the test emits `hypothesis.event()` labels
  `"blocking present"`/`"no blocking finding"` and asserts, via
  `hypothesis.stateful`-free statistics captured with
  `--hypothesis-show-statistics`, that both labels occur. Negative control:
  temporarily change `compliance_status_for_pedante` to return `COMPLIANT`
  unconditionally and confirm the property fails with a counter-example
  containing at least one blocking finding; then revert.

**INV-FINDING-ORDER.** Findings persisted for an evaluation are returned in the
order the evaluator emitted them, and their `ordinal` values are exactly
`0..n-1` with no gaps.

- Method: property test over generated finding sequences, executed against the
  real SQLAlchemy adapter using the py-pglite fixtures.
- Rationale: PostgreSQL returns rows in unspecified order absent `ORDER BY`;
  this is an ordering invariant over a generated sequence, not a single case.
- Domain: 0–20 findings per evaluation, mixed severities.
- Artefact: `tests/canonical_storage/test_qa_artefact_properties.py`.
- Evidence: `uv run pytest tests/canonical_storage/test_qa_artefact_properties.py -q`.
- Non-vacuity: include an evaluation with at least 2 findings whose severities
  sort differently from their emission order, so an accidental
  `ORDER BY severity` is rejected. Negative control: drop the `ORDER BY
  ordinal` clause from the adapter query and confirm the property fails.

**INV-REPLAY-IDEMPOTENT.** Recording the same evaluation twice with the same
`(episode_id, idempotency_key)` pair creates exactly one `qa_evaluations` row
and one set of `qa_findings` rows, and the second call returns the identifier
created by the first.

- Method: parameterized integration test plus a Hypothesis state-machine test
  (`RuleBasedStateMachine`) that interleaves record and list operations.
- Rationale: replay is a transition property over operation sequences. ADR 017
  establishes replay semantics for generation runs; artefact writes performed
  during a replayed run must not multiply.
- Domain: 1–10 record operations drawn from a pool of 3 idempotency keys and 2
  episodes, interleaved with list operations.
- Artefact: `tests/canonical_storage/test_qa_artefact_replay.py`.
- Evidence: `uv run pytest tests/canonical_storage/test_qa_artefact_replay.py -q`.
- Non-vacuity: the machine asserts at least one duplicate key is actually
  replayed (tracked by a counter checked in `teardown`). Negative control:
  remove the `uq_qa_evaluations_episode_idempotency_key` constraint handling
  from the adapter and confirm a duplicate row is created and the test fails.

**INV-FILTER-SOUND.** For any set of stored evaluations and any filter
`(evaluator?, compliance_status?)`, the listed items are exactly those
evaluations matching every supplied predicate, and `total` equals the count of
that same set (not the page length).

- Method: port contract test executed against both an in-memory fake and the
  SQLAlchemy adapter, driven by Hypothesis-generated corpora. This follows the
  precedent in `tests/test_generation_checkpoint_port_contract.py`.
- Rationale: the roadmap's retrieval requirement is precisely this predicate;
  the classic defect is `total` being computed after `LIMIT`.
- Domain: 0–30 evaluations spanning at least 3 evaluators and all 4 compliance
  statuses; filters drawn from `{None} ∪ Evaluator` × `{None} ∪ Status`.
- Artefact: `tests/test_qa_artefact_port_contract.py` and
  `tests/canonical_storage/test_qa_artefact_properties.py`.
- Evidence: `uv run pytest tests/test_qa_artefact_port_contract.py -q`.
- Non-vacuity: the corpus strategy must produce at least one evaluation that
  matches the evaluator filter but not the compliance filter (and vice versa),
  classified with `hypothesis.event()`; a corpus that never exercises the
  conjunction would make the test pass trivially. Negative control: drop the
  compliance predicate from the SQL `WHERE` clause and confirm the contract
  test fails on the SQLAlchemy adapter while still passing on a fake that keeps
  both predicates — proving the test discriminates the implementation.

**INV-PAGINATION-PARTITION.** For a fixed filter and the canonical ordering
(`evaluated_at DESC, id DESC`), concatenating pages
`(limit=L, offset=0), (limit=L, offset=L), ...` reproduces the full ordered
result exactly once, with no duplicates and no omissions.

- Method: property test over generated corpora and page sizes.
- Rationale: an unstable sort key silently reorders rows between pages; only a
  sequence-level property catches it.
- Domain: corpus size 0–25, `L` in 1–10, including corpora containing
  evaluations sharing an identical `evaluated_at`.
- Artefact: `tests/canonical_storage/test_qa_artefact_properties.py`.
- Evidence: as above.
- Non-vacuity: the strategy must generate at least one tie on `evaluated_at`
  (classified explicitly); without ties the tiebreaker is never exercised.
  Negative control: remove `id DESC` from the `ORDER BY` and confirm the
  property finds a duplicate or omission on a tie-containing corpus.

**INV-EPISODE-LINK.** Every `qa_evaluations` row references an existing
`episodes` row, and deleting an episode removes its evaluations and their
findings.

- Method: parameterized integration test against py-pglite plus the schema
  drift gate.
- Rationale: "linked to canonical episodes" is the roadmap's own phrasing; a
  dangling artefact is a data-integrity failure, and the cascade is a database
  behaviour, not a Python one.
- Domain: insert-then-delete for one episode with 2 evaluations and 3 findings;
  attempt an insert with a random non-existent `episode_id`.
- Artefact: `tests/canonical_storage/test_qa_artefacts.py`.
- Evidence: `uv run pytest tests/canonical_storage/test_qa_artefacts.py -q`
  and `make check-migrations`.
- Non-vacuity: the negative case asserts an `IntegrityError` is raised for the
  non-existent episode; without it, a missing foreign key would go unnoticed.
  Negative control: omit `ondelete="CASCADE"` in the migration and confirm the
  delete test fails.

**LEM-SERIALIZATION-STABLE.** The JSON representation of an evaluation and of a
list envelope is stable across changes that do not intend to alter the wire
format.

- Method: snapshot tests with `syrupy` over the serializer output for three
  variants: a Pedante evaluation with findings, a Chrono evaluation with a
  runtime estimate and no findings, and an errored evaluation.
- Rationale: the retrieval contract is consumed by the Terminal User Interface
  (TUI) client; multivariant output-format consistency is exactly the case the
  repository reserves `syrupy` for.
- Artefact: `tests/test_qa_artefact_serializers.py`,
  `tests/__snapshots__/test_qa_artefact_serializers.ambr`.
- Evidence: `uv run pytest tests/test_qa_artefact_serializers.py -q`; the first
  run without `--snapshot-update` fails because no snapshot exists.
- Non-vacuity: the three variants must differ in which optional fields are
  present (`rubric_score`, `runtime_estimate_seconds`, `findings`), so a
  serializer that emits a constant shape cannot satisfy all three.

**LEM-CLI-RENDERING.** The CLI's table and JSON renderings of a page of
evaluations are deterministic given the same API payload.

- Method: snapshot tests over the rendering functions with a stubbed HTTP
  transport (`httpx.MockTransport`), plus a behavioural scenario.
- Rationale: the CLI is the second half of `RM-2.2.7-b`; its output is the
  observable behaviour.
- Artefact: `tests/test_qa_cli.py`,
  `tests/__snapshots__/test_qa_cli.ambr`.
- Evidence: `uv run pytest tests/test_qa_cli.py -q`.
- Non-vacuity: include an empty page and a page with a finding count of zero
  versus many, so a renderer that always prints a fixed header row fails.

### Axioms

These are assumed, not verified. Do not write tests for third-party internals.

- CPython 3.14 provides `uuid.uuid7()` and accepts PEP 758 unparenthesized
  `except` clauses.
- PostgreSQL enforces `UNIQUE`, `CHECK`, and `ON DELETE CASCADE` as documented,
  and py-pglite runs a real PostgreSQL server faithful to those semantics.
- SQLAlchemy 2.x async sessions execute the emitted SQL and map results as
  documented; Alembic applies migrations in `down_revision` order.
- Falcon routes by URI template and invokes `on_get` as documented; `cyclopts`
  binds annotated parameters to command-line arguments as documented.
- `tei-rapporteur` extracts spoken text from TEI P5 as Chrono already relies
  upon (fixed by ADR 006).
- Vidai Mock serves OpenAI-compatible chat completions from the configured
  templates.

Where repository-owned logic sits on top of these — the migration's constraint
definitions, the adapter's `ORDER BY`/`WHERE`/`COUNT` construction, the CLI's
argument binding — it is verified against the real interface (py-pglite for
SQL, the real `cyclopts` app for parsing), not against a mock of it.

### Obligations deliberately not discharged formally

The compliance policy is a two-branch total function; Hypothesis coverage over
the full `SupportLevel` × `FindingSeverity` domain is exhaustive in the
material sense, so bounded model checking or a prover would add ceremony
without additional confidence. CrossHair is not applied because the artefact
mapping contains no arithmetic contracts of the kind
`episodic/qa/chrono.py::_compute_estimated_seconds` carries; if a numeric
normalization is later added to `rubric_score`, revisit this and add a PEP 316
contract with `make crosshair`.

## Plan of work

### Stage A — understand and propose (no production changes)

Read `AGENTS.md`, the skills listed above, and the documents in `Conformance
basis`. Run the baseline gates on the untouched tree so later failures are
attributable:

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
    And a recorded Pedante evaluation with one blocking finding
    And a recorded Chrono evaluation with a runtime estimate
    And a recorded Anthem evaluation that failed to execute

  Scenario: Retrieving every QA evaluation for an episode over HTTP
    When the owner requests the episode's QA evaluations
    Then the response lists 3 evaluations ordered newest first
    And each evaluation reports its evaluator and compliance status

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
    And the response includes 1 finding with severity "high"
    And the finding includes its remediation guidance

  Scenario: A different principal cannot read another owner's QA evaluations
    When a different principal requests the episode's QA evaluations
    Then the response status is 404

  Scenario: Rejecting an unknown evaluator filter
    When the owner requests the episode's QA evaluations for evaluator "nonsuch"
    Then the response status is 400
    And the error code is "validation_error"

  Scenario: Listing QA evaluations from the command line
    When the operator runs "episodic qa evaluations list --episode <episode_id>"
    Then the command exits with status 0
    And the output table lists 3 evaluations

  Scenario: Filtering QA evaluations from the command line
    When the operator runs "episodic qa evaluations list --episode <episode_id> --evaluator pedante --compliance-status non_compliant"
    Then the command exits with status 0
    And the output table lists 1 evaluation

  Scenario: Emitting machine-readable output from the command line
    When the operator runs "episodic qa evaluations list --episode <episode_id> --format json"
    Then the command exits with status 0
    And the output parses as JSON with 3 items

  Scenario: Reporting a failed command-line request
    When the operator runs a QA listing for an episode that does not exist
    Then the command exits with a non-zero status
    And the error message names the episode identifier
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

### EP-M0 — Orientation, architecture grouping, and baseline gates

- Identifier and outcome: `EP-M0`. The four `[tool.hecate]` group memberships
  for the modules this plan will add are declared up front and
  `make check-architecture` passes. No behaviour changes.
- Requirements and gaps: `ADR-014` conformance for all subsequent milestones.
- Work: in `pyproject.toml`, add to the `domain_ports` group prefixes:
  `episodic.canonical.qa_artefacts`, `episodic.canonical.qa_artefact_ports`.
  Add to `application`: `episodic.canonical.qa_artefact_service`,
  `episodic.qa.recording`. Add to `outbound_adapter`:
  `episodic.canonical.storage.qa_artefact_models`,
  `episodic.canonical.storage.qa_artefact_mappers`,
  `episodic.canonical.storage.qa_artefacts`. Add to `inbound_adapter`:
  `episodic.api.resources.qa_artefacts`, `episodic.cli`.
  Because `episodic.qa.recording` (application) will import
  `episodic.qa.pedante.types` and `episodic.qa.chrono`, also add
  `episodic.qa.pedante`, `episodic.qa.chrono`, `episodic.llm` and
  `episodic.observability` to `domain_ports`. These modules are already pure
  contracts; the grouping records what is already true.
- Acceptance evidence: `make check-architecture` exits 0 with the new prefixes
  in place, on a tree with no other changes. `EV-M0-arch`.
- Conformance check: confirm no pre-existing module moved between groups. If
  `make check-architecture` reports violations in modules this plan does not
  touch, that is a tolerance breach — stop and escalate.
- Recovery: revert the `pyproject.toml` hunk; nothing else depends on it yet.
- Remaining gaps: everything.
- Compatibility decision: none required. No consumer exists.

### EP-M1 — QA artefact domain model, compliance policy, and ports

- Identifier and outcome: `EP-M1`. Pure domain types and a port protocol exist
  and are exercised by unit and property tests. Nothing is persisted yet.
- Requirements and gaps: `RM-2.2.7-a` (model), `TDD-DATA`.
- Files added:
  - `episodic/canonical/qa_artefacts.py` — enums and frozen dataclasses.
  - `episodic/canonical/qa_artefact_ports.py` — the repository `Protocol`,
    request objects, and error types.
- Acceptance evidence: `uv run pytest tests/test_qa_artefact_domain.py
  tests/test_qa_artefact_recording_properties.py -q` passes; both files fail
  before the modules exist. `EV-M1-domain`.
- Conformance check: no import of Falcon, SQLAlchemy, LangGraph, or `httpx` in
  either new module; `make check-architecture` still exits 0.
- Recovery: the modules are additive and unreferenced; delete to revert.
- Remaining gaps: persistence, services, HTTP, CLI.
- Compatibility decision: none. Pre-1.0, no external consumer.

### EP-M2 — Persistence adapter, migration, and unit-of-work registration

- Identifier and outcome: `EP-M2`. `qa_evaluations` and `qa_findings` exist in
  PostgreSQL, are reachable as `uow.qa_artefacts`, and round-trip through the
  adapter. `make check-migrations` reports no drift.
- Requirements and gaps: `RM-2.2.7-a`, `TDD-DATA`, `INV-FINDING-ORDER`,
  `INV-REPLAY-IDEMPOTENT`, `INV-FILTER-SOUND`, `INV-PAGINATION-PARTITION`,
  `INV-EPISODE-LINK`.
- Files added or changed:
  - `episodic/canonical/storage/models_base.py` — add the three `sa.Enum`
    constants.
  - `episodic/canonical/storage/qa_artefact_models.py` — the two ORM models.
  - `episodic/canonical/storage/qa_artefact_mappers.py` — record/domain
    mappers.
  - `episodic/canonical/storage/qa_artefacts.py` — `SqlAlchemyQaArtefactStore`.
  - `episodic/canonical/storage/uow.py` — instantiate the store in
    `__aenter__` and document it in the class docstring's `Attributes`.
  - `episodic/canonical/unit_of_work_protocols.py` — declare
    `qa_artefacts: QaArtefactRepository`.
  - `alembic/versions/20260823_000013_add_qa_artefact_tables.py` — hand-written
    migration with `down_revision = "20260624_000012"`.
- Acceptance evidence: `uv run pytest tests/canonical_storage/test_qa_artefacts.py
  tests/canonical_storage/test_qa_artefact_properties.py
  tests/canonical_storage/test_qa_artefact_replay.py -q` passes, and
  `make check-migrations` exits 0. `EV-M2-storage`.
- Conformance check: the ORM models must match the migration exactly, or
  `make check-migrations` fails; enum constants must live in `models_base.py`,
  not inline.
- Recovery: `alembic downgrade -1` reverses the migration; the store and models
  are additive. Re-running the migration is safe because the `upgrade()` body
  is a single transactional `create_table`/`create_index` sequence and the enum
  creation uses `checkfirst=True`.
- Remaining gaps: services, HTTP, CLI.
- Compatibility decision: this is a new persisted format with no deployed
  predecessor, so no data migration of existing rows is required.

### EP-M3 — Recording and query services, and evaluator-result mapping

- Identifier and outcome: `EP-M3`. Application code can record a Pedante
  result, a Chrono estimate, or an evaluator failure against an episode, and
  can query recorded artefacts with filters and pagination.
- Requirements and gaps: `RM-2.2.7-a`, `TDD-QA`, `INV-COMPLIANCE-BLOCKING`.
- Files added:
  - `episodic/qa/recording.py` — pure mapping functions and the compliance
    policy.
  - `episodic/canonical/qa_artefact_service.py` — `record_qa_evaluation`,
    `get_qa_evaluation`, `list_qa_evaluations`, operating on a
    `CanonicalUnitOfWork` without committing (following
    `episodic/canonical/generation_persistence.py`, whose `persist_draft_script`
    deliberately neither commits nor rolls back).
- Acceptance evidence: `uv run pytest tests/test_qa_artefact_recording.py
  tests/test_qa_artefact_recording_properties.py
  tests/test_qa_artefact_service.py -q` passes. `EV-M3-service`.
- Conformance check: `episodic/qa/recording.py` must not import SQLAlchemy or
  Falcon; the service must not import `episodic.canonical.storage`.
- Recovery: additive modules; delete to revert. No schema change.
- Remaining gaps: HTTP, CLI, documentation.
- Compatibility decision: none.

### EP-M4 — REST retrieval filtered by evaluator and compliance status

- Identifier and outcome: `EP-M4`. `GET /v1/episodes/{episode_id}/qa-evaluations`
  and `GET /v1/qa-evaluations/{evaluation_id}` serve owner-scoped artefacts
  with the repository's standard pagination envelope and error envelope.
- Requirements and gaps: `RM-2.2.7-b` (API half), `TUI-API`.
- Files added or changed:
  - `episodic/api/resources/qa_artefacts.py` — two resource classes.
  - `episodic/api/serializers.py` — `serialize_qa_evaluation`,
    `serialize_qa_finding`.
  - `episodic/api/app.py` — `_register_qa_artefact_routes`.
  - `episodic/api/resources/__init__.py` — export the new resources.
- Acceptance evidence: `uv run pytest tests/test_qa_artefact_api.py
  tests/test_qa_artefact_serializers.py
  tests/steps/test_qa_artefact_retrieval_steps.py -q` passes; the REST
  scenarios in `tests/features/qa_artefact_retrieval.feature` pass.
  `EV-M4-rest`.
- Conformance check: pagination bounds match `TUI-API` (`1 <= limit <= 100`,
  `offset >= 0`); the error envelope is the repository's `{code, message,
  details}`, not `application/problem+json`; a foreign principal receives 404,
  not 403, matching `episodic/api/resources/episode_tei.py`.
- Recovery: remove the route registration; the resources become unreachable.
- Remaining gaps: CLI, documentation.
- Compatibility decision: new endpoints under `/v1`; no existing route changes.

### EP-M5 — First-party CLI retrieval surface

- Identifier and outcome: `EP-M5`. `episodic qa evaluations list` and
  `episodic qa evaluations show` exist, are installed by
  `[project.scripts] episodic = "episodic.cli:main"`, and read through the REST
  API.
- Requirements and gaps: `RM-2.2.7-b` (CLI half), `TDD-CLIENT`,
  `LEM-CLI-RENDERING`.
- Files added or changed:
  - `episodic/cli/__init__.py` — `main()` entry point.
  - `episodic/cli/app.py` — the `cyclopts.App` and global options
    (`--base-url`, `--token`, `--timeout`, `--format`).
  - `episodic/cli/qa.py` — the `qa evaluations` sub-commands.
  - `episodic/cli/client.py` — a thin `httpx` client and error translation.
  - `episodic/cli/rendering.py` — table and JSON renderers.
  - `pyproject.toml` — replace the dead `stilyagi` script with `episodic`, and
    move `cyclopts` from the `dev` group into `[project.dependencies]`.
- Acceptance evidence: `uv run pytest tests/test_qa_cli.py
  tests/steps/test_qa_artefact_retrieval_steps.py -q` passes; the CLI scenarios
  in the feature file pass; `uv run episodic qa evaluations list --help` prints
  usage. `EV-M5-cli`.
- Conformance check: `episodic/cli/` must not import `episodic.canonical.storage`
  or open a database session; `make check-architecture` still exits 0.
- Recovery: revert the `[project.scripts]` hunk and delete `episodic/cli/`.
- Remaining gaps: documentation.
- Compatibility decision: the removed `stilyagi` entry point references a
  module that does not exist in this repository, so nothing can depend on it.

### EP-M6 — Documentation, ADRs, and roadmap completion

- Identifier and outcome: `EP-M6`. The decisions are recorded, the guides
  describe the new behaviour, and the roadmap entry is marked done.
- Requirements and gaps: `ADR-001` open item; `TDD-DATA` deviation.
- Files added or changed:
  - `docs/adr/adr-018-qa-artefact-persistence-contract.md` — new. Covers the
    unified `qa_evaluations` + `qa_findings` model, the compliance-status
    taxonomy, `artefact_schema_version` and what a version bump obliges, the
    decision not to duplicate usage data, and the relationship to the
    `generation_iterations` table that the design document anticipates for
    roadmap item `4.4.1`.
  - `docs/adr/adr-019-cli-client-boundary.md` — new. Covers the CLI as a REST
    client, the `cyclopts` choice, authentication via `--token`/environment,
    and output-format policy.
  - `docs/episodic-podcast-generation-system-design.md` — replace the
    `qa_findings` and `brand_compliance_results` bullet in *Data Model and
    Storage* with the tables actually created; add a QA-artefact paragraph to
    *Quality Assurance Stack* referencing ADR 018.
  - `docs/developers-guide.md` — extend *Quality-assurance evaluators* with a
    QA-artefact persistence subsection (module layout, maintainer rules, the
    fact that no evaluator populates `rubric_score` yet, testing conventions),
    and add a *Command-line interface* section. While there, correct the stale
    reference to `episodic/qa/pedante.py`; that module is now the package
    `episodic/qa/pedante/`.
  - `docs/users-guide.md` — extend *Quality & Compliance* with the retrieval
    behaviour, and add the CLI commands with a worked example under *Getting
    Started*.
  - `docs/contents.md` — index both new ADRs.
  - `docs/roadmap.md` — mark `2.2.7` `[x]` and record the delivered outcome in
    the same style as the neighbouring completed items.
- Acceptance evidence: `make markdownlint` and `make nixie` exit 0; the full
  gate set exits 0. `EV-M6-docs`.
- Conformance check: every deviation recorded in `Decision log` appears in an
  ADR or in the design document; no trace link in `Conformance basis` points at
  a file that does not exist.
- Recovery: documentation-only; revert individually.
- Remaining gaps: none for `2.2.7`. Wiring evaluators into the generation graph
  remains roadmap item `4.4.1`; `generation_iterations` remains unimplemented.
- Compatibility decision: none.

## Interfaces and dependencies

Be prescriptive. These are the shapes that must exist at the end of the
relevant milestone.

### `episodic/canonical/qa_artefacts.py` (EP-M1)

```python
"""Domain model for durable quality-assurance (QA) artefacts."""

import dataclasses as dc
import datetime as dt
import decimal
import enum
import uuid

from .domain import JsonMapping


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


QA_ARTEFACT_SCHEMA_VERSION: int = 1


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
class QaEvaluation:
    """One recorded evaluator invocation against a canonical episode."""

    id: uuid.UUID
    episode_id: uuid.UUID
    evaluator: QaEvaluator
    evaluator_version: str
    compliance_status: QaComplianceStatus
    evaluated_at: dt.datetime
    idempotency_key: str
    artefact_schema_version: int = QA_ARTEFACT_SCHEMA_VERSION
    generation_run_id: uuid.UUID | None = None
    summary: str = ""
    rubric_score: decimal.Decimal | None = None
    runtime_estimate_seconds: int | None = None
    evaluator_metadata: JsonMapping = dc.field(default_factory=dict)
    findings: tuple[QaFinding, ...] = ()
    created_at: dt.datetime | None = None
```

`__post_init__` validation must reject a negative `runtime_estimate_seconds`, a
`rubric_score` outside `[0, 1]`, an empty `evaluator_version`, an empty
`idempotency_key`, and `ordinal` values that are not `0..n-1` in order.

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
        """Persist an evaluation and its findings, replaying on repeat keys."""
        ...

    async def get_evaluation(self, evaluation_id: uuid.UUID) -> QaEvaluation | None:
        """Return one evaluation with its findings, or None."""
        ...

    async def list_evaluations(
        self, request: QaEvaluationListRequest
    ) -> tuple[tuple[QaEvaluation, ...], int]:
        """Return one filtered page of evaluations and the unpaged total."""
        ...
```

`record_evaluation` returns the *stored* evaluation, so a replayed call returns
the identifier and findings created by the first call, not the caller's
candidate. `list_evaluations` returns evaluations **without** their findings
(the `findings` tuple is empty) to keep the list query single-table;
`get_evaluation` returns them populated. State this in both docstrings — it is
the kind of asymmetry that bites a reader at 3 a.m.

### Database schema (EP-M2)

```sql
CREATE TABLE qa_evaluations (
    id                       UUID PRIMARY KEY,
    episode_id               UUID NOT NULL REFERENCES episodes (id) ON DELETE CASCADE,
    generation_run_id        UUID     REFERENCES generation_runs (id) ON DELETE SET NULL,
    evaluator                qa_evaluator NOT NULL,
    evaluator_version        TEXT NOT NULL,
    artefact_schema_version  INTEGER NOT NULL,
    compliance_status        qa_compliance_status NOT NULL,
    summary                  TEXT NOT NULL DEFAULT '',
    rubric_score             NUMERIC(5, 4),
    runtime_estimate_seconds INTEGER,
    evaluator_metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key          TEXT NOT NULL,
    evaluated_at             TIMESTAMPTZ NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_qa_evaluations_episode_idempotency_key UNIQUE (episode_id, idempotency_key),
    CONSTRAINT ck_qa_evaluations_rubric_score_unit_interval
        CHECK (rubric_score IS NULL OR (rubric_score >= 0 AND rubric_score <= 1)),
    CONSTRAINT ck_qa_evaluations_runtime_estimate_non_negative
        CHECK (runtime_estimate_seconds IS NULL OR runtime_estimate_seconds >= 0)
);

CREATE INDEX ix_qa_evaluations_episode_evaluator_evaluated_at
    ON qa_evaluations (episode_id, evaluator, evaluated_at DESC);
CREATE INDEX ix_qa_evaluations_episode_compliance_status
    ON qa_evaluations (episode_id, compliance_status);

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

CREATE INDEX ix_qa_findings_evaluation_severity ON qa_findings (evaluation_id, severity);
```

The canonical listing order is `evaluated_at DESC, id DESC`. The `id` tiebreaker
is load-bearing because identifiers are UUIDv7 and therefore monotonic with
creation time; without it, evaluations sharing an `evaluated_at` can swap
between pages.

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
`.create(op.get_bind(), checkfirst=True)` / `.drop(...)` calls, exactly as
`alembic/versions/20260624_000010_add_generation_run_tables.py` does.

### `episodic/canonical/storage/qa_artefacts.py` (EP-M2)

`SqlAlchemyQaArtefactStore` follows `SqlAlchemyGenerationRunStore` rather than
`_RepositoryBase`, because it needs a savepoint-and-requery idempotent insert:

```python
@dc.dataclass(slots=True)
class SqlAlchemyQaArtefactStore(QaArtefactRepository):
    """PostgreSQL-backed QA artefact store."""

    _session: AsyncSession
    _runtime: QaArtefactStorageRuntime
```

`QaArtefactStorageRuntime` mirrors
`episodic/canonical/storage/generation_run_storage_runtime.py`: a frozen
dataclass carrying `clock` and `uuid_factory`, defaulting to
`dt.datetime.now(dt.UTC)` and `uuid.uuid7`, so tests get deterministic
timestamps and identifiers.

`record_evaluation` opens `session.begin_nested()`, inserts the evaluation and
its findings, flushes, and on `IntegrityError` rolls back the savepoint and
re-selects by `(episode_id, idempotency_key)`, returning the existing row. This
is the same shape as `SqlAlchemyGenerationRunStore.create_run`.

`list_evaluations` issues two statements: a `select(...).order_by(...).limit().offset()`
for the page and a `select(sa.func.count()).select_from(...)` for the total,
both built from one shared `WHERE` clause so the predicates cannot drift apart.
Build that clause in a single private helper, `_evaluation_filters(request)`,
returning a list of criteria; sharing the helper is what makes
`INV-FILTER-SOUND` structurally hard to break.

### `episodic/qa/recording.py` (EP-M3)

```python
def compliance_status_for_pedante(
    result: PedanteEvaluationResult,
) -> QaComplianceStatus:
    """Return the compliance status implied by a Pedante result."""


def evaluation_from_pedante(
    result: PedanteEvaluationResult,
    *,
    episode_id: uuid.UUID,
    evaluated_at: dt.datetime,
    generation_run_id: uuid.UUID | None = None,
    idempotency_key: str,
    uuid_factory: cabc.Callable[[], uuid.UUID] = uuid.uuid7,
) -> QaEvaluation:
    """Project a Pedante result onto a persistable QA evaluation."""


def evaluation_from_chrono(
    estimate: ChronoRuntimeEstimate,
    *,
    episode_id: uuid.UUID,
    evaluated_at: dt.datetime,
    generation_run_id: uuid.UUID | None = None,
    idempotency_key: str,
    uuid_factory: cabc.Callable[[], uuid.UUID] = uuid.uuid7,
) -> QaEvaluation:
    """Project a Chrono runtime estimate onto a persistable QA evaluation."""


def evaluation_from_failure(
    evaluator: QaEvaluator,
    *,
    episode_id: uuid.UUID,
    evaluator_version: str,
    error_category: str,
    summary: str,
    evaluated_at: dt.datetime,
    generation_run_id: uuid.UUID | None = None,
    idempotency_key: str,
    uuid_factory: cabc.Callable[[], uuid.UUID] = uuid.uuid7,
) -> QaEvaluation:
    """Record a failed evaluator invocation as an errored QA evaluation."""
```

Mapping rules, which the property tests pin:

- Pedante: `evaluator_version` is the evaluator's contract version string;
  `summary` is `result.summary`; `evaluator_metadata` carries `model`,
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
  `evaluator_metadata` carries the whole `ChronoEstimatorMetadata` projection
  (`estimator_name`, `input_character_count`, `spoken_word_count`,
  `words_per_minute`); `findings` is empty; `compliance_status` is
  `NOT_APPLICABLE`, because a runtime estimate makes no compliance claim.
- Failure: `compliance_status = ERRORED`; `evaluator_metadata` carries
  `error_category`; `findings` is empty.

Do not store `LLMUsage` on the artefact. The correlation to the cost ledger is
`generation_run_id` plus `evaluator_metadata["provider_response_id"]`, which
together reconstruct the ledger idempotency key format used in
`episodic/generation/launcher_support.py`.

### HTTP contract (EP-M4)

`GET /v1/episodes/{episode_id}/qa-evaluations`

Query parameters: `evaluator` (optional, a `QaEvaluator` value),
`compliance_status` (optional, a `QaComplianceStatus` value), `limit`
(default 20, 1–100), `offset` (default 0, ≥ 0). Parse with
`parse_enum_param` and `parse_pagination` from `episodic/api/helpers.py`; do
not hand-roll parsers as `episodic/api/resources/generation_runs.py` was
obliged to for its cursor scheme.

Response `200`:

```json
{
  "items": [
    {
      "id": "0199a0c2-1e2a-7c7f-9a1e-6f0a1b2c3d4e",
      "episode_id": "0199a0c1-0000-7000-8000-000000000001",
      "generation_run_id": "0199a0c1-0000-7000-8000-000000000002",
      "evaluator": "pedante",
      "evaluator_version": "1",
      "artefact_schema_version": 1,
      "compliance_status": "non_compliant",
      "summary": "One claim lacks source support.",
      "rubric_score": null,
      "runtime_estimate_seconds": null,
      "evaluator_metadata": {"model": "gpt-4.1", "finish_reason": "stop"},
      "evaluated_at": "2026-08-23T10:15:00+00:00",
      "finding_count": 1
    }
  ],
  "limit": 20,
  "offset": 0,
  "total": 1
}
```

`GET /v1/qa-evaluations/{evaluation_id}` returns the same object with a
`findings` array in place of `finding_count`. Each finding serializes as
`{id, ordinal, severity, code, summary, remediation, subject_id, subject_text,
is_blocking, citations, details}`.

Authorization mirrors `episodic/api/resources/episode_tei.py`: resolve the
episode, resolve its `last_generation_run_id`, and require
`run.actor == principal_id(req)`. An episode that does not exist, has no
generation run, or belongs to another principal all return `404` with code
`not_found` — never `403`, which would leak existence.

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

episodic [...] qa evaluations show --id UUID [--format {table,json}]
```

`--base-url` defaults to the `EPISODIC_API_URL` environment variable, then to
`http://127.0.0.1:8000`. `--token` defaults to `EPISODIC_API_TOKEN`; it is sent
as `Authorization: Bearer <token>`. Never echo the token, and never place it in
a rendered table.

Exit codes: `0` success; `1` the API returned an error envelope (print
`message` to standard error, prefixed with the HTTP status); `2` usage error
(left to `cyclopts`); `3` the API was unreachable or timed out.

`--format table` prints a fixed-width table with columns `EVALUATOR`, `STATUS`,
`FINDINGS`, `EVALUATED AT`, `ID`, followed by a summary line
`3 of 3 evaluations`. `--format json` prints the API envelope verbatim,
pretty-printed with two-space indentation and a trailing newline, so it can be
piped into `jq`.

Keep the `cyclopts.App` construction, the HTTP client, and the renderers in
separate modules. The renderers must be pure functions from a parsed payload to
a string so `syrupy` can snapshot them without a process boundary; only
`episodic/cli/__init__.py` may write to standard output.

## Concrete steps

Work from the repository root,
`/home/leynos/.lody/repos/github---leynos---episodic/worktrees/c456469d-cdcd-4f92-bc74-871616264ba0`,
on branch `2-2-7-persist-qa-artefacts-linked-to-canonical-episodes.md`.

1. Establish the baseline. Run the four gates sequentially with `tee` as shown
   in Stage A. Expect all four to pass on the unmodified tree.

2. `EP-M0`. Edit the `[tool.hecate]` group prefix lists in `pyproject.toml`,
   then:

   ```bash
   make check-architecture 2>&1 | tee /tmp/arch-episodic-$(git branch --show-current).out
   ```

   Expect:

   ```plaintext
   Hecate: 0 violations
   ```

   Commit: `Group QA artefact modules for architecture enforcement`.

3. `EP-M1` red. Add `tests/test_qa_artefact_domain.py` asserting the enum value
   sets against the design-document taxonomy and the `__post_init__`
   rejections, plus `tests/test_qa_artefact_recording_properties.py` for
   `INV-COMPLIANCE-BLOCKING`. Run:

   ```bash
   uv run pytest tests/test_qa_artefact_domain.py -q
   ```

   Expect collection to fail with
   `ModuleNotFoundError: No module named 'episodic.canonical.qa_artefacts'`.

4. `EP-M1` green. Add `episodic/canonical/qa_artefacts.py` and
   `episodic/canonical/qa_artefact_ports.py`. Re-run the two test modules and
   expect them to pass. Run the negative control described under
   `INV-COMPLIANCE-BLOCKING`, confirm the property fails, and revert the
   control. Commit.

5. `EP-M2` red. Add `tests/canonical_storage/test_qa_artefacts.py` with the
   round-trip, cascade, and dangling-episode cases. Run:

   ```bash
   uv run pytest tests/canonical_storage/test_qa_artefacts.py -q
   ```

   Expect failure because `uow.qa_artefacts` does not exist.

6. `EP-M2` green. Add the enum constants, ORM models, mappers, store, unit-of-work
   registration, protocol attribute, and the Alembic migration. Then:

   ```bash
   make check-migrations 2>&1 | tee /tmp/migrations-episodic-$(git branch --show-current).out
   uv run pytest tests/canonical_storage -q
   ```

   Expect `check-migrations` to report no drift and the storage suite to pass.
   Add the property and replay test modules and run their negative controls.
   Commit.

7. `EP-M3`. Red then green for `episodic/qa/recording.py` and
   `episodic/canonical/qa_artefact_service.py`, with
   `tests/test_qa_artefact_recording.py` and
   `tests/test_qa_artefact_service.py`. Commit.

8. Milestone gate. Run the full sequence and expect all four to pass:

   ```bash
   make check-fmt && make typecheck && make lint && make test
   ```

   Prefer delegating this run to the `scrutineer` subagent, which executes the
   gates sequentially, captures each to a log under `/tmp`, and returns a
   bounded report.

9. `EP-M4`. Write `tests/features/qa_artefact_retrieval.feature` (REST
   scenarios only at this point) and its step module; confirm the scenarios
   fail. Add the resources, serializers, and route registration; confirm they
   pass. Generate the `syrupy` snapshots with a first run, inspect the `.ambr`
   file by eye before committing it, and only then accept it. Commit.

10. `EP-M5`. Add the CLI scenarios to the feature file; confirm they fail. Add
    `episodic/cli/`, update `[project.scripts]`, move `cyclopts` to runtime
    dependencies, and run `uv sync`. Confirm:

    ```bash
    uv run episodic qa evaluations list --help
    ```

    prints usage. Confirm the scenarios pass. Commit.

11. Milestone gate again (step 8).

12. `EP-M6`. Write both ADRs, update the design document, developers' guide,
    users' guide, `docs/contents.md`, and mark `docs/roadmap.md` item `2.2.7`
    done. Then:

    ```bash
    make fmt
    make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-$(git branch --show-current).out
    make nixie        2>&1 | tee /tmp/nixie-episodic-$(git branch --show-current).out
    ```

    `make fmt` can introduce MD013 violations on long inline code spans; if
    `markdownlint` reports MD013 after formatting, shorten or fence the
    offending span rather than lengthening the line limit. Run `make nixie`
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
........                                                            [100%]
8 passed in 0.51s
```

**BDD evidence.** The feature file `tests/features/qa_artefact_retrieval.feature`
must fail before `EP-M4`/`EP-M5` and pass after:

```bash
uv run pytest tests/steps/test_qa_artefact_retrieval_steps.py -q
```

**End-to-end acceptance, observed by a human.** With PostgreSQL available and
migrations applied, start the API, create an episode through the existing
source-to-script slice, record a Pedante evaluation, then:

```bash
curl -sS -H "Authorization: Bearer $EPISODIC_API_TOKEN" \
  "http://127.0.0.1:8000/v1/episodes/$EPISODE_ID/qa-evaluations?evaluator=pedante&compliance_status=non_compliant" \
  | jq '{total, first: .items[0].evaluator}'
```

Expect:

```json
{
  "total": 1,
  "first": "pedante"
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
- Verification: `INV-COMPLIANCE-BLOCKING`, `INV-FINDING-ORDER`,
  `INV-REPLAY-IDEMPOTENT`, `INV-FILTER-SOUND`, `INV-PAGINATION-PARTITION`,
  `INV-EPISODE-LINK`, `LEM-SERIALIZATION-STABLE`, and `LEM-CLI-RENDERING` are
  each discharged by the named artefact, and each negative control has been run
  once and observed to fail for the intended reason.
- Lint and typecheck: `make check-fmt`, `make typecheck`, and `make lint` all
  exit 0. `make lint` includes the blocking Skylos dead-code scan; investigate
  every finding rather than suppressing it. If Skylos flags a genuinely
  reachable symbol, prefer a typed entry-point rule in
  `[tool.skylos.dead_code]` naming the verified runtime caller, matching methods
  as `type = "method"`.
- Migrations: `make check-migrations` reports no drift.
- Documentation: `make markdownlint` and `make nixie` exit 0.
- Performance: no benchmark threshold applies. The two indexes on
  `qa_evaluations` cover both documented filters; do not add further indexes
  without a measured query.
- Security: the artefact stores evaluator summaries and remediation text, which
  may quote script content. Do not log finding text, do not place it in metric
  labels, and keep the CLI from writing the bearer token to standard output.

Quality method (how we check): run each gate sequentially via `make`, delegating
full gate runs to the `scrutineer` subagent so bulky output stays out of the
working context. When a gate fails, read the cited log under `/tmp` rather than
re-running it; re-run only after applying a fix.

## Idempotence and recovery

Every step is re-runnable. The Alembic migration is the only step that mutates
persistent state; `alembic downgrade -1` reverses it, and `upgrade()` creates
its enums with `checkfirst=True` so a partially applied run can be retried.
Test databases are ephemeral py-pglite instances recreated per session, so a
failed storage test leaves nothing behind.

`uv sync` after the dependency change is idempotent. If the `episodic` console
script does not appear on `PATH`, re-run `uv sync` and invoke it as
`uv run episodic`.

No step deletes or overwrites tracked content other than the `stilyagi` entry in
`[project.scripts]`, which references a module that does not exist in this
repository. Confirm that with a repository-wide search before removing it.

Keep `/tmp` logs; they are the evidence trail for this plan. Delete them only
after the retrospective is written.

## Artefacts and notes

Expected `make check-migrations` output at `EP-M2`:

```plaintext
No schema drift detected between models and migrations.
```

Expected Hecate output at `EP-M0`:

```plaintext
Hecate: 0 violations
```

Expected first `syrupy` run at `EP-M4`, before snapshots exist:

```plaintext
E  AssertionError: assert [+ received] == [- snapshot]
   Snapshot 'test_serialize_pedante_evaluation' does not exist!
```

after `uv run pytest tests/test_qa_artefact_serializers.py --snapshot-update`:

```plaintext
3 snapshots generated.
```

Inspect `tests/__snapshots__/test_qa_artefact_serializers.ambr` before
committing it. A snapshot accepted without reading is a test that asserts
whatever the code happened to do.

## Revision note

Initial draft, 2026-08-23. Establishes the QA artefact model, its persistence,
its REST and CLI retrieval surfaces, and the verification obligations that make
the filtering and replay behaviour falsifiable. Remaining work is the whole
plan; no implementation has begun.
