# Define the generation-run port and domain model

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & discoveries`, `Decision log`,
and `Outcomes & retrospective` must be kept up to date as work proceeds.

Status: COMPLETE

## Purpose / big picture

Roadmap item `2.6.1` introduces the domain language for *user-facing*
generation runs: the first-class resource a Terminal User Interface (TUI) or
Representational State Transfer (REST) client creates when it asks Episodic to
turn an ingested source bundle into a Text Encoding Initiative Publication 5
(TEI P5) script, plus the append-only event log and human-in-the-loop
checkpoints that surround it.

After this change, a Python caller can construct a `GenerationRun`, append
ordered `GenerationEvent` records, raise a `Checkpoint` for human review, and
record the reviewer's response — all through a stable, in-memory, port-shaped
contract. Nothing in this plan reaches the database, the Hypertext Transfer
Protocol (HTTP) surface, or the LangGraph orchestrator. Those land in roadmap
items `2.6.2` (repository contracts and Alembic migrations) and `2.6.3` (REST
endpoints). This plan deliberately leaves clean seams for both.

Success is observable in these behaviours:

1. A unit test constructs `GenerationRun`, `GenerationEvent`, and `Checkpoint`
   frozen dataclasses with UUIDv7 identifiers and rejects invalid field values
   eagerly (blank ids, non-mapping payloads, illegal lifecycle strings).
2. A unit test invokes the in-memory adapter's
   `append_event(run_id, kind, payload)` repeatedly and observes per-run `seq`
   advancing as 1, 2, 3, … without gaps and without callers ever supplying a
   `seq` value.
3. A property test using `hypothesis` exercises interleaved concurrent
   `append_event` calls under `asyncio` and asserts that the resulting event
   list is strictly monotonic, gap-free, contains every appended event exactly
   once, and is ordered by both `seq` and `created_at`.
4. A behavioural test using `pytest-bdd` walks a checkpoint from `created` to
   `responded` via the domain factory `Checkpoint.respond(...)`, and a separate
   scenario asserts that a second response on the same checkpoint raises
   `CheckpointAlreadyTerminal`.
5. The architecture gate (`make lint`, which runs Hecate) passes with the new
   modules placed in the `domain_ports` group; no inbound or outbound adapter
   imports leak across the boundary.
6. `make check-fmt`, `make typecheck`, `make lint`, and `make test` all pass on
   a clean checkout after the change.
7. `docs/users-guide.md`, `docs/developers-guide.md`, and the
   `episodic-tui-api-design.md` class diagram are updated to reflect the
   actually-implemented port shape (which is intentionally split — see
   *Decision log*).

This plan does *not* implement Structured Query Language (SQL) persistence,
REST endpoints, WebSocket publishing, the `RunEventBusPort`, or the bridge
between LangGraph's orchestration-layer `WorkflowCheckpoint` and the user-facing
`Checkpoint`. Those concepts are kept disjoint here. See *Decision log* entry
on naming.

## Constraints

- Preserve hexagonal architecture boundaries as enforced by Hecate
  (`[tool.hecate]` in `pyproject.toml`, ADR-014). New entity and port modules
  must live in the `domain_ports` group; the in-memory reference adapter must
  live in the `outbound_adapter` group. No new module may import from
  inbound-adapter modules (Falcon resources, worker tasks/topology) or from
  storage adapters that pull SQLAlchemy. Domain code must not import LangGraph,
  OpenAI clients, or Celery.
- Do not touch `episodic.orchestration._checkpoint_dto.WorkflowCheckpoint` or
  the `CheckpointPort` defined in `episodic.orchestration._protocols`. The
  user-facing `Checkpoint` introduced here is a *different* concept (human
  approval of a generation run) and must not collide in naming with the
  orchestration-layer LangGraph suspend/resume record (ADR-007).
- Frozen dataclasses only for the new entities
  (`@dataclasses.dataclass( frozen=True, slots=True)`), matching the existing
  canonical-domain pattern in `episodic.canonical.domain`.
- Use only the Python 3.14 standard library for identifier generation
  (`uuid.uuid7()`); no third-party UUID library may be added.
- Public method and class names introduced in this plan are stable contracts
  for `2.6.2` and `2.6.3`. Renaming after this plan lands counts as a breaking
  change and requires escalation.
- All quality gates required by `AGENTS.md` must pass before each commit:
  `make check-fmt`, `make lint`, `make typecheck`, `make test`. For
  documentation-only commits: `make markdownlint` and `make nixie` for any
  Mermaid diagrams.
- All prose follows the documentation style guide
  (`docs/documentation-style-guide.md`), including en-GB Oxford spelling and
  the 80-column paragraph rule.

## Tolerances (exception triggers)

These define the boundaries of autonomous action, not quality criteria. If any
threshold is reached, stop and escalate via a *Decision log* entry.

- Scope: if implementation needs to edit more than 18 files or introduce more
  than 1,400 net lines of code (including tests), stop and escalate.
- Interface: if any existing public protocol in
  `episodic.canonical.ports`, `episodic.canonical.entity_protocols`,
  `episodic.canonical.unit_of_work_protocols`, or
  `episodic.orchestration._protocols` must change its signature, stop and
  escalate. Adding new protocols is in scope; changing existing ones is not.
- Hecate config: if the `[tool.hecate]` group rules need to be loosened (any
  `allowed` list extended to permit a previously forbidden direction), stop and
  escalate.
- Dependencies: if a new third-party Python dependency appears necessary,
  stop and escalate.
- Iterations: if any quality gate (`make ...`) still fails after three
  successive fix attempts, stop and escalate with the relevant
  `/tmp/<action>-<project>-<branch>.out` log path.
- Time: if any stage of *Plan of work* takes longer than four wall-clock hours
  of active work, stop and escalate.
- Ambiguity: if the design doc's class diagram and this plan's split-port
  shape diverge in a way that materially affects `2.6.2` or `2.6.3` (for
  example, the design author intends a single composite port), stop and present
  options.

## Risks

- Risk: confusion between the user-facing `Checkpoint` (this plan) and the
  orchestration-layer `WorkflowCheckpoint` (ADR-007). They share a word and
  could be conflated. Severity: medium. Likelihood: medium. Mitigation: name
  the new module `episodic.canonical.generation_run_ports` (not `checkpoints`);
  name the new entity `Checkpoint` only at the user-facing layer and require
  the orchestration record to remain `WorkflowCheckpoint`. Add a short *Naming*
  note to `docs/developers-guide.md` cross-linking the two.

- Risk: caller-supplied `seq` values race under concurrent appenders.
  Severity: high. Likelihood: high once `2.6.3` wires the orchestrator.
  Mitigation: the port contract allocates `seq` *inside* the adapter from
  `append_event(run_id, kind, payload) -> GenerationEvent`. The in-memory
  reference adapter serialises run-status updates and event appends with a
  single `asyncio.Lock`; the SQL adapter in `2.6.2` will use
  `UNIQUE(generation_run_id, seq)` plus `INSERT ... RETURNING`. See *Decision
  log*.

- Risk: a two-state checkpoint lifecycle (`created → responded`) leaks
  resources when reviewers disappear; prior art (LangGraph, Temporal Updates,
  Step Functions human approval) uniformly adds `timed_out` and `cancelled`
  terminal states. Severity: medium. Likelihood: high in production.
  Mitigation: define the lifecycle as
  `created → {responded, timed_out, cancelled}` from day one, with `respond`,
  `time_out`, and `cancel` factory methods on `Checkpoint`. Roadmap item
  `2.6.1` strictly names only `created, responded`; the additional terminal
  states are an *additive* superset and are documented in the *Decision log*.

- Risk: frozen dataclasses with `dict`/`list` fields silently break
  hashability and equality. The CPython documentation calls this out for
  `dataclass(frozen=True, eq=True)`. Severity: medium. Likelihood: medium.
  Mitigation: use `tuple[str, ...]` for `Checkpoint.options`; use the project's
  existing `JsonMapping` alias plus `dict()` defensive copy in `__post_init__`
  (matching the `WorkflowCheckpoint` precedent); set
  `eq=True, frozen=True, slots=True` and document that payload mappings are
  treated as opaque blobs for equality.

- Risk: idempotency of `create_run` ends up duplicated in the REST layer and
  the orchestrator retry path because the port does not expose it. Severity:
  medium. Likelihood: medium. Mitigation: the
  `GenerationRunRepository.create_run` contract takes an optional
  `idempotency_key: str | None` and returns the existing `GenerationRun` if the
  key was seen (first-write-wins), following the `CheckpointPort.save_or_reuse`
  precedent in `2.4.2`.

- Risk: UUIDv7's embedded millisecond timestamp leaks creation timing if the
  identifier reaches an untrusted client. Severity: low. Likelihood: medium.
  Mitigation: the run, event, and checkpoint identifiers are already exposed to
  the TUI client per the design document, so the timing leak is accepted at the
  trust boundary; note in `docs/developers-guide.md` that audit pipelines must
  not assume the UUIDv7 timestamp matches `created_at` after cross-process
  generation.

## Progress

- [x] Draft ExecPlan created.
- [x] Stage A: research, alignment, and red-phase test scaffolding.
- [x] Stage B: implement entities, enums, and `EventSeq` newtype with
  validation.
- [x] Stage C: implement three port protocols
  (`GenerationRunRepository`, `GenerationEventLog`, `GenerationCheckpointPort`)
  plus the `GenerationRunPort` Protocol facade for design-document continuity.
- [x] Stage D: implement the in-memory adapter and wire concurrency tests.
- [x] Stage E: implement `hypothesis` property tests and `pytest-bdd`
  behavioural tests for checkpoint lifecycle.
- [x] Stage F: update `[tool.hecate]` groups, the design document class
  diagram, the users' guide, the developers' guide, and add a short Decision
  Record (ADR) for the port split.
- [x] Stage G: run all quality gates, capture transcripts, run
  `coderabbit review --agent`, and clear concerns.
- [x] Mark roadmap item `2.6.1` done.

- 2026-06-04 00:00 Europe/Berlin: User explicitly requested implementation
  of this ExecPlan, so the approval gate is satisfied and status changed from
  `DRAFT` to `IN PROGRESS`.
- 2026-06-04 00:15 Europe/Berlin: Stage A test scaffolding added in
  `tests/test_generation_run_domain.py`,
  `tests/test_generation_run_port_contract.py`,
  `tests/test_generation_run_properties.py`, and
  `tests/steps/test_generation_run_lifecycle_steps.py`. Focused red run a
  focused `uv run pytest -q ...` command with project cache environment failed
  with the expected missing `Checkpoint` and
  `episodic.canonical.adapters.generation_runs` imports; transcript:
  `/tmp/red-generation-run-2-6-1-generation-run-port-and-domain-model.out`.
- 2026-06-04 01:20 Europe/Berlin: Stages B through F implemented. Focused
  generation-run suite passed (`21 passed`) with transcript
  `/tmp/test-generation-run-2-6-1-generation-run-port-and-domain-model.out`.
  Repository gates passed with transcripts:
  `/tmp/check-fmt-2-6-1-generation-run-port-and-domain-model.out`,
  `/tmp/lint-2-6-1-generation-run-port-and-domain-model.out`,
  `/tmp/typecheck-2-6-1-generation-run-port-and-domain-model.out`,
  `/tmp/markdownlint-2-6-1-generation-run-port-and-domain-model.out`,
  `/tmp/nixie-2-6-1-generation-run-port-and-domain-model.out`, and
  `/tmp/test-2-6-1-generation-run-port-and-domain-model.out`
  (`827 passed, 1 skipped`).
- 2026-06-04 03:40 Europe/Berlin: First CodeRabbit review completed with six
  actionable findings. Fixes grouped flat protocol tests into classes, expanded
  helper docstrings, narrowed a broad Pylint suppression in the test stub,
  clarified ADR wording, and removed a time-of-check/time-of-use race between
  event appends and terminal run updates. The deterministic gates passed before
  review: `make check-fmt`, `make lint`, `make typecheck`, `make markdownlint`,
  `make nixie`, and `make test`.
- 2026-06-04 05:50 Europe/Berlin: Second CodeRabbit review completed with
  seven small findings. Fixes added error-message assertions, removed feature
  file trailing whitespace, documented the then-current lock ordering, added a
  justified Pylint suppression comment, and added
  `from __future__ import annotations` to the BDD step file. A direct
  CodeRabbit suggestion placed the future import before the module docstring;
  `make lint` rejected that with `D100` and `E402`, so the import now uses the
  standard Python position immediately after the module docstring.
- 2026-06-04 07:35 Europe/Berlin: Later CodeRabbit review requested narrower
  Pylint suppressions, a simpler in-memory lock model, a contract-test fixture,
  and descriptive assertion messages. The adapter now serialises run-status
  updates and event appends under the same global in-memory lock, which is
  conservative and sufficient for this reference adapter. Current deterministic
  validation after those changes: `make check-fmt`, `make lint`,
  `make typecheck`, and `make test` passed; `make test` transcript:
  `/tmp/test-2-6-1-generation-run-port-and-domain-model.out`
  (`827 passed, 1 skipped`).
- 2026-06-04 10:45 Europe/Berlin: Final CodeRabbit-preparation pass addressed
  the remaining review findings: module docstrings now describe port and
  adapter usage, Pylint suppressions are narrowly scoped with rationale,
  generation-run error messages are assigned before `super().__init__`, the
  adapter time-provider default uses a dataclass factory, property tests assert
  multiset preservation with explicit messages, and the contract tests create
  UUIDv7 values directly. Deterministic gates passed afterwards:
  `/tmp/check-fmt-2-6-1-generation-run-port-and-domain-model.out`,
  `/tmp/lint-2-6-1-generation-run-port-and-domain-model.out`,
  `/tmp/typecheck-2-6-1-generation-run-port-and-domain-model.out`, and
  `/tmp/test-2-6-1-generation-run-port-and-domain-model.out`
  (`827 passed, 1 skipped`).
- 2026-06-04 11:55 Europe/Berlin: CodeRabbit's next review was limited to
  `tests/test_generation_run_domain.py`. Fixes removed the redundant UUID
  wrapper, converted the test factories to fixtures, split event validation
  into focused tests, added assertion messages, and added Hypothesis coverage
  for blank actors and non-mapping budget snapshots. Focused domain tests passed
  (`11 passed`), followed by `make check-fmt`, `make lint`, `make typecheck`,
  `make markdownlint`, `make nixie`, and `make test` (`831 passed, 1 skipped`).
- 2026-06-04 13:05 Europe/Berlin: CodeRabbit then reported four adapter and
  error-module findings. Fixes changed status filtering from enum identity to
  equality, expanded the in-memory `create_run` idempotency docstring, added
  postponed annotations to the error module, and expanded property coverage for
  first-write-wins idempotency, terminal-run immutability, run pagination, and
  event pagination. Focused generation-run property tests passed (`6 passed`),
  followed by `make check-fmt`, `make lint`, `make typecheck`, and `make test`
  (`835 passed, 1 skipped`).
- 2026-06-04 14:10 Europe/Berlin: CodeRabbit's next review reported two
  property-test style findings. Fixes renamed module-level Hypothesis
  strategies to uppercase constants and extracted `EventInput`/`EventInputs`
  aliases for the event multiset helper. Focused generation-run property tests
  passed (`6 passed`), followed by `make check-fmt`, `make lint`,
  `make typecheck`, and `make test` (`835 passed, 1 skipped`).
- 2026-06-04 14:35 Europe/Berlin: CodeRabbit's follow-up review reported one
  composite-protocol contract-test cleanup. The explicit `del port` statement
  was removed by naming the type-checking assignment `_port`; the focused
  composite-protocol test passed, followed by `make check-fmt`, `make lint`,
  `make typecheck`, and `make test` (`835 passed, 1 skipped`).
- 2026-06-04 15:05 Europe/Berlin: CodeRabbit requested a combined
  Hypothesis-generated adapter operation sequence. Added coverage that exercises
  `create_run`, `append_event`, `update_run_status`, and `list_events`
  together, including idempotency stability, terminal immutability, gap-free
  event sequences, and cursor paging. Focused property tests passed
  (`7 passed`), followed by `make check-fmt`, `make lint`, `make typecheck`, and
  `make test` (`836 passed, 1 skipped`).
- 2026-06-04 16:10 Europe/Berlin: CodeRabbit's next review reported ten
  mostly test-maintainability findings plus missing negative pagination
  contract cases. Fixes expanded generation-run domain and port-contract test
  module docstrings, aligned checkpoint options with lifecycle fixtures, added
  `list_runs` and `list_events` negative pagination contract tests, converted
  the property-test clock to a fixture, updated the Hypothesis character
  strategy API, switched generated adapter operation handling to structural
  pattern matching, clarified the `AdapterExerciseState` docstring, removed the
  error-module future import, and moved BDD action payloads into a typed map.
  Focused generation-run tests passed (`33 passed`), followed by
  `make check-fmt`, `make lint`, `make typecheck`, and a clean `make test` rerun
  (`839 passed, 1 skipped`).
- 2026-06-04 16:45 Europe/Berlin: CodeRabbit's follow-up review reported
  five cleanup findings. Fixes added explicit `RunAlreadyTerminal` message
  assertions in direct and generated adapter-operation tests, tightened the
  `NoopGenerationRunPort` stub signatures to exactly match the public
  protocols, clarified why the generation-run error module keeps a runtime
  `uuid` import, and trimmed property-test prose after the extra assertions
  pushed the module over Pylint's file-length threshold. Focused generation-run
  tests passed (`33 passed`), followed by `make check-fmt`, `make lint`,
  `make typecheck`, and `make test` (`839 passed, 1 skipped`).
- 2026-06-04 17:20 Europe/Berlin: CodeRabbit's next review reported two
  property-test cleanup findings. Fixes converted the test-only type aliases to
  Python 3.14 `type` declarations and replaced the `NamedTuple` adapter
  exercise state with a frozen slots dataclass while leaving the tracked
  `appended` list intentionally mutable. Focused generation-run tests passed
  (`33 passed`), followed by `make check-fmt`, `make lint`, `make typecheck`,
  `make test` (`839 passed, 1 skipped`), `make markdownlint`, and `make nixie`.
- 2026-06-04 18:05 Europe/Berlin: Final CodeRabbit review completed cleanly
  with zero findings after the PEP 695 alias and dataclass-state fixes.
- 2026-06-14 15:20 Europe/Berlin: Rebasing onto `origin/main` stopped on a
  `docs/developers-guide.md` ADR-list conflict. Resolution kept both branch
  ADR-015 (`generation-run-port-split`) and main ADR-015
  (`upload-and-idempotency-ports`) links because both files exist and document
  distinct decisions. The first post-rebase `make test` then exposed a Hecate
  configuration merge issue: the five architecture groups had collapsed into
  duplicate `outbound_adapter` names. The fix restored main's
  `composition_root`, `domain_ports`, `application`, `inbound_adapter`, and
  `outbound_adapter` groups while preserving this branch's
  `generation_run_errors` and `generation_run_ports` prefixes.
- 2026-06-14 16:45 Europe/Berlin: Follow-up review reported four warnings:
  BDD steps were still calling checkpoint domain transitions directly, domain
  validation and repr output lacked snapshots, adapter decision points lacked
  structured logs, and `list_runs` scanned every stored run before pagination.
  The corrective pass adds adapter-level checkpoint timeout and cancellation
  operations, routes BDD lifecycle steps through `InMemoryGenerationRunStore`,
  adds Syrupy snapshots for checkpoint validation messages, dataclass repr
  output, and generation-run error messages, emits structured adapter logs, and
  indexes runs by episode before listing.
- 2026-06-14 17:25 Europe/Berlin: Validation after the warning fixes passed:
  focused generation-run tests (`31 passed`), `make check-fmt`, `make lint`
  (including Hecate, Ruff, and Pylint), `make typecheck`, `make test`
  (`938 passed`), `make markdownlint`, and `make nixie`. Checkpoint-port
  contract tests were split into
  `tests/test_generation_checkpoint_port_contract.py` to keep the original
  port-contract module below the Pylint file-length ceiling.
- 2026-06-14 17:45 Europe/Berlin: CodeRabbit review was requested after the
  deterministic gates passed and completed with zero findings.
- 2026-06-14 22:06 Europe/Berlin: Wyvern verification found three follow-up
  warnings stale and one observability point partially live: terminal
  checkpoint transitions rejected by the domain were not logged. The adapter
  now logs `*_already_terminal` warning events in
  `_apply_checkpoint_transition` before re-raising `CheckpointAlreadyTerminal`,
  preserving domain purity and behaviour.

## Surprises & discoveries

- 2026-06-04: `git branch --show-current` returned
  `2-6-1-generation-run-port-and-domain-model`, matching the required plan
  filename and avoiding main-branch work.
- 2026-06-04: `find . -name AGENTS.md -print` found only the repository-root
  `AGENTS.md` in this worktree, excluding cached dependency checkouts under
  `.uv-cache`.
- 2026-06-04: A full `make test` red run was too coarse for Stage A because
  it reached an unrelated existing
  `tests/test_api_authorization.py::test_authorization_decision_serializes_to_canonical_envelope[service_unavailable]`
  error before the new files. The run was terminated after confirming it was
  not useful as a red-phase signal; focused generation-run tests are used for
  iteration until the milestone is ready for full gates.
- 2026-06-04: The first full `make test` after implementation exposed two
  findings. The generation-run property test sorted tuples containing `dict`
  payloads and failed when event kinds tied; it now compares a `Counter` over
  stable `(kind, repr(payload))` pairs. The same run also hit a timeout in an
  existing workflow-checkpoint rollback test setup; a clean rerun passed the
  full suite.
- 2026-06-04: Repeated full-gate and focused reruns exposed intermittent
  py-pglite fixture setup timeouts in existing API error-envelope tests. The
  failing parameter passed in isolation in four seconds, and a subsequent full
  `make test` passed without code changes. Treat these as environmental
  py-pglite setup flakiness unless they become reproducible outside this change.
- 2026-06-04: One full `make test` pass after the final CodeRabbit fixes hit
  five unrelated `pglite_sqlalchemy_manager` fixture setup timeouts in existing
  API/storage tests. The immediate rerun passed with `839 passed, 1 skipped`,
  so the timeout was recorded as environmental rather than a generation-run
  regression.
- 2026-06-04: CodeRabbit was rate-limited twice during the milestone review
  loop. Each retry used the requested random 15-30 minute `vsleep` backoff.
- 2026-06-04: CodeRabbit's final nits were mostly maintainability checks that
  deterministic gates do not catch: assertion diagnostics, long-method
  suppression scope, and examples in module docstrings. Keeping these changes
  small avoided changing the already-validated behaviour.
- 2026-06-04: Adding CodeRabbit's requested `pytest.raises(..., match=...)`
  assertions to the property test tipped the file over Pylint's 400-line module
  limit. The fix was to reduce duplicated explanatory prose rather than
  suppress the size warning or split the test helper prematurely.
- 2026-06-04: CodeRabbit now enforces Python 3.14 idioms in tests as well as
  production code. The generated-operation property test uses PEP 695 aliases
  and a frozen dataclass state container, preserving the mutable event list
  only where the test sequence needs accumulation.
- 2026-06-04: The final CodeRabbit pass returned no findings after all local
  code, test, documentation, and diagram gates were green.
- 2026-06-14: The rebase conflict in `docs/developers-guide.md` showed that
  two independent ADRs were both numbered `015`. The rebase deliberately kept
  both links rather than renumbering during conflict resolution, because
  changing ADR identities during a rebase would broaden the merge beyond the
  user's request.
- 2026-06-14: `make check-fmt` after the rebase reformatted
  `episodic/canonical/domain.py`. The change is formatting-only and reflects
  current `origin/main` Ruff style interacting with this branch's dataclass
  additions.
- 2026-06-14: Structured logging uses
  `episodic.orchestration._types._log_event`, matching existing storage
  adapters. Domain entities still do not import that helper because the
  `domain_ports` Hecate group may import only other domain-port modules; domain
  transition logging would need a domain-owned logging helper or port in a
  later slice.
- 2026-06-14: The in-memory adapter did not expose timeout or cancellation
  methods even though the domain model had terminal transitions for them. Adding
  `time_out_checkpoint` and `cancel_checkpoint` to the checkpoint port keeps
  BDD lifecycle coverage at the port/adapter boundary without changing the
  existing response contract.

## Decision log

- Decision: place the new user-facing entities (`GenerationRun`,
  `GenerationEvent`, `Checkpoint`, `GenerationRunStatus`, `CheckpointStatus`) in
  `episodic.canonical.domain` rather than a new sub-package. Rationale:
  matches the existing canonical-domain pattern (`CanonicalEpisode`,
  `IngestionJob`, `WorkflowCheckpointStatus` all live there) and keeps Hecate
  group surface narrow. Date/Author: 2026-05-29 / plan author.

- Decision: split the design-document's monolithic `GenerationRunPort` into
  three cohesive sub-port protocols — `GenerationRunRepository`,
  `GenerationEventLog`, and `GenerationCheckpointPort` — and additionally
  expose a `GenerationRunPort` Protocol composing all three so the
  design-document class diagram and roadmap language remain accurate.
  Rationale: each sub-port has different transactional and concurrency
  requirements in `2.6.2` (per-run-aggregate row-level optimistic lock for run
  state versus per-run advisory lock or unique index for event append), and
  tests in `_orchestration_fakes.py` need to fake only the surface they
  exercise. Wyvern review (see ExecPlan history) flagged the monolithic
  contract as the top regret risk. Date/Author: 2026-05-29 / plan author, after
  Wyvern review.

- Decision: the adapter (not the caller) allocates `seq` on
  `append_event(run_id, kind, payload)`. Rationale: caller-supplied `seq` is
  the highest-severity production risk identified in review. Prior art (Marten
  `AppendOptimistic`, EventStoreDB stream revision, the Stack Overflow
  canonical pattern) supports adapter-side allocation backed by a
  `UNIQUE(aggregate_id, seq)` index. The port contract returns the materialised
  `GenerationEvent` so the caller observes the allocated `seq`. Date/Author:
  2026-05-29 / plan author.

- Decision: the in-memory reference adapter uses one global `asyncio.Lock` for
  run creation, run-status updates, checkpoint responses, and event appends.
  Rationale: the adapter is a correctness reference for ports, not the
  production persistence implementation. A single lock is easier to reason
  about than a per-run/two-phase lock split and ensures an event append cannot
  observe a non-terminal run concurrently with a terminal status update. The
  SQL adapter in `2.6.2` can recover concurrency with database constraints and
  transactions. Date/Author: 2026-06-04 / implementing agent.

- Decision: keep checkpoint lifecycle behaviour observable through the
  `GenerationCheckpointPort`, not through BDD steps that call domain entities
  directly. Rationale: behavioural tests should verify the functional boundary
  a TUI or REST service will exercise. The domain factory methods remain unit
  tested, while BDD scenarios now persist the run and checkpoint and invoke
  response, timeout, and cancellation through `InMemoryGenerationRunStore`.
  Date/Author: 2026-06-14 / implementing agent.

- Decision: index in-memory runs by `episode_id` and `(created_at, id)` for
  listing. Rationale: `list_runs` is a reference adapter but should still avoid
  scanning all runs when callers request a single episode. The per-episode
  sorted index preserves existing ordering while limiting work to the relevant
  episode and applying offset/limit before materialising unfiltered pages.
  Date/Author: 2026-06-14 / implementing agent.

- Decision: do not import orchestration logging helpers into
  `episodic.canonical.domain`. Rationale: `_log_event` is the repository's
  existing structured logging convention for adapters, but canonical domain
  modules are in the `domain_ports` Hecate group and must remain independent of
  orchestration. Adapter decisions now emit structured logs; adding domain
  transition logs requires a domain-owned logging seam in a later change.
  Date/Author: 2026-06-14 / implementing agent.

- Decision: log rejected terminal checkpoint transitions in
  `InMemoryGenerationRunStore._apply_checkpoint_transition`. Rationale: this
  makes failed response, timeout, and cancellation attempts observable without
  importing orchestration helpers into the canonical domain or changing the
  exceptions callers receive. Date/Author: 2026-06-14 / implementing agent.

- Decision: extend the checkpoint lifecycle from the roadmap's
  `created → responded` to `created → {responded, timed_out, cancelled}` from
  day one, with three explicit factory methods on `Checkpoint`. Rationale:
  every mature human-in-the-loop system surveyed (LangGraph middleware,
  Temporal Updates, AWS Step Functions human approval) adds at least one
  terminal state beyond "responded"; without it, abandoned approvals leak
  indefinitely. The roadmap entry names the minimum vocabulary, not the
  maximum. Date/Author: 2026-05-29 / plan author.

- Decision: introduce `EventSeq = typing.NewType("EventSeq", int)` and use it
  for every `seq` parameter and field. Rationale:
  `list_events(limit, offset, after_seq)` has three integer parameters; a naked
  `int` invites argument-order bugs that the type checker cannot catch. A
  `NewType` is zero-runtime-cost and provides nominal typing at API boundaries.
  Date/Author: 2026-05-29 / plan author.

- Decision: add `actor: str` to `GenerationRun` and `responded_by: str | None`
  to `Checkpoint` even though the roadmap entry does not list them. Rationale:
  the REST design at `docs/episodic-tui-api-design.md` line 234 already requires
  `actor` on run creation, and audit trails will demand a `responded_by` on
  every checkpoint response. Adding the fields now avoids a destructive Alembic
  migration in `2.7.x`. Date/Author: 2026-05-29 / plan author.

- Decision: do not introduce SQLAlchemy persistence, Alembic migrations, or
  REST endpoints in this plan. Rationale: those are scoped to `2.6.2` and
  `2.6.3`. Mixing them would exceed the *Scope* tolerance and the roadmap
  split. Date/Author: 2026-05-29 / plan author.

- Decision: write tests with `pytest`, `pytest-bdd`, and `hypothesis`, not
  the Rust-flavoured `rstest`/`rstest-bdd`/`proptest`/`kani`/`verus` named in
  the roadmap prologue. Rationale: this is a Python 3.14 codebase; the Rust
  toolchain language is shared roadmap boilerplate. The Python equivalents are
  already first-class in this repository (see
  `tests/test_orchestration_properties.py`, `tests/features/`, and the
  `pytest-bdd` step definitions in `tests/steps/`). Date/Author: 2026-05-29 /
  plan author.

- Decision: Vidai Mock is not used in this plan.
  Rationale: roadmap entry `2.6.1` does not invoke a language model — no
  planner, no executor, no Vidai Mock surface. Vidai Mock applies at `2.6.3`
  when the orchestrator drives runs. Date/Author: 2026-05-29 / plan author.

- Decision: treat the user's 2026-06-04 request to "proceed with
  implementation" as explicit approval to execute the existing ExecPlan.
  Rationale: the ExecPlan skill requires approval before implementation; the
  user named this ExecPlan and requested implementation directly, so no
  additional approval prompt is needed. Date/Author: 2026-06-04 / implementing
  agent.

## Outcomes & retrospective

The delivered implementation matches the observable success criteria:

- `GenerationRun`, `GenerationEvent`, and user-facing `Checkpoint` are frozen
  canonical-domain dataclasses with UUIDv7 identifiers, eager validation,
  defensive JSON-mapping copies, and explicit lifecycle enums.
- The generation-run port surface is split into repository, event-log, and
  checkpoint protocols, with a composite `GenerationRunPort` retained for the
  design-document vocabulary.
- The in-memory adapter allocates gap-free per-run event sequences internally
  and serialises event appends with run terminal-state updates under one
  `asyncio.Lock`.
- Unit, contract, property, and BDD tests cover entity validation, idempotent
  run creation, event ordering, concurrent append preservation, checkpoint
  response, timeout, cancellation, and double-response rejection.
- Hecate treats the new error and port modules as domain ports, while the
  reference adapter stays in the outbound-adapter group.
- `docs/users-guide.md`, `docs/developers-guide.md`,
  `docs/episodic-tui-api-design.md`, `docs/roadmap.md`, and ADR-015 now
  describe the implemented shape.

The main follow-up for `2.6.2` is to preserve the same port semantics in the
SQL adapter with database constraints and transactions rather than copying the
in-memory adapter's global-lock strategy. `2.6.3` will also likely need a
read-optimised run snapshot DTO for REST/TUI polling; that was intentionally
left out of `2.6.1` to keep this change at the domain-port boundary.

## Context and orientation

A reader new to this repository should orient themselves with the following
files before changing anything. All paths are repository-relative.

- `docs/roadmap.md`, section `2.6. Generation runs and checkpoints` (around
  line 307). This plan implements `2.6.1` only; `2.6.2` adds repository
  contracts and Alembic migrations, and `2.6.3` adds REST endpoints. The
  prerequisite `2.4.2` is complete (LangGraph suspend-and-resume).
- `docs/episodic-tui-api-design.md`, section `Generation runs` (line 226),
  the `GenerationRun` / `GenerationEvent` / `Checkpoint` definitions (line
  856), and the class diagram (line 1145). The `GenerationRunPort` interface
  (line 1268) drives the port shape — but see *Decision log* on the split-port
  reshaping.
- `docs/episodic-podcast-generation-system-design.md`, section
  `Content Generation Orchestrator` (line 271) and the persistent state
  inventory mentioning `generation_runs` and `workflow_checkpoints` (around
  line 1484).
- `docs/adr/adr-007-durable-generation-checkpoints.md`. This describes the
  *orchestration-layer* `WorkflowCheckpoint` (LangGraph suspend/resume). The
  user-facing `Checkpoint` introduced here is unrelated; keep the two
  conceptually separate.
- `docs/adr/adr-014-hexagonal-architecture-enforcement.md` and the
  `[tool.hecate]` block in `pyproject.toml` (around line 437). These define the
  architecture groups (`domain_ports`, `application`, `inbound_adapter`,
  `outbound_adapter`, `composition_root`) that the architecture gate enforces.
- `docs/langgraph-and-celery-in-hexagonal-architecture.md`. Explains how
  orchestration ports fit alongside canonical domain ports.

Key code to read before editing:

- `episodic/canonical/domain.py`. The existing frozen-dataclass pattern with
  UUIDv7 identifiers, `StrEnum` lifecycle types, and `__post_init__` validation.
  `WorkflowCheckpointStatus` (line 76) is the closest precedent.
- `episodic/canonical/ingestion_ports.py`. The closest existing
  `typing.Protocol`-shaped port surface in the `domain_ports` group, with
  numpy-style docstrings and `@typing.runtime_checkable` decoration.
- `episodic/canonical/services.py`. The `_new_storage_id()` helper (line 47)
  that wraps `uuid.uuid7()`; new entity-factory helpers should reuse or
  parallel this.
- `episodic/orchestration/_checkpoint_dto.py`. The frozen-dataclass DTO
  pattern with `_normalize_string_fields` and `_normalize_non_empty_text`
  validation. The new entities should reuse these helpers via re-export or copy
  them into a canonical-domain helper module.
- `episodic/orchestration/checkpoints.py`. The `InMemoryCheckpointStore`
  pattern (lock, time provider, first-write-wins) — the new in-memory adapter
  mirrors this shape.
- `episodic/canonical/storage/workflow_checkpoints.py`. The SQLAlchemy
  adapter pattern. Not implemented here, but its method signatures define the
  surface the SQL adapter in `2.6.2` will satisfy.
- `tests/test_orchestration_properties.py` and
  `tests/_orchestration_property_support.py`. The existing `hypothesis`
  strategy idioms for orchestration DTOs.
- `tests/canonical_storage/test_workflow_checkpoints.py`. The
  `pytest-bdd`/integration test idiom for checkpoint adapters.
- `tests/_orchestration_fakes.py`. The fake-port idiom (frozen-state fakes
  satisfying a Protocol) the new in-memory adapter must coexist with.

Terms of art used in this plan:

- **Port**: a `typing.Protocol` defined inside the domain that declares the
  contract an adapter must satisfy. The domain depends on the protocol; the
  adapter depends on the protocol; neither depends on the other directly.
- **Adapter**: a concrete class that implements a port. Adapters live in the
  `outbound_adapter` Hecate group when they are driven by the domain (storage,
  queues, vendor SDKs).
- **Aggregate**: a cluster of entities with a single consistency boundary.
  `GenerationRun` is the aggregate root; `GenerationEvent` and `Checkpoint` are
  children reached only via the run identifier.
- **Append-only event log**: a per-run sequence of immutable events where
  each event has a strictly monotonic, gap-free `seq` integer. New events may
  only be appended; existing events may never be edited or deleted.
- **First-write-wins**: an idempotency policy where the first writer to
  reach a given key (here, `idempotency_key`) succeeds and subsequent writers
  with the same key receive the originally-written record unchanged. Used by
  the existing `CheckpointPort.save_or_reuse` (`2.4.2`).
- **UUIDv7**: a Universally Unique Identifier variant standardised in RFC
  9562 that embeds a 48-bit millisecond timestamp and a 42-bit counter,
  providing in-process intra-millisecond monotonicity and overall time ordering.
  `uuid.uuid7()` is part of Python 3.14's standard library.
- **EventSeq**: a `typing.NewType("EventSeq", int)` introduced in this plan
  to give nominal typing to per-run sequence integers.

## Plan of work

The work proceeds in seven stages. Each stage ends with explicit validation,
and a stage may not be marked complete in *Progress* until its validation
passes. Commit after each stage with a Conventional-style message; do not amend
earlier commits.

### Stage A — research, alignment, and red-phase scaffolding

Read the files listed in *Context and orientation*. Confirm that no other code
already defines `GenerationRun`, `GenerationEvent`, or a user-facing
`Checkpoint`. (At the time of writing, `grep -n "GenerationRun" episodic/`
returns no hits — re-verify on a clean checkout.)

Create the failing test scaffolding *before* writing implementation. The new
test files are:

- `tests/test_generation_run_domain.py` — unit tests for the frozen
  dataclasses, the `EventSeq` newtype, and the two `StrEnum` lifecycle types.
- `tests/test_generation_run_port_contract.py` — port-contract tests
  exercising the in-memory adapter against the three sub-ports.
- `tests/test_generation_run_properties.py` — `hypothesis` property tests
  for append concurrency, monotonicity, and gap-freedom.
- `tests/features/generation_run_lifecycle.feature` — `pytest-bdd` feature
  describing checkpoint `created → responded`, `created → timed_out`, and
  `created → cancelled` transitions plus a double-response scenario.
- `tests/steps/test_generation_run_lifecycle_steps.py` — step definitions.

Run `make test` and confirm the new tests fail with the expected `ImportError`
or `AttributeError`. Capture the transcript to
`/tmp/red-2-6-1-$(git branch --show-current).out`.

Validation: the new tests exist, they fail, and they fail for the right reason
(missing symbol, not syntax error in the test). `make check-fmt`, `make lint`,
and `make typecheck` pass on the test files.

### Stage B — entities, enums, and `EventSeq`

Extend `episodic/canonical/domain.py` with the new lifecycle enums and
entities. Use only existing imports (`dataclasses`, `enum`, `typing`, and the
deferred `datetime`/`uuid` runtime annotation imports already in the module).
Add:

- `GenerationRunStatus(StrEnum)` with values `pending`, `running`, `paused`,
  `succeeded`, `failed`, `cancelled`, and a method `is_terminal(self) -> bool`
  returning `True` for `succeeded`, `failed`, and `cancelled`.
- `CheckpointStatus(StrEnum)` with values `created`, `responded`,
  `timed_out`, `cancelled`, and a method `is_terminal(self) -> bool` returning
  `True` for the latter three.
- `CheckpointAction(StrEnum)` with values `approve`, `request_changes`,
  `edit` (matching the REST contract at line 248 of the design document).
- `GenerationRun`, `GenerationEvent`, `Checkpoint` frozen dataclasses with
  `slots=True`, matching the attribute lists in the design document at lines
  856, 873, and 884, plus the two extra fields named in *Decision log*
  (`actor: str` on `GenerationRun`; `responded_by: str | None` on `Checkpoint`).
- Domain factory methods on `Checkpoint`: `respond(...)`,
  `time_out(self, at: dt.datetime) -> Checkpoint`, and
  `cancel(self, at: dt.datetime) -> Checkpoint`. Each returns a new frozen
  instance and raises `CheckpointAlreadyTerminal` when applied to a terminal
  checkpoint.
- A new module `episodic/canonical/generation_run_errors.py` for the
  exception hierarchy: `GenerationRunError` (base), `RunNotFound`,
  `RunAlreadyTerminal`, `StaleEventSequence`, `CheckpointNotFound`,
  `CheckpointAlreadyTerminal`. Keep imports minimal so the module fits the
  `domain_ports` group.

Introduce `EventSeq = typing.NewType("EventSeq", int)` in the same module where
the port lives (see Stage C). Use it for the `seq` field of `GenerationEvent`
and for the `after_seq` parameter of `list_events`. A small constructor helper
`event_seq(value: int) -> EventSeq` validates `value >= 1` and converts at the
boundary; using the `NewType` directly does not run a validator at runtime.

For payload fields (`GenerationRun.budget_snapshot`,
`GenerationRun.configuration`, `GenerationEvent.payload`,
`Checkpoint.response_payload`), follow the existing `WorkflowCheckpoint`
pattern: declare as `JsonMapping`, validate `isinstance(value, dict)` in
`__post_init__`, and defensively `object.__setattr__(self, field, dict(value))`
to break aliasing. `Checkpoint.options` is `tuple[str, ...]`.

Validation: re-run the failing unit tests from Stage A; the entity-level tests
now pass. `make check-fmt`, `make lint`, `make typecheck` all pass.

### Stage C — port protocols

Create `episodic/canonical/generation_run_ports.py` modelled on
`episodic/canonical/ingestion_ports.py`. Declare three protocols, each
decorated with `@typing.runtime_checkable` so the architecture-test suite in
`tests/test_port_contracts.py` can assert structural conformance:

```python
class GenerationRunRepository(typing.Protocol):
    async def create_run(
        self,
        run: GenerationRun,
        *,
        idempotency_key: str | None = None,
    ) -> GenerationRun: ...
    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None: ...
    async def list_runs(
        self,
        episode_id: uuid.UUID,
        *,
        status: GenerationRunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[GenerationRun, ...]: ...
    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        status: GenerationRunStatus,
        current_node: str | None,
        ended_at: dt.datetime | None,
    ) -> GenerationRun: ...

class GenerationEventLog(typing.Protocol):
    async def append_event(
        self,
        run_id: uuid.UUID,
        *,
        kind: str,
        payload: JsonMapping,
        occurred_at: dt.datetime | None = None,
    ) -> GenerationEvent: ...
    async def list_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
        limit: int = 100,
    ) -> tuple[GenerationEvent, ...]: ...

class GenerationCheckpointPort(typing.Protocol):
    async def create_checkpoint(
        self,
        checkpoint: Checkpoint,
    ) -> Checkpoint: ...
    async def get_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None: ...
    async def respond_to_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        response: CheckpointResponse,
    ) -> Checkpoint: ...
    async def time_out_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint: ...
    async def cancel_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint: ...

class GenerationRunPort(
    GenerationRunRepository,
    GenerationEventLog,
    GenerationCheckpointPort,
    typing.Protocol,
):
    """Composite port matching the design-document class diagram."""
```

`list_events` semantics: results are ordered ascending by `seq`. When
`after_seq` is supplied, the result range is half-open `(after_seq, ...]`. When
`after_seq` is `None`, results start from `seq=1`. `limit` is a hard cap; the
absence of a returned record at index `limit` means the page is drained.
Document these semantics in the protocol docstring.

A new `RunSnapshot` read-DTO is *out of scope* for this plan (called out by
Wyvern review). Record it as a known follow-up in *Outcomes & retrospective*
once the in-memory adapter is wired: `2.6.3` will need it but does not require
it as a `2.6.1` deliverable.

Update `episodic/canonical/ports.py` to re-export the three sub-ports and the
composite (consistent with how existing repositories are re-exported).

Validation: re-run the failing port-contract tests; they fail because there is
no implementation yet. The composite protocol is structurally satisfied by any
class implementing all three sub-ports — verify with a no-op stub in the test
file. `make typecheck` passes.

### Stage D — in-memory reference adapter

Create `episodic/canonical/adapters/generation_runs.py`. The module follows the
`InMemoryCheckpointStore` pattern in `episodic/orchestration/checkpoints.py`:

- A single `InMemoryGenerationRunStore` class that satisfies the composite
  `GenerationRunPort`.
- Internal state: `dict[UUID, GenerationRun]`,
  `dict[UUID, list[ GenerationEvent]]`, `dict[UUID, Checkpoint]`,
  `dict[str, UUID]` for the `idempotency_key → run_id` index, and a per-episode
  sorted `dict[UUID, list[tuple[datetime, UUID]]]` index for run listing.
- Injected `time_provider: cabc.Callable[[], dt.datetime]` defaulting to
  a dataclass factory returning `dt.datetime.now(dt.UTC)`, mirroring the
  existing pattern.
- Adapter-allocated `seq`: under the single in-memory lock,
  `seq = len( self._events[run_id]) + 1` after asserting the run exists and is
  not terminal. Return the persisted `GenerationEvent` to the caller.
- First-write-wins idempotency for `create_run`: if `idempotency_key` is not
  `None` and the index contains it, return the originally-stored run unchanged;
  otherwise insert and index the new run.
- Domain-side transitions for `respond_to_checkpoint`: load the current
  `Checkpoint`, call `Checkpoint.respond(...)`, and persist the returned
  instance. Timeout and cancellation use the same boundary with
  `Checkpoint.time_out(...)` and `Checkpoint.cancel(...)`. Raise
  `CheckpointAlreadyTerminal` when the loaded checkpoint is already in a
  terminal state.
- Structured logging via `episodic.orchestration._types._log_event` (the
  existing adapter convention). Domain entities do not import this helper
  because the canonical domain group must stay independent of orchestration.

Wire the adapter into the existing `_orchestration_fakes.py` and
`tests/api_fixtures.py` test surface where it does not pull in production-only
state.

Validation: the port-contract tests now pass. The architecture gate
(`make lint` → Hecate) still passes; the new adapter must be in the
`outbound_adapter` group and add its prefix to `episodic.canonical.adapters`
(already covered by the existing prefix in `pyproject.toml`).

### Stage E — property and behavioural tests

In `tests/test_generation_run_properties.py`, write `hypothesis` strategies
over event kinds and payload shapes, plus an asynchronous test using
`asyncio.gather` to interleave appends on the same run. Assertions:

- `seq` values are strictly monotonic and gap-free across the resulting
  list.
- Every appended `(kind, payload)` pair appears exactly once.
- `created_at` is non-decreasing.
- Concurrent `append_event` for different runs do not interfere (no shared
  `seq`).

In `tests/features/generation_run_lifecycle.feature`, write `pytest-bdd`
scenarios:

```gherkin
Scenario: Reviewer approves a checkpoint
  Given a generation run with a created checkpoint
  When the reviewer responds with action "approve"
  Then the checkpoint status becomes "responded"
  And the response payload is recorded

Scenario: Reviewer cannot respond twice
  Given a checkpoint that has already been responded to
  When the reviewer attempts to respond again
  Then a CheckpointAlreadyTerminal error is raised

Scenario: A checkpoint times out
  Given a created checkpoint
  When the timeout policy fires
  Then the checkpoint status becomes "timed_out"

Scenario: A cancelled run voids its open checkpoint
  Given a generation run with a created checkpoint
  When the run is cancelled
  Then the checkpoint status becomes "cancelled"
```

Add step definitions in `tests/steps/test_generation_run_lifecycle_steps.py`
following the existing `pytest-bdd` idiom in `tests/steps/`.

Validation: `make test` passes including the new scenarios. The architecture
tests in `tests/test_architecture_enforcement.py` and
`tests/test_port_contracts.py` pass with the new modules registered in the
Hecate groups.

### Stage F — documentation, design-document, ADR

Update the following documentation in a single documentation-only commit
(documentation gates are `make markdownlint` and `make nixie`):

- `docs/episodic-tui-api-design.md`: update the class diagram around line
  1268 to show the three sub-ports with `GenerationRunPort` as their union (a
  Mermaid inheritance or composition arrow), and annotate the `append_event`
  signature so it no longer suggests the caller supplies `seq`. Update the
  entity attribute list at line 856 to include `actor` on `GenerationRun` and
  `responded_by` on `Checkpoint`.
- `docs/users-guide.md`: add a short subsection under a *Generation runs*
  heading describing the new domain vocabulary (`GenerationRun`,
  `GenerationEvent`, `Checkpoint`, the three terminal states for checkpoints)
  and noting that REST endpoints land in `2.6.3`.
- `docs/developers-guide.md`: document the port split (three sub-ports +
  composite) under the architecture / canonical-ports section, the
  user-facing-`Checkpoint` versus orchestration-`WorkflowCheckpoint`
  distinction, the `EventSeq` newtype convention, the first-write-wins
  idempotency contract for `create_run`, and the adapter-allocated `seq`
  contract for `append_event`. Cross-link to ADR-007 to avoid confusion.
- A new `docs/adr/adr-015-generation-run-port-shape.md` ADR recording: the
  port split rationale, the adapter-allocated `seq` decision, the checkpoint
  lifecycle extension to `{responded, timed_out, cancelled}`, and the added
  `actor`/`responded_by` fields. Reference the design document, this ExecPlan,
  and the Wyvern review feedback in the *References* section.
- Update `[tool.hecate]` in `pyproject.toml`: add
  `episodic.canonical.generation_run_ports` and
  `episodic.canonical.generation_run_errors` to the `domain_ports` group
  `prefixes` list (no `allowed` list change needed because the existing
  `allowed = ["domain_ports"]` already covers them).

Validation: `make markdownlint`, `make nixie`, `make check-fmt`, `make lint`,
`make typecheck`, `make test` all pass. The architecture-test suite still
passes with the expanded `domain_ports` group.

### Stage G — final review and roadmap update

Run `coderabbit review --agent` and clear every concern. Address any *real*
findings; document each non-finding in the *Surprises* section. Mark roadmap
item `2.6.1` complete in `docs/roadmap.md` (change the `[ ]` to `[x]`). Update
*Progress* and *Outcomes & retrospective* with the final state and timestamps.

## Concrete steps

All commands run from the worktree root:
`/home/leynos/.lody/repos/github---leynos---episodic/worktrees/abbb722e-e684-4ceb-840f-1205018d6050`.

Every quality-gate command pipes through `tee` to a timestamped log under
`/tmp` per `AGENTS.md`:

```bash
make test       2>&1 | tee /tmp/test-episodic-$(git branch --show-current).out
make lint       2>&1 | tee /tmp/lint-episodic-$(git branch --show-current).out
make typecheck  2>&1 | tee /tmp/typecheck-episodic-$(git branch --show-current).out
make check-fmt  2>&1 | tee /tmp/check-fmt-episodic-$(git branch --show-current).out
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-$(git branch --show-current).out
make nixie      2>&1 | tee /tmp/nixie-episodic-$(git branch --show-current).out
```

Expected transcript shapes (one short example per gate) will be appended to
this section by the implementing agent as each gate first passes.

Run gates sequentially per `AGENTS.md` ("Do not run format / format checking /
lints / tests in parallel"). Do not start an isolated Cargo cache — this is a
Python project but the directive on shared caches applies generally.

Commit cadence: one commit per stage, each gated on a green run of all
applicable quality gates. Commit messages follow `AGENTS.md`:

- Stage B: `Add GenerationRun, GenerationEvent, Checkpoint domain entities`
- Stage C: `Define generation-run port protocols`
- Stage D: `Add in-memory generation-run adapter`
- Stage E: `Cover generation-run lifecycle with property and BDD tests`
- Stage F: `Document generation-run port and update architecture group`
- Stage G: `Mark roadmap 2.6.1 done`

## Validation and acceptance

Quality criteria — what *done* means:

- Tests: `make test` passes on a clean checkout. The new tests
  `test_generation_run_domain.py`, `test_generation_run_port_contract.py`,
  `test_generation_run_properties.py`, and the
  `generation_run_lifecycle.feature` scenarios are part of the run and pass.
  The property test runs at least 200 examples per property without shrinking
  to a failure.
- Lint and architecture: `make lint` passes; Hecate reports no `ARCH001`
  violations on the new modules.
- Typecheck: `make typecheck` passes; `EventSeq` is treated as nominal at
  call sites (verify by feeding a raw `int` to a function expecting `EventSeq`
  and confirming the type checker flags it).
- Formatting: `make check-fmt` passes; `make markdownlint` passes; `make nixie`
  passes for any updated Mermaid diagrams.
- Documentation: `docs/users-guide.md`, `docs/developers-guide.md`,
  `docs/episodic-tui-api-design.md`, and the new `adr-015` reflect the
  delivered shape.
- CodeRabbit: `coderabbit review --agent` reports no unresolved concerns
  after iteration.

Quality method — how we check:

- Run each `make` target listed in *Concrete steps* sequentially and inspect
  the tee'd transcript for failures.
- Run the architecture-gate test (`make lint` includes Hecate; a separate
  run via `make check-architecture` if surfaced) and inspect for `ARCH001:`
  lines.
- For the port-contract check, the test file uses
  `assert isinstance(InMemoryGenerationRunStore(), GenerationRunRepository)`
  for each sub-port and the composite — a structural-typing check enabled by
  `@typing.runtime_checkable`.

Acceptance is observable as: a fresh Python REPL can import `GenerationRun`,
`GenerationEvent`, `Checkpoint`, `GenerationRunStatus`, `CheckpointStatus`, and
`CheckpointAction` from `episodic.canonical.domain`; import the run-port
protocols and `EventSeq` from `episodic.canonical.generation_run_ports`;
instantiate `InMemoryGenerationRunStore`, create a run with an idempotency key,
repeat the call with the same key and observe the same run returned, append
three events and observe `seq=1,2,3`, create and respond to a checkpoint, and
observe a `CheckpointAlreadyTerminal` raised on a second response.

## Idempotence and recovery

The plan is additive: it introduces new modules and tests. There is no schema
migration, no data migration, and no removal of existing public API.

If a stage fails partway:

- Stage A (test scaffolding): delete the newly created test files and
  re-run the stage; no production code has changed.
- Stage B (entities): `git restore episodic/canonical/domain.py` and the
  new error module; no other production code depends on the new symbols yet.
- Stage C (ports):
  `git restore episodic/canonical/generation_run_ports.py episodic/canonical/ports.py`.
- Stage D (adapter): `git restore episodic/canonical/adapters/`.
- Stage E (tests): `git restore tests/`.
- Stage F (docs): `git restore docs/ pyproject.toml`.

All operations are local; no remote-state mutation occurs in this plan. There
is no destructive change to the database, the CI configuration, or the
published documentation.

## Artifacts and notes

Expected transcripts and short examples will be inlined as each stage
completes. The minimum capture is one short *pass* transcript per gate and one
short failure-then-pass transcript for the red→green property test.

## Interfaces and dependencies

The following names are stable contracts after this plan lands. Renaming or
reshaping any of them in a later plan counts as a breaking change.

In `episodic/canonical/domain.py`:

```python
class GenerationRunStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool: ...

class CheckpointStatus(enum.StrEnum):
    CREATED = "created"
    RESPONDED = "responded"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool: ...

class CheckpointAction(enum.StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    EDIT = "edit"

@dc.dataclass(frozen=True, slots=True)
class GenerationRun:
    id: uuid.UUID
    episode_id: uuid.UUID
    template_id: uuid.UUID
    status: GenerationRunStatus
    current_node: str | None
    started_at: dt.datetime | None
    ended_at: dt.datetime | None
    budget_snapshot: JsonMapping
    configuration: JsonMapping
    actor: str
    idempotency_key: str | None
    created_at: dt.datetime
    updated_at: dt.datetime

@dc.dataclass(frozen=True, slots=True)
class GenerationEvent:
    id: uuid.UUID
    generation_run_id: uuid.UUID
    seq: EventSeq
    kind: str
    payload: JsonMapping
    created_at: dt.datetime

@dc.dataclass(frozen=True, slots=True)
class Checkpoint:
    id: uuid.UUID
    generation_run_id: uuid.UUID
    prompt: str
    options: tuple[str, ...]
    status: CheckpointStatus
    response_action: CheckpointAction | None
    response_payload: JsonMapping | None
    responded_at: dt.datetime | None
    responded_by: str | None
    created_at: dt.datetime

    def respond(
        self,
        *,
        action: CheckpointAction,
        payload: JsonMapping,
        responded_at: dt.datetime,
        responded_by: str,
    ) -> "Checkpoint": ...
    def time_out(self, at: dt.datetime) -> "Checkpoint": ...
    def cancel(self, at: dt.datetime) -> "Checkpoint": ...
```

In `episodic/canonical/generation_run_ports.py`:

```python
EventSeq = typing.NewType("EventSeq", int)

@typing.runtime_checkable
class GenerationRunRepository(typing.Protocol):
    async def create_run(
        self,
        run: GenerationRun,
        *,
        idempotency_key: str | None = None,
    ) -> GenerationRun: ...
    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None: ...
    async def list_runs(
        self,
        episode_id: uuid.UUID,
        *,
        status: GenerationRunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[GenerationRun, ...]: ...
    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        status: GenerationRunStatus,
        current_node: str | None,
        ended_at: dt.datetime | None,
    ) -> GenerationRun: ...

@typing.runtime_checkable
class GenerationEventLog(typing.Protocol):
    async def append_event(
        self,
        run_id: uuid.UUID,
        *,
        kind: str,
        payload: JsonMapping,
        occurred_at: dt.datetime | None = None,
    ) -> GenerationEvent: ...
    async def list_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
        limit: int = 100,
    ) -> tuple[GenerationEvent, ...]: ...

@typing.runtime_checkable
class GenerationCheckpointPort(typing.Protocol):
    async def create_checkpoint(
        self,
        checkpoint: Checkpoint,
    ) -> Checkpoint: ...
    async def get_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None: ...
    async def respond_to_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        action: CheckpointAction,
        payload: JsonMapping,
        responded_at: dt.datetime,
        responded_by: str,
    ) -> Checkpoint: ...

@typing.runtime_checkable
class GenerationRunPort(
    GenerationRunRepository,
    GenerationEventLog,
    GenerationCheckpointPort,
    typing.Protocol,
): ...
```

In `episodic/canonical/adapters/generation_runs.py`:

```python
class InMemoryGenerationRunStore:
    """Reference adapter satisfying `GenerationRunPort` for tests."""
    def __init__(
        self,
        *,
        time_provider: cabc.Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None: ...
```

In `episodic/canonical/generation_run_errors.py`:

```python
class GenerationRunError(Exception): ...
class RunNotFound(GenerationRunError): ...
class RunAlreadyTerminal(GenerationRunError): ...
class StaleEventSequence(GenerationRunError): ...
class CheckpointNotFound(GenerationRunError): ...
class CheckpointAlreadyTerminal(GenerationRunError): ...
```

External dependencies: none added. Python 3.14 standard library only (`uuid`,
`dataclasses`, `enum`, `typing`, `datetime`, `asyncio`, `collections.abc`).
Test-side dependencies (`pytest`, `pytest-bdd`, `hypothesis`) are already in
`pyproject.toml`.

Hecate group changes (`[tool.hecate]` in `pyproject.toml`): extend the
`domain_ports` group `prefixes` list with
`"episodic.canonical.generation_run_ports"` and
`"episodic.canonical.generation_run_errors"`. The adapter at
`episodic.canonical.adapters.generation_runs` is already covered by the existing
`episodic.canonical.adapters` prefix in the `outbound_adapter` group.

Cross-references (signposted documentation and skills):

- The `execplans` skill (`docs/execplans/`) for ExecPlan formatting and
  living-document rules.
- The `hexagonal-architecture` skill for port/adapter discipline; in
  particular the rule that the domain owns the port and the adapter implements
  it, and that domain code must not import infrastructure types.
- ADR-014 (`docs/adr/adr-014-hexagonal-architecture-enforcement.md`) and
  Hecate configuration in `pyproject.toml` for the actual enforced groups.
- ADR-007 (`docs/adr/adr-007-durable-generation-checkpoints.md`) for the
  *orchestration-layer* `WorkflowCheckpoint` (distinct from the user-facing
  `Checkpoint` introduced here).
- `docs/episodic-tui-api-design.md` for the REST contract that `2.6.3`
  will satisfy against the ports defined here.
- `docs/episodic-podcast-generation-system-design.md`, section
  *Content Generation Orchestrator*, for the broader runtime picture.
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` for the way
  orchestration ports coexist with canonical ports.
- `docs/testing-async-falcon-endpoints.md` and
  `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md` for the testing idiom
  this plan reuses (no Falcon or SQLAlchemy is touched here, but the test-style
  continuity matters for `2.6.2` and `2.6.3`).
- `docs/async-sqlalchemy-with-pg-and-falcon.md` for the SQLAlchemy
  adapter shape `2.6.2` will implement against these ports.

## Revision note

Initial draft authored 2026-05-29. Sources of design input: roadmap entry
`2.6.1`, `docs/episodic-tui-api-design.md` (sections *Generation runs*,
*Checkpoint intervention*, *Hexagonal architecture alignment*, *Data model
extensions*, and the domain class diagram), ADR-007, ADR-014, the 2.4.2
ExecPlan and its in-memory checkpoint adapter, a firecrawl evidence brief on
UUIDv7, optimistic-concurrency event logs, and human-in-the-loop lifecycle
vocabulary, and a Logisphere/Wyvern design review whose top finding was the
adapter-allocated-`seq` requirement.
