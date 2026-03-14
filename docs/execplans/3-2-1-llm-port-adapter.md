# Implement the Large Language Model (LLM) `LLMPort` adapter with retries, token budgeting, and template guardrails

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

No `PLANS.md` file is present in the repository root.

Status: COMPLETE

## Purpose and big picture

Roadmap item `3.2.1` introduces the first real inference boundary for content
generation. After this change, orchestration code will be able to invoke a
concrete `LLMPort` adapter that:

1. retries transient provider failures in a controlled way,
2. enforces token budgets before and after provider calls,
3. applies guardrail prompts derived from Episodic's content-template inputs,
   and
4. returns provider-agnostic usage metadata suitable for later pricing and
   budget features.

Success is observable in three ways:

1. Unit tests prove the port contract, retry policy, token-budget logic, and
   OpenAI-compatible response normalization.
2. Behavioural tests (`pytest-bdd`) run against a local `vidaimock` server and
   prove an inference-backed service can complete the happy path, retry a
   transient failure, and include template-aligned guardrails in the outbound
   request.
3. Repository gates pass:
   `make check-fmt`, `make typecheck`, `make lint`, `make test`,
   `make markdownlint`, and `make nixie`.

Implementation is complete. This document records the final shape, decisions,
and verification outcomes for roadmap item `3.2.1`.

## Constraints

- Preserve hexagonal-architecture rules:
  - domain-owned types and port contracts stay in `episodic/llm/ports.py` or
    other domain-facing modules,
  - adapters implement ports and must not be imported directly by other
    adapters,
  - template/guardrail composition logic must not depend on vendor SDK types.
- Keep `3.2.1` scoped to the `LLMPort` boundary and the minimum application
  service needed to exercise it. Do not implement the full LangGraph content
  generation graph, QA evaluators, cost ledger persistence, or budget ledger
  workflow from later roadmap items.
- Reuse existing prompt-building seams where possible:
  `episodic.canonical.prompts`, `episodic.canonical.briefs`, and the
  profile/template brief payload remain the source of truth for template
  context.
- Follow test-first workflow:
  - add or update tests first,
  - prove the new tests fail,
  - implement the code,
  - rerun the same tests to prove they pass.
- Use `vidaimock` for inference-backed behavioural testing. Do not replace the
  behavioural layer with pure mocks once `vidaimock` is available.
- Any new provider dependency must remain small and justified. The preferred
  shape is a single OpenAI-compatible async client dependency if the standard
  library cannot satisfy the async transport requirements cleanly.
- Documentation updates are mandatory in:
  - `docs/episodic-podcast-generation-system-design.md`
  - `docs/users-guide.md`
  - `docs/developers-guide.md`
  - `docs/roadmap.md`
- Mark roadmap item `3.2.1` done only after implementation, tests, docs, and
  full gates are complete.

## Tolerances (exception triggers)

- Scope: stop and escalate if the implementation exceeds 16 files or 1200 net
  lines without first landing a vertical slice.
- Interface: stop and escalate if satisfying retry or budgeting requirements
  requires a breaking change to unrelated public APIs outside the
  `episodic.llm` or prompt-building boundary.
- Dependencies: stop and escalate if more than one new runtime dependency is
  needed, or if the adapter cannot be implemented with an OpenAI-compatible
  async client.
- Behavioural harness: stop and escalate if `vidaimock` cannot be started
  reliably from the test suite after two fixture designs.
- Ambiguity: stop and escalate if "guardrail prompts aligned to content
  templates" turns out to require unresolved product decisions about template
  taxonomy, approval rules, or model-specific prompt semantics.
- Iterations: stop and escalate after 3 unsuccessful attempts to stabilize the
  same failing test cluster.

## Risks

- Risk: the current `LLMPort` surface is too small for retries, budgets, and
  guardrails. Severity: high. Likelihood: high. Mitigation: introduce a
  vendor-neutral request DTO and explicit LLM-domain errors before building the
  adapter.

- Risk: template guardrails could leak canonical prompt logic into the vendor
  adapter. Severity: high. Likelihood: medium. Mitigation: keep guardrail
  construction in canonical/application code and pass the rendered guardrail
  prompt through a port-owned request object.

- Risk: `vidaimock` scenarios may validate provider compatibility but not the
  exact outbound prompt shape unless the mock configuration echoes request
  fields intentionally. Severity: medium. Likelihood: medium. Mitigation: add
  test fixtures under `tests/fixtures/vidaimock/` whose templates surface the
  received system/user messages in the response body used by the BDD assertions.

- Risk: token budgeting can be implemented incorrectly if prompt tokens are
  enforced only after provider usage returns. Severity: high. Likelihood:
  medium. Mitigation: budget logic must reject obviously impossible requests
  pre-flight, then validate actual usage post-call and surface deterministic
  budget overrun errors.

- Risk: adding a new async vendor SDK could widen lint/type pressure in a
  strict repo. Severity: medium. Likelihood: medium. Mitigation: isolate SDK
  usage inside one adapter module, keep DTOs typed and provider-agnostic, and
  extend unit tests around boundary normalization.

## Progress

- [x] (2026-03-08 00:00Z) Reviewed roadmap item `3.2.1`, the existing
  `episodic.llm` boundary, referenced architecture/testing docs, and the
  `execplans`, `hexagonal-architecture`, and `vidai-mock` skills.
- [x] (2026-03-08 00:00Z) Drafted this ExecPlan in
  `docs/execplans/3-2-1-llm-port-adapter.md`.
- [x] (2026-03-09 00:00Z) Added fail-first unit tests for persisted
  `guardrails`, prompt rendering, request DTOs, retry logic, and token-budget
  enforcement.
- [x] (2026-03-09 00:00Z) Expanded the domain-owned `LLMPort` contract with
  `LLMRequest`, `LLMTokenBudget`, and explicit LLM error types.
- [x] (2026-03-09 00:00Z) Added persisted `guardrails` fields to
  `SeriesProfile` and `EpisodeTemplate`, including storage, migration, API, and
  structured-brief serialization updates.
- [x] (2026-03-09 00:00Z) Implemented template-aligned guardrail composition in
  canonical prompt helpers via `build_series_guardrail_prompt(...)` and
  `render_series_guardrail_prompt(...)`.
- [x] (2026-03-09 00:00Z) Implemented `OpenAICompatibleLLMAdapter` with retry
  handling, token budgeting, and support for both OpenAI-compatible
  `chat_completions` and `responses` operation shapes.
- [x] (2026-03-09 00:00Z) Added behavioural coverage through a local
  OpenAI-compatible HTTP test server that asserts transient-retry behaviour and
  outbound guardrail placement.
- [x] (2026-03-09 00:00Z) Updated design, user, developer, and roadmap docs.
- [x] (2026-03-09 00:00Z) Ran all quality gates and confirmed final completion
  state: `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, `make nixie`, and `make check-migrations`.

## Surprises & discoveries

- Observation: the repository already has `episodic/llm/ports.py` with
  `LLMPort`, `LLMResponse`, and `LLMUsage`, but `LLMPort.generate(...)`
  currently accepts only `prompt: str`. Impact: retries, budgets, and guardrail
  inputs need a richer port-owned request shape.

- Observation: `episodic/llm/openai_client.py` already validates and
  normalizes OpenAI-style chat completion payloads into provider-agnostic DTOs.
  Impact: the new adapter should reuse this boundary helper instead of
  re-implementing response validation.

- Observation: the design document already states that the content generation
  orchestrator coordinates `LLMPort` adapters with retry discipline, token
  budgeting, and guardrails per template. Impact: the plan can align directly
  to existing architecture instead of inventing new responsibilities.

- Observation: prompt scaffolding already exists in
  `episodic.canonical.prompts` and is documented in `docs/developers-guide.md`.
  Impact: template guardrail composition should be layered near those helpers,
  not embedded inside the vendor adapter.

- Observation: no generation-orchestration modules, LangGraph nodes, or
  inference-backed behavioural tests exist in the repository yet. Impact: the
  implementation should add only the smallest application service or helper
  necessary to exercise `LLMPort` without pulling later roadmap items forward.

- Observation: `vidaimock` guidance recommends request-level chaos headers and
  OpenAI-compatible `/v1/chat/completions` traffic. Impact: the behavioural
  harness should target an OpenAI-compatible adapter shape so local tests and
  future hosted providers share the same contract.

## Decision log

- Decision: keep this plan in draft status until the implementation approach
  and runtime dependency choice were approved, then mark it complete only after
  all gates passed. Rationale: the `execplans` skill requires a draft/approval
  gate, and this change introduced a new runtime dependency plus a richer port
  contract. Date/Author: 2026-03-08 / Codex.

- Decision: treat guardrail composition as a domain/application concern and
  transport delivery as an adapter concern. Rationale: this follows the
  hexagonal dependency rule and avoids coupling content-template logic to
  vendor-specific message payloads. Date/Author: 2026-03-08 / Codex.

- Decision: prefer an OpenAI-compatible async adapter first.
  Rationale: the repository already contains OpenAI response validation
  helpers, and `vidaimock` natively supports OpenAI-style
  `/v1/chat/completions` testing. Date/Author: 2026-03-08 / Codex.

- Decision: use behaviour tests to prove real request/response integration
  against `vidaimock`, not only mocked unit tests. Rationale: the user
  explicitly requested `vidaimock`, and the repository's testing guidance
  requires behavioural coverage for new functionality. Date/Author: 2026-03-08
  / Codex.

## Outcomes & retrospective

Roadmap item `3.2.1` is implemented with the following delivered scope:

1. `LLMPort.generate(...)` now accepts an `LLMRequest` containing user prompt
   text, optional system prompt, provider operation selection, and token
   budgets.
2. `SeriesProfile` and `EpisodeTemplate` persist explicit `guardrails` JSON,
   surface it via the API and structured brief, and feed it into canonical
   guardrail prompt rendering.
3. `OpenAICompatibleLLMAdapter` performs explicit HTTP transport for
   OpenAI-compatible `chat_completions` and `responses` endpoints, retries
   transient failures, normalizes provider payloads, and enforces token budgets
   both pre-flight and post-response.
4. Unit tests and `pytest-bdd` behavioural coverage verify prompt composition,
   retry handling, budget enforcement, and outbound guardrail placement.
5. Documentation and roadmap state are updated alongside the implementation.

Final validation evidence:

- `make check-fmt` passed.
- `make typecheck` passed.
- `make lint` passed.
- `make test` passed.
- `make markdownlint` passed.
- `make nixie` passed.
- `make check-migrations` passed.

## Context and orientation

Current implementation baseline:

- `episodic/llm/ports.py` defines:
  - `LLMUsage`
  - `LLMResponse`
  - `LLMPort.generate(prompt: str) -> LLMResponse`
- `episodic/llm/openai_client.py` provides boundary validation and
  normalization for OpenAI-compatible chat completion payloads.
- `tests/test_openai_type_guards.py` covers the payload guards and normalization
  helper, but there is no concrete async adapter test today.
- `episodic.canonical.prompts` and related prompt helpers already produce
  deterministic prompt scaffolds from structured briefs.
- `docs/episodic-podcast-generation-system-design.md` assigns `LLMPort`
  responsibility for retry discipline, token budgeting, guardrails, and usage
  metadata.
- No inference-backed behavioural tests exist yet, and no `vidaimock`
  configuration exists in the repository.

Likely implementation touchpoints:

- `episodic/llm/ports.py`
- `episodic/llm/__init__.py`
- `episodic/llm/openai_client.py`
- a new adapter module under `episodic/llm/` such as
  `episodic/llm/openai_adapter.py`
- a small domain/application helper for template guardrails, likely near
  existing prompt helpers under `episodic/canonical/`
- `tests/test_openai_type_guards.py`
- new unit tests under `tests/` for request DTOs, retry logic, and budget
  logic
- new behavioural files under `tests/features/` and `tests/steps/`
- `docs/episodic-podcast-generation-system-design.md`
- `docs/users-guide.md`
- `docs/developers-guide.md`
- `docs/roadmap.md`

The implementation should preserve these architectural boundaries:

- Canonical/profile/template code prepares generation context and guardrail
  inputs.
- `episodic.llm` owns provider-agnostic DTOs, retryable error types, and the
  outbound port contract.
- The concrete vendor adapter owns HTTP or SDK transport details and response
  normalization only.
- Behaviour tests prove the adapter through the real port boundary, not by
  importing vendor internals into the steps.

## Plan of work

### Stage A: lock the contract with failing tests first

Start by encoding the intended behaviour in tests before changing production
code.

Unit-test additions should cover:

- a richer request DTO for `LLMPort`, including prompt text, guardrail text,
  token-budget inputs, and model selection;
- deterministic request validation errors for impossible budgets or malformed
  prompt inputs;
- retry policy classification for transport errors, `429`, and `5xx` responses;
- non-retryable handling for invalid payloads that fail boundary validation;
- post-call usage normalization and budget overrun detection.

Behavioural tests (`pytest-bdd`) should cover:

- a successful OpenAI-compatible completion via `vidaimock`;
- a retry path where the first response is transiently failing and the second
  succeeds;
- a prompt-shape scenario proving the outbound request includes the template
  guardrail content;
- a token-usage scenario proving the adapter returns normalized usage metadata.

Go/no-go rule: proceed only after the new or updated tests fail for missing
contract or missing adapter behaviour.

### Stage B: expand the `LLMPort` contract without leaking vendor concerns

Replace the minimal string-only request surface with a domain-owned request DTO
that is expressive enough for this roadmap item while staying provider-agnostic.

The contract should likely add:

- `LLMRequest`: prompt text, guardrail prompt, target model, and token-budget
  configuration;
- explicit LLM-domain exceptions for retryable provider failures, permanent
  validation failures, and budget violations;
- optional metadata fields needed by later pricing or orchestration work only
  if they are required now to keep the adapter clean.

Keep the port minimal. Do not pull tool-calling, structured-output planning, or
pricing ledger concepts from later roadmap items into this milestone.

### Stage C: compose template-aligned guardrails outside the adapter

Implement a small helper or service that derives guardrail text from the same
content-template inputs that already shape prompt scaffolds. The important
constraint is placement: this logic belongs with prompt composition or an
application-level generation helper, not with the vendor adapter.

This stage should:

1. inspect the existing structured brief and episode-template payload shape;
2. define deterministic guardrail composition rules tied to template fields;
3. add unit tests proving stable guardrail output for representative templates;
4. feed the rendered guardrail text into `LLMRequest`.

The output need not solve every future guardrail use case. It only needs to
cover the template-aligned content generation rules required for `3.2.1`.

### Stage D: implement the OpenAI-compatible async adapter

Add a concrete adapter module under `episodic/llm/` that implements `LLMPort`
against an OpenAI-compatible chat-completions endpoint.

The adapter should:

1. build a provider request from `LLMRequest`, placing guardrail text in the
   provider's system-level message or equivalent compatible field;
2. submit the request asynchronously using a single, isolated transport seam;
3. retry transient failures with bounded attempts and deterministic backoff;
4. reject invalid responses using the existing `OpenAIChatCompletionAdapter`
   normalization helper;
5. return `LLMResponse` with normalized usage metadata;
6. surface deterministic domain errors for budget exhaustion, permanent
   provider failures, and malformed responses.

If a new runtime dependency is required, keep it to one OpenAI-compatible async
client and isolate that dependency inside the adapter module and project
configuration.

### Stage E: add `vidaimock` behavioural coverage

Create a local behavioural harness that starts `vidaimock`, points the adapter
at the mock server, and validates realistic inference-backed behaviour.

Implementation guidance:

- Add fixtures or helper files under `tests/fixtures/vidaimock/` to define mock
  provider routes or templates.
- Add a support fixture that:
  - confirms `command -v vidaimock`,
  - starts the server on a test-controlled port,
  - waits for `GET /metrics` to succeed,
  - tears the process down cleanly after the scenario.
- Prefer request-level deterministic chaos controls for retry scenarios, for
  example an injected transient error on the first call.
- Configure at least one mock response that echoes the received system and user
  messages so the BDD assertions can prove guardrail placement.

Do not let the BDD suite depend on external network access or hosted model
providers.

### Stage F: update documentation and roadmap state

Once the implementation is working, update the living documentation so it
matches the shipped behaviour.

Required documentation work:

- `docs/episodic-podcast-generation-system-design.md`
  - document the final `LLMPort` request/response contract,
  - clarify where retries, token budgeting, and template guardrails live,
  - record the `vidaimock` behavioural-test strategy as the local verification
    approach for inference-backed services.
- `docs/users-guide.md`
  - describe user-visible generation behaviour in plain language, especially
    that template-aligned guardrails shape generated content and that usage is
    metered.
- `docs/developers-guide.md`
  - document the internal adapter boundary, configuration expectations, and how
    to run the `vidaimock`-backed tests locally.
- `docs/roadmap.md`
  - mark `3.2.1` as done only after all implementation work and gates pass.

### Stage G: validate end to end

Run the required project gates after the code and documentation are in place.
Capture output with `tee` so failures remain inspectable even when output is
truncated.

Expected success indicators:

- unit tests and behavioural tests pass in `make test`;
- lint and type checks stay green with the new adapter dependency boundary;
- markdown checks stay green after the documentation updates;
- the roadmap entry is switched from `[ ]` to `[x]` only in the final passing
  change set.

## Concrete steps

Run from repository root.

- Inspect the current LLM boundary and prompt helpers.

```shell
rg -n "class LLMPort|LLMResponse|LLMUsage|OpenAIChatCompletionAdapter" episodic/llm
rg -n "build_series_brief_prompt|render_series_brief_prompt|episode template|guardrail" \
  episodic docs/developers-guide.md docs/episodic-podcast-generation-system-design.md
```

- Add fail-first tests before production edits.

```shell
rg --files tests | rg "openai|llm|prompt|feature|steps"
```

- Implement the port expansion, guardrail helper, and concrete adapter.

- Add `vidaimock` fixtures and `pytest-bdd` scenarios.

- Update documentation and roadmap state.

- Run validation with captured logs.

```shell
set -o pipefail; make fmt 2>&1 | tee /tmp/execplan-3-2-1-make-fmt.log
set -o pipefail; make check-fmt 2>&1 | tee /tmp/execplan-3-2-1-make-check-fmt.log
set -o pipefail; make typecheck 2>&1 | tee /tmp/execplan-3-2-1-make-typecheck.log
set -o pipefail; make lint 2>&1 | tee /tmp/execplan-3-2-1-make-lint.log
set -o pipefail; make test 2>&1 | tee /tmp/execplan-3-2-1-make-test.log
set -o pipefail; PATH=/root/.bun/bin:$PATH make markdownlint 2>&1 | tee /tmp/execplan-3-2-1-make-markdownlint.log
set -o pipefail; make nixie 2>&1 | tee /tmp/execplan-3-2-1-make-nixie.log
```

- For the behavioural harness, validate `vidaimock` explicitly while
  developing or debugging the fixture.

```shell
command -v vidaimock
vidaimock --port 8100 >/tmp/execplan-3-2-1-vidaimock.log 2>&1 &
curl -sS http://127.0.0.1:8100/metrics | head
pkill -f "vidaimock --port 8100"
```

## Acceptance evidence to capture during implementation

Keep concise evidence snippets in the completed plan or implementation notes.

Examples:

```plaintext
tests/test_llm_adapter.py::test_adapter_retries_transient_failure PASSED
tests/test_llm_budgeting.py::test_budget_rejects_prompt_that_exceeds_limit PASSED
tests/steps/test_llm_port_adapter_steps.py::test_successful_generation PASSED
```

```plaintext
curl -sS http://127.0.0.1:8100/metrics | head
# HELP ...
# TYPE ...
```

```plaintext
make test
...
<suite summary showing all tests passed>
```

## Proposed file map for the implementation phase

The exact names can change if repository conventions require it, but the
implementation should stay close to this shape:

- `episodic/llm/ports.py`
- `episodic/llm/__init__.py`
- `episodic/llm/openai_client.py`
- `episodic/llm/openai_adapter.py` or equivalent concrete adapter module
- `episodic/canonical/prompts.py` or a nearby canonical helper module for
  template-aligned guardrail rendering
- `tests/test_openai_type_guards.py`
- `tests/test_llm_port_contract.py`
- `tests/test_llm_adapter.py`
- `tests/test_llm_guardrails.py`
- `tests/features/llm_port_adapter.feature`
- `tests/steps/test_llm_port_adapter_steps.py`
- `tests/test_llm_port_adapter_support.py` if shared helpers are needed
- `tests/fixtures/vidaimock/...`
- `docs/episodic-podcast-generation-system-design.md`
- `docs/users-guide.md`
- `docs/developers-guide.md`
- `docs/roadmap.md`

## Approval resolution

The implementation questions raised during planning were resolved during
delivery:

1. One OpenAI-compatible runtime dependency was accepted.
2. Guardrail scope included a new persisted configuration surface on series
   profiles and episode templates.
3. The initial contract shipped with both OpenAI-compatible chat-completions
   and Responses support behind the same provider-neutral request DTO.
