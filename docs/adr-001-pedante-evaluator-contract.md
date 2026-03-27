# Architecture Decision Record (ADR) 001: Pedante evaluator contract

## Status

Accepted

## Date

2026-03-24

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

Since this ADR was first accepted, `tei-rapporteur` has also grown richer
citation support in the canonical TEI model:

- utterances may carry local provenance and citation attributes
  (`@n`, `@source`, `@resp`, `@cert`, `@corresp`, and `@ana`);
- canonical citation declarations live in
  `<teiHeader><encodingDesc><refsDecl>...</refsDecl></encodingDesc>`; and
- the Python `msgspec.Struct` projection exposes TEI pointer-list attributes
  as structured `list[str]` values rather than TEI's whitespace-delimited
  attribute strings.

Pedante needs to reflect those additions because claim support should be
grounded first in the TEI document's own citation and provenance spine rather
than in citations reconstructed ad hoc during prompting. Pedante also needs a
cost-aware internal design: claim discovery is usually cheaper than full
support analysis, so the evaluator should be free to split those concerns
internally without widening the orchestration contract.

## Decision

Pedante uses the following contract.

### Canonical input shape

The canonical Pedante request is `PedanteEvaluationRequest`, which contains:

- `script_tei_xml`: the canonical TEI P5 script payload.
- `sources`: a tuple of `PedanteSourcePacket` values containing stable source
  identifiers, citation labels, TEI locators, titles, and excerpts.

TEI P5 remains the canonical representation. Pedante must treat utterance-level
citation and provenance attributes as the first place to look for claim support
links. Header-level `refsDecl` metadata remains the canonical location for
citation declarations, while utterance-local attributes and any stand-off
annotations provide the per-claim or per-utterance bindings used during
evaluation.

If Pedante or a future evaluator needs JSON for prompt construction or
transport, that JSON is treated as a projection of the same TEI-backed content
model rather than a second canonical schema. The preferred projection is the
`tei_rapporteur` `msgspec.Struct` representation, or builtins derived from it,
because it preserves the TEI data model while normalizing TEI pointer lists
such as `source`, `resp`, `corresp`, and `ana` into explicit arrays.

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

### Internal evaluation flow

Pedante keeps one orchestration contract but may execute internally as a
two-pass evaluator.

Pass 1 is a claim-catalogue pass. It may use a cheaper model, or a later
deterministic extractor, to:

- identify candidate claims in the script;
- classify each claim as a direct quotation, transplanted claim, or inference;
- collect any citation and provenance links already present in the TEI
  document, especially utterance-local attributes and relevant `refsDecl`
  declarations; and
- emit an explicit "citation absent" result when a claim that should be backed
  by citation has no usable TEI citation binding.

Pass 2 is a claim-support verification pass. It may use a stronger model, or a
more specialized service later, to:

- compare each catalogued claim against the cited source packets;
- decide the support level and severity;
- generate remediation guidance; and
- emit findings for uncatalogued material discovered during verification so
  claim extraction is not the hard recall ceiling for the evaluator.

This split is an internal implementation detail. The application layer still
calls one Pedante evaluator and receives one `PedanteEvaluationResult`.

### LLM and orchestration boundary

Pedante remains an internal evaluator implemented through `LLMPort`. The LLM
returns strict JSON text, which Pedante parses and validates locally before
returning typed findings. If the two-pass design is used, each pass must still
flow through `LLMPort` and report normalized usage separately so LangGraph cost
accounting can aggregate the full Pedante run.

LangGraph is used only as an application-layer orchestration seam around this
contract. Canonical editorial truth remains in TEI and persisted storage, not
in graph state blobs. Any intermediate claim-catalogue artefacts belong to the
evaluator's internal workflow or ephemeral graph state, not to the canonical
episode representation.

## Consequences

### Positive

- Pedante is claim-centric from the start, which fits editorial review and
  later evaluator aggregation.
- Cost accounting remains compatible with the existing `LLMUsage` contract.
- The evaluator can be swapped later without changing the request or result
  shape exposed to orchestration code.
- Prompt construction can use JSON ergonomically without weakening the TEI P5
  data spine.
- The richer TEI citation model is used directly instead of flattening
  utterance-local provenance into prompt-only conventions.
- A cheaper first pass can reduce whole-document verification cost while
  preserving the external Pedante interface.

### Negative

- The first implementation relies on strict JSON prompting rather than a
  provider-native structured-output API.
- TEI XML is passed as opaque text in the initial contract rather than as a
  richer parsed document model.
- A two-pass design adds another prompt boundary and therefore another possible
  source of recall loss, drift, or retry overhead.

### Follow-up

- If later work settles a reusable JSON projection for TEI-backed evaluator
  payloads across multiple evaluators, record that separately rather than
  silently widening this ADR.
- If the claim-catalogue pass becomes deterministic or is shared across
  multiple evaluators, record that extraction contract in a follow-on ADR
  instead of letting it emerge implicitly from prompts and fixtures.
- If evaluator results are persisted or exposed through an external API, record
  any versioning or compatibility guarantees in a follow-on ADR.
