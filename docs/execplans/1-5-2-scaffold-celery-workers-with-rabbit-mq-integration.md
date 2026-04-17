# Scaffold Celery workers with RabbitMQ integration

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: COMPLETE

## Purpose and big picture

Roadmap item `1.5.2` fills the missing asynchronous worker scaffold for the
canonical-content platform. The system design already commits Episodic to a
split between a control plane and a data plane: Falcon on Granian handles HTTP
ingress, while Celery on RabbitMQ handles durable background execution. At the
moment, the repository has the HTTP scaffold from `1.5.1`, but it does not yet
expose a typed worker runtime, queue-routing configuration, or a hexagonal seam
for dispatching workload classes to the correct worker pool.

After this work, developers will be able to boot Celery workers against the
project's application factory, route tasks through explicit RabbitMQ bindings
and routing keys, and reason about I/O-bound versus CPU-bound execution using
configuration that matches the design document. The result must remain a
scaffold rather than a full workflow implementation: the purpose is to make the
worker boundary, queue taxonomy, and runtime wiring real so later roadmap items
(such as LangGraph suspend-and-resume flows, evaluator fan-out, and audio jobs)
can build on a stable foundation.

Success is observable in the following ways:

1. The repository exposes a typed Celery application factory and runtime
   configuration module under `episodic/` rather than relying on ad hoc global
   Celery state.
2. RabbitMQ exchanges, queues, queue bindings, and routing keys are defined in
   one canonical configuration surface, with explicit workload categories for
   I/O-bound and CPU-bound tasks.
3. The worker runtime supports distinct concurrency-pool choices for I/O-bound
   and CPU-bound workloads, aligned with the design document's `gevent` or
   `eventlet` versus `prefork` guidance, while keeping the chosen initial
   implementation explicit.
4. The scaffold includes typed task-registration seams and at least one
   representative task per workload class so routing and execution can be
   verified without inventing domain behaviour that belongs to later roadmap
   items.
5. Unit tests written with `pytest` fail first and then pass for queue
   definitions, routing decisions, runtime configuration, and worker-factory
   behaviour.
6. Behavioural tests written with `pytest-bdd` verify worker dispatch and
   execution through public contract surfaces, using Vidai Mock for any
   inference-facing task path included in the scaffold.
7. Documentation updates land in `docs/users-guide.md`,
   `docs/developers-guide.md`, the design document, and a new ADR that records
   the worker-routing and concurrency decisions.
8. `docs/roadmap.md` marks `1.5.2` done only after `make check-fmt`,
   `make typecheck`, `make lint`, and `make test` all succeed.

## Constraints

- Preserve the hexagonal architecture invariants from the
  `hexagonal-architecture` skill:
  - domain and application services must not import Celery, kombu, RabbitMQ
    clients, or worker-runtime configuration directly;
  - outbound worker adapters may depend on ports, but orchestration and task
    code must not import concrete inbound or outbound adapters directly;
  - adapter-to-adapter imports remain forbidden; interactions happen through
    typed ports, message payloads, or explicit dependency seams.
- Keep Celery runtime assembly separate from business logic. Queue topology,
  worker boot configuration, and Celery application construction belong in a
  worker runtime module, not in domain modules.
- Use typed configuration objects or frozen dataclasses for queue and runtime
  definitions. Avoid open dictionaries as the main architectural contract.
- Keep this roadmap item as scaffolding. Do not implement full LangGraph
  orchestration, checkpoint persistence, generation-run storage, or production
  evaluator workflows that belong to later roadmap items.
- Ensure queue bindings and routing keys are explicit and canonical. A future
  maintainer must be able to identify how a task is routed without tracing
  imperative code across multiple modules.
- Use fail-first tests for new behaviour: add or update tests first, confirm
  they fail, then implement the production code and rerun the same tests.
- Provide both unit coverage and behavioural coverage. Behavioural tests must
  use `pytest-bdd`.
- Use Vidai Mock for behavioural testing of inference services. If the scaffold
  includes any representative inference task or `LLMPort`-backed path, that
  behavioural coverage must run through Vidai Mock instead of a live provider
  or a hand-rolled fake.
- Record the architectural decisions in a new ADR under `docs/adr/` and update
  the primary design document so the implemented scaffold matches the stated
  architecture.
- Update `docs/users-guide.md` for user-visible worker/runtime behaviour and
  `docs/developers-guide.md` for maintainer-facing worker wiring, queue
  topology, and test guidance.
- Mark roadmap item `1.5.2` done only after implementation, tests,
  documentation, and quality gates are complete.

## Tolerances

- Scope tolerance: stop and escalate if the scaffold expands beyond roughly 16
  files or 1200 net new lines before a working vertical slice exists.
- Dependency tolerance: stop and escalate if implementation requires new
  runtime dependencies beyond Celery, kombu-compatible queue declarations,
  RabbitMQ support already bundled with Celery, or a small compatibility helper
  already present in the environment.
- Interface tolerance: stop and escalate if preserving the current HTTP
  scaffold and hexagonal boundaries would require broad public API changes
  outside the worker/runtime area.
- Test-environment tolerance: stop and escalate if reliable behavioural tests
  require a new long-lived external service harness that is not already
  supported by the repository's existing test strategy.
- Concurrency tolerance: stop and escalate if the initial worker design cannot
  represent both I/O-bound and CPU-bound pools cleanly without committing to an
  operational model contradicted by the design document.
- Iteration tolerance: stop and escalate after three failed attempts to
  stabilize the same worker behavioural scenario or broker-backed test path.

## Risks

- Risk: the repository may not yet include Celery or kombu, so adding the
  worker scaffold could introduce dependency and import-shape churn. Severity:
  medium. Likelihood: medium. Mitigation: inspect `pyproject.toml` and existing
  modules early, keep the runtime surface small, and confine dependency
  additions to the minimal set needed for the scaffold.

- Risk: broker-backed behavioural tests can become flaky if they depend on a
  real RabbitMQ instance that is not provisioned consistently in local and CI
  environments. Severity: high. Likelihood: medium. Mitigation: prefer
  contract-level behavioural verification around the worker runtime and task
  routing seams, and only use a live broker path if the repository already has
  a stable strategy for it.

- Risk: queue taxonomy may drift from the design document if routing keys,
  queues, and concurrency classes are defined in multiple places. Severity:
  medium. Likelihood: high. Mitigation: centralize topology definitions in one
  typed module and ensure both runtime wiring and tests read from that same
  source of truth.

- Risk: representative tasks may accidentally grow into domain behaviour that
  belongs to later roadmap items. Severity: medium. Likelihood: medium.
  Mitigation: keep the tasks intentionally narrow, such as echo, diagnostic, or
  probe-style tasks that exercise routing and dependency seams without claiming
  business completeness.

- Risk: Vidai Mock integration may be underspecified for worker contexts if no
  current inference-facing task scaffold exists. Severity: low. Likelihood:
  medium. Mitigation: decide early whether the scaffold includes an
  `LLMPort`-facing task. If not, document explicitly why Vidai Mock is not
  exercised in this slice; if yes, route all behavioural coverage for that task
  through Vidai Mock.

## Progress

- [x] Review the current repository state for Celery, RabbitMQ, worker runtime,
  test infrastructure, and relevant design constraints.
- [x] Add fail-first unit and behavioural tests covering queue topology,
  routing decisions, worker-factory wiring, and representative tasks.
- [x] Implement the typed worker runtime, queue topology, and task-registration
  scaffold.
- [x] Implement representative I/O-bound and CPU-bound task paths and the
  associated dependency seams.
- [x] Update ADR, design, developer, and user documentation, then mark roadmap
  item `1.5.2` done.
- [x] Run `make check-fmt`, `make typecheck`, `make lint`, and `make test`, and
  record the outcome.

## Surprises & Discoveries

- Observation: The repository had no pre-existing Celery, Kombu, or RabbitMQ
  runtime surface. Evidence: Stage A codebase inspection and the initial
  red-phase collection failure (`ModuleNotFoundError` for `kombu`). Impact:
  `pyproject.toml` had to add Celery, and the worker scaffold could be
  introduced without conflicting with legacy runtime modules.
- Observation: A live RabbitMQ behavioural harness still does not exist in the
  repository. Evidence: Existing behavioural coverage patterns cover Falcon,
  py-pglite, and Vidai Mock, but nothing provisions a broker-backed queue path.
  Impact: Behavioural coverage for `1.5.2` was kept at the contract level:
  create the Celery app from environment configuration, inspect queue routing,
  and execute representative tasks in eager mode.
- Observation: Celery task names can be reused across app instances during one
  pytest session unless the scaffold explicitly replaces prior registrations.
  Evidence: The full `make test` run initially reused an earlier task
  registration, so injected fake dependencies were not observed. Impact:
  `register_scaffold_tasks(...)` now removes prior scaffold task names before
  registering app-specific task closures.

## Decision Log

- Decision: Keep the first worker behavioural slice broker-free.
  Rationale: A contract-level Celery factory plus eager-mode task execution
  proves the queue and runtime seams without inventing an unstable RabbitMQ
  fixture strategy. Date/Author: 2026-04-09 / Codex.
- Decision: Introduce a dedicated `episodic/worker/` package with separate
  `topology.py`, `runtime.py`, and `tasks.py` modules. Rationale: This mirrors
  the accepted Falcon composition-root split and keeps queue topology,
  environment parsing, and task registration in explicit adapter modules.
  Date/Author: 2026-04-09 / Codex.
- Decision: Represent the first I/O-bound and CPU-bound tasks as diagnostic
  scaffolds with typed payload and dependency seams. Rationale: Roadmap item
  `1.5.2` needed real routing and extension points, not premature workflow
  behaviour from later roadmap items. Date/Author: 2026-04-09 / Codex.

## Outcomes & Retrospective

Outcome:

- Added a typed worker scaffold under `episodic/worker/` with:
  - canonical queue topology (`episodic.tasks`, `episodic.io`, `episodic.cpu`);
  - RabbitMQ-backed runtime configuration parsing and worker launch profiles;
  - representative I/O-bound and CPU-bound diagnostic tasks; and
  - environment-driven Celery application creation via
    `episodic.worker.runtime:create_celery_app_from_env`.
- Added fail-first unit and `pytest-bdd` coverage in
  `tests/test_worker_service_scaffold.py`,
  `tests/features/worker_service_scaffold.feature`, and
  `tests/steps/test_worker_service_scaffold_steps.py`.
- Added ADR-003 and updated the design, developer, user, and roadmap
  documentation to reflect the implemented worker boundary.

Retrospective:

- The scaffold stayed within the intended scope by proving queue topology,
  routing, and dependency injection without adding broker orchestration,
  checkpoint persistence, or workflow-specific task logic.
- The only meaningful implementation trap was Celery task-name reuse across
  repeated app construction in one pytest session; addressing that in the
  scaffold registration path should make future task additions less surprising.
- Validation completed successfully:
  - `make check-fmt`
  - `make lint`
  - `make typecheck` (existing non-blocking `redundant-cast` warnings remain in
    untouched files)
  - `make test` (`330 passed, 2 skipped`)
  - `PATH=/root/.bun/bin:$PATH make markdownlint`
  - `make nixie`

## Context and orientation

The repository already contains the canonical-content platform, SQLAlchemy
persistence, Falcon HTTP scaffolding on Granian, and documentation describing a
hexagonal architecture with explicit worker boundaries.

The most relevant documents for this work are:

- `docs/roadmap.md`, which marks `1.5.2` as the missing worker scaffold.
- `docs/episodic-podcast-generation-system-design.md`, especially the
  Architectural Summary, Hexagonal architecture enforcement, Orchestration
  guardrails, and Control and data plane separation sections.
- `docs/agentic-systems-with-langgraph-and-celery.md`, which describes the
  control-plane versus data-plane split, RabbitMQ as the durable broker, Redis
  or Valkey as the result/checkpoint store, and suspend-and-resume patterns.
- `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md`, and
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`, which define the
  repository's expectations for async runtime setup and testing discipline.
- `docs/users-guide.md` and `docs/developers-guide.md`, which will need to
  reflect the implemented worker/runtime contract once the scaffold exists.

The adjacent roadmap item `1.5.1` already established an HTTP composition root
using a typed dependency object. This worker scaffold should mirror that
pattern: a pure task-registration or Celery-app assembly module should remain
separate from any environment-reading runtime entrypoint so the code stays
hexagonal and testable.

The design document states that LangGraph acts as the control plane and Celery
as the data plane. For this roadmap slice, the important implication is that
Celery tasks must be framed as boundary adapters or orchestration entrypoints,
not as places where domain logic grows uncontrolled. The worker scaffold should
make it easy for later orchestration code to depend on ports and typed payloads
only.

## Stage A: investigate current worker and dependency state

Start by mapping the current repository state before deciding where to insert
new code.

1. Inspect `pyproject.toml` for Celery, kombu, RabbitMQ-related packages, and
   existing testing helpers.
2. Inspect `episodic/` for any existing worker, task, queue, runtime, or
   orchestration modules that already establish naming conventions.
3. Inspect the current HTTP scaffold files and existing ADRs to mirror the
   composition-root patterns already accepted for `1.5.1`.
4. Inspect `tests/` for existing async runtime or behavioural patterns that can
   be reused for worker coverage.
5. Inspect `Makefile` targets so the final validation flow uses repository
   conventions rather than ad hoc commands.

This stage is complete when the implementation entrypoints, likely file
locations, missing dependencies, and reusable test patterns are known.

## Stage B: add fail-first tests for queue topology and worker runtime

Add tests before production code changes.

1. Create a new unit test module, suggested name
   `tests/test_worker_service_scaffold.py`, covering:
   - canonical queue topology definitions for exchanges, queues, bindings, and
     routing keys;
   - worker runtime configuration parsing and validation;
   - Celery application factory behaviour, including task routing; and
   - representative task registration for one I/O-bound path and one CPU-bound
     path.
2. Add behavioural coverage with `pytest-bdd`, suggested files:
   - `tests/features/worker_service_scaffold.feature`
   - `tests/steps/test_worker_service_scaffold_steps.py`
3. Shape the behavioural scenarios around observable contract surfaces, for
   example:
   - creating the worker application from configuration exposes the documented
     queue topology;
   - a representative I/O-bound task resolves to the I/O routing key and queue;
   - a representative CPU-bound task resolves to the CPU routing key and queue;
   - if an inference-facing representative task exists, its behaviour runs
     through Vidai Mock.
4. Keep the first test run red and capture the expected failures, such as
   missing worker modules, undefined queue configuration, or absent task
   registration.

Expected red-phase examples:

```plaintext
E   ModuleNotFoundError: No module named 'episodic.worker.runtime'
E   AssertionError: expected routing key 'episodic.io.*' to exist
E   KeyError: 'cpu_bound'
```

## Stage C: implement typed worker configuration and queue topology

Once the fail-first tests are in place, implement the smallest production slice
that satisfies them.

1. Add a worker topology module, likely under `episodic/worker/` or another
   repository-consistent package, that defines:
   - the canonical exchange name or names;
   - named queues for I/O-bound and CPU-bound workloads;
   - routing keys for each workload family; and
   - any dead-letter or future extension placeholders only if the design or
     current roadmap text explicitly requires them.
2. Use typed dataclasses, enums, or Protocol-friendly value objects so the
   topology can be imported safely by runtime code, task modules, and tests.
3. Add a worker configuration module that reads environment variables and
   produces a typed runtime configuration object, including:
   - RabbitMQ broker URL;
   - result-backend configuration if needed by the chosen scaffold;
   - per-workload pool choices;
   - concurrency values or defaults for I/O-bound and CPU-bound workers.
4. Keep import-time side effects minimal. Parsing environment should happen in
   explicit factory functions, not at module import time.

The result of this stage should be a reusable, typed description of the worker
runtime that expresses the queue and concurrency contract in one place.

## Stage D: implement Celery application factory and representative tasks

With typed configuration and topology in place, implement the actual worker
scaffold.

1. Add a Celery application factory, likely in `episodic/worker/runtime.py`,
   that:
   - constructs a Celery app from the typed runtime configuration;
   - registers the canonical queue topology and routing configuration;
   - exposes task-discovery or explicit registration in a deterministic way;
   - keeps runtime assembly separate from domain code.
2. Add representative task modules for at least two workload classes:
   - one I/O-bound task that is safe, narrow, and suitable for routing tests;
   - one CPU-bound task that is equally narrow and deterministic.
3. If the scaffold needs to demonstrate an inference-service seam, add a third
   representative task that depends on a typed port and ensure its behavioural
   tests use Vidai Mock.
4. Keep the task bodies intentionally small. They should prove registration,
   routing, and dependency wiring rather than claim to implement future roadmap
   behaviour.
5. Ensure tasks depend on typed payloads and ports where appropriate, never by
   importing concrete adapters across hexagonal boundaries.

The result of this stage should be a worker runtime that can be instantiated,
inspected by tests, and extended safely by future roadmap items.

## Stage E: behavioural verification strategy

Once the worker scaffold exists, make the behavioural contract real.

1. Decide whether the repository can support a live broker-backed behavioural
   path with existing test infrastructure. If it can, use that path to verify a
   representative dispatch and result flow.
2. If a live broker path would exceed the stated tolerances, keep behavioural
   tests focused on public worker surfaces that remain deterministic under the
   current repository constraints, such as task routing metadata and runtime
   factory output.
3. If an inference-facing representative task exists, use Vidai Mock as the
   only behavioural test provider for that path.
4. Record the chosen behavioural scope explicitly in the ADR and developer's
   guide so later roadmap items know whether this slice proved full broker
   dispatch or only routing/runtime contracts.

## Stage F: documentation, ADR, and roadmap updates

After code and tests are green, update the documentation set.

1. Add a new ADR under `docs/adr/`, likely `adr-003-celery-worker-scaffold.md`
   unless repository numbering indicates otherwise. Capture:
   - the queue topology and routing-key taxonomy;
   - the choice of initial concurrency pools for I/O-bound and CPU-bound
     workloads;
   - the decision on whether behavioural coverage uses a live broker path or
     contract-level verification only.
2. Update `docs/episodic-podcast-generation-system-design.md` to reference the
   new ADR and align its worker/runtime language with the implemented scaffold.
3. Update `docs/developers-guide.md` with:
   - where the worker runtime and topology live;
   - how to add new tasks without violating hexagonal boundaries;
   - how to run the worker-focused tests; and
   - when Vidai Mock is required for worker tasks that call inference ports.
4. Update `docs/users-guide.md` with any user-visible or operator-visible
   worker/runtime behaviour, such as the worker start command, queue model, or
   runtime expectations that are relevant to operators.
5. Update `docs/roadmap.md` and mark `1.5.2` done only after all implementation
   and validation gates pass.

## Stage G: validation and acceptance

Run the required quality gates sequentially from repository root after the
implementation and documentation are complete.

```shell
make check-fmt
make typecheck
make lint
make test
```

If documentation changes introduce additional repository-required markdown
validation targets, run those as well according to the current Makefile and
project conventions discovered during implementation.

Acceptance evidence to capture during implementation should include concise
proof such as:

```plaintext
tests/test_worker_service_scaffold.py::test_worker_topology_defines_io_and_cpu_queues PASSED
tests/test_worker_service_scaffold.py::test_celery_app_routes_cpu_task_to_cpu_queue PASSED
tests/steps/test_worker_service_scaffold_steps.py::test_worker_scaffold_contract PASSED
```

and, if applicable:

```plaintext
make check-fmt: PASS
make typecheck: PASS
make lint: PASS
make test: PASS
```

## Idempotence and recovery

This plan should be implemented in small, restartable stages. The intended file
additions and edits are additive and can be rerun safely. If a stage fails
partway through:

- restore test-first discipline by rerunning the targeted failing tests;
- keep queue topology and runtime parsing centralized so partial edits do not
  leave duplicate configuration sources behind; and
- avoid destructive operations against external RabbitMQ instances or shared
  infrastructure during scaffolding.

If live broker testing is attempted and proves unstable, stop at the tolerance
boundary, document the issue in `Decision Log`, and request direction rather
than improvising a broad infrastructure detour.

## Artifacts and notes

Implementation should preserve a concise record of:

- the chosen queue names and routing keys;
- the worker start command or commands;
- the exact behavioural scope achieved in tests;
- the final validation command outputs.

## Interfaces and dependencies

The finished scaffold should expose stable, typed interfaces along these lines:

- a typed worker runtime configuration object describing broker URL, result
  backend settings if any, queue names, routing keys, pool choices, and
  concurrency values;
- a Celery application factory under a stable module path such as
  `episodic.worker.runtime:create_celery_app_from_env` or an equivalent naming
  pattern consistent with the repository;
- representative task names that encode workload class clearly enough for
  routing policy and operational debugging;
- task payload and dependency seams that depend on ports or typed DTOs instead
  of direct adapter imports.

The exact names should be finalized only after repository inspection confirms
existing naming conventions.

## Revision note

Initial draft created on 2026-04-06 for roadmap item `1.5.2`, based on the
current roadmap, design documents, testing guidance, and existing ExecPlan
conventions. The next revision must replace assumptions with repository facts
from Stage A and update `Progress`, `Surprises & Discoveries`, and
`Decision Log` accordingly.
