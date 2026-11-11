# Add immutable, content-addressed pricing snapshots (2.5.1)

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & discoveries`, `Decision log`,
`Outcomes & retrospective`, `Conformance basis`, and `Verification plan` must
be kept up to date as work proceeds.

Status: COMPLETE (2026-11-11)

## Purpose / big picture

Roadmap item `2.5.1` asks Episodic to "add immutable pricing snapshots for
provider and helper pricing inputs": persist the model pricing inputs used for
Large Language Model (LLM) and Text-to-Speech (TTS) billing, preserve room for
future helper-service pricing documents, and version snapshots so historical
run costs remain reproducible.

Roadmap item `2.4.4` already shipped a first cut: a `pricing_snapshots` table, a
`PricingSnapshot` value object, YAML rate cards under
`config/pricing-snapshots/`, and run-level pins. Planning research found that
the first cut does not yet deliver the three promises of `2.5.1`:

1. Historical costs are not reproducible from the database. A pinned provider
   call is priced from the YAML file (`FilePricingCatalogue.get_snapshot`), not
   from the persisted row. Editing a rate card file in place is silently
   ignored at persistence (`ON CONFLICT (id) DO NOTHING`) but used for pricing,
   so a resumed run can be priced with rates that no ledger row explains.
   Deleting the file breaks pinned runs outright.
2. Pricing inputs cannot be represented faithfully. Rates are integers in
   minor units per one million usage units, so OpenAI's real cached-input price
   of 7.5 cents per million tokens is stored as `8`. TTS rate cards (per
   character, per thousand characters, per minute of audio) have no home, and
   there is no service kind to tell LLM and TTS pricing apart.
3. Helper-service pricing documents (Service-Level Agreements for OpenAPI,
   SLA4OAI, plans) have nowhere to live, and the snapshot "version" is an
   implicit mixture of a hand-assigned identifier, a raw-file digest, a
   billing-period key, and an effective date.

After this change:

- Every pricing snapshot is an immutable, content-addressed document. Its
  version identity is a canonical SHA-256 content hash computed by the domain
  from a byte-exact, versioned canonical form (schema version `1`). The
  database assigns a surrogate identifier the first time it sees a given
  content hash, and returns the same identifier for the same content forever.
- Rates are exact integer fractions (`amount_minor` per `per_units` units of a
  stated `unit`), so 7.5 cents per million tokens, $15 per million characters,
  and 5 cents per minute of audio are all representable without rounding.
- A snapshot records whether it prices an `llm`, `tts`, or `helper_service`
  call and may carry its verbatim source document (for example an SLA4OAI plans
  document) whose digest is part of the content hash.
- Pinned provider calls are priced from the persisted snapshot. Editing or
  deleting a YAML rate card can never change the price of a run that already
  pinned the earlier version; the edit simply becomes a new version used by
  later runs.
- Reading a snapshot whose stored columns no longer hash to its stored content
  hash fails loudly with `PricingSnapshotIntegrityError`, so a manual `UPDATE`
  against the table is detected rather than silently changing history.

Success is observable as follows:

1. Running `make test` passes, including the new behaviour-driven development
   (BDD) feature `tests/features/pricing_snapshots.feature`, whose scenarios
   pin a run to a rate card, revise or delete the card file, and observe that
   the run's ledger entry and a fresh re-pricing from the persisted snapshot
   both still report the original cost while a new run uses the new price.
2. A Vidai Mock-served chat completion reporting 2,000,000 prompt tokens
   (1,000,000 cached) and 500,000 completion tokens is recorded at 53 minor
   units against a `gpt-4o-mini` card charging 8 minor units per million cached
   tokens (the pre-correction card, copied into a temporary catalogue), and
   still reprices to 53 minor units after the card is corrected to 7.5 minor
   units per million cached tokens; a new run prices the same usage at 52,
   which is also what the corrected shipped card charges.
3. A TTS rate card charging 1500 minor units per 1,000,000 input characters
   and 5 minor units per 60,000 output audio milliseconds is persisted, read
   back unchanged, and prices 2,000,000 characters plus 120,000 milliseconds at
   3010 minor units.
4. Upgrading an alpha database that holds rows written by the `2.4.4` schema
   converts those rows in place; each converted row passes the integrity check
   and hashes identically to the rewritten shipped YAML card of the same
   content, except the corrected `openai-2026-05.yaml` cached-input rate. That
   legacy row keeps the earlier hash, and the corrected card is a new
   content-addressed version.
5. `make check-fmt`, `make typecheck`, `make lint`, and `make test` all pass
   at the end of every milestone, and `make markdownlint` and `make nixie` pass
   after documentation changes.

## Constraints

- Hexagonal boundaries are enforced by Hecate (`[tool.hecate]` in
  `pyproject.toml`; ADR-014, ADR-022). Domain value objects, hashing, and port
  protocols live in the `domain_ports` group and import only `domain_ports`
  modules. `episodic.cost.recorder` stays in `application`. SQLAlchemy and YAML
  adapters stay in `outbound_adapter`. Every new module must be added to its
  group explicitly (Hecate assigns a module to the first matching group, and
  ungrouped modules are never checked, so prefixes must not shadow later groups
  and no new module may be left ungrouped).
- ADR-018 governs versioning: explicit repository writes, no ORM versioning
  library, no database trigger or privilege-based immutability. Immutability is
  enforced by the application (content addressing, insert-only writes, and an
  integrity check on read).
- Money stays integral. No `float` anywhere in pricing, no `Decimal` in
  persisted or wire formats. Rates are integer fractions; computed costs stay
  integer minor units (`computed_cost_minor`).
- The pricing engine's rounding semantics must not change in this item: cost
  remains `sum(usage * amount_minor // per_units)` per metric, which equals the
  existing `usage * rate // 1_000_000` whenever `per_units == 1_000_000`.
  Rounding policy belongs to roadmap items `2.5.3` and `2.5.4`.
- Integers inside a canonical pricing document (`amount_minor`, `per_units`,
  `schema_version`) must lie in `0 ..= 2**53 - 1` so any JSON implementation
  reproduces them exactly.
- No source file may exceed 400 lines (AGENTS.md). `episodic/cost/ports.py`
  and `episodic/cost/storage/adapters.py` are already at exactly 400 lines, so
  every addition there must be preceded by extraction.
- No new third-party dependency. Canonical JSON uses the standard library.
- Out of scope, owned by later roadmap items: SLA4OAI fetching, parsing, and
  OpenAPI `info.x-sla` discovery (`2.5.2`); listing snapshot versions and
  catalogue selection policy beyond what is stated here (`2.5.2`); quota,
  overage, rounding policy, and exact (sub-minor-unit) cost (`2.5.3`); ledger
  columns for model metadata, plan identifiers, and rounding rules (`2.5.4`);
  budget reservation (`2.5.5`); any TTS adapter or TTS usage producer (ADR-013
  work).
- No source-API compatibility machinery: the cost package is application
  internal and pre-1.0. When a signature changes, every caller and test changes
  in the same commit. Persisted data is different: rows written by the `2.4.4`
  schema exist in alpha databases and must be migrated, not dropped.
- Documentation uses en-GB-oxendict spelling, wraps prose at 80 columns, and
  follows `docs/documentation-style-guide.md`.

## Tolerances (exception triggers)

- Scope: if any single milestone needs more than 45 changed files or more
  than 2,500 net changed lines (tests included), stop and escalate with a
  proposed split.
- Interface: if any REST, Celery task, or LangGraph checkpoint payload shape
  must change, stop and escalate. (Internal Python signatures inside
  `episodic.cost` and its direct callers may change.)
- Dependencies: if a new runtime or development dependency appears necessary
  (for example an RFC 8785 library), stop and escalate.
- Persisted format: if the migration cannot convert every `2.4.4` row so that
  it hashes identically to its rewritten YAML card, stop and escalate rather
  than weakening the integrity check. The deliberately corrected
  `openai-2026-05.yaml` cached-input rate is the one exception: its legacy row
  keeps the earlier hash and the corrected card is a new version.
- Rounding: if any test can only pass by changing the floor-per-metric
  rounding rule, stop and escalate; that decision belongs to `2.5.3`.
- Architecture: if Hecate needs a new group or a new allowed edge, stop and
  escalate.
- Iterations: if a gate still fails after three focused fix attempts, stop and
  record the failure evidence in `Surprises & discoveries`.
- Time: if a milestone exceeds one working day of agent time, record progress
  and escalate.
- Ambiguity: if an operator-supplied catalogue directory in the old format is
  discovered in a real deployment (not just alpha previews), stop and present
  the options recorded in `Decision log` (fail fast versus a legacy reader).

## Risks

- Risk: canonical hashes computed by the migration drift from those computed
  by the domain (date encoding, key order, rate reduction), so every converted
  row fails its integrity check after deploy. Severity: high. Likelihood:
  medium. Mitigation: a byte-level v1 hash specification with test vectors in
  ADR-028; the migration's frozen inline canonicalizer is tested against the
  domain function on the same rows, and against each rewritten shipped YAML
  card.
- Risk: a rolling deployment runs old pods against the migrated schema (old
  pods still write `rates_minor_per_metric` and `billing_period_key`).
  Severity: medium. Likelihood: medium (the chart uses `RollingUpdate`;
  migrations are run by hand per `docs/alpha-test-4-3-2-setup-notes.md`).
  Mitigation: document a stop-the-world upgrade (scale launchers and workers to
  zero, migrate, roll out) in `docs/users-guide.md`. Old pods fail on
  `NOT NULL` columns rather than corrupting data.
- Risk: an operator has mounted their own catalogue directory through
  `PRICING_SNAPSHOT_DIRECTORY` in the old file format. Severity: medium.
  Likelihood: low (alpha only). Mitigation: the catalogue validates eagerly at
  startup and rejects legacy files with an error that names the file and points
  to the conversion section of the users' guide; boot fails instead of a paid
  run.
- Risk: floor-per-metric rounding records small calls as zero (for example a
  2,000-token gpt-4o-mini call), and every snapshot written now will be priced
  that way until `2.5.3` changes the engine. Severity: medium. Likelihood:
  high. Mitigation: snapshots carry pricing inputs only, never a rounding rule,
  so `2.5.3` can introduce a rounding rule recorded per ledger row (`2.5.4`)
  without invalidating any snapshot hash. The roadmap entries for `2.5.3` and
  `2.5.4` gain explicit hand-off bullets.
- Risk: pricing failures raised inside the generation success transaction
  roll back an already-paid draft (pre-existing behaviour for `LookupError`,
  which `classify_failure` reports as `unexpected`). Severity: medium.
  Likelihood: low after this change (content addressing removes the
  in-place-edit failure mode). Mitigation: map `PricingSnapshotError` to the
  stable failure category `cost.pricing_snapshot`; record the broader "persist
  the draft, mark cost unpriced" option for `2.5.5` in `Decision log`.
- Risk: removing `billing_period_key` from the snapshot surprises readers of
  `2.4.4` documentation. Severity: low. Likelihood: medium. Mitigation: ADR-028
  and the design document explain that billing periods belong to run pins,
  ledger rows, and quotas, and rate applicability is governed by
  `effective_from`.
- Risk: `RunPricingKey` (and the `run_pricing_pins` primary key) has no
  service kind, so an LLM and a TTS subject sharing provider, model, and
  operation would share one pin. Severity: low. Likelihood: low (no TTS
  producer exists yet). Mitigation: recorded as a residual risk for the first
  TTS adapter; no pin-key change in `2.5.1`.
- Risk: two concurrent `ensure` calls for identical content race. Severity:
  low. Likelihood: medium. Mitigation:
  `INSERT … ON CONFLICT ON CONSTRAINT
  uq_pricing_snapshots_content_hash DO NOTHING RETURNING id`
  followed by a `SELECT` in a new statement; extend
  `tests/test_cost_snapshot_concurrency.py` to assert both callers receive the
  same identifier.

## Progress

- [x] (2026-10-16) Renamed branch to `2-5-1-immutable-pricing-snapshots`.
- [x] (2026-10-16) Reconnaissance with a Wyvern team: existing cost code,
  persistence and test conventions, and design documents.
- [x] (2026-10-16) Prior-art research with Firecrawl: SLA4OAI 0.10.0
  structure, LiteLLM per-unit cost keys, Langfuse effective-dated model prices,
  RFC 8785 canonical JSON.
- [x] (2026-10-16) Draft design brief reviewed by a six-member expert panel
  (structure, alternatives, scaling, contracts, failure modes, viability);
  verdict "revise"; revisions folded into this plan (see `Decision log`).
- [x] (2026-10-16) ExecPlan drafted.
- [x] (2026-10-24) ExecPlan restored after the uncommitted draft was lost
  from the worktree, gated, and committed.
- [x] (2026-10-24) Final read-only consistency review of the written plan
  against the code; corrections applied (see revision note).
- [x] (2026-11-10) Plan approved by the user; implementation started.
- [x] (2026-11-10) EP-M1: shared leaf modules and ADR-028 draft. Gates green:
  `make check-fmt`, `make typecheck`, `make lint`, `make test` (1725 passed, 1
  skipped), `make check-migrations`, `make markdownlint`, `make nixie`.
- [x] (2026-11-10) EP-M1 rebased onto `main` at `92663d12` after 20 upstream
  commits; Hecate and Skylos entries survived the weave. Upstream drift
  reconciled into this plan (see `Surprises & discoveries`).
- [x] (2026-11-10) EP-M2: persisted read path and
  `PricingSnapshotRepository`. Red commit `840ffa54`; green commit `9eb67a65`.
  Gates green at `9eb67a65`: `make check-fmt`, `make typecheck`, `make lint`
  (ruff, pylint 10.00/10, df12 lints, ambrleaks, Skylos, nose duplication gate,
  docstring coverage 100%), `make test` (2127 passed, 1 skipped),
  `make check-migrations`, `make markdownlint`, `make nixie`. Milestone
  CodeRabbit CLI review completed against `92663d12..9eb67a65`; valid findings
  actioned and the id-reuse major finding deferred to EP-M3 by design. Final
  candidate `b7a873f2` re-gated green (2128 passed, 1 skipped) and re-reviewed:
  35/35 changed files, 0 findings, outcome `completed_with_warnings`
  ("unverified findings"), so the zero is recorded as no verified findings
  rather than a guaranteed clean diff. The CLI's included-review allowance was
  exhausted during that run; no retry was attempted.
- [x] EP-M3: schema version 1 snapshots, content addressing, and migration
  `20261110_000017`. Red tests were committed with strict `xfail` markers: the
  v1 domain model, canonical hash, and their property tests passed (48 passed);
  the engine, catalogue, store, recorder service-kind, and migration tests were
  strict `xfail` (28 xfailed) because the integration surface still used the
  legacy representation. Deviation recorded in the `Decision log`: the two new
  domain modules are additive and were committed with their passing tests,
  because a module-level import cannot be expressed as a strict `xfail` without
  lazy-import scaffolding. Implementation now replaces the legacy
  representation end to end: domain model, canonical hash, engine, v1 catalogue
  parser, recorder service kind, content-addressed store, ORM model, migration,
  and the three shipped cards. The `INV-ARCH` structural test
  `tests/test_production_hecate_cost_config.py` was added and its negative
  control run: a temporary `import sqlalchemy` in `pricing_snapshot.py` was
  rejected with
  `ARCH001: episodic.cost.pricing_snapshot:30 imports forbidden
  module sqlalchemy (domain_ports -> external_libraries)`.
  ADR-028 now carries the three hash vectors from
  `tests/__snapshots__/test_cost_pricing_snapshot_hash.ambr`. The first
  milestone gate run failed only at the df12-pylint stage: 68 `C9102`
  (assert-missing-message) findings across ten new test modules and one `R9108`
  (prefer-snapshot-assertion) at
  `tests/test_pricing_snapshot_content_address_migration.py`. Every flagged
  assertion now states the invariant it checks, and the converted `rates`
  comparison became a syrupy snapshot
  (`tests/__snapshots__/test_pricing_snapshot_content_address_migration.ambr`).
  The focused df12-pylint run then scored 10.00/10 and the ten affected modules
  passed (90 passed, 4 snapshots). The next gate run cleared every earlier
  stage and then stopped at `ambrleaks`, which flagged the four documented
  content hashes and the public `https://openai.com/api/pricing/` URL inside
  the new hash snapshot. `ambrleaks.toml` now allowlists those exact values, as
  the developers' guide prescribes for deterministic public test data. That
  run's `make test` also timed out once at py-pglite setup in the pre-existing
  `tests/test_env_runtime_wiring.py`; the test then passed alone and with its
  sibling parameter, so the timeout was host contention rather than a
  regression. With lint reaching past `ambrleaks` for the first time, Skylos
  reported nine dead-code findings, all in EP-M3 files: `parse_retrieved_at`
  and the docstring-only `_example_snapshot` were genuinely unused and are
  deleted; the unused `path` parameter of `_source_document` is removed; the
  migration's one-call `_row_count` helper is inlined into `downgrade`; and the
  five `PricingSnapshot` validators reached only from the dataclass
  `__post_init__` hook gained precise entry-point rules in `pyproject.toml`
  naming that hook as the verified runtime caller. A standalone Skylos run now
  exits 0, and the nose duplication gate passes standalone (`make duplication`,
  30 allowed by reasoned exceptions). All seven gates then passed on candidate
  `f3e75c8a` (`make test` 2204 passed, 1 skipped, 71 snapshots; no timeout),
  and the milestone CodeRabbit CLI review completed over 64 of 64 changed files
  against `92663d12`, reporting five `trivial` findings and no high or medium
  ones. All five were valid and are fixed: the ExecPlan's machine-specific
  checkout path became a branch-relative instruction; the stale
  `episodic.cost.primitives._validate_currency_code` Skylos entry was deleted;
  `pricing_snapshot_ports` now imports `PricingSnapshot` from its defining
  module and names it in the docstring; the concurrency test asserts the
  surviving pin references the stored snapshot; and the observability test now
  drives the real insert-conflict path through an autospecced session instead
  of patching `_ensure_snapshot`. The re-gate on `1c1cab9d` passed all seven
  gates (`make test` 2205 passed, 1 skipped, 71 snapshots), and the second
  milestone review covered 64 of 64 changed files with two findings, no high or
  medium ones. Both were valid and are fixed: `load_snapshot` now guards
  `read_text` so an unreadable or undecodable card raises
  `PricingCatalogueError` naming the file (with regression tests for invalid
  UTF-8 and an unreadable path), and the legacy `pricing_snapshots` table
  definition and its revision moved to
  `tests/fixtures/legacy_pricing_snapshots.py`, imported by both migration
  suites instead of duplicated. The re-gate on `058925bf` passed all seven gates
  (`make test` 2207 passed, 1 skipped, 71 snapshots), and the third milestone
  review covered 65 of 65 changed files with zero findings
  (`outcome: completed`). EP-M3 is complete.
- [x] EP-M4: behavioural coverage, Vidai Mock scenario, and the 7.5-cent
  correction. `tests/features/pricing_snapshots.feature` holds the six
  scenarios from `Validation and acceptance`, declared in
  `tests/steps/test_pricing_snapshots_steps.py`. Shared card writers, recorder
  builders, and persist/read/tamper helpers live in
  `tests/steps/pricing_snapshots_support.py`; the Vidai Mock provider config
  and cached-token template live in
  `tests/steps/pricing_snapshots_vidaimock.py`, and process startup reuses
  `tests/steps/vidaimock_harness.py` rather than copying its orchestration.
  Every scenario writes its own pre-correction card into `tmp_path` and rebuilds
  `FilePricingCatalogue` after a revision or deletion, since the catalogue
  loads eagerly. The Vidai Mock scenario calls the server through
  `OpenAICompatibleLLMAdapter`, records the provider-reported usage through the
  real `CostRecorder` on py-pglite, and so proves the cached-token split prices
  at 52 minor units after the revision.
  `config/pricing-snapshots/openai-2026-05.yaml` now charges
  `amount_minor: "7.5"` per million cached input tokens, replacing the rounded
  `1 / 125000` (8 per million); this is an in-place edit, so it becomes a new
  content-addressed version while historical runs keep the earlier one.
  `tests/test_shipped_pricing_cards.py` loads the shipped directory, asserts
  the corrected rate is `MeteredRate.reduced(3, 400_000, UsageUnit.TOKEN)`,
  prices the behavioural usage at 22 minor units, and shows the corrected card
  has a different content hash from the pre-correction text. The behavioural
  suite passed (6 passed), the shipped-card tests passed (2 passed), and the
  affected set including the wiring and chart contracts passed (31 passed, 1
  skipped). The first gate run stopped at Pylint: the step module exceeded 400
  lines and `record_llm_call` took seven arguments. The step definitions moved
  to `tests/steps/pricing_snapshots_step_definitions.py`, registered through
  `pytest_plugins` in `tests/conftest.py` because pytest-bdd installs each step
  as a fixture in its defining module; the optional call identity became a
  `CallOptions` value object, and the Vidai Mock call moved into
  `record_completion`. Both modules are now under 400 lines and Pylint scores
  10.00/10 on them. The new module also omits
  `from __future__ import annotations`, which the 3.14 baseline rejects outside
  the `test_*_steps.py` files the Makefile excludes from that check. All seven
  gates then passed on `426439cb` (`make test` 2215 passed, 1 skipped, 71
  snapshots); the first `check-migrations` attempt exited 2 on a transient
  PGlite failure and passed on re-run with no drift. The milestone review
  covered 72 of 72 changed files with three findings. Two were valid and are
  fixed: the legacy-card rejection now points to the conversion guidance, with
  the test asserting it, and the shipped-card test anchors its directory to the
  repository root. The third — fail startup when the pricing directory is
  absent — is already satisfied: `_pricing_snapshot_directory` in
  `episodic/api/runtime_config.py` raises `RuntimeConfigurationError` unless
  the resolved path is a directory, and `tests/test_runtime_configuration.py`
  covers it; the catalogue's empty-cache behaviour is reachable only for
  callers that bypass runtime configuration. The re-gate on `9821d178` passed
  all seven gates (`make test` 2215 passed, 1 skipped, 71 snapshots; lint exit
  0 with no findings; `make check-migrations` passed first attempt), and the
  final milestone review covered 72 of 72 changed files with zero findings
  (`outcome: completed`). EP-M4 is complete.
- [x] EP-M5: documentation, roadmap, and final gates. The pricing ADR is
  `docs/adr/adr-028-content-addressed-pricing-snapshots.md`, status
  `Accepted on 2026-11-11`; it was renumbered from 024 because
  `adr-024-review-checkpoint-persistence.md` already held that number (see
  `Surprises & discoveries` and the decision log). ADR-015 gained an amendment
  note, a corrected Neutral TTS bullet, and a 2026-11-11 addendum recording
  that ADR-028 supersedes its 2026-10-10 snapshot representation. The design
  document now lists ADR-028, describes `PricingSnapshotRepository`, and
  replaces the provider-rate-card-only cost bullets, the future SLA contract,
  and the `pricing_snapshots` data-model bullet with the content-addressed
  model. `docs/users-guide.md` gained a `#### Pricing snapshots` section: the
  schema-version-1 field list, an exact 7.5-per-million rate, full LLM and TTS
  cards, how to correct a card, legacy conversion, the `cost.pricing_snapshot`
  failure category, and the stop-the-world upgrade order.
  `docs/developers-guide.md` replaced the stale `ensure_snapshot` and
  `PricingSnapshotCollisionError` paragraph and gained a "Cost accounting and
  pricing snapshots" section covering the repository, integrity check,
  telemetry, canonical form, metric vocabulary, and test fixtures.
  `docs/contents.md` now indexes ADR-028, the cost ADR-015, the `2.4.4`
  ExecPlan, and this ExecPlan; `docs/repository-layout.md` adds `config/` and
  `episodic/cost/`; `docs/roadmap.md` marks `2.5.1` done and hands the rounding
  rule to `2.5.3` and `2.5.4`. Every documented claim was checked against the
  source: the `UsageUnit` and `PricedService` values, the
  `^[a-z][a-z0-9_]{0,63}$` metric pattern, the `pricing_snapshot.ensure` and
  `pricing_snapshot.get` telemetry, the `cost.pricing_snapshot` mapping, and
  `v1_pricing_snapshot()` in `tests/fixtures/cost.py`. The first full gate run
  on `295af018` passed all seven gates, and the milestone review covered 79 of
  79 changed files with 17 advisory findings. All were verified against the
  source and actioned: the migration now rejects a legacy row that cannot
  become a valid version 1 snapshot (blank subject, malformed currency, unknown
  source kind, a plan without its document, or an empty rate card);
  `PricingSubjectFields` declares read-only properties so frozen snapshots
  satisfy it; the card loader rejects duplicate YAML keys; the port docstrings
  document `LookupError` and `PricingSnapshotIntegrityError`; the catalogue
  tests assert the empty-catalogue `LookupError` and use tuple comparisons; the
  loader rejection tests are parametrized; and the ADR, ExecPlan, and users'
  guide were corrected for the corrected-card hash exception, the backup and
  shutdown order, the complete-backup requirement, the legacy rate denominator,
  effective-date selection, the `ports.py` inventory, and `set -e`/`pipefail`
  around the `tee` gate commands.

## Surprises & discoveries

- Observation: pinned provider calls are priced from the YAML file, not the
  persisted row. Evidence was `episodic/cost/recorder.py:229` returning
  `await self.pricing_catalogue.get_snapshot(pinned_snapshot_id)`. Resolved by
  EP-M2: the recorder now reads `await self.snapshots.get(pinned_snapshot_id)`
  through `PricingSnapshotRepository`, and the pinned-path integration tests
  pass after the rate-card file is edited or deleted.
- Observation: an in-place edit of a rate card under the same identifier is
  reported as `reused` and leaves the old row, while pricing uses the edited
  file. Evidence: `_snapshot_insert_statement` still uses
  `on_conflict_do_nothing(index_elements=["id"])`, now in
  `episodic/cost/storage/pricing_snapshot_store.py`. The id remains the
  identity, so `ensure` cannot tell a reused row from a silently different one;
  the milestone CodeRabbit review raised this as its only major finding.
  Impact: EP-M2 deliberately leaves it for content addressing (EP-M3), which
  makes the content hash the identity; the migration and the collision tests
  inherit the responsibility.
- Observation: shipped rate cards round real prices. Evidence:
  `config/pricing-snapshots/openai-2026-05.yaml` sets `cached_input_tokens: 8`
  where the provider price is 7.5 cents per million tokens. Impact: exact
  integer fractions (EP-M3) and a corrective new version (EP-M4).
- Observation: runs started in a month with no rate card fail. Evidence:
  `FilePricingCatalogue.resolve` matches `billing_period_key` exactly
  (`episodic/cost/pricing_catalogue/file_loader.py:209-221`), shipped cards
  cover `2026-05` and `2026-08`, and launchers derive the key from the clock
  (`episodic/generation/launcher_persistence.py:153`). Impact: removing the
  billing period from the snapshot (EP-M3) fixes this as a side effect; a
  regression test is added.
- Observation: `episodic/cost/ports.py` and `episodic/cost/storage/adapters.py`
  are both exactly 400 lines. Impact: extraction precedes every addition.
  Update (2026-11-10): `ports.py` is 380 lines after EP-M1 extracted
  `episodic/cost/primitives.py`; `adapters.py` was still 400, so EP-M2's
  extraction of the snapshot store was a precondition, not a nicety. After
  EP-M2, `adapters.py` is 243 lines and the snapshot store holds the
  instrumentation that moved with it.
- Observation: there are three ADR-015 files and the cost ADR-015 is missing
  from `docs/contents.md`; the `2.4.4` ExecPlan is also unlisted. Impact: EP-M5
  fixes the index entries.
- Observation (2026-11-11): the planned ADR number 024 was already taken by
  `adr-024-review-checkpoint-persistence.md`, which upstream landed while this
  branch was in flight; the original reconnoitre saw the directory ending at
  023. Impact: the pricing ADR is renumbered to 028 and every reference was
  updated. Lesson: an ADR number claimed in a plan is only a reservation that
  upstream can invalidate, so recheck `docs/adr/` before the final index pass.
- Observation: the migration-head revision `20261010_000013` is hard-coded in
  `tests/test_pricing_snapshot_constraint_migration.py:207`, and that file's
  offline test migrates to `head`. Impact: EP-M3 pins those tests to
  `20261010_000013` explicitly.
- Observation (2026-11-10): upstream `main` advanced past this plan while it was
  being written. The Alembic head is now `20261031_000016`
  (`20261020_000014_add_review_checkpoints.py`,
  `20261020_000015_add_expired_lease_index.py`, and
  `20261031_000016_add_qa_artefact_tables.py` landed first), so the proposed
  `000014` content-addressing migration collides by filename and by
  `down_revision`. None of those migrations touches `pricing_snapshots`.
  Impact: EP-M3 creates `20261110_000017_content_address_pricing_snapshots.py`
  with `down_revision = "20261031_000016"`; migration tests seed legacy rows
  after upgrading to `20261031_000016` (the immediate parent) and assert
  rollback lands there rather than at `20261010_000013`. The `000013` pin in
  the constraint-migration test is where the named constraint was introduced
  and stays.
- Observation (2026-11-10): `main` also added comprehensive docstrings across
  `episodic/cost/*` (docstring coverage gate, #424) and split
  `SqlAlchemyUnitOfWork` store construction into `_open_catalogue_stores`,
  `_open_intake_stores`, and `_open_instrumented_stores`, with
  `CanonicalUnitOfWork` now also exposing `generation_runs` and `qa_artefacts`.
  Impact: EP-M2 attaches `pricing_snapshots` inside the instrumented-stores
  helper, next to `cost_ledger`, and new public members need NumPy-style
  docstrings for the coverage gate.
- Observation: no Vidai Mock test exercises the real `CostRecorder`; the
  orchestration BDD steps use `_RecordingCostRecorder`
  (`tests/steps/test_generation_orchestration_steps.py:102`). Impact: the Vidai
  Mock scenario in EP-M4 drives the OpenAI-compatible adapter directly and
  records through the real recorder against py-pglite.
- Observation: the first uncommitted draft of this plan was lost from the
  worktree while the session was suspended during a slow first `make fmt` run
  (which was building the virtual environment). Evidence: on 2026-10-24
  `git status` was clean and `/tmp` scratch files were gone. Impact: commit
  living documents before any long-running gate; the implementer should commit
  each red, green, and refactor step promptly.

## Decision log

- Decision (2026-11-11, EP-M5): the pricing ADR is renumbered from 024 to 028.
  Rationale: `adr-024-review-checkpoint-persistence.md` landed from upstream
  before this branch reached EP-M5, so keeping 024 would leave two different
  decision records with one number. Renumbering costs one file move and a
  mechanical reference update; a duplicate number would persist indefinitely in
  the index, the design document, and the catalogue's conversion guidance.
  ADR-015's amendment note, the design document, the developers' guide,
  `docs/contents.md`, `episodic/cost/pricing_catalogue/_document.py`, and
  `tests/test_cost_pricing_snapshot_hash.py` all point at 028.
- Decision (2026-11-10, EP-M2): snapshot persistence and reads get their own
  port and adapter instead of staying on the ledger and catalogue ports.
  Rationale: the ledger is an append-only cost journal and the catalogue is a
  file-backed resolver; neither owns the stored snapshot lifecycle, and the
  ledger store was already at the 400-line limit. The instrumentation moved
  with the code, so the ledger store no longer accepts metrics, tracer, or
  clock parameters it would not use. Trade-off: one more unit-of-work member
  and one more Hecate `domain_ports` entry.
- Decision (2026-11-10, EP-M2): `ensure` keeps the identifier as the conflict
  target and does not compare stored content before returning `REUSED`.
  Rationale: EP-M3 makes the content hash the identity, at which point a
  same-identifier/different-content row cannot exist; adding a comparison now
  would be deleted by the next milestone. The milestone CodeRabbit review
  raised this as its only major finding, and it is recorded in
  `Surprises & discoveries` as EP-M3's responsibility.
- Decision: content-addressed identity replaces authored revision numbers.
  The version identity of a snapshot is its canonical content hash; the
  database assigns a UUIDv7 surrogate `id` the first time it stores a hash and
  returns that `id` for the same content thereafter. YAML files no longer carry
  `pricing_snapshot_id`. Rationale: the panel showed that authored revisions
  create two sources of truth (authored numbers versus migration backfill),
  collide across billing periods and helper plans, and turn an in-place file
  edit into a production failure. Content addressing makes an edit a new
  version by construction, removes the immutability, collision, and
  revision-conflict error paths, matches ADR-018's "content-hashed documents"
  wording, and is the only identity that works for SLA4OAI documents fetched in
  `2.5.2`. Trade-off: no human-readable "revision 2"; chronology comes from
  `effective_from` and the new `recorded_at` column, and git history is the
  authoring trail. Date/Author: 2026-10-16, planning agent after expert-panel
  review.
- Decision: `billing_period_key` leaves the snapshot. Rate applicability is
  governed by `effective_from`; billing periods stay on run pins, ledger rows,
  and metering counters. `FilePricingCatalogue.resolve` selects the applicable
  card with the greatest `effective_from <= now` for a `PricingSubject`.
  Rationale: a rate card is not period-scoped (SLA4OAI's `billing` is a cycle),
  the exact-match rule forces a new file every month and already breaks runs in
  months without a card, and the subject used for version ordering must not
  depend on it. Date/Author: 2026-10-16, planning agent.
- Decision: rates are exact integer fractions in lowest terms.
  `MeteredRate(amount_minor, per_units, unit)` is normalized to lowest terms at
  construction (`amount_minor == 0` normalizes to `0/1`). YAML authors may write
  `amount_minor` as an integer or a decimal string (for example `"7.5"`) plus
  `per_units`; the loader converts exactly. Rationale: decimal strings cannot
  express per-minute TTS prices (5 cents per 60,000 milliseconds), a fixed
  global scale only moves the precision limit, and lowest terms make the hash
  independent of authoring scale (75 per 10,000,000 and 15 per 2,000,000 hash
  identically). Date/Author: 2026-10-16, planning agent.
- Decision: snapshots carry pricing inputs only, never a rounding rule.
  `schema_version` means the document format and hash field list, nothing else.
  Rationale: tying rounding to the document format would freeze
  floor-per-metric onto every card written now and conflate two concerns.
  `2.5.3` and `2.5.4` own the rounding rule and record it per ledger row.
  Date/Author: 2026-10-16, planning agent.
- Decision: units are data; metric names are validated but open. Each rate
  carries a `UsageUnit` from a closed set (`token`, `character`, `millisecond`,
  `request`). Metric names must match `^[a-z][a-z0-9_]{0,63}$`. The developers'
  guide documents a recommended vocabulary, adding `input_characters` and
  `output_audio_milliseconds` for TTS. Rationale: no TTS usage producer exists
  yet, so a closed metric table would be a guess; `2.5.3` may close the
  vocabulary when usage producers exist. Date/Author: 2026-10-16, planning
  agent.
- Decision: the source document is stored as verbatim text plus media type,
  and the canonical form hashes its SHA-256 digest. Required when `source_kind`
  is `sla4oai_plan`; optional otherwise; capped at 262,144 UTF-8 bytes. No
  parsing in `2.5.1`. Rationale: JSONB reorders keys and drops duplicates, YAML
  parsing produces dates and floats that canonical JSON cannot represent
  faithfully, and parsing is `2.5.2` work. Date/Author: 2026-10-16, planning
  agent.
- Decision: one `PricingSnapshot` type with explicit invariants rather than a
  tagged union of document kinds. Rationale: LLM and TTS differ only by service
  kind and metrics; the SLA4OAI case differs by having a required source
  document and possibly no normalized rates. A union would double the ORM
  mapping and store code for a kind that has no consumer until `2.5.2`. Revisit
  in `2.5.2` if SLA4OAI normalization adds kind-specific fields. Date/Author:
  2026-10-16, planning agent.
- Decision: `plan_name`, `list_revisions`, and a subject lookup index are
  deferred to `2.5.2`. Rationale: nothing in `2.5.1` calls them, and Skylos
  would flag dead code. Date/Author: 2026-10-16, planning agent.
- Decision: the content hash is derived. `PricingSnapshot.content_hash` is a
  `dataclasses.field(init=False)` computed in `__post_init__` from deep-frozen
  fields (`types.MappingProxyType`). Adapters never supply a hash; the SQL
  adapter compares the stored hash with the recomputed hash on read and raises
  `PricingSnapshotIntegrityError` on mismatch. Rationale: a hash supplied by
  callers is not an invariant; recomputation on read is ADR-018's
  application-enforced immutability. Date/Author: 2026-10-16, planning agent.
- Decision: both instants are timezone-aware `datetime` values in the domain
  (`retrieved_at` changes from `str`), encoded in the canonical form as UTC
  `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Rationale: PostgreSQL `timestamptz` returns
  UTC with microsecond precision; any other encoding makes valid rows fail the
  integrity check. Date/Author: 2026-10-16, planning agent.
- Decision: `canonical_json_bytes` moves from
  `episodic/canonical/idempotency_service.py` (application group) to a new leaf
  module `episodic/json_canonicalization.py` (domain_ports group), and both
  source intake and pricing use it. Rationale: AGENTS.md requires reuse of an
  existing helper; the domain cannot import the application group; and a leaf
  module outside the `episodic.canonical` package keeps domain imports from
  executing `episodic/canonical/__init__.py`, which pulls in ingestion and
  services modules (an import-cycle risk, because
  `episodic/canonical/storage/uow.py` already imports `episodic.cost.storage`).
  Date/Author: 2026-10-16, planning agent.
- Decision: legacy-format catalogue files fail fast at startup rather than
  being read by a legacy reader. Rationale: a second reader is compatibility
  machinery whose only known consumer is an alpha preview; failing at boot (not
  mid-run) with an actionable message and documented conversion is sufficient.
  Escalate if a real operator catalogue is found (see `Tolerances`).
  Date/Author: 2026-10-16, planning agent.
- Decision: deployment is stop-the-world for this migration, and offline
  (`--sql`) upgrade emits a guard that raises unless `pricing_snapshots` is
  empty; downgrade refuses with `CommandError` unless the table is empty.
  Rationale: hash recomputation needs Python and live rows; an expand-contract
  migration would keep dead columns purely for old pods in alpha previews.
  Date/Author: 2026-10-16, planning agent.
- Decision: failing a paid run because pricing failed remains the behaviour
  in `2.5.1`, but `PricingSnapshotError` maps to failure category
  `cost.pricing_snapshot`. Persisting the draft and marking cost "unpriced" is
  recorded as an option for `2.5.5` (budget workflow). Rationale: changing
  generation transaction boundaries is outside this item; the panel's scenario
  that motivated it (in-place edits) no longer fails runs. Date/Author:
  2026-10-16, planning agent.
- Decision: the Vidai Mock end-to-end scenario drives the OpenAI-compatible
  adapter and the real `CostRecorder` against py-pglite, alongside a recorder
  integration test that needs no inference service. Rationale: the user
  requires Vidai Mock for behavioural testing of inference services; Vidai Mock
  supplies wire-accurate usage (including cached-token details) that exercises
  normalization and fractional rates, while the integration test is the minimal
  proof of reproducibility. Date/Author: 2026-10-16, planning agent.
- Decision: EP-M3's red commit carries the two new domain modules
  (`pricing_snapshot.py`, `pricing_snapshot_hash.py`) and their passing tests,
  while the integration tests for the engine, catalogue, store, recorder, and
  migration carry strict `xfail` markers. Rationale: a module-level import of a
  not-yet-committed module is a collection error, not an `xfail`, and lazy
  imports inside every test would be scaffolding that the implementation commit
  immediately deletes. The red evidence is therefore the 28 strict `xfail`
  integration tests, which fail against the legacy representation for the
  intended reason. Date/Author: 2026-11-10, implementation agent.

## Outcomes & retrospective

### EP-M1 (2026-11-10)

- `canonical_json_bytes` moved to `episodic/json_canonicalization.py` and both
  source-intake call sites now import it there. `episodic.cost.primitives`
  holds the shared identifiers, `CostAccountingError`, `PricingSourceKind`, and
  the currency validator; `episodic.cost.ports` re-exports them through its
  imports.
- `pyproject.toml` adds both leaf modules to the Hecate `domain_ports` group
  and repoints the Skylos entry at `episodic.cost.primitives`.
- ADR-028 is drafted with status `Proposed`, the normative schema version 1
  canonical form, and migration and risk notes. Test vectors are filled in
  EP-M3.
- Conformance check: no behaviour change, no public interface change, no
  persisted-format change. Gates: `check-fmt`, `typecheck`, `lint`, `test`,
  `check-migrations`, `markdownlint`, `nixie` all green.

### EP-M2 (2026-11-10)

- `PricingSnapshotRepository` now owns persistence and reads:
  `ensure(snapshot)` returns `EnsuredPricingSnapshot` (`PERSISTED` or
  `REUSED`), and `get(id)` rebuilds the snapshot from the stored row or raises
  `PricingSnapshotNotFoundError` (a `LookupError`). `ensure_snapshot` left
  `CostLedgerPort` and `get_snapshot` left `PricingCataloguePort`; the file
  catalogue now only resolves the latest card.
- `SqlAlchemyPricingSnapshotStore`
  (`episodic/cost/storage/pricing_snapshot_store.py`) keeps the id-conflict
  no-op insert and named content-hash collision check, and carries the snapshot
  telemetry that used to live in the ledger store: `pricing_snapshot.ensure` /
  `pricing_snapshot.get` counters, matching duration metrics, spans
  `pricing_snapshot.ensure_snapshot` and `pricing_snapshot.get_snapshot`, and
  the `input_invalid`, `collision`, `integrity`, and `not_found` failure
  categories.
- `CostRecorder` takes `snapshots` and prices pinned calls with
  `await self.snapshots.get(pinned_snapshot_id)`. Integration tests edit and
  delete the rate-card file after pinning and still record the pinned cost.
- The unit of work exposes `pricing_snapshots` next to `cost_ledger`, built in
  `_open_instrumented_stores` with the runtime metrics, tracer, and monotonic
  clock. The ledger store no longer takes unused instrumentation parameters.
- `PricingSnapshotError` maps to `cost.pricing_snapshot`, and
  `PricingSnapshotCollisionError` is mapped explicitly because it still
  subclasses `CostAccountingError` rather than `PricingSnapshotError`.
- Deviations recorded: the snapshot store tests moved out of
  `tests/test_cost_storage_ledger.py` into
  `tests/test_cost_storage_pricing_snapshots.py`; the shared
  `launch_and_load_run` helper moved to
  `tests/generation_run_launcher_support.py` to keep
  `tests/test_generation_run_launcher.py` inside the 400-line limit; the
  pricing launcher test lives in
  `tests/test_generation_run_launcher_pricing.py`; the currency validator
  became public as `episodic.cost.primitives.validate_currency_code` so
  `ports.py` stops importing a private name across modules.
- Conformance check: the persisted schema is unchanged, the only public
  interface change is the split snapshot port, and pinned costs are now
  reproducible from the database. Gates at `9eb67a65`: `check-fmt`, `typecheck`,
  `lint`, `test` (2127 passed, 1 skipped), `check-migrations`, `markdownlint`,
  `nixie` all green. The milestone CodeRabbit CLI review found the delegated
  id-reuse comparison (EP-M3), the launcher collision category, and
  documentation corrections; all in-scope findings were actioned before the
  final gate run. The final candidate `b7a873f2` re-gated green and the fresh
  CLI review covered 35/35 files with 0 findings, but reported
  `completed_with_warnings`; the milestone is therefore recorded as reviewed
  with a verification caveat, not as a guaranteed clean diff.

### EP-M3 (2026-11-10)

- Schema version 1 replaced the `2.4.4` snapshot representation: a
  domain-derived SHA-256 `content_hash`, exact `MeteredRate` fractions, a
  service kind, optional verbatim source documents, and no `billing_period_key`.
  `PricingSnapshotRepository.ensure` inserts by content hash and `get`
  verifies the stored row against its hash.
- Migration `20261110_000017` converts existing rows stop-the-world; its
  offline form refuses a non-empty table and its downgrade refuses unless the
  table is empty.
- Conformance check: the persisted format changed as designed, the public
  snapshot interface changed, and historical costs are reproducible from the
  database. Gates at `058925bf`: all seven green (`make test` 2207 passed, 1
  skipped, 71 snapshots). The milestone review covered 65/65 files with zero
  findings.

### EP-M4 (2026-11-10)

- Six behavioural scenarios in `tests/features/pricing_snapshots.feature`
  cover pinning, revision, deletion, re-pricing from the stored snapshot, TTS,
  and SLA4OAI documents. The Vidai Mock scenario drives the real
  OpenAI-compatible adapter and records provider-reported usage through the
  real recorder on py-pglite.
- The shipped `openai-2026-05.yaml` card now charges the exact 7.5 minor units
  per million cached tokens, and `tests/test_shipped_pricing_cards.py` proves
  the corrected rate, the 22-minor-unit behavioural price, and the new content
  hash.
- Conformance check: no further schema change; the correction is a new
  content-addressed version. Gates at `9821d178`: all seven green (`make test`
  2215 passed, 1 skipped, 71 snapshots). The final milestone review covered
  72/72 files with zero findings.

### EP-M5 (2026-11-11)

- Documentation, index, and roadmap updates landed as described in `Progress`.
  The pricing ADR is ADR-028, not ADR-024, because the review-checkpoint ADR
  already held 024.
- Conformance check: documentation only, plus one user-facing error string
  (`_CONVERSION_GUIDANCE`) and one test docstring that name the ADR. No
  behaviour, interface, or persisted-format change. Gates: `check-fmt`,
  `markdownlint`, `spelling`, and `nixie` green; the full gate set is run on
  the final candidate before publication.

### Post-milestone review rounds (2026-11-11)

- Round 1 at `e74ce428`: all seven gates green (`make test` 2223 passed, 1
  skipped, 71 snapshots). The CLI review raised three findings, all actioned in
  `b6398651`.
- Round 2 at `b6398651`: all seven gates green (`make test` 2225 passed, 1
  skipped, 71 snapshots; lint 67s with 30 reasoned duplication exceptions;
  `check-migrations` 5s; `markdownlint` 0 issues in 135 files; `nixie` all
  diagrams validated). The CLI review raised seven findings: unhashable YAML
  mapping keys escaping as a raw `TypeError`, migrated rates above the
  canonical JSON integer limit, a currency check that accepted non-ASCII
  letters, a stale pricing-snapshot doctest, duplicated test fakes, and two
  documentation inaccuracies. All seven were actioned in `17449258`, which also
  replaced the three-condition currency check with one anchored regular
  expression to satisfy the boolean-expression lint rule.
- Round 3 at `e9b7db88`: all seven gates green (`make test` 2228 passed, 1
  skipped, 71 snapshots; `check-migrations` applied all 17 revisions cleanly;
  `markdownlint` 0 issues in 135 files; `nixie` all diagrams validated). The
  CLI review covered 79 files and raised one finding: the migration held its
  own copy of the defect fixed in round 2, so a legacy row with a code such as
  `ÉÜÖ` migrated cleanly and then failed `get` with
  `PricingSnapshotIntegrityError`. Fixed in `95b524d5` with the same anchored
  pattern, kept local to the migration so a later domain change cannot alter
  how historical rows convert, plus a migration test case.
- Round 4 on the candidate carrying round 3: all seven gates green (`make test`
  2229 passed, 1 skipped, 71 snapshots). The CLI review covered 78 files and
  raised one finding: a quoted amount such as `"1e999999999"` is a valid
  `Decimal`, and `as_integer_ratio` would build a billion-digit integer before
  the rate range check rejected it, hanging startup. Fixed in `52e14676` by
  rejecting an exponent beyond 30 decimal places, with positive and negative
  exponent cases in the loader tests.
- Lesson: the currency validator's shape check and its uppercase check were
  two separate conditions, so a non-ASCII letter such as `É` passed the
  alphabetic test. One anchored pattern expresses the whole contract and cannot
  drift between the two halves. The same defect existed in two places, in the
  domain and in the migration, so fixing one copy is not evidence that the
  other is correct.
- Lesson: validation order is part of a parser's contract. The finite and
  non-negative checks ran before `as_integer_ratio`, but the cost of conversion
  is driven by the exponent, so an amplification attack passed every earlier
  check. Cheap bounds belong ahead of any conversion whose cost the input
  controls.

Record outcomes at each milestone boundary and at completion, including the
conformance check results and any upstream document changes.

## Context and orientation

Episodic is a Python 3.14 podcast-generation service organized as a hexagonal
architecture: domain types and ports (protocols) in the middle, application
services that orchestrate them, and adapters (Falcon HTTP, Celery workers,
SQLAlchemy storage, OpenAI-compatible LLM clients, YAML file loaders) at the
edge. Hecate checks the import boundaries during `make lint`.

Cost accounting lives in `episodic/cost/`:

- `episodic/cost/ports.py` (290 lines) defines the ledger enums
  (`LedgerScope`, `PricingModel`, `UsageSource`), the ledger errors
  (`UnknownPricedMetricError`, `OperationMismatchError`), the ledger value
  objects (`PricedCall`, `ProviderCallLedgerEntry`, `TaskRollupLedgerEntry`,
  `RunPricingKey`), and the ports `CostLedgerPort`, `PricingCataloguePort`, and
  `MeteringPort`. Shared identifiers, `CostAccountingError`,
  `PricingSourceKind`, and the currency validator live in
  `episodic/cost/primitives.py`; `PricingSnapshot` and its rates live in
  `episodic/cost/pricing_snapshot.py`.
- `episodic/cost/pricing_snapshot_ports.py` defines
  `PricingSnapshotRepository`, `EnsuredPricingSnapshot`,
  `SnapshotEnsureOutcome`, and the `PricingSnapshotError` hierarchy.
- `episodic/cost/engine.py` defines `PricingRequest` and `PricingEngine`, a
  pure function that prices usage metrics against a snapshot.
- `episodic/cost/recorder.py` defines `CostRecorder` (application layer),
  which resolves and pins snapshots, prices calls, and writes ledger rows.
- `episodic/cost/pricing_catalogue/file_loader.py` defines
  `FilePricingCatalogue`, which loads YAML rate cards from
  `PRICING_SNAPSHOT_DIRECTORY` (default `config/pricing-snapshots`).
- `episodic/cost/storage/models.py` defines the SQLAlchemy records
  (`PricingSnapshotRecord`, `CostLedgerEntryRecord`, `RunPricingPinRecord`,
  metering records); `episodic/cost/storage/adapters.py` (243 lines) defines
  `SqlAlchemyCostLedgerStore`, and
  `episodic/cost/storage/pricing_snapshot_store.py` defines
  `SqlAlchemyPricingSnapshotStore` with `ensure` and `get`.
- The unit of work (`episodic/canonical/storage/uow.py`, protocol in
  `episodic/canonical/unit_of_work_protocols.py`) exposes `uow.cost_ledger` and
  `uow.pricing_snapshots`. `episodic/api/runtime.py` wires
  `FilePricingCatalogue` and `CostRecorder`.
- Callers: `episodic/orchestration/_planning_orchestrator.py`,
  `episodic/orchestration/langgraph_costs.py`,
  `episodic/generation/launcher_persistence.py`, and
  `episodic/generation/launcher_support_events.py` (which also holds the
  `_FAILURE_CATEGORIES` table used by `classify_failure`).

Terms used in this plan:

- Pricing snapshot: an immutable document of pricing inputs for one provider
  offering (service kind, provider, model, operation), with rates, currency,
  provenance, and an optional verbatim source document.
- Pricing subject: the tuple `(service_kind, provider_name, model, operation)`
  that names what a snapshot prices.
- Content hash: `sha256:` followed by the lowercase hexadecimal SHA-256 digest
  of the snapshot's canonical form; the snapshot's version identity.
- Canonical form: the exact UTF-8 JSON bytes defined in
  `Interfaces and dependencies` below.
- Run pricing pin: a row in `run_pricing_pins` recording which snapshot a run
  uses for a provider operation in a billing period, so resumed work prices
  identically.
- Minor units: the smallest currency unit (cents for USD).
- SLA4OAI: the Service-Level Agreement for OpenAPI specification
  (research version 0.10.0). An OpenAPI document links an SLA document through
  `info.x-sla`; the SLA document has `context`, `infrastructure`, `pricing`
  (`cost`, `currency`, `billing`), `metrics`, `plans`, `quotas`, `rates`,
  `guarantees`, and `configuration`.
- Vidai Mock: an offline, wire-accurate mock of OpenAI-compatible inference
  APIs, started by tests through `tests/steps/vidaimock_harness.py`.

### Signposted documentation

Read these before implementing; each entry says why.

- `docs/roadmap.md` §2.5: the item and its neighbours (`2.5.2`–`2.5.5`), to
  keep scope boundaries.
- `docs/episodic-podcast-generation-system-design.md` §"Cost accounting and
  budget enforcement" (from line 1476) and §"Data Model and Storage" (from line
  1626): the design this plan amends.
- `docs/adr/adr-015-cost-accounting-ports-and-pricing-engine.md` (including
  the 2026-10-10 addendum): current port and persistence decisions.
- `docs/adr/adr-018-explicit-versioning-and-history-strategy.md`: the
  versioning rules this plan must follow.
- `docs/adr/adr-014-hexagonal-architecture-enforcement.md` and
  `docs/adr/adr-022-orchestration-architecture-enforcement.md`: Hecate groups;
  ADR-022 is also the layout model for ADR-028.
- `docs/execplans/2-4-4-cost-accounting-and-usage-metering.md`: how the
  current cost code was built and tested.
- `docs/cost-management-in-langgraph-agentic-systems.md`: cost-accounting
  background for LangGraph nodes (budget material is `2.5.5`).
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` and
  `docs/agentic-systems-with-langgraph-and-celery.md`: port layering for
  orchestration callers of `CostRecorder`.
- `docs/async-sqlalchemy-with-pg-and-falcon.md`: async session and
  transaction conventions for the new store.
- `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`: py-pglite fixtures
  (`migrated_engine`, `session_factory`) for store, migration, and BDD tests.
- `docs/testing-async-falcon-endpoints.md`: only if runtime wiring tests need
  an application instance.
- `docs/complexity-antipatterns-and-refactoring-strategies.md`: guidance for
  the extractions forced by the 400-line limit.
- `docs/femtologging-users-guide.md`: logging conventions for the startup
  catalogue validation message and deprecation of legacy files.
- `docs/tei-rapporteur-users-guide.md`: not needed by this item except to
  understand the generation slice that records costs.
- `docs/documentation-style-guide.md`: ADR template and Markdown rules.
- `docs/developers-guide.md` (cost sections near lines 2099–2122 and
  2414–2422) and `docs/users-guide.md` §"Cost Management" (near line 636):
  documents to update.
- `docs/scripting-standards.md`: only if a helper script is added (none is
  planned).

### Signposted skills

- `execplans`: maintaining this plan.
- `hexagonal-architecture`: port and adapter placement; driven port design.
- `python-router`, then `python-data-shapes` (frozen dataclasses, deep
  freezing), `python-types-and-apis` (protocols, `NewType`), and
  `python-errors-and-logging` (error hierarchy, `raise … from …`).
- `python-testing` (fixtures, syrupy, async tests) and `hypothesis`
  (properties listed in `Verification plan`).
- `vidai-mock`: configuring provider templates with usage details.
- `skylos`: entry-point rules if a verified false positive appears.
- `codegraph-mcp`: callers and impact of `ensure_snapshot`, `get_snapshot`,
  `PricingSnapshot`, and `rates_minor_per_metric` before each edit.
- `en-gb-oxendict`: documentation spelling.
- `logisphere-design-review`: if a material design change is proposed during
  implementation, re-run a focused panel before accepting it.

## Conformance basis

No Terms of Reference document exists for this project; the roadmap and the
system design document are the upstream artefacts.

Upstream identifiers used for tracing:

- `RM-2.5.1-A`: persist model pricing inputs used for LLM and TTS billing
  (`docs/roadmap.md` §2.5, item `2.5.1`, first bullet).
- `RM-2.5.1-B`: preserve room for future helper-service pricing documents
  (second bullet).
- `RM-2.5.1-C`: version snapshots so historical run costs remain reproducible
  (third bullet).
- `TDD-COST-SNAPSHOTS`: design document §"Cost accounting and budget
  enforcement", bullet "Immutable `pricing_snapshots` capture …", and §"Data
  Model and Storage", bullet "`pricing_snapshots` stores immutable provider
  rate cards …".
- `TDD-COST-SLA`: design document §"Future service-oriented pricing
  contracts".
- `ADR-015`: cost-accounting ports and pricing engine (plus addendum).
- `ADR-018-INV-IMM`: "Immutable content is content-addressed or append-only,
  not permission-protected."
- `ADR-018-INV-PIN`: "Consumers pin versions rather than resolving latest."
- `ADR-014`, `ADR-022`: Hecate boundary enforcement.
- `ADR-028` (new, this plan): content-addressed pricing snapshots.

Trace links:

```plaintext
RM-2.5.1-C -> ADR-018-INV-PIN -> EP-M2
  -> tests/test_cost_recorder_integration.py::test_pinned_call_prices_from_persisted_snapshot_after_file_removal
RM-2.5.1-C -> ADR-018-INV-IMM -> ADR-028 -> EP-M3
  -> tests/test_cost_pricing_snapshot_hash_properties.py
  -> tests/test_cost_pricing_snapshot_store.py::test_tampered_row_fails_integrity_check
RM-2.5.1-C -> EP-M4 -> tests/features/pricing_snapshots.feature (reprice scenarios, Vidai Mock scenario)
RM-2.5.1-A -> TDD-COST-SNAPSHOTS -> ADR-028 -> EP-M3 -> tests/test_cost_metered_rate_properties.py
  -> EP-M4 -> pricing_snapshots.feature (TTS scenario)
RM-2.5.1-B -> TDD-COST-SLA -> ADR-028 -> EP-M3 -> tests/test_cost_pricing_snapshot_model.py (source documents)
  -> EP-M4 -> pricing_snapshots.feature (SLA4OAI scenario)
ADR-014/ADR-022 -> every milestone -> make lint (Hecate check)
```

Baseline-to-target gaps: G1 (pricing reads files, EP-M2), G2 (implicit
versioning, EP-M3), G3 (rate precision, EP-M3), G4 (TTS unrepresentable,
EP-M3/EP-M4), G5 (no helper-document home, EP-M3/EP-M4), G6 (hash not
recomputable from rows, EP-M3).

## Verification plan

The implementation is structured so each invariant lives in a small pure
function or a single adapter method: canonicalization and hashing in
`episodic/cost/pricing_snapshot_hash.py`, rate normalization in `MeteredRate`,
persistence in `SqlAlchemyPricingSnapshotStore`, selection in
`FilePricingCatalogue.resolve`. Each obligation below names its method and
non-vacuity evidence.

### Axioms (trusted, not verified)

- `json.dumps(…, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`
  is deterministic for dictionaries of strings, integers, `None`, and nested
  dictionaries; `hashlib.sha256` is a correct SHA-256.
- PostgreSQL `INSERT … ON CONFLICT … DO NOTHING RETURNING` under READ
  COMMITTED either inserts, or returns no row after the conflicting transaction
  commits; a following `SELECT` (new statement) sees the committed row.
  py-pglite reproduces this behaviour.
- PostgreSQL `timestamptz` stores instants in UTC with microsecond precision;
  JSONB stores integers exactly.
- Vidai Mock returns the `usage` object written in its template verbatim.
- RFC 8785 equivalence holds only because every key in the canonical form is
  ASCII and every number is an integer no larger than `2**53 - 1`; both are
  enforced by validation, not assumed.

### Obligations

- Obligation `INV-HASH-DET`: equal snapshot content yields an equal content
  hash, independent of mapping insertion order, rate authoring scale
  (`75/10_000_000` versus `15/2_000_000`), and instant offset (`+01:00` versus
  the equivalent UTC instant). Method: Hypothesis property. Domain: generated
  snapshots (all three service kinds, both source kinds, with and without
  source documents and `effective_from`), permuted mappings, rates scaled by
  random factors, instants shifted into random fixed offsets. Artefact:
  `tests/test_cost_pricing_snapshot_hash_properties.py`. Evidence:
  `uv run pytest tests/test_cost_pricing_snapshot_hash_properties.py -q`
  passes. Non-vacuity: `hypothesis.event` classifies service kind, source kind,
  scaling factor greater than one, and non-UTC offsets; the test fails if any
  class has zero examples. Negative control: a seeded fault that encodes
  instants with `isoformat()` must make this property fail.
- Obligation `INV-HASH-SENS`: changing any single hashed field changes the
  hash. Method: Hypothesis property over a mutation strategy keyed by
  `PRICING_SNAPSHOT_V1_FIELDS`. Artefact: same file. Evidence: passes.
  Non-vacuity: a companion example test asserts that the mutation table has an
  entry for every name in `PRICING_SNAPSHOT_V1_FIELDS` and that the canonical
  document's keys equal that tuple, and that the dataclass's hashed fields
  equal it, so adding a field without bumping the schema fails. Negative
  control: omitting `source_metadata` from the canonical form must fail.
- Obligation `INV-HASH-VECTORS`: the canonical form is byte-stable. Method:
  syrupy snapshots of canonical bytes and hashes for one LLM, one TTS, and one
  SLA4OAI snapshot; the same vectors appear in ADR-028. Artefact:
  `tests/test_cost_pricing_snapshot_hash.py` and
  `tests/__snapshots__/test_cost_pricing_snapshot_hash.ambr`. Non-vacuity: the
  vectors include a non-UTC `retrieved_at`, a null `effective_from`, a
  non-reduced authored rate, and a source document.
- Obligation `INV-RATE-NORM`: `MeteredRate` is always in lowest terms and
  normalization preserves value (`Fraction(a, p)` is unchanged). Method:
  Hypothesis property plus parameterized boundaries (`0`, `1`, `2**53 - 1`,
  `2**53` rejected, `per_units == 0` rejected, negative rejected). Artefact:
  `tests/test_cost_metered_rate_properties.py`. Non-vacuity: event
  classification shows reducible and already-reduced inputs.
- Obligation `INV-LEGACY-EQ`: for every legacy integer rate `r` per
  1,000,000 and every non-negative usage `u`, the new engine's per-metric cost
  equals `u * r // 1_000_000`. Method: Hypothesis property with the old formula
  as oracle. Artefact: `tests/test_cost_pricing_engine_properties.py`
  (extended). Non-vacuity: generated `r` values include ones that reduce (for
  example `8 -> 1/125000`), and a positive check asserts that pricing with the
  unreduced and the reduced form of the same rate agrees. Negative control: a
  seeded engine that uses true division and rounds at the end must be rejected
  by the oracle.
- Obligation `INV-ROUNDTRIP`:
  `store.get(store.ensure(s).pricing_snapshot_id) == s` and passes the
  integrity check, for snapshots with non-UTC instants, microsecond precision,
  all service kinds, and source documents. Method: Hypothesis property against
  py-pglite (`max_examples=6`, per-example unique content as in
  `tests/test_cost_snapshot_persistence_properties.py`). Artefact:
  `tests/test_cost_snapshot_persistence_properties.py` (rewritten).
  Non-vacuity: classification events; a seeded fault that stores `retrieved_at`
  truncated to seconds must fail.
- Obligation `INV-CONTENT-ADDR`: `ensure` of identical content returns the
  same identifier with outcome `reused`; `ensure` of different content returns
  a different identifier; no stored row ever changes. Method: Hypothesis
  sequence property extending the existing ensure-sequence test (operation
  sequences over two contents and repeated calls), plus the concurrency test
  (two sessions ensure identical content concurrently and receive the same
  identifier). Artefacts: `tests/test_cost_snapshot_persistence_properties.py`,
  `tests/test_cost_snapshot_concurrency.py`. Non-vacuity: sequences must
  include at least one repeat and one distinct content (checked by events).
- Obligation `INV-TAMPER`: altering any persisted hashed column directly in
  SQL makes `get` raise `PricingSnapshotIntegrityError`. Method: parameterized
  test over every hashed column. Artefact:
  `tests/test_cost_pricing_snapshot_store.py`. Non-vacuity: the parameter list
  is derived from the column-to-field map and asserted to cover every field in
  `PRICING_SNAPSHOT_V1_FIELDS`; altering the non-hashed `recorded_at` must not
  raise (negative control).
- Obligation `INV-REPRO`: a call priced from a pinned snapshot reprices to
  the same `computed_cost_minor` from `store.get(id)` after the catalogue file
  is revised or deleted, while new runs use the new version. Method:
  integration test with real `FilePricingCatalogue`, `CostRecorder`, and
  py-pglite; Hypothesis over usage values for the repricing equality; BDD
  scenarios; Vidai Mock scenario. Artefacts:
  `tests/test_cost_recorder_integration.py`,
  `tests/features/pricing_snapshots.feature`. Non-vacuity: the revised card
  must price the same usage differently (23 versus 22 minor units), proving the
  test would detect pricing from the file.
- Obligation `INV-CATALOGUE`: `resolve(subject)` returns the card with the
  greatest `effective_from <= now`; a future-dated card is ignored; two loaded
  files with the same subject and `effective_from` are rejected at load; a
  legacy-format file is rejected at load with its path in the message; a run in
  a month without its own card still resolves (regression). Method:
  parameterized pytest. Artefact:
  `tests/test_cost_pricing_catalogue_file_loader.py`.
- Obligation `INV-MIGRATION`: upgrading from `20261031_000016` (the immediate
  parent, which carries the same `pricing_snapshots` shape as
  `20261010_000013`) converts each legacy row so that the domain store reads it
  without an integrity error, and its hash equals the hash of the corresponding
  rewritten shipped card (except the corrected cached-input row described in
  `Success` item 4); a recomputed-hash collision aborts with `CommandError`
  naming both identifiers and leaves the schema at `20261031_000016`; offline
  upgrade SQL contains the non-empty-table guard; downgrade refuses on a
  non-empty table and succeeds on an empty one. Method: py-pglite migration
  tests plus syrupy snapshots of offline SQL. Artefact:
  `tests/test_pricing_snapshot_content_address_migration.py` and its `.ambr`.
  Non-vacuity: legacy fixtures are byte copies of the three shipped `2.4.4`
  YAML files inserted through `sa.table` at the old schema.
- Obligation `INV-ARCH`: new modules sit in the intended Hecate groups and no
  domain module imports SQLAlchemy, YAML, or the application group. Method:
  `make lint` (Hecate) plus a new structural test,
  `tests/test_production_hecate_cost_config.py`, modelled on
  `tests/test_production_hecate_orchestration_config.py` (which maps production
  orchestration modules to groups), asserting each new cost module's group so
  an ungrouped module fails. (`tests/test_architecture_hecate_config.py` tests
  fixture-config generation and is not the right home.) Negative control:
  Hecate must reject a temporary import of `sqlalchemy` in
  `episodic/cost/pricing_snapshot.py` (run once locally, not committed).

Residual gaps: TTS pricing is verified only with synthetic usage because no TTS
adapter exists; SLA4OAI documents are stored and hashed but not interpreted;
rounding bias of floor-per-metric is documented, not fixed.

## Plan of work

The work proceeds in five milestones. Each ends with all gates green and a
commit. Red tests are committed with
`@pytest.mark.xfail(strict=True, reason="…")` and the marker is removed in the
green step; no marker survives the milestone.

### EP-M1: shared leaf modules and ADR-028 draft

Purely structural, no behaviour change.

1. Move `canonical_json_bytes` from `episodic/canonical/idempotency_service.py`
   to a new module `episodic/json_canonicalization.py`; update every importer
   (`episodic/canonical/idempotency_service.py`,
   `episodic/api/source_idempotency.py`, `tests/test_idempotency_service.py`,
   and any other hit from `rg canonical_json_bytes`) to import it from there.
   Add `episodic.json_canonicalization` to the `domain_ports` group in
   `[tool.hecate]`.
2. Create `episodic/cost/primitives.py` holding `CostAccountingError`, the
   `NewType` identifiers (`PricingSnapshotId`, `CostLedgerEntryId`,
   `IdempotencyKey`, `CurrencyCode`, `BillingPeriodKey`, `MeteringCounterKey`),
   `PricingSourceKind`, and the currency validation helper.
   `episodic/cost/ports.py` imports them. Domain modules import
   `episodic.cost.primitives` directly and never the package facade
   `episodic/cost/__init__.py`, which belongs to no Hecate group (so its edges
   go unchecked) and imports the recorder; application and adapter callers may
   keep using the facade. Update the Skylos entry for
   `episodic.cost.ports._validate_currency_code` (`pyproject.toml`, near line
   641) to its new path; `_validate_usage_metrics` stays in `ports.py`. Add
   `episodic.cost.primitives` to `domain_ports`.
3. Write `docs/adr/adr-028-content-addressed-pricing-snapshots.md` with status
   `Proposed`, following the ADR template in
   `docs/documentation-style-guide.md` (Status, Date, Context and problem
   statement, Decision drivers, Requirements, Options considered, Decision
   outcome or proposed direction, Goals and non-goals, Consequences,
   References; ADR-022 shows the heading style used in `docs/adr/`), recording
   the decisions in this plan's `Decision log` and the v1 canonical form with
   placeholder vectors (filled in EP-M3).

Acceptance: all gates pass; `git diff --stat` shows moves only;
`uv run hecate check` passes.

### EP-M2: persisted read path and `PricingSnapshotRepository`

Closes G1 on the current schema.

1. Red: in `tests/test_cost_recorder_integration.py`, add
   `test_pinned_call_prices_from_persisted_snapshot_after_file_removal`: write
   a rate card into a temporary catalogue directory, pin a run through a real
   `CostRecorder` on py-pglite, delete the file, build a fresh
   `FilePricingCatalogue` over the now-empty directory, record a provider call
   for the pinned run, and assert the ledger cost. It fails today with
   `LookupError`. Add a companion test that edits the file in place (same
   identifier, different rates) and asserts the pinned call uses the persisted
   rates.
2. Green: create `episodic/cost/pricing_snapshot_ports.py` (domain_ports) with
   `PricingSnapshotRepository` (`ensure`, `get`), `EnsuredPricingSnapshot`,
   `SnapshotEnsureOutcome`, and the errors `PricingSnapshotError`,
   `PricingSnapshotNotFoundError` (also a `LookupError`), and
   `PricingSnapshotIntegrityError`. Move snapshot persistence and its
   instrumentation (`_snapshot_insert_statement`, `_record_ensure_outcome`,
   `_record_snapshot_insert`, `_persist_snapshot`,
   `_is_pricing_snapshot_hash_collision`) out of
   `episodic/cost/storage/adapters.py` into a new
   `episodic/cost/storage/pricing_snapshot_store.py` as
   `SqlAlchemyPricingSnapshotStore`, adding `get`, which maps a record back to
   `PricingSnapshot` (keeping the current shape in this milestone). Remove
   `ensure_snapshot` from `CostLedgerPort` and the ledger store. Add
   `pricing_snapshots: PricingSnapshotRepository` to `CanonicalUnitOfWork` and
   `SqlAlchemyUnitOfWork`. Give `CostRecorder` a `snapshots` field, call
   `snapshots.ensure` where it called `ledger.ensure_snapshot`, and price
   pinned calls from `snapshots.get(pinned_id)`. Remove
   `PricingCataloguePort.get_snapshot` and `FilePricingCatalogue.get_snapshot`.
   Update `episodic/api/runtime.py`, `episodic/cost/__init__.py`,
   `episodic/cost/storage/__init__.py`, the recorder docstring examples, and
   every fake and test that used the removed methods.
3. Add `(PricingSnapshotError, "cost.pricing_snapshot", False)` to
   `_FAILURE_CATEGORIES` in `episodic/generation/launcher_support_events.py`
   with a test alongside the existing end-to-end category assertions in
   `tests/test_generation_run_launcher.py` (near lines 211–243); no direct unit
   test of `classify_failure` exists today.
4. Keep metric names and label values stable (`pricing_snapshot.ensure`,
   `operation=ensure_snapshot`); add `pricing_snapshot.get` counter and latency
   with outcomes `found`, `not_found`, and `integrity_mismatch` (the latter
   becomes reachable in EP-M3). Extend
   `tests/test_cost_snapshot_observability.py`.

Acceptance: the two red tests pass; all gates pass.

### EP-M3: schema version 1 snapshots, content addressing, and migration

Closes G2, G3, G4 (representation), G5 (storage), and G6. This milestone is one
atomic representation change across domain, engine, catalogue, store,
migration, configuration, and tests; commit red tests first with strict
expected-failure markers, then the implementation.

1. Red tests (strict `xfail`): `tests/test_cost_metered_rate_properties.py`,
   `tests/test_cost_pricing_snapshot_model.py` (validation partitions listed in
   `Interfaces and dependencies`), `tests/test_cost_pricing_snapshot_hash.py`
   (vectors), `tests/test_cost_pricing_snapshot_hash_properties.py`,
   `tests/test_cost_pricing_snapshot_store.py` (content addressing, round-trip,
   tampering), catalogue tests for v1 files and the month-gap regression, and
   `tests/test_pricing_snapshot_content_address_migration.py`.
2. Domain: create `episodic/cost/pricing_snapshot.py` (`PricedService`,
   `UsageUnit`, `MeteredRate`, `SourceDocument`, `PricingSubject`,
   `PricingSnapshot`) and `episodic/cost/pricing_snapshot_hash.py`
   (`PRICING_SNAPSHOT_V1_FIELDS`, `canonical_pricing_document`,
   `pricing_snapshot_content_hash`). Remove `PricingSnapshot` and
   `PricingSnapshotCollisionError` from `episodic/cost/ports.py` and from the
   `episodic/cost/__init__.py` facade. Delete the now-unreachable collision
   path in the store (`_is_pricing_snapshot_hash_collision`, the `collision`
   outcome, and the `pricing_snapshot.collision` failure category) so Skylos
   finds no dead code. Add both new modules to `domain_ports`.
3. Engine: `PricingEngine.price` reads `snapshot.rates[metric]` and computes
   `usage * rate.amount_minor // rate.per_units`; `PricingRequest` loses
   `billing_period_key`; `BillingPeriodMismatchError` (defined in
   `episodic/cost/ports.py`) is removed with its exports; the module docstring
   example in `episodic/cost/engine.py` is updated.
4. Catalogue: `PricingCataloguePort.resolve(subject: PricingSubject)`.
   Extract YAML document parsing into
   `episodic/cost/pricing_catalogue/_document.py` (v1 parser, decimal-string
   `amount_minor` conversion, legacy-format rejection). Add
   `FilePricingCatalogue.from_directory(path, *, now=…)` that loads and
   validates every file eagerly (duplicate subject plus `effective_from`
   rejected) and raise `PricingCatalogueError(ValueError)` naming the file.
   `episodic/api/runtime.py` uses the factory so a bad catalogue fails at
   startup.
5. Recorder and callers: `CostProviderOperation` gains `service_kind`, set to
   `PricedService.LLM` where it is built
   (`episodic/orchestration/_planning_orchestrator.py`
   `_cost_provider_operations`, near lines 287–315, and
   `episodic/generation/launcher_persistence.py`). For unpinned calls,
   `CostRecorder` derives the subject's service kind from
   `ProviderCallRecord.provider_type` with
   `PricedService(record.provider_type)` and rejects an unknown value with
   `ValueError` (records are built in
   `episodic/generation/launcher_support_events.py` near line 94,
   `_planning_orchestrator.py` near line 325, and
   `tests/test_cost_recorder.py`; cover the rejection with a unit test).
   Because the v1 `PricingSnapshot` has no identifier, the recorder's snapshot
   resolver returns the pair `(PricingSnapshot, PricingSnapshotId)`: the pinned
   identifier with `snapshots.get(pinned_id)`, or the identifier returned by
   `snapshots.ensure(resolved)`. `_build_provider_call_entry` takes that
   identifier explicitly instead of reading `snapshot.pricing_snapshot_id`.
   `pin_run_pricing` pins the identifier returned by `snapshots.ensure`.
6. Store: `ensure` inserts with a new UUIDv7 `id` using
   `ON CONFLICT ON CONSTRAINT uq_pricing_snapshots_content_hash DO NOTHING
   RETURNING id`,
   falling back to `SELECT id … WHERE content_hash = :hash`; `get` rebuilds
   the snapshot, compares hashes, and raises `PricingSnapshotIntegrityError` on
   mismatch (metric outcome `integrity_mismatch`, failure category
   `pricing_snapshot.tampered`; the snapshot identifier goes only into the span
   attributes). Keep the existing `pricing_snapshot.integrity` category for
   database `IntegrityError`s; the two must not be merged.
7. ORM model and migration: update `PricingSnapshotRecord` to the v1 columns
   (see `Interfaces and dependencies`). Add
   `alembic/versions/20261110_000017_content_address_pricing_snapshots.py`
   (`down_revision = "20261031_000016"`). Online upgrade: lock the table; add
   the new columns as nullable; read every legacy row; convert it with a frozen
   inline converter and canonicalizer (no imports from `episodic`). The
   converter's legacy defaults are `service_kind = 'llm'`,
   `schema_version = 1`, no source document, `effective_from` and
   `retrieved_at` unchanged, and each legacy rate `r` becomes `r/1_000_000` in
   lowest terms with `unit = 'token'` for the seven legacy metric names
   (`input_tokens`, `output_tokens`, `cached_input_tokens`,
   `cache_write_tokens`, `reasoning_tokens`, `audio_input_tokens`,
   `audio_output_tokens`; `cache_write_tokens` appears in
   `anthropic-2026-05.yaml`). Abort with `CommandError` naming identifiers on
   any recomputed-hash collision, unknown legacy metric, or non-identifier
   `source_metadata` key; write the converted values and hashes; set
   `NOT NULL`; add check constraints; drop `billing_period_key` and
   `rates_minor_per_metric`. Offline upgrade emits the DDL preceded by a
   `DO $$ … $$` block that raises when `pricing_snapshots` has rows. Downgrade
   (online and offline) refuses unless the table is empty, then reverses the
   DDL.
8. Configuration: rewrite the three shipped cards in
   `config/pricing-snapshots/` to schema version 1 with identical values (so
   alpha rows convert to the same hash), removing `pricing_snapshot_id` and
   `billing_period_key`.
9. Tests that change in this milestone: `tests/fixtures/cost.py`,
   `tests/test_cost_ports_protocols.py`, `tests/test_cost_recorder.py`,
   `tests/test_cost_recorder_integration.py`,
   `tests/test_cost_pricing_engine_properties.py`,
   `tests/test_cost_pricing_catalogue_file_loader.py`,
   `tests/test_cost_storage_ledger.py`,
   `tests/test_cost_storage_constraint_errors.py`,
   `tests/test_cost_snapshot_persistence_properties.py`,
   `tests/test_cost_snapshot_observability.py`,
   `tests/test_cost_snapshot_concurrency.py`,
   `tests/test_pricing_snapshot_constraint_migration.py` (keep its
   `20261010_000013` constraint pin; the new content-address migration test
   seeds legacy rows after upgrading to `20261031_000016` with `sa.table`),
   `tests/test_env_runtime_wiring.py`, `tests/test_runtime_configuration.py`,
   and the new `tests/test_production_hecate_cost_config.py`.
10. Fill the hash vectors in ADR-028 from the syrupy snapshots.

Acceptance: strict `xfail` markers removed; all gates pass;
`make check-migrations` reports no drift.

### EP-M4: behavioural coverage, Vidai Mock scenario, and the 7.5-cent correction

1. Add `tests/features/pricing_snapshots.feature` and
   `tests/steps/test_pricing_snapshots_steps.py` (scenarios in
   `Validation and acceptance`). The Vidai Mock scenario writes a provider
   config and a response template reporting `prompt_tokens: 2000000`,
   `prompt_tokens_details.cached_tokens: 1000000`, and
   `completion_tokens: 500000`, starts the server with
   `start_vidaimock_process`, calls it through `OpenAICompatibleLLMAdapter`
   (`episodic/llm/openai_api/adapter.py`; it defaults to Chat Completions and
   routes to `/chat/completions`), and records the call through the real
   `CostRecorder` on py-pglite. The template must return
   `"model": "gpt-4o-mini"`, because the recorder records the response's model
   and the pin key includes it. Every scenario copies a pre-correction
   `gpt-4o-mini` card (8 minor units per million cached tokens) into a
   temporary catalogue directory rather than reading `config/`, and builds a
   fresh `FilePricingCatalogue` after revising or deleting a file, because the
   catalogue loads eagerly and caches. Reuse
   `tests/steps/vidaimock_harness.py`; do not copy the orchestration template
   writers (the nose duplication gate will flag a copy).
2. Correct the shipped `gpt-4o-mini` card: change `cached_input_tokens` to
   `amount_minor: "7.5"` in `config/pricing-snapshots/openai-2026-05.yaml` (an
   in-place edit that becomes a new version), with a commit message that
   explains that historical runs keep the earlier version. Add a test that the
   shipped catalogue loads, that the corrected card's hash differs from the
   original's, and that the corrected shipped card prices the BDD usage at 22
   minor units.

Acceptance: `uv run pytest tests/steps/test_pricing_snapshots_steps.py -v`
passes all scenarios; all gates pass.

### EP-M5: documentation, roadmap, and final gates

1. ADR-028 status `Accepted` with the date; ADR-015 gains a status note
   ("Amended by ADR-028: content-addressed identity, exact rates, TTS and
   helper documents; billing period removed from snapshots") and its Neutral
   TTS bullet is updated.
2. Design document: amend the cost bullets near lines 1501–1511, the future
   SLA contract near lines 1520–1532, the `pricing_snapshots` data-model bullet
   near lines 1673–1676, and the port description near lines 809–815 (also
   fixing the `run_pricing_pins` key wording); reference ADR-028.
3. `docs/users-guide.md` §"Cost Management": the v1 rate-card format with an
   LLM and a TTS example, how to correct a rate card (edit the file; earlier
   runs keep the earlier version), legacy-file conversion, the
   `cost.pricing_snapshot` failure category, and the stop-the-world upgrade
   order.
4. `docs/developers-guide.md`: `PricingSnapshotRepository`, the integrity
   check, the v1 canonical form (pointing to ADR-028), metric naming and
   recommended vocabulary including TTS metrics, units, and test fixtures.
5. `docs/contents.md`: ADR-028, this ExecPlan, the missing cost ADR-015 entry,
   and the missing `2.4.4` ExecPlan entry. `docs/repository-layout.md`: the
   `episodic/cost/` package and `config/pricing-snapshots/`.
6. `docs/roadmap.md`: mark `2.5.1` done; add hand-off bullets to `2.5.3`
   ("record the rounding rule and expose exact cost") and `2.5.4` ("store the
   rounding rule per ledger row").
7. Run all gates; update `Outcomes & retrospective`; set status `COMPLETE`
   only after reconciling every discovery with the upstream documents.

## Milestones and plateaus

- EP-M1: shared leaf modules exist; ADR-028 proposed.
  - Requirements and gaps: enabling work only.
  - Acceptance evidence: gates green; Hecate passes.
  - Conformance check: no behaviour change; no public interface change; no
    persisted-format change; trace links unchanged.
  - Recovery: revert the commit.
  - Remaining gaps: G1–G6.
  - Compatibility decision: none.
- EP-M2: pinned pricing reads the database.
  - Requirements and gaps: `RM-2.5.1-C` (partial), G1.
  - Acceptance evidence:
    `test_pinned_call_prices_from_persisted_snapshot_after_file_removal`.
  - Conformance check: ADR-018 pinning honoured; Hecate passes; no
    persisted-format change; new port documented in ADR-028 draft.
  - Recovery: revert; the schema is untouched.
  - Remaining gaps: G2–G6.
  - Compatibility decision: none (internal ports change with all callers).
- EP-M3: v1 content-addressed snapshots and migration.
  - Requirements and gaps: `RM-2.5.1-A`, `RM-2.5.1-B`, `RM-2.5.1-C`; G2–G6.
  - Acceptance evidence: hash, rate, store, catalogue, and migration tests.
  - Conformance check: ADR-018 invariants (content addressing, insert-only,
    no triggers); rounding unchanged; persisted-format change approved via
    ADR-028; trace links updated.
  - Recovery: downgrade is supported only on an empty table; to recover a
    populated database, restore the pre-upgrade backup taken in `Concrete
    steps`.
  - Remaining gaps: behavioural scenarios and documentation.
  - Compatibility decision: alpha databases holding `2.4.4` rows (deployed
    state) require the data migration; no source-API compatibility.
- EP-M4: behavioural and end-to-end evidence.
  - Requirements and gaps: `RM-2.5.1-A`–`C` behaviour.
  - Acceptance evidence: `pricing_snapshots.feature` scenarios.
  - Conformance check: no production behaviour beyond the rate correction.
  - Recovery: revert.
  - Remaining gaps: documentation.
  - Compatibility decision: none.
- EP-M5: documentation and roadmap.
  - Requirements and gaps: documentation duties from AGENTS.md.
  - Acceptance evidence: `make markdownlint`, `make nixie`, `make check-fmt`.
  - Conformance check: design document and ADRs match the implementation.
  - Recovery: revert documentation commits.
  - Remaining gaps: none for `2.5.1`.
  - Compatibility decision: none.

## Concrete steps

Run everything from the root of a checkout of branch
`2-5-1-immutable-pricing-snapshots`.

Focused red and green runs, for example:

```bash
uv run pytest tests/test_cost_recorder_integration.py -q 2>&1 \
  | tee /tmp/test-episodic-2-5-1-immutable-pricing-snapshots.out
```

Expected red output in EP-M2 before the fix (abridged):

```plaintext
FAILED tests/test_cost_recorder_integration.py::test_pinned_call_prices_from_persisted_snapshot_after_file_removal
LookupError: No pricing snapshot found for id …
```

Gates, run sequentially (never in parallel), each through `tee`; prefer
delegating the full sequence to the `scrutineer` agent:

```bash
set -e
set -o pipefail
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-2-5-1-immutable-pricing-snapshots.out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-2-5-1-immutable-pricing-snapshots.out
make lint 2>&1 | tee /tmp/lint-episodic-2-5-1-immutable-pricing-snapshots.out
make test 2>&1 | tee /tmp/test-episodic-2-5-1-immutable-pricing-snapshots.out
make check-migrations 2>&1 | tee /tmp/check-migrations-episodic-2-5-1-immutable-pricing-snapshots.out
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-2-5-1-immutable-pricing-snapshots.out
make nixie 2>&1 | tee /tmp/nixie-episodic-2-5-1-immutable-pricing-snapshots.out
```

Local `make test` needs Vidai Mock 0.2.8 or later on `PATH`. Shared-host pytest
timeouts above 180 seconds are usually host contention; re-run the failing
module alone before treating them as failures.

Before applying migration `000017` to any alpha database, scale launchers and
workers to zero so no write lands between the dump and the upgrade, then take a
complete database backup. A table-only dump omits `alembic_version`, so a
restore would leave the schema and the recorded revision disagreeing:

```bash
pg_dump "$DATABASE_URL" > /tmp/episodic-backup.sql
```

Then run `uv run alembic upgrade head` and roll out the new image.

## Validation and acceptance

Quality criteria:

- Tests: `make test` passes, including every artefact named in
  `Verification plan`, with no `xfail` markers left from this plan.
- Verification: every obligation in `Verification plan` is discharged with its
  non-vacuity evidence recorded in `Artefacts and notes`.
- Lint and types: `make check-fmt`, `make typecheck`, and `make lint`
  (Hecate, Ruff, Pylint, df12, ambrleaks, Skylos, nose) pass.
- Migrations: `make check-migrations` reports no drift.
- Documentation: `make markdownlint` and `make nixie` pass.

Behavioural specification (`tests/features/pricing_snapshots.feature`):

```gherkin
Feature: Immutable pricing snapshots
  Pricing snapshots are immutable, content-addressed documents, so historical
  run costs remain reproducible after rate cards change.

  Scenario: A pinned run reprices identically after its rate card is revised
    Given a gpt-4o-mini rate card charging 8 minor units per million cached input tokens
    And a generation run pinned to that rate card
    When the run records a call with 1000000 input tokens and 1000000 cached input tokens
    And the rate card file is revised to charge 7.5 minor units per million cached input tokens
    Then the run's ledger entry costs 23 minor units
    And repricing the ledger entry from its persisted snapshot costs 23 minor units
    And a new run pinned after the revision prices the same usage at 22 minor units

  Scenario: A pinned run keeps pricing after its rate card file is deleted
    Given a gpt-4o-mini rate card charging 8 minor units per million cached input tokens
    And a generation run pinned to that rate card
    When the rate card file is deleted
    And the run records a call with 1000000 input tokens and 1000000 cached input tokens
    Then the run's ledger entry costs 23 minor units

  Scenario: A text-to-speech rate card prices characters and audio duration
    Given a TTS rate card charging 1500 minor units per 1000000 input characters
    And the TTS rate card charges 5 minor units per 60000 output audio milliseconds
    When the rate card is persisted and read back
    Then the stored snapshot equals the rate card
    And usage of 2000000 input characters and 120000 output audio milliseconds costs 3010 minor units

  Scenario: A helper-service SLA4OAI plan document is preserved
    Given an SLA4OAI plans document for the helper service "pedante"
    When the helper pricing snapshot is persisted and read back
    Then the stored source document text is identical to the original
    And changing one character of the document produces a different content hash

  Scenario: A tampered pricing snapshot row is refused
    Given a persisted gpt-4o-mini pricing snapshot
    When its rates are altered directly in the database
    Then reading the snapshot fails with a pricing snapshot integrity error

  Scenario: A Vidai Mock completion is priced from the persisted snapshot
    Given a Vidai Mock server reporting 2000000 prompt tokens of which 1000000 are cached and 500000 completion tokens
    And a generation run pinned to a gpt-4o-mini rate card charging 8 minor units per million cached input tokens
    When the run completes a chat completion through the OpenAI-compatible adapter and records its cost
    Then the run's ledger entry costs 53 minor units
    When the rate card file is revised to charge 7.5 minor units per million cached input tokens
    Then repricing the ledger entry from its persisted snapshot costs 53 minor units
    And a new run pinned after the revision prices the same usage at 52 minor units
```

Arithmetic for the expected values: `1,000,000 × 15 / 1,000,000 = 15` (input);
`1,000,000 × 8 / 1,000,000 = 8` (cached, original);
`⌊1,000,000 × 3 / 400,000⌋ = 7` (cached, corrected, 7.5 per million reduced to
3 per 400,000); `500,000 × 60 / 1,000,000 = 30` (output). Hence 23, 22, 53, and
52. TTS: `2,000,000 × 1500 / 1,000,000 = 3000` plus `120,000 × 1 / 12,000 = 10`
(5 per 60,000 reduced to 1 per 12,000).

The BDD runner command, which must fail before EP-M4 (missing steps) and pass
afterwards:

```bash
uv run pytest tests/steps/test_pricing_snapshots_steps.py -v 2>&1 \
  | tee /tmp/test-episodic-2-5-1-immutable-pricing-snapshots.out
```

Expected final output (abridged):

```plaintext
tests/steps/test_pricing_snapshots_steps.py::test_a_pinned_run_reprices_identically_after_its_rate_card_is_revised
PASSED
…
6 passed
```

At each milestone boundary, record the conformance check from
`Milestones and plateaus` in `Outcomes & retrospective`.

## Idempotence and recovery

- Every code step is re-runnable; gates are read-only apart from `make fmt`.
- Migration `000017` runs in one transaction and takes an exclusive lock on
  `pricing_snapshots`; a failure rolls back to `20261031_000016` with the
  `CommandError` message naming the offending rows. Fix the data (or escalate)
  and re-run.
- Downgrade is deliberately refused on a populated table. Recovery from a bad
  upgrade on a populated database is restore-from-backup (see `Concrete steps`).
- `ensure` is idempotent by construction; re-running a recorder step after a
  crash reuses the stored snapshot and existing pins.
- If a milestone is abandoned, revert its commits; earlier milestones remain
  coherent plateaus.

## Artefacts and notes

Expert-panel summary (2026-10-16), recorded because it shaped the design:

```plaintext
Pandalump (structure): Revise - import cycle via ports.py; hash fails on
  timestamptz round trip; subject too coarse; shallow immutability; 400-line
  files; canonical_json_bytes in the wrong Hecate group.
Wafflecat (alternatives): strongest alternative = content-addressed identity
  plus effective dating (adopted); billing period is not a rate-card property
  (adopted); reduce rates to lowest terms (adopted); keep rounding out of the
  document (adopted).
Buzzy Bee (scale): floor-per-metric records small calls as zero (handed to
  2.5.3/2.5.4); per_units model covers real TTS cards; bound integers to
  2**53-1; normalize instants before hashing.
Telefono (contracts): per-schema frozen field list; UTC microsecond instants;
  source document as text plus digest; legacy files; offline migration guard.
Doggylump (operations): in-place edit must not fail runs (solved by content
  addressing); stop-the-world deploy; startup validation; failure category.
Dinolump (viability): close G1 first; defer plan_name and list_revisions;
  split adapters.py; replace a vacuous Vidai Mock test with a real recorder
  integration test plus a meaningful Vidai Mock scenario.
```

Record red, green, and refactor transcripts for each milestone here as work
proceeds.

## Interfaces and dependencies

No new dependencies. Standard library: `dataclasses`, `enum`, `fractions`
(`math.gcd` for reduction), `decimal` (YAML decimal-string parsing only),
`hashlib`, `json`, `types.MappingProxyType`, `uuid.uuid7`.

New and changed modules, with Hecate groups:

- `episodic/json_canonicalization.py` (`domain_ports`):
  `canonical_json_bytes(payload: Mapping[str, object]) -> bytes`.
- `episodic/cost/primitives.py` (`domain_ports`): moved identifiers, enums,
  `CostAccountingError`, currency validation.
- `episodic/cost/pricing_snapshot.py` (`domain_ports`):

```python
class PricedService(enum.StrEnum):
    LLM = "llm"
    TTS = "tts"
    HELPER_SERVICE = "helper_service"


class UsageUnit(enum.StrEnum):
    TOKEN = "token"
    CHARACTER = "character"
    MILLISECOND = "millisecond"
    REQUEST = "request"


@dc.dataclass(frozen=True, slots=True)
class MeteredRate:
    """Exact price: ``amount_minor`` minor units per ``per_units`` units."""

    amount_minor: int  # 0 <= amount_minor <= 2**53 - 1
    per_units: int  # 1 <= per_units <= 2**53 - 1
    unit: UsageUnit

    @classmethod
    def reduced(
        cls, amount_minor: int, per_units: int, unit: UsageUnit
    ) -> MeteredRate: ...

    # __post_init__ rejects values outside bounds and fractions not in lowest terms.


@dc.dataclass(frozen=True, slots=True)
class SourceDocument:
    media_type: str  # non-blank, for example "application/yaml"
    content: str  # verbatim; at most 262_144 UTF-8 bytes

    @property
    def sha256(self) -> str: ...  # "sha256:<hex>" of UTF-8 content


@dc.dataclass(frozen=True, slots=True)
class PricingSubject:
    service_kind: PricedService
    provider_name: str
    model: str
    operation: str


@dc.dataclass(frozen=True, slots=True)
class PricingSnapshot:
    service_kind: PricedService
    provider_name: str
    model: str
    operation: str
    source_kind: PricingSourceKind
    currency: CurrencyCode
    rates: cabc.Mapping[str, MeteredRate]  # deep-frozen
    source_metadata: cabc.Mapping[str, str]  # deep-frozen; identifier keys
    retrieved_at: dt.datetime  # timezone-aware
    effective_from: dt.datetime | None = None  # timezone-aware when set
    source_document: SourceDocument | None = None
    schema_version: int = 1  # only 1 is accepted
    content_hash: str = dc.field(init=False)  # derived in __post_init__

    @property
    def subject(self) -> PricingSubject: ...
```

`PricingSnapshot` invariants (each a parameterized case in
`tests/test_cost_pricing_snapshot_model.py`): non-blank provider, model, and
operation; currency three uppercase letters; naive instants rejected; metric
names and `source_metadata` keys match `^[a-z][a-z0-9_]{0,63}$`;
`provider_rate_card` requires at least one rate; `sla4oai_plan` requires a
source document; `schema_version != 1` rejected; mappings are copied and frozen
so later mutation of the caller's dictionaries cannot change the snapshot.

- `episodic/cost/pricing_snapshot_hash.py` (`domain_ports`):

```python
PRICING_SNAPSHOT_V1_FIELDS: typ.Final = (
    "currency",
    "effective_from",
    "model",
    "operation",
    "provider_name",
    "rates",
    "retrieved_at",
    "schema_version",
    "service_kind",
    "source_document",
    "source_kind",
    "source_metadata",
)


def canonical_pricing_document(snapshot: PricingSnapshot) -> dict[str, object]: ...
def pricing_snapshot_content_hash(snapshot: PricingSnapshot) -> str: ...
```

Canonical form, schema version 1 (normative; ADR-028 repeats it with vectors):
a JSON object whose keys are exactly `PRICING_SNAPSHOT_V1_FIELDS`; enum values
as their string values; `rates` as an object mapping metric name to
`{"amount_minor": int, "per_units": int, "unit": str}` in lowest terms;
`source_metadata` as an object of strings; instants as UTC strings
`YYYY-MM-DDTHH:MM:SS.ffffffZ` (always six fractional digits); absent
`effective_from` and `source_document` as `null`; `source_document` as
`{"media_type": str, "sha256": "sha256:<hex>"}`; encoded with
`episodic.json_canonicalization.canonical_json_bytes`; the hash is
`"sha256:" + hashlib.sha256(bytes).hexdigest()`. A future schema version
defines its own field tuple and encoder; rows are re-hashed with the encoder
selected by their stored `schema_version`, so adding a field never changes the
hash of a version 1 row.

- `episodic/cost/pricing_snapshot_ports.py` (`domain_ports`):

```python
class SnapshotEnsureOutcome(enum.StrEnum):
    PERSISTED = "persisted"
    REUSED = "reused"


@dc.dataclass(frozen=True, slots=True)
class EnsuredPricingSnapshot:
    pricing_snapshot_id: PricingSnapshotId
    outcome: SnapshotEnsureOutcome


class PricingSnapshotError(CostAccountingError): ...


class PricingSnapshotNotFoundError(PricingSnapshotError, LookupError): ...


class PricingSnapshotIntegrityError(PricingSnapshotError): ...


@typ.runtime_checkable
class PricingSnapshotRepository(typ.Protocol):
    async def ensure(self, snapshot: PricingSnapshot) -> EnsuredPricingSnapshot: ...
    async def get(self, pricing_snapshot_id: PricingSnapshotId) -> PricingSnapshot: ...
```

- `episodic/cost/ports.py`:
  `PricingCataloguePort.resolve(self, subject: PricingSubject) -> PricingSnapshot`;
  `CostLedgerPort` without `ensure_snapshot`; `PricingSnapshot` and
  `PricingSnapshotCollisionError` removed.
- `episodic/cost/engine.py`:
  `PricingRequest(usage, operation, is_estimated=False)`;
  `BillingPeriodMismatchError` removed.
- `episodic/cost/recorder.py`:
  `CostRecorder(ledger, snapshots, pricing_catalogue, pricing_engine)`;
  `CostProviderOperation(service_kind, provider_name, model, operation)`.
- `episodic/cost/pricing_catalogue/_document.py` (`outbound_adapter`): v1
  YAML parsing; `episodic/cost/pricing_catalogue/file_loader.py`:
  `FilePricingCatalogue.from_directory(...)`, `PricingCatalogueError`.
- `episodic/cost/storage/pricing_snapshot_store.py` (`outbound_adapter`):
  `SqlAlchemyPricingSnapshotStore(session, *, metrics=None, tracer=None,
  clock=None)`.
- Unit of work:
  `CanonicalUnitOfWork.pricing_snapshots: PricingSnapshotRepository`.

Table `pricing_snapshots` after migration `000017`:

```plaintext
id                          uuid primary key            (surrogate; UUIDv7 for new rows)
schema_version              integer not null            check (schema_version = 1)
service_kind                text not null               check in ('llm','tts','helper_service')
provider_name               text not null
model                       text not null
operation                   text not null
source_kind                 text not null               check in ('provider_rate_card','sla4oai_plan')
currency                    varchar(3) not null
rates                       jsonb not null              {metric: {amount_minor, per_units, unit}}
source_metadata             jsonb not null
retrieved_at                timestamptz not null
effective_from              timestamptz null
source_document_media_type  text null                   check: both source_document columns null or both set
source_document_content     text null                   check: required when source_kind = 'sla4oai_plan'
content_hash                text not null               unique (uq_pricing_snapshots_content_hash)
recorded_at                 timestamptz not null default now()   (not hashed)
```

Shipped rate card, schema version 1
(`config/pricing-snapshots/openai-2026-05.yaml` after EP-M3; EP-M4 changes
`cached_input_tokens` to `"7.5"`):

```yaml
schema_version: 1
service_kind: llm
provider_name: openai
model: gpt-4o-mini
operation: chat_completions
source_kind: provider_rate_card
currency: USD
rates:
  input_tokens: {amount_minor: 15, per_units: 1000000, unit: token}
  output_tokens: {amount_minor: 60, per_units: 1000000, unit: token}
  cached_input_tokens: {amount_minor: 8, per_units: 1000000, unit: token}
  reasoning_tokens: {amount_minor: 60, per_units: 1000000, unit: token}
  audio_input_tokens: {amount_minor: 40, per_units: 1000000, unit: token}
  audio_output_tokens: {amount_minor: 80, per_units: 1000000, unit: token}
source_metadata:
  source_url: https://openai.com/api/pricing/
retrieved_at: "2026-05-01T00:00:00Z"
effective_from: "2026-05-01T00:00:00Z"
```

## Revision note

- 2026-10-16: initial draft. Written after Wyvern reconnaissance, Firecrawl
  prior-art research, and a six-member expert design review whose findings
  replaced authored revision numbers with content-addressed identity, removed
  the billing period from snapshots, fixed the canonical instant encoding,
  stored source documents as text plus digest, and re-sequenced milestones to
  close the file-read reproducibility gap first.
- 2026-10-24: restored the draft after the uncommitted file was lost from the
  worktree; added the Hecate note that ungrouped modules are never checked
  (with a structural test in `INV-ARCH`) and the discovery about committing
  living documents before long-running gates. No design change.
- 2026-10-24: applied a final consistency review. BDD scenarios now use a
  pre-correction card copied into a temporary catalogue (the shipped card is
  corrected in EP-M4); the recorder resolver returns the snapshot identifier
  explicitly and derives the unpinned subject's service kind from
  `provider_type`; corrected caller lists, the Hecate structural test file, the
  ADR template reference, the Skylos entry, the legacy migration defaults, the
  `INV-LEGACY-EQ` control wording, and the `canonical_json_bytes` rationale;
  added the pin-key residual risk. No change to the approved design direction.
- Decision (2026-11-10, EP-M3): the cost package facade `episodic.cost` and
  its stdlib-only helper `episodic.cost._time` stay outside every Hecate group,
  and `tests/test_production_hecate_cost_config.py` pins that fact. Rationale:
  the facade re-exports ports beside the application `CostRecorder`, so no
  single policy group describes it, and `_time` imports nothing from the
  project. The structural test globs the package recursively, so a new module
  without a group fails, which is the property `INV-ARCH` needs. Date/Author:
  2026-11-10, implementation agent.
