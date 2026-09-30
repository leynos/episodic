# VidaiMock release/CLI mismatch: upgrade the pin and consolidate startup logic

Branch: `use-cpython-for-pylint` PR:
<https://github.com/leynos/episodic/pull/339> Baseline commit before this work:
`e7e1f04` (post-rebase head); rebased onto `main` at `f1bdaca`, head `bf2acc8`

## Goal

Fix the release/CLI mismatch between the pinned VidaiMock release and the
`--isolated` flag the test fixtures pass, consolidate the duplicated
startup/readiness/cleanup logic, and add the missing regression coverage.

## Problem statement

Both workflows pin VidaiMock `0.1.3`, but the BDD fixtures pass `--isolated`,
which `0.1.3` rejects. The flag was added to the project in this branch without
a corresponding pin bump, so CI would fail at the first behavioural scenario.

Observed, on the pinned `0.1.3` binary:

```text
$ vidaimock --isolated
error: unexpected argument '--isolated' found
exit code 2
```

## Verified findings

### The `0.2.11` candidate

- Published Linux x64 archive SHA-256 confirmed by download:
  `888d40195438491534a7a669776e06977367da62beb57feac8fa1a1f08faa93b`.
- `vidaimock --version` reports `0.2.11`.
- `--help` lists `--isolated`, described as "Ignore the binary's embedded
  provider configs and templates. Only `--config-dir` is loaded".
- `CHANGELOG.md` records `--isolated` as **Added in 0.2.8**, so `0.2.11`
  clears the floor with the whole 0.2.x series behind it.
- Compatibility confirmed end-to-end: a provider config and Jinja template
  written exactly as the fixtures write them were served correctly under
  `--isolated`, returning the double-encoded assistant content the tests assert
  on.

### Isolation is observable

Started twice over the same `--config-dir` declaring `chapter_markers` and
`guest_bios`:

- `--isolated` → `/v1/models` returns exactly the two declared providers.
- without `--isolated` → `/v1/models` also returns the embedded
  `gemini_count_tokens`, `gemini_embed`, `openai`, `anthropic`, … providers.

This is what "retain isolated-mode behaviour" protects, and it is asserted
directly rather than inferred from the argv.

### Failure signatures (v0.2.11), used to separate retryable from fatal

| Condition             | Exit | stderr                                                                                   |
| --------------------- | ---- | ---------------------------------------------------------------------------------------- |
| Unrecognized argument | 2    | `error: unexpected argument '--not-a-flag' found`                                        |
| Port already bound    | 1    | `ERROR: Failed to bind to address 127.0.0.1:46002: Address already in use (os error 98)` |

Both exit before serving. The bind failure is the only retryable one.

### A missing or malformed `--config-dir` does **not** fail startup

Against `0.2.11`, both a nonexistent `--config-dir` and a directory holding
malformed YAML start successfully:

```text
$ vidaimock --config-dir /nonexistent --isolated
🚀 VidaiMock is running at http://127.0.0.1:46004
```

So "do not suppress the underlying configuration error" cannot mean "surface a
startup exit code for a bad config" — there is no such exit. Under `--isolated`
the configuration error surfaces as an unroutable request (a 404 naming the
missing provider, which the changelog notes carries a mode-aware hint). The
harness must therefore not narrow stderr to exit-code-only detail, and must not
retry in a way that hides a config that never loads.

## Upstream release choice

`0.3.1` is the newest published release and matches the locally installed
binary. `0.3.0` changed `start_server()` to return `Err` on bind failure rather
than calling `process::exit(1)`, and its changelog records that the CLI output
and exit code are verified byte-identical against `v0.2.11`.

The task names `v0.2.11` as the candidate and supplies its verified digest. The
digest for `v0.3.1` is **not** supplied, and the task requires the archive be
verified, so `v0.2.11` is adopted as the pin: a supplied, independently
confirmed digest outranks a newer release whose digest would have to be
self-derived. Recorded as a deliberate decision, not an oversight.

## Work plan

1. Consolidate the duplicated VidaiMock harness into
   `tests/steps/vidaimock_harness.py`, keyed by the scenario label the four
   step modules already use in their messages.
2. Bump both workflow pins to `0.2.11` with the verified digest.
3. Add regression tests: immediate child exit, readiness timeout, diagnostic
   propagation.
4. Add a CI smoke test using the installed binary with `--config-dir` and
   `--isolated`.
5. Update `docs/developers-guide.md` for the pin, the harness, and the smoke
   test.
6. Run `make check-fmt`, `make lint`, `make typecheck`, `make test`, plus
   Markdown gates.

## Progress log

- [x] Rebased onto `origin/main` (`15d790e`), no conflicts; semantic audit
      clean (target-only paths byte-identical, no unexplained deletions, no
      new duplicated blocks).
- [x] Verified `0.2.11` archive digest, flag support, and provider/template
      compatibility; characterized failure signatures.
- [x] Harness consolidation: `tests/steps/vidaimock_harness.py` is the single
      owner of startup, readiness, and cleanup; the five step modules and
      `no_qa_generation_slice_support.py` now route through it, each with its
      own scenario label. The superseded
      `test_generation_orchestration_vidaimock.py` was removed.
- [x] Pin bump: both workflows pin `0.2.11` with the verified digest.
- [x] Regression tests: `tests/steps/test_vidaimock_harness.py`, 9 passing
      (immediate exit, readiness timeout, diagnostic propagation, retry
      policy, bounded capture, reaping, and the local-skip/CI-fail contract).
- [x] CI smoke test: `scripts/check_vidaimock_isolated.py`, wired into
      `ci.yml`; passes on `0.3.1` and on the pinned `0.2.11`, and fails with
      the binary's own diagnostic on `0.1.3`.
- [x] Documentation: new "The Vidai Mock pin", "Behavioural inference
      harness", and "Vidai Mock smoke test" sections in
      `docs/developers-guide.md`.
- [x] Full gate run: all six gates green on the frozen tree — `check-fmt`,
      `lint` (Pylint 10.00/10 on all three passes), `typecheck`, `test` (1273
      passed, 1 skipped), `markdownlint`, and `spelling`. `make nixie` also
      green (all diagrams validated), run separately because the change touches
      Markdown. Logs under `/tmp/$GATE-use-cpython-for-pylint.out`.
- [x] PR coverage command reproduced locally against a faithful copy of the
      shared action's environment: 1273 passed, 1 skipped, exit 0, with
      `coverage.xml` reporting **90.81%** line coverage over the
      `episodic,alembic` production scope.

## CodeScene review round progress

- [x] Verified all findings against the current tree before editing; baseline
      `a59935f` recorded.
- [x] Duplication in `test_vidaimock_harness.py`: merged the two
      executable-missing tests into one parametrized test; `cs check` 9.38 →
      10.00, duplication cleared. CodeScene still warns `Complex Method
      (cc = 9)` at `vidaimock_harness.py:328`.
- [x] `_launch_server` extraction with the leaked-child fix; two new tests, each
      shown to fail when its guard is removed.
- [x] Three lint errors in the in-flight harness work fixed by their owning
      agent: `F401` unused import, `FBT001` boolean positional (parametrized on
      the environment value instead), `DOC502` `Raises: BaseException`.
- [x] `utils_config.py` test half: 8 new cases (4 `bool`, 2 `-inf`, 2
      boundary) plus an acceptance test; mutation-verified decisive; source
      file untouched.
- [x] `guest_bios_tei.py`: five locals replaced by the three shared helpers;
      one new error-path test added and mutation-verified; module 104 → 69
      lines.
- [x] `launcher_persistence.py`: rename applied at both sites.
- [x] `handlers.py`: required-field loop replaced by the existing helper.
- [x] `docs/execplans/use-cpython-for-pylint.md`: stale developer-documentation
      finding dispositioned with git evidence.
- [x] `scripts/check_vidaimock_isolated.py` complexity reduction:
      `_decode_response` holds the shared JSON/transport core, `_check_isolation`
      compares the sorted lists directly and now *rejects* a duplicated
      advertised ID, and `_verify_startup` returns the resolved path so `main`
      resolves the executable once. `cs check` 9.38 → **10.00**, mean radon 3.70
      → 2.67, `_check_isolation` 7 → 2. 19 new tests, including one that fails
      when the comparison is regressed to a set.
- [x] Deduplication fallout handled: making `guest_bios_tei.py` import the
      shared helpers made its import block byte-identical to
      `show_notes_enrichment.py`'s, which the duplication gate caught. Recorded
      as a reasoned exception via `make duplication-allow`, following the
      existing `_guest_bios_executor.py ~ _show_notes_executor.py` precedent
      rather than extracting a helper purely to cross the threshold.
- [x] `check-fmt` caught the table added by this very plan: `mdtablefix --wrap`
      re-aligns every column, so a handwritten table is a formatting defect
      even when it renders correctly. The change is whitespace-only and
      invisible to a `git diff` read, which is why the post-turn hook found it
      and review did not. Realigned with the Makefile's own `mdtablefix
      --in-place` flags and confirmed with `mdtablefix --check` (exit 0) and
      `ruff format --check` (601 already formatted). Lesson: a plan that
      records the hash of its own tree is self-defeating, since every edit
      changes the value it claims; record the *verification* instead.
- [x] `lint` then caught two `C0302 too-many-lines` violations (423 and 473
      lines against a ceiling of 400) that the new tests and the `_launch_server`
      helper had pushed both harness modules over. The ceiling is stated policy,
      `pyproject.toml` calls it "the project file-size ceiling enforced during
      review", and no file in the repository suppresses it, so the remedy was to
      split along real seams rather than disable the rule:
      `resolve_vidaimock_executable` moved to `tests/steps/vidaimock_executable.py`
      (it was the harness's only use of `os`, `shutil`, and `pytest`, so the
      harness no longer imports `pytest` at all) and the stand-in child builders
      moved to `tests/steps/vidaimock_harness_support.py`, following the
      `*_support.py` convention already used across `tests/steps/`. The harness
      re-exports `resolve_vidaimock_executable` so existing callers are
      unaffected. Result: 390 / 44 / 138 / 365 lines, pylint 10.00/10 with no
      C0302, and all 11 harness tests plus 19 script tests still pass.
- [x] Recorded the trap that the lint failure exposed: an earlier `scrutineer`
      run had reported `lint` as PASS while its own log showed the same two
      C0302 errors and `Error 16`. Reading the cited log rather than the summary
      is what settled it, so a gate report is only ever as good as the log
      behind it.
- [x] Code validation for the current follow-up: formatting, the full lint
      recipe, and typecheck passed after adding `PYLINT_JOBS`; the full test
      suite passed on the clean final rerun. One earlier rerun timed out under
      shared-machine load; the named test passed in isolation and the full suite
      passed afterwards.
- [x] Pinned VidaiMock 0.2.11 smoke test and PR coverage test run completed on
      the current code candidate.
- [x] The initial Python, provider-reader, and lifecycle changes are committed
      locally as
      `69775efedab0f56f9d6583c7b333beea5b696d7c`.
- [x] The Pylint worker-count update and the two additional positive-infinity
      cases passed their code gates, full tests, smoke, and coverage checks in
      commit `9f6f639b214f04186294b591d07531dd5e114612`.
- [x] Final documentation checks passed after this plan reconciliation:
      `make check-fmt`, `make markdownlint` using the locally installed
      `typos-config-builder` v0.1.1, and `make nixie`. The default uv fetch for
      that pinned builder remains intermittently unavailable through Lody.
- [ ] Push the local commits, verify workflow runs on the published head, and
      obtain a post-fix review. Publication is blocked by the offline Lody
      GitHub transport; the previous review invocation is recorded below and
      does not confirm resolution.

### CodeScene delta at `bf2acc8` (historical)

`cs delta origin/main --output-format json --pretty` now names **one** finding,
down from three. Both cleared findings are absent from the delta and both files
score 10.00:

| Finding                                                 | Baseline | Final                      |
| ------------------------------------------------------- | -------- | -------------------------- |
| Duplication, `test_vidaimock_harness.py`                | 9.38     | **10.00**, cleared         |
| Overall Code Complexity, `check_vidaimock_isolated.py`  | 9.38     | **10.00**, cleared         |
| Complex Method, `vidaimock_harness.py::start_vidaimock` | 9.68     | 9.68, **cc = 9 unchanged** |

The surviving warning is reported as a miss. It is a deliberate trade: the two
`except` clauses encode two different policies, and the alternative that would
lower the count — one clause guarded by a compound condition, or a predicate
helper — was declined because either makes the retryable and non-retryable
paths harder to tell apart for a diagnostic that blocks nothing.

## Defects found and fixed while clearing lint

- `RUF100` exposed a dead handler rather than a redundant suppression:
  `pytest.skip.Exception` and `pytest.fail.Exception` derive from
  `BaseException`, not `Exception`, so the smoke script's `except Exception`
  never caught them and a missing binary produced a traceback. Now caught by
  name, with the reason attached.
- `tests/steps/test_no_qa_generation_slice_support.py`'s `_Process` stand-in
  predated the consolidated teardown and lacked `poll()`, which the harness
  checks before terminating so an exited child is not waited on twice. The
  stand-in now models that interface.
- The smoke script derived configured provider names from the fixture YAML's
  *filename*; the server advertises the declared `name:` field. It now reads
  the declared name.
- `make typecheck` found five `ty 0.0.32` diagnostics that `make lint` could
  not. A bare `dict` narrowed from `object` by `isinstance` carries an
  uninhabited key type, so every lookup on it is rejected as expecting `Never`.
  `ty` scans untracked files, which is why the two new files were caught here
  and not before the lint gate. The repeated `isinstance` and `raise` blocks at
  five sites were replaced by one named helper,
  `_as_mapping(value, description) -> dict[str, object]`, which states the
  expectation once and narrows with the `typ.cast` idiom the repository already
  uses in `tests/test_helm_chart_contract.py`. Separately,
  `subprocess.Popen.args` is typed as a union admitting `bytes` and `PathLike`,
  so the harness test now casts it to `cabc.Sequence[str]` behind a documented
  assertion.

## Review round: CI green, then four verified defects fixed

CI is green on `f8e9487` and on the successor `5fbf87b`, with all 23 steps
executed and none skipped. The headline `Smoke-test vidaimock isolation` step
ran for the first time and passed on both, so the claim that the isolation
harness works in CI now rests on real CI evidence rather than on a step that
was skipped behind an earlier failure.

CodeRabbit returned `CHANGES_REQUESTED` against `b44ebb9` with eleven comments.
Four findings were reproduced before being fixed, each then verified against
its own failure mode (`ef122dc`):

- `ReferenceDocument.lock_version` accepted `True`, because
  `isinstance(..., int)` admits booleans while the shared
  `require_positive_integer` deliberately excludes them. The module's two
  optimistic-lock counters disagreed; both now share the helper.
- `ReferenceDocumentRevision` raised `AttributeError` rather than `TypeError`
  for a non-string `content_hash`, calling `.strip()` before checking the type.
  Now routed through `validate_non_empty_text`; a blank string still raises
  `ValueError`.
- `validate_llm_config` could mask its documented `ValueError`: a rejected
  numeric field was logged raw, and the logger's `json.dumps` raised
  `TypeError` first for a value such as `timeout_seconds=object()`. A new
  `_json_safe` passes JSON-encodable values through unchanged and falls back to
  `repr` only for the rest.
- `start_vidaimock` leaked the standard-error capture when `Popen` raised
  before a child existed, such as a non-executable binary.

At that review checkpoint, replacing the `isinstance` predicates with `match`
cases was declined. The later request against PR head `7439d26` superseded that
disposition; the current follow-up changes all five predicates to structural
`match` cases, with `bool` matched before numeric types.

The `_json_safe` fix is worth a note on method. The first attempt wrapped all
three fields in `repr` unconditionally, which would have silently changed the
logged types for ordinary mistyping. The snapshot in
`tests/__snapshots__/test_llm_openai_adapter_config.ambr` pins
`"max_attempts": 3` and `"timeout_seconds": 30.0` as numbers, so reading the
existing contract first is what kept the fix from becoming a schema change.

## Second rebase: onto main at `f1bdaca`, dropping the superseded Pylint commit

`main` advanced three commits, one of which — `ced3f90`, "Run Pylint on CPython
3.14 and lint every module (#346)" — is a **successor landing of this branch's
first commit**. It carries the same purpose (Pylint on CPython 3.14, with the
module splits that purpose forced) decomposed into 55 files at a finer
granularity, and its `Makefile` already sets `PYLINT_PYTHON ?= 3.14` with a
*more* precise pin (`pylint==4.0.9`, `--managed-python`) and no PyPy shim.

Replaying `e7e1f04` would therefore have reinstated an older decomposition
beside the newer one. It was excluded from the replay: `--onto f1bdaca e7e1f04`
replays only the five later commits. The instruction to "keep only the elements
of this PR that improve upon what is now present on main" is what this serves.

Three further reconciliation decisions:

- `5fbf87b` (the `typos.toml` regeneration) became empty: its output is
  byte-identical to `main`'s `typos.toml`, verified before skipping rather than
  assumed. Main absorbed the same 13 generated lines independently.
- `e7e1f04` also renamed each scenario's provider fixture to `openai.yaml`.
  That rename is **not load-bearing**: `scripts/check_vidaimock_isolated.py`'s
  own docstring records that a provider's `name` field, not its filename, is
  what `/v1/models` advertises, and a direct probe confirmed it — two fixtures
  differing only in filename both reported the declared `draft` provider. Each
  scenario also gets its own `--config-dir`, so no two providers share a
  directory and no collision was possible. Git's auto-merge kept main's
  descriptive names, and those were retained.
- `ef122dc`'s four fixes were retargeted rather than dropped. Main has no
  `domain_records.py` or `config_validation.py`, but it has the *defects* in
  its differently-named equivalents: `isinstance(self.lock_version, int)` still
  admits `True` in `domain_reference_documents.py`, `self.content_hash.strip()`
  still raises `AttributeError` before the type check, and `utils_config.py`
  still logs the three numeric fields raw. All three fixes were re-applied to
  main's files against main's own underscore-prefixed helper names, and each
  was verified against its exact failure mode. Main's `_json_safe` call site is
  sound because main's snapshot pins the same numeric log types
  (`"max_attempts": 3`, `"timeout_seconds": 30.0`) that pass-through preserves.

The four conflicts were all one shape: main retains the duplicated per-module
startup helpers, and the branch deletes them in favour of the shared harness.
Resolution took the branch side. This is provable rather than a judgement call:
`git diff OLD_BASE origin/main` is **empty** for all five files, so the target
side carried no change of its own and nothing main-side could be lost.

Audited afterwards: `range-diff` clean, `TARGET` an ancestor with no merges in
range, `git diff --check` clean, all 124 target-only paths byte-identical, and
the one deletion (`test_generation_orchestration_vidaimock.py`) is a file main
never touched whose two contracts are re-covered by the new harness's nine
tests. The 13 `e7e1f04`-only modules stay absent.

One element of `e7e1f04` was deliberately **not** carried forward. It derived a
Pylint worker count from `nproc` (`PYLINT_JOBS`, a tenth of the cores with a
floor of two) and ran the pass with `-j`. Main runs Pylint single-threaded
against a pinned `pylint==4.0.9`, and the worker heuristic is a statement about
this machine's topology rather than about the VidaiMock defect this branch
exists to fix. Reinstating it would widen the change beyond its purpose, so it
is recorded here as a decision rather than left as an unexplained omission.

The two special-case reconciliations are worth naming as a pattern. Where main
has already landed a *renamed* equivalent of a file this branch modified, the
right move is not to skip the commit but to retarget its change onto main's
file. Dropping `ef122dc` would have quietly reverted three real fixes, because
"the file is gone" and "the defect is gone" are different claims — and the
second can only be established by reading main's replacement.

### Publication at `bf2acc8` (historical)

The rebased series is `9f51222`, `bf5e1be`, `4c3b54b`, `1a97009`, `5fee061`,
`bf2acc8`.

All six gates are green on `bf2acc8`: `check-fmt` (exit 0, 122 Markdown files
unchanged), `lint` (exit 0, 67s, Pylint 10.00/10 on all three invocations),
`typecheck` (exit 0, `ty 0.0.32`), `test` (exit 0, 174s, 1507 passed, 1
skipped), `markdownlint` (exit 0, 7s, 123 files, 0 errors), and `nixie` (exit
0). `typos.toml` converged and was not rewritten.

The force-push was bound with `--force-with-lease` to the previously recorded
remote head `fdf4f31`, re-read by `git ls-remote` immediately beforehand rather
than refreshed blindly. The remote branch moved `fdf4f31` → `bf2acc8`, and the
pull request updated in place:

<https://github.com/leynos/episodic/pull/339>

Recovery refs for `OLD_HEAD`, `OLD_BASE`, and `TARGET` are retained, so the
pre-rebase history stays recoverable independently of the remote.

## CodeScene review round

`cs delta origin/main --output-format json --pretty` named exactly three
findings, and the review mapped them onto the first three work items. Every
finding was verified against the current tree before any edit.

**Code Duplication in `tests/steps/test_vidaimock_harness.py` — cleared.** The
two executable-missing tests differed only in the `CI` environment variable and
the exception type; the `match=` text and the call were byte-identical. They
are now one parametrized test over the environment value (`"1"` / `None`) with
distinct descriptive case IDs. Measured before and after with `cs check`: 9.38
→ 10.00, both duplication warnings gone. Decisive, not merely green: pointing
`resolve_vidaimock_executable`'s CI branch at `skip` turns the CI case into a
`SKIPPED` outcome rather than a pass, so the two cases remain discriminating.

**Complex Method in `tests/steps/vidaimock_harness.py` — not cleared.** The
extraction did happen: `_launch_server(launch) -> VidaiMockServer` now owns the
single-attempt acquisition (fresh port, fresh capture, `_start_once`, close the
capture and re-raise if no child was created) and returns the child, port,
label, and capture together. It does not decide whether to retry. `cs check`
confirms the finding is merely **relocated**, `292` → `328`, still `cc = 9`,
and the file's score is unchanged at 9.68. This is reported as a miss rather
than claimed as cleared: the extraction did not lower the count, because the
function still carries two handlers for two genuinely different policies — a
bind race that is retried with the attempt limit, and an unforeseen readiness
failure that must reap the child and re-raise unchanged. Collapsing those into
one clause guarded by a compound condition would satisfy the metric by making
the two policies harder to tell apart, which is the wrong trade for a
diagnostic-only gate.

The extraction did fix a real defect: only `VidaiMockStartupError` was caught
around `wait_for_port`, so any other exception leaked the child. Both that path
and the close-the-capture-on-`Popen`-failure path had zero coverage; both now
have a test that fails when its guard is removed.

**Current CodeScene delta on `69775ef` — open.** The refreshed
`cs delta origin/main --output-format json --pretty` reports
`_configured_provider_names` at cyclomatic complexity 13 (threshold 9) and a
module mean of 4.45 (threshold 4). It also reports the known `start_vidaimock`
complexity of 9 at its threshold. The provider-reader change keeps the
requested error boundary explicit; no production control flow was rewritten
solely to lower a score. These CodeScene findings remain separate
maintainability work and are not counted as resolved by the five review fixes.

Two findings from that review were initially dispositioned without a code
change. The `isinstance` disposition below was superseded by the current PR
follow-up:

- Replacing the five `isinstance` predicates in
  `episodic/llm/openai_api/utils_config.py` with `match` cases. At the earlier
  checkpoint, CodeScene reported no finding for that file and the suggestion
  was declined as unnecessary for single type predicates. The current request
  adopted it: all five validators now use structural matching, reject booleans
  before numeric cases, preserve finite checks and numeric bounds, and return
  `False` for unsupported types. Public configuration tests retain the boolean,
  non-finite, invalid-type, whitespace, and boundary cases.
- The developer-documentation finding. It describes
  `GenerationRunsResourceConfig`, a handler request DTO, and a
  generation-resource/error module split. Verified against git rather than
  accepted: `GenerationRunsResourceConfig` has **zero** matches anywhere in the
  tree, and `episodic/api/handlers.py` is **not** in this PR's diff. The text
  describes the decomposition of `e7e1f04`, the commit this branch deliberately
  dropped during the second rebase because `main`'s `ced3f90` landed a
  finer-grained decomposition of the same purpose. The finding is stale, not
  actionable, and re-documenting modules that do not exist would be worse than
  leaving it.

Three further items from the same review are independent of CodeScene:

- `_record_success_events_and_costs` → `_record_success_transition` in
  `episodic/generation/launcher_persistence.py`. Verified first that the old
  name had exactly two occurrences, both in its own module, and that the new
  name was unclaimed. `LauncherHost` does not declare the method, so no
  protocol surface changed. Unrelated `_record_success` methods elsewhere
  cannot collide.
- The five local TEI helpers in `episodic/generation/guest_bios_tei.py` were
  replaced by `body_blocks_payload`, `build_text_inline`, and `is_div_payload`
  from `episodic/generation/tei_payload.py`, with `"guest-bios"` passed to the
  predicate. The count matters: the task named three helpers, but the module
  held five, because `_require_payload_object` and `_require_payload_list` were
  used only by the local `_body_blocks_payload` and became dead once it was
  replaced. All seven call sites were in the one module. The `ValueError`
  messages are byte-identical, since `_format_type_error_message` builds the
  same `"TEI payload field {field} must be a {type}."` text; this was
  established by reading the shared helper, not inferred. The module went from
  104 to 69 lines.
- The required-field loop in `handle_create_entity` was replaced by
  `_require_payload_fields(payload, required_fields)`, matching the call
  `handle_update_entity` already made.

## Lessons

- Editing a document while a gate is running invalidates that gate for the
  candidate being judged. The first gate run after the typecheck fixes failed on
  `docs/execplans/use-cpython-for-pylint.md` alone, because the plan was
  written after the previous format pass. The gate runner correctly ruled out a
  mid-write race by mtime and checking the file hash twice, which is how the
  failure was attributed to the planner rather than to a flaky tool. Freeze the
  tree, then gate it.
- `mdtablefix` reflows prose but will not repair malformed Markdown: a nested
  inline code span, such as a quoted diagnostic inside one, survives a format
  pass and still reads as broken in a rendered page. Write those as plain text.
  Run `grep` for an odd number of backticks on a line before trusting a
  formatting pass to have produced valid Markdown.
- The rebase boundary was clean and uncontested because the branch was a single
  commit; `0740f26` was already an ancestor of `origin/main`.
- Both sides edited `docs/developers-guide.md` (branch: Pylint/CPython;
  target: coverage). Git's `zdiff3` merge kept both, in different regions; the
  audit confirmed no target-only path drifted.
- `stderr=subprocess.PIPE` would have blocked a noisy child on a full 64 KiB
  buffer and lost its diagnostics at exit; a `tempfile.TemporaryFile` avoids
  both. The bounded capture is applied when reading, not when writing, so the
  child is never restricted.
- A linter's "unused suppression" finding is worth reading before deleting the
  suppression: here it was the only signal that a handler was unreachable.
- The lint and typecheck gates have different file scopes in practice: `ty`
  checks untracked files that the Pylint passes also see, but the two report
  disjoint classes of defect. A green `make lint` is not evidence that
  `make typecheck` will pass, so both must run before a commit is claimed gated.
- The fix for the narrowed-`dict` diagnostic was worth confirming on a scratch
  file first. A three-case probe (`object` narrowed by `isinstance`, a typed
  `dict[str, object]`, and the `isinstance` + `cast` idiom) showed the first
  fails and both alternatives pass, which identified the mechanism before any
  repository file was edited. The same probe confirmed the `Popen.args` cast
  clears its four diagnostics.
- Reproducing the PR coverage step needs the *action's* environment, not just
  its command line. The composite action creates `.venv-coverage` inside the
  repository and syncs into it via `UV_PROJECT_ENVIRONMENT`; a hand-built venv
  elsewhere lacks the test dependencies and fails at collection. The
  `granian`-driven BDD scenario also skips unless `.venv-coverage/bin` is on
  `PATH`, so a bare invocation silently converts a real test into a skip.
- The coverage run failed twice under host contention: once with a single
  `pytest-timeout`, then with 297 errors at load average 18.6 on a 6-core
  machine. Both suspect suites passed in ~8s in isolation, and the identical
  command passed 1273/1273 once load fell to ~5. A timeout that changes shape
  between runs and vanishes in isolation is contention, not a regression — but
  it must be shown, not assumed.
- The `typos.toml` regeneration is a *latent* state, not a permanent property of
  the `spelling` gate. It rewrites the tracked file only while the committed
  bytes differ from the generated ones; once they agree the gate reproduces
  them and the tree converges clean. Gate runs after the rebase left
  `git status --porcelain` entirely empty. This is also why a
  `typos.toml`-regeneration commit can rebase to empty — `main` had absorbed
  the same generated lines — which is worth confirming by hash before skipping
  it as redundant.
- A refactor that satisfies a complexity metric is not the same as a refactor
  that improves the code. Extracting `_launch_server` was worth doing on its
  own merits — it fixed a leaked child and gave the single-attempt acquisition
  a name — but it did not reduce `start_vidaimock`'s count, because what
  remains is two exception handlers for two different policies. The honest
  report is that the finding did not clear, which the metric states plainly.
  Claiming otherwise would have required reading the count as "the function
  moved", which is not what it measures.
- A test that only asserts rejection is half a test. The rejection table in
  `test_llm_openai_adapter_config.py` would have passed unchanged if the
  validators had rejected every value, so the boundary work added an acceptance
  test alongside it. Mutation is what settled the question: 8 cases failed when
  their guards were removed, and the boundary cases failed when the comparison
  was tightened. Note also that a single-line guard and its multi-line
  equivalent need different mutation patterns — the first attempt at removing
  the `bool` guards matched only three of the four and would have understated
  the coverage.
- `ty` scans untracked files, which is how a new test file's diagnostics
  surface in `make typecheck` before `make lint` would report them. Scoping a
  `ty` run to the files being changed is worth doing before handing the tree to
  the gate runner, because it reports classes of defect that `ruff` does not.
- The duplication gate's allow entries key on symbol locations, so a
  deduplication can orphan one — but it does not follow that it did. The entry
  naming `tei_payload.py::require_payload_object` and `::require_payload_list`
  survives this change precisely because the shared `body_blocks_payload` still
  calls both; they were only orphaned from the *guest-bios* module's copy.
  Stale entries print a warning rather than failing the gate, which makes
  checking cheaper than guessing.

## Current follow-up evidence — 2026-09-30

The review baseline supplied for this follow-up was
`7439d269ece932b209cb3bc3755e60e3b88a3977`; GitHub still reports that as the
head of pull request 339. The source at that commit was checked before editing:
the five requested validators still used `isinstance`. The implementation
commits are `69775efedab0f56f9d6583c7b333beea5b696d7c`
(`Address outstanding PR review findings`) and
`9f6f639b214f04186294b591d07531dd5e114612`
(`Bound Pylint workers and test finite values`). Both are local; the branch
tracks `origin/use-cpython-for-pylint`.

1. **Direct domain-model regressions — addressed in code.**
   `tests/test_reference_document_models.py` now constructs the dataclasses
   with invalid `lock_version` and `content_hash` inputs, checks the requested
   exact exceptions and messages, accepts positive versions and a non-empty
   hash, and constructs the default version without passing that field. Focused
   tests passed.
2. **OpenAI rejection logging — addressed in code.**
   The public configuration tests exercise `object()` for each rejected numeric
   field and a circular list that makes `json.dumps` raise `ValueError`. They
   parse the real log JSON and assert event, field, and `repr` fallback.
   Existing JSON-type snapshots and numeric boundaries remain in place. Focused
   tests passed.
3. **VidaiMock provider reader — addressed in code.**
   `os.scandir` exposes provider-directory discovery errors; provider reads
   translate filesystem, UTF-8, and YAML failures to `SmokeTestError` with the
   relevant path and original cause. Sorted `*.yaml` selection is retained.
   Tests cover discovery/read failures, malformed and non-mapping YAML, missing
   names, empty directories, and sorted names. The orchestration fixture writes
   `openai.yaml` and declares `orchestration`.
4. **VidaiMock lifecycle model — addressed in code.**
   The bounded Hypothesis test drives the actual retry and cleanup logic with
   process and capture doubles, covers explicit terminal and retry examples,
   and checks cleanup, retry limits, diagnostics, and unexpected exception
   identity. Existing real-child tests remain. The focused selection passed 110
   tests; the full suite passed 1,574 tests with 1 skipped and 50 snapshots.
5. **Plan and final validation — locally complete; publication open.**
   This section reconciles the local implementation, gates, CI, review, and
   remaining publication work. Local gates, pinned smoke, and PR coverage are
   recorded below. Current-head CI and post-fix review confirmation still need
   publication of the validated branch.

Local evidence for commits `69775ef` and `9f6f639`:

- `make check-fmt` passed; 605 Python files were already formatted and the
  Markdown table check passed
  (`/tmp/check-fmt-76ca8268-d606-4699-97a2-0a33c4262211-docs-final6.out`).
- `PYLINT_JOBS` now defaults to one tenth of `nproc`, with a floor of two, and
  is passed to the built-in and both df12 Pylint invocations. On this runner
  `make -n lint` showed `--jobs=2` on all three commands, each using Python
  3.14. `mbake validate Makefile` passed.
- `make check-fmt`, `make lint`, and `make typecheck` passed on the updated
  Makefile. The final lint log confirms all three Pylint passes used `--jobs=2`
  and scored 10.00/10; Hecate, Ruff, `ambrleaks`, Skylos, and the duplication
  gate also passed
  (`/tmp/lint-76ca8268-d606-4699-97a2-0a33c4262211-use-cpython-for-pylint-final4.out`).
- `make test` passed once after the two additional positive-infinity cases:
  1,576 passed, 1 skipped, and 50 snapshots passed
  (`/tmp/test-76ca8268-d606-4699-97a2-0a33c4262211-use-cpython-for-pylint-final3.out`).
  A subsequent run after the Makefile change exited 2 after 389 seconds, with
  1,575 passed, 1 skipped, and one 180-second timeout while setting up
  `test_create_app_from_env_wires_database_readiness_probe[plain_postgresql_url]`
  (`/tmp/test-76ca8268-d606-4699-97a2-0a33c4262211-use-cpython-for-pylint-final4.out`).
  At the time, other repository tests were active and the host load average
  exceeded 27; this is consistent with contention but does not establish the
  timeout's cause. The failing case then passed alone in 5.52 seconds, and the
  final `make test` rerun passed: 1,576 passed, 1 skipped, and 50 snapshots
  (`/tmp/test-76ca8268-d606-4699-97a2-0a33c4262211-use-cpython-for-pylint-timeout-fix.out`).
- The latest default `make markdownlint` attempt stopped during its pinned
  builder fetch
  (`/tmp/markdownlint-76ca8268-d606-4699-97a2-0a33c4262211-docs-final2.out`).
  The repository target then passed using the already-installed
  `typos-config-builder` v0.1.1 executable, whose direct URL records commit
  `b2bc36bee84fbe9b958ab64bd4581377ddd60c72`; all 123 Markdown files had zero
  lint errors
  (`/tmp/markdownlint-76ca8268-d606-4699-97a2-0a33c4262211-docs-final6.out`).
  Targeted spelling checks for the changed guides also passed. The local
  Markdown executable independently reported zero errors on 123 files
  (`/tmp/markdownlint-cli2-76ca8268-d606-4699-97a2-0a33c4262211-local-fallback.out`).
- `make nixie` passed after the current plan update; all diagrams validated
  (`/tmp/nixie-76ca8268-d606-4699-97a2-0a33c4262211-docs-final6.out`).
- The pinned smoke test passed using VidaiMock 0.2.11 with the CI SHA-256
  `888d40195438491534a7a669776e06977367da62beb57feac8fa1a1f08faa93b`
  (`/tmp/vidaimock-smoke-final-76ca8268-d606-4699-97a2-0a33c4262211.out`).
- The workflow-matched coverage invocation on the current test tree passed
  1,575 tests with 2 skips and 50 snapshots. Slipcover reported 90.57% line
  coverage for `episodic,alembic` (17,009 of 18,780 lines)
  (`/tmp/pr-coverage-run-final-pylint-jobs-76ca8268-d606-4699-97a2-0a33c4262211.out`).
  The skips were the optional Granian and Docker smoke tests. No local PR
  baseline cache was available, so the ratchet comparison is not claimed as
  verified.

Hosted evidence is older than the local follow-up. CI run
[36418797888](https://github.com/leynos/episodic/actions/runs/36418797888)
completed successfully on the baseline commit `7439d269`; it is not CI evidence
for either local commit. GitHub's current PR metadata still reports head
`7439d269ece932b209cb3bc3755e60e3b88a3977`. CodeRabbit's completed invocation
on that baseline is recorded at
[the PR review comment](https://github.com/leynos/episodic/pull/339#issuecomment-5760687503).
It reported five findings and said its automatic review was paused after three
errors and two warnings. That invocation does not confirm the fixes are
resolved, and no post-fix review has completed.

The branch has not been pushed. The latest `git push` attempt failed before a
GitHub operation with `Cannot verify GitHub identity preferences with Lody` and
`remote helper 'lody-github' aborted session`; the push log is
`/tmp/git-push-final-76ca8268-d606-4699-97a2-0a33c4262211.out`. The session
machine reported online before this retry, but the identity check still failed.
GitHub still reports the PR head as the baseline. Current-head CI and post-fix
review confirmation remain open until the Lody GitHub transport can publish the
local commits.
