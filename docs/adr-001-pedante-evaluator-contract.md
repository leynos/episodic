# ADR 001: Pedante evaluator contract

## Status

Accepted

## Date

2026-03-19

## Context

Roadmap item `2.2.1` introduces Pedante as the first internal quality assurance
evaluator in the agentic podcast authoring loop. The system design already
establishes three important constraints:

- Text Encoding Initiative (TEI) P5 is the canonical data spine for podcast
  authoring and provenance.
- Large Language Model (LLM) calls must pass through the provider-neutral
  `LLMPort` contract so orchestration code remains adapter-agnostic.
- LangGraph nodes belong to the application layer, where they may coordinate
  domain services and ports but must not become the canonical source of truth.

Pedante therefore needs a durable contract that can support the current
LangGraph-based implementation while still allowing later replacement with a
different evaluator implementation or a network service. The implementation
also needs one explicit decision about the relationship between TEI XML,
Python-native structures, and any JSON representation used for prompt
construction.

## Decision

Pedante uses the following contract.

### Canonical input shape

The canonical Pedante request is `PedanteEvaluationRequest`, which contains:

- `script_tei_xml`: the canonical TEI P5 script payload.
- `sources`: a tuple of `PedanteSourcePacket` values containing stable source
  identifiers, citation labels, TEI locators, titles, and excerpts.

TEI P5 remains the canonical representation. If Pedante or a future evaluator
needs JSON for prompt construction or transport, that JSON is treated as a
projection of the same TEI-backed content model rather than a second canonical
schema.

### Canonical output shape

Pedante returns `PedanteEvaluationResult`, which contains:

- `summary`: a human-readable evaluator summary.
- `findings`: claim-centric `PedanteFinding` values.
- normalized `LLMUsage` plus provider response metadata (`model`,
  `provider_response_id`, and `finish_reason`).

Each `PedanteFinding` records:

- the claim identifier and claim text,
- the claim kind (`direct_quote`, `transplanted_claim`, or `inference`),
- a support-level taxonomy value,
- a severity level,
- remediation guidance, and
- the cited source identifiers used in the judgement.

The support-level taxonomy keeps the claim-support distinctions from the
Pedante sketch, including citation absence, misquotation, fabricated claim,
supported paraphrase, and inference-specific support cases.

### LLM and orchestration boundary

Pedante remains an internal evaluator implemented through `LLMPort`. The LLM
returns strict JSON text, which Pedante parses and validates locally before
returning typed findings. LangGraph is used only as an application-layer
orchestration seam around this contract. Canonical editorial truth remains in
TEI and persisted storage, not in graph state blobs.

## Consequences

### Positive

- Pedante is claim-centric from the start, which fits editorial review and
  later evaluator aggregation.
- Cost accounting remains compatible with the existing `LLMUsage` contract.
- The evaluator can be swapped later without changing the request or result
  shape exposed to orchestration code.
- Prompt construction can use JSON ergonomically without weakening the TEI P5
  data spine.

### Negative

- The first implementation relies on strict JSON prompting rather than a
  provider-native structured-output API.
- TEI XML is passed as opaque text in the initial contract rather than as a
  richer parsed document model.

### Follow-up

- If later work settles a reusable JSON projection for TEI-backed evaluator
  payloads across multiple evaluators, record that separately rather than
  silently widening this ADR.
- If evaluator results are persisted or exposed through an external API, record
  any versioning or compatibility guarantees in a follow-on ADR.
