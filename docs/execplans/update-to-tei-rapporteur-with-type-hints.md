# Update tei-rapporteur pin and remove local TEI typing shims

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises and discoveries`, `Decision log`, and
`Outcomes and retrospective` must be kept up to date as work proceeds.

Status: DRAFT

No `PLANS.md` file is present in the repository root.

## Purpose and big picture

Update the `tei-rapporteur` dependency pin to commit
`c587b1814a6234e6c55b709ff9e943bef2d83610`, then remove local protocol shims
that were only present to compensate for missing upstream type hints. After
this change, `episodic` should rely on `tei-rapporteur` type information
directly. Success is observable when type-checking passes without local TEI
typing shims, TEI parsing behaviour is unchanged, and all project quality gates
pass.

## Constraints

- Keep user-visible TEI parsing behaviour unchanged in
  `episodic/canonical/tei.py`.
- Do not add new dependencies.
- Keep dependency source as the existing git dependency in
  `pyproject.toml`; only update the commit SHA.
- Remove local TEI typing shims instead of replacing them with new local
  protocol wrappers.
- Preserve repository quality gates: formatting, linting, type-checking, and
  tests must pass before completion.
- Do not touch unrelated domains (`episodic/canonical/storage`,
  `episodic/canonical/services`, migrations) unless required to keep tests
  green.

## Tolerances (exception triggers)

- Scope: stop and escalate if implementation needs changes in more than 7
  files or more than 280 net lines.
- Interface: stop and escalate if `parse_tei_header` signature or return type
  must change.
- Dependency: stop and escalate if updating `tei-rapporteur` requires adding
  any additional package or changing Python version constraints.
- Iterations: stop and escalate if type-checking or tests fail after 3 full
  fix attempts.
- Behaviour: stop and escalate if TEI payload key handling (`teiHeader`,
  `header`, `fileDesc`, `file_desc`) changes unexpectedly.
- Ambiguity: stop and escalate if the upstream typed API differs materially
  from expected members (`Document`, `emit_xml`, `parse_xml`, `to_dict`).

## Risks

- Risk: The upstream typed surface may differ from current assumptions.
  Severity: medium. Likelihood: medium. Mitigation: inspect `tei_rapporteur`
  exports and signatures immediately after pin update; adapt local usage
  minimally.
- Risk: Lockfile refresh may introduce unrelated dependency drift.
  Severity: medium. Likelihood: low. Mitigation: review `uv.lock` diff and keep
  changes constrained to `tei-rapporteur` entries.
- Risk: Removing protocol shims may expose latent type issues in tests.
  Severity: low. Likelihood: medium. Mitigation: use a test-first type-check
  flow and keep runtime tests in the validation sequence.

## Progress

- [x] (2026-02-09 12:28Z) Gathered repository context, identified tei-rapporteur
  pin locations, and identified local TEI typing shim locations.
- [x] (2026-02-09 12:28Z) Drafted this ExecPlan for review.
- [ ] Update dependency pin and lockfile to
  `c587b1814a6234e6c55b709ff9e943bef2d83610`.
- [ ] Remove TEI local protocol/type-ignore shim code and switch to direct
  upstream typing.
- [ ] Run all Python quality gates and confirm no behavioural regression.

## Surprises and discoveries

- Observation: No MCP resources are exposed in this session, so the
  qdrant-backed notes retrieval protocol could not be executed. Evidence:
  `list_mcp_resources` returned an empty resource list. Impact: Planning
  proceeded using repository files only.
- Observation: TEI typing shims exist in both production and test code.
  Evidence: `episodic/canonical/tei.py` defines `TEIDocumentProtocol` and
  `TEIProtocol`; `tests/steps/test_canonical_ingestion_steps.py` defines
  `TEITestProtocol`; `tests/test_canonical_tei.py` uses
  `type: ignore[unresolved-attribute]`. Impact: Plan must remove shim patterns
  consistently across these files.

## Decision log

- Decision: Use a type-check-first workflow to prove the old dependency pin
  cannot satisfy direct typing and the new pin can. Rationale: The requested
  change is fundamentally a typing-surface upgrade, so static analysis is the
  primary proof point. Date/Author: 2026-02-09, Codex.
- Decision: Keep runtime behaviour validation in scope with targeted TEI tests
  plus full `make test`. Rationale: Dependency upgrades can alter parsing
  behaviour even when the intent is typing-only. Date/Author: 2026-02-09, Codex.

## Outcomes and retrospective

This plan is in DRAFT status. Implementation outcomes and lessons learned will
be recorded here after execution.

## Context and orientation

The dependency pin and likely change surface are:

- `pyproject.toml` currently pins `tei-rapporteur` to
  `3129188d792585976bff1c12332c9243bca8cac0`.
- `uv.lock` contains the corresponding git source and revision entries.
- `episodic/canonical/tei.py` wraps `tei_rapporteur` behind local protocol
  types and a `pyright` member-type ignore.
- `tests/steps/test_canonical_ingestion_steps.py` defines a local
  `TEITestProtocol` shim and casts `tei_rapporteur`.
- `tests/test_canonical_tei.py` uses unresolved-attribute ignore comments on
  `tei_rapporteur` members.

Terms used in this plan:

- Local typing shim: a local `typing.Protocol`, cast, or ignore comment used
  to stand in for missing third-party types.
- Direct upstream typing: consuming the third-party package API without local
  shim wrappers, relying on package-provided type hints.

## Plan of work

Stage A is baseline verification. Confirm current pin locations and capture a
before-state type-check run after removing test-only TEI ignore comments in a
small preparatory edit. Do not continue unless type-checking fails for TEI
member typing under the old pin; this is the proof that the migration is
necessary.

Stage B is dependency update. Change the `tei-rapporteur` SHA in
`pyproject.toml` to `c587b1814a6234e6c55b709ff9e943bef2d83610`, regenerate
`uv.lock`, and verify lockfile entries now point to the new revision. Keep the
diff constrained to the expected dependency entries.

Stage C is shim removal and direct typing adoption. Update
`episodic/canonical/tei.py` to remove `TEIDocumentProtocol`, `TEIProtocol`, and
the `TEI` cast/ignore alias, then use `tei_rapporteur` APIs directly with their
upstream hints. Remove `TEITestProtocol` and cast usage from
`tests/steps/test_canonical_ingestion_steps.py`, and remove
`type: ignore[unresolved-attribute]` TEI lines from
`tests/test_canonical_tei.py`. Keep runtime logic unchanged.

Stage D is hardening and validation. Run format, lint, type-check, and test
gates with logged output. If any documentation is updated during execution, run
Markdown validation gates as well.

Each stage has a go/no-go checkpoint: proceed only when the stage validation
passes.

## Concrete steps

1. Confirm baseline dependency and shim locations.

    rg -n "tei-rapporteur|tei_rapporteur|TEIProtocol|TEITestProtocol" \
      pyproject.toml uv.lock episodic tests

2. Create a deliberate failing type-check proof (test-first typing step) by
   removing TEI unresolved-attribute ignore comments in
   `tests/test_canonical_tei.py`, then run:

    set -o pipefail
    timeout 300 make typecheck 2>&1 | tee /tmp/update-tei-typecheck-before.log

   Expected before-state: type-check fails on unresolved TEI members.

3. Update `pyproject.toml` to use SHA
   `c587b1814a6234e6c55b709ff9e943bef2d83610` for `tei-rapporteur`, then
   regenerate lock metadata:

    set -o pipefail
    timeout 300 uv lock 2>&1 | tee /tmp/update-tei-uv-lock.log

4. Verify dependency update landed:

    rg -n "tei-rapporteur|c587b1814a6234e6c55b709ff9e943bef2d83610" \
      pyproject.toml uv.lock

5. Remove local TEI type shims in:
   `episodic/canonical/tei.py`,
   `tests/steps/test_canonical_ingestion_steps.py`, and
   `tests/test_canonical_tei.py`.

6. Run project quality gates with logs:

    set -o pipefail
    timeout 300 make fmt 2>&1 | tee /tmp/update-tei-fmt.log

    set -o pipefail
    timeout 300 make check-fmt 2>&1 | tee /tmp/update-tei-check-fmt.log

    set -o pipefail
    timeout 300 make lint 2>&1 | tee /tmp/update-tei-lint.log

    set -o pipefail
    timeout 300 make typecheck 2>&1 | tee /tmp/update-tei-typecheck.log

    set -o pipefail
    timeout 300 make test 2>&1 | tee /tmp/update-tei-test.log

7. If any Markdown files are changed as part of implementation, also run:

    set -o pipefail
    timeout 300 make markdownlint 2>&1 | tee /tmp/update-tei-markdownlint.log

    set -o pipefail
    timeout 300 make nixie 2>&1 | tee /tmp/update-tei-nixie.log

## Validation and acceptance

Acceptance requires all of the following:

- `pyproject.toml` and `uv.lock` reference
  `c587b1814a6234e6c55b709ff9e943bef2d83610` for `tei-rapporteur`.
- `episodic/canonical/tei.py` no longer contains local TEI protocol shim
  classes or `pyright` TEI member-type ignore aliases.
- `tests/steps/test_canonical_ingestion_steps.py` no longer uses
  `TEITestProtocol` and cast shims for `tei_rapporteur`.
- `tests/test_canonical_tei.py` no longer needs TEI unresolved-attribute
  ignore comments.
- `make fmt`, `make check-fmt`, `make lint`, `make typecheck`, and `make test`
  pass.
- TEI parsing tests retain behaviour (including missing-header and
  missing-title error mapping).

## Idempotence and recovery

All steps are re-runnable. If a step fails:

- Fix the reported issue and rerun only the failed step, then rerun the full
  validation sequence.
- If lockfile regeneration introduces unexpected drift, restore
  `pyproject.toml` and `uv.lock` to the last good state and rerun `uv lock`
  after confirming only the TEI SHA changed.
- If upstream typed API differs, pause at the tolerance gate and record
  options in `Decision log` before proceeding.

## Artifacts and notes

Expected execution artifacts:

- `/tmp/update-tei-typecheck-before.log`
- `/tmp/update-tei-uv-lock.log`
- `/tmp/update-tei-fmt.log`
- `/tmp/update-tei-check-fmt.log`
- `/tmp/update-tei-lint.log`
- `/tmp/update-tei-typecheck.log`
- `/tmp/update-tei-test.log`
- Optional, if docs change:
  `/tmp/update-tei-markdownlint.log`, `/tmp/update-tei-nixie.log`

## Interfaces and dependencies

The implementation should treat `tei_rapporteur` as the source of truth for
typing on:

- document construction in tests (`Document`, `emit_xml`), and
- parsing and serialization in production (`parse_xml`, `to_dict`,
  document `validate()`).

No new adapter layer should be introduced unless a tolerance threshold is hit.

## Revision note

Initial draft created on 2026-02-09 to plan the `tei-rapporteur` SHA update and
removal of local TEI typing shims in favour of upstream type hints.
