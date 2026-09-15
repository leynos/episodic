# ADR-021: Adopt nose code-duplication gate

- Status: Accepted
- Date: 2026-08-28
- Deciders: Episodic maintainers

## Context and decision

In the context of keeping copy-paste duplication out of Episodic, facing a
benchmarked tie on Types 1-3 between nose 0.20.0 and the incumbent PyChase
0.1.0 — with nose byte-identical across repeated runs and roughly fifty times
faster on `episodic/` (89 ms against 4.8 s), while PyChase needs a Python 3.13
interpreter pin and a fixed `PYTHONHASHSEED` to keep its locality-sensitive
hashing stable — the decision is to run nose 0.20.0 behind
`scripts/duplication_gate.py` in `make lint`, installed by `make install-nose`
through `cargo-binstall` at a version pinned identically in the Makefile, the
CI workflow, and `[tool.nose]` and asserted by
`tests/test_toolchain_contract.py`, with reasoned location-keyed exceptions in
`[tool.duplication_gate]`, and against retaining PyChase, adopting pyscn's
Type-4 clone analysis even behind an allowlist, or replacing the reasoned
pyproject entries with nose's native baseline and ignore files, to achieve
deterministic duplication enforcement that costs milliseconds rather than
seconds and whose exceptions stay reviewable in version control, accepting that
the gate depends on a pre-1.0, platform-specific binary published through
GitHub releases, that nose reports spans without qualified unit names so allow
keys are path globs with an optional `::name` suffix, and that ranked-surface
gating adjudicates the top 30 families rather than every reported one.

This supersedes ADR-020, whose 2026-08-27 addendum recorded nose as evaluated
and not adopted. The reversal is deliberate: no new detection evidence emerged,
and speed and determinism decided a tie that the earlier addendum resolved in
favour of the incumbent.

## Consequences

- `make lint` and the standalone `make duplication` target depend on
  `make install-nose`, which installs `nose-cli` at `NOSE_VERSION` into
  `.tools/nose` using `cargo-binstall`'s git mode against
  <https://github.com/corca-ai/nose>, because the crate is not published on
  crates.io and binstall must resolve the GitHub release artefact instead. The
  target is a no-op when the installed binary already reports the pinned
  version, and CI caches `.tools/nose` on a key carrying the runner operating
  system and that version.
- The gate resolves `NOSE_BIN` (or the repository-local binary, or one on
  `PATH`), refuses to run when `nose --version` differs from
  `[tool.nose] version`, and directs the maintainer to `make install-nose`, so
  a drifted local install cannot quietly change what blocks the build.
- `[tool.nose]` pins the scan: roots `episodic` and `openai_test_types.py`, the
  three detection channels as `mode = "syntax,semantic,near"`, a floor of 24
  intermediate-language (IL) tokens, `surface = "all"` so families nose keeps
  off its dashboard are still adjudicated, and `top = 30` ranked families.
  Pinning the channels explicitly keeps a change to nose's defaults from
  widening or narrowing the gate silently.
- nose's exact-equivalence semantic channel is one of the blocking channels, so
  a narrow, witness-backed subset of semantic duplication is now machine
  checked. Type-4 duplication in general remains a human review concern,
  because that subset covers alpha-renaming and loop-to-comprehension rewrites
  but not, for example, a loop against a `sum()` fold.
- Findings print as `path:start-end ~ path:start-end` families, with the unit
  name appended for each location nose named, alongside the witness kind and
  refactoring value that ordered the family.
- Exceptions key on locations rather than line spans, which churn whenever code
  above them moves. A key is a path glob matched with
  `PurePosixPath.full_match`, optionally suffixed `::name` to require nose's
  unit name. An entry names one key (`unit`) or several (`members`) and
  silences a family only when every location in it matches one of the entry's
  keys, so a new copy in an unlisted file still blocks. Entries that cover no
  finding are reported as stale.
- The declarative-module exclusions ADR-020 kept in `[tool.pychase]` become
  ordinary reasoned allow entries, so what used to be a wholesale exclusion is
  now reviewable and stale-checked like every other exception.
- Re-adjudicating every family nose reports left 23 allow entries: five re-keyed
  from the PyChase list, 20 dropped because the duplication is no longer
  reported, and 18 added. One genuinely triplicated state guard was extracted
  into `_require_request_and_planner()` in
  `episodic/orchestration/_graph_state.py` rather than allow-listed.

## Rejected alternatives

- **Retaining PyChase 0.1.0.** It matches nose on Types 1-3 and reports
  qualified unit names, but it costs a separate Python 3.13 environment, a
  `PYTHONHASHSEED` pin for reproducible LSH bucketing, and a scan two orders of
  magnitude slower on `episodic/`. Naming is the only capability lost by the
  switch, and location keys recover most of it.
- **pyscn Type-4 enforcement, even behind an allowlist.** At Episodic scale
  pyscn's semantic lane reported 692 Type-4 pairs at permissive settings, and
  18 at gate strength that adjudication found to be intentional idiom
  parallels. Its ranking is inverted where it matters: the corpus's only true
  Type-4 pair scored 0.77, below control pairs scoring 0.93, so no threshold
  admits the true clone while excluding the false parallels.
- **nose's native baseline and ignore files.** A baseline records what was
  duplicated, not why it may stay. Reasoned entries in
  `[tool.duplication_gate]` keep every exception attached to a justification,
  reviewable in a diff, and removable when the gate reports it stale.

## Accepted trade-offs

- The gate depends on a pre-1.0 tool distributed as a platform-specific binary
  from GitHub releases rather than as a Python package, so provisioning needs
  `cargo-binstall` and a cached `.tools/nose` in CI.
- nose reports spans without qualified unit names, so allow keys are path
  globs with optional unit names rather than `path::qualname` pairs. A
  fragment-level finding such as a shared import block carries no name at all,
  and `::name` keys never match it.
- Gating on the top 30 ranked families bounds what the gate adjudicates.
  Duplication valuable enough to enter that ranking blocks the build;
  duplication below it does not, and the bound must be revisited if the ranked
  surface stays saturated.
- The benchmark corpus, tuning tables, and adjudication evidence behind the
  tool choice remain under `benchmarks/duplication/` and are summarized in
  [the duplication head-to-head](../pychase-pyscn-duplication-head-to-head.md).
