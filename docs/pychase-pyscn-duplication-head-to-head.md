# PyChase and pyscn code-duplication head-to-head

## Outcome

PyChase 0.1.0 is the choice for Episodic's blocking duplication gate. On the
labelled corpus it reported every syntactic clone with no false positives and
no unlabelled noise, and its unit-level findings carry qualified names that
feed directly into remediation. pyscn 1.29.1 matched PyChase's syntactic recall
and was the only tool to detect the Type-4 semantic clone, but it could not do
so without also reporting a false positive, and its similarity scores compress
into a narrow band that offers no threshold separating the two.

Neither tool detects semantically equivalent code reliably. The adopted gate
therefore targets copy-paste duplication (Types 1-3) and treats semantic
duplication as a review concern, not a machine-checked one.

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
  two classes; and
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
false one, because the false positive scores higher. PyChase assigned the
renamed Type-2 clones similarity 1.0 and reported no control pair at any
threshold down to 0.6.

pyscn's similarity band is also compressed: near-identical code rarely scores
above 0.85 unless it is byte-identical, so the usable strict range collapses to
a single step between 0.8 and exact match.

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
members (`results/production-adjudication.json`):

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

## Recommendation

- Use PyChase behind `scripts/duplication_gate.py` as the blocking
  copy-paste gate, with the declarative-module exclusions and the reasoned
  allowlist in `pyproject.toml` (ADR-018).
- Do not rely on either tool for semantic (Type-4) duplication. pyscn's
  semantic detector inverted the ranking between a true and a false semantic
  pair on this corpus.
- Revisit the comparison when PyChase gains Python 3.14 support or pyscn
  widens its similarity band; both caveats are release-specific behaviour, not
  architectural limits.

The corpus is intentionally small and Episodic is only one codebase. The
results establish behaviour for these released versions and fixtures; they do
not validate project-authored claims or predict precision elsewhere.
