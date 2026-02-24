# Upgrade to Python 3.14: adopt lazy annotation semantics

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & discoveries`, `Decision log`, and
`Outcomes & retrospective` must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

Status: DRAFT

## Purpose and big picture

After this change, Episodic will rely on Python 3.14 deferred annotation
semantics directly and stop requiring `from __future__ import annotations` in
project modules. The observable outcome is a cleaner, modernized codebase that
aligns with Python 3.14 behaviour and avoids lint rules that force legacy
future imports.

Success is visible when future-import lines are removed where appropriate,
runtime behaviour remains stable, and all quality gates pass.

## Constraints

- Keep runtime behaviour unchanged for domain logic and persistence.
- Preserve compatibility with SQLAlchemy annotation usage in
  `episodic/canonical/storage/models.py`.
- Do not broaden scope into unrelated typing refactors.
- Keep pyproject/tooling coherent with Python 3.14 expectations.
- Run all Python quality gates before completion:
  `make check-fmt`, `make lint`, `make typecheck`, and `make test`.

## Tolerances (exception triggers)

- Scope: if more than 25 Python files require manual non-import edits, stop and
  escalate.
- Tooling: if removing the Ruff `FA` rule causes unrelated lint drift that is
  not annotation-related, stop and escalate.
- Runtime: if SQLAlchemy model loading fails due to annotation evaluation,
  stop and escalate.
- Iterations: if full gates fail twice after targeted fixes, stop and escalate
  with logs.

## Risks

- Risk: some modules may implicitly rely on stringized annotations under older
  behaviour. Severity: medium. Likelihood: medium. Mitigation: run full tests
  and type checks after removal and patch only affected call sites.

- Risk: lint policy changes may accidentally relax unrelated standards.
  Severity: medium. Likelihood: low. Mitigation: make the minimal Ruff
  configuration change and preserve existing rule set otherwise.

- Risk: docs and coding examples may still instruct future imports.
  Severity: low. Likelihood: medium. Mitigation: update docs references in the
  same change.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan created.
- [ ] Stage A: Inventory all future imports and relevant lint configuration.
- [ ] Stage B: Update tests or add regressions for annotation-sensitive paths.
- [ ] Stage C: Remove future imports and adjust tooling/docs.
- [ ] Stage D: Run full gates and finalize notes.

## Surprises & discoveries

- Observation: project memory MCP resources are unavailable in this session.
  Evidence: empty results from `list_mcp_resources` and
  `list_mcp_resource_templates`. Impact: plan context comes from local
  repository inspection only.

- Observation: the project enables Ruff `FA` rules that enforce
  `from __future__ import annotations`. Evidence: `pyproject.toml` includes
  `"FA"` in `tool.ruff.lint.select`. Impact: lint configuration must be updated
  as part of this migration.

## Decision log

- Decision: treat this as a behaviour-preserving modernization, not a typing
  redesign. Rationale: the goal is to align with Python 3.14 language defaults
  while minimizing blast radius. Date/Author: 2026-02-24 / Codex.

- Decision: include docs and lint-policy updates in the same milestone.
  Rationale: code and contributor guidance must not diverge after migration.
  Date/Author: 2026-02-24 / Codex.

## Outcomes & retrospective

Pending implementation.

Completion should show that annotation import cleanup and tooling updates can
be landed without runtime regressions.

## Context and orientation

Future annotations imports are present across most Python modules in
`episodic/` and `tests/`. Tooling currently enforces these imports through Ruff
`FA` rules in `pyproject.toml`.

Relevant files include:

- `pyproject.toml`
- `episodic/**/*.py`
- `tests/**/*.py`
- `docs/scripting-standards.md` and other docs containing future-import code
  examples.

The migration target is Python 3.14+, where deferred annotation behaviour is
available by default and the explicit future import is no longer required.

## Plan of work

Stage A maps migration scope. Generate an inventory of all
`from __future__ import annotations` occurrences and identify modules that may
be sensitive to runtime annotation evaluation, especially SQLAlchemy model
modules.

Stage B updates tests first where needed. If no existing test directly protects
annotation-sensitive behaviour, add focused regression tests around model
import and mapper configuration to ensure runtime annotation access remains
stable.

Stage C applies migration edits. Remove future imports from project modules,
update Ruff config to stop enforcing `FA`, and adjust documentation examples
that prescribe future imports as mandatory. Keep all other style and typing
rules intact.

Stage D validates with full gates. Resolve any runtime or typing regressions,
then finalize with concise documentation notes in the developer guide if needed.

## Concrete steps

Run from repository root.

1. Inventory current usage.

    rg -n "from __future__ import annotations" episodic tests docs
    rg -n '"FA"' pyproject.toml

2. Add or update annotation-sensitive tests first and run them.

    set -o pipefail; uv run pytest -v tests/test_canonical_storage.py \
      tests/test_migration_check.py 2>&1 \
      | tee /tmp/py314-lazy-ann-targeted.log |

3. Apply code and tooling changes.

4. Run full gates with logs.

    set -o pipefail; make check-fmt 2>&1 | tee /tmp/py314-lazy-ann-check-fmt.log
    set -o pipefail; make lint 2>&1 | tee /tmp/py314-lazy-ann-lint.log
    set -o pipefail; make typecheck 2>&1 | tee /tmp/py314-lazy-ann-typecheck.log
    set -o pipefail; make test 2>&1 | tee /tmp/py314-lazy-ann-test.log

Expected success indicators:

- No remaining required future-import enforcement in lint config.
- Project modules import and execute without annotation-related regressions.
- All full gates pass.

## Validation and acceptance

Acceptance criteria:

- `from __future__ import annotations` usage is removed where no longer needed
  by project policy.
- Ruff configuration no longer enforces `FA` as a required rule for this code
  style.
- Runtime behaviour is preserved, especially in SQLAlchemy-backed modules.
- `make check-fmt`, `make lint`, `make typecheck`, and `make test` all pass.

## Idempotence and recovery

- This migration is text-based and can be repeated safely.
- If regressions surface, revert only affected modules and re-apply in smaller
  batches by package.
- If lint churn becomes broad, limit fixes to annotation-related changes and
  escalate on scope breach.

## Artifacts and notes

Capture during implementation:

- `git diff -- pyproject.toml episodic tests docs`
- `/tmp/py314-lazy-ann-targeted.log`
- `/tmp/py314-lazy-ann-check-fmt.log`
- `/tmp/py314-lazy-ann-lint.log`
- `/tmp/py314-lazy-ann-typecheck.log`
- `/tmp/py314-lazy-ann-test.log`

## Interfaces and dependencies

- Language baseline must be Python 3.14+.
- No new third-party dependencies are expected.
- Lint/tool changes are limited to project policy in `pyproject.toml`.
- Existing port and repository interfaces remain unchanged.

## Revision note

Initial draft created to plan migration from explicit future annotations
imports to Python 3.14 native deferred annotation semantics.
