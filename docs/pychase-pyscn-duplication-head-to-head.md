# PyChase and pyscn code-duplication head-to-head

## Outcome

On the labelled corpus PyChase 0.1.0 reported every syntactic clone with no
false positives and no unlabelled noise, and its unit-level findings carry
qualified names that feed directly into remediation. pyscn 1.29.1 matched
PyChase's syntactic recall and was the only tool to detect the Type-4 semantic
clone, but it could not do so without also reporting a false positive, and its
similarity scores compress into a narrow band that offers no threshold
separating the two.

No tool measured here detects semantically equivalent code reliably. The
duplication gate therefore targets copy-paste duplication (Types 1-3) and
treats semantic duplication, beyond nose's narrow exact-equivalence witness, as
a review concern rather than a machine-checked one.

A follow-up evaluation of nose 0.20.0 on 2026-08-27 (see
[the nose follow-up](#follow-up-nose-0200)) tied PyChase's perfect syntactic
score and detected no Type-4 clone in any configuration. On 2026-08-28 the
maintainers nevertheless moved the gate to nose on speed and determinism
grounds; see [ADR-019](adr/adr-019-adopt-nose-duplication-gate.md). The tables
and history below record the comparison as measured, not the current tool
choice.

## What each project means by duplication

The [pyscn repository](https://github.com/ludo-technologies/pyscn) implements
Type 1-4 clone detection using APTED tree edit distance over parsed functions,
with per-type thresholds, optional data-flow analysis for Type-4 findings, and
locality-sensitive-hashing (LSH) acceleration.

The [PyChase repository](https://github.com/Mayne-X/PyChase) implements Type
1-3 detection by normalizing the abstract syntax tree (replacing identifiers
and literals with placeholders), shingling the normalized node sequence, and
scoring candidate pairs by Jaccard similarity, with MinHash and LSH above 200
units.

Those contracts overlap but are not the same, so the comparison scores separate
`syntactic-clone` (Types 1-3) and `semantic-clone` (Type 4) lanes. A single
blended score would punish PyChase for a capability it does not claim.

## Method

The comparison was run on 2026-08-22 using the released packages pyscn 1.29.1
and PyChase 0.1.0, both through `uvx` without becoming project dependencies.

The checked-in corpus labels ten unit pairs fixed before either scan:

- five clone pairs: one Type-1 copy, one Type-2 rename, one Type-3
  modification, one Type-4 semantic rewrite, and one Type-2 method clone across
  two classes.
- five non-clone controls: parser, builder, and scanner pairs that share only
  idiomatic structure, plus two numeric folds whose merging would conflate
  distinct semantics.

Both tools ran at permissive capability settings (all clone types enabled,
minimum sizes below every corpus unit) so the corpus measures detection ability
rather than configuration taste. Findings were matched to labels by unordered
span overlap. Unlabelled findings were preserved separately instead of being
converted into false positives after the fact. The raw reports, oracle,
normalizer, and normalized counts are under `benchmarks/duplication/`.

## Labelled corpus results

| Tool          | Lane            | TP  | FP  | FN  | TN  | Unmatched | Precision   | Recall | F1          |
| ------------- | --------------- | --: | --: | --: | --: | --------: | ----------: | -----: | ----------: |
| PyChase 0.1.0 | Syntactic clone | 4   | 0   | 0   | 3   | 0         | 100.0%      | 100.0% | 100.0%      |
| pyscn 1.29.1  | Syntactic clone | 4   | 1   | 0   | 2   | 0         | 80.0%       | 100.0% | 88.9%       |
| PyChase 0.1.0 | Semantic clone  | 0   | 0   | 1   | 2   | 0         | Not defined | 0.0%   | Not defined |
| pyscn 1.29.1  | Semantic clone  | 1   | 0   | 0   | 2   | 14        | 100.0%      | 100.0% | 100.0%      |

*Table 1: Confusion matrices for the pre-labelled corpus at permissive
settings.*

The pyscn semantic-lane row needs qualification. pyscn found the true Type-4
pair at similarity 0.77, but it scored the `longest_valid_streak` and
`count_state_changes` control pair — two different algorithms — at 0.93, and
emitted fourteen unlabelled cross-pairs between unrelated corpus functions at
0.73-0.81. No threshold accepts the true semantic clone while rejecting the
false one because the false positive scores higher. PyChase assigned the
renamed Type-2 clones similarity 1.0 and reported no control pair at any
threshold down to 0.6.

pyscn's similarity band is also compressed: near-identical code rarely scores
above 0.85 unless it is byte-identical, so the usable strict range collapses to
a single step between 0.8 and exact match.

The same behaviour scales badly on production code. Run over `episodic/` on
2026-08-28, pyscn's semantic lane reported 692 Type-4 pairs at permissive
settings; tightened to gate strength it still reported 18, every one of which
adjudication found to be an intentional idiom parallel rather than a semantic
clone (both raw reports and their run configurations are retained under
`benchmarks/duplication/results/` beside the adjudicated summary
`pyscn-1.29.1-episodic-type4.json`). Combined with the ranking inversion on the
corpus — the true Type-4 pair at 0.77 beneath control pairs at 0.93 — no
threshold keeps the true positives while rejecting the parallels, so Type-4
enforcement through pyscn stays rejected even with an allowlist absorbing the
known parallels.

## Configuration tuning

Configurations were tuned generationally against the corpus oracle, with the
production scan as the second-generation fitness signal; the score tables are
retained under `benchmarks/duplication/results/`.

- Generation 1 swept 60 pyscn and 189 PyChase configurations against the
  corpus. Both plateaued at F1 0.889 over all ten labels (perfect precision,
  Type-4 unreachable without loss). PyChase held that plateau across the whole
  swept threshold range at or below 0.75 and every size floor, while pyscn's
  best region required disabling Type-4 entirely.
- Generation 2 ran the plateau configurations over `episodic/`:
  63-842 raw findings depending on size floors, dominated by declarative code.
- Generation 3 swept stricter gate candidates and selected threshold 0.9,
  minimum 13 source lines, and minimum 50 normalized AST nodes, which kept
  every corpus syntactic clone of gate-relevant size while reducing the
  production scan to 84 candidates.

## Episodic production scan and adjudication

Every candidate from the selected configuration was adjudicated by reading both
members
([the production adjudication report](results/production-adjudication.json)):

| Disposition                | Count | Interpretation                                                              |
| -------------------------- | ----: | --------------------------------------------------------------------------- |
| Declarative-module pairs   | 53    | Records, mappers, protocols, and typed request modules; excluded by pattern |
| Genuine copy-paste (fixed) | 4     | The duplicated `_validate_async_callable` helper and the `log_*` triple     |
| Allowlisted with reasons   | 27    | Parallel structure adjudicated as intentional; recorded in `pyproject.toml` |

*Table 2: Adjudication of the 84 production candidates at gate settings.*

The declarative cluster is the dominant false-positive mode for
normalization-based detection: once identifiers and literals become
placeholders, any two SQLAlchemy record classes, msgspec request types,
repository protocols, or field-by-field mappers look identical. The gate
excludes those module patterns with documented reasons rather than allowlisting
dozens of pairs individually.

## Operational caveats

- PyChase 0.1.0 imports `ast.Str` and related aliases that Python 3.14
  removed, so the gate pins Python 3.13 for its own environment.
- Above 200 scanned units PyChase buckets MinHash signatures with the
  built-in `hash()`. Unless `PYTHONHASHSEED` is pinned, near-threshold findings
  appear and disappear between runs; the gate re-executes itself with a fixed
  seed. Even pinned, LSH candidate recall near the threshold is probabilistic
  by construction (roughly 96% at similarity 0.9 with the default banding),
  while exact structural matches are always caught.
- PyChase's advertised `# pychase: ignore` pragma is actually spelled
  `# dry4python: ignore` in 0.1.0 and applies only to functions, not classes.
  The gate therefore implements suppression itself through reviewable allow
  entries instead of relying on pragmas.
- `pyscn check` treats clones as warnings only, and its clone findings carry
  spans without unit names, so a blocking gate would need report
  post-processing under either tool.

## Follow-up: nose 0.20.0

[nose](https://github.com/corca-ai/nose) was evaluated on 2026-08-27 as a
candidate replacement for PyChase (Types 1-3) and as a candidate Type-4
detector where pyscn had failed. nose is a pre-1.0 Rust binary that lowers
source into a normalized intermediate language (IL) and reports duplication
families through three channels: `syntax` (token-level copies), `semantic`
(exact IL value-graph equivalence, witness `exact`), and `near` (fuzzy
similarity with a configurable threshold). The released
`nose-cli-x86_64-unknown-linux-gnu` 0.20.0 binary ran against the same corpus
oracle through `parse_nose_pairs`, which expands each reported family into its
unordered member pairs. The sweep table is retained in
`benchmarks/duplication/results/tuning-nose-0.20.0.json` alongside the raw
reports.

| Configuration                    | Lane            | TP  | FP  | FN  | TN  | Unmatched | Precision   | Recall | F1          |
| -------------------------------- | --------------- | --: | --: | --: | --: | --------: | ----------: | -----: | ----------: |
| Default channels, `--min-size 1` | Syntactic clone | 3   | 0   | 1   | 3   | 2         | 100.0%      | 75.0%  | 85.7%       |
| `--mode near:0.7 --min-size 1`   | Syntactic clone | 4   | 0   | 0   | 3   | 0         | 100.0%      | 100.0% | 100.0%      |
| Every swept configuration        | Semantic clone  | 0   | 0   | 1   | 2   | 0         | Not defined | 0.0%   | Not defined |

*Table 3: nose 0.20.0 corpus scores over all reported surfaces.*

Three observations qualify the table:

- The default syntax channel merges the adjacent Type-1 and Type-2 function
  pairs into one block-level copy-paste family (`reporting.py:5-64` against
  `pricing.py:5-62`), which pair-level scoring credits to the Type-1 label and
  counts the Type-2 label as missed. The near channel reports function-level
  pairs instead, and every swept near threshold from 0.5 to 0.9 restores the
  perfect syntactic score with no false positives.
- The semantic channel never reported the Type-4 pair. Probes show why: it
  converges alpha-renamed structure and a bare loop against its list
  comprehension (both witness `exact`), but declines a loop against a `sum()`
  fold, `if`/`else` against a ternary, and De Morgan rewrites. The corpus
  Type-4 pair additionally needs loop-fission reasoning (a one-pass
  two-accumulator loop against two comprehension passes), which is outside the
  modelled subset. Its coverage report shows zero unlowered IL nodes on the
  corpus, so the miss is a modelling limit, not a parsing gap.
- Against pyscn on Type 4, the comparison inverts: pyscn found the true
  semantic pair but ranked a false pair above it, while nose reports nothing at
  all — perfect precision with zero recall. Neither behaviour supports a
  machine-checked Type-4 gate, though nose's refusal to guess makes it the
  safer advisory signal.

Operationally, nose is attractive: three consecutive corpus runs were
byte-identical with no hash-seed pinning, and it scanned the corpus in 12 ms and
`episodic/` in 89 ms against PyChase's 4.8 s. An all-surface production scan
reported 30 families — 24 copy-paste (import blocks and small fragments), five
near-similar, and one `exact` family of thirteen two-line resource `__init__`
methods — all trivial parallels below the adopted gate's thirteen-line floor.
Against adoption: it ties rather than beats PyChase on Types 1-3, its findings
carry spans without qualified unit names (the adopted gate's allowlist keys on
`path::qualname`), it is distributed as a pre-1.0 platform-specific binary from
GitHub releases rather than PyPI, and the project documentation describes a
`nose verify` behavioural oracle that the released 0.20.0 CLI does not include.

The evaluation therefore left nose tied on Types 1-3 — equalling but not
bettering PyChase, at the cost of the qualified-name output and `uvx` pinning
the gate then relied on — and empty-handed on Type 4. On 2026-08-28 the
maintainers adopted nose regardless, in
[ADR-019](adr/adr-019-adopt-nose-duplication-gate.md): with detection quality
tied, its determinism (byte-identical runs needing neither a `PYTHONHASHSEED`
nor a Python 3.13 pin) and its roughly fiftyfold speed advantage decided the
choice, and location-keyed allow entries replace the qualified names it does
not report. Its exact-equivalence channel is enforced as a narrow blocking
signal, since its witness design refuses false equivalences rather than ranking
them above true ones; broader Type-4 duplication remains a review concern.

## Recommendation

- Use nose 0.20.0 behind `scripts/duplication_gate.py` as the blocking
  copy-paste gate, with the pinned `[tool.nose]` settings and the reasoned,
  location-keyed allowlist in `pyproject.toml` (ADR-019). PyChase remains the
  reference for detection quality on Types 1-3, which nose matches.
- Do not rely on pyscn for semantic (Type-4) duplication. Its semantic detector
  inverted the ranking between a true and a false semantic pair on this corpus,
  and on `episodic/` reported only intentional parallels at gate strength.
- Treat nose's exact-equivalence witness as the only machine-checked semantic
  signal. It covers a narrow modelled subset and misses rewrites such as a loop
  against a `sum()` fold, so wider semantic duplication stays a review concern.
- Revisit the comparison if nose's pre-1.0 distribution or ranked-surface view
  becomes a liability, or if pyscn widens its similarity band; these caveats
  are release-specific behaviour, not architectural limits.

The corpus is intentionally small and Episodic is only one codebase. The
results establish behaviour for these released versions and fixtures; they do
not validate project-authored claims or predict precision elsewhere.
