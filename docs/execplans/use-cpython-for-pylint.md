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

One suggestion was declined: replacing the `isinstance` predicates with `match`
cases. The cited guidance is about verbose if-elif chains and switch
statements, not single type predicates, and the repository uses `isinstance` in
54 files against `match` in 18.

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

### Publication

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
