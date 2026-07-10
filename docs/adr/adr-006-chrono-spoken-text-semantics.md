# ADR-006: Chrono spoken-text semantics for TEI P5 scripts

## Status

Proposed

## Context

Roadmap item `2.2.6` introduces Chrono, a deterministic quality-assurance (QA)
estimator for anticipated spoken runtime. Chrono operates on canonical Text
Encoding Initiative (TEI) P5 scripts and records estimator metadata so later
implementations can be compared with the first local baseline.

The current Chrono implementation extracts text with local XML (Extensible
Markup Language) traversal. That is no longer an acceptable ownership boundary.
Episodic treats valid TEI P5 XML as the enforced interchange format, and
`tei-rapporteur` is the shared parser and projection library for TEI P5. Chrono
may own runtime-estimation policy, but it must not define TEI parsing or
spoken-dialogue semantics locally.

This decision defines what counts as spoken script text for runtime estimation.
It also defines the extraction behaviour that `tei-rapporteur` must expose
before Chrono replaces its local TEI traversal.

## Decision

Chrono estimates only words that are intended to be performed aloud by a host,
narrator, guest, actor, or other scripted voice. Chrono does not estimate
metadata, editorial notes, citations, show notes, headings, speaker labels, or
stage directions.

### Spoken containers and spoken leaves

Episodic uses these TEI P5 elements for spoken-runtime extraction:

- `<sp>` is a speech container. It groups one speaker turn and provides context
  for child spoken blocks. Its own descendant text is not counted wholesale,
  because it may contain speaker labels, stage directions, notes, and multiple
  spoken blocks.
- `<u>` is an utterance container. It groups one spoken utterance. If it
  contains direct textual content and no child spoken block, that direct text
  is a spoken segment. If it contains child spoken blocks, those child blocks
  define the spoken segments.
- `<p>` is a spoken prose block when it appears in the script body outside an
  excluded structure. Its descendant inline text contributes to one spoken
  segment, except for excluded descendants.
- `<ab>` is a spoken anonymous block under the same rule as `<p>`.
- `<l>` is a spoken line under the same rule as `<p>`. Verse, poem, or
  line-broken performance text is therefore estimable without flattening it
  into a paragraph first.
- `<seg>` is inline spoken segmentation. Inside an enclosing spoken block it is
  not a separate counted segment; its text contributes to the enclosing
  segment. If the Episodic TEI P5 profile accepts a standalone `<seg>` in a
  spoken context and there is no enclosing spoken block, it is a spoken segment.
- Inline descendants such as emphasis, highlighting, and pause markup are not
  independent spoken containers. Their text contributes only when they appear
  inside a counted spoken segment and are not inside an excluded element.

This mapping is the application-level semantic contract. If a future TEI
profile changes any of these meanings, the ADR must be superseded before
Chrono, QA orchestration, or `tei-rapporteur` behaviour changes.

### Excluded content

The extractor must exclude the following elements and their descendants from
spoken-runtime text:

- speaker labels, including `<speaker>` and label-like metadata;
- stage directions, including `<stage>`;
- notes and editorial annotations, including `<note>`;
- lists and list entries, including `<list>`, `<item>`, and `<label>`;
- headings and titles, including `<head>`;
- references and citation structures, including `<ref>`, `<ptr>`, `<bibl>`,
  and bibliographic descendants;
- show-note blocks represented as `<div type="notes">`; and
- TEI header, stand-off metadata, source descriptions, revision history, and
  any other document metadata outside the body performance script.

If excluded markup appears inside an otherwise spoken block, it creates a
boundary but contributes no words. For example, a spoken paragraph with an
inline note counts the paragraph text before and after the note, but not the
note text.

### Nested spoken text

Text must be counted exactly once.

`tei-rapporteur` must identify the outermost counted spoken block for each
piece of text. Inline segmentation inside that block is part of the same spoken
segment, not a second segment. For example:

```xml
<p>Hello <seg>there</seg></p>
```

This produces one spoken segment with the normalized text `Hello there`. It
must not produce both `Hello there` and `there`.

Speech containers may contain multiple spoken blocks. For example:

```xml
<sp>
  <speaker>Host</speaker>
  <p>First line.</p>
  <p>Second line.</p>
</sp>
```

This produces two spoken segments, `First line.` and `Second line.`. It must
not count `Host`, and it must not count the whole `<sp>` subtree as a third
segment.

### Text normalization before tokenization

`tei-rapporteur` must return spoken text segments in document order with stable
normalization:

- Trim leading and trailing whitespace from each segment.
- Collapse runs of XML text whitespace to a single American Standard Code for
  Information Interchange (ASCII) space.
- Treat excluded inline elements as word boundaries.
- Resolve XML entities through normal XML parsing.
- Preserve punctuation characters in the returned text; Chrono's tokenizer
  decides whether punctuation affects word boundaries.
- Preserve emphasis text, but discard emphasis markup.
- Represent pause, gap, and break markup as a boundary that contributes no word.
- Do not expand abbreviations, numbers, symbols, references, or pronunciation
  hints during the initial Chrono estimate.

Chrono then applies its versioned word-token heuristic to the normalized
segments. The initial `chrono-naive-word-count` estimator counts Latin-script
word tokens using the current baseline token pattern: an ASCII letter followed
by zero or more ASCII letters, digits, apostrophes, or hyphens.

The initial estimator therefore treats contractions and hyphenated terms as one
word token, counts alphanumeric terms that begin with a letter, and does not
count pure numbers as words. Non-English scripts are in scope for extraction
and provenance, but they are outside the initial naive token-counting scope
unless they also contain tokens matched by the versioned baseline pattern. A
future estimator may broaden language and numeric handling by changing the
estimator version and documenting the new token policy.

### Validation and failure policy

Chrono input must be valid XML and must validate against the Episodic TEI P5
profile accepted by `tei-rapporteur`. Malformed XML, invalid TEI P5, and TEI
documents that do not satisfy the Episodic profile are hard failures.

Chrono must not fall back to raw-text counting. It must not estimate from
partial parse results. It must not silently ignore validation failures.

`tei-rapporteur` should expose deterministic error types or stable error
messages that let Chrono raise a domain validation error without parsing
unstable implementation strings. The error should distinguish malformed XML
from structurally invalid TEI P5 where practical, but both cases block runtime
estimation.

### Required `tei-rapporteur` extraction contract

`tei-rapporteur` must expose a Python-callable application programming
interface (API) that:

- accepts a complete TEI P5 XML document string;
- validates it using the same parser and Episodic profile as `parse_xml(...)`;
- returns ordered spoken text segments;
- includes normalized text for each segment;
- includes provenance for each segment, such as an `xml:id`, XML Path Language
  (XPath)-like locator, event path, or equivalent stable location;
- excludes the content defined in this ADR;
- avoids nested double-counting; and
- exposes typed Python structures suitable for `make typecheck`.

The API may be implemented as a direct spoken-text iterator or as a projection
over typed parser events, but Episodic callers must not need to reimplement the
semantic rules from this ADR.

## Rationale

Chrono's runtime estimate is only meaningful if every component agrees on what
the spoken script is. Leaving that mapping inside Chrono would create a second
TEI domain model beside `tei-rapporteur`, and small differences would change
reported episode runtime.

Using `tei-rapporteur` as the extraction boundary keeps TEI validation, profile
knowledge, document-order traversal, and locator provenance in one place.
Chrono remains responsible for the estimator: token counting, words-per-minute
configuration, duration rounding, and metadata.

The mapping deliberately treats `<sp>` and `<u>` as grouping containers rather
than simple `itertext()` sources. That preserves speaker-turn structure and
prevents speaker labels, notes, and child blocks from being counted twice.

The initial token policy stays narrow because `chrono-naive-word-count` is a
baseline estimator, not a linguistic model. Keeping the token pattern versioned
and visible makes later improvements comparable rather than silently changing
historical runtime estimates.

Chrono is Python application code, so Kani and Verus are out of scope for its
numeric arithmetic. Those tools verify Rust code and cannot be applied directly
to `episodic/qa/chrono.py`. Chrono instead uses CrossHair with Python PEP 316
contracts around the pure `_compute_estimated_seconds(...)` helper. CrossHair
symbolically checks the same safety boundary that matters for the estimator:
valid inputs have a non-negative word count and positive words-per-minute
setting, zero words produce zero seconds, and positive word counts use the
documented integer-only ceiling formula. The surrounding dataclass guards
enforce the same input preconditions at Chrono's runtime boundaries.

## Consequences

### Positive

- Episodic has one explicit spoken-text semantic contract for runtime
  estimation.
- Chrono can reject invalid input instead of producing misleading estimates
  from malformed XML.
- `tei-rapporteur` receives a concrete, testable extraction surface that serves
  Chrono and any future spoken-script consumer.
- Nested inline segmentation can no longer inflate runtime estimates by
  double-counting child text.
- Chrono now has a Python-native symbolic verification gate for the
  deterministic duration arithmetic without adding a Rust verification
  toolchain to this repository.

### Negative

- Chrono remains blocked until `tei-rapporteur` exposes the spoken-text
  extraction API described above.
- Existing Chrono tests that use minimal TEI-shaped snippets must be replaced
  with valid TEI P5 fixtures.
- Non-Latin scripts and pure numeric speech are undercounted by the first naive
  estimator unless a later version broadens tokenization.
- CrossHair covers the pure numeric helper only. It does not replace the
  behavioural, property, or TEI-validation tests that exercise Chrono's parser
  boundary and orchestration side effects.

### Neutral

- Show notes remain valid TEI body content, but they are not spoken-runtime
  content.
- JSON projections remain acceptable for prompts and test helpers, but TEI P5
  remains the canonical script interchange format.
- Later estimators may use richer tokenization, speech-rate models, language
  metadata, or audio evidence if they change estimator identity or version.

## Deferred work

- Implement the `tei-rapporteur` spoken-text extraction API.
- Replace Chrono's local XML traversal and malformed-XML fallback with the
  `tei-rapporteur` API.
- Update Chrono tests to use valid TEI P5 fixtures and validation-failure
  assertions.
- Decide whether future runtime estimators should use language-specific
  tokenization or pronunciation dictionaries.

## References

- Roadmap item `2.2.6` — `docs/roadmap.md`
- ExecPlan —
  `docs/execplans/2-2-6-chrono-runtime-estimator.md`
- Show-notes TEI representation —
  `docs/adr/adr-004-show-notes-tei-representation.md`
- TEI parser guide — `docs/tei-rapporteur-users-guide.md`
- Chrono implementation — `episodic/qa/chrono.py`
