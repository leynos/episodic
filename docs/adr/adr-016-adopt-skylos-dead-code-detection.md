# ADR-016: Adopt Skylos dead-code detection

- Status: Accepted
- Date: 2026-07-27
- Deciders: Episodic maintainers

## Context and decision

In the context of keeping unused Python symbols out of Episodic, facing gaps in
Ruff and Pylint's cross-module dead-code detection, we decided for a local,
blocking Skylos scan in `make lint`, with explicit entry-point rules and
reasoned named exceptions in `pyproject.toml`, and against an advisory-only
scan, cloud analysis, automatic deletion, unexplained baselines, or
report-scraping suppression, to achieve deterministic dead-code enforcement
whose exceptions remain reviewable in version control, accepting that dynamic
framework and compatibility surfaces require narrow configuration entries that
maintainers must remove when they become stale.

## Consequences

- `make lint` runs Skylos locally with concise output and fails while
  unsuppressed dead-code findings remain.
- Contributors remove genuine dead code and use
  `make skylos-allow NAME=... REASON=...` only for intentional named
  exceptions; the target rejects missing names or reasons.
- Framework callbacks, protocol implementations, and compatibility re-exports
  remain live through precise, reasoned configuration rather than bulk
  baselines or unexplained inline suppressions.

## Addendum: rename the Skylos allowlist argument (2026-09-03)

The `skylos-allow` Make target now accepts `SYMBOL` instead of `NAME`. WSL
injects the host name into the ambient `NAME` variable, which could otherwise
silently satisfy the target's required-value check. `SYMBOL` avoids that
collision while preserving the same named-exception format and reason
requirement.
