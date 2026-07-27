# Benchmark pyscn and Skylos dead-code detection

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`,
and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: COMPLETE

## Purpose / big picture

This work will produce a reproducible, evidence-led comparison of the current
dead-code detection in pyscn and Skylos. A maintainer will be able to inspect a
small labelled Python corpus, rerun both scanners with recorded versions and
commands, compare their precision and recall in distinct unused-symbol and
unreachable-statement lanes, and understand how both behave on the real
`episodic/` package. Success is observable in a checked-in report whose tables
can be regenerated from retained raw results and whose conclusions distinguish
documented claims from measured behaviour.

## Constraints

- Compare released, installable versions resolved on 2026-07-27, and record
  their exact versions. Do not compare an unreleased source checkout with a
  released competitor.
- Give both tools the same source corpus and equivalent exclusions. Preserve
  each tool's raw output before normalizing findings.
- Score unused-symbol detection separately from control-flow unreachability.
  The projects use “dead code” for overlapping but non-identical analyses.
- Treat checked-in labels, not either tool's output, as ground truth. Every
  labelled case must state why code is live or dead.
- Run core static analysis without optional large language model services or
  cloud uploads. Do not send Episodic source code to third-party services.
- Use primary project documentation and released command-line help for factual
  claims. Attribute project-authored benchmark claims rather than presenting
  them as independently verified.
- Keep benchmark artefacts out of `episodic/` and scan `episodic/` separately
  so the synthetic corpus cannot contaminate the real-project findings.
- Follow the repository documentation style guide, including British English
  with Oxford spelling and 80-column prose wrapping.

## Tolerances (exception triggers)

- Scope: stop and escalate if reproducibility requires changing production
  application code or more than 25 repository files.
- Dependencies: benchmark tools may run ephemerally through `uvx`; stop and
  escalate before adding either scanner as a project dependency.
- Corpus: stop and escalate if more than 30 labelled expectations are needed
  to resolve the main comparison. Additional cases belong in follow-up work.
- Compatibility: stop and document the problem if either current release
  cannot execute on this Linux host or cannot scan ordinary Python source.
- Iterations: stop and escalate after three unsuccessful attempts to obtain
  machine-readable output from a tool. Retain the textual output as a fallback.
- Ambiguity: do not assign a true-positive or false-positive label where Python
  runtime semantics or framework conventions leave liveness genuinely
  undecidable. Classify such results as review-required and exclude them from
  precision and recall.

## Risks

- Risk: the tools report at different granularities and categories.
  Severity: high. Likelihood: high. Mitigation: define a small normalization
  contract keyed by labelled source location and keep lane-specific scores
  alongside raw finding counts.
- Risk: dynamic Python features make static liveness uncertain.
  Severity: high. Likelihood: medium. Mitigation: include explicit dynamic and
  framework cases, document their runtime reachability, and use the
  review-required category where necessary.
- Risk: latest releases or command interfaces may change during the study.
  Severity: medium. Likelihood: medium. Mitigation: record versions, full
  commands, UTC date, and raw outputs.
- Risk: a benchmark designed after reading both tools could favour their known
  strengths. Severity: medium. Likelihood: medium. Mitigation: use
  language-level categories derived from Python semantics, include both
  positive and negative controls, and disclose corpus selection.
- Risk: a small synthetic corpus may not predict large-project usefulness.
  Severity: medium. Likelihood: high. Mitigation: pair scored fixtures with an
  unscored but manually adjudicated scan of `episodic/` and state the limits of
  generalization.

## Progress

- [x] (2026-07-27 00:05Z) Read the repository instructions, documentation
  index, repository layout, and documentation style guide.
- [x] (2026-07-27 00:05Z) Use Firecrawl to study both canonical repositories
  and their dead-code or analysis documentation.
- [x] (2026-07-27 00:05Z) Identify the need for separate unused-symbol and
  unreachable-statement benchmark lanes.
- [x] (2026-07-27 00:21Z) Resolve released versions pyscn 1.28.0 and
  Skylos 4.30.0, capture their command interfaces, and complete the bounded
  smoke comparison.
- [x] (2026-07-27 00:37Z) Add a 19-case labelled, tool-neutral Python corpus
  and normalization manifest.
- [x] (2026-07-27 00:44Z) Run both tools on the corpus and retain raw
  machine-readable output and elapsed-time metadata.
- [x] (2026-07-27 00:49Z) Normalize and score the corpus results, checking
  every mismatch against the source and tool output.
- [x] (2026-07-27 01:02Z) Scan `episodic/` with both tools and manually
  adjudicate actionable, false-positive, and review-required findings.
- [x] (2026-07-27 01:02Z) Write and index the final head-to-head report,
  including methodology, results, limitations, commands, and recommendation by
  use case.
- [x] (2026-07-27 01:09Z) Run all documentation and code gates required by the
  final artefacts, validate the Makefile, and prepare the final atomic commit.

## Surprises & discoveries

- Observation: pyscn's configuration reference emphasizes control-flow
  unreachability such as code after `return`, `break`, `continue`, or `raise`,
  while its analysis page also describes unreachable functions, classes, and
  modules. Evidence: Firecrawl extraction from
  `https://docs.codescan.dev/cli/analyze` and
  `https://docs.codescan.dev/configuration/reference` on 2026-07-27. Impact:
  released behaviour must be measured rather than inferred from a single
  documentation page.
- Observation: Skylos explicitly advertises unused imports, functions,
  classes, variables, and parameters, with confidence filtering and
  framework-aware or dynamic-code handling. Evidence: Firecrawl extraction from
  `https://docs.skylos.dev/dead-code-detection` on 2026-07-27. Impact: the
  benchmark must include precision controls for dynamic access and framework
  entry points as well as straightforward unused symbols.
- Observation: Leta could not register this checkout because its global
  workspace registry is mounted read-only, and direct daemon startup also
  failed. Evidence: `leta workspace add` returned `Read-only file system`, and
  `leta files` returned `Failed to start daemon`. Impact: repository navigation
  will use read-only repository-native tools where Leta remains unavailable;
  this does not affect scanner execution.
- Observation: an unmarked fixture directory under `/tmp` caused Skylos to
  promote `/tmp` to the analysis root because the sandbox exposes `/tmp/.git`;
  auxiliary MDX and browser-reference discovery then traversed unrelated
  scratch directories. Evidence: three interrupted Skylos 4.30.0 runs remained
  in `collect_mdx_ts_imports` or `collect_browser_event_handler_refs`; adding a
  minimal fixture `pyproject.toml` reduced the same scan to about 0.1 seconds.
  Impact: every retained corpus must include its own project marker, and the
  report must warn that ad hoc targets can inherit a broader ancestor project
  root.
- Observation: on the two-signal smoke file, pyscn reported the assignment
  after `return` as `unreachable_after_return` and did not report the unused
  function. Skylos reported the unused function and also reported the
  unreachable assignment as an unused variable. Evidence: pyscn 1.28.0 and
  Skylos 4.30.0 JSON output captured on 2026-07-27. Impact: source-location
  normalization can reveal useful overlap while the report preserves the tools'
  different explanations.
- Observation: pyscn found four of five labelled unreachable statements and no
  unused symbols; Skylos found all five labelled unused symbols and the same
  four unreachable locations as unused assignments. Both missed `if False`.
  Evidence: retained pyscn 1.28.0 and Skylos 4.30.0 corpus JSON plus
  `results/scores.json`. Impact: Skylos wins the unused-symbol lane, while
  pyscn provides the stronger control-flow explanation despite equal location
  recall in the second lane.
- Observation: the zero-threshold Episodic scan produced no pyscn findings and
  143 Skylos findings. Manual review classified two as actionable, 139 as false
  positives, and two as review-required contract placeholders. Evidence:
  compressed production reports and `results/production-adjudication.json`.
  Impact: Skylos is useful as a broad advisory inventory in this codebase, but
  needs project-specific tuning before use as a blocking gate.

## Decision log

- Decision: use two scored lanes plus a real-project review instead of one
  aggregate dead-code score. Rationale: an aggregate would reward or penalize
  tools for analyses they do not claim to perform and obscure whether a
  detector finds unused symbols or unreachable statements. Date/Author:
  2026-07-27 00:05Z / Codex.
- Decision: use released tools in ephemeral `uvx` environments and do not add
  project dependencies. Rationale: this matches a prospective adopter's
  experience while keeping the Episodic dependency graph unchanged.
  Date/Author: 2026-07-27 00:05Z / Codex.
- Decision: retain raw outputs and a normalization manifest in the repository.
  Rationale: normalized scores alone are not auditable when tool schemas and
  finding categories differ. Date/Author: 2026-07-27 00:05Z / Codex.
- Decision: give the synthetic corpus a minimal `pyproject.toml` at its scan
  root. Rationale: this bounds Skylos project-root discovery and represents a
  normal Python project without configuring either detector's findings.
  Date/Author: 2026-07-27 00:21Z / Codex.
- Decision: exclude unmatched findings from the labelled confusion matrix and
  report them separately. Rationale: the 11 unmatched Skylos findings were
  genuine unused fixture result variables, but expanding the oracle after
  seeing output would make the score post hoc and less defensible. Date/Author:
  2026-07-27 00:49Z / Codex.
- Decision: retain the large production reports with deterministic gzip
  metadata and replace Skylos' absolute checkout prefix with `./`. Rationale:
  compression preserves audit evidence without a multi-megabyte textual diff,
  while path normalization avoids committing a workstation-specific checkout
  identifier. Date/Author: 2026-07-27 01:02Z / Codex.

## Outcomes & retrospective

The study delivered a reproducible 19-label corpus, raw and normalized scanner
results, a manually adjudicated Episodic scan, and an indexed head-to-head
report. Skylos won the unused-symbol lane with 100% recall and precision on the
labelled cases. pyscn provided the more direct control-flow diagnostics; both
tools located four of five unreachable cases, but Skylos described those
locations as unused assignments.

The practical scan justified keeping the two capabilities separate. pyscn
returned no Episodic findings, while Skylos returned a broad inventory whose
143 displayed findings yielded two actionable private helpers, two contract
questions, and 139 false positives after repository-aware review. Confidence
filtering reduced subclass-hook noise but did not solve implicit dataclass,
framework, export, and interface semantics.

All Python, formatting, lint, typing, test, Markdown, Mermaid, and Makefile
validation passed. The default merman Mermaid backend timed out on an unchanged
large TUI design diagram; the supported `mmdc` backend validated the full
documentation set successfully. No production code was changed or removed.

## Context and orientation

Episodic is a Python application whose production package lives in `episodic/`.
Repository documentation lives in `docs/`, and this plan lives in
`docs/execplans/`. The comparison will add a bounded benchmark area outside the
production package for labelled fixtures and raw scanner results, then add a
report under `docs/` and link it from `docs/contents.md`. If a new top-level
benchmark directory is retained, `docs/repository-layout.md` must document its
responsibility.

A “labelled expectation” is one source location that the benchmark declares to
be dead, live, or review-required before considering scanner output. Precision
is the proportion of reported labelled findings that are truly dead. Recall is
the proportion of truly dead labelled expectations reported by the tool. A true
negative is deliberately live code that a tool correctly leaves alone.

The synthetic corpus will cover ordinary unused symbols, direct and exported
uses, unreachability after terminating statements, constant branches, dynamic
attribute access, decorator registration, special methods, and type-only
references. The real-project scan will not receive a synthetic score because
proving the liveness of every unreported Episodic symbol is outside this
bounded study; reported findings will instead be manually classified.

## Plan of work

### Stage A: establish tool contracts

Resolve each latest released version through `uvx`, capture `--version` and
relevant help, and run a one-file smoke test. Compare those interfaces with the
Firecrawl research and update this plan when observed behaviour contradicts the
docs. This stage is a go only when both tools can scan a local Python file
without external services.

### Stage B: create the benchmark oracle

Add small Python fixture modules and a machine-readable manifest. Each manifest
entry will name a lane, source path and line or symbol, expected liveness, and
rationale. Add tests for any normalization or scoring code before implementing
it, demonstrating the expected red failure and green pass. This stage is a go
only when labels can be inspected independently of either scanner.

### Stage C: execute and normalize

Run both released scanners against the same corpus, retain raw output, and
normalize findings to manifest entries without discarding unmatched results.
Produce counts for true positives, false positives, false negatives, and true
negatives by lane, plus precision, recall, and F1 where defined. Manually
inspect every mismatch. This stage is a go only when the normalized record can
be traced back to raw output and source.

### Stage D: test practical usefulness on Episodic

Run both tools against `episodic/` with equivalent exclusions and static-only
settings. Review every reported dead-code finding using source references and
tests, classifying it as actionable, false-positive, or review-required. Do not
delete production code as part of this comparison.

### Stage E: report and clean up

Write the report with dated versions, methodology, lane-level results, timing,
resource caveats, real-project findings, limitations, and recommendations by
use case. Link primary sources and index the report. Update repository layout
documentation if benchmark artefacts introduce a new top-level path. Run all
required gates sequentially, inspect generated changes, and commit atomic
documentation, benchmark, and report changes.

## Concrete steps

Run all commands from the repository root.

1. Resolve tool interfaces without changing project dependencies:

   ```bash
   uvx --from pyscn pyscn --version
   uvx --from pyscn pyscn analyze --help
   uvx --from skylos skylos --version
   uvx --from skylos skylos --help
   ```

   Record exact resolved versions. A successful transcript names both versions
   and exits zero. Observed versions are pyscn 1.28.0 and Skylos 4.30.0.

   The successful bounded smoke invocations are:

   ```bash
   uvx pyscn@latest analyze --select deadcode --min-severity info --json \
     /tmp/dead-code-smoke
   uvx skylos /tmp/dead-code-smoke --no-upload --no-provenance \
     --confidence 0 --no-grep-verify --format json
   ```

   `/tmp/dead-code-smoke/pyproject.toml` is required to keep Skylos discovery
   inside that directory.

2. Create and validate the labelled corpus and normalization tests using the
   focused test command documented alongside the benchmark implementation.
   Capture the expected red failure before the scorer exists, then the green
   pass after its minimal implementation.

3. Execute both tools with machine-readable output into retained raw-result
   files. Record the exact commands in this section after confirming the
   released interfaces rather than guessing flags from documentation.

4. Run the scorer and expect a summary containing separate
   `unused-symbol` and `unreachable-statement` rows for each tool. Investigate
   every unmatched or contradictory finding before accepting the output.

5. Scan `episodic/`, record the exact commands, and classify all findings in
   the report. A finding remains review-required when static evidence cannot
   establish liveness confidently.

6. Run repository gates sequentially with logs under `/tmp`:

   ```bash
   make check-fmt
   make test
   make typecheck
   make lint
   make markdownlint
   make nixie
   ```

   Each command must exit zero. Inspect `git status --short` after gates for
   regenerated tracked artefacts.

## Validation and acceptance

Acceptance requires all of the following observable outcomes:

- The report records exact versions, commands, dates, corpus labels, raw
  results, and lane-specific scores for both tools.
- Every scored discrepancy is explained from source evidence; unmatched
  scanner findings are never silently discarded.
- The report separates project-authored claims from measurements made in this
  repository.
- The Episodic scan classifies each reported finding without changing
  production code.
- Any scorer tests show recorded red and green evidence, then pass with the
  wider Python gates.
- `make check-fmt`, `make test`, `make typecheck`, `make lint`,
  `make markdownlint`, and `make nixie` all pass sequentially.
- The final Git worktree is clean and the plan status is `COMPLETE`.

Performance observations are descriptive wall-clock measurements from this
host, not a microbenchmark claim. Security acceptance requires that neither
tool uploads source or invokes optional large language model services.

## Idempotence and recovery

All scanner runs are read-only over fixture and application source. Raw result
files may be regenerated by rerunning the recorded commands and should replace
only files dedicated to this benchmark. Ephemeral `uvx` environments may be
reused safely. If a run fails, preserve its log, correct only the invocation or
fixture problem, and rerun that tool; do not change ground-truth labels to make
a tool pass. Git commits provide recovery points for each atomic stage.

## Artefacts and notes

Primary research sources consulted before benchmark design:

- <https://github.com/ludo-technologies/pyscn>
- <https://docs.codescan.dev/cli/analyze>
- <https://docs.codescan.dev/configuration/reference>
- <https://github.com/duriantaco/skylos>
- <https://docs.skylos.dev/dead-code-detection>

Firecrawl content was retrieved on 2026-07-27. The final report will link the
specific sources supporting each factual claim and will date potentially
changing release information.

## Interfaces and dependencies

The comparison must not add runtime or development dependencies to
`pyproject.toml`. Released scanner executables run through `uvx`. Any retained
normalizer must use the Python standard library unless an existing Episodic
development dependency clearly provides the required facility. Its public
contract will accept the ground-truth manifest and raw tool outputs, preserve
unmatched findings, and emit deterministic machine-readable scores plus a
human-readable summary. Exact paths and function signatures will be recorded
after Stage A confirms the released output schemas.

Revision note (2026-07-27 00:05Z): created the approved initial plan after the
primary-source documentation review. The remaining work begins with released
CLI verification and may refine exact commands or normalization interfaces as
observed schemas become known.

Revision note (2026-07-27 00:21Z): record Stage A versions, successful smoke
results, and the Skylos ancestor-root discovery caveat. Stage B must place a
project marker at the retained corpus root before implementing labels and the
normalizer.
