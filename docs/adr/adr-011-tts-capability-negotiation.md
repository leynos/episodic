# ADR-011: Text-to-Speech capability negotiation

## Status

Accepted

## Context

Episodic needs to synthesize natural podcast speech without binding its domain
model to one Text-to-Speech (TTS) provider. The planned `TTSPort` must support
ordinary approved script rendering, partial regeneration, voice previews,
pricing, and audio feedback. New provider targets add materially different
capability surfaces:

- Inworld offers direct TTS and a session-based realtime path that can use
  conversational context.
- Chatterbox via FAL centres reference-audio voice cloning and expressive text
  tags.
- ElevenLabs v3 via FAL exposes provider-managed voices, language hints,
  optional word timestamps, text normalization, and a separate dialogue
  endpoint.

The canonical script and editorial state must remain the Text Encoding
Initiative (TEI) P5 Episodic data model. Provider request payloads can be JSON
or SDK-native structures, but they must be projections of canonical TEI rather
than competing sources of truth.

## Decision

Define speech synthesis around provider-neutral capability negotiation.

`TTSPort` remains the single-speaker segment synthesis port. It accepts
TEI-derived episode, segment, speaker-turn, and revision identifiers plus voice
reference, language hints, output preferences, execution mode, text
normalization policy, performance cues, speech variation controls,
pronunciation requirements, verbatim requirements, and idempotency keys. It
returns provider-agnostic audio artefacts, transcripts, timings, warnings,
usage metadata, and provider request identifiers.

Add `DialogueSpeechPort` as a separate optional port for providers that render
ordered multi-speaker turns as one conversation-aware artefact. Dialogue
rendering is not a subtype of segment rendering because it may return a
combined file, use session context, and have weaker partial-regeneration
properties.

Every adapter exposes a `TtsProviderCapabilities` descriptor covering:

- provider and model identity;
- maximum text length;
- supported execution modes, including blocking, queue, streaming, and webhook
  resume;
- supported voice-reference kinds, including provider voice ID, managed voice
  profile, and consented reference audio;
- supported output formats, timing metadata, language hints, text
  normalization, performance cues, and speech variation controls;
- supported pronunciation strategies; and
- whether dialogue rendering is supported.

The Audio Synthesis StateGraph validates requested behaviour against the
descriptor before dispatch. If a provider cannot satisfy required behaviour,
the graph rejects the request with a stable unsupported-capability diagnostic
or selects a compatible fallback provider. Adapters must not silently drop
requested capabilities.

## Rationale

Provider parameters are not stable architecture. Treating `stability`, `cfg`,
`audio_url`, realtime sessions, pronunciation dictionaries, inline IPA, and
timestamps as domain fields would make the first provider implementation
load-bearing. A capability descriptor lets the domain ask for speech behaviour
in its own vocabulary and lets adapters state what they can actually deliver.

The separate dialogue port protects approved scripts. Segment synthesis means
"speak this TEI turn verbatim and return an editable stem." Dialogue synthesis
means "render these ordered TEI turns with conversation-level context." Both
are useful, but they have different editability, transcript verification, and
regeneration semantics.

## Consequences

### Positive

- The domain can route between Inworld, Chatterbox via FAL, ElevenLabs v3 via
  FAL, and future engines without changing canonical TEI.
- Unsupported provider behaviour becomes visible before money is spent on a
  synthesis call.
- Direct segment rendering and conversation-aware rendering can evolve without
  overloading one port.
- Cost, timing, transcripts, and provider request metadata can be captured
  consistently across adapters.

### Negative

- Adapter authors must maintain capability descriptors and contract tests
  alongside request mapping code.
- The request model is broader than the first concrete adapter needs.
- The selector can only be as accurate as the descriptors and provider tests
  that back them.

### Neutral

- Provider-specific escape hatches may exist inside adapter-owned metadata,
  but they are not canonical episode data and must not be required by ordinary
  orchestration code.

## References

- Roadmap items `3.1.x` and `3.3.x` in `docs/roadmap.md`
- Design:
  `docs/episodic-podcast-generation-system-design.md#speech-synthesis-contracts`
- Inworld Realtime and TTS documentation:
  <https://docs.inworld.ai/realtime/overview>
- FAL Chatterbox TTS documentation:
  <https://fal.ai/models/fal-ai/chatterbox/text-to-speech/api>
- FAL ElevenLabs v3 TTS documentation:
  <https://fal.ai/models/fal-ai/elevenlabs/tts/eleven-v3/api>
