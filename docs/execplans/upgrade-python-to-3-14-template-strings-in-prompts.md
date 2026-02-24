# Upgrade to Python 3.14: adopt template strings in prompts

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & discoveries`, `Decision log`, and
`Outcomes & retrospective` must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

Status: DRAFT

## Purpose and big picture

After this change, Episodic prompt construction will use Python 3.14 template
strings (`t"..."`) and the standard template representation, rather than ad-hoc
string interpolation in orchestration code. The observable outcome is safer,
inspectable prompt assembly with explicit static text and interpolation parts,
supporting auditing and future policy enforcement.

Success is visible when prompt templates are represented as template objects,
rendering is deterministic, and tests verify escaping and interpolation
behaviour.

## Constraints

- Keep prompt semantics unchanged for existing workflows.
- Do not introduce vendor-specific prompt dependencies in the domain layer.
- Keep orchestration boundaries aligned with hexagonal architecture.
- Avoid introducing new third-party template engines.
- Ensure all Python quality gates pass:
  `make check-fmt`, `make lint`, `make typecheck`, and `make test`.

## Tolerances (exception triggers)

- Scope: if migration requires modifying more than 12 modules, stop and
  escalate.
- Interface: if public port contracts must change in a non-backward-compatible
  way, stop and escalate.
- Ambiguity: if no concrete prompt-building code exists yet in implementation
  scope, stop and escalate with options for staged delivery.
- Validation: if tests for rendering behaviour fail after 2 iterations, stop
  and escalate with evidence.

## Risks

- Risk: prompt infrastructure is largely planned, not fully implemented, so
  migration targets may be sparse. Severity: medium. Likelihood: high.
  Mitigation: include a prototype milestone that lands reusable template
  utilities and tests before deep integration.

- Risk: escaping or quoting behaviour could change subtly during migration.
  Severity: high. Likelihood: medium. Mitigation: add fixture-based rendering
  tests that lock expected outputs.

- Risk: team familiarity with `t"..."` syntax may be low initially.
  Severity: low. Likelihood: medium. Mitigation: document usage patterns and
  anti-patterns in developer docs.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan created.
- [ ] Stage A: Confirm concrete prompt-construction touchpoints.
- [ ] Stage B: Add renderer tests and template fixtures before implementation.
- [ ] Stage C: Implement template-string-backed prompt builder.
- [ ] Stage D: Integrate selectively and run full gates.

## Surprises & discoveries

- Observation: current repository design docs describe prompt scaffolds, but
  concrete OpenAI/LLM prompt builder modules are not yet implemented. Evidence:
  repository search shows prompt references mainly in docs. Impact: staged
  prototype-first implementation is required.

- Observation: project memory Model Context Protocol (MCP) resources are
  unavailable in this session. Evidence: resource and template listings are
  empty. Impact: this plan relies on repository text only.

## Decision log

- Decision: start with a dedicated prompt-template utility module and tests,
  then integrate into orchestration paths as they are implemented. Rationale:
  avoids speculative wide refactors when core orchestration modules are still
  in roadmap phases. Date/Author: 2026-02-24 / Codex.

- Decision: prefer stdlib template-string support over external template
  engines. Rationale: lower dependency surface and direct Python 3.14 feature
  adoption. Date/Author: 2026-02-24 / Codex.

## Outcomes & retrospective

Pending implementation.

Completion should leave a tested, reusable prompt templating primitive and
clear migration guidance for future LLM adapters.

## Context and orientation

Prompt construction is currently described in design documentation, especially
`docs/episodic-podcast-generation-system-design.md`, but not yet represented by
concrete orchestration modules. Planned workflow areas include generation
prompts, QA remediation prompts, and audio synthesis parameter prompts.

This plan introduces a foundational prompt template abstraction in code so
future Large Language Model (LLM) port (`LLMPort`) adapters can consume
normalized rendered prompts without relying on ad-hoc string formatting.

Likely new or modified areas:

- New module under `episodic/` for prompt template representation and rendering.
- New tests under `tests/` for interpolation, escaping, and deterministic
  serialization.
- Documentation updates in `docs/developers-guide.md` and possibly
  `docs/users-guide.md` where prompt behaviour is described.

## Plan of work

Stage A confirms integration points and defines a minimal API surface. Identify
where prompt scaffolds will enter implemented workflows first, and avoid
premature coupling to incomplete orchestration components.

Stage B writes tests first. Add unit tests that define template rendering
behaviour for plain text, variable interpolation, unsafe content escaping, and
stable output ordering. Include fail-before assertions for accidental direct
f-string usage where policy requires templates.

Stage C implements a prompt template module backed by Python 3.14 template
string objects. Add helpers to render template objects with typed context maps
and optionally expose structured interpolation metadata for audit logs.

Stage D integrates the new renderer into the first available prompt path
(ingestion-adjacent metadata prompts or newly added LLM adapter scaffolding),
updates docs, and runs full gates.

## Concrete steps

Run from repository root.

1. Map current and planned prompt references.

    rg -n "prompt|LLMPort|template" episodic docs tests

2. Add rendering tests first and run targeted tests.

    set -o pipefail; uv run pytest -v tests/test_prompt_templates.py \
      2>&1 | tee /tmp/py314-tstring-targeted.log

3. Implement template utility and integration.

4. Run full Python gates with logs.

    set -o pipefail; make check-fmt 2>&1 | tee /tmp/py314-tstring-check-fmt.log
    set -o pipefail; make lint 2>&1 | tee /tmp/py314-tstring-lint.log
    set -o pipefail; make typecheck 2>&1 | tee /tmp/py314-tstring-typecheck.log
    set -o pipefail; make test 2>&1 | tee /tmp/py314-tstring-test.log

5. If documentation files change, run Markdown gates.

    set -o pipefail; make markdownlint 2>&1 | tee /tmp/py314-tstring-markdownlint.log
    set -o pipefail; make nixie 2>&1 | tee /tmp/py314-tstring-nixie.log

Expected success indicators:

- Prompt rendering tests pass and protect interpolation semantics.
- No ad-hoc prompt formatting remains in migrated paths.
- Full gates pass.

## Validation and acceptance

Acceptance criteria:

- At least one concrete prompt path uses template-string-backed rendering.
- Unit tests verify interpolation and escaping behaviour.
- Prompt rendering outputs remain deterministic and audit-friendly.
- `make check-fmt`, `make lint`, `make typecheck`, and `make test` pass.
- If docs are touched, `make markdownlint` and `make nixie` pass.

## Idempotence and recovery

- The migration can be executed incrementally by prompt path.
- If integration scope expands unexpectedly, keep template utility changes and
  defer additional adapters to follow-up plans.
- Failed rendering tests should be corrected before wider integration.

## Artifacts and notes

Capture during implementation:

- `git diff -- episodic tests docs`
- `/tmp/py314-tstring-targeted.log`
- `/tmp/py314-tstring-check-fmt.log`
- `/tmp/py314-tstring-lint.log`
- `/tmp/py314-tstring-typecheck.log`
- `/tmp/py314-tstring-test.log`
- Optional Markdown logs if docs changed.

## Interfaces and dependencies

- Use Python 3.14 template-string support (`t"..."`) and stdlib template APIs.
- Keep LLM adapters behind existing or planned `LLMPort` abstractions.
- Do not add external template dependencies.
- Keep domain modules free of direct vendor SDK coupling.

## Revision note

Initial draft created to stage Python 3.14 template strings adoption in prompt
construction with a utility-first, test-first rollout.
