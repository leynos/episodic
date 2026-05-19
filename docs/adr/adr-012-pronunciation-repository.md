# ADR-012: Pronunciation repository

## Status

Accepted

## Context

Podcast production needs repeatable pronunciation guidance for names, brands,
acronyms, project terms, place names, and ambiguous words. Episodic already
plans Chiltern as the evaluator that flags terms lacking pronunciation
guidance, and audio feedback can identify mispronunciations after preview
generation.

The targeted speech providers do not expose one common pronunciation surface.
Inworld can use inline International Phonetic Alphabet (IPA) guidance in TTS
text. ElevenLabs text-to-dialogue via FAL can use provider pronunciation
dictionary locators. Chatterbox via FAL does not expose a native dictionary or
phoneme field in the targeted endpoint, so it needs text-level substitutions or
downstream quality assurance.

The canonical data transfer spine remains TEI P5. Pronunciation guidance must
therefore attach to TEI-backed script and metadata rather than to a
provider-specific request string.

## Decision

Introduce a `PronunciationRepositoryPort` and versioned pronunciation-entry
model.

Entries are scoped to organizations, series, episodes, speakers, and segments.
Broader scopes can supply defaults, and narrower scopes can override them. Each
entry records:

- surface forms and match policy;
- language, locale, accent, and optional speaker applicability;
- lifecycle state, such as proposed, approved, deprecated, or rejected;
- provenance, including whether the entry came from editorial review, Chiltern
  QA, source metadata, or audio feedback;
- reviewer identity, timestamps, and the motivating TEI revision hash; and
- one or more realizations.

Realizations are provider-neutral variants of how a term can be pronounced or
compiled:

- IPA phoneme guidance;
- spelling substitutions;
- acronym expansions;
- textual pronunciation notes; and
- provider dictionary references, including provider, dictionary identifier,
  and version identifier.

The repository resolves a pronunciation pack for each TEI-derived synthesis
request. The pack hash is recorded on the speech render request for audit and
reproducibility. Adapters compile the pack according to their capability
descriptor. If a provider cannot honour a required strategy, the adapter must
return an unsupported-capability diagnostic rather than ignore the guidance.

## Rationale

Pronunciation is editorial knowledge, not a provider parameter. Storing it in a
repository lets one approved correction benefit future episodes and future
providers. Separating entries from realizations avoids treating inline IPA,
spelling hacks, and provider dictionaries as interchangeable when they have
different fidelity and portability.

TEI remains authoritative because entries cite TEI revisions and are resolved
into speech DTOs from canonical TEI speaker turns. Provider request strings are
compiled artefacts and can be regenerated when adapter rules change.

## Consequences

### Positive

- Chiltern, audio feedback, voice previews, and synthesis adapters share one
  pronunciation source of truth.
- Mispronunciation fixes can trigger partial regeneration of affected TEI
  turns only.
- Provider dictionary support can be used where available without making it
  mandatory for every adapter.
- Audit records explain who approved a pronunciation and which TEI revision it
  corrected.

### Negative

- Repository resolution introduces inheritance and override rules that need
  careful contract tests.
- Some providers will still require lower-fidelity fallback strategies such as
  spelling substitutions.
- Editors may need a review workflow for proposed entries before automatic
  re-rendering.

### Neutral

- Provider dictionaries are referenced, not copied, unless a later compliance
  decision requires storing exported dictionary contents.

## References

- Roadmap items `2.2.3` and `3.2.x` in `docs/roadmap.md`
- Design:
  `docs/episodic-podcast-generation-system-design.md#pronunciation-repository`
- ADR 011:
  `docs/adr/adr-011-tts-capability-negotiation.md`
