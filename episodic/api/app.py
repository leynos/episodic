"""Falcon ASGI entry point for canonical HTTP APIs.

This module exposes :func:`create_app`, which wires the canonical series
profile, episode template, reference-document, and health resources into a
Falcon ASGI application. Callers pass a typed dependency object and receive a
ready-to-serve app object.

Example
-------
from episodic.api import ApiDependencies, create_app
dependencies = ApiDependencies(uow_factory=uow_factory)
app = create_app(dependencies)  # Returns a Falcon ASGI app with API routes.
"""

import typing as typ
from functools import partial

from falcon import asgi

from episodic.logging import get_logger, log_error

from .authorization import AuthorizationMiddleware
from .errors import serialize_http_error
from .routes import _register_api_routes

if typ.TYPE_CHECKING:
    from episodic.observability import MetricsPort, MonotonicClockPort

    from .dependencies import ApiDependencies, ShutdownHook


logger = get_logger(__name__)

_GENERATION_REQUEST_TOTAL = "generation_api_request_total"
_GENERATION_REQUEST_LATENCY = "generation_api_request_latency_ms"

_PATH_OPERATIONS = (
    ("/v1/ingestion-jobs/", "/generation-runs", "generation_run.command"),
    ("/v1/episodes/", "/tei", "episode_tei.read"),
    ("/v1/episodes/", "/qa-evaluations", "qa_evaluations.list"),
)
_GENERATION_RUN_PREFIX = "/v1/generation-runs/"
_QA_EVALUATION_PREFIX = "/v1/qa-evaluations/"


def _generation_run_operation(path: str) -> str:
    """Return the operation for a generation-run path."""
    if path.endswith("/events"):
        return "generation_run.events.list"
    return "generation_run.read"


def _generation_route_operation(path: str) -> str | None:
    """Return a bounded operation name for an instrumented API path."""
    for prefix, suffix, operation in _PATH_OPERATIONS:
        if path.startswith(prefix) and path.endswith(suffix):
            return operation
    if path.startswith(_GENERATION_RUN_PREFIX):
        return _generation_run_operation(path)
    if path.startswith(_QA_EVALUATION_PREFIX):
        return "qa_evaluation.read"
    return None


class _GenerationRouteMetricsMiddleware:
    """Emit bounded generation-route outcome and latency observations."""

    def __init__(
        self,
        metrics: MetricsPort,
        monotonic_clock: MonotonicClockPort,
    ) -> None:
        """Store the metrics sink and monotonic clock for route timing."""
        self._metrics = metrics
        self._monotonic_clock = monotonic_clock

    async def process_request(
        self,
        req: asgi.Request,
        resp: asgi.Response,
    ) -> None:
        """Start timing an instrumented generation route."""
        del resp
        operation = _generation_route_operation(req.path)
        if operation is not None:
            req.context["generation_api_metrics"] = (
                operation,
                self._monotonic_clock.monotonic_seconds(),
            )

    async def process_response(
        self,
        req: asgi.Request,
        resp: asgi.Response,
        resource: object,
        req_succeeded: bool,  # ruff: ignore[boolean-type-hint-positional-argument]  # Falcon ASGI middleware contract.
    ) -> None:
        """Record the completed response without retaining request data."""
        del resource, req_succeeded
        observation = req.context.get("generation_api_metrics")
        if not isinstance(observation, tuple):
            return
        operation, started_at = typ.cast(
            "tuple[str, float]",
            observation,
        )
        if not isinstance(operation, str) or not isinstance(started_at, float):
            return
        outcome = _response_outcome(resp.status)
        labels = {"operation": operation, "outcome": outcome}
        self._metrics.increment_counter(_GENERATION_REQUEST_TOTAL, labels=labels)
        self._metrics.observe_latency_ms(
            _GENERATION_REQUEST_LATENCY,
            (self._monotonic_clock.monotonic_seconds() - started_at) * 1_000,
            labels=labels,
        )


def _response_outcome(status: str | int) -> str:
    """Map an HTTP response status to a bounded metric outcome."""
    status = str(status)
    if status.startswith("304"):
        return "not_modified"
    if status.startswith("2"):
        return "success"
    if status.startswith("4"):
        return "rejected"
    return "failed"


class _ShutdownHooksMiddleware:
    """Run injected async cleanup hooks during the ASGI shutdown phase."""

    def __init__(self, shutdown_hooks: tuple[ShutdownHook, ...]) -> None:
        """Store the shutdown hooks to run in order."""
        self._shutdown_hooks = shutdown_hooks

    async def process_shutdown(
        self,
        scope: dict[str, typ.Any],
        event: dict[str, typ.Any],
    ) -> None:
        """Release runtime-managed resources before the process exits."""
        del scope, event
        first_failure: Exception | None = None
        for shutdown_hook in self._shutdown_hooks:
            try:
                await shutdown_hook()
            except Exception as exc:  # ruff: ignore[blind-except] - cleanup must attempt every hook.
                log_error(logger, "ASGI shutdown hook failed.", exc_info=True)
                if first_failure is None:
                    first_failure = exc
        if first_failure is not None:
            raise first_failure


def create_app(dependencies: ApiDependencies) -> asgi.App:
    """Build and return Falcon ASGI application for canonical APIs."""
    app = asgi.App()
    app.add_middleware(AuthorizationMiddleware(dependencies.authorization))
    app.add_middleware(
        _GenerationRouteMetricsMiddleware(
            dependencies.metrics,
            dependencies.monotonic_clock,
        )
    )
    if dependencies.shutdown_hooks:
        # Falcon supports lifespan middleware at runtime, but its exported
        # middleware type union does not model process_shutdown-only hooks.
        app.add_middleware(
            typ.cast("typ.Any", _ShutdownHooksMiddleware(dependencies.shutdown_hooks))
        )
    emit_error = dependencies.unmapped_error_emitter
    if emit_error is None:
        emit_error = partial(log_error, logger)
    app.set_error_serializer(serialize_http_error)

    _register_api_routes(app, dependencies, emit_error)

    return app
