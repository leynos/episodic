# Migrate episodic to femtologging v0.1.0 API at SHA 691a73962df8f99308a82348d99c4f707c245e63

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision log`, and `Outcomes & retrospective` must be kept up to date as work
proceeds.

Status: COMPLETE

## Purpose and big picture

`episodic` already depends on `femtologging`, but it is pinned to the older Git
revision `7c139fb7aca18f9277e00b88604b8bf5eb471be0` in `pyproject.toml` and
`uv.lock`. The target revision `691a73962df8f99308a82348d99c4f707c245e63`
includes the v0.1.0 migration changes documented in the upstream migration
guide:
<https://raw.githubusercontent.com/leynos/femtologging/691a73962df8f99308a82348d99c4f707c245e63/docs/v0-1-0-migration-guide.md>.

The practical goal is not only to bump the pinned dependency, but to align the
`episodic` codebase with the newer stdlib-like logging surface where it helps:
direct `logger.info(...)` / `logger.error(...)` style calls,
`logger.exception(...)`, `logger.isEnabledFor(...)`, and the `getLogger`
compatibility alias. At the same time, the migration must preserve local
behaviour that `episodic` currently relies on, especially
`episodic.logging.configure_logging(...)` and the small amount of existing
call-site logging inside the canonical-storage and ingestion code.

Success is observable in six ways:

1. `pyproject.toml` and `uv.lock` both pin `femtologging` to
   `691a73962df8f99308a82348d99c4f707c245e63`.
2. New fail-first tests cover the current `episodic.logging` wrapper and the
   intended stdlib-style usage inside `episodic`.
3. `episodic` code that currently uses `log_info(...)` / `log_error(...)`
   either continues to work through thin compatibility shims or is migrated to
   direct logger convenience methods without changing observable behaviour.
4. No code or tests in `episodic` rely on the upstream renamed flush-builder
   methods, old `as_dict()` keys, or old validation strings after the migration.
5. Maintainer documentation is updated so it no longer teaches the stale
   pre-v0.1.0 femtologging surface.
6. All required repository gates pass after the migration:
   `make fmt`, `make check-fmt`, `make lint`, `make typecheck`, `make test`,
   `make markdownlint`, and `make nixie`.

## Constraints

- Keep the migration dependency-scoped. This is a logging-runtime upgrade, not
  a broad observability redesign.
- Preserve the current public `episodic` package surface unless there is a
  strong, documented reason to change it. In particular,
  `episodic.logging.configure_logging(...)` must either remain available or be
  replaced by a compatibility shim in the same module.
- Prefer the upstream stdlib-like `FemtoLogger` convenience methods for new or
  touched `episodic` call sites, but do not remove compatibility helpers until
  equivalent test coverage exists.
- Treat completed historical ExecPlans in `docs/execplans/` as archival
  records. Do not churn them solely to replace legacy logging examples unless a
  specific plan is still active or normative.
- Update maintainer-facing documentation that is meant to describe current
  practice:
  - `docs/developers-guide.md`
  - `docs/femtologging-users-guide.md`
- Do not invent builder-based usage in order to exercise the upstream rename.
  Discovery already shows that the repository does not use the renamed builder
  methods in production code.
- Use test-first workflow for each touched behaviour:
  1. add or modify tests,
  2. confirm the new or updated tests fail,
  3. implement the code change,
  4. rerun targeted tests,
  5. rerun all repository gates.
- Prefer Makefile targets where they exist. The repository does not expose a
  lockfile-refresh target, so `uv lock` may be invoked directly for that one
  step.

## Tolerances

- Scope tolerance: stop and escalate if the migration requires more than
  roughly 10 source files and 8 documentation files, or more than about 700 net
  lines, before a working vertical slice exists.
- API tolerance: stop and escalate if the new femtologging revision breaks
  `basicConfig(...)`, `get_logger(...)`, or `logger.log(...)` in a way that
  cannot be handled with a local compatibility shim.
- Documentation tolerance: stop and escalate if updating
  `docs/femtologging-users-guide.md` would require a full upstream-document
  resynchronization larger than this migration itself. In that case, switch to
  a smaller accuracy-focused update and record the divergence explicitly.
- Behaviour tolerance: stop and escalate after three failed attempts to make
  the same new logging test pass against the target dependency.
- Dependency tolerance: stop and escalate if the target femtologging SHA
  requires additional new runtime dependencies in `episodic`.

## Risks

- Risk: `episodic/logging.py` has no direct tests today, so an apparently small
  dependency bump could silently change wrapper behaviour. Severity: high.
  Likelihood: high. Mitigation: add wrapper-focused unit and integration tests
  before changing the pinned SHA.

- Risk: the local `docs/femtologging-users-guide.md` is materially behind the
  target upstream revision. It still documents old builder names and claims
  that convenience methods do not exist. Severity: medium. Likelihood: high.
  Mitigation: update the local guide from the target SHA, or at minimum replace
  all sections known to be stale.

- Risk: the repo-wide guidance in `docs/developers-guide.md` currently tells
  maintainers to use `episodic.logging` wrappers, which could work against the
  upstream stdlib-alignment goal. Severity: medium. Likelihood: high.
  Mitigation: update the guide to distinguish between the minimal compatibility
  wrapper and the preferred direct `FemtoLogger` convenience methods for new
  code.

- Risk: moving existing call sites from `log_info(...)` to `logger.info(...)`
  can accidentally introduce eager string interpolation where the old wrapper
  used percent-style templates. Severity: low. Likelihood: medium. Mitigation:
  only migrate the four existing internal call sites, and use
  `logger.isEnabledFor(...)` if any new string construction becomes materially
  expensive.

- Risk: lockfile refresh can cause unrelated dependency churn. Severity: medium.
  Likelihood: medium. Mitigation: pin the exact femtologging SHA, inspect the
  resulting `uv.lock` diff closely, and do not accept unrelated upgrades.

## Progress

- [x] (2026-04-08 00:00Z) Queried project memory and reviewed repository
  instructions, quality gates, and documentation rules.
- [x] (2026-04-08 00:00Z) Audited the current repository usage of
  `femtologging`, `episodic.logging`, and related documentation.
- [x] (2026-04-08 00:00Z) Verified the upstream migration guide and inspected
  the target femtologging revision `691a73962df8f99308a82348d99c4f707c245e63`
  directly.
- [x] (2026-04-08 00:00Z) Drafted this ExecPlan.
- [x] (2026-04-08 20:40Z) Stage A: added fail-first logging regression tests
  in `tests/test_logging.py` and confirmed they failed against the old
  dependency because `getLogger`, logger convenience methods, and
  `isEnabledFor` were absent.
- [x] (2026-04-08 20:42Z) Stage B: updated the femtologging pin in
  `pyproject.toml`, refreshed `uv.lock`, and confirmed the lockfile diff was
  limited to the targeted SHA movement.
- [x] (2026-04-08 20:50Z) Stage C: aligned `episodic` call sites and
  compatibility helpers with the stdlib-like API.
- [x] (2026-04-08 20:56Z) Stage D: updated maintainer documentation and the
  local femtologging guide for the v0.1.0 surface.
- [x] (2026-04-08 21:10Z) Stage E: ran the full repository gate set and
  captured evidence under `/tmp/femtologging-migration-*.log`.

## Surprises & discoveries

- Observation: the repository does not use the upstream-renamed builder methods
  (`with_flush_timeout_ms`, `with_flush_record_interval`) anywhere in
  production code or tests. Impact: the upstream breaking changes are mostly a
  documentation and compatibility-audit exercise for `episodic`, not a large
  code rewrite.

- Observation: `episodic/logging.py` is a small local wrapper that imports only
  `basicConfig` and `get_logger`, then adds three convenience helpers
  (`log_info`, `log_warning`, `log_error`). Impact: the migration can either
  keep this as a compatibility facade or thin it further while moving the few
  internal call sites to direct `FemtoLogger` methods.

- Observation: only four code locations currently import the wrapper helpers:
  `episodic/canonical/ingestion_service.py`, `episodic/canonical/services.py`,
  `episodic/canonical/storage/migration_check.py`, and
  `episodic/canonical/storage/uow.py`. Impact: direct call-site migration is
  cheap if the implementation chooses it.

- Observation: `docs/femtologging-users-guide.md` is stale relative to the
  target upstream revision. It still mentions `.with_flush_timeout_ms(...)`,
  says convenience methods are not implemented, and omits `getLogger`,
  `isEnabledFor`, and `StdlibHandlerAdapter`. Impact: documentation is part of
  the real migration surface and cannot be skipped.

- Observation: `docs/developers-guide.md` currently tells maintainers to import
  `get_logger` from `episodic.logging` and emit via `log_info`, `log_warning`,
  or `log_error`. Impact: a decision is needed about whether those wrappers
  remain the preferred style or become legacy compatibility shims.

- Observation: the target femtologging revision still accepts
  `basicConfig(level=..., force=...)`, so `configure_logging(...)` does not
  need a breaking redesign just to survive the dependency bump. Impact: the
  migration can stay incremental.

- Observation: femtologging v0.1.0 adds stdlib-style method names, but it
  still does not implement stdlib lazy `*args` formatting. Impact: the direct
  call-site migration must build final strings before calling
  `logger.info(...)` or `logger.error(...)`.

- Observation: runtime handler assertions need an explicit
  `logger.flush_handlers()` before checking collected Python-handler output.
  Impact: integration tests should flush before asserting on emitted records.

## Decision log

- Decision: use a compatibility-first migration. Bump the dependency and
  protect existing `episodic.logging` behaviour with tests before deciding how
  much wrapper cleanup to do. Rationale: the wrapper is currently untested, and
  dependency-only changes are safest when anchored by new regression tests.
  Date/Author: 2026-04-08 / Codex.

- Decision: prefer direct `FemtoLogger` convenience methods in touched
  `episodic` production code, but keep `episodic.logging` available for
  configuration and compatibility during this migration. Rationale: the target
  revision adds stdlib-like methods specifically to reduce the need for local
  wrappers, but removing the wrapper entirely would create avoidable churn.
  Date/Author: 2026-04-08 / Codex.

- Decision: do not mass-edit completed historical ExecPlans that mention the
  wrapper. Rationale: those files document how earlier work was delivered, not
  the preferred style for future changes. Current maintainer guidance should be
  corrected in `docs/developers-guide.md` instead. Date/Author: 2026-04-08 /
  Codex.

- Decision: treat the local `docs/femtologging-users-guide.md` as a tracked
  local copy of upstream guidance and update it to match the target dependency
  revision. Rationale: the file is already in the repository and is clearly
  meant to describe current femtologging behaviour for maintainers.
  Date/Author: 2026-04-08 / Codex.

## Outcomes & retrospective

Outcome:

- `pyproject.toml` and `uv.lock` now pin femtologging to
  `691a73962df8f99308a82348d99c4f707c245e63`.
- `tests/test_logging.py` covers wrapper normalization, compatibility helpers,
  `getLogger`, direct convenience methods, and `isEnabledFor`.
- `episodic.logging` remains the configuration seam, now re-exporting
  `getLogger` and delegating compatibility helpers through direct logger
  methods.
- The internal logging call sites in ingestion, canonical services, unit of
  work, and schema-drift detection now use direct logger methods.
- Maintainer docs were updated to stop teaching wrapper-only usage and stale
  builder names.

Retrospective:

- The code migration was small, but the missing tests and stale docs were the
  real risk surface.
- Compatibility-first worked: the wrapper remains available without blocking
  direct stdlib-style usage in touched code.
- The main behavioural nuance worth preserving in docs and tests is that
  femtologging v0.1.0 keeps pre-formatted-message semantics even though the
  method names now look more like stdlib logging.

## Context and orientation

### Current dependency state

The repository currently pins femtologging in two places:

- `pyproject.toml`
- `uv.lock`

Both point at the older Git revision
`7c139fb7aca18f9277e00b88604b8bf5eb471be0`. The target revision for this
migration is `691a73962df8f99308a82348d99c4f707c245e63`.

### Current local logging wrapper

`episodic/logging.py` currently:

- re-exports `get_logger` from femtologging,
- wraps `basicConfig(...)` in `configure_logging(...)`,
- defines `log_info(...)`, `log_warning(...)`, and `log_error(...)`,
- uses a local `_SupportsLog` protocol that targets `logger.log(...)`.

The wrapper is not referenced by any direct test file today.

### Current internal call sites

Only four production files use the wrapper today:

- `episodic/canonical/ingestion_service.py`
- `episodic/canonical/services.py`
- `episodic/canonical/storage/migration_check.py`
- `episodic/canonical/storage/uow.py`

These call sites are simple enough to move to `logger.info(...)`,
`logger.error(...)`, or `logger.exception(...)` if desired.

### Upstream change surface relevant to episodic

From the upstream migration guide and direct inspection of the target revision:

- Builder method renames:
  - `with_flush_timeout_ms(...)` ->
    `with_flush_after_ms(...)`
  - `with_flush_record_interval(...)` ->
    `with_flush_after_records(...)`
- Matching `as_dict()` key renames:
  - `flush_timeout_ms` -> `flush_after_ms`
  - `flush_record_interval` -> `flush_after_records`
- Matching validation message renames:
  - `flush_timeout_ms must be greater than zero` ->
    `flush_after_ms must be greater than zero`
  - `flush_record_interval must be greater than zero` ->
    `flush_after_records must be greater than zero`
- New stdlib-like additions:
  - `logger.debug(...)`, `logger.info(...)`, `logger.warning(...)`,
    `logger.error(...)`, `logger.critical(...)`, `logger.exception(...)`
  - `logger.isEnabledFor(...)`
  - `getLogger(...)` alias for `get_logger(...)`
  - `StdlibHandlerAdapter` for wrapping stdlib `logging.Handler` instances

Only the additions, not the builder renames, appear relevant to current
`episodic` production code.

### Known documentation gap

The local `docs/femtologging-users-guide.md` is out of date relative to the
target dependency. At minimum, the following sections are known to need
revision:

- `FemtoStreamHandler` builder method naming
- the statements about convenience methods being unavailable
- the `basicConfig` / compatibility sections where stdlib alignment is now
  wider than before
- the deviations section that still says there is no `LoggerAdapter` bridge,
  even though `StdlibHandlerAdapter` now exists

## Plan of work

### Stage A: add fail-first logging regression tests

Create direct tests for the local logging surface before touching the
dependency pin.

Add a new test module, expected to be `tests/test_logging.py`, covering:

- `configure_logging(...)` normalization and defaulting behaviour
- wrapper-level `log_info(...)` / `log_warning(...)` / `log_error(...)`
  compatibility against a lightweight spy object
- integration coverage against the real femtologging runtime for the intended
  post-migration usage:
  - `logger.info(...)`
  - `logger.error(..., exc_info=True)`
  - `logger.exception(...)`
  - `logger.isEnabledFor(...)`

The red phase should demonstrate at least one expectation that the current
repository does not yet encode, such as the preferred direct convenience-method
usage or any newly documented wrapper compatibility behaviour.

Go/no-go: the new tests fail before implementation, and the failure is clearly
explained in the test names or assertions.

### Stage B: update the femtologging pin and refresh uv.lock

Update both dependency declarations:

- `pyproject.toml`
- `uv.lock`

Use the exact Git revision `691a73962df8f99308a82348d99c4f707c245e63`. Keep the
lockfile diff narrow. If `uv lock` pulls unrelated upgrades, revert and retry
with a more targeted dependency refresh approach.

Go/no-go: `pyproject.toml` and `uv.lock` both point at the target SHA, and the
lockfile diff contains only the expected femtologging movement.

### Stage C: align episodic code with the stdlib-like API

Refactor the tiny set of internal call sites to use the newer upstream logger
convenience methods where it improves clarity:

- `logger.info(...)` for simple informational logs
- `logger.error(...)` or `logger.exception(...)` where exception capture is the
  actual intent

Keep `episodic/logging.py` as a small compatibility module, but simplify it so
it no longer hides the upstream API unnecessarily. The expected end state is:

- `configure_logging(...)` remains available
- `get_logger(...)` remains available, and optionally `getLogger(...)` is
  re-exported if that improves internal consistency
- legacy wrapper helpers remain only if there is still local value in keeping
  them, and if retained they should delegate to the new convenience methods
  rather than duplicating logging semantics

Do not remove the compatibility helpers until the new logging tests are green.

Go/no-go: all touched production call sites compile, the logging tests pass,
and the wrapper module has a clear, smaller purpose.

### Stage D: update maintainer documentation

Update the maintainer-facing docs to reflect the new dependency revision and
the intended local usage style.

Required files:

- `docs/developers-guide.md`
- `docs/femtologging-users-guide.md`
- this ExecPlan, updating status/progress/discoveries as implementation
  proceeds

Documentation changes should:

- stop teaching the old builder method names
- stop claiming that convenience methods are unavailable
- explain whether new `episodic` code should prefer direct `logger.info(...)`
  style calls or the local compatibility wrapper
- mention `getLogger(...)`, `isEnabledFor(...)`, and `StdlibHandlerAdapter`
  where relevant

Go/no-go: maintainer guidance no longer contradicts the target femtologging
revision.

### Stage E: run full validation and capture evidence

After the targeted tests and docs are green, run the full repository gates in
the required order and capture all output via `tee`.

Go/no-go: all gates exit `0`, and the resulting logs are saved under `/tmp/`.

## Concrete steps

Run all commands from the repository root.

1. Baseline discovery and current-state evidence:

   ```shell
   set -o pipefail; git status --short 2>&1 | tee /tmp/femtologging-migration-git-status.log
   set -o pipefail; rg -n "femtologging|episodic\\.logging|log_info\\(|log_warning\\(|log_error\\(" \
     pyproject.toml uv.lock episodic docs tests 2>&1 | \
     tee /tmp/femtologging-migration-scan.log
   ```

2. Stage A red phase:

   ```shell
   set -o pipefail; PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
     uv run pytest -v tests/test_logging.py 2>&1 | \
     tee /tmp/femtologging-migration-red-logging.log
   ```

3. Stage B dependency refresh:

   ```shell
   set -o pipefail; PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
     uv lock 2>&1 | tee /tmp/femtologging-migration-uv-lock.log
   set -o pipefail; make build 2>&1 | tee /tmp/femtologging-migration-make-build.log
   ```

4. Stage C targeted green checks after code changes:

   ```shell
   set -o pipefail; PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
     uv run pytest -v tests/test_logging.py tests/test_migration_check.py \
     tests/canonical_storage/test_unit_of_work.py tests/test_ingestion_integration.py \
     2>&1 | tee /tmp/femtologging-migration-green-targeted.log
   ```

5. Stage D and E final repository gates:

   Ensure the `markdownlint-cli2` executable required by `make markdownlint` is
   already available on `PATH` before running this sequence.

   ```shell
   set -o pipefail; make fmt 2>&1 | tee /tmp/femtologging-migration-make-fmt.log
   set -o pipefail; make check-fmt 2>&1 | tee /tmp/femtologging-migration-make-check-fmt.log
   set -o pipefail; make lint 2>&1 | tee /tmp/femtologging-migration-make-lint.log
   set -o pipefail; make typecheck 2>&1 | tee /tmp/femtologging-migration-make-typecheck.log
   set -o pipefail; make test 2>&1 | tee /tmp/femtologging-migration-make-test.log
   set -o pipefail; make markdownlint 2>&1 | \
     tee /tmp/femtologging-migration-make-markdownlint.log
   set -o pipefail; make nixie 2>&1 | tee /tmp/femtologging-migration-make-nixie.log
   ```

Expected success indicators:

- `tests/test_logging.py` fails before the implementation and passes after it.
- The lockfile diff is narrow and points at the target femtologging SHA.
- The touched production modules still pass their targeted tests.
- Maintainer docs describe the new API correctly.
- All make targets complete successfully.

## Validation and acceptance

The migration is complete only when all of the following are true:

- `pyproject.toml` pins femtologging to
  `691a73962df8f99308a82348d99c4f707c245e63`.
- `uv.lock` matches the same femtologging revision.
- Logging regression tests exist and pass.
- Touched `episodic` code uses the intended post-migration logging style.
- `episodic/logging.py` remains accurate and test-covered.
- `docs/developers-guide.md` no longer recommends stale wrapper-only usage.
- `docs/femtologging-users-guide.md` no longer documents the pre-v0.1.0 API.
- All required quality gates pass:
  - `make fmt`
  - `make check-fmt`
  - `make lint`
  - `make typecheck`
  - `make test`
  - `make markdownlint`
  - `make nixie`

## Idempotence and recovery

- All steps are re-runnable.
- If `uv lock` introduces unrelated dependency churn, revert the lockfile and
  retry the refresh with the dependency pin narrowed first.
- If direct call-site migration proves unexpectedly noisy, keep the production
  files on the wrapper for this revision and record that decision in
  `Decision log`; the dependency bump and documentation refresh can still ship
  separately.
- If documentation synchronization becomes too large, reduce Stage D to the
  sections known to be wrong and record the remaining drift explicitly in
  `Surprises & Discoveries`.
- Preserve all `/tmp/femtologging-migration-*.log` files as the evidence trail.

## Artifacts and notes

Expected evidence artifacts:

- `/tmp/femtologging-migration-git-status.log`
- `/tmp/femtologging-migration-scan.log`
- `/tmp/femtologging-migration-red-logging.log`
- `/tmp/femtologging-migration-uv-lock.log`
- `/tmp/femtologging-migration-make-build.log`
- `/tmp/femtologging-migration-green-targeted.log`
- `/tmp/femtologging-migration-make-fmt.log`
- `/tmp/femtologging-migration-make-check-fmt.log`
- `/tmp/femtologging-migration-make-lint.log`
- `/tmp/femtologging-migration-make-typecheck.log`
- `/tmp/femtologging-migration-make-test.log`
- `/tmp/femtologging-migration-make-markdownlint.log`
- `/tmp/femtologging-migration-make-nixie.log`

Implementation files expected to change:

- `pyproject.toml`
- `uv.lock`
- `episodic/logging.py`
- `episodic/canonical/ingestion_service.py`
- `episodic/canonical/services.py`
- `episodic/canonical/storage/migration_check.py`
- `episodic/canonical/storage/uow.py`
- `tests/test_logging.py`
- `docs/developers-guide.md`
- `docs/femtologging-users-guide.md`

## Interfaces and dependencies

Upstream interfaces expected to matter during implementation:

- `femtologging.basicConfig(...)`
- `femtologging.get_logger(...)`
- `femtologging.getLogger(...)`
- `FemtoLogger.log(...)`
- `FemtoLogger.info(...)`
- `FemtoLogger.warning(...)`
- `FemtoLogger.error(...)`
- `FemtoLogger.exception(...)`
- `FemtoLogger.isEnabledFor(...)`
- `StdlibHandlerAdapter`

Local interfaces expected to matter during implementation:

- `episodic.logging.configure_logging(...)`
- `episodic.logging.get_logger(...)`
- `episodic.logging.log_info(...)`
- `episodic.logging.log_warning(...)`
- `episodic.logging.log_error(...)`

The implementation should actively decide which of the local wrapper helpers
remain part of the preferred internal style after the dependency bump, then
document that decision in `Decision log` and `docs/developers-guide.md`.
