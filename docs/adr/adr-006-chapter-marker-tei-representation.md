# ADR-006: Chapter-marker TEI representation

## Status

Accepted

## Context

Roadmap item `2.3.2` requires the generation pipeline to create chapter markers
aligned to script segments and to include timing metadata suitable for
podcast-player projection. Episodic keeps generated content inside the
canonical Text Encoding Initiative (TEI) document, so chapter markers must be
represented as TEI body metadata rather than as a separate sidecar format.

Existing profile and template fixtures represent segment ordering as structured
metadata, for example `{"segments": ["intro", "main", "outro"]}`. Current TEI
fixtures do not define a dedicated segment element convention. The chapter
generator therefore accepts explicit segment metadata for prompt construction
and uses optional TEI locators to connect generated chapters back to source
segments when such locators are available.

## Decision

Represent chapter markers as a thematic TEI division with a list of chapter
items:

```xml
<div type="chapters">
  <list>
    <item n="PT5M30S" corresp="#seg-main">
      <label>Main discussion</label>
      The hosts move from setup into the central interview.
    </item>
  </list>
</div>
```

The representation rules are:

- Use `<div type="chapters">` as the container for all chapter markers.
- Use a child `<list>` to group chapter entries.
- Use one `<item>` per generated chapter marker.
- Use `<label>` inside `<item>` for the chapter title.
- Store the optional chapter summary as inline text after `<label>`.
- Store the chapter start time in required `@n` using an integer-only
  ISO 8601-style `PT#H#M#S` duration. Days and fractional units are not
  accepted by this milestone's parser.
- Store source-segment locators in optional `@corresp`.
- Replace an existing `<div type="chapters">` block during enrichment so the
  operation is idempotent.

The generator data transfer object (DTO) also validates optional `end` and
`duration` fields returned by an LLM. Those fields are not emitted into TEI in
this milestone because the current `tei_rapporteur` payload model does not
preserve an attempted `dur` attribute on `<item>`.

## Rationale

This structure follows the show-notes pattern defined in
[`ADR-004`](adr-004-show-notes-tei-representation.md). It keeps enrichment
metadata in the canonical TEI document and uses TEI elements that
`tei_rapporteur` already parses, validates, and emits.

Using required `@n` values gives later audio mastering code enough canonical
timing metadata to project chapters into podcast-player formats such as ID3,
MP4 chapters, or sidecar JSON. Player-specific output remains outside this
milestone.

## Consequences

### Positive

- Chapter markers remain inside the canonical TEI document.
- Chapter starts are explicitly ordered, non-negative integer-only
  ISO 8601-style `PT#H#M#S` durations.
- The representation reuses the established enrichment convention.
- Re-running enrichment replaces the existing chapter block rather than
  appending duplicates.

### Negative

- Optional chapter end and duration values are validated but not persisted in
  TEI until the TEI tooling exposes a supported attribute for them.

### Neutral

- Segment alignment is prompt-facing metadata plus optional `@corresp`
  locators. A future task can introduce a richer canonical segment element if
  the wider TEI model settles on one.

## References

Roadmap item `2.3.2` in `docs/roadmap.md`.[^1] ExecPlan: `docs/execplans/2-3-2-generate-chapter-markers-aligned-to-script-segments.md`.[^2]
Implementation: `episodic/generation/chapter_markers.py`.[^3] Tests:
`tests/test_chapter_markers.py`, `tests/features/chapter_markers.feature`,
`tests/steps/test_chapter_markers_steps.py`.[^4]

[^1]: Roadmap item `2.3.2` in `docs/roadmap.md`
[^2]: ExecPlan:
  `docs/execplans/2-3-2-generate-chapter-markers-aligned-to-script-segments.md`
[^3]: Implementation: `episodic/generation/chapter_markers.py`
[^4]: Tests: `tests/test_chapter_markers.py`,
  `tests/features/chapter_markers.feature`,
  `tests/steps/test_chapter_markers_steps.py`
