# Upgrade to Python 3.14: adopt concurrent interpreters for CPU workloads

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & discoveries`, `Decision log`, and
`Outcomes & retrospective` must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

Status: DRAFT

## Purpose and big picture

After this change, Episodic will have an optional execution path that uses
Python 3.14 subinterpreters (`concurrent.interpreters` and
`InterpreterPoolExecutor`) for selected CPU-bound tasks. The observable result
is true multi-core parallelism with explicit isolation boundaries for safe
workloads, enabling future LangGraph and Celery CPU-heavy stages to scale
without immediate process-level fan-out everywhere.

Success is visible when a constrained CPU task can run through the interpreter
executor, produce deterministic results, and pass functional and performance
smoke checks.

## Constraints

- Keep hexagonal boundaries intact: orchestration code uses ports, not direct
  executor coupling in domain logic.
- Do not switch all task execution to subinterpreters in one step.
- Restrict first adoption to explicitly interpreter-safe workloads.
- Do not introduce backward-incompatible changes to planned task ports.
- Maintain current test reliability and pass full Python gates.

## Tolerances (exception triggers)

- Scope: if first milestone requires touching more than 14 files, stop and
  escalate.
- Safety: if a candidate workload imports extension modules that are not
  subinterpreter-safe, stop and escalate with alternative options.
- Performance: if prototype throughput is worse than baseline by more than 15%
  for selected CPU tasks, stop and escalate before broad rollout.
- Validation: if repeated nondeterministic failures appear in new concurrency
  tests, stop and escalate.

## Risks

- Risk: C extension compatibility in subinterpreters may vary by dependency.
  Severity: high. Likelihood: medium. Mitigation: start with pure-Python CPU
  tasks and explicitly gate adapter usage by capability checks.

- Risk: serialization boundaries may increase overhead for small tasks.
  Severity: medium. Likelihood: medium. Mitigation: enforce minimum task-size
  thresholds before dispatching to interpreter pools.

- Risk: operational debugging complexity may increase.
  Severity: medium. Likelihood: medium. Mitigation: add clear tracing and
  structured task metadata around executor dispatch and completion.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan created.
- [ ] Stage A: Define eligible workloads and baseline metrics.
- [ ] Stage B: Add tests and prototype executor adapter.
- [ ] Stage C: Integrate behind a port and feature flag.
- [ ] Stage D: Validate functional correctness and compare performance.

## Surprises & discoveries

- Observation: current codebase does not yet include production LangGraph or
  Celery task modules; concurrency strategy is documented but mostly planned.
  Evidence: repository has design docs but no concrete orchestration runtime
  package implementing those components. Impact: this activity should begin as
  an adapter prototype with clear integration seams.

- Observation: project memory MCP resources are unavailable in this session.
  Evidence: resource listings are empty. Impact: risk assumptions rely on
  repository documents and Python stdlib docs.

## Decision log

- Decision: implement interpreter execution as an optional adapter first.
  Rationale: protects ongoing delivery while validating compatibility and
  performance in a controlled scope. Date/Author: 2026-02-24 / Codex.

- Decision: require benchmark evidence before defaulting any workload to
  interpreter pools. Rationale: concurrency changes without measurement can
  regress throughput. Date/Author: 2026-02-24 / Codex.

## Outcomes & retrospective

Pending implementation.

Completion should produce a safe adoption path with measured trade-offs,
including explicit guidance for when to use interpreter pools versus existing
Celery worker profiles.

## Context and orientation

Episodic design documentation already distinguishes I/O-bound and CPU-bound
execution in planned Celery routing. This plan adds a Python-runtime-level
option for CPU tasks where subinterpreter isolation and shared-process resource
use are beneficial.

Relevant context files:

- `docs/episodic-podcast-generation-system-design.md`
- `docs/agentic-systems-with-langgraph-and-celery.md`
- Future orchestration adapter modules under `episodic/` to be introduced.

No current canonical ingestion path is an immediate candidate for high-cost CPU
parallelism, so first implementation should target a contained prototype
workload and adapter abstraction.

## Plan of work

Stage A defines boundaries and benchmark criteria. Select one representative,
pure-Python CPU task and establish baseline throughput with current execution
mode. Document workload size and expected outputs.

Stage B writes tests first and creates a prototype adapter that dispatches work
through `InterpreterPoolExecutor`. Tests should cover correctness,
exception-propagation behaviour, and deterministic ordering where required.

Stage C introduces integration behind a port and feature toggle so caller code
can choose between baseline execution and interpreter execution without
changing business logic. Keep integration additive.

Stage D validates both correctness and performance. Compare baseline versus
interpreter execution with repeatable measurements. If criteria are met,
document rollout guidance and keep default mode conservative unless explicitly
enabled.

## Concrete steps

Run from repository root.

1. Confirm planned execution touchpoints.

    rg -n "Celery|StateGraph|cpu|concurrency|TaskResumePort" docs episodic

2. Create tests first for adapter correctness.

    set -o pipefail; uv run pytest -v tests/test_interpreter_executor.py 2>&1 \
      | tee /tmp/py314-interpreters-targeted.log |

3. Implement adapter and feature flag wiring.

4. Run benchmark comparison for prototype workload.

    set -o pipefail; uv run python -m episodic.benchmarks.interpreters 2>&1 \
      | tee /tmp/py314-interpreters-bench.log |

5. Run full Python gates.

    set -o pipefail; make check-fmt 2>&1 | tee /tmp/py314-interpreters-check-fmt.log
    set -o pipefail; make lint 2>&1 | tee /tmp/py314-interpreters-lint.log
    set -o pipefail; make typecheck 2>&1 | tee /tmp/py314-interpreters-typecheck.log
    set -o pipefail; make test 2>&1 | tee /tmp/py314-interpreters-test.log

Expected success indicators:

- Prototype adapter tests pass.
- Benchmark output demonstrates acceptable overhead and expected scaling trend.
- Full gates pass.

## Validation and acceptance

Acceptance criteria:

- Interpreter-based execution path exists behind an explicit adapter interface.
- Correctness tests pass for success and failure cases.
- Benchmark evidence shows no unacceptable regression against tolerance.
- Full Python quality gates pass.

## Idempotence and recovery

- Prototype adapter can be disabled via feature toggle if issues are observed.
- If compatibility issues arise, keep port interface and revert adapter wiring
  to baseline execution only.
- Benchmark and test commands are safe to re-run and overwrite logs.

## Artifacts and notes

Capture during implementation:

- `git diff -- episodic tests docs`
- `/tmp/py314-interpreters-targeted.log`
- `/tmp/py314-interpreters-bench.log`
- `/tmp/py314-interpreters-check-fmt.log`
- `/tmp/py314-interpreters-lint.log`
- `/tmp/py314-interpreters-typecheck.log`
- `/tmp/py314-interpreters-test.log`

## Interfaces and dependencies

- Python 3.14 stdlib: `concurrent.interpreters` and
  `concurrent.futures.InterpreterPoolExecutor`.
- Adapter interface should remain isolated from domain services.
- No new third-party dependencies are required for the initial milestone.

## Revision note

Initial draft created to stage safe adoption of Python 3.14 concurrent
interpreters for CPU-bound execution.
