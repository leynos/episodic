# ADR-013: Speech synthesis adapters

## Status

Accepted

## Context

Episodic needs more than one Text-to-Speech (TTS) route so podcast rendering is
not tied to a single vendor or style of synthesis. The first provider targets
are:

- Inworld TTS and Inworld Realtime for natural host dialogue and direct
  segment rendering;
- Chatterbox via FAL for reference-audio voice cloning and expressive tags;
  and
- ElevenLabs v3 via FAL for provider-managed voices, word timings, text
  normalization, and dialogue rendering through the separate text-to-dialogue
  endpoint.

These providers differ in voice model, pronunciation support, execution shape,
streaming behaviour, timestamps, and dialogue support. Episodic must keep TEI
P5 as the canonical data spine and expose provider diversity through ports and
adapters.

## Decision

Implement the initial speech provider family as outbound adapters behind
`TTSPort` and `DialogueSpeechPort`.

`InworldTtsAdapter` implements `TTSPort` for approved segment rendering. It
maps TEI-derived text, IPA guidance, pause controls, steering cues, streaming
audio, output format preferences, and timestamp alignment onto supported
Inworld TTS features. It returns transcripts and timings when available.

`InworldRealtimeDialogueAdapter` implements `DialogueSpeechPort` for opt-in
conversation-aware rendering. It opens a session for a TEI dialogue block or
scene, renders ordered host turns, captures streamed audio and transcript
events, records session metadata, and verifies transcript drift when verbatim
output is required. Direct TTS remains the default for approved scripts that
must be spoken exactly.

`FalChatterboxTtsAdapter` implements `TTSPort` for Chatterbox through FAL. It
maps consented reference-audio voice personas to `audio_url`, compiles
supported non-verbal cues into Chatterbox text tags, maps expressiveness,
randomness, guidance, and seed controls to the request, and rejects unsupported
features such as provider voice IDs, native pronunciation dictionaries, or word
timings unless a later capability descriptor proves support.

`FalElevenV3TtsAdapter` implements `TTSPort` for ElevenLabs v3 through FAL. It
maps provider voice IDs, language code, stability, timestamp requests, and
text-normalization policy. It compiles supported bracket-style performance cues
at the adapter edge and returns word timing metadata when requested and
provided.

`FalElevenV3DialogueAdapter` implements `DialogueSpeechPort` for ElevenLabs v3
text-to-dialogue through FAL. It maps TEI speaker turns to provider dialogue
blocks, applies provider pronunciation dictionary locators when approved
entries have matching references, and marks combined dialogue outputs as less
editable unless turn-level alignment is available.

All adapters expose capability descriptors and are covered by contract
scenarios that assert either successful fulfilment or stable
unsupported-capability diagnostics. Provider-specific fields remain in adapter
mapping code and provider metadata; they are not stored as canonical TEI or
domain configuration.

## Rationale

This adapter set deliberately covers three different synthesis shapes:

- direct segment TTS for editable stems and partial regeneration;
- reference-audio cloning for voice experimentation and self-hostable future
  options; and
- dialogue rendering for more natural multi-host conversations.

Proving the contracts against all three shapes gives better evidence of
provider flexibility than implementing three similar voice-ID-only adapters. It
also keeps the roadmap honest about trade-offs: dialogue renderers may sound
more natural but can be less editable than individual stems.

## Consequences

### Positive

- Episodic can choose a provider per segment or dialogue block based on
  capabilities rather than hard-coded vendor preference.
- The Inworld realtime path is available for natural host conversations
  without replacing ordinary verbatim TTS.
- FAL-backed Chatterbox and ElevenLabs paths exercise both reference-audio and
  provider-managed voice models.
- Pronunciation and cue compilation stay at the adapter edge.

### Negative

- Each adapter needs provider-specific contract fixtures and drift monitoring
  because hosted model APIs can change.
- Dialogue renderers can produce artefacts that are harder to partially
  regenerate than per-turn stems.
- Verbatim transcript verification is necessary for session-based or otherwise
  generative render paths.

### Neutral

- The adapter family does not make any provider mandatory. Deployments can
  enable only the adapters for which credentials, consent records, and pricing
  snapshots exist.

## References

- Roadmap items `3.3.x` in `docs/roadmap.md`
- Design:
  `docs/episodic-podcast-generation-system-design.md#initial-speech-adapters`
- ADR 011:
  `docs/adr/adr-011-tts-capability-negotiation.md`
- ADR 012:
  `docs/adr/adr-012-pronunciation-repository.md`
- Inworld Realtime overview:
  <https://docs.inworld.ai/realtime/overview>
- Inworld Realtime WebSocket reference:
  <https://docs.inworld.ai/api-reference/realtimeAPI/realtime/realtime-websocket>
- FAL Chatterbox TTS:
  <https://fal.ai/models/fal-ai/chatterbox/text-to-speech/api>
- FAL ElevenLabs v3 TTS:
  <https://fal.ai/models/fal-ai/elevenlabs/tts/eleven-v3/api>
