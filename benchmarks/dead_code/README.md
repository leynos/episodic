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
