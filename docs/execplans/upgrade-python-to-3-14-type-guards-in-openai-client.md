# Upgrade to Python 3.14: add type guards in OpenAI client adapter

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & discoveries`, `Decision log`, and
`Outcomes & retrospective` must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

Status: COMPLETE

## Purpose and big picture

After this change, Episodic's OpenAI-facing adapter code will use explicit type
narrowing helpers (type guards) to validate and normalize vendor responses
before converting them into domain-level Large Language Model (LLM) port
(`LLMPort`) outputs. The observable outcome is safer parsing with clearer
failure modes and stronger static typing for response handling.

Success is visible when malformed provider payloads are rejected with clear
errors, valid payloads are normalized consistently, and adapter tests cover the
guards.

## Constraints

- Keep OpenAI software development kit (SDK) handling inside adapter
  boundaries; no vendor types in domain modules.
- Do not weaken hexagonal architecture constraints.
- Keep planned `LLMPort` contract stable once introduced.
- Avoid runtime dependence on unchecked dictionary access for provider payloads.
- Run full Python quality gates after implementation.

## Tolerances (exception triggers)

- Scope: if this requires adding a full orchestration subsystem beyond adapter
  and tests, stop and escalate.
- Interface: if adopting type guards requires changing core domain entities,
  stop and escalate.
- Dependency: if OpenAI SDK version constraints conflict with current toolchain,
  stop and escalate.
- Validation: if strict typing cannot be satisfied after 2 iterations, stop and
  escalate with diagnostics.

## Risks

- Risk: OpenAI SDK response shapes can evolve and break naive assumptions.
  Severity: high. Likelihood: medium. Mitigation: isolate normalization with
  exhaustive guard coverage and compatibility tests.

- Risk: current repository has planned, not fully implemented, `LLMPort`
  modules. Severity: medium. Likelihood: high. Mitigation: implement adapter
  and guard utilities in a staged, additive manner that does not require full
  orchestration rollout.

- Risk: over-constrained typing could reduce flexibility for multi-provider
  support. Severity: medium. Likelihood: medium. Mitigation: normalize provider
  payloads into internal data transfer objects (DTOs) at adapter edge.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan created.
- [x] (2026-02-26 10:29Z) Stage A: Defined `LLMPort` response DTO contract and
  guard requirements for OpenAI chat completion payloads.
- [x] (2026-02-26 10:32Z) Stage B: Added fail-first guard and adapter tests in
  `tests/test_openai_type_guards.py`; initial run failed with
  `ModuleNotFoundError` before adapter implementation.
- [x] (2026-02-26 10:34Z) Stage C: Implemented
  `episodic/llm/openai_client.py`, `episodic/llm/ports.py`, and package exports
  with `TypeIs`-based guards and normalization.
- [x] (2026-02-26 10:39Z) Stage D: Integrated adapter modules and passed full
  quality gates (`make check-fmt`, `make lint`, `make typecheck`, `make test`,
  `make markdownlint`, and `make nixie`).

## Surprises & discoveries

- Observation: current repository documents `LLMPort` and orchestration
  behaviour, but does not yet contain a concrete OpenAI adapter implementation.
  Evidence: search results show `LLMPort` references primarily in docs. Impact:
  this work should be staged as a foundational adapter module with tests, ready
  for later orchestration integration.

- Observation: direct `uv run pytest` under Python 3.14 can fail building
  `tei-rapporteur` unless `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` is set.
  Evidence: targeted test run failed in dependency build before test
  collection. Impact: use the ABI compatibility environment variable for direct
  `uv run` commands in this workstream.

## Decision log

- Decision: implement type guards at adapter ingress/egress boundaries instead
  of spreading checks across orchestrator code. Rationale: concentrates
  validation logic and keeps domain/core clean. Date/Author: 2026-02-24 / Codex.

- Decision: include malformed payload fixtures as first-class tests.
  Rationale: edge-case resilience is the main value of this activity.
  Date/Author: 2026-02-24 / Codex.

- Decision: introduce a minimal provider-agnostic DTO surface in
  `episodic/llm/ports.py` (`LLMResponse`, `LLMUsage`) and normalize OpenAI
  payloads into that shape. Rationale: keeps vendor schema handling in the
  adapter layer while enabling stable orchestration-facing contracts.
  Date/Author: 2026-02-26 / Codex.

## Outcomes & retrospective

Implementation completed successfully.

Delivered outcomes:

- Added fail-first then passing guard/adapter tests in
  `tests/test_openai_type_guards.py` covering valid payloads, malformed
  payloads, wrong field types, and partial usage blocks.
- Added OpenAI adapter boundary validation and normalization in
  `episodic/llm/openai_client.py` with deterministic validation errors.
- Added provider-agnostic response DTOs and port contract in
  `episodic/llm/ports.py`.
- Updated architecture and user documentation to describe guard-backed OpenAI
  normalization behaviour.

Verification summary:

- Targeted tests: `uv run pytest -v tests/test_openai_type_guards.py` passed.
- Python gates: `make check-fmt`, `make lint`, `make typecheck`, and
  `make test` all passed.
- Markdown gates: `make markdownlint` and `make nixie` both passed.

## Context and orientation

Episodic's design docs define planned `LLMPort` behaviour and cost accounting,
but implementation of provider adapters is pending. This plan introduces
response validation primitives now, so OpenAI adapter development lands with
strong typing from the start.

Relevant context files:

- `docs/episodic-podcast-generation-system-design.md`
- `docs/roadmap.md` (Phase 3.2.1 and related tasks)
- New adapter modules under `episodic/` to be created.

Type guard terminology in this plan means functions returning
`typing.TypeGuard[...]` or `typing.TypeIs[...]` that narrow unknown payloads to
verified typed shapes before downstream conversion.

## Plan of work

Stage A defines interfaces and data shapes. Specify a minimal normalized
response data transfer object (DTO) for `LLMPort` consumption and identify
required fields from OpenAI responses, including text output and usage metadata.

Stage B writes tests first. Add fixtures for valid chat responses, missing
fields, wrong types, and partial usage blocks. Ensure tests fail before guard
implementation.

Stage C implements the guard and normalization utilities. Add small, composable
guard functions for response envelope, choices/output blocks, and usage
structures. Then convert guarded payloads into internal DTOs consumed by
adapter methods.

Stage D integrates with the OpenAI adapter entrypoint and runs full quality
gates. Document expected error classes and logging behaviour for invalid
payloads.

## Concrete steps

Run from repository root.

1. Confirm current adapter and port implementation status.

    rg -n "LLMPort|openai|adapter|usage|token" episodic docs tests

2. Create guard tests first.

    set -o pipefail; uv run pytest -v tests/test_openai_type_guards.py \
      2>&1 | tee /tmp/py314-openai-guards-targeted.log

3. Implement guard and normalization modules.

4. Run full Python gates.

    set -o pipefail; make check-fmt 2>&1 | tee /tmp/py314-openai-guards-check-fmt.log
    set -o pipefail; make lint 2>&1 | tee /tmp/py314-openai-guards-lint.log
    set -o pipefail; make typecheck 2>&1 | tee /tmp/py314-openai-guards-typecheck.log
    set -o pipefail; make test 2>&1 | tee /tmp/py314-openai-guards-test.log

Expected success indicators:

- Guard tests prove invalid payload rejection and valid payload acceptance.
- Type checker confirms narrowed types without unsafe casts.
- Full gates pass.

## Validation and acceptance

Acceptance criteria:

- OpenAI adapter boundary uses explicit type guards for payload validation.
- Invalid payloads produce deterministic, documented errors.
- Adapter outputs satisfy planned internal DTO/port contracts.
- `make check-fmt`, `make lint`, `make typecheck`, and `make test` pass.

## Idempotence and recovery

- Guard implementation is additive and can be rolled back independently of
  broader adapter logic.
- If SDK changes break guards, update only normalization layer and fixtures.
- Test commands are deterministic and safe to rerun.

## Artifacts and notes

Capture during implementation:

- `git diff -- episodic tests docs`
- `/tmp/py314-openai-guards-targeted.log`
- `/tmp/py314-openai-guards-check-fmt.log`
- `/tmp/py314-openai-guards-lint.log`
- `/tmp/py314-openai-guards-typecheck.log`
- `/tmp/py314-openai-guards-test.log`

## Interfaces and dependencies

- Use Python typing features for narrowing (`TypeGuard` and/or `TypeIs`).
- Keep provider-specific parsing in adapter layer.
- Ensure compatibility with planned `LLMPort` result shapes and usage metadata.
- No additional parsing dependencies should be required.

## Revision note

Initial draft created to enforce typed response validation at the OpenAI
adapter boundary as part of the Python 3.14 modernization track.
