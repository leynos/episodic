# ADR-020: Adopt PyChase code-duplication gate

- Status: Superseded by
  [ADR-021](adr-021-adopt-nose-duplication-gate.md)
- Date: 2026-08-22
- Deciders: Episodic maintainers

## Context and decision

In the context of keeping copy-paste duplication out of Episodic, facing the
benchmark result that PyChase 0.1.0 detects Type 1-3 clones with perfect corpus
precision while pyscn 1.29.1 cannot separate true semantic clones from false
ones, the decision is to use a local, blocking PyChase scan driven by
`scripts/duplication_gate.py` in `make lint`, with tuned thresholds and
documented declarative-module exclusions in `[tool.pychase]`, and reasoned unit
or pair exceptions in `[tool.duplication_gate]`, and against an advisory-only
report, pyscn's clone analysis, semantic (Type-4) enforcement, inline pragma
suppression, or unexplained baselines, to achieve deterministic duplication
enforcement whose exceptions remain reviewable in version control, accepting
that the gate pins Python 3.13 and a fixed `PYTHONHASHSEED` for the detector's
sake, that declarative modules are excluded wholesale rather than per finding,
and that semantic duplication remains a human review concern.

## Consequences

- `make lint` (and the standalone `make duplication` target) runs the gate
  and fails while unsuppressed duplicate pairs remain, printing
  `path:lines ~ path:lines` findings with qualified unit names that feed
  directly into refactoring work.
- Contributors extract the shared logic, or record a considered exception
  with `make duplication-allow FIRST=... [SECOND=...] REASON=...`; the target
  rejects missing keys or reasons, and the gate reports entries whose
  duplication has been resolved as stale so they get removed.
- Storage record models, record/domain mappers, repository protocols, and
  typed request/response modules are excluded by documented patterns because
  identifier normalization makes such declarations structurally identical
  without any copy-paste.
- The benchmark corpus, tuning tables, and production adjudication that
  justify the tool choice and thresholds are retained under
  `benchmarks/duplication/` and summarized in
  [the duplication head-to-head](../pychase-pyscn-duplication-head-to-head.md).

## Addendum: nose 0.20.0 evaluated and not adopted (2026-08-27)

The nose semantic clone detector was benchmarked against the same corpus as a
candidate replacement for PyChase on Types 1-3 and as a Type-4 detector where
pyscn had failed. At tuned near-channel settings it tied PyChase's perfect
syntactic precision and recall, but its exact-equivalence semantic channel
reported no Type-4 clone in any swept configuration, and its findings carry
spans without the qualified unit names this gate's allowlist keys on. The
decision stands: PyChase remains the blocking detector, no tool enforces
Type-4, and nose is the first candidate to revisit if PyChase's interpreter and
hash-seed pins become untenable. Evidence is retained under
`benchmarks/duplication/results/` (`nose-0.20.0*.json`,
`tuning-nose-0.20.0.json`) and summarized in the head-to-head's nose follow-up
section.

This verdict was reversed the next day on speed and determinism grounds; see
[ADR-021](adr-021-adopt-nose-duplication-gate.md) (2026-08-28), which
supersedes this record.
