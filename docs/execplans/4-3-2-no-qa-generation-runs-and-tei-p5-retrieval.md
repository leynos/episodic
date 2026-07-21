# Implement no-QA generation runs and TEI-P5 retrieval (4.3.2)

This ExecPlan (execution plan) is a living document. The sections `Constraints`,
`Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`, `Decision Log`,
and `Outcomes & Retrospective` must be kept up to date as work proceeds.

Status: IN PROGRESS

## Purpose / big picture

After this change an integration client can drive the narrowest useful
source-to-script workflow entirely through JSON/REST (Representational State
Transfer) without touching the quality-assurance (QA), audio, or export-job
pipelines:

1. Upload show source material and attach presenter context (already delivered
   by roadmap task 4.3.1).
2. Create a generation run for an episode with
   `quality_mode=draft_without_qa`, a `skip_qa_rationale`, and actor metadata,
   protected by an `Idempotency-Key`.
3. Poll the run resource and its append-only event log over REST until the run
   reaches a terminal state.
4. Download the resulting Text Encoding Initiative (TEI) P5 script as either a
   JSON metadata envelope or an `application/tei+xml` file.

This validates the `/v1` resource contract defined in
[ADR 009](../adr/adr-009-source-to-script-rest-vertical-slice.md) before the
full approval, QA, audio, and export surfaces land.

You can observe success by running the end-to-end behavioural scenario
`tests/features/no_qa_generation_slice.feature` (added by this plan) against a
running service backed by a Vidai Mock inference server: a `POST` to
`/v1/episodes/{episode_id}/generation-runs` returns `202 Accepted` with a
`Location` header, polling `GET /v1/generation-runs/{run_id}` transitions from
`pending` to `succeeded`, and `GET /v1/episodes/{episode_id}/tei` with
`Accept: application/tei+xml` returns a downloadable TEI-P5 document whose
`qa_status` is `skipped`.

## Scope and roadmap relationship

This task is the second half of the source-to-script vertical slice. It depends
on roadmap items 2.1.1 (the `LLMPort` adapter), 2.4.2 (LangGraph
suspend-and-resume orchestration), and 4.3.1 (source and presenter-profile
intake).

The vertical-slice design in ADR 009 deliberately cuts across the horizontal
roadmap items 2.6.2 (generation-run persistence) and 2.6.3 (generation-run REST
endpoints). This plan therefore implements the **subset** of durable
generation-run persistence and REST endpoints that the no-QA slice needs, in a
shape that those later tasks extend rather than replace. Out of scope and left
to later tasks: human-review checkpoint persistence (2.6.2), the full
generation-run REST surface including the checkpoint endpoint (2.6.3), the
QA-gated execution graph and the full draft-generation graph (4.4.1), and an
automated stuck-run recovery worker (2.6.2). This plan does, however, add the
*durable hooks and observability* (lease columns, conditional state
transitions, stuck-run signal) that ADR 009 requires so those later workers
inherit a recoverable, observable system rather than a silent one.

Three slice-shaping decisions were confirmed with the requester before drafting
(see `Decision Log`):

1. **Execution model:** in-process asynchronous execution behind a launcher
   port, with durable run and event records so REST polling works across
   requests. Celery dispatch is deferred (ADR 007 records that
   LangGraph-to-Celery dispatch has not yet landed; `TaskResumePort` is the
   future seam). The launcher is documented as a degenerate `TaskResumePort` so
   2.6.2/4.4.1 can converge it onto the durable checkpoint model.
2. **Episode provisioning:** the episode and its initial canonical TEI are
   materialized from the ingestion job's attached sources, so the client flow
   stays upload → ingest → generate without a separate episode-creation API.
3. **Generation engine:** a minimal but real single-pass, large language model
   (LLM)-driven draft generator behind a `DraftScriptGenerator` port, producing
   valid TEI-P5 spoken script, exercised through Vidai Mock. The full
   QA-bypass-branching draft graph is left to roadmap item 4.4.1, which swaps
   the engine behind the same port.

## Constraints

Hard invariants that must hold throughout implementation. Violation requires
escalation, not a workaround.

- Respect the hexagonal architecture boundary rules enforced by
  [ADR 014](../adr/adr-014-hexagonal-architecture-enforcement.md) and
  `make lint` (`make check-architecture`). Domain code in `episodic/canonical/`
  and `episodic/generation/` must not import Falcon, SQLAlchemy, httpx, Celery,
  or LangGraph. The architecture groups are defined by exact module-prefix
  lists in `pyproject.toml` (the `domain_ports`, `application`,
  `outbound_adapter`, `inbound_adapter`, and `composition_root` groups). There
  is **no blanket `episodic.canonical` prefix**, so every new module must be
  added to the correct prefix list in `pyproject.toml` or it falls outside
  enforcement.
- Preserve TEI-P5 as the canonical episode artefact. All script content is
  produced, stored, and served as valid TEI-P5 XML parsed, validated, and
  emitted through the `tei-rapporteur` library (see
  [TEI Rapporteur users' guide](../tei-rapporteur-users-guide.md)). Do not add
  a second TEI parser or hand-roll XML traversal (the spoken-text semantic
  contract is owned by
  [ADR 006](../adr/adr-006-chrono-spoken-text-semantics.md)).
- Honour the ADR 009 API contract exactly: `quality_mode=draft_without_qa` runs
  record `qa_status=skipped`, the requesting actor, and a client-supplied
  rationale; side-effecting `POST` requests accept `Idempotency-Key` with
  first-write-wins semantics, identical-body replay (including the stored
  `Location` and `Retry-After`), and `409 Conflict` on body mismatch;
  long-running creation returns `202 Accepted` with `Location` and
  `Retry-After`.
- The launcher's asynchronous task MUST own a fresh unit of work obtained from
  `uow_factory` and MUST NOT reuse the request's unit of work, session, or any
  repository bound to it. The request transaction is closed once the `202`
  response is sent.
- All state transitions that can race across workers MUST be conditional
  (compare-and-set): `pending → running` is a guarded `UPDATE`, and the episode
  TEI write is optimistic on `tei_revision`. No blind status overwrites.
- The TEI download uses the `application/tei+xml` media type registered by
  [RFC 6129](https://datatracker.ietf.org/doc/html/rfc6129) with
  `Content-Disposition: attachment`.
- Do not modify the public contract or behaviour of existing 4.3.1 intake
  endpoints, series-profile, episode-template, reference-document, or
  reference-binding resources beyond additive wiring.
- The TEI file download must not require the audio or export-job pipeline.
- All Python quality gates must pass before each milestone is considered
  complete: `make check-fmt`, `make typecheck`, `make lint`, `make test`, and
  (when models or migrations change) `make check-migrations`. Markdown changes
  must pass `make markdownlint` and `make nixie`.

## Tolerances (exception triggers)

Stop and escalate (record the situation in `Decision Log` and await direction)
when any of the following is breached.

- Scope: if a single milestone requires net changes to more than 12 source
  files or more than roughly 600 net lines, stop and re-segment.
- Interface: if delivering the slice forces a breaking change to an existing
  public `/v1` route, the `LLMPort`, the `GenerationRunPort` sub-protocols, or
  the `CanonicalUnitOfWork` surface, stop and escalate.
- Dependencies: if a new third-party runtime dependency (beyond what is already
  in `pyproject.toml`, and beyond the Vidai Mock test-only binary) is required,
  stop and escalate.
- Idempotency adapter: if the durable SQLAlchemy `IdempotencyStore` adapter that
  `POST /v1/uploads` relies on turns out to be missing rather than present,
  implementing it is an escalation-gated sub-task (it is a prerequisite the
  slice assumes 4.3.1 already shipped), not silent extra work.
- Migrations: if `make check-migrations` reports drift that cannot be resolved
  by an additive, reversible migration, stop and escalate.
- Iterations: if a focused test still fails after 3 genuine fix attempts, stop
  and escalate with the failing transcript.
- Architecture: if satisfying a requirement appears to require a domain module
  to import an infrastructure library, stop and escalate rather than relaxing
  `make check-architecture`.
- Ambiguity: if an unanticipated design fork materially changes the externally
  observable contract, stop and present options with trade-offs.

## Risks

- Risk: the launcher is implemented as a background task that closes over the
  request's unit of work or session, causing use-after-free on a recycled
  connection (silent cross-episode corruption or `IllegalStateChangeError`).
  Severity: high. Likelihood: high (this is the natural-but-wrong
  implementation). Mitigation: a hard constraint (above) plus a dedicated
  Milestone 4 test that launches through real `asyncio.create_task` against
  py-pglite and asserts the task writes through its own session while the
  request unit of work is already closed. The "drive deterministically"
  shortcut covers logic only; one test must exercise the detached-session path.
- Risk: a run is left stuck in `running` after a deploy/restart/crash, its
  idempotency record stuck `InFlight`, so every retry with the same key returns
  `409` forever and the client cannot resubmit. Severity: high. Likelihood:
  high (happens on every deploy overlapping an in-flight run). Mitigation:
  persist `started_at` (indexed) and add `lease_expires_at` and
  `error_category` columns now (additive); make `pending → running` a
  conditional update; emit a startup stuck-run gauge (count of `running` older
  than a threshold) so the state is alertable; document a manual-fail runbook.
  The automated reaper itself is deferred to 2.6.2, but the recoverable hooks
  and signal ship now (ADR 009 §Partial-failure recovery and §Observability
  require this regardless of when the worker lands).
- Risk: idempotency partial failure — the run row is created but task scheduling
  fails, orphaning a `pending` run while the idempotency record is `failed` or
  `complete`. Severity: high. Likelihood: medium. Mitigation: specify the
  ordering — create the run row and schedule the task inside the same `work()`;
  if scheduling fails, mark the run `failed` with an `error_message` (do not
  merely fail the idempotency record) so the orphan is visible and the
  stuck-run gauge catches it.
- Risk: the generated draft is not valid TEI-P5 and fails `tei-rapporteur`
  validation on persistence, raising inside the detached task with no Falcon
  handler. Severity: high. Likelihood: medium. Mitigation: the launcher's outer
  try/except covers generation AND persistence AND validation, mapping any
  exception to `run.failed` + `error_message` + terminal status with a distinct
  `tei.invalid` event kind; a unit test feeds invalid TEI and asserts `failed`
  rather than a leaked exception.
- Risk: snapshot tests are non-deterministic because TEI `xml:id` values or
  timestamps vary per run. Severity: high. Likelihood: high (without
  mitigation; the codebase reaches for `uuid.uuid4().hex` for fresh ids
  elsewhere). Mitigation: a deterministic id scheme (`sp-1`, `p-1`, …) and the
  existing injected `clock()` provider routed into the generator, persistence
  service, and run store; freeze the clock and pin ids in snapshot tests.
- Risk: LLM draft spend is never ledgered because the cost recorder is not wired
  into the launcher's composition root (a regression against the just-landed
  2.4.4 cost accounting and an ADR 009 observability requirement). Severity:
  medium. Likelihood: high (the plan's earlier "if available" hedge would
  silently skip it). Mitigation: wiring `CostRecorder` (over
  `SqlAlchemyCostLedgerStore`) into the composition root and the launcher is an
  explicit Milestone 4 deliverable, not a conditional.
- Risk: detached tasks are garbage-collected mid-run or run unbounded,
  competing with request handling on the event loop. Severity: medium.
  Likelihood: medium. Mitigation: hold strong task references in a registry,
  bound concurrency with a semaphore, drain the registry in a shutdown hook
  (marking drained runs `failed`), and document the single-worker assumption in
  the new ADR.
- Risk: scope bleed into roadmap items 2.6.2, 2.6.3, or 4.4.1.
  Severity: medium. Likelihood: medium. Mitigation: the
  `Scope and roadmap relationship` section fixes the boundary.

## Progress

- [x] (completed, 2026-06-24) M0: Branch, plan baseline, and red
  end-to-end scaffold. Implementation approval was given in this Lody session;
  the branch already had the requested name, and branch tracking plus
  PR/session metadata were aligned. The red behavioural scaffold now exists at
  `tests/features/no_qa_generation_slice.feature` and
  `tests/steps/test_no_qa_generation_slice.py`; the focused run produced
  `7 xfailed in 0.48s` as expected. Deterministic gates passed:
  `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make markdownlint`, and `make nixie`. CodeRabbit review completed with zero
  findings.
- [x] (completed, 2026-06-24) M1: Domain model extensions (quality mode, QA
  status, rationale). Red evidence captured the missing
  `episodic.canonical.generation_quality` module. Green focused evidence:
  `tests/test_generation_run_domain.py`,
  `tests/test_generation_run_port_contract.py`,
  `tests/test_generation_run_properties.py`, and
  `tests/steps/test_generation_run_lifecycle_steps.py` passed with
  `38 passed in 1.43s`. Full deterministic gates passed: `make check-fmt`,
  `make typecheck`, `make lint`, `make test`, `make markdownlint`, and
  `make nixie`. CodeRabbit review completed with zero findings after the
  required rate-limit backoff and retry.
- [x] (completed, 2026-06-24) M2a: Durable generation-run and event
  persistence. Initial orientation found that storage models are surfaced
  through `episodic/canonical/storage/models.py` for Alembic metadata, and
  `SqlAlchemyUnitOfWork` wires repositories during `__aenter__`, matching the
  pattern M2a should extend. Red storage tests were added at
  `tests/canonical_storage/test_generation_runs.py`; the focused run failed
  during collection because `GenerationEventRecord` is not yet exported from
  `episodic.canonical.storage`. Green focused evidence: the new SQLAlchemy
  storage tests passed with `8 passed in 3.53s`, and the updated generation-run
  port contract/property tests passed with `17 passed in 0.68s`. After the
  checkpoint adapter split, the focused storage/port/lifecycle suite passed with
  `29 passed in 4.29s`; full deterministic gates passed: `make check-fmt`,
  `make typecheck`, `make lint`, `make test`, and `make check-migrations`.
  CodeRabbit review completed with zero findings.
- [x] (completed, 2026-06-24) M2b: Episode TEI revisioning columns and
  optimistic update. Red evidence captured the missing
  `episodic.canonical.episode_errors` module after adding failing storage
  tests. Green focused evidence: `tests/canonical_storage/test_episodes.py`,
  `tests/canonical_storage/test_episode_tei_updates.py`, and
  `tests/test_protocol_stubs.py` passed with `64 passed in 3.51s`. The new
  migration applies through `20260624_000011`, and full deterministic gates
  passed: `make check-fmt`, `make typecheck`, `make lint`, `make test`,
  `make check-migrations`, `make markdownlint`, and `make nixie`. CodeRabbit
  review completed with zero findings.
- [x] (completed, 2026-06-24) M3: Draft script generator port and TEI
  persistence service. Orientation found that the installed `tei_rapporteur`
  Python binding accepts `utterance` payloads emitted as `<u who="...">`, while
  `<sp><speaker>...</speaker><p>...</p></sp>` XML is not currently accepted by
  `parse_xml`. Red focused evidence captured the missing
  `episodic.generation.draft_script` and
  `episodic.canonical.generation_persistence` modules. Green focused evidence:
  `tests/test_draft_script_generation.py` and
  `tests/test_generation_persistence.py` passed with `9 passed in 2.82s`. Full
  deterministic gates passed: `make check-fmt`, `make typecheck`, `make lint`,
  `make test` (`988 passed, 2 skipped, 7 xfailed`), `make markdownlint`, and
  `make nixie`. CodeRabbit review completed with zero findings.
- [ ] (implemented, deterministic gates passed, 2026-06-24) M4: In-process
  launcher, lifecycle events, cost wiring, and observability. The launcher now
  claims pending no-QA runs, records `run.started`, emits `draft.generated`
  before TEI persistence, persists valid TEI, records cost ledger entries when
  a recorder is configured, and marks terminal success/failure states with
  stable error categories. Green focused evidence:
  `tests/test_generation_run_launcher.py` and
  `tests/test_env_runtime_wiring.py` passed with `15 passed in 14.24s`. Full
  deterministic gates passed: `make check-fmt`, `make typecheck`, `make lint`,
  `make test` (`994 passed, 2 skipped, 7 xfailed`), `make markdownlint`, and
  `make nixie`. CodeRabbit review remains pending for this milestone.
- [ ] (pending) M5: Generation-run REST endpoints with idempotency (incl.
  Location/Retry-After replay).
- [ ] (pending) M6: Episode TEI retrieval endpoint with content negotiation.
- [ ] (pending) M7: End-to-end behavioural slice with Vidai Mock (observed
  passing at least once).
- [ ] (pending) M8: Documentation, roadmap update, and final gates.

## Surprises & discoveries

- Observation: the existing generation-orchestration graph
  (`episodic/orchestration/langgraph.py`,
  `build_generation_orchestration_graph`) takes an existing `script_tei_xml`
  and *enriches* it (default action `GENERATE_SHOW_NOTES`); it does not
  generate the initial script from sources, and
  `GenerationOrchestrationRequest` requires a non-empty `script_tei_xml`.
  Evidence: `episodic/orchestration/_dto.py` (`GenerationOrchestrationRequest`
  around line 177; `enabled_action_kinds=(ActionKind.GENERATE_SHOW_NOTES,)`
  around line 221). Impact: 4.3.2 introduces a separate minimal
  `DraftScriptGenerator`; the orchestration graph is not on the critical path
  for this slice.
- Observation: there is **no** service that materializes a `CanonicalEpisode`
  from intake-stage (4.3.1) sources. `_create_canonical_episode`
  (`episodic/canonical/services.py` around line 91) needs a `TeiHeader` parsed
  from caller-supplied TEI, and the 4.3.1 intake path
  (`episodic/canonical/source_intake_service.py`) creates only ingestion jobs
  and sources — never an episode. The draft TEI is *produced by generation*, so
  there is an ordering problem. Evidence: greps over `episodes.add`,
  `source_intake_service.py`. Impact: Milestone 3 adds an explicit "materialize
  episode from ingestion job" step that creates the episode with a minimal
  placeholder TEI header before generation, then the launcher updates it with
  the generated script. This is a new step, not pure reuse; the construction
  helpers may be reused but the path is new.
- Observation: `GenerationRun.source_bundle_id` exists with no producer; the
  ingestion job whose sources materialize the episode is the natural bundle.
  Evidence: `episodic/canonical/domain.py` around line 139; no `SourceBundle`
  aggregate exists. Impact: map `source_bundle_id` to the ingestion job id.
- Observation: `GenerationRun` and `CanonicalEpisode` are `frozen=True` with no
  field defaults; adding fields breaks ~5 `GenerationRun(` and ~18
  `CanonicalEpisode(` construction sites and the full-repr snapshot
  `tests/__snapshots__/test_generation_run_domain.ambr`. Evidence: `domain.py`
  around lines 133 and 308. Impact: give the new fields safe defaults where
  possible and regenerate the affected snapshot as an explicit M1 step.
- Observation: Vidai Mock subprocess fixtures already exist in the repo
  (`tests/steps/test_guest_bios_steps.py` has `_start_vidaimock_process`,
  `_await_port_ready`, `_terminate_process_gracefully`, and a `shutil.which`
  skip); the `model="vidai-mock"` name convention is established. Evidence:
  `tests/steps/test_guest_bios_steps.py`,
  `tests/steps/generation_orchestration_vidaimock.py`,
  `tests/_guest_bios_helpers.py`. Impact: Milestone 7 extracts these helpers
  into a shared `tests/fixtures/` module and reuses them rather than writing a
  third copy.
- Observation: on 2026-06-24 the local branch was already named
  `4-3-2-no-qa-generation-runs-and-tei-p5-retrieval` and the matching remote
  branch existed at `origin`, but the worktree did not have an upstream branch
  configured. The original Concrete steps section still referenced the planning
  worktree path. Evidence: `git branch --show-current`,
  `git ls-remote --heads origin 4-3-2-no-qa-generation-runs-and-tei-p5-retrieval`,
  and `git branch -vv`. Impact: Milestone 0 sets tracking with
  `git branch --set-upstream-to` instead of renaming an already correctly named
  branch, and the Concrete steps path is updated to this implementation
  worktree.
- Observation: the first M1 `coderabbit review --agent` request hit a
  recoverable CodeRabbit rate limit. Impact: the implementation followed the
  required backoff command, `vsleep $(shuf -i 45-90 -n 1)m`, then retried the
  review successfully before starting M2a.
- Observation: adding SQLAlchemy persistence plus guarded run claiming pushed
  the in-memory generation-run adapter over the 400-line project limit. Impact:
  the checkpoint methods were extracted into
  `episodic/canonical/adapters/generation_checkpoints.py` as a mixin, keeping
  the run/event adapter focused while preserving the existing public in-memory
  test adapter surface.
- Observation: SQL event sequence allocation cannot rely on `max(seq) + 1`
  alone; concurrent appenders could read the same maximum and one would fail
  the unique `(generation_run_id, seq)` constraint. Impact: the SQLAlchemy
  store locks the owning generation-run row before allocating the next event
  sequence, serializing appenders per run without introducing a separate
  sequence table.
- Observation: adding optimistic episode TEI updates would have pushed the
  existing storage repository and episode test module beyond the project
  400-line guideline. Impact: the SQLAlchemy episode repository now lives in
  `episodic/canonical/storage/episode_repository.py`, and the TEI update tests
  live in `tests/canonical_storage/test_episode_tei_updates.py`, keeping the
  changed modules focused.
- Observation: `tei_rapporteur.parse_xml` rejects `<sp>` blocks in the current
  binding (`unknown variant sp`) but accepts body `utterance` payloads, which
  emit as TEI `<u who="...">` elements. Impact: Milestone 3 uses
  `tei_rapporteur.from_dict` with `utterance`/`paragraph` blocks for the
  minimal draft script, preserving TEI validation without hand-written XML.
- Observation: `ingestion_jobs.target_episode_id` has a foreign key to
  `episodes.id`, so an intake job cannot point at an episode id that the
  materialization step has not created yet. Impact: M3 materialization treats a
  `NULL` target episode as the normal pre-generation state and allocates the
  episode id while projecting attached intake sources into canonical source
  documents.
- Observation: M4 source documents preserve rich source text in
  `SourceDocument.metadata["content"]` when it is available, while older or URI
  only sources may only have `source_uri`. Impact: the launcher builds
  `DraftScriptSource.content` from non-blank metadata content first, falling
  back to `source_uri` so legacy rows still produce deterministic generator
  requests.

## Decision log

- Decision: execution model is in-process async behind a `GenerationRunLauncher`
  port; Celery dispatch deferred; the launcher is documented as a degenerate
  `TaskResumePort`. Rationale: ADR 007 records that LangGraph-to-Celery
  dispatch has not landed and that `TaskResumePort` is the future seam; the
  slice only needs the 202/poll/download contract, which durable run/event
  records satisfy without a worker. Documenting the convergence keeps
  2.6.2/4.4.1 collapsing onto the checkpoint model instead of replacing the
  launcher. Confirmed with requester on 2026-06-15. Date/Author: 2026-06-15,
  planning agent.
- Decision: the episode is materialized from the ingestion job's attached
  sources (with a placeholder TEI header created before generation) rather than
  via a new `POST /v1/episodes`. Rationale: keeps the client flow upload →
  ingest → generate; aligns with `GenerationRun.source_bundle_id`; avoids
  adding episode-CRUD surface owned by later roadmap work. Confirmed with
  requester on 2026-06-15. Date/Author: 2026-06-15, planning agent.
- Decision: 4.3.2 ships a minimal real single-pass `DraftScriptGenerator`
  behind a port; the full QA-bypass draft graph is left to 4.4.1. Rationale:
  roadmap 4.4.1 (requires 4.3.2) owns the draft generation graph with explicit
  QA bypass; a port keeps the engine swappable. Confirmed with requester on
  2026-06-15. Date/Author: 2026-06-15, planning agent.
- Decision: 4.3.2 implements durable SQLAlchemy persistence for generation runs
  and events plus the generation-run REST endpoints it needs, as a subset of
  2.6.2/2.6.3. Rationale: cross-process REST polling is impossible with the
  in-memory adapter (ADR 007 calls it tests/local only). Date/Author:
  2026-06-15, planning agent.
- Decision: an unsupported-but-recognized `quality_mode` value returns
  `422 Unprocessable Entity`; a malformed body or missing/blank
  `skip_qa_rationale` returns `400 Bad Request`. Rationale: a shape-valid body
  carrying `quality_mode="qa_gated"` is semantically unsupported in this slice;
  422 lets `qa_gated` later become a `202` without flipping a wire status from
  `400` (which clients may treat as "never valid") — `422 → 202` is
  forward-compatible, `400 → 202` is not. Aligns with the TUI design error
  table. Date/Author: 2026-06-15, planning agent.
- Decision: `GET /v1/episodes/{id}/tei` before any draft exists returns
  `404 Not Found` (recorded as a contract, not a TODO, so it does not silently
  flip to `200` empty later, which would be breaking). Date/Author: 2026-06-15,
  planning agent.
- Decision: optimistic concurrency (`expected_revision`) is out of scope for
  this slice's read-only `GET /tei` and append-only run creation, but the
  episode `tei_revision` integer returned as the envelope `version` is the
  exact value a later `expected_revision` (on `PUT /tei` / `PATCH /script`)
  will compare against, so the contract composes later without renaming.
  Date/Author: 2026-06-15, planning agent.
- Decision: the no-QA slice keeps idempotency in Python (reusing
  `IdempotencyStore` and `run_idempotent`); no Rust extension or formal proof
  is introduced. ADR 009 anticipates Kani/Verus only if the idempotency state
  machine moves into Rust; that is a future task. Date/Author: 2026-06-15,
  planning agent.
- Decision: treat the 2026-06-24 user request to proceed as ExecPlan approval
  and move this document from draft to in-progress. Rationale: the plan
  approval gate is satisfied by the explicit implementation request, and the
  requester also required the plan to remain current during delivery.
  Date/Author: 2026-06-24, implementation agent.
- Decision: preserve the existing `update_run_status(...) -> GenerationRun`
  port contract for ordinary lifecycle updates and add
  `claim_run_for_execution(...) -> GenerationRun | None` for the guarded
  `pending -> running` transition. Rationale: this gives the launcher an
  explicit compare-and-set operation that reports whether it won without
  weakening the existing status-update API. `None` means another worker claimed
  the run first; missing or terminal runs still raise the existing domain
  errors. Date/Author: 2026-06-24, implementation agent.
- Decision: allocate SQL generation-event sequences while holding a row-level
  lock on the parent `generation_runs` record. Rationale: the append-only log
  requires gap-free, monotonic sequence numbers per run; locking the parent run
  row is the smallest durable serialization point already present in the schema
  and keeps the event table append-only. Date/Author: 2026-06-24,
  implementation agent.
- Decision: episode TEI updates use an `EpisodeTeiUpdate` request object
  instead of expanding `EpisodeRepository.update` with several scalar keyword
  parameters. Rationale: the update operation must carry TEI XML, QA status,
  generation-run provenance, expected revision, and an optional timestamp as
  one coherent command; grouping them keeps the port stable and avoids a long,
  error-prone parameter list. Date/Author: 2026-06-24, implementation agent.

## Context and orientation

This is a Python project. The HTTP service is built on Falcon's ASGI
application; persistence uses async SQLAlchemy with PostgreSQL (tested against
py-pglite); orchestration uses LangGraph with a Celery worker boundary. Domain
logic is kept behind ports and adapters (hexagonal architecture).

Read these documents before starting; they are the source of truth for this
slice:

- [ADR 009: Source-to-script REST vertical slice](../adr/adr-009-source-to-script-rest-vertical-slice.md)
  — the API contract, idempotency rules, observability, partial-failure
  recovery, and testing strategy.
- [ADR 007: Durable generation checkpoints](../adr/adr-007-durable-generation-checkpoints.md)
  — orchestration boundary and why Celery dispatch is deferred.
- [ADR 006: Chrono spoken-text semantics](../adr/adr-006-chrono-spoken-text-semantics.md)
  — which TEI elements count as spoken script (`<sp>`, `<u>`, `<p>`, `<l>`,
  `<ab>`, `<seg>`; `<speaker>`/`<stage>`/`<note>` excluded). This fixes the
  shape the generator must emit and Chrono will later consume.
- [ADR 015: Generation-run port split](../adr/adr-015-generation-run-port-split.md)
  and
  [ADR 015: Upload and idempotency ports](../adr/adr-015-upload-and-idempotency-ports.md).
- [ADR 014: Hexagonal architecture enforcement](../adr/adr-014-hexagonal-architecture-enforcement.md).
- [Episodic podcast generation system design](../episodic-podcast-generation-system-design.md),
  section "Source-to-script vertical slice".
- [Episodic TUI API design](../episodic-tui-api-design.md), sections
  "Episodes and TEI" and "Generation runs", and the standard error table.
- [Async SQLAlchemy with PostgreSQL and Falcon](../async-sqlalchemy-with-pg-and-falcon.md).
- [Testing async Falcon endpoints](../testing-async-falcon-endpoints.md).
- [Testing SQLAlchemy with pytest and py-pglite](../testing-sqlalchemy-with-pytest-and-py-pglite.md).
- Read
  [Agentic systems with LangGraph and Celery](../agentic-systems-with-langgraph-and-celery.md).

Relevant skills to load when implementing: `hexagonal-architecture`,
`python-router` (then `python-types-and-apis`, `python-data-shapes`,
`python-errors-and-logging`, `python-testing`, `python-verification`),
`vidai-mock`, and `leta` for code navigation.

### Key existing code (full repository-relative paths)

Domain and ports:

- `episodic/canonical/domain.py` — `GenerationRun` (around line 133),
  `GenerationRunStatus` (around line 93), `GenerationEvent` (around line 161),
  `CanonicalEpisode` (around line 308), `TeiHeader` (around line 297),
  `EpisodeStatus`, `ApprovalState`.
- `episodic/canonical/generation_run_ports.py` —
  `GenerationRunRepository`, `GenerationEventLog`, `GenerationCheckpointPort`,
  composite `GenerationRunPort`, `EventSeq` newtype (`event_seq` rejects `< 1`;
  `list_events(after_seq, limit)` is half-open `(after_seq, …]`, ascending by
  `seq`, `limit` a hard cap).
- `episodic/canonical/adapters/generation_runs.py` —
  `InMemoryGenerationRunStore` (reference adapter; tests/local only).
- `episodic/canonical/idempotency.py`, `episodic/canonical/upload_protocols.py`
  (`IdempotencyStore`), `episodic/canonical/idempotency_service.py`
  (`json_body_hash` → `canonical_json_bytes`; SHA-256 over canonical JSON).
- `episodic/canonical/entity_protocols.py` — `EpisodeRepository`
  (`add`/`get`/`list_by_ids`; no update yet). Note `SeriesProfileRepository` and
  `EpisodeTemplateRepository` expose `update(entity)` mapping a field list via
  `_update_entity_fields` — match that convention.
- `episodic/canonical/pagination.py` — `Pagination`.
- `episodic/cost/recorder.py` — `CostRecorder`;
  `episodic/cost/storage/adapters.py` — `SqlAlchemyCostLedgerStore`.

Persistence:

- `episodic/canonical/storage/entity_models.py` — `EpisodeRecord`
  (around line 76; `tei_xml: Text` with sibling `tei_xml_zstd: BYTEA`
  compression; `content_hash` columns are `String(128)`), `TeiHeaderRecord`
  (around line 26, same compression pattern).
- `episodic/canonical/storage/entity_mappers.py` — `_episode_from_record`,
  `_episode_to_record`; `encode_text_for_storage`/`decode_text_from_storage`
  compression helpers.
- `episodic/canonical/storage/repositories.py` — `SqlAlchemyEpisodeRepository`
  (around line 176); `SeriesProfileRepository.update` (around line 137) is the
  `update`-convention exemplar.
- `episodic/canonical/storage/repository_base.py` — `_update_entity_fields`,
  `_update_where`.
- `episodic/canonical/storage/uow.py` — `SqlAlchemyUnitOfWork` (exposes
  `episodes`, `idempotency = SqlAlchemyIdempotencyStore(...)`,
  `workflow_checkpoints`; a `clock()` provider is threaded here).
- `episodic/canonical/storage/workflow_checkpoints.py` —
  `SqlAlchemyWorkflowCheckpointStore.save_or_reuse` (the DB-unique-constraint
  durable-idempotent primitive the launcher's convergence target uses).
- `alembic/` — migration environment and versioned migrations.

TEI and generation:

- `episodic/canonical/tei.py` — `parse_tei_header`.
- `episodic/generation/tei_payload.py` — `body_blocks_payload`,
  `build_text_inline`, payload validators.
- `episodic/generation/show_notes.py` — `enrich_tei_with_show_notes` (the
  `tei-rapporteur` parse → mutate body blocks → emit pattern to imitate).
- `episodic/generation/chapter_marker_tei.py` — shows the existing
  `uuid.uuid4().hex` id habit to AVOID for deterministic output.
- `episodic/canonical/services.py` — `ingest_sources`,
  `_create_canonical_episode` (construction helpers).
- `episodic/canonical/source_intake_service.py` — the 4.3.1 intake path and the
  `clock()`/`providers` injection convention.

Orchestration and LLM:

- `episodic/llm/ports.py` — `LLMPort`, `LLMRequest`, `LLMResponse`,
  `LLMUsage`, `LLMTokenBudget`, `ProviderCallUsage`, and the error hierarchy
  (`LLMTokenBudgetExceededError`, `LLMProviderResponseError`,
  `LLMTransientProviderError`).
- `episodic/llm/openai_api/adapter.py` — `OpenAICompatibleLLMAdapter` (retry,
  timeout, token budget).

HTTP API:

- `episodic/api/app.py` — `create_app` and the `_register_*` route functions.
- `episodic/api/runtime.py` — the composition root (`composition_root` group);
  `uow_factory` returns a fresh `SqlAlchemyUnitOfWork` per call; shutdown hooks
  call `engine.dispose`.
- `episodic/api/resources/base.py` — async resource base classes.
- `episodic/api/resources/source_intake.py` — representative idempotent and
  paginated resources.
- `episodic/api/serializers.py`, `episodic/api/errors.py`
  (`validation_error`, `RevisionConflictError`, `http_error`),
  `episodic/api/helpers.py` (`parse_uuid`, `require_payload_dict`,
  `require_str`), `episodic/api/dependencies.py` (`ApiDependencies`),
  `episodic/api/types.py` (`UowFactory = Callable[[], CanonicalUnitOfWork]`).
- `episodic/api/source_idempotency.py` — `run_idempotent`,
  `IdempotencyContext`, `IdempotentResponse` (currently stores only `status` +
  `media`), `apply_response`, `_encode_outcome`/`_decode_outcome`.
- `episodic/api/source_intake_support.py` — `json_body_hash` (note: this is the
  correct module for the hash helper).

Tests and fixtures:

- `tests/fixtures/database.py` (`session_factory`, `migrated_engine`,
  `pglite_session`), `tests/fixtures/api.py` (`build_api_dependencies`,
  `canonical_api_async_client`), `tests/fixtures/llm.py`, `tests/conftest.py`
  (`pytest_plugins`).
- `tests/show_notes_support.py` — `FakeLLMPort`, `valid_llm_response`.
- `tests/test_source_intake_api.py` — httpx `ASGITransport` end-to-end pattern.
- `tests/steps/test_guest_bios_steps.py`,
  `tests/steps/generation_orchestration_vidaimock.py` — existing Vidai Mock
  subprocess + skip helpers to extract and reuse.
- `tests/features/*.feature`, `tests/steps/test_*.py` — pytest-bdd pattern.
- `tests/__snapshots__/*.ambr` — syrupy snapshots (existing TEI snapshots use
  stable caller-supplied ids such as `xml:id="seg-intro"`).

### Terms

- TEI-P5: Text Encoding Initiative Guidelines, fifth edition; the canonical XML
  format for the episode script. Spoken script uses the Performance Texts
  module elements (`<sp>` speech, `<speaker>` label, `<u>` utterance, `<p>`/
  `<l>`/`<ab>` spoken blocks) within `<text><body>`.
- Generation run: a first-class resource representing one attempt to turn
  ingested source material into a script, with a status lifecycle and an
  append-only event log.
- Quality mode: the requested generation policy; the only value implemented in
  this slice is `draft_without_qa`, which skips QA and records `qa_status`
  `skipped`.
- Idempotency key: a client-supplied header making a side-effecting `POST`
  safe to retry; identical bodies replay the original response (status, body,
  `Location`, `Retry-After`), different bodies for the same key return
  `409 Conflict`.
- Long-running operation: an operation that may outlive its initiating request;
  returned as a pollable resource with `202 Accepted`, `Location`, and
  `Retry-After`. See [RFC 6129](https://datatracker.ietf.org/doc/html/rfc6129)
  for the TEI media type and the IBM Cloud / Microsoft long-running-operation
  guidance cited in ADR 009 for the polling pattern.

## Interfaces and dependencies

The following names must exist at the end of the listed milestone. Prefer these
exact names and paths. Every new `episodic/canonical/*` module must be added to
the matching `pyproject.toml` architecture-group prefix list (`domain_ports`
for pure domain/ports, `application` for services, `outbound_adapter` for
storage/adapters); `episodic/generation/*` and `episodic/canonical/storage/*`
may already be blanket-covered — verify and add prefixes if not.

### Domain (Milestone 1) — `episodic/canonical/`

In `episodic/canonical/generation_quality.py` (new, `domain_ports` group, pure):

```python
import enum


class QualityMode(enum.StrEnum):
    """Requested generation quality policy for a run."""

    DRAFT_WITHOUT_QA = "draft_without_qa"


class QaStatus(enum.StrEnum):
    """Recorded QA outcome for a run and the TEI it produced."""

    SKIPPED = "skipped"
```

Extend `GenerationRun` in `episodic/canonical/domain.py` with three fields
(defaults chosen to minimize construction-site churn) and validation:

```python
quality_mode: QualityMode = QualityMode.DRAFT_WITHOUT_QA
qa_status: QaStatus | None = None
skip_qa_rationale: str | None = None
```

Validation in `__post_init__` (or a validating factory): when
`quality_mode is QualityMode.DRAFT_WITHOUT_QA`, `qa_status` must be
`QaStatus.SKIPPED` and `skip_qa_rationale` must be a non-empty string. Update
the ~5 `GenerationRun(` construction sites and the in-memory adapter, and
regenerate `tests/__snapshots__/test_generation_run_domain.ambr`.

### Generation-run persistence (Milestone 2a) — `episodic/canonical/storage/`

- `GenerationRunRecord` and `GenerationEventRecord` SQLAlchemy models
  (`generation_runs`, `generation_events` tables) in a new
  `episodic/canonical/storage/generation_run_models.py`. `generation_runs`
  carries the lifecycle columns plus `started_at` (indexed), `ended_at`,
  `error_message`, `error_category`, and `lease_expires_at` (nullable; reserved
  for the 2.6.2 reaper). `generation_events` enforces a unique
  `(generation_run_id, seq)` and allocates `seq` per run.
- `SqlAlchemyGenerationRunStore` implementing `GenerationRunRepository` and
  `GenerationEventLog` (not `GenerationCheckpointPort`; checkpoints are out of
  scope) in `episodic/canonical/storage/generation_runs.py`.
  `update_run_status` for `pending → running` MUST be a conditional update
  (`UPDATE … SET status='running' WHERE id=:id AND status='pending'`) returning
  whether it won, so only one worker proceeds.
- `SqlAlchemyUnitOfWork` exposes `generation_runs` (run repository + event log)
  so handlers and the launcher share one transaction boundary; mirror the
  existing `workflow_checkpoints` attribute pattern.
- An Alembic migration creating the two tables, reversible, passing
  `make check-migrations`.

### Episode TEI revisioning (Milestone 2b) — `episodic/canonical/`

- Episode columns added to `EpisodeRecord` and mirrored on `CanonicalEpisode`
  (with defaults): `tei_revision: int = 0`, `tei_content_hash: str | None`
  (`String(128)`), `qa_status: str | None`,
  `last_generation_run_id: uuid.UUID | None`.
- `EpisodeRepository.update(self, episode, *, expected_revision: int)` added to
  the protocol and implemented via a conditional `_update_where`
  (`WHERE tei_revision = :expected_revision`), raising a revision-conflict
  domain error on mismatch (the launcher is the sole writer and passes the
  current revision). The update path MUST re-run `encode_text_for_storage` when
  it rewrites `tei_xml` so the compressed and plain columns stay in sync.
- An Alembic migration adding the four episode columns, reversible.

### Generation (Milestone 3) — `episodic/generation/` and `episodic/canonical/`

In `episodic/generation/draft_script.py` (new):

```python
class DraftScriptGenerator(typing.Protocol):
    async def generate(
        self, request: DraftScriptRequest
    ) -> DraftScriptResult: ...
```

- `DraftScriptRequest` carries the source material (normalized text or source
  TEI), presenter profiles (host/guest reference-document revisions), the
  episode/series identifiers, and an injected `clock()` plus a deterministic id
  factory (sequential `sp-1`, `p-1`, …) so output is reproducible.
- `DraftScriptResult` carries the emitted TEI-P5 XML, the content hash (bare
  SHA-256 hex; the envelope adds any `sha256:` prefix — pin one and snapshot
  it), and the LLM `LLMUsage`/`ProviderCallUsage` for cost accounting.
- `LLMDraftScriptGenerator` is the single-pass implementation using `LLMPort`;
  it builds TEI via `tei-rapporteur` `from_dict`/`emit_xml` using ADR-006
  spoken containers (`<text><body>` with `<sp><speaker/>…<p/></sp>` turns),
  validates the result, and maps each `LLMError` subclass to a typed failure.

In `episodic/canonical/generation_persistence.py` (new, `application` group):

- `materialise_episode_from_ingestion(...)` creates the episode from the
  ingestion job's attached sources with a minimal placeholder TEI header
  (reusing `_create_canonical_episode`/`TeiHeader` construction), returning the
  episode id; called before the run is launched.
- `persist_draft_script(...)` writes the generated TEI into the episode within
  one unit of work: increments `tei_revision` (optimistic), sets
  `tei_content_hash`, sets `qa_status='skipped'`, and sets
  `last_generation_run_id`. Validation failure raises a typed error the
  launcher maps to `run.failed` + `tei.invalid`.

### Launcher (Milestone 4) — `episodic/generation/`

```python
class GenerationRunLauncher(typing.Protocol):
    async def launch(self, run_id: uuid.UUID) -> None: ...
```

`InProcessGenerationRunLauncher` (placed in `episodic/generation/`, the
`application` group; the concrete is constructed in `episodic/api/runtime.py`
and injected via a new `ApiDependencies.launcher: GenerationRunLauncher | None`
field). It:

- accepts `uow_factory`, the `DraftScriptGenerator`, the persistence service, a
  `CostRecorder`, a `clock()`, a bounded-concurrency semaphore, and a task
  registry (strong references) drained by a shutdown hook;
- per launched task opens its OWN fresh unit of work (never the request's);
- performs the conditional `pending → running` transition (skips if it did not
  win);
- captures the correlation id at schedule time and binds it to the task's
  logging context (it runs outside the request context);
- generates, persists, and records cost in-transaction; appends lifecycle
  events (`run.started`, `draft.generated`, `tei.persisted`, `run.succeeded`);
- wraps generation AND persistence AND validation in one try/except mapping any
  exception to `run.failed` + `error_message` + `error_category` + a terminal
  status, emitting `run.failed` (and `tei.invalid` for validation failures),
  mapping each `LLMError` subclass to a stable classified message;
- on shutdown drain, marks still-running drained runs `failed`.

The launcher is a driven port so a Celery adapter replaces it later without
touching the REST or domain layers; the new ADR documents it as a degenerate
`TaskResumePort`.

### HTTP API (Milestones 5–6) — `episodic/api/`

New resources, wired by a new `_register_generation_run_routes` and
`_register_episode_tei_routes` in `episodic/api/app.py`:

- `POST /v1/episodes/{episode_id}/generation-runs` — `GenerationRunsResource`.
  Body: required `quality_mode`, `skip_qa_rationale`, `actor`; optional
  accepted-and-ignored `template_id`, `prompt_overrides`, `budget_hints` (do not
  `400` on them; round-trip them into `configuration`/`budget_snapshot` so
  they survive). Validation: missing/blank rationale or malformed body → `400`;
  recognized-but-unsupported `quality_mode` → `422`. Returns `202` with
  `Location: /v1/generation-runs/{run_id}` and `Retry-After`. The handler
  creates the run row AND schedules the launcher inside one `work()`;
  scheduling failure marks the run `failed`.
- `GET  /v1/generation-runs/{run_id}` — `GenerationRunResource` (run snapshot;
  `Retry-After` while non-terminal).
- `GET  /v1/generation-runs/{run_id}/events` — `GenerationRunEventsResource`
  (`after_seq` cursor + `limit` cap; `offset` deliberately omitted in favour of
  the cursor).
- `GET  /v1/episodes/{episode_id}/tei` — `EpisodeTeiResource`.

Idempotency replay fix (Milestone 5): `IdempotentResponse` is extended with
optional `location` and `retry_after`; `_encode_outcome`/`_decode_outcome`
persist them and `apply_response` sets the headers, so a replayed/in-flight
`202` carries `Location` and `Retry-After` as ADR 009 requires. Reuse
`json_body_hash` from `episodic/api/source_intake_support.py` (not
`source_idempotency.py`) and a new operation constant `generation_run.create`.

New serializers in `episodic/api/serializers.py`: `serialize_generation_run`,
`serialize_generation_event`, `serialize_tei_envelope`. The TEI envelope maps
internal `tei_revision → version` and `tei_content_hash → content_hash`, and
exposes `episode_id`, `tei_header_id`, `tei_xml`, `content_hash`, `version`,
`last_generation_run_id`, `quality_mode`, `qa_status`, and `updated_at`. A
content negotiation helper `negotiate_tei_media_type` in
`episodic/api/helpers.py`; the `tei+xml` response sets
`Content-Type: application/tei+xml` and
`Content-Disposition: attachment; filename="episode-<id>.xml"`, and an `ETag`
derived from `tei_content_hash` for conditional GETs.

## Plan of work

Each milestone follows Red-Green-Refactor and ends with the relevant quality
gates. Do not proceed to the next milestone if the current gate fails. Commit
after each green-plus-refactor cycle.

### Milestone 0 — Branch, plan baseline, red end-to-end scaffold

Stage A: rename the working branch (see `Concrete steps`) and commit this
ExecPlan.

Stage B (red): add a strict-xfail end-to-end behavioural feature
`tests/features/no_qa_generation_slice.feature` and a step module
`tests/steps/test_no_qa_generation_slice.py` whose scenarios express the whole
slice, bound with
`@pytest.mark.xfail(strict=True, reason="4.3.2 not implemented")` so
`make test` stays green while the target behaviour is captured. This is the
executable definition of done; the markers are removed in Milestone 7.

The feature (full text embedded here so the plan is self-contained):

```gherkin
Feature: No-QA source-to-script generation slice

  As an integration client
  I want to generate a draft script without QA and download the TEI
  So that I can validate the source-to-script workflow over REST

  Background:
    Given a Vidai Mock inference server is running
    And a series profile exists
    And a host presenter profile and a guest presenter profile are bound

  Scenario: Draft generation without QA produces a downloadable TEI-P5 script
    Given an ingestion job with an attached source document
    When I create a draft-without-qa generation run for the ingested episode
    Then the run creation responds 202 Accepted with a Location header
    And the response carries a Retry-After header
    And the run is created with qa_status "skipped" and my rationale recorded
    When I poll the generation run until it reaches a terminal state
    Then the run status is "succeeded"
    And the event log contains a "tei.persisted" event
    When I fetch the episode TEI as application/tei+xml
    Then the response is a TEI-P5 attachment with qa_status "skipped"
    And the TEI validates against the Episodic TEI-P5 profile

  Scenario: Reusing an idempotency key with the same body replays the run
    Given an ingestion job with an attached source document
    When I create a draft-without-qa run twice with the same idempotency key and body
    Then both responses describe the same run id
    And the replayed response carries the same Location and Retry-After

  Scenario: Reusing an idempotency key with a different body conflicts
    Given an ingestion job with an attached source document
    When I create a draft-without-qa run, then reuse the key with a different rationale
    Then the second response is 409 Conflict

  Scenario: A missing rationale is rejected
    Given an ingestion job with an attached source document
    When I create a draft-without-qa run without a skip_qa_rationale
    Then the response is 400 Bad Request

  Scenario: An unsupported quality mode is unprocessable
    Given an ingestion job with an attached source document
    When I create a generation run with quality_mode "qa_gated"
    Then the response is 422 Unprocessable Entity

  Scenario: Generation failure is reported on the run
    Given an ingestion job with an attached source document
    And the inference server is configured to fail
    When I create a draft-without-qa generation run for the ingested episode
    And I poll the generation run until it reaches a terminal state
    Then the run status is "failed"
    And the run records an error message and an error category

  Scenario: A malformed completion is reported as a failed run
    Given an ingestion job with an attached source document
    And the inference server is configured to return a non-TEI completion
    When I create a draft-without-qa generation run for the ingested episode
    And I poll the generation run until it reaches a terminal state
    Then the run status is "failed"
    And the event log contains a "tei.invalid" event
```

Gate: `make check-fmt && make typecheck && make lint && make test` (the new
scenarios are xfail, so the suite stays green). Commit.

### Milestone 1 — Domain model extensions

Red: extend `tests/test_generation_run_domain.py` asserting the new
`QualityMode`/`QaStatus` enums and that a `draft_without_qa` run with an empty
rationale raises `ValueError`, and that a valid run round-trips its new fields.
Run; observe failure.

Green: add `episodic/canonical/generation_quality.py`, extend `GenerationRun`
with the three fields and validation, export from
`episodic/canonical/__init__.py`, update the construction sites and the
in-memory adapter, and add the new module to the `domain_ports` prefix list in
`pyproject.toml`.

Refactor: regenerate `tests/__snapshots__/test_generation_run_domain.ambr`;
confirm `make lint` (`make check-architecture`) passes.

Gate: `make check-fmt && make typecheck && make lint && make test`. Commit.

### Milestone 2a — Durable generation-run and event persistence

Red: add persistence tests under `tests/canonical_storage/`:

- `SqlAlchemyGenerationRunStore` round-trips a run, lists runs by episode with
  pagination and status filter, appends events with monotonically increasing
  `EventSeq` (unique per run), and lists events `after_seq`.
- the conditional `pending → running` update wins exactly once when called
  twice concurrently (simulate by two sequential guarded updates; the second
  reports it did not win).

Add a Hypothesis property test: appending N events in arbitrary interleavings
yields strictly increasing seqs and an `after_seq` pagination that partitions
the log with no gaps or duplicates.

Green: add `generation_run_models.py`, the `generation_runs.py` store, the
`SqlAlchemyUnitOfWork.generation_runs` attribute, the Alembic migration, and the
`outbound_adapter`/`storage` prefix entries if needed. Verify the durable
`SqlAlchemyIdempotencyStore` is already wired on the unit of work; if absent,
escalate per Tolerances.

Gate:

```bash
make check-fmt
make typecheck
make lint
make check-migrations
make test
```

Commit.

### Milestone 2b — Episode TEI revisioning columns and optimistic update

Red: add `tests/canonical_storage/` tests asserting that the episode TEI
`update` increments `tei_revision`, stores `tei_content_hash`, sets `qa_status`
and `last_generation_run_id`, keeps the zstd-compressed column in sync, is
visible in a fresh unit of work, and raises a revision-conflict error when
`expected_revision` does not match. Run; observe failure.

Green: add the four episode columns and mappers, the
`EpisodeRepository.update(..., expected_revision=...)` method (conditional
`_update_where`, re-encoding `tei_xml`), and an additive reversible migration.

Gate: full Python gates including `make check-migrations`. Commit.

### Milestone 3 — Draft script generator, episode materialization, persistence

Red: add unit tests in `tests/test_draft_script_generation.py` using
`FakeLLMPort` returning a canned script-shaped payload, an injected frozen
clock, and the deterministic id factory. Assert the generator emits TEI-P5 that
`tei-rapporteur` parses and validates, contains the expected `<sp>`/`<speaker>`/
`<p>` turns, and reports a stable content hash; add a syrupy snapshot of the
emitted TEI XML (clock frozen, ids pinned). Add tests for each `LLMError`
subclass mapping to a typed failure. Add tests for
`materialise_episode_from_ingestion` (creates episode + placeholder TEI from an
ingestion job) and `persist_draft_script` (episode TEI, revision, hash,
`qa_status`, `last_generation_run_id`; invalid TEI raises the typed error).

Green: implement `DraftScriptGenerator`/`LLMDraftScriptGenerator`
(`episodic/generation/draft_script.py`) and
`episodic/canonical/generation_persistence.py`; add prefix entries.

Refactor: extract shared TEI-construction helpers into
`episodic/generation/tei_payload.py`; keep generator pure of HTTP/DB.

Gate: full Python gates. Commit.

### Milestone 4 — Launcher, lifecycle events, cost wiring, observability

Red: add tests in `tests/test_generation_run_launcher.py`:

- a logic test driving the launcher to completion against a persisted `pending`
  run and a `FakeLLMPort`, asserting status transitions, appended event kinds
  in order, persisted TEI, and recorded cost-ledger entry;
- a failure test asserting an LLM error and an invalid-TEI case each yield
  `failed` with `error_message`/`error_category`, `run.failed`, and (for
  invalid TEI) a `tei.invalid` event — not a leaked exception;
- a **detached-session** test that launches through real `asyncio.create_task`
  against py-pglite and asserts the task writes through its own session while a
  request-scoped unit of work is already closed;
- a shutdown-drain test asserting a still-running drained run is marked
  `failed`.

Green: implement `InProcessGenerationRunLauncher`; construct it plus a
`CostRecorder` over `SqlAlchemyCostLedgerStore` in `episodic/api/runtime.py`;
add the `ApiDependencies.launcher` field; bind the correlation id and emit the
ADR-009-required structured logs and metrics (draft latency, terminal-state
counters, draft error rate by category, QA-bypass rate; idempotency
replay/conflict counters are emitted in M5).

Refactor: ensure the launcher depends only on ports (run store, event log,
generator, persistence, cost recorder, clock), holds strong task references,
and bounds concurrency with a semaphore.

Gate: full Python gates. Commit.

### Milestone 5 — Generation-run REST endpoints with idempotency

Red: add endpoint tests in `tests/test_generation_run_api.py` using
`canonical_api_async_client` + httpx `ASGITransport` (mirror
`tests/test_source_intake_api.py`): valid create → `202` + `Location` +
`Retry-After`, records `qa_status=skipped` and rationale, and triggers the
launcher; missing rationale → `400`; `quality_mode="qa_gated"` → `422`;
`GET /generation-runs/{id}` → snapshot + `Retry-After` while non-terminal;
`GET /generation-runs/{id}/events` paginates by `after_seq`/`limit`; an
idempotent replay returns the same run id AND the same `Location`/
`Retry-After`; a different body with the same key → `409`.

Add Hypothesis property tests for idempotency invariants against the in-memory
`IdempotencyStore`/`run_idempotent` (fast, pure): identical body + same key
never creates more than one run; different body + same key → `409`; in-flight
duplicates return the stored `202` metadata including `Location`/`Retry-After`.
Cover the SQL adapter with a couple of example-based tests only (avoid
Hypothesis × py-pglite flake).

Green: extend `IdempotentResponse` with `location`/`retry_after` and update
`_encode_outcome`/`_decode_outcome`/`apply_response`; implement the three
resources, serializers, and route registration; reuse `run_idempotent`/
`IdempotencyContext` and `json_body_hash` (from `source_intake_support`).
Inject the launcher and clock via `ApiDependencies`. Emit idempotency
replay/conflict metrics.

Refactor: keep resources thin (parse → service/port → serialize); map domain
errors through the existing error-envelope helpers.

Gate: full Python gates. Commit.

### Milestone 6 — Episode TEI retrieval with content negotiation

Red: add tests in `tests/test_episode_tei_api.py`: default `GET .../tei`
returns the JSON envelope (with the `tei_revision → version`,
`tei_content_hash → content_hash` mapping and a stable, snapshotted shape under
a frozen clock); `Accept: application/tei+xml` returns the raw TEI-P5 body with
`Content-Type: application/tei+xml`,
`Content-Disposition: attachment; filename="episode-<id>.xml"`, and an `ETag`;
a request before any draft exists returns `404`.

Green: implement `EpisodeTeiResource`, `negotiate_tei_media_type`, and
`serialize_tei_envelope`; register the route.

Refactor: factor the content-negotiation helper for reuse; document it in the
developers' guide (Milestone 8).

Gate: full Python gates. Commit.

### Milestone 7 — End-to-end behavioural slice with Vidai Mock

Red→Green: implement the Milestone 0 step module and remove the xfail markers.
Extract the existing Vidai Mock subprocess helpers (`_start_vidaimock_process`,
`_await_port_ready`, `_terminate_process_gracefully`, and the `shutil.which`
skip) from `tests/steps/test_guest_bios_steps.py` into a shared
`tests/fixtures/` module and reuse them. Configure a provider template
returning a deterministic TEI-script-shaped completion; use
`X-Vidai-Chaos-Drop: 100` for the failure scenario and a non-TEI completion
template for the malformed-completion scenario. Drive the full flow with the
async HTTP client.

Acceptance gate (not optional): the slice's headline scenario MUST be observed
passing at least once on a host where `vidaimock` is available; capture that
transcript in `Artefacts and notes`. The graceful `shutil.which` skip keeps CI
green where the binary is absent, but the plan is not done until the green
transcript exists. Record where CI obtains the `vidaimock` binary.

Gate: full Python gates including the now-active scenarios. Commit.

### Milestone 8 — Documentation, roadmap update, final gates

1. Add `docs/adr/adr-016-no-qa-generation-run-execution-and-tei-persistence.md`
   recording: the in-process launcher port (a degenerate `TaskResumePort`) and
   the Celery deferral, the single-worker assumption and stuck-run hooks (lease
   columns, conditional transitions, stuck-run gauge, manual-fail runbook),
   episode materialization from ingestion, the `DraftScriptGenerator` port and
   its 4.4.1 successor, episode TEI revisioning and optimistic update, the
   422-vs-400 and 404 contract decisions, and the content-negotiation approach.
   Reference it from ADR 009 and the system design.
2. Update `docs/episodic-podcast-generation-system-design.md`
   (source-to-script vertical slice) with the implemented decisions.
3. Update `docs/users-guide.md` with the trigger → poll → download workflow,
   the `Accept: application/tei+xml` download, and the draft/QA-skipped caveat.
4. Update `docs/developers-guide.md` with the content-negotiation helper, the
   generation-run launcher seam and its lifecycle/observability conventions,
   and the Vidai Mock test harness; add new modules to
   `docs/repository-layout.md` and index new docs in `docs/contents.md`.
5. Mark roadmap item 4.3.2 as done in `docs/roadmap.md`.

Gate:

```bash
make check-fmt
make typecheck
make lint
make check-migrations
make test
make markdownlint
make nixie
```

Commit.

## Concrete steps

Run all commands from the repository root
(`/home/leynos/.lody/repos/github---leynos---episodic/worktrees/7cb51da6-204f-4329-8dfd-ca46598e888c`).

Branch rename and tracking (Milestone 0):

```bash
git branch -m 4-3-2-no-qa-generation-runs-and-tei-p5-retrieval
git push -u origin 4-3-2-no-qa-generation-runs-and-tei-p5-retrieval
```

Quality gates (run sequentially to benefit from build caching; never in
parallel), teeing output for review:

```bash
make check-fmt 2>&1 | tee /tmp/check-fmt-$(git branch --show-current).out
make typecheck 2>&1 | tee /tmp/typecheck-$(git branch --show-current).out
make lint 2>&1 | tee /tmp/lint-$(git branch --show-current).out
make check-migrations 2>&1 | tee /tmp/check-migrations-$(git branch --show-current).out
make test 2>&1 | tee /tmp/test-$(git branch --show-current).out
```

Markdown gates (run unsandboxed where required; see the memory note on nixie):

```bash
make markdownlint 2>&1 | tee /tmp/markdownlint-$(git branch --show-current).out
make nixie 2>&1 | tee /tmp/nixie-$(git branch --show-current).out
```

Vidai Mock for behavioural tests (Milestone 7):

```bash
command -v vidaimock   # confirm the binary is available before expecting M7 to run
```

Run a single focused test during Red-Green:

```bash
uv run pytest tests/test_generation_run_api.py -k idempotency -x -q
```

Expected transcripts (illustrative until captured for real in Artefacts):

```plaintext
$ uv run pytest tests/steps/test_no_qa_generation_slice.py -q   # M0 (red, before impl)
XFAIL tests/steps/test_no_qa_generation_slice.py::test_draft_generation ...
N xfailed in N.Ns
```

```plaintext
$ uv run pytest tests/steps/test_no_qa_generation_slice.py -q   # M7 (green, vidaimock present)
N passed in N.Ns
```

## Validation and acceptance

The slice is done when:

- `make check-fmt`, `make typecheck`, `make lint`, `make check-migrations`,
  `make test`, `make markdownlint`, and `make nixie` all pass.
- The behavioural scenarios in `tests/features/no_qa_generation_slice.feature`
  pass, and the headline scenario has been **observed passing at least once**
  with a `vidaimock` binary present (transcript captured in
  `Artefacts and notes`). The `shutil.which` skip only protects binary-less CI;
  it does not satisfy the acceptance gate.
- Manually, against a running service with a Vidai Mock backend:
  `POST /v1/episodes/{episode_id}/generation-runs` with
  `{"quality_mode":"draft_without_qa","skip_qa_rationale":"vertical-slice demo","actor":"editor@example.test"}`
  and an `Idempotency-Key` returns `202 Accepted` with
  `Location: /v1/generation-runs/{run_id}` and `Retry-After`; polling
  `GET /v1/generation-runs/{run_id}` reaches `succeeded`;
  `GET /v1/generation-runs/{run_id}/events` shows a `tei.persisted` event; and
  `GET /v1/episodes/{episode_id}/tei` with `Accept: application/tei+xml`
  downloads a TEI-P5 attachment with `qa_status=skipped`. Replaying the same
  request returns the same run id with the same `Location`/`Retry-After`; a
  different body with the same key returns `409`.

Red-Green-Refactor evidence must be recorded per milestone: the focused test
command and its red failure (the M0 scenarios use
`@pytest.mark.xfail(strict=True, ...)` to prove the red stage; markers removed
in M7), the green pass after the minimal change, and the wider-gate pass after
refactor.

Quality criteria:

- Tests: unit (`pytest`), behavioural (`pytest-bdd`), snapshot (`syrupy` for TEI
  XML and the JSON envelope, with a frozen clock and pinned ids), and property
  (`hypothesis` for idempotency invariants and event-seq
  monotonicity/pagination) all pass. CrossHair (`make crosshair`) is only
  extended if a new pure PEP-316-contracted helper is introduced (e.g. a
  content-hash or revision-increment helper); otherwise it is unchanged.
- Observability: the ADR-009-required structured logs, metrics, and
  correlation-id propagation across the asyncio boundary are present and
  asserted in M4/M5 tests.
- Lint/typecheck/migrations: `make lint` (incl. `make check-architecture`),
  `make typecheck`, and `make check-migrations` clean.

Verification method: run the gate commands after each milestone and run
`coderabbit review --agent`, clearing all concerns, before moving on.
CodeRabbit must only see code that already passes the deterministic gates.

### Verification note (Rust/Verus and Kani)

ADR 009 anticipates Kani/Verus only "if the idempotency state machine moves
into Rust". This slice keeps idempotency in Python (reusing the existing
`IdempotencyStore` and `run_idempotent`), so no Rust extension or formal proof
is introduced; the idempotency invariants are covered by Hypothesis property
tests. If a future task moves the state machine to Rust, add the bounded model
checking then.

## Idempotence and recovery

- Re-running any gate command is safe and idempotent.
- Database tests reset the `public` schema per test via the py-pglite fixtures.
- Alembic migrations must be reversible (`downgrade` drops the added columns and
  tables); verify with an upgrade/downgrade/upgrade cycle locally.
- Generation-run creation is idempotent by `Idempotency-Key`; retrying with the
  same key and body returns the original run with its stored `Location` and
  `Retry-After`.
- `pending → running` is a conditional update so only one worker proceeds; the
  episode TEI write is optimistic on `tei_revision`. This prevents double-spend
  and clobbering if a future reaper re-launches.
- If the service restarts mid-run, the run may remain `running` (no automated
  reaper in this slice). The `started_at`/`lease_expires_at` columns and the
  startup stuck-run gauge make this state recoverable and alertable; the
  manual-fail runbook (in ADR 016 / developers' guide) describes how to fail a
  stuck run and its idempotency record. The automated reaper is a 2.6.2
  follow-up.
- Known limitation: a `pending`/`running` run that outlives the 24h idempotency
  TTL could let a replayed key create a second run; documented for the 2.6.2
  recovery work.

## Artefacts and notes

Capture as work proceeds: the M0 red xfail transcript; the M2a/M2b
`make check-migrations` clean output; the M3 emitted-TEI snapshot diff; the M4
detached-session test transcript; and the M7 green behavioural-slice transcript
on a `vidaimock`-equipped host (mandatory acceptance evidence).

- M0 red scaffold evidence (2026-06-24):

  ```plaintext
  $ uv run pytest tests/steps/test_no_qa_generation_slice.py -q
  xxxxxxx                                                                  [100%]
  7 xfailed in 0.48s
  ```

- M0 deterministic gate evidence (2026-06-24):
  `make check-fmt` reported `420 files already formatted`; `make typecheck`
  reported `All checks passed!`; `make lint` passed Hecate and Ruff and rated
  Pylint `10.00/10`; `make test` reported
  `962 passed, 2 skipped, 7 xfailed in 74.14s`; `make markdownlint` reported
  `Summary: 0 error(s)`; and `make nixie` reported all diagrams validated.

- M0 CodeRabbit evidence (2026-06-24):
  `coderabbit review --agent` ended with
  `{"type":"complete","status":"review_completed","findings":0}`.

- M1 red evidence (2026-06-24):

  ```plaintext
  E   ModuleNotFoundError: No module named
  E   'episodic.canonical.generation_quality'
  ```

- M1 focused green evidence (2026-06-24):

  ```plaintext
  $ uv run pytest tests/test_generation_run_domain.py \
      tests/test_generation_run_port_contract.py \
      tests/test_generation_run_properties.py \
      tests/steps/test_generation_run_lifecycle_steps.py -q
  ......................................                                   [100%]
  38 passed in 1.43s
  ```

- M1 deterministic gate evidence (2026-06-24):
  `make check-fmt` reported `421 files already formatted`; `make typecheck`
  reported `All checks passed!`; `make lint` passed Hecate and Ruff and rated
  Pylint `10.00/10`; `make test` reported
  `966 passed, 2 skipped, 7 xfailed in 68.44s`; `make markdownlint` reported
  `Summary: 0 error(s)`; and `make nixie` reported all diagrams validated.

- M1 CodeRabbit evidence (2026-06-24): the first review attempt returned a
  recoverable `rate_limit` response; after the required `vsleep` backoff, the
  retry ended with
  `{"type":"complete","status":"review_completed","findings":0}`.

- M2a red evidence (2026-06-24):

  ```plaintext
  E   ImportError: cannot import name 'GenerationEventRecord' from
  E   'episodic.canonical.storage'
  ```

- M2a focused green evidence (2026-06-24):

  ```plaintext
  $ uv run pytest tests/canonical_storage/test_generation_runs.py -q
  ........                                                                 [100%]
  8 passed in 3.53s

  $ uv run pytest tests/test_generation_run_port_contract.py \
      tests/test_generation_run_properties.py -q
  .................                                                        [100%]
  17 passed in 0.68s

  $ uv run pytest tests/canonical_storage/test_generation_runs.py \
      tests/test_generation_run_port_contract.py \
      tests/test_generation_run_properties.py \
      tests/steps/test_generation_run_lifecycle_steps.py -q
  .............................                                            [100%]
  29 passed in 4.29s
  ```

- M2a migration gate evidence (2026-06-24): `make check-migrations` applied
  migrations through `20260624_000010` and exited cleanly with no schema drift
  reported.

- M2a deterministic gate evidence (2026-06-24): `make check-fmt` reported
  `426 files already formatted`; `make typecheck` reported `All checks passed!`;
  `make lint` passed Hecate and Ruff and rated Pylint `10.00/10`; `make test`
  reported `975 passed, 2 skipped, 7 xfailed in 73.81s`; and
  `make check-migrations` exited cleanly after applying migrations through
  `20260624_000010`.

- M2a CodeRabbit evidence (2026-06-24): `coderabbit review --agent` ended with
  `{"type":"complete","status":"review_completed","findings":0}`.

## Outcomes & retrospective

To be completed at major milestones and at the end. Compare the delivered
behaviour against the Purpose section, record gaps handed to 2.6.2 / 2.6.3 /
4.4.1 (durable checkpoints and the automated stuck-run reaper, the full
generation-run and checkpoint REST surface, the QA-bypass draft graph), and
note what would be done differently.

## Revision note

Revised 2026-06-15 after a Logisphere community-of-experts design review.
Changes: split Milestone 2 into 2a (runs/events) and 2b (episode TEI columns)
to respect the file/line tolerance; made the launcher own a fresh unit of work
(use-after-free fix) with a dedicated detached-session test; added durable
stuck-run hooks (indexed `started_at`, `lease_expires_at`, `error_category`,
conditional `pending → running`, optimistic TEI update, startup stuck-run
gauge); extended idempotency replay to carry `Location`/`Retry-After`;
corrected the `json_body_hash` module path and added the
`generation_run.create` operation; specified the request-body required/optional
split and the 422-vs-400 and 404 contract decisions; made cost-recorder wiring
an explicit deliverable; specified deterministic TEI ids and clock injection
for stable snapshots; clarified that episode materialization is a new step (not
pure reuse); mandated `pyproject.toml` architecture-group registration for new
modules; broadened LLM-failure and malformed-completion handling and tests;
required observability acceptance; and turned the Vidai Mock skip into a
must-run-once acceptance gate reusing existing helpers. These strengthen
correctness and operability without enlarging the externally observable
contract.
