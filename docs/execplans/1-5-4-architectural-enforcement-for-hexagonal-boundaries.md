# Implement architectural enforcement for hexagonal boundaries

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: APPROVED - implementation in progress

## Purpose and big picture

Roadmap item `1.5.4` is the missing automation layer for the boundary rules
that were documented in `1.5.3`. The design document already says Episodic uses
a hexagonal architecture with domain logic, typed ports, inbound adapters,
outbound adapters, and composition roots. Today, however, that rule set is
still enforced mostly by convention. Ruff is configured and CI already gates on
`make lint` plus `make test`, but the repository does not yet have a dedicated
dependency-direction checker or an architecture-test suite that proves concrete
adapters still satisfy the published port contracts.

After this work, a maintainer should be able to change code in
`episodic/canonical`, `episodic/api`, `episodic/llm`, and related packages and
immediately learn whether the change crosses a forbidden boundary. The local
developer path and the Continuous Integration (CI) path should agree:
`make lint` must fail on forbidden imports, `make test` must fail when adapters
stop honouring port contracts, and CI must surface the architecture gate
clearly enough that a reviewer can tell whether a failure is a formatting
problem, a typing problem, or a boundary-regression problem.

This plan intentionally lands the foundation for boundary enforcement in the
current service scaffold without consuming roadmap item `2.4.5`. Item `1.5.4`
should make the core canonical, HTTP, worker-runtime, and Large Language Model
(LLM) seams enforceable now. Item `2.4.5` should then extend the same checker
framework to deeper orchestration-specific rules for LangGraph nodes, Celery
tasks, and checkpoint payload audits.

Success is observable in eight ways:

1. A repo-local architecture checker exists, emits stable diagnostics, and can
   classify modules into allowed dependency groups without requiring an
   external service.
2. `make lint` fails when a scoped module imports from a forbidden layer, with
   messages that name the offending importer, imported module, and violated
   rule.
3. Dedicated `pytest` architecture tests validate that concrete adapters still
   satisfy the public port protocols they are meant to implement.
4. `pytest-bdd` scenarios prove the architecture checker's behaviour against
   small fixture packages that represent allowed and forbidden import graphs.
5. Current boundary leaks inside the scoped packages are either removed or
   reduced to a documented, explicit allowlist with a roadmap-backed reason.
6. CI exposes architecture enforcement as a named gate and fails the pipeline
   when the checker or architecture tests fail.
7. A new Architecture Decision Record (ADR), the design document, the
   developers' guide, and a short users' guide note all describe the
   enforcement model and its scope.
8. `docs/roadmap.md` marks `1.5.4` done only after
   `make check-fmt`, `make typecheck`, `make lint`, `make test`,
   `make markdownlint`, and `make nixie` all pass.

Implementation approval rule:

- This document is a draft only. No implementation work should begin until the
  user explicitly approves this plan.

## Constraints

- Preserve the core invariants from the `hexagonal-architecture` skill:
  - domain and application logic must not import Falcon, SQLAlchemy adapter
    modules, Celery runtime code, provider SDK adapters, or other
    infrastructure-heavy modules directly;
  - ports remain the typed integration boundary;
  - inbound adapters depend on domain or application code plus ports, not on
    concrete outbound adapters; and
  - cross-adapter imports are forbidden unless the file is an explicitly named
    composition root.
- Treat composition roots as a small, explicit exception set. Files such as
  `episodic/api/runtime.py` and `episodic/worker/runtime.py` are allowed to
  wire concrete adapters together because that is their purpose. The checker
  must model that exception deliberately rather than weakening the whole rule
  set.
- Keep `1.5.4` scoped to enforceable architecture rules for the current service
  scaffold. Do not use this roadmap item to implement the orchestration
  extensions already reserved for `2.4.5`, such as deep checkpoint-payload
  audits or LangGraph-node-specific policies beyond what is necessary to avoid
  contradiction with the design.
- Avoid a broad package reorganisation unless the checker cannot be made
  truthful without moving code. Prefer small refactors that remove specific
  boundary leaks over renaming half the repository.
- Use fail-first tests for each milestone: add or update tests, run them to
  confirm failure, implement the production changes, then rerun the same test
  cluster.
- Use `pytest` for unit and architecture tests, and `pytest-bdd` for
  behavioural tests.
- Use Vidai Mock for behavioural testing of inference services. This roadmap
  item does not need to invoke an inference path merely to mention Vidai Mock.
  If an implementation change causes a behavioural test to exercise
  `LLMPort`-backed inference directly, that behaviour test must use Vidai Mock.
- Keep existing public API and runtime behaviour stable. This work adds
  enforcement, not new user-facing endpoints or protocol changes.
- Record the enforcement design in a new ADR under `docs/adr/`.
- Update `docs/episodic-podcast-generation-system-design.md`,
  `docs/developers-guide.md`, and `docs/users-guide.md` so the documented
  enforcement scope matches the implementation exactly.
- Mark roadmap item `1.5.4` done only after the implementation, tests,
  documentation updates, and validation gates are complete.

## Tolerances

- Scope tolerance: stop and escalate if the first working slice requires more
  than roughly 18 files or 1200 net new lines before the checker can run on at
  least one meaningful production package group.
- Dependency tolerance: stop and escalate if the plan appears to require more
  than one lightweight new development dependency. The preferred path is zero
  new dependencies, using a repo-local checker plus existing test tooling.
- Refactor tolerance: stop and escalate if current boundary leaks are numerous
  enough that enforcement would first require a large package split rather than
  a few targeted fixes.
- Roadmap tolerance: stop and escalate if making `1.5.4` pass would force full
  implementation of `2.4.5` in the same change.
- Composition-root tolerance: stop and escalate if the checker cannot model
  composition-root exceptions cleanly and would therefore report legitimate
  runtime-wiring modules as violations.
- Diagnostic tolerance: stop and escalate after three failed attempts to make
  the same checker message stable enough for reliable `pytest-bdd` assertions.

## Risks

- Risk: some current canonical service helpers already import
  `episodic.canonical.storage.models`, which means a strict gate will fail
  immediately. Severity: high. Likelihood: high. Mitigation: identify the
  existing leaks early, then either refactor them behind neutral constants or
  classify them in a temporary, explicit allowlist with a removal note tied to
  the roadmap.

- Risk: composition roots legitimately import concrete adapters, and an
  over-simplified checker could classify them as violations. Severity: high.
  Likelihood: medium. Mitigation: encode composition roots as a first-class
  module group with narrow, documented exceptions rather than ad hoc ignores.

- Risk: public ports are expressed as `typing.Protocol`, but the repository
  does not currently mark them `@runtime_checkable`, which makes direct runtime
  contract assertions awkward. Severity: medium. Likelihood: high. Mitigation:
  add `@runtime_checkable` only to the public ports that architecture tests
  actually need to assert at runtime.

- Risk: the design document currently speaks as though orchestration-specific
  architecture tests already exist, while the roadmap defers a dedicated
  extension of those rules to `2.4.5`. Severity: medium. Likelihood: high.
  Mitigation: use the ADR and design update to clarify the staged rollout:
  `1.5.4` establishes the checker framework and current core rules, and `2.4.5`
  extends that framework to orchestration-specific policies.

- Risk: behavioural tests for an internal linting tool can become brittle if
  they assert on full multi-line output. Severity: medium. Likelihood: medium.
  Mitigation: assert on stable substrings such as rule identifiers, importer
  paths, and imported-module names rather than exact whole-file transcripts.

## Progress

- [x] (2026-04-24 00:00Z) Reviewed `docs/roadmap.md`, the system design, the
  async Falcon and py-pglite testing references, the existing scaffold
  ExecPlans, and the current Makefile and CI workflow.
- [x] (2026-04-24 00:00Z) Re-inspected the current package layout under
  `episodic/` and confirmed that Ruff import conventions are present but no
  dedicated architecture checker or architecture-test suite exists yet.
- [x] (2026-04-24 00:00Z) Identified current hot spots that will matter during
  implementation, especially `episodic/canonical/profile_templates/helpers.py`
  and `episodic/canonical/reference_documents/bindings.py`, which currently
  reach into `episodic.canonical.storage.models`.
- [x] (2026-04-30 22:14Z) User explicitly approved implementation of this
  ExecPlan and requested that the living plan stay current throughout the
  change.
- [x] (2026-04-30 22:14Z) Stage A: define the first enforced module map and add
      fail-first
  architecture tests plus behaviour fixtures.
- [x] (2026-04-30 22:18Z) Stage B: implement the repo-local architecture
      checker and Makefile
  wiring.
- [x] (2026-04-30 22:21Z) Stage C: remove or explicitly justify current
      boundary leaks, then enable
  the checker on the scoped production packages.
- [x] (2026-04-30 22:23Z) Stage D: add runtime-checkable port contract tests
      for current concrete
  adapters.
- [x] (2026-04-30 22:27Z) Stage E: wire CI, ADR, and guide updates, then mark
      the roadmap item
  complete.
- [x] (2026-04-30 22:42Z) Stage F: run the full validation gates and update
  this ExecPlan with the delivery outcome.

## Surprises & Discoveries

- Observation: `pyproject.toml` already enables Ruff's general import hygiene
  rules (`ICN`, `TID`, `TC`), but nothing in the current config encodes the
  repository's package-to-package dependency graph. Impact: `1.5.4` needs a
  dedicated checker rather than a small Ruff setting tweak.

- Observation: CI already runs `make lint` and `make test`, so the plumbing for
  a gate exists, but no named architecture-enforcement step is present in
  `.github/workflows/ci.yml`. Impact: the implementation can reuse the current
  pipeline while still adding a visible architecture gate for reviewers.

- Observation: `episodic/api/runtime.py` legitimately imports the concrete
  `SqlAlchemyUnitOfWork` adapter. Impact: composition roots must be modelled as
  explicit exceptions, not accidental false positives.

- Observation: `episodic/canonical/profile_templates/helpers.py` imports
  `REVISION_CONSTRAINT_NAMES` from `episodic.canonical.storage.models`, and
  `episodic/canonical/reference_documents/bindings.py` imports several storage
  uniqueness-constraint constants from the same module. Impact: at least two
  current boundary leaks must be addressed before a repo-wide gate can be made
  truthful.

- Observation: `docs/roadmap.md` reserves
  `2.4.5 Extend architecture enforcement to orchestration code`, while the
  design document's current prose reads as though LangGraph-node and Celery
  task checks already exist. Impact: the documentation update in this plan must
  reconcile that staged rollout clearly.

- Observation: The first focused red run could not reach pytest collection
  until the Makefile's `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` environment was
  applied. Impact: all subsequent focused and full validation commands should
  use the Makefile targets or carry the same environment variable when invoking
  `uv run` directly.

- Observation: The checker initially saw `from package import storage` as an
  import of `package` only. Impact: `ImportFrom` handling now emits both the
  base module and imported member path so fixture and production diagnostics
  catch package-level adapter imports.

- Observation: `make fmt` runs `mdformat-all`, which shells out to a
  repository-wide `markdownlint --fix` invocation and reports older MD013
  line-length findings in many pre-existing documents. The dedicated
  `make markdownlint` gate uses the configured `markdownlint-cli2` path and
  passes with zero errors. Impact: this slice treats `make fmt` as blocked by
  pre-existing formatter-tool scope, while `make check-fmt`, `make lint`,
  `make test`, `make typecheck`, `make markdownlint`, and `make nixie` are
  green.

- Observation: Post-turn hooks run in a narrower `PATH` than the interactive
  shell, so Makefile targets that required global `ruff`, `ty`, or
  `markdownlint-cli2` binaries failed before reaching the actual checks.
  Impact: the Makefile now invokes Python developer tools through `uv`, pins
  the `ty` tool runner to the already validated `0.0.32` version, and invokes
  Markdown lint through `npx -y markdownlint-cli2`.

## Decision Log

- Decision: implement architecture import enforcement as a repo-local checker
  with a dedicated Makefile target, then wire that target into `make lint` and
  CI. Rationale: the boundary rules are specific to Episodic's package map, and
  a repo-local checker keeps diagnostics deterministic, testable, and easy to
  extend for `2.4.5`. Date/Author: 2026-04-24 / Codex.

- Decision: scope the first enforcement slice to the current core service
  layers and their composition roots, not the full future orchestration rule
  set. Rationale: this honours the roadmap sequencing and avoids collapsing
  `1.5.4` and `2.4.5` into one over-large change. Date/Author: 2026-04-24 /
  Codex.

- Decision: validate port adherence through `@runtime_checkable` public
  protocols plus focused adapter tests that use existing fixtures, especially
  the py-pglite `session_factory` and LLM adapter fixtures. Rationale: this
  proves the published contracts using the repository's existing test harness
  instead of inventing a second abstract contract layer. Date/Author:
  2026-04-24 / Codex.

- Decision: use `pytest-bdd` against small architecture-fixture packages rather
  than against self-mutating production files. Rationale: behavioural tests
  should prove the checker's observable behaviour without rewriting real source
  files during the test run. Date/Author: 2026-04-24 / Codex.

- Decision: move database constraint-name constants used by service-layer
  conflict handling into `episodic.canonical.constraints` and re-export them to
  storage models by import. Rationale: the names are part of the canonical
  conflict contract, while SQLAlchemy model classes remain outbound adapter
  infrastructure. Date/Author: 2026-04-30 / Codex.

- Decision: keep Stage D port tests structural and avoid live inference calls.
  Rationale: `LLMPort` conformance only needs the adapter method surface for
  `1.5.4`, so Vidai Mock remains unnecessary until future behaviour tests
  exercise inference-backed orchestration. Date/Author: 2026-04-30 / Codex.

## Outcomes & Retrospective

Implementation began after explicit approval on 2026-04-30. The delivery adds
the repo-local architecture checker, production boundary fixes, port contract
tests, CI visibility, ADR-005, guide updates, and roadmap completion.

Delivered outcome:

- `make lint` includes an architecture-enforcement step that rejects forbidden
  import directions in the scoped package groups.
- `make test` includes architecture tests that prove the current concrete
  adapters still satisfy the public port contracts.
- CI exposes architecture enforcement as a named gate.
- The design document and ADR set explain the staged scope clearly:
  `1.5.4` covers the core service scaffold, while `2.4.5` extends the same
  mechanism to orchestration-specific rules.
- `docs/roadmap.md` marks `1.5.4` done only after all validation gates pass.

Validation outcome:

- `make check-fmt` passed.
- `make typecheck` passed with existing `ty` redundant-cast warnings.
- `make lint` passed, including `make check-architecture`.
- `make test` passed: 393 passed, 3 skipped.
- `make markdownlint` passed with zero errors.
- `make nixie` passed.
- `make fmt` failed in `mdformat-all` because its raw `markdownlint --fix`
  invocation reports pre-existing MD013 line-length findings across older
  documentation files that are outside this change. The committed files pass
  the configured Markdown and formatting gates above.

## Context and orientation

This section describes the current repository state so a novice can navigate
the change confidently.

### Relevant documentation

The implementation should stay anchored to the following documents:

- `docs/roadmap.md`
  - `1.5.4 Implement architectural enforcement checks for hexagonal
    boundaries`
  - `2.4.5 Extend architecture enforcement to orchestration code`
- `docs/episodic-podcast-generation-system-design.md`
  - `Architectural Summary`
  - `Hexagonal architecture enforcement`
  - `Orchestration ports and adapters`
- `docs/async-sqlalchemy-with-pg-and-falcon.md`
- `docs/testing-async-falcon-endpoints.md`
- `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`
- `docs/agentic-systems-with-langgraph-and-celery.md`
- `docs/execplans/1-5-1-scaffold-falcon-http-services-on-granian.md`
- `docs/execplans/1-5-2-scaffold-celery-workers-with-rabbit-mq-integration.md`
- `docs/adr/adr-002-http-service-composition-root.md`
- `docs/adr/adr-003-celery-worker-scaffold.md`

### Relevant skills

The implementer should keep the following skills close at hand:

- `execplans` for keeping this document current as implementation proceeds.
- `hexagonal-architecture` for the dependency-rule, port-ownership, and
  adapter-isolation invariants.
- `vidai-mock` only if a behavioural test in this slice ends up exercising a
  real `LLMPort`-backed inference path.

### Current package map

The production package already has enough structure for a useful first
enforcement slice:

- `episodic/canonical/domain.py`, `episodic/canonical/ingestion.py`,
  `episodic/canonical/ports.py`, and `episodic/canonical/ingestion_ports.py`
  hold the core domain and public port contracts for canonical content.
- `episodic/canonical/services.py`,
  `episodic/canonical/ingestion_service.py`,
  `episodic/canonical/profile_templates/`, and
  `episodic/canonical/reference_documents/` hold application-service style
  workflows that should depend on domain types and ports rather than concrete
  storage adapters.
- `episodic/canonical/storage/` and `episodic/canonical/adapters/` hold the
  concrete outbound adapters for persistence and ingestion pipeline behaviour.
- `episodic/api/` holds the Falcon inbound adapter, with
  `episodic/api/runtime.py` acting as the composition root.
- `episodic/llm/ports.py` defines the public LLM port, while
  `episodic/llm/openai_adapter.py` and `episodic/llm/openai_client.py` hold a
  concrete outbound adapter.
- `episodic/worker/runtime.py` is another composition root. It should remain
  explicitly modelled, but orchestration-specific worker-task rules are still a
  later roadmap concern.

### Current gaps

The current codebase documents the architecture but does not yet automate it:

- `Makefile` exposes `lint`, `typecheck`, and `test`, but `lint` currently
  runs `ruff check` only.
- `.github/workflows/ci.yml` runs `make lint` and `make test`, but there is no
  named architecture-enforcement step.
- No `tests/test_architecture_*.py` module exists yet.
- No `tests/features/architecture_*.feature` scenario exists yet.
- Public ports such as `CanonicalUnitOfWork`, the ingestion ports, and
  `LLMPort` are `typing.Protocol` contracts but are not currently marked
  `@runtime_checkable`.

### Terms used in this plan

- Architecture checker: the repo-local static checker that walks imports,
  classifies modules, and reports forbidden dependency directions.
- Composition root: a module whose job is to construct concrete adapters and
  wire them into an inbound surface, for example `episodic/api/runtime.py`.
- Port contract test: a `pytest` test that proves a concrete adapter still
  satisfies the public protocol it claims to implement.
- Architecture fixture package: a small package tree under `tests/fixtures/`
  used by behavioural tests to prove allowed and forbidden import graphs.

## Stage A: define the first enforced module map and add fail-first tests

Start by turning the intended rules into executable expectations before adding
the checker itself.

1. Add a new unit-test module, suggested name
   `tests/test_architecture_enforcement.py`, that defines the first supported
   module groups and expected dependency directions.
2. The first rule set should be intentionally small and explicit:
   - domain and public-port modules may not import inbound adapters, outbound
     adapters, or composition roots;
   - application-service modules may depend on domain and ports, but not on
     concrete storage or LLM adapter modules;
   - inbound adapters may depend on domain or application code plus ports, but
     not directly on concrete outbound adapters except through explicit
     composition roots; and
   - composition roots may import the concrete adapters they wire.
3. Add architecture-fixture packages under `tests/fixtures/architecture/`, for
   example:
   - `allowed_case/`
   - `domain_imports_storage/`
   - `api_imports_outbound_adapter/`
   - `composition_root_allows_wiring/`
4. Add a behavioural feature file,
   `tests/features/architecture_enforcement.feature`, with scenarios such as:
   - a violating domain module is rejected with a clear diagnostic;
   - a violating inbound adapter is rejected with a clear diagnostic; and
   - a composition root that wires adapters is accepted.
5. Add matching BDD steps in
   `tests/steps/test_architecture_enforcement_steps.py`. The steps should call
   the checker through its public function or command-line entrypoint, not by
   importing private helpers.
6. Add a red-phase assertion for the current production hot spots so the work
   is honest about today's leaks. The initial failure may reference
   `episodic/canonical/profile_templates/helpers.py` and
   `episodic/canonical/reference_documents/bindings.py`.
7. Run the targeted architecture unit tests and BDD scenarios first and record
   the red phase.

Suitable red-phase examples:

```plaintext
E architecture: episodic.canonical.profile_templates.helpers imports forbidden
  module episodic.canonical.storage.models
E architecture: episodic.canonical.reference_documents.bindings imports
  forbidden module episodic.canonical.storage.models
E ModuleNotFoundError: No module named 'episodic.architecture'
```

## Stage B: implement the repo-local architecture checker and Makefile wiring

Implement the smallest production checker that can satisfy the new tests.

1. Add a new module for the checker, for example:
   - `episodic/architecture/__init__.py`
   - `episodic/architecture/checker.py`
   - `episodic/architecture/rules.py`
2. Keep the checker repo-local and deterministic:
   - parse imports from Python source using the standard library `ast` module;
   - resolve only repository-local `episodic.*` imports for rule checking;
   - ignore imports inside `tests/` except for the fixture packages used to
     prove checker behaviour; and
   - emit stable diagnostics that include a rule identifier, importer module,
     imported module, and a short reason.
3. Store the first-scope dependency policy in one explicit manifest structure
   rather than scattering ad hoc conditionals. A frozen dataclass or named
   tuple structure is suitable here.
4. Add a Makefile target such as `check-architecture` that runs the checker
   through `uv run python -m episodic.architecture`.
5. Update `make lint` so it runs both Ruff and `check-architecture`.
6. Keep the checker extensible for `2.4.5`, but do not yet implement deep
   checkpoint-payload or LangGraph-node-specific rules in this stage.

Expected Stage B result:

- `make lint` has an explicit architecture-enforcement sub-step.
- The checker can run against both production code and fixture packages.

## Stage C: remove current boundary leaks and enable the scoped production gate

With the checker available, make the production package conform to the scoped
rules.

1. Fix the known canonical-to-storage leaks identified during discovery:
   - `episodic/canonical/profile_templates/helpers.py`
   - `episodic/canonical/reference_documents/bindings.py`
2. The preferred fix is to move storage-specific constraint-name knowledge
   behind a neutral seam, for example:
   - a small port-facing constant module that is safe for service-layer use; or
   - a storage helper that translates database exceptions into domain-level
     conflict signals before the service layer inspects them.
3. Keep any allowlist temporary, narrow, and documented. If one exception must
   survive this roadmap item, record it in the checker manifest together with a
   comment that names the owning roadmap item or ADR.
4. Confirm that the scoped production packages now pass the checker locally.
5. Keep composition roots explicitly allowed and covered by fixture tests so
   the checker remains truthful about wiring modules such as
   `episodic/api/runtime.py`.

Go/no-go for Stage C:

- the checker passes on the scoped production modules without undocumented
  ignores; and
- the BDD scenarios still distinguish genuine violations from legitimate
  composition-root wiring.

## Stage D: add runtime-checkable port contract tests

Once import-direction enforcement exists, prove that the current concrete
adapters still satisfy the published ports.

1. Add `@runtime_checkable` to the public protocols that architecture tests
   need to assert at runtime. The likely initial set is:
   - `episodic.canonical.ports.CanonicalUnitOfWork`
   - `episodic.canonical.ingestion_ports.SourceNormalizer`
   - `episodic.canonical.ingestion_ports.WeightingStrategy`
   - `episodic.canonical.ingestion_ports.ConflictResolver`
   - `episodic.llm.ports.LLMPort`
2. Extend `tests/test_architecture_enforcement.py` or add a sibling module such
   as `tests/test_port_contracts.py`.
3. Prove the current concrete adapters satisfy those protocols using existing
   fixtures:
   - `SqlAlchemyUnitOfWork` against the py-pglite-backed `session_factory`
   - `InMemorySourceNormalizer`
   - `DefaultWeightingStrategy`
   - `HighestWeightConflictResolver`
   - `OpenAICompatibleLLMAdapter` through the existing LLM adapter fixture
     pattern in `tests/fixtures/llm.py`
4. Keep these tests structural and contract-focused. They should not duplicate
   the existing adapter behaviour tests in full; they should prove that the
   adapter still exposes the expected protocol surface and can be treated as
   the port type.
5. If a runtime-checkable protocol would be misleading because a structural
   `isinstance(...)` check is too weak on its own, pair it with one or two
   targeted assertions on method names or call signatures rather than widening
   the public API.

Vidai Mock note:

- Stage D should not require Vidai Mock unless the contract test for
  `LLMPort` intentionally exercises a live inference-facing behaviour path. A
  structural adapter contract test using the existing fixture and mock
  transport is sufficient for `1.5.4`.

## Stage E: wire CI and update the documentation set

After the checker and tests are green locally, update the documented operating
model.

1. Update `.github/workflows/ci.yml` so architecture enforcement is visible as
   a named gate. One acceptable pattern is:
   - add a `Run architecture checks` step that calls `make check-architecture`;
   - keep `Run ruff` as the general lint step; and
   - leave `make test` to collect the architecture tests along with the rest of
     the suite.
2. Add a new ADR, expected path
   `docs/adr/adr-005-hexagonal-architecture-enforcement.md`, describing:
   - why Ruff alone is insufficient for Episodic's dependency graph;
   - the chosen checker shape and scope;
   - the explicit composition-root exception model; and
   - the staged relationship between `1.5.4` and `2.4.5`.
3. Update `docs/episodic-podcast-generation-system-design.md`:
   - add the new ADR to the accepted decision-record list; and
   - revise the enforcement prose so it matches the staged rollout honestly.
4. Update `docs/developers-guide.md` with:
   - the architecture checker command;
   - the meaning of each enforced module group;
   - how to extend the manifest when a new port or adapter is added;
   - how to run the architecture BDD tests; and
   - when Vidai Mock becomes required for future inference-facing behavioural
     coverage.
5. Update `docs/users-guide.md` with a brief, truthful note only. This feature
   does not add a new public API surface, so the user-facing update should be
   small, for example noting that releases now gate on architecture checks that
   protect API and workflow stability.
6. Update `docs/roadmap.md` and mark `1.5.4` done only after Stage F passes.

## Stage F: run the full validation gates

Run every gate sequentially from repository root. Use `tee` so truncated
outputs remain inspectable.

```shell
set -o pipefail; make fmt 2>&1 | tee /tmp/execplan-1-5-4-make-fmt.log
set -o pipefail; make check-fmt 2>&1 | tee /tmp/execplan-1-5-4-make-check-fmt.log
set -o pipefail; make typecheck 2>&1 | tee /tmp/execplan-1-5-4-make-typecheck.log
set -o pipefail; make lint 2>&1 | tee /tmp/execplan-1-5-4-make-lint.log
set -o pipefail; make test 2>&1 | tee /tmp/execplan-1-5-4-make-test.log
set -o pipefail; PATH=/root/.bun/bin:$PATH make markdownlint 2>&1 | tee /tmp/execplan-1-5-4-make-markdownlint.log
set -o pipefail; make nixie 2>&1 | tee /tmp/execplan-1-5-4-make-nixie.log
```

Acceptance criteria for completion:

1. `make check-fmt`, `make typecheck`, `make lint`, and `make test` all pass.
2. Markdown validation also passes because this feature adds an ExecPlan, an
   ADR, and guide updates.
3. The checker fails on known bad fixture packages and passes on the scoped
   production package set.
4. Port contract tests pass for the concrete adapters covered in Stage D.
5. CI exposes the architecture gate clearly.
6. `docs/roadmap.md` marks `1.5.4` done only after the previous five items are
   true.
