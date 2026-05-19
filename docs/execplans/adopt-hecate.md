# Adopt Hecate for hexagonal architecture checks

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: DRAFT - awaiting approval before implementation

## Purpose and big picture

Episodic currently enforces hexagonal architecture boundaries with a
repository-local checker in `episodic.architecture`. That checker proved the
rule set, but it now duplicates behaviour that belongs in the shared Hecate
tool. This plan replaces the ad hoc checker with Hecate pinned at Git SHA
`46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12`, while keeping the maintainer
workflow stable: `make check-architecture` remains the command to run, and
`make lint` remains the gate that includes architecture enforcement.

The observable success condition is that a maintainer can run:

```shell
make check-architecture
make lint
make test
```

and get the same boundary protection that exists today, now powered by Hecate
configuration in `pyproject.toml` rather than duplicated Python code under
`episodic/architecture/`.

This plan is only the planning artefact. Implementation must not begin until
the user explicitly approves this ExecPlan. Until then, do not edit
`pyproject.toml`, the Makefile, tests, product documentation, or roadmap status
as though the migration has happened.

The plan signposts these skills for the implementing agent:

- `leta`, for semantic navigation before changing or removing code symbols.
- `hexagonal-architecture`, for dependency-direction and port/adapter checks.
- `execplans`, for keeping this plan current during implementation.
- `en-gb-oxendict-style`, for project documentation spelling and tone.
- `commit-message`, for file-based commit messages when committing each slice.

## Constraints

- Do not implement the migration before explicit approval of this plan.
- Preserve the hexagonal architecture invariants from the
  `hexagonal-architecture` skill:
  domain and port modules stay inward, application services depend only on
  application and domain-port groups, inbound adapters must not import outbound
  adapters, outbound adapters must not import inbound adapters, and composition
  roots are the only modules allowed to wire concrete adapters together.
- Keep the local maintainer command contract. `make check-architecture` must
  continue to exist, and `make lint` must continue to include the architecture
  gate.
- Pin Hecate to
  `git+https://github.com/leynos/hecate@46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12`
  unless explicit approval is given to use a different revision.
- Put the production architecture policy in `pyproject.toml` under
  `[tool.hecate]`, because Hecate discovers that table from the project root.
- Keep composition-root prefixes before broader adapter prefixes. Hecate group
  matching is first-match, so `episodic.api.runtime` must be matched before
  the broader `episodic.api` inbound-adapter prefix.
- Retire duplicated checker semantics from Episodic once Hecate has equivalent
  coverage. Do not keep two independent import-policy engines active.
- Preserve project-specific fixture coverage where it documents Episodic's
  intended architecture. General checker semantics belong in Hecate.
- Update documentation only when it matches implemented behaviour. During this
  planning phase, the users' guide, developers' guide, design document,
  Architecture Decision Record (ADR), and roadmap should describe the current
  repo-local checker until the approved implementation changes it.
- On implementation, record the decision to adopt Hecate in an ADR or by
  superseding `docs/adr/adr-006-hexagonal-architecture-enforcement.md`, then
  update `docs/episodic-podcast-generation-system-design.md` to reference the
  accepted decision.
- On implementation, update `docs/users-guide.md` only for user-visible command
  or diagnostic behaviour, update `docs/developers-guide.md` for
  maintainer-facing conventions, and update component architecture
  documentation if an internally facing interface or practice changes.
- On implementation completion, mark the relevant roadmap entry done only after
  the code, tests, documentation, CodeRabbit review, and gates all pass.
- Use Makefile targets for validation. Run `make check-fmt`, `make lint`, and
  `make test` sequentially with output captured through `tee` to `/tmp`.
- Use `coderabbit review --agent` after each major implementation milestone,
  clear all concerns before moving on, and record the result in this plan.
- Commit frequently after gated slices. Do not commit a slice that fails its
  required gate.

## Tolerances

- Scope tolerance: stop and escalate if the implementation needs more than
  roughly 16 files or 900 net changed lines before Hecate can run on the
  production `episodic` package.
- Public interface tolerance: stop and escalate before removing
  `episodic.architecture` as an importable API if any non-test code in this
  repository still imports `check_architecture`, `ArchitecturePolicy`, or
  `ArchitectureViolation`.
- Compatibility tolerance: stop and escalate if an external consumer-facing
  command-line interface (CLI) compatibility shim for
  `python -m episodic.architecture` appears necessary. The preferred route is
  to document `hecate check` and keep the Makefile target, not to preserve a
  second public checker command forever.
- Diagnostic tolerance: stop and escalate if Hecate diagnostics cannot provide
  stable substrings for fixture assertions after three focused attempts.
- Policy tolerance: stop and escalate if reproducing the current production
  policy requires undocumented `ignore_imports` entries. Every ignore must have
  a specific reason and a removal condition.
- Test tolerance: stop and escalate if converting fixture tests requires
  deleting coverage for re-export handling, star exports, explicit empty
  `__all__`, or composition-root wiring.
- Dependency tolerance: stop and escalate if Hecate cannot be installed through
  the normal `uv sync --group dev` path from the pinned Git revision.
- Validation tolerance: stop and escalate if `make check-fmt`, `make lint`, or
  `make test` fails for a reason unrelated to this migration and the failure
  cannot be isolated as pre-existing with a concise transcript.

## Risks

- Risk: Hecate and the local checker differ in diagnostic text. Severity:
  medium. Likelihood: high. Mitigation: keep assertions focused on stable
  fields such as rule identifier, importer, imported module, and group names.
  Prefer setting `default_rule_id = "ARCH001"` only if preserving the existing
  rule code is more valuable than adopting Hecate's default `HEC001`.

- Risk: fixture tests currently depend on `python -m episodic.architecture
  --fixture-policy`, while Hecate has no fixture-policy flag. Severity: high.
  Likelihood: high. Mitigation: create fixture-specific Hecate TOML config
  files or a test helper that writes temporary Hecate configs, then invoke
  `hecate check --config <path>` through the command line.

- Risk: first-match group ordering can accidentally classify
  `episodic.api.runtime` as an inbound adapter instead of a composition root.
  Severity: high. Likelihood: medium. Mitigation: put composition-root groups
  first in `[tool.hecate.groups]` and add tests that fail if runtime wiring is
  rejected.

- Risk: keeping `episodic.architecture` as a wrapper around Hecate may create
  a new compatibility surface that has to be maintained. Severity: medium.
  Likelihood: medium. Mitigation: remove the repo-local package unless a
  concrete consumer requires a temporary compatibility shim.

- Risk: removing the local checker package may also remove useful
  project-specific tests. Severity: medium. Likelihood: medium. Mitigation:
  retain architecture fixture packages and BDD scenarios where they describe
  Episodic policy, but move generic parser and re-export semantics to Hecate's
  own test suite.

- Risk: documentation can get ahead of implementation. Severity: medium.
  Likelihood: medium. Mitigation: update product and maintainer docs in the
  same implementation slice that changes the command and dependency, and leave
  this draft plan as the only Hecate-specific repository document until
  approval.

- Risk: the roadmap item `1.5.4` is already marked done for the existing
  repo-local checker. Severity: low. Likelihood: high. Mitigation: treat
  Hecate adoption as replacement work for the same gate, not as completion of
  deferred roadmap item `2.4.5`. Do not mark `2.4.5` done unless the approved
  implementation actually completes orchestration-specific enforcement.

## Progress

- [x] (2026-05-19 00:00Z) Loaded the requested `leta` and
  `hexagonal-architecture` skills, loaded the `execplans` skill for this
  planning work, and created a Leta workspace for this worktree.
- [x] (2026-05-19 00:00Z) Confirmed the branch is
  `feat/plan-hecate-adoption`, not a protected main branch.
- [x] (2026-05-19 00:00Z) Used a Wyvern agent team for read-only planning
  support covering current enforcement, Hecate migration notes, and
  documentation placement.
- [x] (2026-05-19 00:00Z) Reviewed Hecate documentation at the pinned SHA and
  verified the project name, CLI entry point, configuration table, exit codes,
  group schema, and Episodic-specific migration mapping.[^1][^2][^3][^4]
- [x] (2026-05-19 00:00Z) Inspected the current Makefile, CI workflow,
  `pyproject.toml`, architecture checker package, architecture tests, BDD
  steps, fixture packages, ADR-006, the system design, the developers' guide,
  and the roadmap.
- [x] (2026-05-19 00:00Z) Drafted this plan for approval.
- [x] (2026-05-19 00:00Z) Validated the planning artefact with
  `make check-fmt`, `make lint`, `make test`, `make markdownlint`, and
  `make nixie`.
- [x] (2026-05-19 00:00Z) Ran `coderabbit review --agent`; it reported two
  minor documentation findings, both resolved in this plan.
- [ ] User approves this ExecPlan for implementation.
- [ ] Milestone 1: Add Hecate as a pinned development dependency and encode
  the production policy in `[tool.hecate]`.
- [ ] Milestone 2: Replace the Makefile architecture command with
  `hecate check` while keeping `make check-architecture` and `make lint`
  behaviour.
- [ ] Milestone 3: Convert architecture fixture tests and BDD scenarios to
  Hecate-driven configs and diagnostics.
- [ ] Milestone 4: Remove or reduce `episodic.architecture` so Episodic no
  longer owns duplicated checker semantics.
- [ ] Milestone 5: Update ADR, system design, users' guide, developers' guide,
  and roadmap text to match the implemented behaviour.
- [ ] Milestone 6: Run full validation gates, run CodeRabbit review, clear
  concerns, and commit the final implementation state.

## Surprises & Discoveries

- Observation: the current architecture gate is already part of `make lint`.
  Impact: the migration can keep CI and local workflows stable by changing the
  implementation behind `make check-architecture`, not by introducing a new
  top-level command.

- Observation: `episodic.architecture` exposes `check_architecture` and policy
  types through `episodic/architecture/__init__.py`, but discovered usage is
  limited to tests and the package's own command line. Impact: full removal is
  likely feasible after tests are converted, but the implementing agent must
  verify references with Leta before deleting the package.

- Observation: Hecate's migration notes already contain an Episodic policy
  translation that mirrors the current local groups. Impact: the approved
  implementation should start from that TOML rather than manually translating
  the policy again.

- Observation: Hecate defaults diagnostics to `HEC001`, while the current test
  suite and documentation mention `ARCH001`. Impact: the approved
  implementation must make an explicit decision about rule identifier
  continuity, update tests and docs accordingly, and record the decision.

- Observation: the fixture policy is generic and package-relative, but Hecate
  configuration is TOML-based. Impact: fixture coverage should probably move
  to small generated or checked-in TOML configs rather than recreating a
  Python-only policy helper.

- Observation: the documentation-focused Wyvern warned not to mark deferred
  roadmap item `2.4.5` done during Hecate adoption. Impact: this plan treats
  Hecate migration as replacement of the existing `1.5.4` enforcement
  mechanism unless the approved implementation explicitly expands scope.

- Observation: the first full `make test` validation run timed out once while
  setting up
  `tests/test_reference_document_service_validation.py::test_list_endpoints_reject_invalid_pagination`,
  but a focused rerun of that test passed and the full gate passed on rerun.
  Impact: the timeout was treated as transient and is recorded here because the
  plan itself only changed Markdown.

## Decision Log

- Decision: keep `make check-architecture` as the stable local command and
  change it to run `hecate check`. Rationale: maintainers already know the
  Makefile target, and `make lint` already depends on it. Date/Author:
  2026-05-19 / Codex.

- Decision: add Hecate as a pinned development dependency using the requested
  Git SHA instead of invoking an unpinned global tool. Rationale: CI, local
  validation, and reviewers need reproducible checker behaviour. Date/Author:
  2026-05-19 / Codex.

- Decision: encode the production architecture policy in `pyproject.toml`
  under `[tool.hecate]`. Rationale: Hecate discovers that table by default from
  the project root, and this keeps the enforced policy close to the other
  project tooling configuration. Date/Author: 2026-05-19 / Codex.

- Decision: remove duplicated local checker semantics after Hecate fixture
  coverage is in place, rather than preserving a long-lived wrapper. Rationale:
  two independent checkers would create policy drift and unclear ownership.
  Date/Author: 2026-05-19 / Codex.

- Decision: do not update product documentation, users' guide, developer
  guide, ADR status, or roadmap status during the draft planning phase.
  Rationale: those documents should describe implemented behaviour, and this
  plan still awaits approval. Date/Author: 2026-05-19 / Codex.

## Implementation plan

### Milestone 0: approval gate

Present this ExecPlan to the user and wait for explicit approval. Do not start
Milestone 1 until approval is received.

After approval, update this section with the approval timestamp and begin a
small commit sequence. Load the `commit-message` skill before the first commit.

### Milestone 1: add Hecate and production policy

Use Leta to verify there are no unexpected references to the local architecture
API:

```shell
leta refs check_architecture
leta refs ArchitecturePolicy
leta refs ArchitectureViolation
```

Add the pinned dependency to `[dependency-groups].dev` in `pyproject.toml`:

```toml
"hecate @ git+https://github.com/leynos/hecate@46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12",
```

Add `[tool.hecate]` with `root_packages = ["episodic"]`. Start with
`default_rule_id = "ARCH001"` if compatibility with existing test and
documentation language is chosen. Otherwise accept Hecate's default `HEC001`
and update all diagnostics, tests, and documentation in the same slice.

Add the groups in this order:

```toml
[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["episodic.api.runtime", "episodic.worker.runtime"]
allowed = [
    "application",
    "composition_root",
    "domain_ports",
    "inbound_adapter",
    "outbound_adapter",
]

[[tool.hecate.groups]]
name = "domain_ports"
prefixes = [
    "episodic.canonical.domain",
    "episodic.canonical.constraints",
    "episodic.canonical.ingestion",
    "episodic.canonical.ingestion_ports",
    "episodic.canonical.entity_protocols",
    "episodic.canonical.history_protocols",
    "episodic.canonical.ports",
    "episodic.canonical.reference_protocols",
    "episodic.canonical.unit_of_work_protocols",
    "episodic.llm.ports",
]
allowed = ["domain_ports"]

[[tool.hecate.groups]]
name = "application"
prefixes = [
    "episodic.canonical.services",
    "episodic.canonical.ingestion_service",
    "episodic.canonical.profile_templates",
    "episodic.canonical.reference_documents",
    "episodic.generation",
]
allowed = ["application", "domain_ports"]

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = [
    "episodic.api",
    "episodic.worker.tasks",
    "episodic.worker.topology",
]
allowed = ["inbound_adapter", "application", "domain_ports"]

[[tool.hecate.groups]]
name = "outbound_adapter"
prefixes = [
    "episodic.canonical.adapters",
    "episodic.canonical.storage",
    "episodic.llm.openai_adapter",
    "episodic.llm.openai_client",
]
allowed = ["outbound_adapter", "application", "domain_ports"]
```

Run the focused command:

```shell
make build 2>&1 | tee /tmp/build-episodic-feat-plan-hecate-adoption.out
uv run hecate check 2>&1 | tee /tmp/hecate-episodic-feat-plan-hecate-adoption.out
```

Expected result: `hecate check` exits `0` on the production package. If it
exits `1`, inspect the diagnostics and decide whether the issue is a real
boundary leak or a policy translation problem. If it exits `2`, fix the config
or dependency installation before proceeding.

Run `coderabbit review --agent`, clear concerns, update this plan, then commit
the dependency and production policy once the focused gate passes.

### Milestone 2: switch Makefile and CI command path

Change `Makefile` so `check-architecture` runs:

```make
	$(UV_ENV) $(UV) run hecate check
```

Do not remove the `check-architecture` target, and keep `lint:
check-architecture` unless a documented Makefile ordering problem appears.

Review `.github/workflows/ci.yml`. Because CI already runs `make build` before
`make lint`, a development dependency should make `hecate` available in the
virtual environment. Only add a separate CI tool installation if the normal
`uv sync --group dev` path cannot expose the command.

Run:

```shell
make check-architecture 2>&1 | tee /tmp/check-architecture-episodic-feat-plan-hecate-adoption.out
make lint 2>&1 | tee /tmp/lint-episodic-feat-plan-hecate-adoption.out
```

Expected result: both commands exit `0`, and the lint log shows the Hecate gate
running before Ruff and Pylint. Run CodeRabbit, clear concerns, update this
plan, then commit the Makefile and CI slice.

### Milestone 3: convert architecture tests and fixtures

Replace direct imports of `episodic.architecture.check_architecture` in
`tests/test_architecture_enforcement.py` with Hecate CLI or Hecate library
checks. Prefer CLI coverage for behaviour that users and maintainers observe.

For fixture packages, create either:

- checked-in TOML files under `tests/fixtures/architecture/<case>/hecate.toml`;
  or
- a small test helper that writes a temporary TOML config for the selected
  fixture package.

The fixture policy must model:

- `runtime` as `composition_root`, allowed to import all fixture groups;
- `domain` as inward-only;
- `service` as application code, allowed to import domain and application;
- `api` as inbound adapter, allowed to import domain, application, and inbound
  adapter;
- `storage` as outbound adapter, allowed to import domain, application, and
  outbound adapter.

Update `tests/steps/test_architecture_enforcement_steps.py` so the BDD command
runs Hecate:

```shell
hecate check --config <fixture-config>
```

Keep coverage for:

- `domain_imports_storage`;
- `api_imports_outbound_adapter`;
- `api_imports_reexported_outbound_adapter`;
- `api_imports_star_reexported_outbound_adapter`;
- `api_imports_nested_star_reexported_outbound_adapter`;
- `api_imports_cyclic_star_reexported_outbound_adapter`;
- `explicit_empty_all`;
- `allowed_case`;
- `composition_root_allows_wiring`.

Run fail-first where practical by updating one fixture expectation before the
implementation helper is complete, then confirm it fails for the expected
reason. After implementation, run:

```shell
uv run pytest -q tests/test_architecture_enforcement.py \
  tests/steps/test_architecture_enforcement_steps.py \
  2>&1 | tee /tmp/architecture-tests-episodic-feat-plan-hecate-adoption.out
```

Expected result: all architecture fixture and BDD tests pass, and violating
fixtures still fail through Hecate diagnostics. Run CodeRabbit, clear concerns,
update this plan, then commit the fixture-test slice.

### Milestone 4: retire duplicated local checker semantics

Use Leta before deletion:

```shell
leta refs check_architecture
leta refs fixture_policy
leta refs ArchitecturePolicy
```

If only tests and `episodic.architecture` internals reference the package, remove
the duplicated checker implementation in `episodic/architecture/` and adjust
exports accordingly. If import compatibility is required, keep only a minimal
module that raises a clear deprecation or delegates to Hecate without owning
policy logic. Escalate before adding a compatibility shim with more than one
release-cycle's worth of behaviour.

Run:

```shell
make lint 2>&1 | tee /tmp/lint-retire-checker-episodic-feat-plan-hecate-adoption.out
make test 2>&1 | tee /tmp/test-retire-checker-episodic-feat-plan-hecate-adoption.out
```

Expected result: removal of the local checker does not reduce architecture
coverage, and no code imports deleted symbols. Run CodeRabbit, clear concerns,
update this plan, then commit the removal slice.

### Milestone 5: update documentation and roadmap

Update documentation in the same implementation sequence that changes the
behaviour:

- Update or supersede
  `docs/adr/adr-006-hexagonal-architecture-enforcement.md`. If the change is
  substantive enough to be a new accepted decision, create a new ADR under
  `docs/adr/` and reference the old ADR as superseded or amended.
- Update the accepted decision records list and hexagonal architecture
  enforcement section in
  `docs/episodic-podcast-generation-system-design.md`.
- Update `docs/developers-guide.md` so maintainers edit `[tool.hecate]` when
  package boundaries change, not `episodic/architecture/checker.py`.
- Update `docs/users-guide.md` only if the checker command, diagnostics, or
  CLI behaviour is user-visible for consumers or operators.
- Update any relevant component architecture document if internal conventions
  around Hecate configs, fixture configs, or architecture policy ownership
  become normative.
- Update `docs/roadmap.md` to state that the existing architecture gate is now
  Hecate-backed. Mark a roadmap entry done only if the approved implementation
  actually completes that entry. Do not mark deferred orchestration item
  `2.4.5` done unless its full scope is implemented.

Run:

```shell
make fmt 2>&1 | tee /tmp/fmt-docs-episodic-feat-plan-hecate-adoption.out
make check-fmt 2>&1 | tee /tmp/check-fmt-docs-episodic-feat-plan-hecate-adoption.out
make markdownlint 2>&1 | tee /tmp/markdownlint-docs-episodic-feat-plan-hecate-adoption.out
make nixie 2>&1 | tee /tmp/nixie-docs-episodic-feat-plan-hecate-adoption.out
```

Expected result: documentation is formatted, Markdown lint passes, and Mermaid
diagrams remain valid. Run CodeRabbit, clear concerns, update this plan, then
commit the documentation slice.

### Milestone 6: final validation and completion

Run the required gates sequentially:

```shell
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-feat-plan-hecate-adoption.out
make lint 2>&1 | tee /tmp/lint-episodic-feat-plan-hecate-adoption.out
make test 2>&1 | tee /tmp/test-episodic-feat-plan-hecate-adoption.out
```

Also run `make typecheck`, `make markdownlint`, and `make nixie` if the
implementation changed Python typing or documentation:

```shell
make typecheck 2>&1 | tee /tmp/typecheck-episodic-feat-plan-hecate-adoption.out
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-feat-plan-hecate-adoption.out
make nixie 2>&1 | tee /tmp/nixie-episodic-feat-plan-hecate-adoption.out
```

Run final review:

```shell
coderabbit review --agent 2>&1 | tee /tmp/coderabbit-episodic-feat-plan-hecate-adoption.out
```

Clear every CodeRabbit concern or document why a concern is intentionally not
actionable. If any gate fails, fix the issue before the final commit. After all
gates and review pass, update `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective`, then make the final commit.

## Acceptance criteria

- `pyproject.toml` includes Hecate pinned to
  `46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12` and defines the production
  `[tool.hecate]` policy.
- `make check-architecture` runs Hecate and exits `0` on the current
  production package graph.
- `make lint` still includes the architecture gate.
- Architecture fixture tests and BDD scenarios still prove forbidden domain to
  storage imports, forbidden inbound to outbound imports, re-export handling,
  star re-export handling, explicit empty `__all__` handling, allowed graphs,
  and composition-root wiring.
- Episodic no longer owns an independent duplicate checker implementation,
  unless an explicitly approved compatibility shim remains.
- ADR, system design, users' guide when applicable, developers' guide, and
  roadmap text describe the implemented Hecate-backed architecture gate.
- `make check-fmt`, `make lint`, and `make test` pass with logs under `/tmp`.
- CodeRabbit review has been run after each major milestone, and all concerns
  have been cleared or explicitly resolved.
- The final implementation is committed in small, reviewable commits.

## Rollback plan

Each milestone should be committed separately. If Hecate adoption fails after a
later milestone, revert the most recent milestone commit first and rerun the
focused gate for the previous milestone.

If the pinned Hecate dependency cannot be installed, revert the dependency and
policy commit and leave the repo-local checker untouched. If fixture conversion
fails but production Hecate succeeds, keep the production Hecate branch only if
tests can be made green without deleting coverage; otherwise revert to the last
commit where `make lint` and architecture tests passed.

Never use `git reset --hard` or `git checkout --` to roll back user or other
agent changes. Use ordinary revert commits or ask for direction if unrelated
work is present in the same files.

## Outcomes & Retrospective

Not started. This plan is awaiting approval. When implementation completes,
record what changed, which gates passed, what CodeRabbit reported, which
roadmap entry was updated, and any follow-up work left for deferred
orchestration enforcement.

[^1]: Hecate users' guide at pinned SHA:
  <https://raw.githubusercontent.com/leynos/hecate/46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12/docs/users-guide.md>
[^2]: Hecate Episodic migration notes at pinned SHA:
  <https://raw.githubusercontent.com/leynos/hecate/46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12/docs/migration-episodic.md>
[^3]: Hecate configuration guide at pinned SHA:
  <https://raw.githubusercontent.com/leynos/hecate/46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12/docs/configuration.md>
[^4]: Hecate project metadata at pinned SHA:
  <https://raw.githubusercontent.com/leynos/hecate/46f8c8798e7a80a3a1ab5a13c2a000a4423ffc12/pyproject.toml>
