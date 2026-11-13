# Architectural decision record (ADR) 026: QA artefact persistence contract

## Status

Accepted. Durable quality-assurance (QA) evaluations and their findings are
stored in one `qa_evaluations` table plus one `qa_findings` child table, with
explicit payload-shape and policy-version columns.

## Date

2026-11-01.

## Context and problem statement

Roadmap item `2.2.7` requires the system to store evaluator findings, runtime
estimates, rubric scores, and compliance results, and to retrieve them filtered
by evaluator and compliance status. Two evaluators exist when the item starts:
Pedante (roadmap item `2.2.1`), which reports findings, and Chrono (roadmap item
`2.2.6`), which reports a runtime estimate and renders no verdict. Bromide,
Chiltern, Anthem, and Caesura remain unimplemented.

The design document's *Data Model and Storage* section named two tables:
`qa_findings` and `brand_compliance_results`. Only Anthem would write the
second, and Anthem does not exist. Writing retrieval as a union over two tables
for a producer that may never be built makes the roadmap's own filter
requirement — "filtered by evaluator and compliance status" — harder than the
data warrants.

Three further questions had to be settled before implementation:

- How does a stored row stay interpretable after an evaluator changes the
  meaning of its payload or the policy changes what counts as a failure?
- What happens when an evaluator fails transiently and the same evaluation is
  retried?
- Where does token usage live, given that the cost ledger already records it?

## Decision drivers

- One indexed query must answer the roadmap's filter requirement, including
  pagination and an unpaged total.
- A historical row must remain interpretable without guessing which release
  wrote it.
- A transient evaluator failure must not permanently mark an episode
  non-compliant.
- Cost data must not be duplicated, because two copies drift.
- The schema must admit the four evaluators that are still unimplemented
  without a rewrite.
- The persistence boundary must stay inside the canonical package, so the
  evaluator package does not gain a dependency on persistence.

## Decision outcome

### Unified evaluation table with a findings child

`qa_evaluations` records one evaluator invocation linked to a canonical episode
and, optionally, to the generation run that produced the evaluated script.
`qa_findings` records the ordered findings that belong to one evaluation.
Compliance is a `compliance_status` column on the evaluation, not a separate
table.

The reasons a separate `brand_compliance_results` table was rejected are:

- It would carry the same episode, evaluator, policy version, and timestamp
  columns as the evaluation that produced it, so the same fact would live in
  two places.
- Retrieval filtered by evaluator and status would become a union across two
  shapes that a client must reconcile.
- The only producer that would populate it is Anthem, which is unimplemented;
  building for it now is speculative generality.

The child table is kept rather than a JSONB findings array because roadmap items
`4.4.1` and `4.4.2` aggregate findings across evaluators and drive refinement
turns from individual findings, which needs stable identifiers and
cross-episode queryability.

### Compliance-status taxonomy

`qa_compliance_status` has four values:

| Value            | Meaning                                                                         |
| ---------------- | ------------------------------------------------------------------------------- |
| `compliant`      | The evaluator found nothing that blocks the episode under the recorded policy.  |
| `non_compliant`  | At least one finding is blocking under the recorded policy.                     |
| `not_applicable` | This evaluator renders no compliance verdict under the recorded policy version. |
| `errored`        | The evaluator failed to produce an artefact.                                    |

*Table 1: The four compliance-status values.*

`not_applicable` means "this evaluator renders no compliance verdict under the
recorded policy version", not "not applicable to this episode". Chrono records
it today. When Chrono gains pacing thresholds, new rows will carry a later
`compliance_policy_version` and a real verdict, while rows recorded under
version 1 remain accurate statements about version 1.

A `lifecycle_status` plus nullable `verdict` split was rejected. An artefact is
written only after an evaluator returns or fails, so `pending` and `running`
have no representable state, and `superseded` is covered by the
errored-supersession rule below plus ordering by `evaluated_at`. The split
would become justified if an evaluator ever reported partial results.

### Versioning obligations

`artefact_schema_version` versions the *shape* of the payload fields —
`evaluator_metadata`, `QaFinding.details`, and the vocabulary of
`QaFinding.code` — not the table columns, which Alembic versions.

- Adding a new optional key does not bump the version.
- Changing the meaning of an existing key, removing a key, or changing the
  vocabulary of `code` does bump it.
- The mapper carries the stored value through; it never falls back to the
  module default, because a mapper bug would silently relabel history.
- A reader that meets a version newer than the running release fails loudly:
  the API returns `422 unprocessable_entity` with code
  `qa_artefact_schema_unsupported`. The detail route applies the episode
  ownership check before answering, so the failure cannot confirm the existence
  of an artefact to a principal that does not own it.
- Stored rows are never rewritten by a bump.

`compliance_policy_version` versions the *decision rule* that produced
`compliance_status` and `QaFinding.is_blocking`. Changing the blocking
support-level set, or any evaluator's outcome-to-status mapping, obliges a
bump. Because `code` preserves the raw signal, historical rows can be
re-derived by a backfill; without the policy version there would be no way to
distinguish a re-derivable row from an authoritative one.

### Immutability and the one exception

Artefacts are immutable once recorded, with exactly one exception: an artefact
whose status is `errored` is provisional and is superseded in place, keeping
its identifier, by a later successful recording under the same idempotency key.
Without the exception a transient failure would permanently mark an episode
errored and the successful retry would be discarded as a replay. Without
immutability the stored status and blocking flags could drift away from the
policy version they record.

`errored` has no production producer in this slice. Pedante and Chrono raise
rather than record a failure, and the generation graph does not yet call the
recording service. The status, the supersession rule, and their tests exist so
the first producer that needs them does not have to change the storage contract.

### Cost correlation rather than duplication

Token usage is not stored on the artefact. The cost ledger already records
normalized usage and priced entries per provider call. The correlation is
`generation_run_id` plus `evaluator_metadata["provider_response_id"]`, which
together reconstruct the ledger's idempotency key
`run:{run_id}:node:{node}:call:{provider_response_id}:attempt:{n}`.

### Rubric precision is a domain contract

The rubric score is held at four decimal places, rounded half-to-even, by the
value object itself rather than by the storage adapter. The precision is a
domain decision: a score is part of the immutable artefact, and an in-memory
summary must equal the summary the same artefact reconstructs after a round
trip. Quantizing in the adapter instead would leave the constructed object
holding a value no read could return, because the object is frozen and the
adapter cannot rewrite it. Storage therefore follows the domain: the column is
sized to hold exactly four decimal places, and the domain modules state their
own precision without naming a column type or a database product.

### Retention posture

Evaluations and findings are retained for the life of the canonical episode.
The episode foreign key is `ON DELETE CASCADE`, so deleting an episode removes
its QA history with it. The generation-run foreign key is `ON DELETE SET NULL`,
so purging run history leaves the evaluation attached to its episode but no
longer correlated with a run. That foreign key carries a partial index over
non-null values, because PostgreSQL indexes no referencing column on its own
and the evaluation indexes all lead with `episode_id`; without it a purge would
scan the whole table once per deleted run. No background job prunes QA
artefacts; a future retention policy is a separate decision.

### Enum extension is a two-deploy operation

`qa_evaluator` admits all six evaluators named in the design document, even
though four are unimplemented, because PostgreSQL cannot add an enum value and
use it in the same transaction. Extending the taxonomy later would therefore
take two deploys, not one migration. A parameterized test pins the value set
against the documented taxonomy so it cannot drift silently.

## Considered alternatives

### The generation event log as the QA store

Rejected. The launchers call `_require_mutable_run(..., lock=True)`, which
raises `RunAlreadyTerminal` once a run is terminal; QA results are produced
during and after that point. Storing them in the run's event log would require
weakening the terminal-state guard that protects the generation record.

### A JSONB findings array on the evaluation row

Rejected for now. It would make the first persistence change smaller, but
roadmap items `4.4.1` and `4.4.2` need per-finding identity and cross-episode
aggregation. Collapsing to JSONB remains a legitimate retreat if the child
table proves costly.

### Derive compliance at read time

Rejected. Deriving the verdict from findings on every read means every client
re-implements the policy, and a policy change silently rewrites the apparent
history of every episode. Storing the verdict with its policy version keeps the
answer stable and the provenance explicit.

### A separate `brand_compliance_results` table

Rejected, as described above.

## Consequences

- `qa_evaluations` and `qa_findings` replace the two named design-document
  tables; the design document's *Data Model and Storage* section is updated in
  the same change.
- Two SQLAlchemy enum types (`qa_evaluator`, `qa_compliance_status`) and one
  finding-severity type join the schema, so a new evaluator is a migration
  before it is code.
- Every writer must supply both version columns explicitly; a default would
  make a new writer silently claim the oldest policy.
- The recording service lives in `episodic/canonical/`, because it knows both
  the evaluator result and the canonical episode, and hosting it in
  `episodic/qa/` would invert the dependency direction.
- Readers must handle `qa_artefact_schema_unsupported`; a newer writer is a
  deployment-ordering fact, not a parse error to swallow.
- This record discharges the open item in [ADR 001: Pedante evaluator
  contract](adr-0001-pedante-evaluator-contract.md), which asks for a follow-on
  record of the versioning and compatibility guarantees that apply once
  evaluator results are persisted or exposed through an API. The two version
  columns, the reader-side schema check, and the single errored-supersession
  exception are those guarantees.

## References

- [ADR 001: Pedante evaluator contract](adr-0001-pedante-evaluator-contract.md)
- [Design document, *Data Model and Storage*](../episodic-podcast-generation-system-design.md#data-model-and-storage)
- [Design document, *Quality Assurance Stack*](../episodic-podcast-generation-system-design.md#quality-assurance-stack)
- [ADR 017: No-QA generation execution and TEI persistence](adr-0017-no-qa-generation-run-execution-and-tei-persistence.md)
- [ADR 018: Explicit repository-written versioning and history strategy](adr-0018-explicit-versioning-and-history-strategy.md)
- ExecPlan:
  `docs/execplans/2-2-7-persist-qa-artefacts-linked-to-canonical-episodes.md`
