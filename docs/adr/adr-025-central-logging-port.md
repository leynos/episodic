# ADR-025: Central logging port

## Status

Accepted, 2026-11-03.

## Context

`episodic.logging` already provided convenience functions, but most production
modules emitted through logger methods directly. That bypass made the helper
boundary incomplete and would leave cross-cutting logging behaviour out of
scope. Roadmap item 4.1.3 needs the request correlation identifier on each
request log. Femtologging does not carry ambient structured context, so the
identifier must be attached where application logging enters the backend.

## Decision

- Treat `episodic.logging` as the application logging port. Call sites obtain
  an opaque `LoggerHandle` from `get_logger` and emit through `log_debug`,
  `log_info`, `log_warning`, `log_error`, or `log_exception`.
- Keep femtologging imports and raw logger operations inside the port. A
  `LoggerHandle` exposes no backend level methods; helper calls eagerly format
  percent-style arguments and preserve the convenience-method and `.log()`
  fallback behaviours.
- Enforce the dependency edge with Hecate's ordered `logging_port`,
  `logging_backend`, and `external_libraries` groups while tracking external
  imports. The femtologging group must match before broad third-party prefixes.
- Enforce call-site ownership with the opaque handle under `ty` and a
  production-tree AST check that rejects standard-library `logging` imports
  outside `episodic.logging`.
- Keep structured event fields in the JSON message until the backend supports
  ambient fields. When roadmap item 4.1.3 adds request correlation, attach it
  at this port so all wrapper emissions share one policy point.

## Consequences

### Positive

- A cross-cutting logging change has one application boundary to update.
- The type checker and architecture tests make raw backend calls visible during
  development instead of relying on convention.
- Explicit wrappers preserve level intent and exception metadata while
  decoupling application code from femtologging.

### Negative

- New logging behaviours need a corresponding port helper and wrapper tests.
- Structured fields are serialized into message text until femtologging gains
  ambient structured context.
- Enabling external import analysis requires ordered Hecate groups for the
  repository's third-party dependencies.

## References

- [Issue #286](https://github.com/leynos/episodic/issues/286)
- [Request-correlation ExecPlan](../execplans/4-1-3-integrate-request-correlation.md)
- [ADR-014: Hexagonal architecture enforcement](adr-014-hexagonal-architecture-enforcement.md)
