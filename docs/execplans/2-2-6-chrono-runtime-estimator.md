# Implement Chrono runtime estimation

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: COMPLETE

## Purpose and big picture

Chrono is the local quality-assurance (QA) evaluator that estimates how long a
written podcast dialogue will take to speak. It sits beside Pedante, Bromide,
Chiltern, Anthem, and Caesura in the generation quality stack, but unlike those
evaluators it does not call a Large Language Model (LLM). The first
implementation should use a deterministic, naive local heuristic and record
enough metadata to compare later estimators against it.

After this change, application code can pass a canonical Text Encoding
Initiative (TEI) script to Chrono and receive a typed runtime estimate that
includes:

1. the predicted spoken duration;
2. the input size used by the estimator;
3. the estimator name and version; and
4. local heuristic metadata, such as the words-per-minute setting.

Success is observable when unit tests prove the heuristic is deterministic and
well validated, property tests prove core invariants across generated inputs,
pytest-bdd behavioural tests prove the evaluator can run in the same QA
workflow style as the other evaluators, and LangGraph seam tests show Chrono
results can be carried through graph state without introducing an LLM charge.
The feature is complete only after documentation is updated, roadmap item
`2.2.6` is marked done, and the required gates pass: `make check-fmt`,
`make typecheck`, `make lint`, and `make test`.

## Constraints

- Preserve the hexagonal architecture dependency rule. Domain-level Chrono
  types and heuristic policy must not import Falcon, SQLAlchemy, LangGraph,
  Celery, Vidai Mock, HTTP clients, or database infrastructure.
- Keep Chrono local and deterministic for this roadmap item. Do not call an
  LLM, network service, or provider adapter from the estimator.
- Keep canonical script input TEI-first. JSON may be used only as a projection
  for tests or documentation, not as a competing canonical script model.
- Keep future estimator comparability explicit. Every result must identify the
  estimator name, estimator version, input size, and predicted runtime.
- Do not invent persistence for QA artefacts in this item. Persistence belongs
  to roadmap item `2.2.7`, unless the implementation uncovers an already
  existing repository seam that can be reused without widening scope.
- Use test-first workflow for each implementation stage. Add or update tests,
  confirm they fail for the missing behaviour, implement the smallest change,
  then rerun the same tests.
- Use Vidai Mock for behavioural testing of inference-service integrations that
  remain in the surrounding QA workflow. Chrono itself should not require Vidai
  Mock because it has no inference boundary.
- Update `docs/episodic-podcast-generation-system-design.md`,
  `docs/users-guide.md`, and the relevant internally facing architecture or
  developer documentation when the implementation pins behaviour.
- Mark `docs/roadmap.md` item `2.2.6` done only after implementation,
  documentation, and quality gates pass.

## Tolerances

- Scope: stop and escalate if implementation requires more than 10 production
  files or 700 net lines before a working vertical slice exists.
- Interface: stop and escalate if Chrono cannot be added without changing the
  public Pedante request/result types or existing LLM port contracts.
- Dependencies: stop and escalate if a new runtime dependency is required for
  the naive estimator.
- Persistence: stop and escalate if implementation appears to require database
  schema changes or migrations.
- Orchestration: stop and escalate if integrating Chrono into the existing
  LangGraph seam requires replacing the current Pedante-focused graph rather
  than extending or adding a small Chrono-specific seam.
- Behavioural testing: stop and escalate if the only plausible behavioural
  test would make a local estimator depend on a live LLM or network service.
- Iterations: stop and escalate after three failed attempts to settle the same
  failing test group.
- Ambiguity: stop and escalate if multiple result schemas remain plausible and
  the choice would affect roadmap item `2.2.7` persistence.

## Risks

- Risk: TEI parsing may be heavier than the naive estimator needs. Severity:
  medium. Likelihood: medium. Mitigation: start with a small helper that
  extracts spoken text from common TEI dialogue elements and strips tags using
  structured XML parsing from the Python standard library where possible.

- Risk: the repository currently has a Pedante-specific QA graph rather than a
  general multi-evaluator QA graph. Severity: medium. Likelihood: high.
  Mitigation: add a narrow Chrono graph seam first, or extend the QA state only
  if that remains small and testable.

- Risk: "runtime" could mean wall-clock execution time instead of spoken audio
  duration. Severity: low. Likelihood: medium. Mitigation: name fields and docs
  in terms of spoken duration, such as `estimated_seconds`, and define Chrono
  as a spoken-runtime estimator in public prose.

- Risk: the initial word-count heuristic may mishandle stage directions,
  markup, or non-dialogue text. Severity: medium. Likelihood: high. Mitigation:
  document the heuristic as naive, make the counted input size visible, and add
  tests for dialogue text, markup-only input, and mixed narrative/script
  content.

- Risk: property tests over arbitrary text may generate pathological whitespace
  or XML-like fragments that do not match the estimator's intended input.
  Severity: low. Likelihood: medium. Mitigation: constrain Hypothesis
  strategies to text payloads and simple TEI wrappers that represent expected
  caller input.

## Progress

- [x] (2026-05-08 00:00Z) Drafted this pre-implementation ExecPlan from
  `docs/roadmap.md`, `docs/episodic-podcast-generation-system-design.md`,
  `docs/agentic-systems-with-langgraph-and-celery.md`, and current QA code in
  `episodic/qa/`.
- [x] (2026-05-08 00:30Z) Validated the pre-implementation plan branch with
  `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie`.
- [x] (2026-05-08 20:05Z) Reconfirmed the branch and current QA symbols before
  implementation. The package still has a Pedante-specific graph seam and no
  Chrono implementation.
- [x] Stage A: inspect current QA module exports, Pedante tests, and
  generation graph seams immediately before implementation.
- [x] (2026-05-08 20:15Z) Added fail-first Chrono unit, property, LangGraph,
  and pytest-bdd tests. The focused pytest run failed during collection with
  `ModuleNotFoundError: No module named 'episodic.qa.chrono'`, as expected.
- [x] Stage B: add fail-first unit and property tests for Chrono request,
  result, metadata, validation, and heuristic invariants.
- [x] Stage C: add fail-first LangGraph seam tests and pytest-bdd behavioural
  scenarios for Chrono in the QA workflow.
- [x] (2026-05-08 20:35Z) Implemented `episodic.qa.chrono` and
  `episodic.qa.chrono_langgraph`, exported the Chrono public QA surface, and
  confirmed the focused Chrono suite passes with 18 tests.
- [x] (2026-05-08 20:50Z) Updated the system design, users guide, developers
  guide, and roadmap for the initial Chrono behaviour.
- [x] (2026-05-08 21:10Z) Ran final gates. `make check-fmt`, `make typecheck`,
  `make lint`, `make test`, `make markdownlint`, and `make nixie` all passed.
- [x] Stage D: implement the Chrono domain/policy module and exports.
- [x] Stage E: implement the minimal Chrono graph seam and any orchestration
  state wiring required by tests.
- [x] Stage F: update user, developer, architecture, and design documentation.
- [x] Stage G: mark roadmap item `2.2.6` done after all implementation gates
  pass.
- [x] Stage H: run final validation, update this ExecPlan with evidence, and
  commit the completed feature.

## Surprises & Discoveries

- Observation: `docs/roadmap.md` item `2.2.6` is currently open and names two
  acceptance points: estimate anticipated runtime with a naive local heuristic,
  and record estimator metadata for later comparison. Evidence: roadmap
  inspection on 2026-05-08. Impact: the initial scope is local estimation and
  metadata, not persistence or API retrieval.

- Observation: `docs/episodic-podcast-generation-system-design.md` defines
  Chrono as deterministic and auditable, recording estimator version, input
  size, and predicted runtime even though it does not create an external-call
  charge. Evidence: design inspection on 2026-05-08. Impact: Chrono should have
  a typed result shape rather than returning a bare integer duration.

- Observation: current QA implementation is centred on Pedante:
  `episodic/qa/pedante.py` defines Pedante request/result/evaluator types, and
  `episodic/qa/langgraph.py` carries a minimal Pedante StateGraph. Evidence:
  local `leta` symbol inspection on 2026-05-08. Impact: the Chrono plan should
  add a focused seam instead of assuming a complete multi-evaluator graph
  already exists.

- Observation: implementation started on the existing
  `docs/execplans/2-2-6-chrono-runtime-estimator` branch after explicit user
  instruction to proceed. Evidence: branch and status checks on 2026-05-08.
  Impact: the ExecPlan approval gate is satisfied and the status is now
  `IN PROGRESS`.

- Observation: Chrono behavioural coverage does not need Vidai Mock because
  the estimator has no inference-service boundary. Evidence:
  `tests/steps/test_chrono_steps.py` exercises the BDD path entirely
  in-process with `ChronoRuntimeEstimator`. Impact: Vidai Mock remains reserved
  for LLM-backed evaluators and adapters.

## Decision Log

- Decision: implement Chrono as a pure local QA evaluator with typed request,
  result, and metadata objects, separate from LLM-backed evaluators. Rationale:
  the roadmap and design both say Chrono is non-LLM, deterministic, and should
  remain comparable with later implementations. Date/Author: 2026-05-08 / Codex.

- Decision: keep persistence out of this item and defer durable QA artefact
  storage to roadmap item `2.2.7`. Rationale: `2.2.6` asks only for estimation
  and metadata, while `2.2.7` explicitly covers persisted QA artefacts.
  Date/Author: 2026-05-08 / Codex.

- Decision: use property tests for monotonicity and non-negativity invariants.
  Rationale: the runtime estimate should never become negative and adding
  spoken words should not reduce the estimated duration for a fixed heuristic.
  Date/Author: 2026-05-08 / Codex.

- Decision: keep the initial TEI extraction on `xml.etree.ElementTree` with a
  local lint suppression at the parse boundary. Rationale: the implementation
  plan explicitly constrained the estimator to the Python standard library, the
  estimator consumes internal canonical TEI, and adopting `defusedxml` would
  add a runtime dependency outside the roadmap slice. Date/Author: 2026-05-08 /
  Codex.

## Outcomes & Retrospective

Chrono now exposes a deterministic typed spoken-runtime estimate for TEI
dialogue through `episodic.qa.chrono`. The result includes estimator identity,
input character count, spoken word count, words-per-minute configuration, and
estimated seconds. `episodic.qa.chrono_langgraph` provides a narrow graph seam
for running Chrono inside QA orchestration without adding `LLMUsage`.

Unit tests, property tests, LangGraph seam tests, and pytest-bdd behavioural
coverage are in place. Documentation explains the initial heuristic, the lack
of LLM charges, maintainer boundaries, and test locations. Roadmap item
`2.2.6` is marked done.

The main implementation lesson is that keeping Chrono separate from the
Pedante graph avoided unnecessary generalisation while still preserving a
consistent evaluator port shape for future orchestration work.

## Context and orientation

This repository is a Python service for podcast generation and quality
assurance. Scripts use TEI P5 XML as the canonical authoring data model. TEI is
an XML vocabulary for representing structured texts; in this project it is the
source of truth for generated scripts and QA input.

The current QA package lives in `episodic/qa/`. The implemented evaluator is
Pedante, the factuality checker:

- `episodic/qa/pedante.py` defines `PedanteEvaluationRequest`,
  `PedanteEvaluationResult`, `PedanteEvaluator`, and strict parsing for
  LLM-backed evaluator output.
- `episodic/qa/langgraph.py` defines a minimal Pedante StateGraph with
  `PedanteGraphState`, `_pedante_node`, `route_after_pedante(...)`, and
  `build_pedante_graph(...)`.
- `episodic/qa/__init__.py` exports Pedante contracts and graph helpers.

Chrono should follow the same local clarity: typed contracts in `episodic/qa/`,
tests in `tests/`, and documentation in `docs/`. It should differ from Pedante
in one important way: Chrono must not use `episodic.llm.LLMPort`, because it is
not an LLM evaluator.

The roadmap and design documents relevant to this feature are:

- `docs/roadmap.md`, section `2.2.6`, which defines the requested Chrono
  feature.
- `docs/episodic-podcast-generation-system-design.md`, especially the Content
  Generation Orchestrator, Quality Assurance Stack, and cost-accounting
  sections that mention Chrono.
- `docs/agentic-systems-with-langgraph-and-celery.md`, which explains how
  LangGraph orchestration should remain stateful and testable.
- `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md`, and
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`, which matter only if
  implementation accidentally touches HTTP or persistence. Under this plan it
  should not.

## Plan of work

### Stage A: re-check repository context

Before writing code, inspect the current branch state and QA symbols:

- Run `git status --short` and confirm there are no unrelated local changes.
- Run `git branch --show-current` and confirm the branch is
  `docs/execplans/2-2-6-chrono-runtime-estimator`.
- Use `leta grep` and `leta show` to inspect `PedanteEvaluationRequest`,
  `PedanteEvaluationResult`, `PedanteEvaluator`, `PedanteGraphState`, and
  `build_pedante_graph`.
- Inspect `tests/test_pedante.py`, `tests/test_pedante_langgraph.py`,
  `tests/features/pedante.feature`, and `tests/steps/test_pedante_steps.py` for
  local test style.

Go/no-go: proceed only if the current QA structure still matches this plan. If
a general QA graph or Chrono implementation already exists, update this plan
before continuing.

### Stage B: define Chrono contracts with failing tests

Add unit tests in `tests/test_chrono.py` before production code exists. Cover:

- `ChronoEvaluationRequest` rejects blank `script_tei_xml`.
- `ChronoEstimatorConfig` rejects non-positive words-per-minute values and
  blank estimator names or versions.
- `ChronoRuntimeEstimate` rejects negative duration and negative input counts.
- a simple TEI dialogue produces a predictable estimate using the default
  heuristic.
- markup-only or whitespace-only spoken text produces a zero-second estimate
  while still recording input metadata.
- estimator metadata includes name, version, word count, character count, and
  words-per-minute.

Add property tests to the same file or to `tests/test_chrono_properties.py`.
Use Hypothesis to prove:

- estimated seconds are never negative for generated text;
- adding spoken words does not reduce the estimate for a fixed
  words-per-minute value; and
- the reported word count equals the number of tokens accepted by the naive
  tokenizer for generated simple text.

Run the focused tests and expect failure because `episodic.qa.chrono` does not
exist yet.

### Stage C: define orchestration behaviour with failing tests

Add LangGraph seam tests in `tests/test_chrono_langgraph.py`. Model them after
`tests/test_pedante_langgraph.py`, but keep Chrono routing simple. Cover:

- `_chrono_node(...)` requires a Chrono request in graph state.
- the node calls an evaluator port and stores a Chrono result.
- `build_chrono_graph(...)` propagates the result and metadata.
- the graph does not require or expose `LLMUsage`.

Add behavioural tests using pytest-bdd:

- Create `tests/features/chrono.feature`.
- Create `tests/steps/test_chrono_steps.py`.
- Scenario: a TEI dialogue is prepared, Chrono estimates spoken runtime, and
  the result includes estimated seconds plus estimator metadata.

If the scenario exercises surrounding LLM-backed QA services, use Vidai Mock in
the same style as `tests/steps/test_pedante_steps.py`. If the scenario covers
only Chrono, keep it local and document in the test module why Vidai Mock is
not launched: Chrono has no inference-service boundary.

### Stage D: implement the Chrono domain and policy module

Add `episodic/qa/chrono.py` with immutable dataclasses and pure helpers.
Recommended contracts:

```python
@dc.dataclass(frozen=True, slots=True)
class ChronoEvaluationRequest:
    script_tei_xml: str


@dc.dataclass(frozen=True, slots=True)
class ChronoEstimatorConfig:
    estimator_name: str = "chrono-naive-word-count"
    estimator_version: str = "1"
    words_per_minute: int = 150


@dc.dataclass(frozen=True, slots=True)
class ChronoEstimatorMetadata:
    estimator_name: str
    estimator_version: str
    input_character_count: int
    spoken_word_count: int
    words_per_minute: int


@dc.dataclass(frozen=True, slots=True)
class ChronoRuntimeEstimate:
    estimated_seconds: int
    metadata: ChronoEstimatorMetadata
```

Add `ChronoRuntimeEstimator` with an async `evaluate(...)` method or a
synchronous `estimate(...)` method plus an async adapter method. Prefer the
shape that best matches the QA graph port without adding fake asynchrony to the
domain policy. Keep XML parsing and word counting as pure functions in the same
module unless size demands extraction.

The initial heuristic should:

- extract spoken text from the TEI XML using the Python standard library XML
  parser when possible;
- fall back to treating the input as plain text only if parsing fails and tests
  define that policy explicitly;
- count simple word tokens deterministically;
- compute seconds as `ceil(spoken_word_count / words_per_minute * 60)`; and
- preserve zero words as zero seconds.

Update `episodic/qa/__init__.py` to export Chrono contracts and the estimator.

### Stage E: implement the Chrono LangGraph seam

Add a small graph seam in `episodic/qa/langgraph.py` or a separate
`episodic/qa/chrono_langgraph.py`. Prefer a separate module if adding Chrono to
the existing file makes the Pedante graph harder to read.

The seam should define:

- `ChronoEvaluatorPort`, a protocol with `evaluate(...)` returning
  `ChronoRuntimeEstimate`;
- `ChronoGraphState`, carrying `chrono_request` and `chrono_result`;
- `_chrono_node(...)`, which validates state and returns the result delta; and
- `build_chrono_graph(...)`, a minimal graph that runs Chrono and ends.

Do not add routing based on target runtime unless implementation also receives
explicit requirements for duration thresholds. This roadmap item asks only for
estimation and metadata.

### Stage F: update documentation

Update `docs/episodic-podcast-generation-system-design.md` to pin the initial
heuristic and metadata fields. Make clear that Chrono is deterministic, local,
and does not create normalized LLM usage.

Update `docs/users-guide.md` in the Quality & Compliance section. Describe the
new internal behaviour in user-facing terms: generated scripts can now receive
an anticipated spoken-runtime estimate during QA, but the result is currently
internal to authoring workflows rather than a public API feature.

Update `docs/developers-guide.md` or a more specific component architecture
document if one exists by then. Document Chrono package structure, maintainer
rules, and test locations, mirroring the Pedante section.

If implementation establishes a durable schema for persisted Chrono artefacts,
stop and update this plan first because that would exceed the intended `2.2.6`
scope and overlap with `2.2.7`.

### Stage G: update roadmap after gates pass

After code, tests, and documentation are complete, update `docs/roadmap.md` by
changing only this checklist item:

```markdown
- [x] 2.2.6. Implement Chrono for runtime estimation.
```

Do not mark roadmap item `2.2.7` done.

### Stage H: final validation and commit

Run all required gates sequentially, using `tee` to preserve logs under `/tmp`.
Do not run formatting, linting, typechecking, or tests in parallel. If a
command fails, inspect its log, fix the issue, rerun the focused failing check,
and then rerun the full gate sequence.

Commit the implementation only after all gates pass. Keep refactors separate
from the feature commit if post-commit review identifies unrelated cleanup.

## Concrete steps

Run these commands from the repository root
`/home/leynos/.lody/repos/github---leynos---episodic/worktrees/35a26e97-19d8-42f9-a7a5-d906dad1340f`.

First confirm context:

```bash
git status --short
git branch --show-current
```

Expected output before implementation starts:

```plaintext
docs/execplans/2-2-6-chrono-runtime-estimator
```

Use `leta` for symbol inspection:

```bash
leta grep "Pedante|Chrono|GraphState|Evaluator" "episodic|tests" -k class,function,method
leta show PedanteEvaluationResult -n 20
leta show build_pedante_graph -n 20
```

Add fail-first tests:

```bash
uv run pytest tests/test_chrono.py tests/test_chrono_properties.py
uv run pytest tests/test_chrono_langgraph.py
uv run pytest-bdd tests/features/chrono.feature
```

Expected result before implementation:

```plaintext
ModuleNotFoundError: No module named 'episodic.qa.chrono'
```

Implement the feature and rerun focused tests:

```bash
uv run pytest tests/test_chrono.py tests/test_chrono_properties.py
uv run pytest tests/test_chrono_langgraph.py
uv run pytest-bdd tests/features/chrono.feature
```

Expected result after implementation:

```plaintext
... passed
```

Run final gates sequentially with logs:

```bash
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-2-2-6-chrono-runtime-estimator.out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-2-2-6-chrono-runtime-estimator.out
make lint 2>&1 | tee /tmp/lint-episodic-2-2-6-chrono-runtime-estimator.out
make test 2>&1 | tee /tmp/test-episodic-2-2-6-chrono-runtime-estimator.out
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-2-2-6-chrono-runtime-estimator.out
make nixie 2>&1 | tee /tmp/nixie-episodic-2-2-6-chrono-runtime-estimator.out
```

Expected result for each command:

```plaintext
... 0
```

After gates pass, inspect and commit:

```bash
git diff
git status --short
git add episodic/qa tests docs
git commit -F "$COMMIT_MSG_FILE"
```

Create the commit message in a temporary file from `mktemp -d`, then commit
with `git commit -F`; do not pass the message with `git commit -m`.

## Validation and acceptance

The implemented feature is accepted when all of the following are true:

- Unit tests prove Chrono validates its request, configuration, result, and
  metadata contracts.
- Unit tests prove the default heuristic returns a predictable duration for
  known TEI dialogue.
- Property tests prove non-negative estimates and monotonic estimates for a
  fixed heuristic over generated simple spoken text.
- LangGraph seam tests prove Chrono can run as a QA graph node and propagate
  typed metadata without `LLMUsage`.
- pytest-bdd behavioural tests prove an editor-facing QA workflow can obtain a
  Chrono spoken-runtime estimate from a TEI script.
- `docs/episodic-podcast-generation-system-design.md` records the initial
  heuristic and metadata.
- `docs/users-guide.md` explains the user-visible internal QA behaviour.
- `docs/developers-guide.md` or a more specific component architecture
  document explains the internal Chrono interfaces and test locations.
- `docs/roadmap.md` marks only item `2.2.6` done.
- `make check-fmt`, `make typecheck`, `make lint`, and `make test` pass.
- Markdown gates pass for changed docs: `make markdownlint` and `make nixie`.

## Idempotence and recovery

The implementation steps are additive and safe to repeat. Re-running tests and
quality gates should not change source files except when `make fmt` is invoked
to repair formatting. If `make check-fmt` fails, run `make fmt`, inspect the
diff, then rerun `make check-fmt`.

If a test stage fails because a test expectation is wrong, update this ExecPlan
before changing production code so future readers understand the corrected
behaviour. If a branch contains unrelated local changes, do not overwrite them;
either work around them or stop and ask for direction.

No destructive Git commands are required. If implementation needs to discard
generated scratch files, remove only known scratch paths after confirming they
are not tracked.

## Interfaces and dependencies

Use only the Python standard library for the initial estimator. In particular,
use `dataclasses`, `math`, `re`, and `xml.etree.ElementTree` as needed. Do not
add runtime dependencies.

The target public Python surface after implementation should include these
exports from `episodic.qa`:

```python
ChronoEvaluationRequest
ChronoEstimatorConfig
ChronoEstimatorMetadata
ChronoRuntimeEstimate
ChronoRuntimeEstimator
build_chrono_graph
```

If the implementation uses a separate graph module, export graph helpers from
`episodic.qa.__init__` in the same style as the existing Pedante graph helper.

The initial heuristic should default to `150` words per minute. If product or
editorial documentation later defines a different default, update this plan and
the decision log before changing code.

## Artifacts and notes

This plan was drafted before implementation. Validation evidence for the plan
branch:

```plaintext
make check-fmt ... passed; 271 files already formatted
make typecheck ... passed; ty check: All checks passed!
make lint ... passed; ruff check: All checks passed!
make test ... passed; 439 passed, 3 skipped
make markdownlint ... passed; Summary: 0 error(s)
make nixie ... passed; All diagrams validated successfully!
```

Final implementation validation:

```plaintext
make check-fmt ... passed; 277 files already formatted
make typecheck ... passed; ty check: All checks passed!
make lint ... passed; ruff check: All checks passed!
make test ... passed; 457 passed, 3 skipped
make markdownlint ... passed; Summary: 0 error(s)
make nixie ... passed; All diagrams validated successfully!
```

## Revision note

Initial draft defined the implementation sequence for roadmap item `2.2.6`,
including Chrono contracts, test-first milestones, documentation, roadmap
completion, and quality gates. The plan was later executed after explicit user
approval, and the completed implementation was validated with the required
Python and Markdown gates.
