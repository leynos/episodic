# Architectural decision record (ADR) 027: CLI client boundary

## Status

Accepted. The `episodic` command is a REST client of the HTTP API, built on
`cyclopts`, isolated in its own import-boundary group, and reporting failures
through a small exit-code contract.

## Date

2026-11-01.

## Context and problem statement

Roadmap item `2.2.7` requires retrieval of QA artefacts "via API and CLI
filtered by evaluator and compliance status". The repository already had a
first-party `stilyagi` console script pointing at a module that does not exist,
so the entry point was dead.

The design document places the CLI in the Client Experience Layer alongside the
web console, and `docs/episodic-tui-api-design.md` fixes the authentication,
error, and pagination contracts clients use. The CLI therefore has a
constitutional choice to make before any command is written: does it call the
HTTP API, or does it open a database session and reuse the canonical services?

A second question is how much of the client architecture to fix now. The
roadmap names exactly one CLI command in this item, and roadmap item `4.6.1`
extends the CLI later.

## Decision drivers

- One authorization story. The API owns principal resolution, ownership checks,
  and the 404-for-foreign-principal rule; a second persistence entry point
  would need its own copy.
- The CLI must be testable without a database or a network.
- Adding a command should not require touching a parser, a formatter, and an
  error map in three places.
- Machine-readable output must be stable enough to pipe into `jq`.
- The boundary must be enforced, not merely documented.
- The command noun structure must be able to change once more commands exist.

## Decision outcome

### The CLI is an HTTP client

`episodic/cli/` contains no unit of work, no repository, and no canonical
service import. It builds a request, sends it, and renders the response. The
authorization rule, the error envelope, the pagination contract, and the
`422 qa_artefact_schema_unsupported` outcome all belong to the API and are
consumed rather than re-implemented.

### `cyclopts` for command declaration

The `cyclopts.App` is built in `episodic/cli/app.py`. Commands are ordinary
typed functions whose annotations declare their options, and the enum-valued
filters pass explicit `choices=` built from the wire values so `--help` shows
the API vocabulary (`non_compliant`, not `non-compliant`).

`cyclopts` resolves a command's annotations when the command is registered, so
a type used only in an annotation must still be importable at runtime; this is
why `episodic/cli/qa.py` imports `uuid` and the enum helpers at module level.

### Module split

- `episodic/cli/entrypoint.py` owns `main` and the process exit status.
- `episodic/cli/app.py` owns the application object and global options.
- `episodic/cli/qa.py` declares the `qa evaluations list` command.
- `episodic/cli/client.py` owns the `httpx` client and error translation.
- `episodic/cli/rendering.py` owns the pure table and JSON renderers.
- `episodic/cli/__init__.py` re-exports `main` and nothing else, because the
  `non-empty-init-module` lint rule forbids implementation code there.

Only the entry point writes to standard output or chooses an exit status, and
the renderers are pure functions from a parsed payload to a string, so
snapshots pin them without a process boundary.

### Enforced boundary

`[tool.hecate]` gives `episodic.cli` its own group with
`allowed = ["cli", "domain_ports"]`. The CLI may import its own modules and the
canonical domain types that describe the wire payload, and nothing else. An
accidental import of `episodic.api` or a canonical service fails
`make check-architecture`.

### Authentication and endpoint configuration

- `--base-url`, defaulting to `EPISODIC_API_URL`, then
  `http://127.0.0.1:8000`.
- `--token`, defaulting to `EPISODIC_API_TOKEN`, sent as
  `Authorization: Bearer <token>`.

The base URL must be an `http` or `https` URL with a host, without embedded
credentials, and without a query string or fragment, because the client appends
the resource path to it. A bearer token is refused over plain HTTP to a
non-loopback host: loopback and every `https://` endpoint remain allowed, so
local development works unchanged while a misconfigured remote endpoint cannot
put the credential on the wire in clear. The token is never echoed and never
appears in a rendered table.

### Output and exit-code policy

`--format table` prints a fixed-width table for people. `--format json` prints
the API envelope verbatim, indented by two spaces with a trailing newline, so
it can be piped.

| Exit code | Meaning                                                               |
| --------- | --------------------------------------------------------------------- |
| `0`       | Success.                                                              |
| `1`       | The API returned an error envelope, or a 2xx body that is not a page. |
| `2`       | Usage error, including a base URL the client cannot use.              |
| `3`       | The API was unreachable or timed out.                                 |
| `4`       | The API answered `429 Too Many Requests`.                             |

_Table 1: The CLI exit-code contract._

A successful response whose body lacks an `items` list is an error rather than
an empty page, so a proxy error page cannot render as `0 of 0 evaluations` with
exit 0.

### The noun structure is provisional

The top-level structure is `episodic qa evaluations list`. It is provisional
until a second command group lands under roadmap item `4.6.1`; a second group
may show that `qa` should be a noun at a different level. Only `list` ships in
this slice, because filtered retrieval satisfies the roadmap requirement and
the TUI client, not the CLI, consumes `GET /v1/qa-evaluations/{evaluation_id}`.

## Considered alternatives

### A CLI that opens its own unit of work

Rejected. It would create a second persistence entry point with its own
authorization story, duplicate the 404-for-foreign-principal rule, and let the
CLI bypass any middleware the API adds later.

### `argparse` from the standard library

Rejected. It is available without a dependency, but every option, choice, and
sub-command has to be declared imperatively and separately from the function
that consumes it, which is the duplication this CLI exists to avoid.

### Click or Typer

Rejected. Both would work, but the project standardizes on `cyclopts` for this
surface: it derives options from the same typed signature the command already
needs, including `Annotated` metadata for choices and help text.

### Rendering inside the command functions

Rejected. A renderer that prints cannot be snapshotted, and a renderer that
formats and exits cannot be reused by a second output mode. Both renderers are
pure and the entry point does the printing.

## Consequences

- The CLI inherits the API's authorization, pagination, and error contracts and
  must be re-released only when the API's wire shape changes.
- `cyclopts` becomes a runtime dependency and its version is bounded to the
  current major release, so a breaking change in its annotation handling is a
  dependency decision rather than an implementation detail.
- The Hecate group makes a future convenience import a build failure, which is
  the point but does mean an intentional new dependency needs a configuration
  change and an architecture review.
- The provisional noun structure is recorded, so renaming `qa evaluations` in
  roadmap item `4.6.1` is a planned change rather than an oversight.

## References

- [Design document, _Client Experience Layer_](../episodic-podcast-generation-system-design.md)
- [TUI and API design](../episodic-tui-api-design.md)
- [ADR 026: QA artefact persistence contract](adr-026-qa-artefact-persistence-contract.md)
- [Developers' guide, _Command-line interface_](../developers-guide.md#command-line-interface)
- ExecPlan:
  `docs/execplans/2-2-7-persist-qa-artefacts-linked-to-canonical-episodes.md`
