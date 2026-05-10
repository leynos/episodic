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

After this change, application code can pass a valid canonical Text Encoding
Initiative (TEI) P5 script to Chrono and receive a typed runtime estimate that
includes:

1. the predicted spoken duration;
2. the input size used by the estimator;
3. the estimator name and version; and
4. local heuristic metadata, such as the words-per-minute setting.

Success is observable when Chrono rejects malformed TEI, extracts spoken text
through the shared `tei-rapporteur` TEI P5 model rather than local XML
heuristics, and has a ratified Architectural Decision Record (ADR) that defines
which TEI elements count as spoken dialogue across Episodic. The initial local
heuristic and metadata contract are already implemented, but this ExecPlan is
reopened because the current implementation treats malformed XML as raw text
and encodes spoken-element semantics locally. The feature is complete only
after the `tei-rapporteur` change requests are prioritized, the ADR is merged,
Chrono uses the `tei-rapporteur` surface, documentation is updated, roadmap
item `2.2.6` remains done only if the stricter TEI contract is implemented, and
the required gates pass: `make check-fmt`, `make typecheck`, `make lint`, and
`make test`.

## Constraints

- Preserve the hexagonal architecture dependency rule. Domain-level Chrono
  types and heuristic policy must not import Falcon, SQLAlchemy, LangGraph,
  Celery, Vidai Mock, HTTP clients, or database infrastructure.
- Chrono must consume valid TEI P5 XML. Malformed XML is not accepted input and
  must produce a deterministic validation error rather than falling back to raw
  text.
- Document fragments used in tests or fixtures must still be valid TEI P5
  documents according to `tei-rapporteur`. Minimal XML that bypasses the TEI
  header or document model is not an acceptable interchange example.
- `tei-rapporteur` must be the least-friction path for working with TEI P5 in
  Episodic. If Chrono cannot use it directly, record the missing API in this
  plan, raise the corresponding `tei-rapporteur` change request, and stop
  before adding more local TEI semantics.
- Spoken-text semantics for Chrono must be ratified in an ADR before further
  production behaviour is added. Uncertainty over whether elements such as `p`,
  `ab`, `seg`, `l`, `u`, `sp`, or inline descendants count as spoken text is a
  hard stop, not an implementation detail.
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
- TEI semantics: stop and escalate if the ADR does not settle the spoken-text
  element mapping, nested inline handling, and malformed-input policy.
- Upstream tooling: stop and escalate if `tei-rapporteur` cannot expose a
  spoken-text iterator or equivalent structured projection without broad
  changes outside this feature branch.
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

- Risk: `tei-rapporteur` does not yet expose the exact spoken-text extraction
  surface Chrono needs. Severity: high. Likelihood: high. Mitigation:
  prioritize `tei-rapporteur` change requests before changing Chrono further.
  Required behaviour is documented in this ExecPlan under "Required
  `tei-rapporteur` behaviour".

- Risk: Episodic currently lacks a ratified ADR for which TEI P5 elements are
  spoken dialogue for runtime estimation. Severity: high. Likelihood: high.
  Mitigation: write and merge an ADR before implementing new Chrono parsing
  behaviour. Treat unresolved semantics as a hard stop.

- Risk: the existing Chrono implementation and tests accept malformed XML and
  minimal TEI-shaped snippets. Severity: high. Likelihood: high. Mitigation:
  replace fallback tests with valid TEI P5 fixtures and validation-error tests
  after the ADR and `tei-rapporteur` API are available.

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
- [x] (2026-05-08 20:50Z) Updated the system design, users' guide, developers'
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
- [x] (2026-05-10 00:00Z) Reopened the ExecPlan after product direction
  clarified that valid TEI P5 is an enforced interchange format, malformed XML
  fallback is unacceptable, and Chrono must prioritize `tei-rapporteur` gaps
  rather than local XML semantics.
- [ ] Stage I: write the Episodic ADR that ratifies spoken-text TEI semantics
  for runtime estimation and marks unresolved semantics as a hard stop.
- [x] (2026-05-10 00:00Z) Drafted proposed ADR-006 under `docs/adr/` with the
  spoken-container mapping, exclusion rules, normalization policy, tokenization
  scope, validation failure policy, and required `tei-rapporteur` extraction
  contract. Stage I remains blocked until the ADR is accepted.
- [ ] Stage J: raise and prioritize `tei-rapporteur` change requests for a
  Chrono-ready spoken-text extraction API.
- [ ] Stage K: replace Chrono's local `ElementTree` extraction and malformed
  XML fallback with the ratified `tei-rapporteur` API and strict validation
  behaviour.
- [ ] Stage L: update tests, documentation, and final gates for the stricter
  TEI P5 contract.

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
  Impact: the ExecPlan approval gate was satisfied for the first implementation
  slice.

- Observation: Chrono behavioural coverage does not need Vidai Mock because
  the estimator has no inference-service boundary. Evidence:
  `tests/steps/test_chrono_steps.py` exercises the BDD path entirely in-process
  with `ChronoRuntimeEstimator`. Impact: Vidai Mock remains reserved for
  LLM-backed evaluators and adapters.

- Observation: the current Chrono implementation uses `xml.etree.ElementTree`
  and explicitly falls back to raw text on parse failure. Evidence:
  `episodic/qa/chrono.py` catches `ElementTree.ParseError` in
  `_extract_spoken_text(...)`. Impact: this violates the clarified invariant
  that valid TEI P5 XML is the enforced interchange format and must be replaced.

- Observation: `tei-rapporteur` already exposes `parse_xml`, `to_dict`,
  `to_msgpack`, and `iter_parse`, but the current Episodic docs do not define a
  Chrono-specific spoken-text iterator contract. Evidence:
  `docs/tei-rapporteur-users-guide.md` documents paragraph, utterance, and div
  events, plus inline tagged nodes, but no runtime-estimation extraction API.
  Impact: Chrono should not invent local TEI semantics; the required behaviour
  must move upstream into `tei-rapporteur`.

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

- Decision: supersede the local `ElementTree` extraction decision. Chrono must
  use `tei-rapporteur` for TEI P5 parsing and must not accept malformed XML as
  raw text. Rationale: valid TEI P5 XML is the enforced Episodic interchange
  format, and `tei-rapporteur` is expected to be the least-friction TEI P5
  interface. Date/Author: 2026-05-10 / User and Codex.

- Decision: treat spoken-element semantics as an ADR-gated domain decision.
  Rationale: Episodic cannot leave core domain semantics uncertain inside one
  evaluator. The ADR must define what counts as spoken dialogue for Chrono and
  any other component that consumes script dialogue. Date/Author: 2026-05-10 /
  User and Codex.

- Decision: draft ADR-006 as `Proposed`, not `Accepted`. Rationale: the ADR
  records a concrete proposed contract, but Stage J and Stage K must remain
  blocked until project acceptance ratifies the semantics. Date/Author:
  2026-05-10 / Codex.

## Outcomes & Retrospective

Chrono now exposes a deterministic typed spoken-runtime estimate for TEI
dialogue through `episodic.qa.chrono`. The result includes estimator identity,
input character count, spoken word count, words-per-minute configuration, and
estimated seconds. `episodic.qa.chrono_langgraph` provides a narrow graph seam
for running Chrono inside QA orchestration without adding `LLMUsage`.

Unit tests, property tests, LangGraph seam tests, and pytest-bdd behavioural
coverage are in place for the initial local heuristic. Documentation explains
the initial heuristic, the lack of LLM charges, maintainer boundaries, and test
locations. Roadmap item `2.2.6` is marked done.

This outcome is now incomplete against the clarified architecture. The current
implementation remains useful as a metadata and orchestration slice, but its
TEI parsing policy must be revised. Completion now requires `tei-rapporteur`
spoken-text extraction support, strict TEI P5 validation, and an ADR ratifying
spoken-dialogue semantics.

The main implementation lesson is that keeping Chrono separate from the Pedante
graph avoided unnecessary generalization while still preserving a consistent
evaluator port shape for future orchestration work.

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

Chrono must also differ from ad hoc XML-processing helpers: it must not own TEI
P5 parsing semantics. `tei-rapporteur` is the shared TEI P5 parser and
projection library used elsewhere in Episodic. Chrono may own runtime-estimator
policy, such as words per minute and metadata shape, but it must delegate
document validation and spoken-text extraction to `tei-rapporteur` once the
required API exists.

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

The original initial heuristic used the Python standard library XML parser and
raw-text fallback. That behaviour is superseded. The revised heuristic should:

- parse and validate the script as TEI P5 through `tei-rapporteur`;
- reject malformed XML or invalid TEI P5 with a deterministic validation error;
- extract spoken text through a `tei-rapporteur` API ratified by the Episodic
  ADR;
- count simple word tokens deterministically;
- compute seconds as `ceil(spoken_word_count / words_per_minute * 60)`; and
- preserve valid TEI documents with zero spoken words as zero seconds.

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

### Stage I: ratify spoken-text semantics in an ADR

Add a new ADR under `docs/adr/` before changing Chrono parsing behaviour. The
ADR must define, in Episodic domain language, what counts as spoken script text
for runtime estimation. It must be explicit about:

- whether `sp`, `u`, `p`, `ab`, `seg`, `l`, and inline descendants are spoken
  containers, spoken leaves, grouping elements, or non-spoken markup;
- how speaker labels, stage directions, notes, lists, headings, references,
  citations, and show-note blocks are excluded;
- how nested spoken elements are handled so text is counted exactly once;
- how whitespace, punctuation, pauses, emphasis, and inline annotations are
  normalized before word tokenization;
- whether non-English scripts, numbers, contractions, and hyphenated words are
  in scope for the naive estimator; and
- the failure policy for malformed XML or TEI that does not validate against
  the Episodic TEI P5 profile.

Go/no-go: do not proceed to Stage J or K until the ADR is accepted. If the ADR
cannot settle a semantic question, record that as a hard stop and ask for
product/editorial direction.

### Stage J: prioritize `tei-rapporteur` change requests

Before rewriting Chrono, raise the missing `tei-rapporteur` work as upstream
change requests. The goal is to make `tei-rapporteur` the least-friction TEI P5
interface for Chrono rather than forcing every Episodic component to re-encode
TEI semantics locally.

Required `tei-rapporteur` behaviour:

- Provide a Python-callable API that accepts TEI P5 XML and validates it using
  the same parser/profile as `parse_xml(...)`.
- Return a stable ordered stream or list of spoken text segments suitable for
  runtime estimation. A segment should include the normalized text and enough
  location/provenance to diagnose where it came from, such as an XPath-like
  locator, `xml:id`, or event path.
- Count each spoken text node exactly once even when TEI uses nested inline
  structures such as `<p>Hello <seg>there</seg></p>`.
- Exclude non-dialogue content ratified by the ADR, including speaker labels,
  notes, headings, metadata, show-note blocks, citations, and stage directions
  unless the ADR explicitly says otherwise.
- Preserve document order.
- Expose structured error types or deterministic `ValueError` messages for
  malformed XML and invalid TEI P5 so Chrono can report a domain error without
  pattern-matching unstable strings.
- Provide Python type information for the new API so `make typecheck` can
  validate Chrono without local `Any` shims.
- Include tests in `tei-rapporteur` for `p`, `ab`, `seg`, `l`, nested inline
  content, utterance-style dialogue, non-spoken exclusions, malformed XML, and
  invalid TEI documents.

Go/no-go: do not add more local XML traversal to Chrono to compensate for a
missing `tei-rapporteur` API. If the API cannot be delivered in the dependency
pin used by this branch, keep Chrono blocked and update this plan with the
upstream status.

### Stage K: replace local Chrono TEI parsing

After the ADR and `tei-rapporteur` API are available, update
`episodic/qa/chrono.py` so `_extract_spoken_text(...)` delegates TEI validation
and spoken-text extraction to `tei-rapporteur`. Remove the raw-text fallback.
Update tests so malformed XML and invalid TEI assert validation failure instead
of word counting. Replace minimal TEI-like test strings with valid TEI P5
fixtures accepted by `tei-rapporteur`.

Chrono should still own:

- `ChronoEvaluationRequest`, `ChronoEstimatorConfig`,
  `ChronoEstimatorMetadata`, and `ChronoRuntimeEstimate`;
- simple word-token counting for the initial estimator, unless the ADR assigns
  tokenization to `tei-rapporteur`; and
- words-per-minute configuration and estimated seconds calculation.

Chrono should not own:

- TEI document validation;
- the definition of which TEI elements are spoken dialogue; or
- XML traversal rules for nested TEI content.

### Stage L: documentation and final gates for the strict TEI contract

Update `docs/episodic-podcast-generation-system-design.md`,
`docs/developers-guide.md`, and `docs/users-guide.md` to remove any implication
that Chrono accepts malformed XML or local TEI-shaped fragments. Link the new
ADR from the developer-facing Chrono section. Update this ExecPlan's outcomes
and validation evidence after the implementation passes the gates.

## Concrete steps

Run these commands from the repository root.

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

For the reopened strict TEI P5 work, first create the ADR and upstream
`tei-rapporteur` requests before changing Chrono:

```bash
rg -n "tei_rapporteur|tei-rapporteur|Chrono|spoken" episodic tests docs
rg -n "ADR|Architectural Decision" docs
```

Expected result before Chrono rewrite:

```plaintext
The ADR file and tei-rapporteur spoken-text API are absent or incomplete.
```

After the ADR is accepted and the `tei-rapporteur` API is available in this
branch, replace the local XML extraction and run focused validation:

```bash
uv run pytest tests/test_chrono.py tests/test_chrono_properties.py
uv run pytest tests/test_chrono_langgraph.py tests/steps/test_chrono_steps.py
```

Expected result after the strict TEI P5 rewrite:

```plaintext
Malformed XML and invalid TEI P5 are rejected; valid TEI P5 fixtures pass.
```

## Validation and acceptance

The implemented feature is accepted when all of the following are true:

- Unit tests prove Chrono validates its request, configuration, result, and
  metadata contracts.
- Unit tests prove the default heuristic returns a predictable duration for
  known TEI dialogue.
- Unit tests prove malformed XML and invalid TEI P5 are rejected instead of
  being counted as raw text.
- Unit and behavioural fixtures use valid TEI P5 documents accepted by
  `tei-rapporteur`, including any compact examples used in tests.
- Property tests prove non-negative estimates and monotonic estimates for a
  fixed heuristic over generated simple spoken text.
- LangGraph seam tests prove Chrono can run as a QA graph node and propagate
  typed metadata without `LLMUsage`.
- pytest-bdd behavioural tests prove an editor-facing QA workflow can obtain a
  Chrono spoken-runtime estimate from a TEI script.
- A merged ADR defines the Episodic spoken-text semantics used by Chrono and
  any other script-dialogue consumer.
- The required `tei-rapporteur` spoken-text extraction API exists, is covered
  by its own tests, and is used by Chrono for TEI P5 validation and extraction.
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

Use the existing `tei-rapporteur` dependency as Chrono's TEI P5 parsing and
spoken-text extraction boundary. Do not add a second XML or TEI parser for
Chrono, and do not keep a local `xml.etree.ElementTree` traversal path once the
`tei-rapporteur` API is available. The standard library remains appropriate for
estimator-local concerns such as `dataclasses`, `math`, `re`, and logging.

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

The required `tei-rapporteur` Python surface should expose a typed function or
method that validates a TEI P5 document and returns ordered spoken text
segments with normalized text and locator/provenance metadata. Chrono should
depend on that surface instead of depending on lower-level parser events unless
the ADR explicitly chooses an event-level integration.

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

ADR-006 draft validation:

```plaintext
make fmt ... passed; 278 files left unchanged; Summary: 0 error(s)
make markdownlint ... passed; Summary: 0 error(s)
make nixie ... passed; All diagrams validated successfully!
```

## Revision note

Initial draft defined the implementation sequence for roadmap item `2.2.6`,
including Chrono contracts, test-first milestones, documentation, roadmap
completion, and quality gates. The plan was later executed after explicit user
approval, and the completed implementation was validated with the required
Python and Markdown gates.

The 2026-05-10 revision reopens the plan because valid TEI P5 is the enforced
interchange format in Episodic. Raw-text fallback for malformed XML is invalid,
minimal TEI-shaped snippets are not acceptable fixtures unless they validate as
TEI P5 documents, and Chrono must not own TEI spoken-dialogue semantics. The
remaining work is gated by an ADR and by prioritized `tei-rapporteur` changes
that provide the spoken-text extraction contract Chrono needs.

The next 2026-05-10 revision adds proposed ADR-006 as the Stage I draft. The
ADR is intentionally not yet accepted, so Stage J and Stage K remain blocked
until reviewers ratify or revise the proposed TEI P5 spoken-text semantics.
