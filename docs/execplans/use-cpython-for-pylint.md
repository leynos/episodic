# VidaiMock release/CLI mismatch: upgrade the pin and consolidate startup logic

Branch: `use-cpython-for-pylint` PR:
<https://github.com/leynos/episodic/pull/339> Baseline commit before this work:
`e7e1f04` (post-rebase head)

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
| Unrecognised argument | 2    | `error: unexpected argument '--not-a-flag' found`                                        |
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
      compatibility; characterised failure signatures.
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
