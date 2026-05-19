# ADR-010: Guest-bios TEI representation

## Status

Accepted

## Context

Roadmap item `2.3.3` requires the generation pipeline to retrieve guest profile
reference documents and format biographical summaries within the canonical Text
Encoding Initiative (TEI) body. Episodic already represents generated show
notes as a body `<div>` containing a `<list>` of `<item>` elements, as recorded
in ADR 004.[^1]

TEI P5 also offers richer personography structures for formal descriptions of
people. Those structures are suitable for stable participant metadata, but this
feature produces episode-facing generated biographies from pinned guest profile
reference-document revisions. The generated material therefore belongs in the
episode body, where content enrichment output is already represented.

## Decision

Represent generated guest biographies as a thematic TEI division with a list of
guest items:

For screen readers: example XML representation of guest biographies with list
items containing name labels, biography text, and external revision links.

```xml
<div type="guest-bios">
  <list>
    <item n="Mathematician"
          corresp="urn:episodic:reference-document-revision:019e1368">
      <label>Ada Lovelace</label>
      Ada Lovelace writes about analytical engines.
    </item>
  </list>
</div>
```

The representation rules are:

- Use `<div type="guest-bios">` as the canonical container in the TEI body.
- Use a child `<list>` to group generated guest biographies.
- Use one `<item>` per resolved guest profile reference-document revision.
- Use `<label>` inside `<item>` for the guest display name.
- Store the generated biography as inline text after `<label>`.
- Store the optional guest role in `@n`.
- Store the pinned reference-document revision identifier in `@corresp`.

## Rationale

This shape extends the accepted ADR 004 enrichment convention without adding a
sidecar content format. It keeps TEI P5 as the canonical parser/emitter
boundary, while still allowing prompt-facing JSON as a transient LLM transport
format.

`@corresp` is used for the source revision link because the pinned reference
document revision is external to the TEI document and `tei_rapporteur` exposes
`Item.corresp` as a pointer list. The project currently does not require
stricter TEI provenance semantics such as `@source` on `<item>`, so that is
left as a future library and representation enhancement rather than a
requirement for roadmap item `2.3.3`.

## Consequences

### Positive

- Guest biographies remain inside the canonical TEI body.
- The representation round-trips through the pinned `tei_rapporteur`
  parser/emitter.
- Generated biographies preserve a direct link back to the pinned profile
  revision used as source material.
- The show-notes and guest-bios enrichments share the same body-level
  structural pattern.

### Negative

- Generated biographies are constrained to inline item content rather than
  arbitrary nested block markup.

### Neutral

- Formal TEI personography can still be added later for stable person metadata
  without changing the body representation for episode-facing generated bios.

## References

ADR 004 show-notes TEI representation.[^1] ExecPlan for roadmap item
`2.3.3`.[^2] Implementation: `episodic/generation/guest_bios.py`.[^3]

[^1]: `docs/adr/adr-004-show-notes-tei-representation.md`
[^2]: `docs/execplans/2-3-3-generate-guest-bios-from-reference-document-bindings.md`
[^3]: `episodic/generation/guest_bios.py`
