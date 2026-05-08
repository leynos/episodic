# Implement Chrono Runtime Estimation

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: DRAFT

## Purpose / big picture

Chrono is the quality-assurance runtime estimator for generated podcast
scripts. It predicts how long written dialogue will take to speak before a
draft reaches editorial approval. Unlike Pedante, Bromide, Chiltern, Anthem,
and Caesura, Chrono is not a Large Language Model (LLM) evaluator. It is a
deterministic local estimator that returns a runtime estimate plus metadata
describing the heuristic version, input size, and assumptions used.

After this change, orchestration code should be able to call a Chrono evaluator
from the QA layer and receive a typed result that can later be aggregated with
LLM-backed evaluator outputs. A user or developer can observe success by
running the unit and behavioural tests: the tests should show that Chrono
extracts dialogue from a Text Encoding Initiative (TEI) script, applies a
documented words-per-minute heuristic, records comparable metadata, and
participates in the LangGraph QA seam without invoking `LLMPort`.

This plan is intentionally written to
`docs/execplans/2-2-1-pedante-factuality-and-accuracy-evaluator.md` because
that path was requested explicitly. The implementation scope is roadmap task
`2.2.6. Implement Chrono for runtime estimation`, not Pedante task `2.2.1`.

## Constraints

- Preserve the roadmap scope: implement task `2.2.6` only. Do not expand this
  work into persistence of QA artefacts; that remains task `2.2.7`.
- Keep Chrono non-LLM. It must not import or call `episodic.llm.LLMPort`, Vidai
  Mock client code, OpenAI adapters, or any external inference provider.
- Follow the hexagonal architecture dependency rule. Domain and application
  logic may define Chrono request/result types and heuristic policy, whilst
  LangGraph code remains an orchestration adapter around those contracts.
- Keep the first estimator deliberately naive and local. The accepted baseline
  is a words-per-minute heuristic over spoken dialogue, with estimator metadata
  making the assumption explicit so later estimators remain comparable.
- Keep TEI as the canonical script input. Chrono may parse TEI XML locally to
  extract spoken text, but it must not introduce a competing canonical script
  schema.
- Keep metadata stable enough for future comparison. At minimum, record
  estimator name, estimator version, words-per-minute assumption, dialogue word
  count, input character count, and whether non-dialogue text was ignored.
- Use test-first delivery. Add or update pytest and pytest-bdd coverage before
  implementing each behaviour, observe the expected failure, then implement.
- Use property tests with Hypothesis for estimator invariants over ranges of
  dialogue text, such as non-negative durations and monotonicity as words are
  added.
- Update relevant documentation:
  `docs/episodic-podcast-generation-system-design.md`
  for the design decision, `docs/users-guide.md` for any user-visible QA
  behaviour, and the relevant developer or component architecture document for
  internal interfaces.
- On completion, mark roadmap task `2.2.6` in `docs/roadmap.md` as done.
- Run all requested gates sequentially, not in parallel:
  `make check-fmt`, `make typecheck`, `make lint`, and `make test`. For
  Markdown changes, also run `make markdownlint` and `make nixie`.
- Commit each completed logical change only after its gates pass.

## Tolerances

- Stop and escalate if implementing Chrono requires changing existing Pedante
  public types, LLM adapter contracts, or generation orchestration public
  inputs.
- Stop and escalate if the work appears to require database migrations or
  durable persistence changes; those belong to roadmap task `2.2.7`.
- Stop and escalate if TEI parsing cannot be implemented with the existing
  standard library or already-pinned dependencies.
- Stop and escalate before adding any new runtime dependency.
- Stop and escalate if the implementation grows beyond 10 files or 650 net new
  lines before a working vertical slice exists.
- Stop and escalate if the naive heuristic cannot be documented in one
  clear formula.
- Stop and escalate after three failed attempts to make the same test cluster
  pass.

## Risks

- Risk: the current QA package is centred on Pedante, so adding Chrono may
  invite copy-pasting LLM-backed result shapes that do not fit a deterministic
  estimator. Mitigation: define Chrono-specific request, result, and metadata
  types first, with no usage metrics field unless the orchestration contract
  already requires one.

- Risk: TEI scripts may contain show notes, headings, stage directions, or
  metadata that should not count as spoken dialogue. Mitigation: start with a
  documented extraction policy that counts text under likely speech-bearing
  body elements and ignores TEI header content; add tests for header and note
  exclusion.

- Risk: the naive words-per-minute value can look more precise than it is.
  Mitigation: return seconds as an estimate, expose the words-per-minute value
  and heuristic version in metadata, and avoid claims of audio-accurate timing.

- Risk: future evaluators need a shared QA graph state, but the current seam is
  named around Pedante. Mitigation: keep the first Chrono LangGraph seam small
  and compatible with the existing module layout; only generalise names when
  tests prove a shared abstraction removes real duplication.

- Risk: behavioural tests mention Vidai Mock because LLM evaluators use it,
  but Chrono must not. Mitigation: add a behavioural scenario that proves a QA
  run can estimate runtime without any inference call; if existing Vidai Mock
  fixtures are reused, assert they receive zero requests.

## Progress

- [x] (2026-05-08 00:00Z) Read `AGENTS.md`, `docs/roadmap.md`, the QA design
  section in `docs/episodic-podcast-generation-system-design.md`, and the
  current Pedante QA implementation for orientation.
- [x] (2026-05-08 00:00Z) Loaded the `execplans`, `hexagonal-architecture`,
  and `leta` skills. `leta workspace add` succeeded, but the daemon failed to
  start, so repository orientation fell back to shell inspection.
- [x] (2026-05-08 00:00Z) Confirmed the branch is
  `feat/plan-chrono-evaluator`, not a main branch.
- [ ] Stage A: add failing unit tests for Chrono request validation, dialogue
  extraction, runtime calculation, and metadata.
- [ ] Stage B: add failing Hypothesis property tests for estimator invariants.
- [ ] Stage C: implement Chrono domain/application types and the naive local
  estimator.
- [ ] Stage D: add and satisfy a LangGraph seam test for invoking Chrono as a
  QA node without `LLMPort`.
- [ ] Stage E: add and satisfy pytest-bdd behavioural coverage for runtime
  estimation, including a zero-inference assertion when Vidai Mock fixtures are
  present.
- [ ] Stage F: update the design document, users' guide, developer/component
  documentation, and roadmap checkbox.
- [ ] Stage G: run the full sequential validation gates and commit the
  completed implementation.

## Surprises & Discoveries

- The requested output path already existed and contained a Pedante follow-up
  plan. The current request explicitly names the same path for Chrono, so this
  plan replaces that content while documenting the scope mismatch.
- `docs/roadmap.md` marks `2.2.1` Pedante done and `2.2.6` Chrono pending.
  The implementation must update `2.2.6`, not reopen or alter Pedante.
- The existing QA code is currently concentrated in `episodic/qa/pedante.py`
  and `episodic/qa/langgraph.py`. There is no Chrono module yet.
- The design document already states that Chrono is local, records estimator
  version, input size, and predicted runtime, and is used alongside evaluator
  scores for QA routing.

## Decision Log

- Decision: implement Chrono as deterministic QA policy rather than an
  inference adapter. Rationale: the roadmap and design document both define
  Chrono as a non-LLM runtime estimator. Date/Author: 2026-05-08 / Codex.

- Decision: keep the first formula simple: estimate spoken runtime from a
  configurable or constant words-per-minute value and extracted dialogue word
  count. Rationale: the roadmap asks for an initial naive local heuristic, and
  metadata makes future estimator comparisons possible. Date/Author: 2026-05-08
  / Codex.

- Decision: treat QA persistence as out of scope. Rationale: roadmap task
  `2.2.7` explicitly owns persisted QA artefacts, and pulling persistence into
  Chrono would expand the blast radius. Date/Author: 2026-05-08 / Codex.

- Decision: include a behavioural zero-inference assertion rather than using
  Vidai Mock to fake Chrono output. Rationale: the user requires Vidai Mock for
  behavioural testing of inference services, but Chrono is specifically not an
  inference service. Date/Author: 2026-05-08 / Codex.

## Implementation Plan

Stage A starts with unit tests in a new file such as `tests/test_chrono.py`.
Create tests for invalid blank TEI input, extraction that ignores `teiHeader`,
counting of normal dialogue words, deterministic runtime calculation, and
metadata fields. Use clear fixture XML with a `TEI` root, `teiHeader`, and
`text/body` dialogue content.

Stage B adds property tests, either in `tests/test_chrono.py` or a focused
`tests/test_chrono_properties.py`. Generate simple word lists with Hypothesis
and assert that estimated seconds are never negative, empty spoken text
produces zero seconds, and adding words never decreases the estimate when the
words-per-minute setting is unchanged.

Stage C implements the Chrono types and estimator in a new module such as
`episodic/qa/chrono.py`. Keep the module free of framework, database, network,
and LLM imports. A suitable shape is `ChronoEvaluationRequest`,
`ChronoEstimatorMetadata`, `ChronoRuntimeEstimate`, and `ChronoEstimator`.
Represent duration in seconds as an integer or decimal value, but document the
choice. Prefer a stable estimator version string such as `chrono-naive-wpm-v1`.

Stage D extends the QA LangGraph seam. Either add Chrono-specific graph state
and node functions beside the existing Pedante seam in
`episodic/qa/langgraph.py` or create a small `episodic/qa/chrono_langgraph.py`
module if that keeps names clearer. The graph node should accept a Chrono
request, call the estimator, and return a state delta containing the runtime
estimate.

Stage E adds behavioural coverage. Create `tests/features/chrono.feature` and
`tests/steps/test_chrono_steps.py`, or extend an existing QA feature only if it
remains readable. The scenario should say that a generated TEI script with
dialogue is evaluated by Chrono and the result includes an estimated runtime
and metadata. If Vidai Mock fixtures are part of the scenario setup, assert
that no LLM request was sent.

Stage F updates documentation. In
`docs/episodic-podcast-generation-system-design.md`, add the exact initial
heuristic and metadata contract near the Quality Assurance Stack or internal
evaluator metering sections. In `docs/users-guide.md`, describe that generated
draft QA now includes an estimated spoken runtime when that workflow is
surfaced. In the relevant developer/component document, record how to call the
Chrono estimator and where it fits in the hexagonal boundary. Finally, change
the roadmap checkbox for `2.2.6` from `[ ]` to `[x]`.

Stage G validates sequentially. Run the narrow tests first while developing,
then the full gates:

```plaintext
pytest tests/test_chrono.py
pytest tests/features/chrono.feature
make check-fmt
make typecheck
make lint
make test
make markdownlint
make nixie
```

For long-running gate commands, tee output into `/tmp` using the repository
convention, for example:

```plaintext
make test 2>&1 | tee /tmp/test-episodic-feat-plan-chrono-evaluator.out
```

When all gates pass, stage the touched files and commit with an imperative
message such as `Implement Chrono runtime estimator`.

## Validation

The implementation is complete only when all of the following are true:

- `pytest` unit tests cover Chrono validation, extraction, calculation, and
  metadata.
- Hypothesis property tests cover non-negative and monotonic runtime estimates.
- `pytest-bdd` behavioural tests prove runtime estimation from TEI dialogue.
- Chrono does not import `episodic.llm`, provider adapters, Falcon, SQLAlchemy,
  or Celery.
- Documentation names the initial heuristic and explains that it is a local
  estimate, not measured audio duration.
- `docs/roadmap.md` marks `2.2.6` done.
- `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie` pass sequentially.

## Outcomes & Retrospective

Not started. Record the final implemented files, validation evidence, commit
hash, and any follow-up work here after implementation.
