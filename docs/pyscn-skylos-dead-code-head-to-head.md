# pyscn and Skylos dead-code detection head-to-head

## Outcome

Neither tool is the universal winner because they implement different meanings
of dead code. Skylos 4.30.0 is the clear choice for finding unused Python
symbols: it found all five labelled unused symbols without flagging any of the
eight labelled live controls. pyscn 1.28.0 is the more focused choice for
control-flow cleanup: it reported four of five unreachable statements with no
false positives and far less repository-scale noise.

For a broad cleanup campaign, start with Skylos and expect manual triage. For a
low-noise check for statements after unconditional terminators, use pyscn. The
tools are complementary rather than interchangeable.

## What each project means by dead code

The [pyscn repository](https://github.com/ludo-technologies/pyscn) presents a
general Python quality scanner. Its
[analysis command documentation](https://docs.codescan.dev/cli/analyze) and
[configuration reference](https://docs.codescan.dev/configuration/reference)
describe dead-code findings centred on unreachable control flow, including
statements after `return`, `raise`, `continue`, and `break`.

The [Skylos repository](https://github.com/duriantaco/skylos) and
[dead-code detection documentation](https://docs.skylos.dev/dead-code-detection)
describe a symbol-liveness analyzer for unused imports, functions, classes,
variables, and parameters. Skylos also advertises confidence scoring and
special handling for frameworks and dynamic Python.

Those contracts overlap, but they are not the same. The comparison therefore
uses separate unused-symbol and unreachable-statement lanes. A single blended
score would reward one project for a capability that the other does not
primarily claim.

## Method

The comparison was run on 2026-07-27 using the released command-line packages
pyscn 1.28.0 and Skylos 4.30.0. Both ran through `uvx`, without becoming
project dependencies. Uploads, provenance collection, large language model
services, and Skylos grep verification were disabled.

The checked-in corpus contains 19 labels fixed before either full scan:

- five dead and eight live unused-symbol cases;
- five dead and one live unreachable-statement cases; and
- dynamic controls for decorator registration, `getattr`, `__call__`, package
  exports, and direct uses.

Findings were matched by source location. Unlabelled findings were preserved
separately instead of being converted into false positives after the fact. The
raw reports, oracle, normalizer, and normalized counts are under
`benchmarks/dead_code/`.

## Labelled corpus results

| Tool          | Lane                           | TP  | FP  | FN  | TN  | Precision   | Recall | F1          |
| ------------- | ------------------------------ | --: | --: | --: | --: | ----------: | -----: | ----------: |
| pyscn 1.28.0  | Unused symbol                  | 0   | 0   | 5   | 8   | Not defined | 0.0%   | Not defined |
| Skylos 4.30.0 | Unused symbol                  | 5   | 0   | 0   | 8   | 100.0%      | 100.0% | 100.0%      |
| pyscn 1.28.0  | Unreachable statement          | 4   | 0   | 1   | 1   | 100.0%      | 80.0%  | 88.9%       |
| Skylos 4.30.0 | Unreachable statement location | 4   | 0   | 1   | 1   | 100.0%      | 80.0%  | 88.9%       |

*Table 1: Confusion matrices for the pre-labelled corpus.*

The apparent tie in the second lane needs qualification. pyscn identified the
four locations as unreachable after `return`, `raise`, `continue`, or `break`.
Skylos reported assignments at the same locations as unused variables; it did
not provide a control-flow explanation. Both missed the literal `if False`
branch. Skylos also emitted 11 unlabelled findings for intentionally unused
top-level result variables that make live calls in the fixture. Those were
genuine unused variables, but were excluded from the pre-registered confusion
matrix rather than added to the oracle after seeing results.

| Tool          | Raw findings | One-shot elapsed time |
| ------------- | -----------: | --------------------: |
| pyscn 1.28.0  | 4            | 326 ms                |
| Skylos 4.30.0 | 20           | 415 ms                |

*Table 2: Corpus output volume and observed wall-clock time.*

The timings are single observations on one host, not a performance benchmark.

## Episodic package scan

The practical scan used `episodic/` as the common target. pyscn emitted no
findings in 292 ms. Skylos emitted 143 findings in 13.747 seconds at confidence
zero: 88 functions, 22 imports, five classes, four variables, and 24
parameters. Every displayed finding was checked against source references,
tests, public exports, framework contracts, and design documentation.

| Disposition     | Count | Share | Interpretation                                                       |
| --------------- | ----: | ----: | -------------------------------------------------------------------- |
| Actionable      | 2     | 1.4%  | Private helpers with no production caller                            |
| False positive  | 139   | 97.2% | Live through Python, framework, export, test, or interface semantics |
| Review required | 2     | 1.4%  | Unreferenced code retained by explicit delivery contracts            |

*Table 3: Manual adjudication of Skylos repository findings at confidence zero.*

The actionable candidates were `_build_payload_dataclass` in
`episodic/api/helpers.py`, which is referenced only by its direct tests, and
`_load_reference_documents_for_target` in the profile-template brief loaders,
which has no repository references. This study does not delete production code.

The two review-required findings were `StaleEventSequence` and
`UploadInitRequest`. Both are currently unreferenced, but each is named by an
existing execution-plan contract, so removal requires a product or design
decision rather than an automated cleanup.

The false positives clustered rather than appearing randomly:

- 41 were framework callbacks, subclass hooks, nested callbacks, or a string
  process entry point;
- 40 were validation helpers reached by dataclass `__post_init__` methods;
- 24 were intentionally ignored framework, protocol, or no-op parameters;
- 22 were type-related imports or declared façade and compatibility re-exports;
- five were documented public or test-support functions;
- three were referenced, documented, or test-support classes; and
- four were external process constants or serialized fields.

Skylos assigned confidence 40 to 32 subclass-hook findings. Applying its
default threshold of 60 would remove those findings, leaving 111: two
actionable, 107 false positives, and two requiring review. Confidence filtering
helps, but does not address the dominant implicit-hook and interface patterns
in this codebase.

## Operational caveat

Skylos discovers a project root above the supplied target. During an early
scratch run, an unmarked directory beneath `/tmp` inherited `/tmp/.git` from
the sandbox and triggered traversal of unrelated scratch projects during
auxiliary discovery. Adding a minimal `pyproject.toml` at the corpus root
bounded the scan. Ad hoc scans should therefore use an explicit Python project
root rather than an arbitrary unmarked directory.

## Recommendation

- Choose Skylos when the goal is broad unused-symbol discovery and there is
  capacity to tune exclusions and review results. Its corpus recall was
  excellent, and its category coverage is materially wider.
- Choose pyscn when the goal is a fast, low-noise control-flow pass. Its
  diagnostics explained why statements were unreachable, but it did not detect
  unused symbols in this comparison.
- Use both in a cleanup programme: pyscn as a focused control-flow gate and
  Skylos as an advisory inventory. Do not make zero-threshold Skylos findings a
  blocking gate without project-specific suppression and framework modelling.

The corpus is intentionally small and Episodic is only one framework-heavy
application. The results establish behaviour for these released versions and
fixtures; they do not validate project-authored benchmark claims or predict
precision on every Python codebase.
