# ADR-0029: QA-gated mode branching and the content-generation graph

## Status

Accepted, 2026-11-22. Roadmap item `4.4.1` routes every generation run through
a compiled content-generation graph whose quality branch either persists a
no-QA draft directly or evaluates a QA-gated candidate before persistence or
escalation.

## Date

2026-11-22.

## Context and problem statement

ADR-0017 introduced `InProcessGenerationRunLauncher` as the scheduling port and
implemented a single-pass no-QA path. Its `launch(run_id)` sequence claims the
run, generates one draft, persists TEI with `qa_status=skipped`, and records a
terminal status. Roadmap item `4.4.1` must add the first slice of the *Content
Generation Graph* described in
`docs/episodic-podcast-generation-system-design.md`: a quality branch that
routes a run either to direct draft persistence (no-QA) or through QA
evaluation (QA-gated), with distinct terminal states and unambiguous branch
ownership.

Three forces shape the design:

- The `draft_without_qa` contract must not change. Its REST shape, event
  stream, metrics, span outcomes, persisted provenance, and cancellation
  behaviour are pinned by a characterization suite.
- The launcher must remain the single writer of a run's events and status, with
  ordered publication. Which task executes a node is an implementation detail;
  the runner owns and names its graph task and every node task so that rule
  stays observable.
- Hecate (ADR-0014, ADR-0022) keeps LangGraph mechanics out of node functions
  and keeps the application layer independent of orchestration. The composition
  root injects the graph.

Roadmap items `4.4.2` to `4.4.4` will add Chrono evaluators, refinement, and a
checkpointed escalation. This decision deliberately leaves room for those
without reopening the run or launcher ports.

## Decision drivers

- Preserve the no-QA observable contract exactly.
- Keep one writer per run and ordered event publication.
- Keep cancellation shutdown-safe at every node.
- Keep domain policy and port protocols in `domain_ports`, node functions in
  `orchestration_nodes`, and the graph builder and runner in `orchestration`.
- Fail closed on any evaluation uncertainty.
- Accept `qa_gated` only where a deployment can evaluate it.

## Decision outcome

Every generation run executes through one compiled LangGraph `StateGraph`,
injected into the launcher through `ContentGenerationGraphPort`. The topology
is:

```plaintext
START → initialize → [quality branch]
  draft_without_qa: generate_draft_without_qa → persist_draft_without_qa → END
  qa_gated:         generate_qa_candidate → evaluate → [evaluation route]
                      pass:     persist_qa_passed_draft → END
                      escalate: escalate → END
```

The recorded decisions are:

- **D1: inject a compiled graph through a domain port.** The graph is compiled
  once. `LangGraphContentGenerationGraph` lives in `orchestration` and
  implements `ContentGenerationGraphPort` from `domain_ports`. The composition
  root injects it as a required launcher field. Per-run collaborators reach
  nodes through LangGraph's runtime context, and the builder wraps each plain
  node function in a closure
  `lambda state, runtime: node(state, runtime.context)`, so node functions
  import no LangGraph.
- **D2: graph state holds domain values only.** `ContentGenerationGraphState`
  carries `request`, `verdict`, `evaluations`, and `terminal`. Application
  objects stay in a per-run run session that implements
  `ContentGenerationSteps`. Nodes reach run state only through the step port.
- **D3: fork before generation, and give each branch its own nodes.** Both
  generate nodes delegate to one step method, and both persist nodes delegate
  to one step method, but each branch owns its nodes and terminal. The only
  shared node is `initialize`.
- **D4: make `escalate` a failing terminal in this item.** The run fails with
  `error_category="qa.escalation_required"` and `qa_status=failed`, writes no
  TEI, records the provider cost, and appends `qa.escalated`. Approval
  preparation, refinement, parallel evaluator fan-out, and a checkpointed
  escalation belong to roadmap items `4.2.1` and `4.4.2` to `4.4.4`.
- **D5: define the QA-status lifecycle.** `QaStatus` gains `pending`, `passed`
  and `failed`. For `qa_gated`, `skip_qa_rationale` must be absent, `qa_status`
  must be one of those three, and `passed` holds if and only if the run
  succeeded. `GenerationRunStatusUpdate` gains `qa_status` with an `UNCHANGED`
  sentinel, so an omitted value keeps the persisted status rather than clearing
  it. Both store adapters resolve updates through one domain helper,
  `apply_status_update`, which re-validates via `dc.replace`.
- **D6: the TEI envelope reports the producing run's `quality_mode`.**
  `EpisodeTeiUpdate` refuses any QA status other than `skipped` or `passed`, so
  TEI can never be persisted for a run that has not passed.
- **D7: accept `qa_gated` only where the deployment can evaluate it.**
  `ContentGenerationGraphPort.accepted_quality_modes()` is the single source of
  truth, copied into `ApiDependencies.accepted_quality_modes`. The capability
  check runs inside the idempotent work, after body parsing and before the
  gated-rationale rule; both errors release the idempotency key.
- **D8: aggregate verdicts with "all must pass", and isolate evaluator
  errors.** An empty set is `inconclusive`; any failure is `failed`; otherwise
  any inconclusive result is `inconclusive`; otherwise the draft passed. Each
  evaluator runs under `asyncio.timeout`. An exception, timeout, or self-raised
  `CancelledError` becomes that evaluator's inconclusive evaluation with an
  error classification. A genuine cancellation is always re-raised.
- **D9: define the QA-gated event stream.** `run.started`, `draft.generated`,
  `qa.evaluation_started`, then one terminal unit of work containing
  `qa.result` and either `tei.persisted` plus `run.succeeded`, or
  `qa.escalated` plus `run.failed`. No-QA runs emit no new events.
- **D10: escalation reuses the failure write path.** `Failure` gains
  `qa_status`, `is_draft_error`, and `escalation`. The escalated draft did
  spend inference, so its cost is recorded; QA verdicts do not count as draft
  errors for alerting.
- **D11: validate the generator's draft as TEI before evaluation.** QA must not
  pass invalid TEI. For no-QA runs the failure classification and event order
  are unchanged.
- **D12: the runner translates graph-level failures.** It translates
  LangGraph's node-cancellation wrapper back into `asyncio.CancelledError`, so
  a generator that raises `CancelledError` itself keeps today's
  `launcher.shutdown` classification. It raises `ContentGenerationGraphError`
  (category `orchestration.incomplete`) when the final state has no terminal or
  the terminal's branch is not the run's branch.

Deviations from the system-design diagram, all deliberate:

- The fork comes before generation, with one generate node per branch.
- Persist Draft is split into one node per branch.
- Aggregate as a separate node, Refine, Prepare for Approval, and a
  checkpointed Escalate are deferred.

## Implementation notes

The implemented slice matches the topology above. Three findings refined the
detail without changing the decision:

- LangChain wraps every node call in a task of its own, so nodes never run in
  the launcher's task. The runner owns the graph task, names it
  `generation-run-{run_id}`, renames each node task to the same convention, and
  cancels and drains in-flight node tasks on shutdown. This keeps event appends
  attributable to their run and stops a cancelled run from writing after
  teardown.
- `quality_branch` and `terminal` span attributes are recorded for no-QA runs
  as well as gated ones, because the quality branch is the decision worth
  observing. This is the only change the no-QA characterization baseline
  records.
- The gated-rationale rejection is a `400 validation_error` with
  `details.constraint="exclusive_with_quality_mode"` and
  `details.quality_mode="qa_gated"`.

## Verification

- A Hypothesis property drives the production runner over generated quality
  modes, evaluator outcomes, and injected faults, and proves branch ownership
  and determinism. A graph with the two branches exchanged proves the ownership
  checker rejects a foreign terminal.
- Static topology assertions and a Mermaid snapshot pin the compiled graph.
- A migration test compares PostgreSQL enum labels with the Python enums in
  staged transactions, because Alembic metadata comparison ignores labels.
- REST tests cover the capability gate, the gated-rationale rejection, the
  unchanged 422, replay after capability withdrawal, and key release after a
  rejected retry.
- Launcher tests cover every QA-gated cell, including cancellation while an
  evaluator awaits and inside either terminal transaction.

## Consequences

### Positive

- A QA-gated run that succeeds is equivalent to "QA passed".
- Branch ownership is visible in topology and enforced at runtime, so a
  routing mistake fails loudly instead of silently taking the wrong route.
- The no-QA path keeps its direct route and its entire observable contract.
- Deployments without evaluators refuse `qa_gated` before spending inference.
- Evaluator outages are distinguishable from genuine QA failures through
  events, metrics, and logs.

### Negative

- A hung evaluator holds a launcher concurrency permit until its timeout
  elapses. The default timeout is two minutes.
- The escalate terminal fails runs in `4.4.1`; roadmap item `4.4.4` will pause
  them instead. The `qa.escalated` event is the stable signal across that
  change, and `qa.escalation_required` is specific to `4.4.1`.
- The candidate draft lives only in the session's memory. `4.4.4` needs a
  durable draft artefact for review and resume.
- No lease renewal happens at `evaluate`; roadmap item `2.6.2` must not reclaim
  a run on a stale lease while `current_node="evaluate"`.

### Neutral

- `accepted_quality_modes` always contains `draft_without_qa`, so a deployment
  policy that forbids it is not supported until the approval workflow exists.
- Alembic `compare_metadata` ignores enum labels, so a parity test compares the
  PostgreSQL labels with the Python enum values directly.

## References

- ADR-0009, the source-to-script slice.
- ADR-0014, hexagonal architecture enforcement.
- ADR-0017, no-QA generation execution and TEI persistence. Its rule that run
  creation accepts only `draft_without_qa` is superseded in part by D7.
- ADR-0022, orchestration architecture enforcement.
- ExecPlan `docs/execplans/4-4-1-qa-gated-mode-branching.md`.
- `docs/episodic-podcast-generation-system-design.md`, "Content Generation
  Graph".
- `docs/episodic-tui-api-design.md`, "Generation runs" and the event catalogue.
