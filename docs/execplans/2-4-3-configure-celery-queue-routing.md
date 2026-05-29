# Configure Celery queue routing for workload isolation

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`,
and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: COMPLETE

## Purpose / big picture

Roadmap item `2.4.3` configures Celery queue routing, so the generation
platform can isolate I/O-bound and CPU-bound work. I/O-bound work is work that
spends most of its time waiting on network or storage operations, such as Large
Language Model (LLM) calls, tool calls, database calls, or resume callbacks.
CPU-bound work is work that spends most of its time using processor cycles,
such as local parsing, scoring, transcript analysis, or other deterministic
batch computation.

After this change, enqueueable worker tasks have an explicit workload
classification. I/O-bound tasks route to the durable `episodic.io` queue with
routing keys under `episodic.io.#`, and operators can run those workers with a
high-concurrency greenlet pool such as `gevent` or `eventlet`. CPU-bound tasks
route to the durable `episodic.cpu` queue with routing keys under
`episodic.cpu.#`, and operators can run those workers with the Celery `prefork`
pool. A maintainer can inspect the Celery application configuration and see
that every registered worker task used by this roadmap slice is mapped to a
queue intentionally rather than falling through to the default I/O route.

This plan does not implement cost-ledger persistence from roadmap item `2.4.4`,
budget enforcement from later roadmap items, or a mandatory live RabbitMQ
integration harness. The default validation remains brokerless and
contract-level, matching Architecture Decision Record (ADR) 003. A later
roadmap slice may add live RabbitMQ dispatch coverage on top of the same
topology without changing the boundary.

Success is observable in these behaviours:

1. `episodic/worker/topology.py` remains the single source of truth for the
   topic exchange, workload classes, durable queues, routing-key families, and
   task-route metadata.
2. `episodic/worker/runtime.py` builds a Celery app whose `task_queues`,
   `task_routes`, default queue and worker launch profiles preserve the
   documented I/O versus CPU split.
3. Any production or representative worker task introduced by this roadmap
   item is explicitly classified as I/O-bound or CPU-bound before it can be
   routed.
4. Unit tests fail before the implementation when a route is missing,
   malformed, duplicated, or assigned to the wrong workload class, and pass
   after the implementation.
5. Behavioural tests using `rstest-bdd` or the repository's Python BDD pattern
   show an operator inspecting the worker routing and seeing distinct I/O and
   CPU queue contracts. If an orchestration-facing behavioural path uses LLM
   calls, it uses Vidai Mock rather than a live provider.
6. Property tests using `proptest` for Rust code, or Hypothesis for Python
   code, cover route-key invariants if the implementation introduces a
   non-trivial route resolver or parser over a range of task names or workload
   labels.
7. Documentation records the route contract for users, maintainers, and design
   readers. The roadmap entry is marked done only after implementation,
   documentation, validation, CodeRabbit review and commit gates succeed.

## Constraints

- Implementation must not start until this ExecPlan is explicitly approved.
- Preserve hexagonal architecture boundaries. Domain and application code must
  not import Celery, Kombu, RabbitMQ client types, Falcon resources, SQLAlchemy
  adapters, or concrete LLM provider clients.
- Keep queue topology and broker mechanics inside the worker adapter boundary:
  `episodic/worker/topology.py`, `episodic/worker/runtime.py`, and narrowly
  scoped worker task registration modules.
- LangGraph orchestration code may emit typed workload intent through ports or
  data transfer objects (DTOs), but route resolution and Celery configuration
  remain adapter concerns.
- Celery tasks must stay single-responsibility and idempotent. Task bodies
  should use typed payload DTOs and injected dependencies rather than reaching
  directly into storage, HTTP, LLM, or queue adapters.
- Do not add a mandatory live RabbitMQ dependency to the default validation
  path. Broker-backed dispatch tests may be added only as an optional explicit
  target if the repository already has stable infrastructure for it.
- Do not add new runtime dependencies without escalation. The plan should use
  Celery, Kombu, existing test tools, Vidai Mock where applicable, and existing
  repository patterns.
- Use official Celery semantics for routing and worker launch documentation:
  `task_routes`, `task_queues`, routing keys, `-Q` queue selection, `--pool`,
  `--concurrency`, and `--autoscale`.
- Use Vidai Mock only for behavioural tests that exercise inference or
  orchestration flows requiring deterministic LLM responses. Pure routing and
  topology tests must not start Vidai Mock.
- Keep roadmap scope limited to workload isolation. Do not implement
  cost-accounting persistence, pricing catalogues, budget breach alerts, public
  generation-run APIs, or deeper audit ledger work in this change.
- Update `docs/episodic-podcast-generation-system-design.md`,
  `docs/users-guide.md`, `docs/developers-guide.md`, relevant ADRs, and
  `docs/roadmap.md` when implementation lands.
- Run validation commands sequentially, not in parallel:
  `make check-fmt`, `make typecheck`, `make lint`, and `make test`. For
  documentation changes, also run `make markdownlint` and `make nixie`. Capture
  long command output with `tee` under `/tmp`.
- Run `coderabbit review --agent` after each major implementation milestone
  and clear all concerns before moving to the next milestone.
- Commit each approved, validated logical change with a file-based commit
  message using `git commit -F`.

## Tolerances (exception triggers)

- Scope: stop and escalate if implementation requires more than 16 changed
  files or 900 net new lines before validation passes.
- Interface: stop and escalate if an incompatible public signature change is
  required for existing worker factories, orchestration DTOs, `LLMPort`,
  checkpoint ports, Falcon resources, or canonical repository ports.
- Dependency: stop and escalate if routing cannot be implemented without a new
  runtime package, a new broker service in default tests, or a new external
  test service beyond Vidai Mock.
- Boundary: stop and escalate if practical implementation requires domain,
  canonical, or application services to import Celery, Kombu, RabbitMQ,
  SQLAlchemy adapters, concrete OpenAI clients, or Falcon resources.
- Ambiguity: stop and present options if unknown task behaviour could mean
  either strict fail-fast classification or fallback-to-default routing because
  that choice materially affects workload isolation.
- Orchestration coupling: stop and escalate if route intent cannot be added
  without redesigning LangGraph execution or changing checkpoint persistence
  semantics from roadmap item `2.4.2`.
- Testing: stop and escalate if focused routing tests still fail after three
  implementation attempts, or if full `make test` still fails after two
  unrelated-failure triage passes.
- Infrastructure: stop and escalate if a live RabbitMQ harness becomes
  necessary to prove the acceptance criteria.
- CodeRabbit: stop and escalate if `coderabbit review --agent` reports a
  concern that requires changing approved scope or cannot be cleared locally.

## Risks

- Risk: unclassified tasks may silently fall back to the default I/O queue,
  defeating workload isolation. Severity: high. Likelihood: medium. Mitigation:
  require explicit task-to-workload mappings for every registered worker task
  in scope, and test route map completeness.

- Risk: worker launch profiles may describe the intended pools, while
  operators can still start workers with mismatched `-Q`, `--pool`, or
  `--concurrency` command-line options. Severity: medium. Likelihood: medium.
  Mitigation: document launch commands and keep `WorkerLaunchProfile` as the
  canonical operator contract; do not pretend code can enforce external process
  flags unless a launch wrapper is explicitly added.

- Risk: broadening routing from diagnostic tasks to workflow tasks could
  introduce Celery imports into orchestration or domain code. Severity: high.
  Likelihood: medium. Mitigation: confine Celery and Kombu to worker runtime
  and topology modules; pass workload intent through typed ports, DTOs, or
  dependency seams.

- Risk: testing with eager Celery execution can prove route metadata and task
  registration, but not a full RabbitMQ publish/consume round trip. Severity:
  medium. Likelihood: high. Mitigation: keep the acceptance claim precise,
  document the brokerless scope, and leave a later live-dispatch follow-up if
  needed.

- Risk: greenlet pools such as `gevent` and `eventlet` may have feature
  limitations compared with `prefork`, including timeout behaviour. Severity:
  medium. Likelihood: medium. Mitigation: route only I/O-bound work to greenlet
  pools by default, and document that CPU-bound work uses prefork.

- Risk: property tests over routing keys may overconstrain valid Advanced
  Message Queuing Protocol (AMQP) topic patterns. Severity: low. Likelihood:
  medium. Mitigation: keep invariants aligned with the repository's accepted
  taxonomy, not every possible AMQP routing pattern.

- Risk: Vidai Mock could be applied to pure routing tests unnecessarily,
  slowing the suite and obscuring failures. Severity: low. Likelihood: medium.
  Mitigation: use Vidai Mock only when the route decision is observed through
  an LLM-backed orchestration scenario.

## Relevant documentation and skills

Use these repository documents while implementing the plan:

- `docs/roadmap.md`, especially roadmap item `2.4.3`.
- `docs/episodic-podcast-generation-system-design.md`, especially
  "LangGraph Integration Principles", "Control and data plane separation",
  "Execution patterns for long-running tasks", and "Orchestration ports and
  adapters".
- `docs/agentic-systems-with-langgraph-and-celery.md`, especially the sections
  on RabbitMQ routing, I/O-bound worker pools, CPU-bound worker pools, and
  suspend-and-resume task patterns.
- `docs/langgraph-and-celery-in-hexagonal-architecture.md`, especially the
  sections warning against Celery tasks bypassing ports.
- `docs/async-sqlalchemy-with-pg-and-falcon.md`,
  `docs/testing-async-falcon-endpoints.md`, and
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` if a routing change
  touches persistence, HTTP, or integration fixtures. The expected
  implementation should not require those surfaces.
- `docs/users-guide.md` for operator-visible worker configuration.
- `docs/developers-guide.md` for maintainer-facing task registration and
  routing conventions.
- `docs/adr/adr-003-celery-worker-scaffold.md` for the accepted worker
  topology and brokerless test scope.
- `docs/adr/adr-007-durable-generation-checkpoints.md` because it currently
  treats Celery routing as later work.

Apply these Codex skills while implementing the plan:

- `leta` for code navigation and refactoring.
- `hexagonal-architecture` for boundary checks around ports and adapters.
- `execplans` for maintaining this living plan.
- `vidai-mock` only for LLM-backed behavioural tests.
- `rust-router` and the smallest relevant Rust skill if the implementation
  touches Rust code. The likely implementation is Python only.
- `commit-message` for file-based commits.
- `pr-creation` and `en-gb-oxendict-style` for pull request preparation.

External references consulted for this plan:

- Celery's routing guide documents `task_routes`, `task_queues`, routing keys,
  named queues, and `celery worker -Q queue_a,queue_b` queue selection.
- Celery's concurrency guide identifies `prefork` as the default and preferred
  pool for CPU-bound tasks, and `gevent` or `eventlet` as I/O-oriented greenlet
  pools with feature limitations.
- Celery's worker guide documents `--concurrency`, `--autoscale`,
  `--max-tasks-per-child`, `--max-memory-per-child`, and queue selection with
  `-Q`.

## Repository orientation

The existing worker scaffold is already close to the target shape.
`episodic/worker/topology.py` defines `WorkerTopology`, `WorkerQueueSpec`,
`WorkloadClass`, and `DEFAULT_WORKER_TOPOLOGY`. The default topology uses one
durable topic exchange, `episodic.tasks`, and two durable queues: `episodic.io`
with binding key `episodic.io.#`, and `episodic.cpu` with binding key
`episodic.cpu.#`.

`episodic/worker/runtime.py` defines `WorkerRuntimeConfig`,
`WorkerLaunchProfile`, `load_runtime_config(...)`,
`build_worker_launch_profiles(...)`, `create_celery_app(...)`, and
`create_celery_app_from_env()`. The runtime validates an AMQP broker URL,
configures JSON serialization, disables missing queue creation, sets the
default queue, registers known task routes, and exposes pool/concurrency
profiles.

`episodic/worker/tasks.py` defines representative diagnostic task names,
payload/result DTOs, `WorkerDependencies`, `SCAFFOLD_TASK_WORKLOADS`, and
`register_scaffold_tasks(...)`. Existing tests cover the diagnostic route
contract, but future implementation should tighten the contract so new routed
tasks cannot be registered without an explicit workload classification.

The orchestration package currently owns LangGraph control flow, checkpoint
DTOs, ports, and result aggregation under `episodic/orchestration/`. Any route
intent added there must remain provider-neutral. Do not import Celery or Kombu
from orchestration modules.

## Implementation plan

### Milestone 1: confirm the current routing contract and write fail-first tests

Before changing production code, inspect the current symbols with Leta:

```bash
leta show episodic/worker/topology.py:WorkerTopology
leta show episodic/worker/topology.py:WorkerQueueSpec
leta show episodic/worker/runtime.py:create_celery_app
leta show episodic/worker/runtime.py:build_worker_launch_profiles
leta show episodic/worker/tasks.py:register_scaffold_tasks
```

Then add focused tests that express the final behaviour. Use the existing
`tests/test_worker_service_scaffold.py` style for unit tests and the existing
`tests/features/worker_service_scaffold.feature` plus
`tests/steps/test_worker_service_scaffold_steps.py` style for behavioural
tests. These tests should fail before the implementation if the current
scaffold still allows the gap being closed.

Plan the following unit tests:

1. Every task registered by the worker module has exactly one explicit
   workload classification.
2. Route metadata for each classified task includes queue, exchange and
   routing key values that match the queue binding family for the workload.
3. Unknown workloads or malformed task names fail predictably instead of
   producing an accidental default route.
4. `task_create_missing_queues` remains false, and the configured queues are
   exactly the durable topology queues.
5. Worker launch profiles continue to map I/O workloads to `gevent` or another
   configured I/O pool with high concurrency and CPU workloads to `prefork`
   with lower concurrency.

Plan the following behavioural tests:

1. An operator creates the worker app from environment configuration and sees
   I/O tasks routed to `episodic.io` with `episodic.io.*` routing keys.
2. The same operator sees CPU tasks routed to `episodic.cpu` with
   `episodic.cpu.*` routing keys.
3. Invalid route metadata fails during app construction or topology
   construction with a clear error.

If a non-trivial route-key builder or parser is introduced, add a property test
that checks generated route keys are non-empty, contain no empty topic
segments, stay within the accepted `episodic.io.*` or `episodic.cpu.*`
families, and never map one task to two workloads. If the implementation is a
small constant mapping with existing validation, document in this plan why
property tests would not add useful rigour.

Run the focused tests and record the expected red result in `Progress`. Use
`tee` for output:

```bash
make test 2>&1 | tee /tmp/test-episodic-2-4-3-configure-celery-queue-routing.out
```

Stop at this milestone if the failing tests reveal that the roadmap task
requires choosing between strict unknown-task rejection and default fallback
routing.

### Milestone 2: implement explicit route classification and safe route metadata

Implement the smallest worker-boundary change that makes the fail-first tests
pass. The likely code paths are:

- `episodic/worker/tasks.py` for task names, typed task payloads and explicit
  task-to-workload mappings.
- `episodic/worker/topology.py` for route-building validation, queue binding
  invariants and any helper that resolves a task's workload to route metadata.
- `episodic/worker/runtime.py` for wiring the stricter route map into Celery
  app configuration and worker launch profiles.
- `episodic/worker/__init__.py` if a new helper or DTO becomes part of the
  worker module's public surface.

Prefer a route table that is explicit and auditable over pattern-matching task
names. If a helper is needed, name it in worker language, such as
`build_task_routes` or `route_for_task`, and keep it independent of domain
entities. Make sure the helper returns Celery-compatible route metadata without
forcing callers outside the worker boundary to import Celery.

Do not broaden the default queue as a substitute for classification. If the
implementation keeps a default I/O queue for Celery compatibility, tests, and
documentation must say that the default is not a licence for unclassified
production tasks.

Run focused tests after the implementation:

```bash
make test 2>&1 | tee /tmp/test-episodic-2-4-3-configure-celery-queue-routing.out
```

Then run:

```bash
coderabbit review --agent 2>&1 | tee /tmp/coderabbit-episodic-2-4-3-configure-celery-queue-routing.out
```

Clear any CodeRabbit concerns before continuing.

### Milestone 3: connect orchestration-facing workload intent only if needed

Inspect whether the generation orchestration introduced by roadmap item `2.4.2`
needs to dispatch route-aware Celery work in this slice. Use Leta on the
orchestration symbols before editing:

```bash
leta show episodic/orchestration/_dto.py:GenerationOrchestrationRequest
leta show episodic/orchestration/_protocols.py:TaskResumePort
leta show episodic/orchestration/langgraph.py:resume_generation_orchestration
```

If no orchestration task dispatch exists yet, do not invent a full dispatch
adapter. Instead, document that `2.4.3` hardens the worker routing contract and
leaves actual LangGraph-to-Celery dispatch to the next roadmap item that adds
real asynchronous generation tasks.

If orchestration does need to express route intent in this slice, add a small
provider-neutral DTO or enum that says whether a step is I/O-bound or
CPU-bound. The worker adapter may translate that intent into Celery route
metadata. The orchestration module must not import Celery, Kombu or RabbitMQ
types.

Use Vidai Mock only if the route intent is observed through an LLM-backed
generation behavioural scenario. Start with the existing
`tests/steps/test_generation_orchestration_steps.py` pattern rather than
creating a separate mock inference harness.

Run focused orchestration or BDD tests with `tee`, then run CodeRabbit again if
this milestone changes production code.

### Milestone 4: update documentation and decision records

Update documentation after code behaviour is stable:

- `docs/episodic-podcast-generation-system-design.md` should describe the
  finalized worker route contract, the I/O and CPU routing-key families, and
  the boundary rule that orchestration emits workload intent while worker
  adapters own Celery configuration.
- `docs/users-guide.md` should describe operator-visible worker configuration:
  queue names, routing keys, recommended worker launch options, and the fact
  that default validation does not require live RabbitMQ.
- `docs/developers-guide.md` should explain how maintainers add a new routed
  task: define a typed payload, classify the task, add tests, and avoid adapter
  leakage.
- `docs/adr/adr-003-celery-worker-scaffold.md` should be updated if the
  scaffold route contract becomes stricter or if representative tasks are
  joined by production workflow tasks.
- `docs/adr/adr-007-durable-generation-checkpoints.md` should stop describing
  Celery routing as entirely future work once this item lands.
- Add a new ADR only if implementation makes a substantive new decision beyond
  ADR-003, such as strict unknown-task rejection, a new route-intent DTO, or a
  launch wrapper contract.
- `docs/roadmap.md` should be marked done only at the end, after validation
  and CodeRabbit review pass.

Run documentation validation:

```bash
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-2-4-3-configure-celery-queue-routing.out
make nixie 2>&1 | tee /tmp/nixie-episodic-2-4-3-configure-celery-queue-routing.out
```

Run CodeRabbit again after the documentation milestone and clear all concerns.

### Milestone 5: run full gates, commit, push and open the draft pull request

Run the required gates sequentially:

```bash
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-2-4-3-configure-celery-queue-routing.out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-2-4-3-configure-celery-queue-routing.out
make lint 2>&1 | tee /tmp/lint-episodic-2-4-3-configure-celery-queue-routing.out
make test 2>&1 | tee /tmp/test-episodic-2-4-3-configure-celery-queue-routing.out
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-2-4-3-configure-celery-queue-routing.out
make nixie 2>&1 | tee /tmp/nixie-episodic-2-4-3-configure-celery-queue-routing.out
```

If all gates pass, mark roadmap item `2.4.3` done, update this ExecPlan's
living sections, run the relevant documentation gates again if
`docs/roadmap.md` changed, and commit. Use the `commit-message` skill and a
temporary message file:

```bash
git status --short
git diff --check
git add <changed files>
git diff --cached
git commit -F "$COMMIT_MSG_FILE"
```

Push the branch so it tracks `origin/2-4-3-configure-celery-queue-routing`,
then open a draft pull request. The pull request title must include `(2.4.3)`,
and the summary must mention this ExecPlan:
`docs/execplans/2-4-3-configure-celery-queue-routing.md`.

Run:

```bash
echo ${LODY_SESSION_ID}
```

Include the session link in the pull request body's final `## References`
section as:

```plaintext
https://lody.ai/leynos/sessions/${LODY_SESSION_ID}
```

## Validation strategy

The implementation uses red-green-refactor discipline. Tests are written or
updated first, then production code is changed, then documentation is aligned.

The minimum validation set is:

```bash
make check-fmt
make typecheck
make lint
make test
make markdownlint
make nixie
```

Use focused pytest invocations only while iterating, but final acceptance
requires the full gates above. Commands must run sequentially, with output
captured to `/tmp/*-episodic-2-4-3-configure-celery-queue-routing.out`.

Use Vidai Mock for any behavioural test that proves route intent through an
LLM-backed generation flow. Do not use Vidai Mock for pure topology, runtime,
or Celery app configuration tests.

Use property tests only when an introduced route resolver, parser, or
classifier has a meaningful invariant over a range of inputs. A fixed mapping
from constant task names to constant workload classes does not need property
tests unless it gains generated input handling.

Do not require live RabbitMQ for default validation. If an optional
broker-backed target is added later, it must be separate from the default pull
request gates and must not be the only proof of routing correctness.

## Progress

- [x] (2026-05-19T18:20:50Z) Loaded the `leta`,
  `hexagonal-architecture`, `execplans`, `firecrawl-mcp`, `vidai-mock`,
  `commit-message`, `pr-creation`, `en-gb-oxendict-style`, and `rust-router`
  skills relevant to planning this task.
- [x] (2026-05-19T18:20:50Z) Created a Leta workspace for this repository with
  `leta workspace add`.
- [x] (2026-05-19T18:20:50Z) Confirmed the branch was
  `feat/celery-routing-execplan` and renamed it locally to
  `2-4-3-configure-celery-queue-routing`.
- [x] (2026-05-19T18:20:50Z) Reviewed `AGENTS.md`, `docs/roadmap.md`, the
  existing `2.4.2` ExecPlan, the worker scaffold, worker tests, and the
  relevant design and ADR context.
- [x] (2026-05-19T18:20:50Z) Used Firecrawl to consult official Celery routing,
  concurrency, and worker documentation for route and pool terminology.
- [x] (2026-05-19T18:20:50Z) Used a Wyvern agent team to review likely
  implementation scope, architecture and documentation impacts, and validation
  strategy.
- [x] (2026-05-19T18:20:50Z) Drafted this pre-implementation ExecPlan for
  roadmap item `2.4.3`.
- [x] (2026-05-19T18:48:27Z) Validated this planning-only Markdown change with
  `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie`. The first `make test` run hit one
  transient async fixture timeout after 660 passes; the focused failing test
  passed on rerun, and the full `make test` rerun passed with
  `661 passed, 3 skipped`.
- [x] (2026-05-19T18:48:27Z) Ran `coderabbit review --agent` for the planning
  milestone and applied all eight minor/trivial prose findings.
- [x] (2026-05-19T19:00:12Z) Ran a CodeRabbit confirmation pass, applied two
  additional minor prose findings, and reran `make markdownlint` plus
  `make nixie` successfully.
- [x] (2026-05-19T19:13:40Z) Committed this ExecPlan, pushed the branch, and
  opened draft pull request [#106](https://github.com/leynos/episodic/pull/106)
  for plan review.
- [x] (2026-05-24T00:00:00Z) Received explicit approval to proceed with the
  planned implementation.
- [x] (2026-05-24T00:00:00Z) Implemented Milestone 1 fail-first
  route-contract tests and ran `make test` with output captured in
  `/tmp/test-red-episodic-2-4-3-configure-celery-queue-routing.out`. The run
  failed as expected with four failures covering missing exchange metadata,
  missing `SCAFFOLD_TASK_NAMES`, and missing malformed route-table validation.
- [x] (2026-05-24T15:59:35Z) Implemented Milestone 2 strict route
  classification and metadata. The worker route builder now validates task
  names and `WorkloadClass` values, scaffold task names are explicit, route
  metadata includes `queue`, `exchange`, `exchange_type`, and `routing_key`,
  and the BDD scenario asserts both exchange and queue targeting.
- [x] (2026-05-24T15:59:35Z) Ran deterministic gates before CodeRabbit:
  `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie` all passed. The post-implementation
  test run passed with `664 passed, 3 skipped`.
- [x] (2026-05-24T16:11:21Z) Ran CodeRabbit for the implementation milestone.
  CodeRabbit reported two minor findings asking for clearer assertion failure
  messages in `tests/test_worker_routing_contract.py`; both were valid and were
  applied.
- [x] (2026-05-24T16:17:32Z) Re-ran gates after applying CodeRabbit findings:
  `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie` all passed. The test run again passed
  with `664 passed, 3 skipped`.
- [x] (2026-05-24T16:19:43Z) Reviewed Milestone 3 orchestration-facing
  workload intent. `GenerationOrchestrationRequest`, `TaskResumePort`, and
  `resume_generation_orchestration(...)` remain provider-neutral and do not
  dispatch Celery work yet, so this slice does not add a new route-intent DTO
  or Vidai Mock scenario.
- [x] (2026-05-24T16:19:43Z) Updated the design document, users' guide,
  developers' guide, ADR-003, and ADR-007 to describe strict route-table
  validation, full queue/exchange route metadata, and the worker-adapter
  boundary.
- [x] (2026-05-24T16:30:15Z) Ran documentation gates and CodeRabbit for the
  documentation milestone. `make markdownlint` and `make nixie` passed, and
  CodeRabbit reported no findings.
- [x] (2026-05-24T16:30:15Z) Marked roadmap item `2.4.3` done after the
  worker and documentation milestones had passed deterministic gates and
  CodeRabbit review.
- [x] (2026-05-24T16:46:52Z) Ran final gates: `make check-fmt`,
  `make typecheck`, `make lint`, `make test`, `make markdownlint`, and
  `make nixie` all passed. The final test run passed with
  `664 passed, 3 skipped`.
- [x] (2026-05-24T16:46:52Z) Ran final CodeRabbit review after deterministic
  gates; CodeRabbit reported no findings.
- [x] (2026-05-24T16:49:45Z) Committed the documentation and roadmap close-out,
  pushed branch `2-4-3-configure-celery-queue-routing`, and updated draft pull
  request #106 with the implementation summary, validation results, CodeRabbit
  status, execplan link, and Lody session reference.

## Surprises & Discoveries

- Observation: the existing worker scaffold already defines `episodic.io` and
  `episodic.cpu` queues, workload launch profiles, and eager-mode behavioural
  tests. Impact: implementation should harden and extend the route contract
  rather than replace the scaffold.

- Observation: `create_celery_app(...)` currently configures the default queue
  as the I/O queue. Impact: implementation must decide and document whether
  unclassified production tasks fail fast, or whether Celery's default remains
  only a compatibility fallback.

- Observation: ADR-003 deliberately keeps worker behavioural coverage
  brokerless. Impact: this roadmap item should not require live RabbitMQ unless
  the user explicitly approves a broader integration-test slice.

- Observation: official Celery documentation supports explicit `task_routes`
  and `task_queues`, queue selection with `-Q`, `prefork` for CPU-bound work,
  and `gevent` or `eventlet` for I/O-bound work. Impact: the repository's
  design terminology matches Celery's documented operational model.

- Observation: the Wyvern agents could not inspect the MCP context pack even
  though it was created in this parent session. Impact: future agent teams may
  need direct file references as well as context pack identifiers.

- Observation: `make fmt` rewrote many existing Markdown files outside this
  planning task. Impact: those formatter-only side effects were restored
  because the worktree was clean before the command, and this branch should
  carry only the new ExecPlan.

- Observation: the first full `make test` run reported one timeout in
  `test_list_endpoints_reject_invalid_pagination` during async fixture setup,
  while the focused rerun and full rerun both passed. Impact: record it as a
  transient validation anomaly rather than a plan regression.

- Observation: adding the fail-first unit coverage to
  `tests/test_worker_service_scaffold.py` pushed that file over the Pylint
  module length limit. Impact: the route-table tests were moved into
  `tests/test_worker_routing_contract.py`, leaving scaffold execution tests in
  the original module.

## Decision Log

- Decision: Keep this ExecPlan in draft status and do not implement routing
  until explicit approval is received. Rationale: the `execplans` skill
  requires an approval gate, and the user explicitly said the plan must be
  approved before implementation.

- Decision: Treat default validation as brokerless and contract-level.
  Rationale: ADR-003 already accepted eager-mode routing tests for the worker
  scaffold, and the roadmap item can prove route configuration without a live
  RabbitMQ dependency.

- Decision: Use strict route classification as the preferred implementation
  direction while preserving escalation if default fallback semantics are
  required. Rationale: workload isolation is weakened if new tasks silently
  route to the I/O queue by default.

- Decision: Use Vidai Mock only for orchestration-facing behavioural tests that
  need deterministic inference responses. Rationale: topology and Celery
  configuration are pure routing concerns and should not depend on an inference
  simulator.

- Decision: Plan for Hypothesis or property-test coverage only if generated or
  parsed route inputs are introduced. Rationale: property tests add useful
  rigour for invariants over ranges of inputs, but a fixed constant route table
  is better covered by precise unit and behavioural tests.

- Decision: Do not add property tests for this implementation milestone.
  Rationale: the change keeps a fixed, explicit route table and validates only
  structural fields; there is no generated route parser or classifier whose
  behaviour ranges over arbitrary inputs.

- Decision: Do not add orchestration-facing workload intent in this roadmap
  slice. Rationale: the current LangGraph orchestration exposes request,
  checkpoint, and resume ports but does not dispatch Celery tasks; adding a DTO
  now would be speculative and would broaden the worker-boundary task beyond
  workload isolation.

## Outcomes & Retrospective

Roadmap item `2.4.3` shipped as a worker-boundary hardening slice. The Celery
topology still exposes one topic exchange, `episodic.tasks`, and the two
durable queues `episodic.io` and `episodic.cpu`; route construction now
validates task names and workload values before producing Celery route
metadata. Representative scaffold tasks have an explicit task-name tuple and
workload map, and task routes include queue, exchange, exchange type, and
routing key.

The implementation deliberately did not add LangGraph-to-Celery dispatch or a
new orchestration workload-intent DTO because the current orchestration layer
does not enqueue Celery work yet. This preserves the documented hexagonal
boundary: orchestration stays provider-neutral, and the worker adapter owns
Celery mechanics. Vidai Mock was not used because no LLM-backed behavioural
route path changed.

Validation completed with `make check-fmt`, `make typecheck`, `make lint`,
`make test`, `make markdownlint`, and `make nixie`. CodeRabbit reviewed the
worker milestone, the documentation milestone, and the final state; all
findings were cleared, and the final review reported no findings.
