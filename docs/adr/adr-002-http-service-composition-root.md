# ADR-002: HTTP service composition root

## Status

Accepted

## Context

The canonical-content API already exposed Falcon resources for series profiles,
episode templates, reusable reference documents, and reusable reference
bindings. That adapter surface lacked three operational seams:

1. a typed dependency object for injecting ports into the HTTP layer,
2. explicit liveness and readiness endpoints, and
3. a Granian-friendly runtime composition root that can build the Falcon ASGI
   application from environment configuration.

Without those seams, the HTTP adapter risked importing concrete infrastructure
directly into resources, and operators had no stable health contract for
deployment systems.

## Decision

The Falcon HTTP adapter now uses a separate composition-root arrangement with
the following rules:

1. `episodic/api/dependencies.py` defines `ApiDependencies` and
   `ReadinessProbe` as the typed inbound dependency contract.
2. `episodic/api/app.py` remains a pure Falcon application factory. It wires
   routes only and receives an `ApiDependencies` instance rather than parsing
   environment variables or constructing database engines.
3. `episodic/api/runtime.py` is the Granian runtime composition root. It reads
   `DATABASE_URL`, creates the SQLAlchemy session factory used by
   `SqlAlchemyUnitOfWork`, constructs infrastructural readiness probes, and
   returns the Falcon ASGI app through
   `episodic.api.runtime:create_app_from_env`.
4. The HTTP health contract exposes two endpoints:
   - `GET /health/live` returns `200 OK` with
     `{"status": "ok", "checks": [{"name": "application", "status": "ok"}]}`
     once the Falcon app has booted.
   - `GET /health/ready` returns `200 OK` when every configured readiness probe
     succeeds and `503 Service Unavailable` when any configured probe fails.

## Rationale

This arrangement preserves the hexagonal boundary rules:

- Falcon resources depend on ports and typed dependencies, not concrete
  adapter construction.
- Runtime concerns stay in one module instead of spreading across route
  handlers.
- Operators get a deterministic health contract that can be checked in memory
  and through a live Granian process.

Keeping the runtime factory outside `app.py` also makes the Falcon adapter easy
to test in isolation, because unit and integration tests can build the app from
in-memory dependencies without importing database configuration code.

## Consequences

### Positive

- The inbound HTTP adapter now has an explicit extension seam for future
  injected ports, including `LLMPort`.
- Granian can boot the service via a documented factory target.
- Health behaviour is consistent across in-memory tests and live HTTP process
  tests.

### Negative

- The service now has one extra module (`episodic/api/runtime.py`) and one more
  typed contract module (`episodic/api/dependencies.py`).
- Runtime readiness for Postgres-backed deployments depends on a dedicated
  connectivity probe in addition to the SQLAlchemy unit-of-work engine.

## References

- `docs/execplans/1-5-1-scaffold-falcon-http-services-on-granian.md`
- `episodic/api/app.py`
- `episodic/api/dependencies.py`
- `episodic/api/runtime.py`
