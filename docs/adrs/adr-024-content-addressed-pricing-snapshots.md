# Architectural decision record (ADR) 024: Content-addressed pricing snapshots

## Status

Proposed.

## Date

2026-11-10.

## Context and problem statement

Roadmap item `2.5.1` requires immutable pricing snapshots for provider and
helper pricing inputs, with versions that keep historical run costs
reproducible. Roadmap item `2.4.4` introduced a first cut: a
`pricing_snapshots` table, a `PricingSnapshot` value object, YAML rate cards
under `config/pricing-snapshots/`, and run-level pins recorded in
`run_pricing_pins`.

That first cut does not yet deliver the `2.5.1` promises:

- Historical costs are not reproducible from the database. A pinned provider
  call is priced from the YAML file rather than the persisted row, so editing a
  rate card in place changes the price of a run that already pinned the earlier
  version. Deleting the file breaks pinned runs outright.
- Pricing inputs cannot be represented faithfully. Rates are integers in minor
  units per one million usage units, so OpenAI's cached-input price of 7.5
  cents per million tokens is rounded to 8. Text-to-Speech (TTS) rate cards
  priced per character or per minute of audio have no representation, and
  nothing distinguishes an LLM snapshot from a TTS one.
- Helper-service pricing documents such as Service-Level Agreements for
  OpenAPI (SLA4OAI) plans[^1] have nowhere to live, and the snapshot "version"
  is an implicit mixture of a hand-assigned identifier, a raw-file digest, a
  billing-period key, and an effective date.

The question is how Episodic should identify and version pricing snapshots so
that history is reproducible, exact prices are representable, and a future
helper-service document fits the same model.

## Decision drivers

- ADR-018 requires immutable content to be content-addressed or append-only,
  and consumers to pin versions rather than resolve latest.
- Persisted `2.4.4` rows exist in alpha databases and must be migrated, not
  dropped.
- Money stays integral: no floating-point arithmetic in pricing, and no
  `Decimal` in persisted or wire formats.
- The pricing engine's truncating rounding policy must not change in `2.5.1`;
  rounding belongs to later roadmap items.
- No new third-party dependency and no source-API compatibility machinery for
  this internal, pre-1.0 package.
- Hecate enforces hexagonal import boundaries, so domain hashing and value
  objects must not import SQLAlchemy, YAML, or application modules.

## Requirements

### Functional requirements

- Persist the model pricing inputs used for LLM and TTS billing.
- Preserve room for future helper-service pricing documents.
- Version snapshots so that historical run costs remain reproducible after a
  rate card is edited or deleted.
- Represent a per-million-token price of 7.5 cents exactly, and represent TTS
  prices per character, per thousand characters, and per minute of audio.
- Store a verbatim helper-service source document when the snapshot describes
  one.
- Detect a snapshot row whose stored columns no longer match its content hash.

### Technical requirements

- The version identity is a canonical SHA-256 content hash derived by the
  domain, defined byte for byte as schema version `1`.
- The database assigns a surrogate identifier the first time it stores a
  content hash, and returns the same identifier for the same content thereafter.
- The canonical form encodes instants so that a PostgreSQL `timestamptz` round
  trip reproduces the hash exactly.
- Integers inside the canonical document lie in `0 ..= 2**53 - 1`.
- Pinned provider calls are priced from the persisted snapshot.
- The migration converts every `2.4.4` row so that it hashes identically to the
  rewritten shipped YAML card of the same content.

## Options considered

### Option A: Authored revision numbers

Each rate card carries a human-assigned revision such as `2026-05-r2`, and
snapshots are unique on subject plus revision.

This is easy to read, but it creates two sources of truth (the authored number
and the migration backfill), collides across billing periods and helper plans,
and turns an in-place file edit into a production failure or a silent price
change.

### Option B: Content-addressed identity with effective dating

A snapshot's identity is the SHA-256 hash of a canonical document; the database
assigns a surrogate identifier per hash. Applicability is governed by
`effective_from`, and billing periods remain on pins, ledger rows, and metering
counters.

An edit becomes a new version by construction, the hash works for documents
fetched later from an external service, and no authoring convention is needed.

### Option C: Database-assigned monotonic versions

The database assigns version `1`, `2`, … per subject on insert.

This keeps ordering trivial, but the identity then depends on insertion history
rather than content, identical content can be stored twice, and a restored or
replayed migration changes the numbers.

| Topic            | A: Authored  | B: Content-addressed | C: Sequence |
| ---------------- | ------------ | -------------------- | ----------- |
| In-place edit    | Ambiguous    | New version          | New version |
| Same content     | May collide  | Same identity        | Duplicated  |
| External fetch   | Needs author | Works                | Works       |
| Human-readable   | Yes          | No (use dates)       | Yes         |
| Migration replay | Fragile      | Idempotent           | Not stable  |

_Table 1: Comparison of snapshot identity options._

## Decision outcome / proposed direction

Adopt Option B.

- `PricingSnapshot` is an immutable, deeply frozen value object with a derived
  `content_hash` computed in `__post_init__`. Adapters never supply a hash.
- The snapshot records `service_kind` (`llm`, `tts`, or `helper_service`), the
  subject tuple `(provider_name, model, operation)`, `source_kind`, `currency`,
  exact rates, verbatim source metadata, and optionally an effective date and a
  verbatim source document.
- Rates become `MeteredRate(amount_minor, per_units, unit)` normalized to
  lowest terms, so 7.5 cents per million tokens is `3` per `400000` and a TTS
  price of 5 cents per minute of audio is `1` per `12000` milliseconds.
- `billing_period_key` leaves the snapshot. Rate applicability is governed by
  `effective_from`; billing periods stay on run pins, ledger rows, and metering
  counters.
- Snapshots carry pricing inputs only, never a rounding rule.
- The source document is stored as verbatim text plus media type, and the
  canonical form hashes its SHA-256 digest. It is required when `source_kind` is
  `sla4oai_plan` and optional otherwise, capped at 262,144 UTF-8 bytes. No
  parsing happens in `2.5.1`.
- The store inserts with
  `ON CONFLICT ON CONSTRAINT uq_pricing_snapshots_content_hash DO NOTHING
  RETURNING id`
  and falls back to a `SELECT` by content hash. `get` rebuilds the snapshot
  and compares the recomputed hash with the stored one, raising
  `PricingSnapshotIntegrityError` on mismatch.
- A legacy-format catalogue file is rejected at startup with a message naming
  the file and pointing to the conversion guidance, rather than being read by a
  second compatibility reader.

### Schema version 1 canonical form

The canonical form is a JSON object whose keys are exactly
`PRICING_SNAPSHOT_V1_FIELDS`:

```plaintext
currency, effective_from, model, operation, provider_name, rates,
retrieved_at, schema_version, service_kind, source_document,
source_kind, source_metadata
```

Normative encoding rules:

- Enum values are encoded as their string values.
- `rates` is an object mapping metric name to
  `{"amount_minor": int, "per_units": int, "unit": str}`, already in lowest
  terms.
- `source_metadata` is an object of strings.
- Instants are encoded as UTC strings `YYYY-MM-DDTHH:MM:SS.ffffffZ` with
  exactly six fractional digits, so a `timestamptz` round trip is byte-stable.
- Absent `effective_from` and `source_document` are encoded as `null`.
- `source_document` is `{"media_type": str, "sha256": "sha256:<hex>"}`.
- The document is encoded with
  `episodic.json_canonicalization.canonical_json_bytes`, and the hash is
  `"sha256:"` followed by the lowercase hexadecimal SHA-256 digest of those
  bytes. The encoding is RFC 8785-equivalent for this document because every
  key is ASCII and every number is an integer no larger than `2**53 - 1`[^2].

Canonical bytes and hashes for one LLM, one TTS, and one SLA4OAI snapshot are
recorded as test vectors in `tests/test_cost_pricing_snapshot_hash.py` and its
syrupy snapshot, and are repeated below. The vectors include a non-UTC
`retrieved_at`, a null `effective_from`, a non-reduced authored rate, and a
source document.

#### Test vectors

The documents below are pretty-printed for readability. The canonical bytes are
the compact encoding produced by `canonical_json_bytes`, and each hash is the
SHA-256 digest of those compact bytes.

| Vector        | Distinguishing inputs                                                                                            | Content hash                                                              |
| ------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| LLM rate card | `retrieved_at` at `+02:00`, null `effective_from`, per-million rates reduced on construction, no source document | `sha256:6fda0bd585c7380f6b26ebe14e914e8ab4d3bff383063f17870a125408fb4369` |
| TTS rate card | five cents per minute reduced to `1/12000` milliseconds                                                          | `sha256:31f5ede6303e271994e141b54203e510d97aa6b65ff3dc2179a6f3aa6f9d85c6` |
| SLA4OAI plan  | required source document, verbatim content hashed by digest                                                      | `sha256:912f19b822917adbaa268a6b08384fe8a101528a86733eb6ec39f43039c1e0d7` |

LLM rate card:

```json
{
  "currency": "USD",
  "effective_from": null,
  "model": "gpt-4o-mini",
  "operation": "chat_completions",
  "provider_name": "openai",
  "rates": {
    "input_tokens": {"amount_minor": 3, "per_units": 200000, "unit": "token"},
    "output_tokens": {"amount_minor": 3, "per_units": 50000, "unit": "token"}
  },
  "retrieved_at": "2026-05-01T00:30:00.000000Z",
  "schema_version": 1,
  "service_kind": "llm",
  "source_document": null,
  "source_kind": "provider_rate_card",
  "source_metadata": {"source_url": "https://openai.com/api/pricing/"}
}
```

TTS rate card:

```json
{
  "currency": "USD",
  "effective_from": "2026-04-01T00:00:00.000000Z",
  "model": "tts-1",
  "operation": "speech",
  "provider_name": "openai",
  "rates": {
    "milliseconds": {"amount_minor": 1, "per_units": 12000, "unit": "millisecond"}
  },
  "retrieved_at": "2026-05-01T00:00:00.000000Z",
  "schema_version": 1,
  "service_kind": "tts",
  "source_document": null,
  "source_kind": "provider_rate_card",
  "source_metadata": {}
}
```

SLA4OAI plan:

```json
{
  "currency": "USD",
  "effective_from": "2026-05-01T00:00:00.000000Z",
  "model": "gpt-4o-mini",
  "operation": "chat_completions",
  "provider_name": "openai",
  "rates": {
    "input_tokens": {"amount_minor": 3, "per_units": 200000, "unit": "token"},
    "output_tokens": {"amount_minor": 3, "per_units": 50000, "unit": "token"}
  },
  "retrieved_at": "2026-05-01T00:30:00.000000Z",
  "schema_version": 1,
  "service_kind": "llm",
  "source_document": {
    "media_type": "application/yaml",
    "sha256": "sha256:c357cca0909f1a2aaf833a0d7f277925abb283937c2210525c374af9d61b9c0c"
  },
  "source_kind": "sla4oai_plan",
  "source_metadata": {"source_url": "https://openai.com/api/pricing/"}
}
```

A future schema version defines its own field tuple and encoder; rows are
re-hashed with the encoder selected by their stored `schema_version`, so adding
a field never changes the hash of a version 1 row.

## Goals and non-goals

- Goals:
  - Reproducible historical cost after a rate card is edited or deleted.
  - Exact integer-fraction rates with explicit units for LLM and TTS.
  - A home for verbatim helper-service pricing documents.
  - Tamper detection on read.
  - Migration of `2.4.4` rows.
- Non-goals:
  - SLA4OAI fetching, parsing, and OpenAPI `info.x-sla` discovery (`2.5.2`).
  - Catalogue listing and selection policy beyond effective dating (`2.5.2`).
  - Quota, overage, rounding policy, and exact sub-minor-unit cost (`2.5.3`).
  - Ledger columns for model metadata, plan identifiers, and rounding rules
    (`2.5.4`).
  - Budget reservation (`2.5.5`).
  - Any TTS adapter or TTS usage producer.

## Migration plan

1. Extract shared leaf modules (`episodic.json_canonicalization`,
   `episodic.cost.primitives`) so domain modules can hash and validate without
   the application group.
2. Introduce `PricingSnapshotRepository` and price pinned calls from the
   persisted snapshot on the existing schema.
3. Replace the snapshot representation with schema version 1, content
   addressing, exact rates, TTS and helper support, and migration
   `20261110_000017`.
4. Add behavioural coverage, including a Vidai Mock scenario and the 7.5-cent
   correction to the shipped card.
5. Update the design document, ADR-015, the users' guide, the developers'
   guide, and the roadmap.

Migration `20261110_000017` runs stop-the-world: operators scale launchers and
workers to zero, back up the three cost tables, upgrade, then roll out the new
image. The offline (`--sql`) upgrade emits a guard that raises unless
`pricing_snapshots` is empty, because hash recomputation needs Python and live
rows. Downgrade refuses unless the table is empty.

## Known risks and limitations

- `RunPricingKey` and the `run_pricing_pins` primary key have no service kind,
  so an LLM and a TTS subject sharing provider, model, and operation would
  share one pin. No TTS producer exists yet; the first TTS adapter must revisit
  the pin key.
- Truncating per-metric rounding records small calls as zero. Snapshots carry
  inputs only, so `2.5.3` can introduce a rounding rule recorded per ledger row
  without invalidating any hash.
- A failing pricing operation inside the generation success transaction still
  rolls back an already-paid draft; `PricingSnapshotError` maps to the stable
  failure category `cost.pricing_snapshot`.
- Chronology is expressed by `effective_from` and `recorded_at` rather than a
  human-readable revision number; Git history is the authoring trail.

## Outstanding decisions

- Whether `plan_name` and snapshot listing belong on the catalogue port in
  `2.5.2` once SLA4OAI parsing exists.
- Whether the first TTS adapter adds `service_kind` to the run pin key.

## Architectural rationale

Content addressing satisfies ADR-018's immutability invariant without database
triggers or privilege tricks, keeps the domain free of persistence concerns,
and gives the same identity semantics to provider rate cards and to
helper-service documents fetched in `2.5.2`. Exact integer fractions keep money
integral while allowing TTS and per-minute prices. The design deliberately
leaves rounding, quotas, and budget behaviour to the roadmap items that own
them, so no snapshot written now has to be rewritten later.

## References

- Roadmap item `2.5.1`: `docs/roadmap.md`.
- Cost accounting ports and pricing engine: ADR-015,
  `docs/adr/adr-015-cost-accounting-ports-and-pricing-engine.md`.
- Explicit versioning and history strategy: ADR-018,
  `docs/adr/adr-018-explicit-versioning-and-history-strategy.md`.
- Hexagonal architecture enforcement: ADR-014,
  `docs/adr/adr-014-hexagonal-architecture-enforcement.md`.
- ExecPlan: `docs/execplans/2-5-1-immutable-pricing-snapshots.md`.

[^1]: SLA4OAI Specification 0.10.0:
  <https://github.com/isa-group/SLA4OAI-Specification>
[^2]: RFC 8785, JSON Canonicalization Scheme:
  <https://www.rfc-editor.org/rfc/rfc8785>
