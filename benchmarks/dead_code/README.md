# Dead-code detector benchmark

This directory contains the reusable, tool-neutral corpus and normalizer for
the pyscn and Skylos comparison. It is development evidence, not part of the
Episodic application or its test fixtures.

`corpus/` is a deliberately small Python project. Its own `pyproject.toml`
bounds project-root discovery without configuring either detector. The source
contains intentional unused and unreachable code, so each corpus module uses a
file-level Ruff suppression to keep repository lint separate from benchmark
ground truth.

`expectations.json` is the oracle. Each entry labels one source location before
scanner output is considered, assigns it to either the `unused-symbol` or
`unreachable-statement` lane, and explains why Python semantics make it live or
dead. Add a new label only when its liveness can be decided without trusting a
scanner. Do not change a label merely to make a detector result pass.

The `score.py` module is intentionally specific to the two released JSON
schemas captured by this comparison. Reuse it for reruns of this corpus; add a
separate parser when evaluating a different detector rather than disguising
schema differences inside an existing parser.

`results/` retains the tool output, wall-clock metadata, normalized scores, and
repository-scan adjudication from 2026-07-27. The large repository reports are
compressed with deterministic gzip metadata; their SHA-256 digests are in
`production-adjudication.json`. Absolute checkout prefixes in the Skylos report
were replaced by `./` before compression, so the retained evidence does not
depend on one workstation path. Finding content was otherwise unchanged.

Run the corpus commands from `benchmarks/dead_code/corpus/`:

```bash
uvx pyscn@1.28.0 analyze --select deadcode --min-severity info --json .
uvx skylos@4.30.0 . --no-upload --no-provenance --confidence 0 --no-grep-verify --format json
```

Run the practical comparison from the repository root:

```bash
uvx pyscn@1.28.0 analyze --select deadcode --min-severity info --json episodic
uvx skylos@4.30.0 episodic --no-upload --no-provenance --confidence 0 --no-grep-verify --format json
```

The elapsed times are single wall-clock observations, not performance
benchmarks. They are retained to expose order-of-magnitude differences only.
