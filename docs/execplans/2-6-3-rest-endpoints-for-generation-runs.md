# Implement REST endpoints for generation runs

This ExecPlan is a living document. Keep Constraints, Tolerances, Risks,
Progress, Surprises & discoveries, Decision log, Outcomes & retrospective,
Conformance basis, and Verification plan current throughout delivery.

Status: DRAFT. This change delivers the plan; implementation requires approval.

## Purpose / big picture

Complete roadmap item 2.6.3 so authenticated clients can create another draft
for an existing episode, list their generation runs, inspect progress and
submit a durable human review response. A successful demonstration creates an
initial episode through ingestion, regenerates the same episode through the new
REST (Representational State Transfer) collection, replays creation without
duplicating inference, and retrieves an ordered event history. A separate
review scenario submits a checkpoint and observes its response event.

Existing ingestion-job creation, run retrieval, and event retrieval already
work. This plan completes those surfaces rather than replacing the launcher.
Quality assurance (QA) execution, WebSocket delivery, automatic checkpoint
resumption, and applying review patches are outside this task.

## Constraints

- Preserve inward dependencies. Domain values and application policy must not
  import Falcon, SQLAlchemy, HTTP resources, Celery, or outbound adapters.
  Ports return domain types. Compose infrastructure at the existing runtime
  boundary; never call one HTTP resource from another.
- Preserve the existing ingestion-job creation workflow, run and event wire
  shapes, trusted bearer-principal attribution, and resource-level concealment
  of inaccessible records. Authentication middleware retains its own 401/403
  policy. Request bodies cannot choose an actor.
- Reuse the existing run, event, review-checkpoint, idempotency, unit-of-work,
  and launcher contracts. A unit of work owns one transaction. No new database
  table, dependency, worker scheduler, or inference provider is planned.
- Retain review-checkpoint compare-and-set transitions: an update succeeds
  only while stored status is `created`. Keep review checkpoints distinct from
  LangGraph `WorkflowCheckpoint` records.
- Keep code files at or below 400 lines, use typed commands and NumPy-style
  public docstrings, and avoid compatibility wrappers for internal APIs.
- Use Vidai Mock for inference behavioural tests. No paid provider calls or
  provider credentials are needed. Use existing PostgreSQL-compatible test
  fixtures for persistence, with their concurrency limitation stated below.
- Keep roadmap 2.6.3 unchecked until implementation acceptance is complete.
  Do not absorb roadmap 2.6.4–2.6.10 follow-ups into this task.
- Run formatting, format checks, type checking, lint, and tests sequentially.
  Delegate full gates to the scrutineer agent, retaining terminal exit status
  and logs. Commit only validated coherent changes.

## Tolerances (exception triggers)

Proceed milestone by milestone after approval. Stop and record a proposed
change if delivery needs a schema migration, a new dependency, new ownership
rules outside generation-run collections, additional quality modes, workflow
resumption, or replacement of the launcher. These would change the approved
architecture or scope. Also escalate if a milestone exceeds 25 non-ExecPlan
files or 1,500 net added lines, or the whole implementation exceeds 45 files or
3,000 net added lines. ExecPlan files are excluded from both counts; other code
and documentation count. There is no time limit.

Mechanical naming and test-file splits within these limits need no approval. If
the chosen contract cannot be implemented, set Status to BLOCKED, record
options and upstream/downstream impacts in Decision log, and obtain acceptance
of the deviation. Do not loosen assertions or suppress diagnostics to proceed.

## Risks

Ownership is a high-impact risk: an episode's `last_generation_run_id` is set
only after successful draft persistence. Reusing that predicate for collection
reads would hide initial pending and failed runs. Use actor-owned run existence
for collection access; retain the narrower predicate for regeneration.

Idempotency has two persistence levels: HTTP response replay expires after 24
hours, while run-key deduplication persists. Bind targets explicitly and
compare durable request meaning on reuse. Do not describe the transport helper
as providing exactly-once execution across arbitrary process crashes.

Checkpoint response and event persistence can diverge if committed separately.
Stage both in one transaction with run-before-checkpoint locking. Refresh the
SQLAlchemy identity map at the locking read. PGlite cannot establish real
multi-session lock behaviour; require the focused PostgreSQL experiment below.

Episode list status can change between reads. Deterministic ordering does not
make offset pages or a separate count a consistent snapshot. Document that
limitation and avoid introducing a snapshot token protocol.

The no-QA launcher does not create human review checkpoints. Seed these through
the domain port in REST acceptance tests; do not invent QA orchestration to
make the test possible. Review patches are recorded data, not executable patch
instructions.

## Progress

- [x] (2026-11-08) Renamed the branch and inspected the baseline and
      instructions.
- [x] (2026-11-08) Completed three Wyvern reconnaissance assignments covering
  runtime code, documented contracts, and verification infrastructure.
- [x] (2026-11-08) Reviewed the proposal through all six community-of-experts
  lenses and incorporated ownership, idempotency, and transaction corrections.
- [x] (2026-11-08) Prepared the reviewed plan, proposed ADR, and design
  references for gated draft publication.
- [ ] Obtain plan approval before implementation.
- [ ] EP-M1: expose the owned episode run collection.
- [ ] EP-M2: create idempotent episode regeneration runs.
- [ ] EP-M3: submit durable review checkpoint responses.
- [ ] EP-M4: complete behavioural evidence, documentation, and roadmap closure.

## Surprises & discoveries

The roadmap names episode-scoped POST, but the current API design names
ingestion-job-scoped POST. Both have useful distinct meanings: ingestion
materializes the initial episode; regeneration operates on an existing one. The
proposed ADR-028 records this reconciliation without changing the roadmap.

`episodic/api/app.py::_register_generation_run_routes` already wires ingestion
creation, run GET, and events GET. Only the episode collection and checkpoint
submission are absent. `GenerationRunRepository.list_runs` already sorts by
`(created_at, id)` but has neither an actor filter nor a matching count method.

`Checkpoint.respond` rejects terminal checkpoints but does not enforce that an
action appears in `Checkpoint.options`. The submission service must enforce
that additional request policy. Its parent field is `generation_run_id`.

CodeGraph workspace indexing timed out after 300 seconds; reconnaissance used
direct source inspection and shared context packs instead.

ADR-024 explicitly limits py-pglite concurrency evidence. Existing storage
helpers also emit some metrics before commit; new REST success spans must be
emitted only after commit and must not imply those counters are commit counts.

## Decision log

2026-11-08, planning review: D1 retains ingestion creation for initial content
and adds episode creation for regeneration. Regeneration requires a successful
owned predecessor; initial or failed initial attempts use the ingestion route.
Collection reads instead use owned run history. This satisfies the literal
roadmap while preserving a usable first-generation workflow.

2026-11-08, planning review: D2 reuses existing HTTP idempotency machinery with
a new operation name and target-bound fingerprint. Durable run reuse verifies
all accepted client inputs and preserves the original source. No migration or
normal ingestion replay change is planned. Add only a cross-scope collision
guard to its durable reuse path.

2026-11-08, planning review: D3 stages the response event first, then performs
the checkpoint compare-and-set and commits once. The event append already locks
the parent run, so no public lock-management port is needed. SQL locking reads
must refresh loaded state. Review submission does not resume workflows.

2026-11-08, planning review: D4 requires one focused real-PostgreSQL
transaction experiment for the new composition, while leaving the general
concurrency suite under 2.6.7. Generated sequential histories are not
concurrency proof.

These proposed decisions are recorded in
[ADR-028](../adr/adr-028-generation-run-rest-completion.md) and signposted from
the API and system designs. They become approved design when this plan is
accepted. No standalone Terms of Reference exists for this task.

## Outcomes & retrospective

Planning has identified two missing resource surfaces and concrete reuse paths.
Implementation and its acceptance evidence remain outstanding. At every
milestone, record completed behaviour, logs, commit identity, unresolved risks,
and conformance results here. Before marking COMPLETE, reconcile discoveries
with the design documents and ADR, update the guides, and mark roadmap 2.6.3
done. Planning publication alone does not complete the feature.

## Context and orientation

The baseline is commit `92663d12e0e336fcc4e3e5df918f6eb386adc4c1`. The
following paths are repository-relative; commands run at the repository root.
Read `AGENTS.md`, `docs/contents.md`, `docs/repository-layout.md`, and
`docs/documentation-style-guide.md` first.

`episodic/canonical/domain_generation.py` defines frozen run, event,
checkpoint, and response values. `episodic/canonical/domain_enums.py` defines
their states. `episodic/canonical/generation_run_ports.py` defines repository,
event-log, and checkpoint sub-ports. The canonical unit of work exposes their
composite as `generation_runs`. Storage implements these through
`episodic/canonical/storage/generation_runs.py`, `review_checkpoints.py`, and
`generation_run_port_adapter.py`. The reference adapters live under
`episodic/canonical/adapters/`.

HTTP resources live in `episodic/api/resources/generation_runs.py`,
`generation_runs_create_support.py`, and `generation_runs_events.py`.
`episodic/api/source_idempotency.py` stores and replays HTTP responses through
a domain port; `source_intake_support.py` provides canonical body hashing.
`episodic/api/episode_access.py::read_owned_episode` checks the last successful
run. Do not import this inbound helper into the application layer.
`episodic/api/app.py` registers routes; `dependencies.py` and `runtime.py`
provide composition seams. `episodic/api/serializers.py` owns existing wire
representations.

`episodic/canonical/generation_persistence.py::materialise_episode_from_ingestion`
creates source projections for an initial episode. `persist_draft_script`
updates TEI (Text Encoding Initiative) and its successful-run pointer.
`episodic/generation/launcher.py` exposes the launcher port;
`launcher_claim.py` loads the persisted source bundle and claims execution;
`launcher_persistence.py` commits results and terminal events. Regeneration
must reuse these mechanisms, including revision-conflict handling and bounded
admission.

## Conformance basis

The exact upstream revision for existing documentation is the baseline commit
above. Requirements R1–R5 below name this plan's trace points, not invented
upstream identifiers. Roadmap 2.6.1 and 2.6.2 are already complete.

- R1: roadmap 2.6.3 episode POST and GET → EP-M1/EP-M2 → owned collection
  tests and the regeneration behavioural scenario.
- R2: run GET and paginated event GET → EP-M1/EP-M4 → existing polling and
  paging regression suites plus event cursor properties.
- R3: checkpoint POST → EP-M3 → REST, rollback, action, and ownership tests.
- R4: creation idempotency → EP-M2 → replay/conflict tests and inference
  request-count evidence.
- R5: hexagonal boundary acceptance → every milestone →
  `make check-architecture`, negative boundary fixtures, and `make lint`.

The governing design sections are Generation runs in
`docs/episodic-tui-api-design.md`, and Content Generation Orchestrator and
Quality Assurance Stack in `docs/episodic-podcast-generation-system-design.md`.
Use ADR-014 for architecture enforcement, ADR-017 for existing execution and
trusted ownership, ADR-018 for concurrency and history, ADR-024 for review
checkpoint persistence, ADR-007 for the separate workflow checkpoint concept,
and proposed ADR-028 for this completion. Read the generation-run-specific
`docs/adr/adr-015-generation-run-port-split.md`; three records share 015, and
renumbering belongs to roadmap 2.6.4.

Relevant implementation references are:

- `docs/async-sqlalchemy-with-pg-and-falcon.md` and
  `docs/testing-async-falcon-endpoints.md`: asynchronous HTTP and transaction
  boundaries; reuse local fixtures rather than transplanting tutorial code.
- `docs/testing-sqlalchemy-with-pytest-and-py-pglite.md`: real persistence tests
  and the limitations of the embedded PostgreSQL-compatible backend.
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` and
  `docs/agentic-systems-with-langgraph-and-celery.md`: orchestration boundaries
  that this REST slice must not bypass.
- `docs/cost-management-in-langgraph-agentic-systems.md`: preserve existing
  budget snapshots and spend accounting without adding billing policy.
- `docs/complexity-antipatterns-and-refactoring-strategies.md`: keep handlers
  small and split policy from transport; avoid generic command infrastructure.
- `docs/femtologging-users-guide.md`: use `episodic/logging.py` and existing
  observability ports; never log credentials or review payloads.
- `docs/tei-rapporteur-users-guide.md`: retain current generated TEI validation
  and persistence; review submission does not mutate TEI.

Load the `execplans`, `codegraph-mcp`, `hexagonal-architecture`, and
`python-router` skills. Route testing work to `python-testing` and `hypothesis`
when applicable; use `vidai-mock` for inference acceptance. Use
`logisphere-experts` for design deviations, `firecrawl-mcp` for unresolved
external-interface questions, and `commit-message`/`pr-creation` for delivery.
Agents exchanging code should use `context_pack`; packs are reconnaissance
support, not required dependencies of this self-contained plan.

External interface assumptions checked through Firecrawl on 2026-11-08 are
SQLAlchemy's [one AsyncSession per concurrent task rule][sqlalchemy-async] and
PostgreSQL's
[read-committed and unique-conflict behaviour][postgres-isolation]. Use these
as library contracts, not as evidence that repository transactions are correct.
No new protocol or provider library is needed.

## Interfaces and proposed wire contract

### Episode collection

Add `EpisodeGenerationRunsResource` in
`episodic/api/resources/episode_generation_runs.py`, wired under
`/v1/episodes/{episode_id}/generation-runs` for GET and POST.

GET returns 200 with `{items, limit, offset, total}`. Defaults are limit 20 and
offset 0; accept `1 <= limit <= 100`, `offset >= 0`, and an optional single
`GenerationRunStatus` value. Invalid UUIDs, statuses, and pagination return 400
through the existing structured error envelope. First require an existing
episode and at least one run with that episode and principal, independent of
the requested status. Absent/inaccessible episodes return the same 404. Apply
actor, episode, and status predicates in storage before sorting, slicing, and
counting. An authorized collection with no matching status returns an empty
page. An offset beyond the end returns no items with the filtered total.

Extend `GenerationRunRepository.list_runs` with an optional keyword actor
filter and add `count_runs(episode_id, *, actor=None, status=None) -> int` to
both adapters and the composite. Existing internal unfiltered callers retain
their explicit use; HTTP always supplies the authenticated actor. Update all
implementers and test fakes together. Sort oldest first by `(created_at, id)`.
The count observes matching records when queried, not a frozen multi-request
snapshot. Reuse existing serializers and query parsing where appropriate.

POST accepts the existing no-QA creation inputs: required
`quality_mode="draft_without_qa"` and non-blank `skip_qa_rationale`; optional
`template_id`, `prompt_overrides`, and `budget_hints`. Preserve the existing
meaning of these fields; type-check configuration at the HTTP boundary and
specify it in tests: `template_id` is a UUID string when supplied,
`prompt_overrides` and `budget_hints` are JSON objects. Reject unknown fields,
including `actor`, source-bundle selection, and internal metadata. Recognized
`qa_gated` remains 422; malformed input is 400. The `Idempotency-Key` header is
required and non-blank. Bound the canonical encoded request body to 16 KiB
before acquiring idempotency or writing any run; return 413 `payload_too_large`
above that limit. Validate the 64 KiB stored response-envelope budget against
maximum-size accepted inputs using the actual serializer, including internal
metadata and JSON escaping. If that budget cannot be established, lower the
request limit in the proposed contract before implementation rather than
discovering overflow after persistence or launch.

For a fresh request, require the episode's last successful run to belong to the
principal and use that run's `source_bundle_id`. Verify the source job is
owned, ready, and targets this episode. Reuse persisted projections and the
existing source bounds; never materialize a second episode or take a source
identifier from the request body. An owned episode without a successful
predecessor returns 409 `generation_prerequisite`; an inaccessible episode
returns 404. Initial attempts and retries after an initial failure use the
existing ingestion-job endpoint. A ready source association that no longer
matches is also a prerequisite conflict, with no new run or launch.

Return 202 with the serialized run, `Location: /v1/generation-runs/{run_id}`,
and `Retry-After: 1`. Preserve existing 503 launcher-unavailable/overload
behaviour and durable scheduling-failure classification. A different key
creates a distinct run on the same episode; existing revision checks arbitrate
competing draft writes. The endpoint does not promise that competing runs all
succeed.

### Creation application service and idempotency

Introduce a small framework-free application service in
`episodic/generation/run_creation.py`, with typed request/result values and
injected unit-of-work factory, launcher, clock, and UUID factory. It owns fresh
run eligibility, durable create-or-reuse validation, commit-before-launch, and
launch-failure recording. Keep parsing, Falcon errors, JSON response snapshots,
and `run_idempotent` in the inbound adapter. Extract common scheduling policy
from the existing resource where reused, updating its callers in the same
milestone; do not create a generic command bus. Verify the existing Hecate
classification of `episodic.generation` covers the module as application code;
edit configuration only if it does not. Define the factory through
`CanonicalUnitOfWork` directly, never through `episodic.api.types.UowFactory`.
Close the service transaction before invoking the launcher.

Use operation `generation_run.episode_create` for HTTP idempotency. Hash a
canonical envelope containing target episode UUID and the complete accepted
request payload. The existing operation/principal/key record then rejects
same-key changes of target or payload with 409 `idempotency_conflict`, and
reports 409 `idempotency_in_progress` while a request is acquired. Perform
current resource authorization before replay, without requiring a configured
launcher or re-evaluating fresh-source eligibility for an already stored
successful response.

Add a domain-port query
`get_run_by_idempotency_key(principal_id, key) -> GenerationRun | None` to the
repository, reference adapter, SQL adapter, and composite. After authorization
and HTTP acquisition, look up durable reuse before testing fresh-source
eligibility. Keep `create_run` as the atomic uniqueness arbiter, and validate
the returned winner again if another creator won between lookup and insert.

For durable run storage, derive a bounded key using a versioned prefix and
SHA-256 of a canonical tuple `(operation, episode_id, raw_key)`; keep the
principal in the existing separate uniqueness column. Persist a server-owned
creation-scope/target marker in configuration and reject attempts to supply it
through HTTP. Verify that marker, episode, actor, quality mode, rationale,
configuration inputs, and initial budget inputs when a stored run is returned.
Keep the server-owned marker out of HTTP configuration serialization and
provider prompt inputs; test both boundaries explicitly. A collision or
semantic mismatch must return 409 without exposing or launching the other run.
Internal metadata must not be mistaken for user overrides. Also guard the
existing ingestion creation path: if raw-key reuse returns a server-marked
episode run, reject it before scheduling or responding. This handles both
arrival orders of a deliberate cross-scope key collision. Normal ingestion
replay remains unchanged; test this narrow correction independently.

During the existing 24-hour response lifetime, replay the original status,
body, and headers without another launch. After HTTP expiry, durable reuse
returns the same run ID with its current snapshot, provided accepted client
inputs still match. Pin the source from first creation: do not invalidate a
retry because a later successful generation changed the episode pointer.
Running or terminal reused runs are never relaunched. A pending reused run may
be reoffered by ID, relying on the existing durable execution claim. A new key
is required for a genuinely new attempt after terminal failure. Document that
key scope differs between the ingestion and episode creation operations.

### Run and event reads

Retain `GenerationRunResource` and `GenerationRunEventsResource` and their
current snapshots. Events default to limit 20, maximum 100, offset 0. An
optional positive `after_seq` selects strictly greater sequence numbers;
non-zero offset and `after_seq` cannot be combined. Total counts events after
the cursor, before pagination. Omitted cursor begins at sequence 1; zero is
invalid under the existing contract. Polling non-terminal runs retains
`Retry-After`. Test absent and inaccessible runs with indistinguishable errors.

### Review checkpoint submission

Add `GenerationRunCheckpointResource` in
`episodic/api/resources/generation_run_checkpoints.py` at
`POST /v1/generation-runs/{run_id}/checkpoint`. Require a JSON object containing
`checkpoint_id`, `action`, and object `payload`. Actions are `approve`,
`request_changes`, or `edit`, and must also occur in the stored checkpoint's
`options`. Payload records review data such as notes and patch; it is not a
JSON Patch executor. Reject body actor/time fields and unknown top-level keys.
Use the authenticated principal and injected UTC clock for the response.

Implement policy in `episodic/generation/checkpoint_submission.py` with a typed
command and a result containing the resolved `Checkpoint`. Authorize the parent
run, load the checkpoint, and check `checkpoint.generation_run_id == run.id`.
Missing/inaccessible parent gives 404 `run_not_found`; missing or mismatched
child gives 404 `checkpoint_not_found`. Invalid action or payload gives 400. An
already resolved checkpoint gives 409 `checkpoint_already_terminal` and a
terminal parent gives 409 `run_already_terminal`. Non-terminal pending,
running, and paused parents are admissible; no run-status change is implied.

Within one unit of work, stage a `checkpoint.responded` event first, with
checkpoint ID, action, and trusted responder metadata but no notes or patch.
Existing event append acquires the parent run lock. Ensure
`SqlAlchemyGenerationRunStore._require_mutable_run(lock=True)` refreshes loaded
state, for example with `populate_existing`, before checking terminal status.
Then call `respond_to_checkpoint` with `CheckpointResponse` and commit once.
Any event, compare-and-set, or commit failure rolls back both writes. This
orders locks parent-run then checkpoint, matching run-oriented reclamation.
Keep the lower-level checkpoint port's independent contract unchanged.

Return 200 only after commit, with fields `id`, `generation_run_id`, `node`,
`prompt`, `options`, `status`, `created_at`, `responded_at`, `responded_by`,
`response_action`, and `response_payload`. Use the project's UUID, UTC
timestamp, and enum serialization conventions. Repeating a successful
submission returns 409 rather than overwriting the first response. This
endpoint needs no creation idempotency header and performs no workflow resume
or TEI mutation.

Trace list/create/submit operations through existing ports. Set success only
after commit; distinguish invalid input, not-found, conflict, and storage
failure. Logs go through `episodic/logging.py`; keep credentials, raw keys,
notes, and patches out. Do not use run IDs as metric labels.

## Plan of work and milestones

### EP-M1: expose an authorized episode run collection

R1-read, R2, and R5: first add failing collection tests using the existing
SQL-backed API fixtures. Implement actor filtering and count in the port,
reference store, SQL store, and composite; add the GET resource and route. Use
existing run serializers. Keep run and event GET regression suites green.
Acceptance is initial pending/failed visibility, no cross-owner records or
counts, stable tie ordering, validated bounds, and an empty filtered page.

The plateau is a complete read surface with no creation-policy change.
Conformance checks must confirm R1-read/R2/R5 evidence, unchanged ownership
outside this collection, no new dependencies or persistent format, and current
trace links. Run the major-milestone gates below, then commit. Recovery is a
revert of this atomic milestone; regeneration and submission remain absent.

### EP-M2: create idempotent regeneration runs

R1-create, R4, and R5: write red tests for fresh episode creation, eligibility,
replay, cross-target conflict, and source pinning. Add the application service,
resource POST, and composition wiring. Share only the needed scheduling logic
with the initial creation resource. Verify Hecate classification and test all
existing creation paths. Add Vidai Mock regeneration success and inference
failure scenarios, including request-count assertions for replay.

The plateau creates and executes regeneration through the existing launcher.
Acceptance is same episode ID, distinct fresh run ID, durable new TEI revision,
correct replay/conflict responses, no duplicate inference, and preserved
initial-ingestion behaviour. Conformance checks cover R1/R4/R5, D1/D2 and
ADR-017, scope markers, unchanged trust boundaries, and no schema dependency.
Run gates and commit. Recovery reverts the resource/service change; existing
rows retain ordinary run semantics and must not be deleted to roll back.
Checkpoint submission remains absent.

### EP-M3: submit review decisions atomically

R3 and R5: add red transport and application tests, then implement the
resource, service, serializer, error mapping, route, and fresh locking read.
Reuse checkpoint persistence; do not add a second checkpoint store. Validate
action membership and all association checks before staging writes. Add SQL
rollback and stale-state tests and the focused PostgreSQL experiment below.

The plateau exposes durable review recording with an event visible through
existing polling. Conformance checks cover D3, ADR-024 compare-and-set,
run-before-checkpoint ordering, no workflow resumption, payload
confidentiality, and all R3/R5 trace evidence. Run gates and commit. Recovery
reverts endpoint availability without deleting already recorded decisions.
End-to-end closure and final documentation remain.

### EP-M4: close acceptance and documentation

Reconcile R1–R5 with tests and actual behaviour. Update `docs/users-guide.md`
with both creation workflows, eligibility, pagination, 24-hour replay versus
durable deduplication, checkpoint responses and errors. Update
`docs/developers-guide.md` with service composition, focused commands, Vidai
Mock setup, recovery limits, and the PostgreSQL experiment. Update the API
design, system design, ADR-028 status, and `docs/contents.md`; preserve
historical accepted ADRs rather than rewriting their earlier slice outcomes.

After all acceptance evidence passes, mark only roadmap 2.6.3 done and record
the completion evidence. This is the complete feature plateau. Conformance must
confirm every traced requirement, all recorded design changes, and no remaining
unaccepted deviation. Run the four named gates plus documentation gates and
commit. Use revert commits for corrections; retain audit data.

## Verification plan

All new behaviour follows red-green-refactor: write a meaningful failing test,
run it before production edits, record the expected failure, implement the
minimum change, then rerun focused tests and refactor. Collection failure
should be missing-route/unsupported-method evidence; checkpoint failure should
expose missing submission or non-atomic behaviour, not an import/setup error.
For a bug discovered in existing code, retain its regression test. Do not leave
expected-failure markers in the delivered feature.

V1, visibility and bounded pagination: generate small run sets with mixed
owners, episodes, all statuses, timestamp ties, empty sets, and page bounds.
Compare SQL and reference results to an independently written
filter/sort/slice/count oracle in proposed
`tests/test_episode_generation_run_properties.py`. Add named examples to
`tests/test_episode_generation_run_api.py`. Witness an initial pending run
without `last_generation_run_id`, a foreign run interleaved before an owned
run, and an offset beyond the end. A deliberately wrong filter-after-slice
reference must be rejected by the oracle. Passing generated cases plus these
witnesses discharge sequential selection semantics, not snapshot consistency.

V2, retry meaning: in `tests/test_episode_generation_run_idempotency.py`, use
finite cases for missing/blank keys, exact replay, changed target, changed
accepted fields, another principal, both route scopes, and in-flight state.
Exercise expiry through controlled storage time/fixtures, pending recovery,
running and terminal reuse, changed latest-success pointer, and deliberate
durable-key collisions in both arrival orders. Assert persisted run count,
identity, pinned source, HTTP headers, launcher calls, and provider request
counts separately. Cover maximum-size and over-limit request bodies; the latter
must create no idempotency record or run and make no launcher call. The
intermediate contract is that the reused immutable request meaning matches
before it can be returned or launched. Removing the target from the fingerprint
must make the cross-target case fail. These tests establish repository replay
behaviour, not crash-free exactly-once dispatch.

V3, review atomicity: add `tests/test_generation_run_checkpoint_api.py` and
`tests/canonical_storage/test_checkpoint_submission.py`. Parameterize all three
actions, invalid options, all terminal checkpoint states, terminal runs,
unknown IDs, wrong parent, foreign principal, malformed payload, and duplicate
submission. Inject failure after event staging and during commit, then read
through a fresh unit of work: either one response and one event exist, or
neither exists. Use an independent lifecycle oracle for short generated
response/timeout/cancel sequences, preserving first terminal state. Ensure
successful response is reachable and every rejected transition is exercised. A
split-commit negative control must violate the rollback assertion.

V4, lock composition: use a targeted test against an operator-provided isolated
PostgreSQL database with two independent sessions. Coordinate with barriers,
not timing sleeps: one transaction holds the run row; another submission blocks
there; commit terminal status in the first; verify submission reloads terminal
state, fails, and leaves the checkpoint/event unchanged. Race two responses and
verify one wins, one reports terminal conflict, and only one response event is
committed. Bound waits and clean up only this test's rows. Add this opt-in test
as `tests/integration/test_checkpoint_submission_postgres.py`, using explicit
`EPISODIC_TEST_POSTGRES_DSN` and the existing `slow` pytest marker. Its fixture
creates an independent async engine and session factory for that isolated test
database, applies Alembic head, and never falls back to PGlite. Only a
dedicated disposable database is admissible; do not migrate an application
database. A normal PGlite run may skip this test, but feature acceptance must
record a real pass. If no suitable service is available, record this obligation
as undischarged and do not mark implementation complete. Building the general
concurrency tier remains 2.6.7.

V5, event progress: reuse `tests/test_generation_run_paging.py` and
`tests/test_generation_run_properties.py`. Verify exclusive cursor selection,
ascending sequences, no duplicates on append-and-page histories, and correct
filtered total. Explicitly exercise sequences 1 and 2, an empty suffix, limit
1/100, invalid zero/negative bounds, and cursor-plus-offset rejection. Replacing
`>` with `>=` must fail the cursor witness. Do not change retention or
counting algorithms, which belong to 2.6.8/2.6.9.

V6, boundaries and representations: use pytest unit tests with fake ports for
application policy; use SQL-backed API tests for transaction wiring; use Syrupy
snapshots for pending/terminal run, collection, resolved-checkpoint, and error
representations with deterministic UUID/time seams. Preserve material IDs and
state differences rather than normalizing them away. Snapshot content is
reviewed, not blindly regenerated. Run architecture tests with a negative
fixture importing an outbound adapter from each new application/resource
classification. Tests must fail for that forbidden dependency.

Axioms are PostgreSQL transactions, unique constraints, row-lock serialization
and compare-and-set semantics; SQLAlchemy fresh identity-map population and one
session per task; Falcon async dispatch and existing authentication middleware;
and the existing launcher claim and TEI revision guard. Exercise the
repository's composition of these interfaces without attempting to prove
library internals. Hypothesis generates bounded sequential state histories; it
does not explore all runtime schedules. The targeted PostgreSQL experiment
covers selected competing schedules, not exhaustive distributed crash recovery.

### Behavioural specification

Add `tests/features/generation_run_rest.feature` and
`tests/steps/test_generation_run_rest_steps.py`, reusing
`tests/fixtures/generation_run_api.py` and existing domain factories. The core
pytest-bdd specification is:

```gherkin
Feature: Observe and review episode generation runs
  Scenario: Observe an initial run before any draft succeeds
    Given an owned episode has a pending first generation run
    And the episode has no successful generation pointer
    When the owner lists the episode generation runs
    Then the response is 200 and includes the pending run
    And another principal cannot observe that run or its count

  Scenario: Record an allowed review decision
    Given an owned non-terminal run has a created review checkpoint
    And approve is an allowed checkpoint option
    When the owner submits approve with review notes
    Then the response is 200 with the trusted responder and responded status
    And exactly one checkpoint.responded event is durable
    And submitting the checkpoint again returns 409

  Scenario: Refuse a checkpoint from another run
    Given two owned runs have distinct review checkpoints
    When a checkpoint is submitted through the other run URL
    Then the response is 404 and neither checkpoint nor event history changes

  Scenario: Roll back an incomplete review decision
    Given an owned non-terminal run has a created review checkpoint
    When persistence fails after staging its response event
    Then a fresh read finds the checkpoint still created
    And no checkpoint.responded event is durable
```

Extend `tests/features/no_qa_generation_slice.feature` and
`tests/steps/test_no_qa_generation_slice.py` using
`tests/steps/no_qa_generation_slice_support.py` and `vidaimock_harness.py`:

```gherkin
Scenario: Regenerate an existing episode once per request
  Given Vidai Mock returns a valid draft for an owned completed episode
  When the owner creates an episode generation run with a fresh key
  And repeats the same request with the same key
  Then both responses identify the same new run on the existing episode
  And only one new inference request is made
  And polling reaches succeeded with a new durable TEI revision

Scenario: Report inference failure during regeneration
  Given Vidai Mock returns a deterministic provider failure
  When the owner regenerates an eligible episode
  Then polling reaches failed with the existing stable failure category
  And the previous successful episode revision remains available
```

Seed review checkpoints through the real domain port, not a fictitious no-QA
review producer. The regeneration scenarios must exercise the actual provider
HTTP adapter against a locally running Vidai Mock process and SQL persistence;
a recording launcher alone cannot establish end-to-end behaviour. Read the
installed mock version and use the repository harness's fixture format.

## Concrete steps and acceptance commands

Use the repository Makefile for full gates. Run focused tests at the red and
green points; for example, after their files are introduced:

```bash
uv run pytest tests/test_episode_generation_run_api.py tests/test_episode_generation_run_properties.py
uv run pytest tests/test_episode_generation_run_idempotency.py
uv run pytest tests/test_generation_run_checkpoint_api.py tests/canonical_storage/test_checkpoint_submission.py
uv run pytest tests/test_generation_run_api.py tests/test_generation_run_paging.py tests/test_generation_run_idempotency.py
uv run pytest tests/steps/test_generation_run_rest_steps.py tests/steps/test_no_qa_generation_slice.py
uv run pytest -m slow tests/integration/test_checkpoint_submission_postgres.py
make check-architecture
```

Record actual collected/pass counts, expected red failures, and evidence paths;
no invented passing transcript is provided here. A zero-test collection or
skipped required acceptance scenario is not a pass. Existing fixture names
include `RecordingLauncher` and `HeaderPrincipalAuthorization`; reuse them for
focused tests. The real-PostgreSQL command requires the isolated test DSN from
V4. Do not print credentials in logs.

At each major milestone, have scrutineer run these commands one at a time, with
`set -o pipefail` and a distinct log per command:

```bash
set -o pipefail
make fmt 2>&1 | tee /tmp/fmt-episodic-2-6-3.out
make check-fmt 2>&1 | tee /tmp/check-fmt-episodic-2-6-3.out
make typecheck 2>&1 | tee /tmp/typecheck-episodic-2-6-3.out
make lint 2>&1 | tee /tmp/lint-episodic-2-6-3.out
make test 2>&1 | tee /tmp/test-episodic-2-6-3.out
make markdownlint 2>&1 | tee /tmp/markdownlint-episodic-2-6-3.out
make nixie 2>&1 | tee /tmp/nixie-episodic-2-6-3.out
```

Stop the sequence on failure and inspect its log. Preserve per-milestone log
copies before reuse. `make lint` includes architectural enforcement and the
complete repository lint pipeline; retain CPython 3.14 for df12 lint tools. Do
not bypass shared compiler admission or create isolated Cargo caches.
Formatting can edit files: review the resulting diff before gating/committing.
If spelling regenerates unrelated `typos.toml` content, follow the repository's
separate-base-change policy rather than hiding it in this feature.

This planning-only change runs `make fmt`, `make check-fmt`,
`make markdownlint`, and `make nixie`. Runtime implementation milestones
require all four requested code gates above. Before each commit, inspect
`git diff --check` and the full diff, then use the commit-message skill. All
required gates must exit zero.

## Idempotence and recovery

Re-running reads is safe. Same-key creation replays or reuses the durable run
under the explicit lifetime rules; a fresh key deliberately requests another
run. Re-submitting a checkpoint is a conflict, not a second transition. Tests
must use isolated identifiers and tear down only their own fixtures/processes.

A crash after run persistence but before launch leaves a pending run; a retry
may reoffer it, subject to the existing idempotency acquisition lifetime. The
current launcher has no automatic reaper. Follow the existing documented manual
recovery procedure; implementing a scheduler belongs to 2.6.5. A failure to
store a replay response after launch does not justify creating a new run ID.

No migration is planned. Never downgrade review-checkpoint migrations to undo
this REST feature: ADR-024 documents data loss on downgrade. Roll back code
with a revert commit and preserve run, event, response, and TEI audit records.

## Artefacts and notes

Wyvern findings were exchanged through context packs `pk_7dzdkw5j`,
`pk_nws4ausb`, and `pk_4jyewimj`. The plan contains the durable conclusions so
those temporary packs are unnecessary for implementation.

The community review used Pandalump and Wafflecat for architecture, Telefono
and Doggylump for contracts and reliability, and Buzzy Bee and Dinolump for
bounded queries, observability, and verification. Revisions resolved early-run
visibility, target-bound retries, action membership, identity-map freshness,
and atomic event/response writes. Final review added a durable-key lookup,
bidirectional collision guards, pre-write size validation, and an explicit
PostgreSQL fixture contract. The principal trade-off is a narrowly scoped
regeneration endpoint and targeted concurrency evidence instead of a new
ownership model or a general concurrency framework.

Revision note, 2026-11-08: initial evidence-led draft incorporates the six-lens
review and explicitly separates planning delivery from feature completion.

[sqlalchemy-async]: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks
[postgres-isolation]: https://www.postgresql.org/docs/current/transaction-iso.html
