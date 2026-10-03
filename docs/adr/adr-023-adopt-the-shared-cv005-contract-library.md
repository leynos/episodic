# ADR-023: Adopt the shared CV-005 contract library

- Status: Accepted
- Date: 2026-10-03
- Deciders: Episodic maintainers

## Context and decision

In the context of keeping CodeScene coverage owned by `main` (the estate rule
CV-005) in Episodic, facing a repository-local copy of the contract that ran as
six test modules and had to be re-edited whenever the rule gained a clause, the
decision is to run `cv005-contracts check` from `leynos/shared-actions`
(`packages/cv005-contracts`) through `make test-workflow-contracts`, fetched by
`uv tool run` from the full commit named by `CV005_CONTRACTS_REF` in the
`Makefile`, with this repository's parameters in `.github/cv005.toml`, and
against keeping the local copy, vendoring the library, or running it from a
floating branch, to achieve one definition of the rule that every repository
shares and that is proved by its own suite, accepting that a fix to the rules
reaches this repository only as a pin bump, that the target needs `uv` and the
Python 3.13 it fetches, and that anything the library does not know stays a
small local test.

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
