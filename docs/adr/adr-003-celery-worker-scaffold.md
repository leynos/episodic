# Architectural Decision Record (ADR)-003: Celery worker scaffold

## Status

Accepted

## Context

Roadmap item `1.5.2` required Episodic to make the worker boundary real rather
than leaving Celery and RabbitMQ as design-only concepts. The platform already
had a typed Falcon composition root under `episodic/api/`, but it lacked an
equivalent worker runtime, canonical queue topology, and a safe way to add
representative tasks without leaking Celery concerns into the domain.

The design document already committed the system to:

1. RabbitMQ as the durable Celery broker,
2. workload isolation through routing keys and explicit queues, and
3. a split between high-concurrency I/O workers and prefork CPU workers.

The repository does not yet provide a stable RabbitMQ test harness for local
and Continuous Integration (CI) runs, so behavioural coverage also needed a
clear scope decision.

## Decision

The worker scaffold now follows these rules:

1. `episodic/worker/topology.py` is the single source of truth for the
   exchange, queues, workload classes, and task-route metadata.
2. `episodic/worker/runtime.py` is the Celery composition root. It reads
   environment variables, validates RabbitMQ-backed configuration, exposes
   worker launch profiles, and builds the Celery application through
   `create_celery_app(...)` and `create_celery_app_from_env()`.
3. `episodic/worker/tasks.py` holds only representative scaffold tasks and
   their typed payload and dependency seams. These tasks are intentionally
   diagnostic, not business-complete workflow implementations.
4. The canonical queue topology uses one topic exchange, `episodic.tasks`, and
   two queues:
   - `episodic.io` for I/O-bound tasks, routed with
     `episodic.io.diagnostic`;
   - `episodic.cpu` for CPU-bound tasks, routed with
     `episodic.cpu.diagnostic`.
5. The initial worker-profile split is:
   - I/O-bound workloads default to the `gevent` pool with high concurrency;
   - CPU-bound workloads default to the `prefork` pool with lower concurrency.
6. Behavioural coverage for this roadmap slice remains contract-level rather
   than broker-backed. Tests create the Celery app from environment
   configuration, inspect routing metadata, and execute representative tasks in
   eager mode. A live RabbitMQ dispatch path is deferred until the repository
   has a stable broker fixture strategy.

## Rationale

This arrangement preserves the hexagonal boundaries:

- queue topology and worker boot logic stay in dedicated adapter modules;
- domain and application services do not import Celery, Kombu, or RabbitMQ
  clients;
- task bodies depend on typed payloads and injected callables rather than
  concrete adapters; and
- tests can exercise routing and execution deterministically without inventing
  later workflow behaviour.

Using eager-mode behavioural tests is an explicit trade-off. It proves the
public factory, queue contract, and task registration today, whilst avoiding a
fragile pseudo-integration test that would still not guarantee a stable broker
story across developer machines and CI runners.

## Consequences

### Positive

- Episodic now has a typed worker composition root that mirrors the Falcon
  runtime pattern.
- Queue names, routing keys, and worker pools are defined once and reused by
  runtime code, tests, and documentation.
- Future roadmap items can add Celery tasks by extending typed dependency seams
  rather than introducing ad hoc globals.

### Negative

- The repository now depends on Celery for the worker scaffold, even though
  the first tasks are intentionally diagnostic.
- The current behavioural tests do not prove a full RabbitMQ round-trip.
  Operators still need a later broker-backed test slice before treating the
  worker runtime as production-validated.
- The default I/O worker profile assumes `gevent` semantics from the design
  document, but the repository does not yet ship a broker-backed operational
  harness for that pool.

## References

- `docs/execplans/1-5-2-scaffold-celery-workers-with-rabbit-mq-integration.md`
- `docs/episodic-podcast-generation-system-design.md`
- `episodic/worker/topology.py`
- `episodic/worker/runtime.py`
- `episodic/worker/tasks.py`
- `tests/test_worker_service_scaffold.py`
- `tests/features/worker_service_scaffold.feature`
- `tests/steps/test_worker_service_scaffold_steps.py`
