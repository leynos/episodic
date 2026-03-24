# Align Pedante implementation with revised ADR 001

This ExecPlan (execution plan) is a living document. The sections
`Constraints`, `Tolerances`, `Risks`, `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work
proceeds.

Status: DRAFT

## Purpose and big picture

Pedante already exists in `episodic/qa/`, but the shipped implementation still
reflects the original single-pass design: it sends one prompt containing raw
TEI XML and source packets, then parses one structured response. The revised
Architecture Decision Record (ADR) at
`docs/adr-001-pedante-evaluator-contract.md` now requires a more specific
internal design. Pedante must remain TEI-first, use the richer `tei-rapporteur`
citation model, and be free to execute internally as two passes:

1. a claim-catalogue pass that identifies claims and harvests existing TEI
   citation links, and
2. a claim-support verification pass that checks whether those citations
   justify the claims.

After this change, the application layer should still call one Pedante
evaluator and receive one `PedanteEvaluationResult`. The externally visible
contract remains stable. The internal workflow, however, should become
citation-aware, cost-aware, and explicit about how it uses utterance-local TEI
provenance such as `@source`, `@resp`, `@cert`, `@corresp`, `@ana`, and
header-level `refsDecl` declarations. If JSON is used for prompt construction,
it must come from the canonical TEI P5 model through the `tei_rapporteur`
`msgspec.Struct` or builtins projection rather than from an ad hoc schema.

Success is observable in seven ways:

1. Unit tests show that Pedante now derives claim context from TEI-backed
   projections rather than treating the script as opaque XML text.
2. Unit tests show that the evaluator performs two internal passes while
   keeping the same public `evaluate(...) -> PedanteEvaluationResult` contract.
3. Claim-catalogue tests cover utterance-local citation metadata,
   `refsDecl`-backed citation declarations, and explicit "citation absent"
   outcomes.
4. Verification tests show that pass-two findings remain claim-centric and can
   still emit uncatalogued findings when verification discovers a missed claim.
5. Behavioural tests (`pytest-bdd`) using Vidai Mock prove that one Pedante
   evaluation can drive two LLM calls and still return aggregated usage metrics.
6. The design, user, and developer documentation explain the new internal
   flow, and any newly pinned durable data shape is captured in an additional
   ADR if required.
7. The required validation commands pass sequentially:
   `make check-fmt`, `make test`, `make typecheck`, `make lint`,
   `PATH=/root/.bun/bin:$PATH make markdownlint`, and `make nixie`.

This plan is a follow-on plan. It supersedes the earlier "Pedante is complete"
record in this file and now describes the refactor needed to bring the code
into line with the amended ADR.

## Constraints

- Preserve the existing external Pedante contract unless a new ADR and explicit
  user approval say otherwise. The application layer should continue to call a
  single Pedante evaluator and receive a single `PedanteEvaluationResult`.
- Keep Text Encoding Initiative (TEI) P5 as the canonical data spine. Pedante
  may parse TEI XML into `tei_rapporteur` structures or builtins for prompt
  construction, but it must not define a competing canonical script schema.
- Ground citation handling in the TEI model now documented in
  `docs/tei-rapporteur-users-guide.md`. Utterance-local provenance and citation
  attributes, plus header-level `refsDecl`, are the primary citation sources
  for Pedante.
- Keep LangGraph concerns in the application layer only. Domain-level Pedante
  types and helpers must not import graph internals, queue adapters, Falcon,
  SQLAlchemy, or HTTP client details.
- Keep all model calls behind `episodic.llm.LLMPort`. Both Pedante passes must
  use the existing provider-neutral port.
- Retain claim-centric findings. Do not regress to whole-document labels or
  prose-only evaluator summaries.
- Preserve Vidai Mock as the behavioural inference harness.
- Use test-first workflow for each milestone. Modify or add tests first, run
  them to confirm failure, implement the change, then rerun the same tests.
- Record any new durable representation choice in an ADR if implementation
  pins it down. Examples include a reusable internal claim-catalogue shape, a
  stable per-pass diagnostics object, or a shared TEI-to-builtins projection
  contract that other evaluators will depend on.
- Keep `docs/roadmap.md` truthful. The roadmap entry is already marked done, so
  do not toggle it unless the implementation reveals the current status is
  misleading and the user explicitly wants that corrected.

## Tolerances

- Interface tolerance: stop and escalate if aligning Pedante with ADR 001
  requires changing the signature or required fields of
  `PedanteEvaluationRequest`, `PedanteFinding`, or `PedanteEvaluationResult`.
- Scope tolerance: stop and escalate if implementation appears to require more
  than 14 files or 900 net new lines before a working vertical slice exists.
- Dependency tolerance: stop and escalate if a new runtime dependency is
  required. The current branch already has `langgraph` and `tei-rapporteur`.
- TEI tooling tolerance: stop and escalate if the installed Python surface of
  `tei_rapporteur` cannot supply the required builtins or struct projection
  without first changing the dependency pin.
- Usage tolerance: stop and escalate if the revised design cannot aggregate
  usage cleanly without inventing a new public result shape.
- Ambiguity tolerance: stop and escalate if there are multiple plausible
  durable shapes for internal claim-catalogue data and the choice would affect
  later evaluators or cost-accounting code.
- Iteration tolerance: stop and escalate after three failed attempts to settle
  the same test cluster or behaviour scenario.

## Risks

- Risk: the current implementation keeps the script as raw `script_tei_xml`
  text until prompt rendering, so the refactor may expose hidden assumptions in
  tests and prompt helpers. Severity: high. Likelihood: high. Mitigation:
  introduce fail-first tests around TEI projection and citation harvesting
  before changing evaluation flow.

- Risk: utterance-local citation metadata and `refsDecl` may not map one-to-one
  onto existing `PedanteSourcePacket.source_id` values. Severity: high.
  Likelihood: medium. Mitigation: define and test the mapping policy early, and
  record it in an ADR if it becomes a durable shared contract.

- Risk: a cheap claim-catalogue pass may miss claims that the verifier would
  have found in the old single-pass design. Severity: high. Likelihood: medium.
  Mitigation: require the verifier to emit uncatalogued claims and add tests
  for that escape hatch.

- Risk: the current result shape only exposes one `LLMUsage` object plus one
  set of provider metadata. Severity: medium. Likelihood: high. Mitigation:
  aggregate usage totals into the existing result and keep any per-pass
  diagnostics internal unless a new ADR deliberately widens the stable shape.

- Risk: Vidai Mock scenarios will need to prove two deterministic LLM
  interactions from one evaluator call, which is more complex than the current
  one-response behaviour test. Severity: medium. Likelihood: medium.
  Mitigation: drive the two passes with explicit template fixtures and assert
  the request count plus the combined usage.

- Risk: LangGraph state may be tempted to carry internal claim-catalogue data
  permanently once it exists. Severity: medium. Likelihood: medium. Mitigation:
  keep internal pass artefacts local to Pedante or, if temporarily surfaced in
  graph state for routing or debugging, keep them namespaced and explicitly
  non-canonical.

## Progress

- [x] (2026-03-19 01:43Z) The original Pedante implementation landed as a
  single-pass evaluator with typed findings, a minimal LangGraph seam, Vidai
  Mock behavioural tests, and ADR 001.
- [x] (2026-03-24 13:00Z) ADR 001 was amended to require TEI citation-spine
  awareness and to allow an internal two-pass Pedante design.
- [x] (2026-03-24 13:30Z) The current implementation was re-inspected. The code
  still uses one `build_prompt(...)` path over raw TEI XML and one
  `LLMPort.generate(...)` call per evaluation.
- [x] (2026-03-24 13:45Z) This ExecPlan was revised to describe ADR-alignment
  work rather than the already-completed first implementation.
- [ ] Stage A: add fail-first tests that capture the gap between the current
  single-pass code and the amended ADR.
- [ ] Stage B: introduce TEI-aware internal projection and citation-harvesting
  helpers.
- [ ] Stage C: implement the claim-catalogue pass.
- [ ] Stage D: implement the claim-support verification pass and aggregate
  usage.
- [ ] Stage E: update the LangGraph seam and behavioural tests for the revised
  internals.
- [ ] Stage F: update docs and record any newly pinned durable data shapes in
  ADRs.
- [ ] Stage G: run the full validation gates and update this ExecPlan with the
  delivery outcome.

## Surprises & Discoveries

- Observation: `episodic/qa/pedante.py` currently defines the complete Pedante
  contract and service in one file, with `PedanteEvaluator.build_prompt(...)`
  serializing raw `script_tei_xml` plus source packets into a single prompt.
  Evidence: local inspection on 2026-03-24. Impact: the refactor can stay
  focused if it introduces internal helpers first, rather than immediately
  splitting modules unless code size demands it.

- Observation: `PedanteEvaluationResult` already exposes only one aggregated
  `LLMUsage` value and one set of provider metadata. Evidence:
  `episodic/qa/pedante.py` inspection on 2026-03-24. Impact: the revised design
  should aggregate pass usage into the current public result and keep per-pass
  details internal unless another ADR widens the stable contract.

- Observation: the updated `tei-rapporteur` guide now documents utterance-local
  citation attributes, `refsDecl`, stand-off citation overlays, and Python
  `msgspec.Struct` projections with TEI pointer-list attributes normalized to
  `list[str]`. Evidence: `docs/tei-rapporteur-users-guide.md` on `origin/main`.
  Impact: the plan should favour a TEI-to-builtins projection step over prompt
  assembly from opaque XML text.

- Observation: the current behavioural tests prove one structured evaluator
  response, not a multi-step evaluation pipeline. Evidence:
  `tests/test_pedante.py`, `tests/test_pedante_langgraph.py`, and
  `tests/steps/test_pedante_steps.py` inspection on 2026-03-24. Impact: the
  revised tests must become the primary safety net for the two-pass refactor.

- Observation: `leta` could not be used for code navigation in this
  environment because the local `basedpyright` language-server dependency is
  missing. Evidence: `leta grep ...` failed with
  `Language server 'basedpyright' for python failed to start`. Impact: code
  inspection for this plan fell back to direct file reads.

## Decision Log

- Decision: keep the public Pedante contract stable and express the two-pass
  change as an internal refactor. Rationale: ADR 001 explicitly says the
  application layer still calls one Pedante evaluator and receives one
  `PedanteEvaluationResult`. Date/Author: 2026-03-24 / Codex.

- Decision: prefer a TEI-backed builtins or `msgspec.Struct` projection as the
  working representation inside Pedante instead of extracting citations from
  raw XML text by string processing. Rationale: the revised ADR and the updated
  `tei-rapporteur` guide both make that projection the preferred JSON shape for
  prompt construction and preserve TEI pointer semantics more faithfully.
  Date/Author: 2026-03-24 / Codex.

- Decision: treat citation harvesting as a first-class internal step before
  verification. Rationale: the amended ADR says Pedante should use utterance
  citation metadata and `refsDecl` as the citation spine rather than
  reconstructing citations ad hoc from prose. Date/Author: 2026-03-24 / Codex.

- Decision: aggregate usage into the existing public result unless
  implementation proves that later orchestration needs durable per-pass usage
  objects. Rationale: widening the stable contract would be a representation
  decision that needs explicit ADR coverage and likely user review.
  Date/Author: 2026-03-24 / Codex.

## Outcomes & Retrospective

No ADR-alignment implementation has started yet. The current outcome is a
revised, self-contained plan that starts from the shipped single-pass code and
defines the staged refactor needed to satisfy amended ADR 001.

Expected outcome after implementation:

- Pedante keeps the same external contract.
- Pedante internally performs citation-aware claim cataloguing followed by
  support verification.
- TEI utterance citations and `refsDecl` data become the primary citation
  spine for claim checking.
- Vidai Mock behavioural coverage proves the two-pass flow and aggregated usage
  accounting.

## Context and orientation

The codebase already contains a working first version of Pedante:

- `episodic/qa/pedante.py` defines:
  `PedanteSourcePacket`, `PedanteEvaluationRequest`, `PedanteFinding`,
  `PedanteEvaluationResult`, `PedanteEvaluatorConfig`, and `PedanteEvaluator`.
- `episodic/qa/langgraph.py` defines the minimal LangGraph seam:
  `PedanteGraphState`, `route_after_pedante(...)`, and
  `build_pedante_graph(...)`.
- `tests/test_pedante.py` covers DTO validation, JSON parsing, and one
  successful single-pass evaluation.
- `tests/test_pedante_langgraph.py` covers the minimal graph routing seam.
- `tests/features/pedante.feature` and `tests/steps/test_pedante_steps.py`
  cover the Vidai Mock-backed behaviour path.
- `docs/adr-001-pedante-evaluator-contract.md` now requires TEI citation-spine
  awareness and permits a two-pass internal evaluator.
- `docs/tei-rapporteur-users-guide.md` is the authoritative guide to the
  current TEI projection model.
- `docs/langgraph-and-celery-in-hexagonal-architecture.md` is the governing
  guidance for keeping graph state non-canonical and ports-only.

Terms used in this plan:

- Claim catalogue pass: the first Pedante pass that identifies candidate claims
  and harvests citation context from the TEI-backed script representation.
- Citation spine: the canonical TEI sources of citation truth used by Pedante,
  especially utterance-local provenance attributes and header-level `refsDecl`.
- Verification pass: the second Pedante pass that checks whether the cited
  sources justify the catalogued claims.
- Builtins projection: a nested tree of normal Python objects derived from
  `tei_rapporteur` or `msgspec` that preserves the TEI structure without
  forcing prompt code to parse raw XML text.
- Uncatalogued claim: a claim that the verifier discovers even though the
  catalogue pass did not emit it. The revised ADR allows this escape hatch to
  avoid making pass one the hard recall ceiling.

The current gap to the amended ADR is straightforward:

- the script is still treated as raw TEI XML until prompt rendering,
- citation harvesting from utterances and `refsDecl` does not exist,
- Pedante does not yet have a distinct claim-catalogue pass,
- Pedante performs only one `LLMPort.generate(...)` call per evaluation, and
- behavioural tests do not yet prove aggregated usage across multiple passes.

## Plan of work

### Stage A: capture the ADR gap with fail-first tests

Start by updating the existing Pedante tests so they describe the amended ADR,
not the old implementation. The objective of this stage is to make the gap
between current code and target behaviour explicit and reviewable before
refactoring production code.

Extend `tests/test_pedante.py` with new failing tests for:

- a TEI-backed internal projection step that can expose utterance-local
  citation lists and relevant `refsDecl` content,
- a claim-catalogue result shape or helper that preserves claim text, claim
  kind, and citation bindings derived from TEI rather than from prompt prose,
- explicit citation-absent handling for claims that lack a usable TEI citation
  binding,
- aggregation of usage from more than one `LLMResponse`,
- verifier-emitted uncatalogued claims, and
- stable final `PedanteEvaluationResult` behaviour after internal aggregation.

Update `tests/test_pedante_langgraph.py` so it continues to assert the same
external routing outcome while tolerating the evaluator's new internal
multi-pass workflow.

Update `tests/features/pedante.feature` and `tests/steps/test_pedante_steps.py`
so the behavioural story reflects one Pedante evaluation triggering two model
interactions and returning combined usage totals.

Acceptance for Stage A:

- the modified unit and behavioural tests fail against the current single-pass
  implementation, and
- the failure messages clearly point to missing citation harvesting,
  multi-pass orchestration, or usage aggregation rather than vague prompt
  regressions.

### Stage B: introduce TEI-aware internal projection and citation harvesting

Add a bounded internal representation for the script and its citation context.
This representation does not replace the public request DTO. It exists so
Pedante can parse the canonical TEI once, then work with structured data.

Implement a helper in `episodic/qa/pedante.py` or a nearby internal module that
accepts `PedanteEvaluationRequest.script_tei_xml` and produces a Pedante-local
projection using `tei_rapporteur` parsing plus a builtins or `msgspec.Struct`
view. The helper should make it easy to access:

- utterances and paragraphs in order,
- utterance-local `source`, `resp`, `cert`, `corresp`, and `ana` values as
  explicit lists,
- `refsDecl` declarations from the TEI header, and
- any other document identifiers needed to map claims back to TEI locations.

At this stage, also implement the citation-harvesting rule that maps TEI
pointer values to the bounded `PedanteSourcePacket` list. This is where the
plan must settle how utterance-local TEI citations correspond to
`PedanteSourcePacket.source_id`.

If that mapping becomes a durable shared contract rather than a Pedante-local
helper, add a follow-on ADR during Stage F. Do not let that decision remain
implicit in tests.

Acceptance for Stage B:

- tests prove that Pedante can derive citation bindings from TEI-backed data
  without string-parsing XML in prompt code, and
- the citation-harvesting helper is pure, deterministic, and free of LangGraph
  or transport concerns.

### Stage C: implement the claim-catalogue pass

Add the first internal Pedante pass. This pass may keep using the same model as
the verifier initially, but the code must treat it as a separate step so it can
later swap to a cheaper model without changing the contract.

Define an internal claim-catalogue data shape. It should be rich enough to
carry:

- claim identifier,
- claim text,
- claim kind,
- TEI location or originating utterance or paragraph identifier,
- harvested citation bindings, and
- any flag or precomputed note needed to emit a final citation-absent finding.

Keep this data shape internal unless implementation proves it will be reused by
other evaluators. If it becomes a stable cross-evaluator contract, record that
decision in an ADR during Stage F.

Implement prompt construction for pass one from the TEI-backed projection
rather than from raw XML text alone. The catalogue prompt should instruct the
model to identify claims, classify claim kind, and preserve the TEI citation
context already present in the document. If a claim that should carry citation
has no usable citation binding, the pass should surface that fact explicitly.

Acceptance for Stage C:

- unit tests prove that the catalogue pass emits claims with TEI-derived
  citation context,
- citation-absent cases are represented explicitly, and
- Pedante can proceed to verification without changing the public evaluator
  signature.

### Stage D: implement the support-verification pass and usage aggregation

Add the second internal Pedante pass. It should receive the catalogued claims
plus the bounded source packets and decide whether the cited source material
supports each claim.

The verifier should continue to emit the existing claim-centric
`PedanteFinding` taxonomy. It may also emit uncatalogued claims when pass two
discovers issues that pass one missed.

Add a small pure helper that aggregates `LLMUsage` across passes. The final
public `PedanteEvaluationResult` should expose the total aggregated usage.
Provider metadata policy must also be made explicit. If the current single
`model`, `provider_response_id`, and `finish_reason` fields are still
sufficient, document the aggregation rule in code comments and the developer's
guide. If they are not sufficient, stop and add ADR coverage before widening
the public result shape.

Acceptance for Stage D:

- one call to `PedanteEvaluator.evaluate(...)` can drive two `LLMPort`
  interactions and return one stable `PedanteEvaluationResult`,
- usage is aggregated correctly across both passes, and
- verifier logic can emit uncatalogued findings without breaking the result
  contract.

### Stage E: update the LangGraph seam and behavioural tests

Keep the application-layer LangGraph seam small. `episodic/qa/langgraph.py`
should still depend only on the Pedante evaluator contract and produce one
final routing decision. The node should not need to understand claim-catalogue
internals.

If temporary graph-state diagnostics are useful during the refactor, keep them
namespaced and explicitly non-canonical. Do not let graph state become the
authoritative home of the claim catalogue.

Update the Vidai Mock assets and BDD steps so one evaluator call results in two
deterministic LLM responses. Add assertions for:

- the number of model calls,
- the pass order if the fixtures depend on it,
- combined usage totals, and
- final findings that still match the claim-centric contract.

Acceptance for Stage E:

- graph-routing tests still pass without depending on Pedante internals,
- behavioural tests prove the two-pass flow deterministically, and
- Vidai Mock remains the only behavioural inference harness.

### Stage F: update documentation and record any new ADRs

Once the code is stable, update:

- `docs/adr-001-pedante-evaluator-contract.md` only if implementation exposed
  ambiguity or required clarification;
- `docs/episodic-podcast-generation-system-design.md` so the QA stack section
  describes the two-pass internal Pedante design accurately;
- `docs/users-guide.md` if the user-facing explanation of Pedante checks needs
  to mention citation-aware claim checking or new categories of findings; and
- `docs/developers-guide.md` so maintainers know where the TEI projection,
  claim catalogue, verification pass, and Vidai Mock fixtures live.

If implementation pins down a new durable representation boundary, add a new
ADR rather than silently expanding ADR 001. Likely candidates are:

- a reusable internal claim-catalogue DTO shared across evaluators,
- a durable mapping contract between TEI pointer values and
  `PedanteSourcePacket.source_id`, or
- a stable per-pass diagnostics or cost-accounting object.

Acceptance for Stage F:

- the docs accurately describe the shipped behaviour,
- any durable new representation decision has explicit ADR coverage, and
- the revised plan sections can be updated to reflect completed work.

### Stage G: run the full validation gates

Run the required gates sequentially and capture logs with `tee`. Do not run
`make test` and `make typecheck` in parallel, because this repository rebuilds
`.venv` inside those Make targets.

Use this exact pattern from the repository root:

```plaintext
set -o pipefail
make fmt 2>&1 | tee /tmp/pedante-adr-align-make-fmt.log
```

```plaintext
set -o pipefail
make check-fmt 2>&1 | tee /tmp/pedante-adr-align-make-check-fmt.log
```

```plaintext
set -o pipefail
make test 2>&1 | tee /tmp/pedante-adr-align-make-test.log
```

```plaintext
set -o pipefail
make typecheck 2>&1 | tee /tmp/pedante-adr-align-make-typecheck.log
```

```plaintext
set -o pipefail
make lint 2>&1 | tee /tmp/pedante-adr-align-make-lint.log
```

```plaintext
set -o pipefail
PATH=/root/.bun/bin:$PATH make markdownlint 2>&1 | tee /tmp/pedante-adr-align-make-markdownlint.log
```

```plaintext
set -o pipefail
make nixie 2>&1 | tee /tmp/pedante-adr-align-make-nixie.log
```

Only after all gates pass should this ExecPlan be marked `COMPLETE`.

## Concrete implementation steps

1. Update Pedante unit tests and behaviour tests to fail against the current
   single-pass implementation.

```plaintext
pytest tests/test_pedante.py tests/test_pedante_langgraph.py -q
pytest tests/steps/test_pedante_steps.py -q
```

1. Add the TEI-backed internal projection and citation-harvesting helpers.

```plaintext
pytest tests/test_pedante.py -q
```

1. Add the claim-catalogue pass and its internal data shape.

```plaintext
pytest tests/test_pedante.py -q
```

1. Add the verification pass, uncatalogued-claim handling, and usage
   aggregation.

```plaintext
pytest tests/test_pedante.py tests/test_pedante_langgraph.py -q
```

1. Update the Vidai Mock fixtures and behavioural steps for the two-pass flow.

```plaintext
pytest tests/steps/test_pedante_steps.py -q
```

1. Update the design, user, developer, and ADR documents as needed.

```plaintext
PATH=/root/.bun/bin:$PATH make markdownlint
make nixie
```

1. Run the full Stage G gate sequence.

## Validation and acceptance

The ADR-alignment work is complete only when all of the following are true:

- `PedanteEvaluator.evaluate(...)` still exposes the same stable external
  contract.
- Pedante internally performs a claim-catalogue pass and a support-verification
  pass.
- the evaluator uses TEI-backed citation context from utterance-local
  attributes and `refsDecl` rather than reconstructing citations solely from
  prompt prose,
- final findings remain claim-centric and compatible with the existing result
  contract,
- combined `LLMUsage` totals are reported correctly for the whole Pedante run,
- unit tests and behavioural tests prove the two-pass flow and the citation
  spine usage,
- any newly pinned durable data representation is documented in an ADR, and
- `make check-fmt`, `make test`, `make typecheck`, `make lint`,
  `make markdownlint`, and `make nixie` all succeed.

## Idempotence and recovery

This plan is safe to execute incrementally.

- The test updates are additive and can be rerun freely.
- The TEI projection and claim-catalogue helpers should be introduced behind
  tests so the refactor can proceed in small steps.
- If a stage fails, fix the immediate failure, rerun the targeted tests for
  that stage, then rerun the full Stage G sequence before closing the work.
- If the `tei_rapporteur` Python surface proves insufficient, stop at the TEI
  tooling tolerance gate rather than hand-rolling a one-off XML parser inside
  Pedante.
- If aggregated usage or provider metadata cannot be represented cleanly inside
  the current public result type, stop at the usage tolerance gate and add ADR
  coverage before proceeding.

## Artifacts and notes

Expected validation logs:

- `/tmp/pedante-adr-align-make-fmt.log`
- `/tmp/pedante-adr-align-make-check-fmt.log`
- `/tmp/pedante-adr-align-make-test.log`
- `/tmp/pedante-adr-align-make-typecheck.log`
- `/tmp/pedante-adr-align-make-lint.log`
- `/tmp/pedante-adr-align-make-markdownlint.log`
- `/tmp/pedante-adr-align-make-nixie.log`

Expected long-lived project artifacts if the implementation needs them:

- updated `tests/test_pedante.py`
- updated `tests/test_pedante_langgraph.py`
- updated `tests/features/pedante.feature`
- updated `tests/steps/test_pedante_steps.py`
- possible new Pedante-internal helper modules under `episodic/qa/`
- possible new ADR if a durable internal data shape is pinned down

Example success indicators:

```plaintext
pytest tests/test_pedante.py -q
...
N passed
```

```plaintext
pytest tests/steps/test_pedante_steps.py -q
...
1 passed
```

```plaintext
make test
...
235 passed, 2 skipped
```

## Revision note

Updated on 2026-03-24 to replace the earlier single-pass completion record with
a new follow-on plan. The revised ADR now requires Pedante to become
citation-aware and internally two-pass while keeping its public contract
stable, so this ExecPlan now describes that refactor, the TEI citation-spine
work, the likely ADR follow-on points, and the updated validation path.
