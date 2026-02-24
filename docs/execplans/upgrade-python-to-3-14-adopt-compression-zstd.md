# Upgrade to Python 3.14: adopt stdlib Zstandard compression

This ExecPlan is a living document. The sections `Constraints`, `Tolerances`,
`Risks`, `Progress`, `Surprises & discoveries`, `Decision log`, and
`Outcomes & retrospective` must be kept up to date as work proceeds.

No `PLANS.md` file is present in the repository root.

Status: DRAFT

## Purpose and big picture

After this change, Episodic will use Python 3.14 standard-library Zstandard
compression for large text payloads where storage and transfer costs matter,
beginning with canonical TEI-adjacent payloads and future orchestration
artifacts. The observable outcome is reduced payload size while preserving
exact round-trip content semantics for domain consumers.

Success is visible when payloads can be compressed and decompressed losslessly,
read paths remain transparent, and storage behaviour is validated through tests.

## Constraints

- Preserve exact textual content on read; compression must be lossless.
- Keep existing public domain interfaces unchanged (callers still receive `str`
  where currently expected).
- Ensure backward compatibility for rows created before compression adoption.
- Avoid introducing external compression dependencies.
- If schema changes are introduced, they must use Alembic migrations and remain
  reversible.

## Tolerances (exception triggers)

- Scope: if rollout requires modifying more than 15 files in first milestone,
  stop and escalate.
- Storage model: if migration would require rewriting all historical rows in a
  single blocking operation, stop and escalate.
- Performance: if compression/decompression increases end-to-end ingestion
  latency by more than 20% for representative payload sizes, stop and escalate.
- Validation: if data round-trip tests fail twice after fixes, stop and
  escalate.

## Risks

- Risk: compression may complicate debugging if raw payload visibility is lost.
  Severity: medium. Likelihood: medium. Mitigation: retain controlled debug
  utilities and optional uncompressed views for diagnostics.

- Risk: small payloads may not benefit and can regress latency.
  Severity: low. Likelihood: high. Mitigation: include threshold policy that
  skips compression below a minimum size.

- Risk: migration design may add schema complexity.
  Severity: medium. Likelihood: medium. Mitigation: stage rollout with
  dual-read compatibility and clear fallback.

## Progress

- [x] (2026-02-24 00:00Z) Draft ExecPlan created.
- [ ] Stage A: Select first payload targets and define storage policy.
- [ ] Stage B: Add fail-first round-trip and compatibility tests.
- [ ] Stage C: Implement codec utilities and persistence integration.
- [ ] Stage D: Run migrations, gates, and performance smoke checks.

## Surprises & discoveries

- Observation: current canonical storage persists TEI XML as plain text fields.
  Evidence: `episodic/canonical/storage/models.py` includes text columns for
  `raw_xml` and `tei_xml`. Impact: compression rollout requires either
  transparent encode/decode logic or additive schema support.

- Observation: project memory MCP resources are unavailable in this session.
  Evidence: empty resource/template listings. Impact: migration assumptions
  rely on local code and docs only.

## Decision log

- Decision: implement a codec utility layer first, then integrate into selected
  persistence paths. Rationale: isolates compression mechanics and improves
  testability. Date/Author: 2026-02-24 / Codex.

- Decision: require dual-read compatibility during rollout.
  Rationale: avoids hard cutover risk and preserves readability for historical
  rows. Date/Author: 2026-02-24 / Codex.

## Outcomes & retrospective

Pending implementation.

Completion should prove lossless compression, backward-compatible reads, and
acceptable performance trade-offs for selected payload classes.

## Context and orientation

Canonical persistence currently stores TEI payload text in relational tables
via SQLAlchemy models and repository mappers.

Relevant modules:

- `episodic/canonical/storage/models.py`
- `episodic/canonical/storage/mappers.py`
- `episodic/canonical/storage/repositories.py`
- `alembic/versions/*.py`
- `tests/test_canonical_storage.py`
- `tests/test_ingestion_integration.py`

Python 3.14 adds stdlib Zstandard support (`compression.zstd`), enabling
first-party compression without an extra dependency.

## Plan of work

Stage A defines policy. Decide initial compression targets, minimum size
thresholds, and where metadata indicating compression state will be stored.
Confirm whether first milestone is schema-additive or purely in-memory artifact
compression.

Stage B creates tests first. Add round-trip tests for text payloads,
compatibility tests for pre-existing uncompressed rows, and failure-path tests
for corrupt compressed payload handling.

Stage C implements codec and integration. Add a small `compression.zstd` helper
module, wire repository write paths for selected payloads, and preserve
existing read interfaces by decoding before mapping to domain entities.

Stage D validates. Run migration checks if schema changed, then full quality
gates and a small performance smoke benchmark on representative payload sizes.

## Concrete steps

Run from repository root.

1. Inspect current payload persistence paths.

    rg -n "tei_xml|raw_xml|payload|JSONB|Text" episodic/canonical/storage alembic

2. Add tests first and run targeted suites.

    set -o pipefail; uv run pytest -v \
      tests/test_canonical_storage.py tests/test_ingestion_integration.py 2>&1 \
      | tee /tmp/py314-zstd-targeted.log |

3. Implement codec and repository integration.

4. If schema changes were added, validate migration alignment.

    set -o pipefail; make check-migrations 2>&1 | tee /tmp/py314-zstd-check-migrations.log

5. Run full Python gates.

    set -o pipefail; make check-fmt 2>&1 | tee /tmp/py314-zstd-check-fmt.log
    set -o pipefail; make lint 2>&1 | tee /tmp/py314-zstd-lint.log
    set -o pipefail; make typecheck 2>&1 | tee /tmp/py314-zstd-typecheck.log
    set -o pipefail; make test 2>&1 | tee /tmp/py314-zstd-test.log

Expected success indicators:

- Round-trip and compatibility tests pass.
- No regression in domain-facing read types.
- Full gates pass.

## Validation and acceptance

Acceptance criteria:

- Selected payloads use stdlib Zstandard compression in write paths.
- Read paths transparently return original textual content.
- Historical uncompressed rows remain readable.
- Migration checks pass if schema changed.
- `make check-fmt`, `make lint`, `make typecheck`, and `make test` pass.

## Idempotence and recovery

- Codec operations are deterministic and safe to re-run.
- If rollout issues appear, disable compression write-paths while keeping
  decode-capable read paths for mixed data.
- Migration rollback path must be documented before applying production schema
  changes.

## Artifacts and notes

Capture during implementation:

- `git diff -- episodic/canonical/storage alembic tests`
- `/tmp/py314-zstd-targeted.log`
- `/tmp/py314-zstd-check-migrations.log` (if applicable)
- `/tmp/py314-zstd-check-fmt.log`
- `/tmp/py314-zstd-lint.log`
- `/tmp/py314-zstd-typecheck.log`
- `/tmp/py314-zstd-test.log`

## Interfaces and dependencies

- Use Python 3.14 stdlib `compression.zstd` only.
- Preserve existing domain model and repository method signatures.
- Keep Alembic as the only migration mechanism for storage schema changes.

## Revision note

Initial draft created to plan staged adoption of stdlib Zstandard compression
in storage-facing payload paths after Python 3.14 upgrade.
