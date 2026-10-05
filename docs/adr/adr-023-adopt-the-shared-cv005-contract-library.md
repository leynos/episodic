# ADR-023: Adopt the shared CV-005 contract library

- Status: Accepted
- Date: 2026-10-03
- Deciders: Episodic maintainers

## Context and decision

Episodic keeps CodeScene coverage owned by `main`, the estate rule CV-005. Its
repository-local copy of the contract ran as six test modules and had to be
re-edited whenever the rule gained a clause.

The decision is to run `cv005-contracts check` from `leynos/shared-actions`
(`packages/cv005-contracts`) through `make test-workflow-contracts`.
`uv tool run` fetches it from the full commit named by `CV005_CONTRACTS_REF` in
the `Makefile`, and `.github/cv005.toml` holds this repository's parameters.

The alternatives were to keep the local copy, to vendor the library, and to run
it from a floating branch. All three were rejected. Adopting the library gives
one definition of the rule that every repository shares and that its own suite
proves.

The trade-offs are accepted. A fix to the rules reaches this repository only as
a pin bump. The target needs `uv` and the Python 3.13 it fetches. Anything the
library does not know stays a small local test.

## Consequences

- The deleted `tests/test_codescene_*` modules and `codescene_environment_rules`
  are replaced by the library's clauses: the pull-request closure, the
  publisher's shape, the upload guard, the token check, the environment
  placement, lane hardening and selection parity.
- `.github/cv005.toml` holds `repository`, `environment = true`, and a
  `[selection]` table carrying what the ratchet baseline measures. Both
  workflows must carry that selection.
- `tests/test_action_revisions_contract.py` stays local because the approved
  shared-action revisions and the retired nested pins are not in the library.
- CI runs the target in its own `lint-test` step after the uv cache restore,
  and `make test` and `make all` depend on it, so a local run covers the
  contract.
- The publisher job carries no `if:` (the library refuses one, since it could
  skip the baseline); the upload step's guard requires `main`, and the
  `codescene` environment's branch policy is a second layer.
