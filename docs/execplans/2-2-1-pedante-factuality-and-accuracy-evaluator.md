# Implement Pedante factuality and accuracy evaluator

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

No `PLANS.md` file is present in the repository root.

Status: DRAFT

## Purpose and big picture

Roadmap item `2.2.1` introduces the first quality assurance evaluator for
generated scripts. After this change, orchestration code will be able to call a
domain-owned Pedante contract that inspects a draft script plus cited source
packets, returns typed findings for unsupported claims and likely inaccuracies,
and passes through normalized `LLMUsage` for later LangGraph cost accounting.

Success is observable in six ways:

1. Unit tests prove the Pedante contract, result parsing, severity mapping, and
   usage-metrics propagation.
2. A small labelled corpus exercises claim-level failure modes such as missing
   citations, misquotation, unsupported inference, and contradiction.
3. Behavioural tests (`pytest-bdd`) run against local Vidai Mock and prove a
   real OpenAI-compatible inference path can return Pedante findings and usage
   metrics deterministically.
4. A minimal LangGraph-backed node returns a stable state delta that can be
   consumed by later orchestration work without changing the Pedante result
   contract.
5. Documentation lands in the design document, user's guide, developer's
   guide, and a new Architecture Decision Record (ADR).
6. The full required gates pass sequentially:
   `make check-fmt`, `make typecheck`, `make lint`, `make test`,
   `PATH=/root/.bun/bin:$PATH make markdownlint`, and `make nixie`.

This plan intentionally stops short of later roadmap items. It does not
implement persisted QA artefacts, the full generation run model, budget-ledger
storage, or the complete multi-evaluator routing graph from `2.4.x` and `2.6.x`.

## Constraints

- Preserve hexagonal-architecture invariants:
  domain-owned evaluator types and interfaces stay free of Falcon, SQLAlchemy,
  LangGraph internals, and provider SDK payload types.
- Treat Pedante as the first evaluator contract, not as a one-off utility.
  Later evaluator implementations must be able to follow the same orchestration
  seam without breaking callers.
- Keep `2.2.1` scoped to factuality and accuracy evaluation only.
  Do not pull in persistence from `2.2.7`, budget reservation from `2.5.x`, or
  generation-run storage from `2.6.x`.
- Use the existing `LLMPort` boundary from `episodic/llm/ports.py`.
  Do not bypass it with direct HTTP calls from Pedante code.
- Keep the initial structured-output path provider-neutral by emitting strict
  JSON text through `LLMPort` and validating it in Pedante code.
- Use test-first workflow for each stage:
  write or update tests first, prove failure, implement code, then rerun the
  same tests to prove success.
- Use Vidai Mock for behavioural inference tests for Pedante.
  Do not add another bespoke HTTP stub for the new evaluator layer.
- Keep claim support evaluation claim-centric.
  Whole-document pass or fail labels are insufficient for this roadmap item.
- Preserve future service-oriented replacement.
  The Pedante orchestration contract must not depend on a specific prompt
  shape, provider transport detail, or LangGraph-only type.
- Update these documents as part of the implementation:
  `docs/episodic-podcast-generation-system-design.md`, `docs/users-guide.md`,
  `docs/developers-guide.md`, `docs/roadmap.md`, and a new ADR in `docs/`.
- Mark roadmap item `2.2.1` done only after code, docs, behavioural tests, and
  all gates are green.

## Tolerances

- Scope: stop and escalate if the implementation exceeds 16 files or 1200 net
  lines before a vertical slice is working.
- Dependencies: stop and escalate if more than one new runtime dependency is
  required. The expected new runtime dependency is `langgraph`; Vidai Mock is
  already available as a local binary.
- Persistence: stop and escalate if Pedante seems to require schema changes or
  stored QA artefacts to be useful. Those belong to later roadmap items.
- Citation model: stop and escalate if the required citation payload cannot be
  defined without changing canonical ingestion storage contracts or TEI
  persistence semantics.
- Contract ambiguity: stop and escalate if the team cannot settle on one stable
  finding schema that distinguishes unsupported claims from likely inaccuracies.
- Iteration budget: stop and escalate after three failed attempts to stabilize
  the same failing test cluster.
- Orchestration: stop and escalate if satisfying the "inside LangGraph"
  requirement would force implementation of the full generation graph rather
  than a minimal node seam.

## Risks

- Risk: the repository has `LLMPort` and an OpenAI-compatible adapter, but no
  existing evaluator package or LangGraph dependency. Severity: high.
  Likelihood: high. Mitigation: add a minimal evaluator package and a single
  LangGraph seam rather than waiting for the later full orchestration work.

- Risk: Pedante can become a vague whole-document reviewer instead of a
  claim-level evaluator. Severity: high. Likelihood: medium. Mitigation: define
  a finding schema around individual claims, cited sources, support level, and
  remediation guidance, then back it with a labelled mutation corpus.

- Risk: the current canonical model does not expose a ready-made TEI citation
  packet specifically for generation QA. Severity: medium. Likelihood: high.
  Mitigation: define a bounded Pedante request DTO that accepts draft text plus
  source packets carrying citation labels, locators, and source excerpts.

- Risk: structured-output parsing can be brittle if the model returns malformed
  JSON or partial fields. Severity: medium. Likelihood: medium. Mitigation:
  validate the response text strictly, return a typed evaluator error, and add
  corpus and Vidai Mock negative cases.

- Risk: the existing behavioural LLM tests use a custom in-process HTTP server,
  while this feature must use Vidai Mock. Severity: medium. Likelihood: medium.
  Mitigation: introduce Pedante-specific Vidai Mock fixtures and keep their
  configuration assets isolated under `tests/fixtures/vidaimock/`.

- Risk: premature routing logic could drag `2.4.x` into scope. Severity:
  medium. Likelihood: medium. Mitigation: limit orchestration coverage to one
  minimal node plus a tiny route decision harness that proves the contract can
  drive refine-versus-pass decisions without implementing the full production
  graph.

## Progress

- [x] (2026-03-18 00:00Z) Reviewed roadmap item `2.2.1`, the existing
  `LLMPort` implementation, prior ExecPlan patterns, documentation style
  requirements, and the `execplans`, `hexagonal-architecture`, and `vidai-mock`
  skills.
- [x] (2026-03-18 00:00Z) Drafted this ExecPlan in
  `docs/execplans/2-2-1-pedante-factuality-and-accuracy-evaluator.md`.
- [ ] Stage A: add fail-first contract and corpus tests for Pedante DTOs and
  parsing.
- [ ] Stage B: implement the Pedante domain contract and request/result types.
- [ ] Stage C: implement the LLM-backed Pedante evaluator adapter and strict
  JSON parsing.
- [ ] Stage D: add the minimal LangGraph node seam and route-contract tests.
- [ ] Stage E: add Vidai Mock behavioural coverage for the inference path.
- [ ] Stage F: update design, ADR, user, developer, and roadmap documents.
- [ ] Stage G: run all repository gates sequentially and confirm completion.

## Surprises & Discoveries

- Observation: `episodic/llm/ports.py` already provides the core provider
  boundary needed for Pedante, including `LLMRequest`, `LLMResponse`, and
  normalized `LLMUsage`. Impact: Pedante should consume `LLMPort` directly
  rather than inventing a new inference seam.

- Observation: the repository does not yet contain an evaluator package, a
  generation package, or any LangGraph runtime code. Impact: `2.2.1` must
  introduce the first evaluator-facing domain seam in a way that does not
  pre-commit the later full orchestration design.

- Observation: `langgraph` is described heavily in the docs but is not present
  in `pyproject.toml`. Impact: the implementation likely needs one new runtime
  dependency and must keep it tightly scoped.

- Observation: `vidaimock` is installed at `/root/.local/bin/vidaimock`.
  Impact: behavioural tests can use the real local simulator instead of an
  ad-hoc HTTP stub.

- Observation: the repo guidance warns not to run `make typecheck` and
  `make test` in parallel because shared `.venv` creation can race. Impact: all
  gates in this plan must run sequentially with `set -o pipefail` and `tee`.

- Observation: there are no existing ADR files in `docs/`. Impact: the new ADR
  can use `adr-001-pedante-evaluator-contract.md` unless another ADR lands
  first on the target branch.

## Decision Log

- Decision: introduce Pedante as a dedicated package under `episodic/qa/`
  rather than burying it inside `episodic/llm/` or a not-yet-real
  generation-run package. Rationale: Pedante is a QA concern that depends on
  `LLMPort`, and keeping it in its own feature-oriented package matches the
  repo's grouping-by-domain guidance while avoiding premature coupling to later
  orchestration persistence. Date/Author: 2026-03-18 / Codex.

- Decision: keep the first stable contract claim-centric, with one evaluation
  result containing typed findings plus normalized usage metrics. Rationale:
  this matches the roadmap requirement and the supplied benchmarking guidance,
  which emphasizes claim-level precision and recall over whole-document labels.
  Date/Author: 2026-03-18 / Codex.

- Decision: use strict JSON-over-`LLMPort` for structured findings rather than
  changing `LLMPort` again immediately. Rationale: the current port already
  exists, and Pedante can validate the response text locally while preserving a
  provider-neutral orchestration contract. Date/Author: 2026-03-18 / Codex.

- Decision: implement only a minimal LangGraph node seam now. Rationale: the
  roadmap explicitly places the broader suspend/resume orchestration and
  routing graph work in later steps, but `2.2.1` still needs a concrete
  node-shaped contract to avoid painting the future graph into a corner.
  Date/Author: 2026-03-18 / Codex.

- Decision: use Vidai Mock for Pedante behavioural tests even though older LLM
  adapter BDD coverage uses a custom server. Rationale: this task explicitly
  requires Vidai Mock, and the evaluator layer is the right point to introduce
  that harness without broad collateral changes. Date/Author: 2026-03-18 /
  Codex.

## Outcomes & Retrospective

Implementation has not started yet. The intended completed state is:

- `episodic/qa/` owns a stable Pedante request and result contract.
- Pedante returns structured factuality findings and normalized usage metrics.
- A minimal LangGraph node produces a deterministic state delta that later
  orchestration work can consume unchanged.
- Behavioural tests use Vidai Mock to validate the live inference path.
- The design document references an accepted ADR for the Pedante contract.
- `docs/roadmap.md` marks `2.2.1` done only after all required gates pass.

Retrospective notes will be added after implementation, including any prompt
stability issues, corpus gaps, or LangGraph integration friction encountered.

## Context and orientation

Current implementation baseline:

- `episodic/llm/ports.py` defines `LLMPort`, `LLMRequest`, `LLMResponse`,
  `LLMTokenBudget`, and `LLMUsage`.
- `episodic/llm/openai_adapter.py` provides a working OpenAI-compatible async
  adapter with retries and token-budget enforcement.
- `tests/test_llm_openai_adapter_*.py` already cover the transport boundary
  thoroughly.
- `tests/features/llm_adapter.feature` and
  `tests/steps/test_llm_adapter_steps.py` demonstrate the existing BDD style,
  even though the new Pedante behaviour layer should use Vidai Mock instead of
  another custom HTTP server.
- `docs/episodic-podcast-generation-system-design.md` defines the QA stack,
  LangGraph integration principles, and the rule that orchestration code
  depends on ports only.
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` warns against graph
  nodes or Celery tasks importing adapters directly or storing domain truth in
  graph state blobs.
- `docs/cost-management-in-langgraph-agentic-systems.md` makes normalized
  usage metrics and state-level cost accumulation explicit design inputs.

Likely implementation touchpoints:

- `pyproject.toml`
- `episodic/qa/__init__.py`
- `episodic/qa/types.py`
- `episodic/qa/pedante.py`
- `episodic/qa/langgraph.py`
- `tests/test_pedante_types.py`
- `tests/test_pedante_evaluator.py`
- `tests/test_pedante_langgraph.py`
- `tests/features/pedante.feature`
- `tests/steps/test_pedante_steps.py`
- `tests/fixtures/pedante_cases/`
- `tests/fixtures/vidaimock/pedante/`
- `docs/adr-001-pedante-evaluator-contract.md`
- `docs/episodic-podcast-generation-system-design.md`
- `docs/users-guide.md`
- `docs/developers-guide.md`
- `docs/roadmap.md`

Terms used in this plan:

- Claim: one factual assertion made in the draft script that Pedante can test
  against cited sources.
- Source packet: the bounded input Pedante receives for one cited source,
  including at least a citation label, locator, and source excerpt or summary.
- Support level: Pedante's classification of how well a cited source supports
  a claim, such as accurate quotation, citation absent, or unsupported
  inference.
- Finding: one typed Pedante result for one claim, including severity,
  rationale, and remediation guidance.

## Plan of work

### Stage A: lock the Pedante contract with fail-first tests

Start by adding tests before any Pedante production code exists. The goal is to
make the evaluator contract concrete and reviewable before a single prompt or
adapter helper is implemented.

Add unit tests that define the request and result DTOs and the evaluator
semantics. The contract should stay small and explicit:

- `PedanteEvaluationRequest`
- `PedanteSourcePacket`
- `PedanteFinding`
- `PedanteEvaluation`
- enums for claim kind, support level, and severity

The finding schema should carry, at minimum:

- the claim excerpt,
- the claim kind (`direct_quote`, `transplanted_claim`, or `inference`),
- the cited source labels Pedante believes are relevant,
- a support-level classification,
- severity,
- rationale text, and
- remediation guidance.

Also add a small labelled corpus under `tests/fixtures/pedante_cases/`. Keep
the first slice intentionally small but adversarial:

- supported quotation,
- citation absent,
- misquotation,
- plausible restatement,
- unsupported inference,
- contradictory claim,
- numeric or date drift.

The corpus should be mutation-based where possible: start from a supported
source-backed excerpt, then alter one fact at a time so the evaluator must
distinguish the exact defect rather than wave at the whole paragraph.

Acceptance for Stage A:

- The new tests fail because the types and evaluator do not exist yet.
- The expected finding schema and support classifications are explicit in test
  assertions, not buried in comments.

### Stage B: implement the Pedante domain contract

Create `episodic/qa/` as the new feature package. Keep it small and explicit.

`episodic/qa/types.py` should define the stable types. Prefer frozen
dataclasses and `enum.StrEnum` values, following the existing style in
`episodic/canonical/domain.py` and `episodic/llm/ports.py`. Avoid `Any`,
framework imports, and open-ended `dict[str, object]` blobs except where raw
JSON parsing truly requires them.

`episodic/qa/pedante.py` should define the Pedante-facing protocol and service
entrypoint. The recommended surface is:

- a small protocol such as `PedantePort` with
  `async def evaluate(request: PedanteEvaluationRequest) -> PedanteEvaluation`,
  or
- a concrete `PedanteEvaluator` service whose constructor accepts an
  `LLMPort`.

Keep the outward contract evaluator-specific for now rather than introducing a
generic "all evaluators" abstraction too early. The shared concepts such as
severity can still live in `types.py` and be reused later by Bromide, Chiltern,
Anthem, and Caesura.

Acceptance for Stage B:

- Stage A contract tests pass.
- No Pedante domain type imports Falcon, SQLAlchemy, LangGraph, or `httpx`.
- The public shape is small enough that later evaluator implementations can
  mirror it without a breaking redesign.

### Stage C: implement the LLM-backed evaluator and strict parser

Add the actual Pedante service implementation in `episodic/qa/pedante.py`. This
service should:

1. build a provider-neutral Pedante prompt from the request DTO,
2. send it through `LLMPort.generate(...)`,
3. parse the returned text as strict JSON,
4. validate the JSON into `PedanteFinding` instances, and
5. return `PedanteEvaluation` with the unmodified `LLMUsage` from the
   `LLMResponse`.

Do not change the `LLMPort` contract again for this step. The prompt should
instruct the model to emit only the agreed JSON envelope. The parser should
raise a typed Pedante-specific error if the JSON is malformed, missing required
fields, or contains unsupported enum values.

Keep the prompt-building helper pure and local to Pedante. A helper such as
`build_pedante_prompt(...)` can live beside the evaluator. There is no need to
invent a separate prompt templating subsystem for one evaluator.

Use the labelled corpus from Stage A to drive the implementation. Add
parameterized tests that exercise:

- JSON validation success,
- malformed JSON,
- missing required finding fields,
- correct severity mapping for strong fail versus pass cases, and
- usage-metrics pass-through from `LLMResponse.usage`.

Acceptance for Stage C:

- Corpus-driven unit tests pass.
- The evaluator returns findings and usage metrics without leaking provider
  payload shapes.
- Parser failures are deterministic and typed.

### Stage D: add the minimal LangGraph seam

Add `langgraph` to `pyproject.toml` if it is still absent. Keep this as the
only new runtime dependency unless a hard blocker emerges.

Create `episodic/qa/langgraph.py` with the smallest useful surface:

- a Pedante node function that accepts a state mapping or typed state object,
- calls the Pedante evaluator through its domain contract, and
- returns a state delta containing the evaluation result and normalized usage
  metrics.

Keep production routing logic out of scope. The only orchestration helper worth
adding now is a tiny pure function such as
`should_request_refinement(evaluation: PedanteEvaluation) -> bool`, if a
separate predicate simplifies testing and future graph integration.

Add tests that prove:

- the node depends on the evaluator contract, not a concrete adapter,
- the node emits a deterministic state delta,
- severe Pedante findings can drive a simple refine-versus-pass branch in a
  tiny test harness graph, and
- parallel-merge concerns are contained because the node writes only its own
  namespaced result fields.

Acceptance for Stage D:

- LangGraph is introduced only at the orchestration seam.
- The node contract is stable enough to reuse in later `2.4.x` work.
- No full generation graph, persistence layer, or Celery workflow is added.

### Stage E: add Vidai Mock behavioural coverage

Build Pedante behavioural tests with Vidai Mock rather than a custom HTTP
server. Use the simulator assets under `tests/fixtures/vidaimock/pedante/`,
following the workspace pattern from the `vidai-mock` skill:

- `mock-server.toml`
- `config/providers/openai.yaml`
- `config/templates/openai/...`

Add a pytest fixture that:

1. confirms `vidaimock` is available,
2. starts it on a test-local port,
3. points `OpenAICompatibleLLMAdapter` at the local `/v1` base URL, and
4. shuts the server down cleanly after the scenario.

Add `pytest-bdd` scenarios in `tests/features/pedante.feature` that prove:

1. Pedante returns a structured unsupported-claim finding with usage metrics
   from a real inference path.
2. Pedante returns no failing findings for a clearly supported claim set.
3. A malformed or adversarial structured-output response is rejected cleanly.

If it remains cheap, add one deterministic chaos scenario using request-level
Vidai Mock controls to inject malformed JSON or a transient 500. Keep the
failure explicit and reproducible; do not rely on random chaos in CI.

Acceptance for Stage E:

- Pedante BDD coverage uses Vidai Mock.
- Behavioural tests exercise the real `LLMPort` adapter path.
- The behavioural layer proves both findings shape and usage propagation.

### Stage F: update documentation and roadmap state

Add a new ADR at `docs/adr-001-pedante-evaluator-contract.md` unless another
ADR number is consumed first. The ADR should record:

- why Pedante is claim-centric,
- why the first contract uses JSON-over-`LLMPort`,
- why the evaluator lives in `episodic/qa/`,
- why the initial orchestration surface is a minimal LangGraph node, and
- what remains intentionally deferred.

Update `docs/episodic-podcast-generation-system-design.md` in the Quality
Assurance Stack section to reference the ADR and describe the concrete Pedante
contract now present in code.

Update `docs/users-guide.md` with a short user-facing explanation of what
Pedante checks before editorial review and what kinds of findings users should
expect.

Update `docs/developers-guide.md` with maintainer-facing instructions covering:

- where the Pedante contract lives,
- how to add new corpus cases,
- how to run Pedante unit and behavioural tests, and
- how Vidai Mock is configured for this evaluator.

Update `docs/roadmap.md` by marking `2.2.1` done only after all code and
validation work is complete.

Acceptance for Stage F:

- The ADR follows the documentation style guide exactly.
- The design, user, and developer docs are synchronized with the implementation.
- The roadmap entry changes only at the very end.

### Stage G: run the full validation gates

Run repository gates sequentially and capture logs with `tee`. Do not run
`make typecheck` and `make test` in parallel.

Use this exact pattern:

```plaintext
set -o pipefail
make fmt 2>&1 | tee /tmp/pedante-make-fmt.log
```

```plaintext
set -o pipefail
make check-fmt 2>&1 | tee /tmp/pedante-make-check-fmt.log
```

```plaintext
set -o pipefail
make typecheck 2>&1 | tee /tmp/pedante-make-typecheck.log
```

```plaintext
set -o pipefail
make lint 2>&1 | tee /tmp/pedante-make-lint.log
```

```plaintext
set -o pipefail
make test 2>&1 | tee /tmp/pedante-make-test.log
```

```plaintext
set -o pipefail
PATH=/root/.bun/bin:$PATH make markdownlint 2>&1 | tee /tmp/pedante-make-markdownlint.log
```

```plaintext
set -o pipefail
make nixie 2>&1 | tee /tmp/pedante-make-nixie.log
```

Only after all gates pass should the implementation:

- mark roadmap item `2.2.1` done,
- update this ExecPlan's `Status` to `COMPLETE`, and
- fill in the final `Outcomes & Retrospective`.

## Concrete implementation steps

1. Add fail-first tests for Pedante DTOs, parsing, corpus cases, and the
   minimal LangGraph seam.

```plaintext
pytest tests/test_pedante_types.py tests/test_pedante_evaluator.py tests/test_pedante_langgraph.py -q
```

1. Add the labelled corpus and Pedante package under `episodic/qa/`.

```plaintext
mkdir -p tests/fixtures/pedante_cases
```

1. Implement the Pedante types and evaluator against `LLMPort`.

```plaintext
pytest tests/test_pedante_types.py tests/test_pedante_evaluator.py -q
```

1. Add the minimal LangGraph node and route-contract tests.

```plaintext
pytest tests/test_pedante_langgraph.py -q
```

1. Add Vidai Mock fixtures and `pytest-bdd` coverage.

```plaintext
pytest tests/steps/test_pedante_steps.py -q
```

1. Update the ADR, design document, user's guide, developer's guide, and
   roadmap.

```plaintext
PATH=/root/.bun/bin:$PATH make markdownlint
```

1. Run the full gate sequence from Stage G.

## Validation and acceptance

The feature is complete only when all of the following are true:

- `episodic/qa/` exposes a stable Pedante contract with typed request and
  result DTOs.
- Pedante returns structured findings for unsupported claims and likely
  inaccuracies.
- Pedante returns normalized `LLMUsage` metrics unchanged from the underlying
  `LLMPort` response.
- A minimal LangGraph node returns a deterministic state delta that later
  orchestration work can consume without a contract change.
- Unit tests cover the contract, parser, and labelled corpus.
- Behavioural tests use Vidai Mock and cover the live inference path.
- Documentation is updated in the ADR, design, user, and developer docs.
- `docs/roadmap.md` marks `2.2.1` done.
- `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie` all succeed.

## Idempotence and recovery

This plan is safe to execute incrementally.

- The labelled corpus and Vidai Mock fixtures are additive.
- The Pedante package can be developed behind fail-first tests without touching
  unrelated feature areas.
- If a gate fails, fix the underlying issue and rerun only the failing command,
  then rerun the full Stage G sequence before marking completion.
- If Vidai Mock startup proves unstable, pause at the behavioural-testing
  tolerance gate rather than silently replacing it with another harness.
- If `langgraph` introduces dependency friction, pause at the dependency
  tolerance gate rather than re-implementing a fake graph abstraction.

## Artifacts and notes

Expected logs:

- `/tmp/pedante-make-fmt.log`
- `/tmp/pedante-make-check-fmt.log`
- `/tmp/pedante-make-typecheck.log`
- `/tmp/pedante-make-lint.log`
- `/tmp/pedante-make-test.log`
- `/tmp/pedante-make-markdownlint.log`
- `/tmp/pedante-make-nixie.log`

Expected new long-lived project artifacts:

- `tests/fixtures/pedante_cases/*`
- `tests/fixtures/vidaimock/pedante/*`
- `docs/adr-001-pedante-evaluator-contract.md`

Example success indicators:

```plaintext
pytest tests/test_pedante_evaluator.py -q
...
N passed
```

```plaintext
pytest tests/steps/test_pedante_steps.py -q
...
1 passed
```

```plaintext
make test
...
passed
```

## Revision note

Initial draft created on 2026-03-18 for roadmap item `2.2.1` before any
implementation work begins. This plan requires explicit approval before
execution.
