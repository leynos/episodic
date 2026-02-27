# Upgrade to Python 3.14: use UUIDv7 for storage IDs

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & discoveries`, `Decision log`, and
`Outcomes & retrospective` must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

Status: COMPLETE

## Purpose and big picture

After this change, Episodic will generate time-ordered UUID version 7 values
for storage-backed identifiers instead of random UUID version 4 values. The
observable benefit is improved locality for index inserts and deterministic
chronological ordering semantics for newly generated IDs, while preserving the
existing UUID column types and public API payload shapes.

Success is visible when canonical ingestion persists records using UUIDv7,
existing retrieval behaviour remains unchanged, and full quality gates pass.

## Constraints

- Do not change table primary key types away from PostgreSQL `UUID`.
- Do not break existing persisted UUIDv4 rows; mixed historical UUID versions
  must remain readable.
- Keep repository and unit-of-work public interfaces stable.
- Keep ingestion semantics unchanged apart from ID generation strategy.
- Use only standard-library UUID support available in Python 3.14.
- Follow repository quality gates for Python changes:
  `make check-fmt`, `make lint`, `make typecheck`, and `make test`.

## Tolerances (exception triggers)

- Scope: if implementation requires edits in more than 10 files, stop and
  escalate.
- Interface: if any public protocol signature in
  `episodic/canonical/ports.py` must change, stop and escalate.
- Persistence: if migration scripts are required to rewrite existing IDs, stop
  and escalate.
- Dependencies: if a third-party UUID library appears necessary, stop and
  escalate.
- Validation: if any gate still fails after 2 fix attempts, stop and escalate
  with logs.

## Risks

- Risk: some tests may implicitly assume UUIDv4 randomness patterns.
  Severity: medium. Likelihood: medium. Mitigation: add focused tests that
  assert UUID version and keep unrelated assertions value-agnostic.

- Risk: database index behaviour gains are workload-dependent and may not be
  visible in unit tests. Severity: low. Likelihood: high. Mitigation: constrain
  acceptance to functional correctness and optionally add a benchmark follow-up
  task.

- Risk: ID generation could remain duplicated across modules.
  Severity: medium. Likelihood: medium. Mitigation: centralize generation
  behind a small helper to avoid drift.

- Risk: UUIDv7 embeds a Unix timestamp, so IDs that reach external API
  consumers reveal record-creation timing. Severity: medium. Likelihood:
  medium. Mitigation: audit API response shapes and event payloads for UUID
  exposure; use opaque aliases where timing disclosure is unacceptable.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan created.
- [x] (2026-02-26 10:29Z) Stage A complete: mapped runtime UUID generation
  and narrowed scope to `episodic/canonical/services.py` ingestion writes.
- [x] (2026-02-26 10:33Z) Stage B complete: added UUIDv7 assertions to
  ingestion behavioural and integration tests, then captured red-phase failures.
- [x] (2026-02-26 10:34Z) Stage C complete: implemented `_new_storage_id()`
  using `uuid.uuid7()` and replaced canonical ingestion storage ID call sites.
- [x] (2026-02-26 10:52Z) Stage D complete: updated Python baseline files,
  refreshed docs, and passed all applicable quality gates.

## Surprises & discoveries

- Observation: current canonical ingestion creates IDs in
  `episodic/canonical/services.py` with `uuid.uuid4()` for episodes, jobs,
  headers, source documents, and approval events. Evidence: direct source
  inspection. Impact: one concentrated module can deliver the primary behaviour
  change.

- Observation: direct `uv run pytest ...` fails before test execution unless
  `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` is set. Evidence:
  `/tmp/py314-uuid7-targeted-red.log` from the first red-phase attempt. Impact:
  the plan's targeted test command needs this environment variable in this
  container.

- Observation: `make check-fmt` on Python 3.14 expects ruff-formatted
  multi-exception syntax (`except TypeError, ValueError:`) in two existing
  modules outside the feature area. Evidence: check-fmt output in
  `/tmp/py314-uuid7-check-fmt.log`. Impact: two formatting-only files were
  updated to satisfy required gates.

## Decision log

- Decision: scope UUIDv7 adoption first to storage ID generation in canonical
  ingestion. Rationale: this is the only implemented write-heavy path today and
  yields immediate value with limited blast radius. Date/Author: 2026-02-24 /
  Codex.

- Decision: do not require data migrations for existing UUIDv4 rows.
  Rationale: PostgreSQL UUID columns are version-agnostic and existing records
  remain valid identifiers. Date/Author: 2026-02-24 / Codex.

- Decision: execute red/green by adding UUID version assertions first in
  ingestion behaviour and integration tests. Rationale: this verifies the
  behaviour contract before implementation and prevents silent regressions.
  Date/Author: 2026-02-26 / Codex.

- Decision: centralize canonical storage ID creation behind
  `_new_storage_id()` in `episodic/canonical/services.py`. Rationale: one
  helper removes duplicated generation logic and keeps call sites aligned.
  Date/Author: 2026-02-26 / Codex.

- Decision: raise project minimum Python to 3.14 in packaging and CI entry
  points (`pyproject.toml`, `uv.lock`, `.github/workflows/ci.yml`,
  `.github/workflows/release.yml`). Rationale: stdlib `uuid.uuid7()` is a
  Python 3.14 feature; declaring 3.13 support would be inaccurate. Date/Author:
  2026-02-26 / Codex.

## Outcomes & retrospective

Completed.

Delivered outcomes:

- Canonical ingestion now generates UUIDv7 IDs for TEI headers, canonical
  episodes, ingestion jobs, source documents, and approval events.
- UUID version assertions were added to ingestion tests and passed after
  implementation (`6 passed` in targeted suite).
- Project baseline now declares Python 3.14 compatibility for packaging and CI
  entry points.
- Documentation now states UUIDv7 storage-ID behaviour in user and design
  guides.

Validation outcomes:

- `make check-fmt` passed.
- `make lint` passed.
- `make typecheck` passed (with one pre-existing `ty` warning).
- `make test` passed (`74 passed, 2 skipped`).
- `make markdownlint` passed.
- `make nixie` passed.

## Context and orientation

The current ID generation surface for canonical persistence is centered in
`episodic/canonical/services.py`, where helper constructors call
`uuid.uuid4()`. Repository adapters in
`episodic/canonical/storage/repositories.py` and ORM models in
`episodic/canonical/storage/models.py` already use generic UUID types and do
not encode version-specific assumptions.

Tests that may need adjustment are primarily:

- `tests/test_canonical_storage.py`
- `tests/steps/test_canonical_ingestion_steps.py`
- `tests/steps/test_multi_source_ingestion_steps.py`
- `tests/conftest.py`

The Python 3.14 `uuid` module adds `uuid7()` support, which this plan adopts
for generated storage IDs.

## Plan of work

Stage A establishes the exact change set. Enumerate every runtime UUID creation
site and identify which are persisted IDs versus ephemeral test data. Confirm
that API inputs accepting caller-supplied UUIDs remain unchanged.

Stage B updates tests first. Add targeted tests around canonical ingestion to
assert that generated IDs are version 7. Avoid brittle equality checks by
validating `id.version == 7` for generated entities. Run focused tests and
confirm they fail before implementation changes.

Stage C implements the behaviour. Introduce a private helper in
`episodic/canonical/services.py` (for example `_new_storage_id()`) that returns
`uuid.uuid7()`, and replace direct `uuid.uuid4()` calls in storage entity
constructors with this helper. Keep externally provided IDs untouched.

Stage D validates and hardens. Run full project gates, update any affected
developer documentation if it mentions UUID generation assumptions, and review
for duplicated generation logic in nearby modules.

## Concrete steps

Run from repository root.

1. Identify generation and usage sites.

    rg -n "uuid\.uuid4|uuid\.uuid7|id=" episodic tests

2. Update tests first, then run targeted test files.

    set -o pipefail; PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
      uv run pytest -v tests/steps/test_canonical_ingestion_steps.py \
      tests/test_ingestion_integration.py \
      2>&1 | tee /tmp/py314-uuid7-targeted.log

3. Implement service-level UUIDv7 generation.

4. Run full gates with logs.

    set -o pipefail; make check-fmt 2>&1 | tee /tmp/py314-uuid7-check-fmt.log
    set -o pipefail; make lint 2>&1 | tee /tmp/py314-uuid7-lint.log
    set -o pipefail; make typecheck 2>&1 | tee /tmp/py314-uuid7-typecheck.log
    set -o pipefail; make test 2>&1 | tee /tmp/py314-uuid7-test.log

Expected success indicators:

- Targeted tests demonstrate fail-before/pass-after for UUID version checks.
- All four full gates exit with status 0.

## Validation and acceptance

Acceptance is met when all of the following are true:

- Canonical ingestion-generated IDs are UUID version 7.
- No repository interface signatures changed.
- Existing persisted data compatibility assumptions remain valid.
- `make check-fmt`, `make lint`, `make typecheck`, and `make test` all pass.
- `make markdownlint` and `make nixie` pass for documentation updates.

## Idempotence and recovery

- The planned edits are deterministic and safe to re-run.
- If tests fail after partial edits, revert only the affected hunks and
  re-apply in this order: tests, implementation, docs.
- If full test suite runtime is long, re-run targeted files first to localize
  regressions before repeating `make test`.

## Artifacts and notes

Capture the following evidence during implementation:

- `git diff -- episodic/canonical/services.py tests`
- `/tmp/py314-uuid7-targeted.log`
- `/tmp/py314-uuid7-targeted-red.log`
- `/tmp/py314-uuid7-check-fmt.log`
- `/tmp/py314-uuid7-lint.log`
- `/tmp/py314-uuid7-typecheck.log`
- `/tmp/py314-uuid7-test.log`
- `/tmp/py314-uuid7-markdownlint.log`
- `/tmp/py314-uuid7-nixie.log`

## Interfaces and dependencies

- Use stdlib `uuid.uuid7()` from Python 3.14.
- Keep `episodic/canonical/ports.py` interfaces unchanged.
- Keep PostgreSQL UUID column mapping unchanged in
  `episodic/canonical/storage/models.py`.
- No new third-party dependency is allowed for UUID generation.

## Revision note

Initial draft created to scope UUIDv7 adoption for storage ID generation after
raising the project minimum Python version to 3.14.

Implementation completed on 2026-02-26 with full quality-gate evidence.
