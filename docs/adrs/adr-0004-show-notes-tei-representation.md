# ADR-004: Show-notes TEI representation

## Status

Accepted

## Context

Roadmap item `2.3.1` requires the generation pipeline to derive show notes from
template expansions and persist them as structured metadata alongside the
canonical podcast script. Episodic uses Text Encoding Initiative (TEI) P5 as
its canonical content model, so show notes must fit that spine rather than
introducing a competing document format.

The show-notes generator in `episodic/generation/show_notes.py` returns typed
entries containing:

- A topic heading
- A short summary
- An optional timestamp
- An optional locator back into the source script

The remaining design question is how those entries should be represented inside
the TEI body so that later enrichment tasks can follow a consistent pattern and
so that `tei_rapporteur` can parse and validate the result.

## Decision

Represent show notes as a thematic TEI division with a list of note items:

```xml
<div type="notes">
  <list>
    <item n="PT5M30S" corresp="#seg-intro">
      <label>Opening context</label>
      The hosts frame the episode and introduce the core question.
    </item>
  </list>
</div>
```

The representation rules are:

- Use `<div type="notes">` as the container for all show notes in the body.
- Use a child `<list>` to group individual note entries.
- Use one `<item>` per generated show-note entry.
- Use `<label>` inside `<item>` for the topic title.
- Store the summary as inline text after `<label>`, not as a nested `<p>`.
- Store timestamps in the optional `@n` attribute using ISO 8601 durations.
- Store source-script locators in the optional `@corresp` attribute.

## Rationale

This structure aligns with the implemented enrichment helper
`enrich_tei_with_show_notes(...)` and with the current `tei_rapporteur` support
for `<div>`, `<list>`, `<item>`, and `<label>`.

Using inline summary text is intentional. The current schema and parser shape
for `item` content expects label-plus-inline content, and implementation
testing showed that nested paragraphs inside `<item>` do not round-trip
correctly through the TEI tooling used by this repository.

The `<div type="notes">` pattern also provides a repeatable convention for
future metadata enrichments such as chapter markers, guest bios, or sponsor
reads without weakening TEI's role as the canonical authoring model.

## Consequences

### Positive

- Show notes remain inside the canonical TEI document rather than drifting
  into sidecar JSON.
- The representation is compact, parseable, and compatible with the current
  `tei_rapporteur` body model.
- Later enrichment tasks can reuse the same `<div type="...">` pattern.

### Negative

- Show-note summaries are constrained to inline content, which is less
  expressive than allowing arbitrary block-level markup.

### Neutral

- Prompt-facing JSON remains acceptable as a transport format for LLM calls,
  but it is a projection of the TEI-backed content model rather than a second
  canonical schema.

## References

Roadmap item `2.3.1` in `docs/roadmap.md`.[^1] ExecPlan:
`docs/execplans/2-3-1-generate-show-notes-from-template-expansions.md`.[^2]
Implementation: `episodic/generation/show_notes.py`.[^3] Tests:
`tests/test_show_notes.py`, `tests/features/show_notes.feature`,
`tests/steps/test_show_notes_steps.py`.[^4]

[^1]: Roadmap item `2.3.1` in `docs/roadmap.md`
[^2]: ExecPlan:
  `docs/execplans/2-3-1-generate-show-notes-from-template-expansions.md`
[^3]: Implementation: `episodic/generation/show_notes.py`
[^4]: Tests: `tests/test_show_notes.py`,
  `tests/features/show_notes.feature`, `tests/steps/test_show_notes_steps.py`
