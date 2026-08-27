# Code-duplication detector benchmark

This directory contains the reusable, tool-neutral corpus and normalizer for
the PyChase and pyscn clone-detection comparison, and for the follow-up nose
evaluation. It is development evidence, not part of the Episodic application or
its test fixtures.

`corpus/` is a deliberately small Python project. Its own `pyproject.toml`
bounds project-root discovery without configuring either detector. The
`pricing` module holds original routines; `reporting` clones them as labelled
Type-1 to Type-4 duplicates; `controls` holds structurally similar but
semantically distinct false-positive bait.

`expectations.json` is the oracle. Each entry labels one pair of source units
before detector output is considered, assigns it to either the
`syntactic-clone` (Types 1-3) or `semantic-clone` (Type 4) lane, and explains
why merging the pair would or would not be a defensible refactor. Add a new
label only when its clone status can be decided without trusting a detector. Do
not change a label merely to make a detector result pass.

The `score.py` module is intentionally specific to the released JSON schemas
captured by this comparison (pyscn, PyChase, and nose query-JSON v9). Reuse it
for reruns of this corpus; add a separate parser when evaluating a different
detector rather than disguising schema differences inside an existing parser.
The nose parser expands each reported duplication family into its unordered
member pairs before scoring.

`configs/` holds the permissive pyscn capability settings. `results/` retains
the tool output, normalized scores, generational tuning tables, and the
production-scan adjudication from 2026-08-22, plus the nose 0.20.0 follow-up
runs and sweep from 2026-08-27. The large production report is compressed with
deterministic gzip metadata; its SHA-256 digest is recorded in
`production-adjudication.json`.

Run the corpus commands from `benchmarks/duplication/corpus/`:

```bash
uvx pyscn@1.29.1 analyze --select clones --json -c ../configs/pyscn-permissive.toml .
PYTHONHASHSEED=0 uvx pychase@0.1.0 --json --threshold 0.6 --min-lines 5 --min-nodes 10 .
```

nose is a platform-specific binary, not a Python package; the follow-up used
`nose-cli-x86_64-unknown-linux-gnu.tar.xz` from the tagged v0.20.0 GitHub
release. The retained corpus runs are the permissive default-channel scan and
the tuned near-channel scan, both over all reported surfaces:

```bash
nose query . all --format json --min-size 1
nose query . all --format json --min-size 1 --mode near:0.7
```

The nose production run was `nose query episodic all --format json` from the
repository root.

Run the production comparison from the repository root:

```bash
PYTHONHASHSEED=0 uvx pychase@0.1.0 --json --threshold 0.9 --min-lines 13 --min-nodes 50 episodic
```

`PYTHONHASHSEED` must be pinned for repository-scale PyChase runs: above 200
units it buckets MinHash signatures with the built-in `hash()`, so an unpinned
seed makes near-threshold findings flicker between runs.

The elapsed times recorded in `results/scores.json` are single wall-clock
observations, not performance benchmarks. They are retained to expose
order-of-magnitude differences only.
