# ADR-015: Cost accounting ports and pricing engine

## Status

Accepted.

## Context

Roadmap item `2.4.4` instruments per-call cost accounting for structured
generation orchestration. Planner, executor, and evaluator nodes call Large
Language Model (LLM) providers through `LLMPort`, and those calls must become
auditable without changing the stable three-field `LLMUsage` aggregate that the
orchestration result already exposes.

Historical bills must remain reproducible after provider rate cards change.
Retries must not create duplicate ledger rows, and suspended workflow runs must
resume with the same pricing snapshot selected at run start. Future
Service-Level Agreements for OpenAPI (SLA4OAI) helper-service pricing documents
should fit the same port shape, but the first implementation prices internal
LangGraph nodes from pinned provider rate cards loaded from local catalogue
files.

## Decision

Add a cost-accounting port family under `episodic.cost`:

- `CostLedgerPort` records append-only provider-call ledger entries and final
  task roll-up rows.
- `PricingCataloguePort` resolves an immutable `PricingSnapshot` for provider,
  model, operation, and billing period.
- `MeteringPort` atomically consumes per-period counters for future quota and
  overage pricing.
- `PricingEngine` is a pure function over a `PricingSnapshot`, canonical usage
  metrics, provider operation, and billing period. It performs no I/O and reads
  no clock.

`LLMUsage` remains unchanged. Provider-specific usage details travel in a new
`ProviderCallUsage` envelope on `LLMResponse`, keyed by this canonical metric
vocabulary:

- `input_tokens`
- `output_tokens`
- `cached_input_tokens`
- `cache_write_tokens`
- `reasoning_tokens`
- `audio_input_tokens`
- `audio_output_tokens`

Pricing snapshots carry `source_kind` with values `provider_rate_card` and
`sla4oai_plan`. The initial catalogue uses `provider_rate_card`; `sla4oai_plan`
is reserved so helper-service pricing can be added without changing the port
signature.

The schema includes `run_pricing_pins`, keyed by workflow run, provider, model,
operation, and billing period. The pin table records the selected
`pricing_snapshot_id` before cost entries are written, so resumed workflows use
the same rate card they started with.

## Examples

OpenAI Chat Completions usage:

```json
{
  "prompt_tokens": 1200,
  "completion_tokens": 350,
  "total_tokens": 1550,
  "prompt_tokens_details": {
    "cached_tokens": 200
  },
  "completion_tokens_details": {
    "reasoning_tokens": 50
  }
}
```

Normalized metrics:

```json
{
  "input_tokens": 1200,
  "output_tokens": 350,
  "cached_input_tokens": 200,
  "reasoning_tokens": 50
}
```

OpenAI Responses usage:

```json
{
  "input_tokens": 900,
  "output_tokens": 220,
  "input_tokens_details": {
    "cached_tokens": 100
  },
  "output_tokens_details": {
    "reasoning_tokens": 30
  }
}
```

Normalized metrics:

```json
{
  "input_tokens": 900,
  "output_tokens": 220,
  "cached_input_tokens": 100,
  "reasoning_tokens": 30
}
```

Anthropic Messages usage:

```json
{
  "input_tokens": 800,
  "output_tokens": 180,
  "cache_read_input_tokens": 75,
  "cache_creation_input_tokens": 25
}
```

Normalized metrics:

```json
{
  "input_tokens": 800,
  "output_tokens": 180,
  "cached_input_tokens": 75,
  "cache_write_tokens": 25
}
```

## Consequences

### Positive

- Existing orchestration usage aggregation remains stable because `LLMUsage`
  keeps its current shape.
- Provider billing details are captured with enough fidelity to price cached,
  reasoning, and audio token classes when the snapshot includes those rates.
- Suspended workflow runs can resume with reproducible pricing.
- The same ports can later ingest SLA4OAI pricing documents for external
  helper services.

### Negative

- Provider adapters must maintain explicit normalization code for each response
  family they support.
- `MeteringPort` exists before budget enforcement consumes it, so its first
  implementation is validated by tests rather than production call volume.

### Neutral

- Budget reservation, commitment, and release semantics remain out of scope for
  this roadmap slice.
- Text-to-Speech pricing is reserved in schema names and enum values but is not
  exercised by the initial implementation.

## Addendum (2026-10-10)

The SQLAlchemy cost-ledger adapter persists pricing snapshots as immutable
rows. It inserts by snapshot identifier with `ON CONFLICT DO NOTHING` and uses
`RETURNING` to distinguish a newly persisted row from an existing row reused
under that identifier. Reuse leaves the stored row unchanged. A content hash
already associated with a different identifier raises
`PricingSnapshotCollisionError`; the database identifies this condition with the
`uq_pricing_snapshots_content_hash` unique constraint.

`CostRecorder` persists a resolved snapshot before inserting a run-pricing pin
or an unpinned provider-call ledger row, so their foreign keys refer to an
existing snapshot. A provider call with an existing run pin relies on that
pin's foreign key and does not persist the snapshot again.

For file-backed snapshots, `content_hash` is the SHA-256 digest of the entire
source YAML file, including its rates and metadata. The adapter stores the
catalogue-provided `rates_minor_per_metric` mapping as JSONB and stores the
provided content hash; it does not recalculate either value. A timezone-aware
`effective_from` value is validated by `PricingSnapshot` and forwarded to the
timezone-aware database column without string parsing; an absent value remains
unset. `retrieved_at` is parsed as a timezone-aware instant before persistence.

Revision `20261010_000013` applies the named content-hash constraint to
already-deployed schemas. It renames PostgreSQL's historical
`pricing_snapshots_content_hash_key` constraint to
`uq_pricing_snapshots_content_hash`, preserving uniqueness and its backing
index. Before issuing DDL, the online migration validates that exactly one
candidate constraint exists and that it is a unique constraint over only
`content_hash`; it raises `CommandError` if the constraint is missing,
malformed, or ambiguous. An already-renamed alpha-preview constraint passes
validation without another rename. The offline migration emits SQL with
equivalent catalogue guards. Downgrade restores the historical name after the
same validation.

## Addendum (2026-11-11)

This ADR is amended by ADR-028: content-addressed identity, exact rates,
Text-to-Speech (TTS) and helper documents, and the billing period removed from
snapshots. The decision above is unchanged; this addendum records the
supersession and the one consequence it revises.

ADR-028 supersedes the snapshot representation in the 2026-10-10 addendum.
Snapshots are now schema version 1 with a domain-derived SHA-256 content hash,
exact `MeteredRate(amount_minor, per_units, unit)` rates normalized to lowest
terms, a service kind, and optional verbatim helper-service documents.
`billing_period_key` leaves the snapshot; billing periods stay on run pins,
ledger rows, and metering counters. `PricingSnapshotRepository.ensure` replaces
`CostLedgerPort.ensure_snapshot` and inserts by content hash with
`ON CONFLICT ... DO NOTHING RETURNING id`, so identical content always maps to
one identifier and an existing row is never rewritten.
`PricingSnapshotIntegrityError` replaces `PricingSnapshotCollisionError`; `get`
additionally verifies that a stored row still hashes to its recorded identity.
The `rates_minor_per_metric` JSONB column and the raw-file-digest content hash
described above no longer exist. Migration `20261110_000017` converts the
`2.4.4` rows.

The TTS consequence also changes. TTS pricing is now representable in a
snapshot, but no TTS adapter or usage producer exercises it yet, so the
reservation recorded above is a live shape rather than a reserved name.

## References

Roadmap item `2.4.4` in `docs/roadmap.md`.[^1] ExecPlan:
`docs/execplans/2-4-4-cost-accounting-and-usage-metering.md`.[^2] System design
section "Cost accounting and budget enforcement".[^3] Hexagonal architecture
enforcement decision ADR-014.[^4] Content-addressed pricing snapshots
ADR-028.[^5]

[^1]: Roadmap item `2.4.4` in `docs/roadmap.md`
[^2]: ExecPlan:
  `docs/execplans/2-4-4-cost-accounting-and-usage-metering.md`
[^3]: System design section "Cost accounting and budget enforcement" in
  `docs/episodic-podcast-generation-system-design.md`
[^4]: ADR-014: `docs/adrs/adr-0014-hexagonal-architecture-enforcement.md`
[^5]: ADR-028:
  `docs/adrs/adr-0028-content-addressed-pricing-snapshots.md`
