# Migrating to Episodic 0.2.0

This guide describes what a deployment must change when it moves from Episodic
0.1.0 to 0.2.0. It covers the renamed command-line entry point, the database
migration that must run before the service starts, and the new quality
assurance (QA) retrieval interfaces.

## Renamed command-line entry point

Version 0.1.0 declared a `stilyagi` console script that pointed at a module
that does not exist, so the command could not run. Version 0.2.0 replaces it
with `episodic`.

| 0.1.0                 | 0.2.0      |
| --------------------- | ---------- |
| `stilyagi` (unusable) | `episodic` |

*Table 1: The console-script change.*

Any wrapper, container entry point, or local documentation that invokes
`stilyagi` must invoke `episodic` instead. The distribution name and the
`episodic` import path are unchanged.

## Database migration

The release adds the `qa_evaluations` and `qa_findings` tables and three
PostgreSQL enum types: `qa_evaluator`, `qa_compliance_status`, and
`qa_finding_severity`. Apply the migration before starting the API or any
worker:

```console
uv run alembic upgrade head
```

`make check-migrations` reports drift between the object-relational mapping
(ORM) models and the migration history. A deployment that skips this step fails
when the QA recording or retrieval paths first touch the missing tables.

## QA retrieval over REST

Two owner-scoped endpoints are new:

- `GET /v1/episodes/{episode_id}/qa-evaluations` lists one episode's
  evaluations, filtered by `evaluator` and `compliance_status` and paginated
  with `limit` and `offset`. Each item is a summary.
- `GET /v1/qa-evaluations/{evaluation_id}` returns one evaluation with its
  findings in the order the evaluator recorded them.

Both endpoints require the bearer token the service already accepts. A request
without credentials receives `401 unauthorized`. An authenticated caller who
does not own the episode receives `404 qa_evaluation_not_found`, whether the
episode, the evaluation, or its launcher run is missing or belongs to someone
else. A row written by a newer release returns
`422 qa_artefact_schema_unsupported` instead of being misread.

## QA retrieval from the CLI

The `episodic` command is a REST client for the running API:

```console
uv run episodic qa evaluations list \
    0199a0c1-0000-7000-8000-000000000001
```

The command reads `EPISODIC_API_URL` and `EPISODIC_API_TOKEN`. `--base-url`
overrides the first and `--token` the second; `--timeout` sets the request
timeout independently and has no environment variable. A bearer token is
refused over plain HTTP unless the host is loopback, so a remote endpoint needs
`https://`. `--format json` prints the API envelope unchanged. Exit codes are
`0` for success, `1` for an API error envelope, `2` for a usage error, `3` when
the API is unreachable or times out, and `4` for `429 Too Many Requests`.

## Evaluator graph builders moved out of the package barrel

`episodic.qa` no longer re-exports the LangGraph adapters. Import each symbol
from the module that defines it:

- `build_chrono_graph` is in `episodic.qa.chrono_langgraph`.
- `build_pedante_graph` and `route_after_pedante` are in
  `episodic.qa.langgraph`.

A re-export would make every import of the evaluator contracts load the
orchestration stack, so a deployment that needs only the Pedante or Chrono
contracts no longer pulls in `langgraph`. Code that imported these three names
from `episodic.qa` must change its import statement; the symbols themselves are
unchanged.

## Configuration summary

| Setting              | Purpose                  | Default                 |
| -------------------- | ------------------------ | ----------------------- |
| `EPISODIC_API_URL`   | Base URL the CLI calls   | `http://127.0.0.1:8000` |
| `EPISODIC_API_TOKEN` | Bearer token for the API | none                    |

*Table 2: CLI configuration.*

The API continues to read its existing database and authentication
configuration. This release adds no new required server setting.

## References

- [Users' guide](users-guide.md)
- [ADR 026: QA artefact persistence contract](adr/adr-026-qa-artefact-persistence-contract.md)
- [ADR 027: CLI client boundary](adr/adr-027-cli-client-boundary.md)
