"""Tests for production metrics wiring in the runtime composition root."""

import typing as typ
from unittest import mock

import httpx
import pytest

import tests.test_http_service_scaffold_support as scaffold_support

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from httpx._transports.asgi import _ASGIApp

    from episodic.api.dependencies import ApiDependencies
    from episodic.canonical.storage import UnitOfWorkRuntime
    from episodic.llm.openai_adapter import OpenAICompatibleLLMRuntime


class _RecordingMetrics:
    """Capture bounded route observations for assertion."""

    def __init__(self) -> None:
        """Initialize empty counter and latency observation lists."""
        self.counters: list[tuple[str, dict[str, str]]] = []
        self.latencies: list[tuple[str, float, dict[str, str]]] = []

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record one bounded counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record one bounded latency observation."""
        self.latencies.append((name, value, dict(labels)))


class _SteppingMonotonicClock:
    """Return deterministic monotonic timestamps for request timing tests."""

    def __init__(self, timestamps: cabc.Iterator[float]) -> None:
        """Store the iterator of timestamps to replay."""
        self._timestamps = timestamps

    def monotonic_seconds(self) -> float:
        """Return the next configured timestamp."""
        return next(self._timestamps)


def _configure_runtime_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    log_level: str,
) -> None:
    """Set the environment required by the production runtime factory."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/episodic")
    monkeypatch.setenv("SOURCE_INTAKE_OBJECT_STORE_ROOT", str(tmp_path))
    monkeypatch.setenv("API_AUTHORIZATION_BEARER_TOKEN", "runtime-test-token")
    monkeypatch.setenv("API_AUTHORIZATION_PRINCIPAL_ID", "runtime-test-principal")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("EPISODIC_LOG_LEVEL", log_level)


def _compose_runtime_observability_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    log_level: str = "INFO",
) -> tuple[ApiDependencies, dict[str, object], dict[str, object]]:
    """Capture runtime adapter arguments while composing the production app."""
    _configure_runtime_environment(monkeypatch, tmp_path, log_level=log_level)

    from episodic.api import runtime as runtime_module
    from episodic.llm.openai_adapter import OpenAICompatibleLLMAdapter
    from episodic.observability import (
        NoopTracer,
        NoopValueMetrics,
        StructuredLogMetrics,
        StructuredLogTracer,
    )

    captured_dependencies: ApiDependencies | None = None

    def capture_dependencies(dependencies: ApiDependencies) -> object:
        """Store the dependencies and return a placeholder app object.

        Returns
        -------
        object
            A new plain object standing in for the composed application.
        """
        nonlocal captured_dependencies
        captured_dependencies = dependencies
        return object()

    with (
        mock.patch.object(
            runtime_module,
            "configure_structured_observability",
            return_value=(
                (NoopValueMetrics(), NoopTracer())
                if log_level == "WARNING"
                else (StructuredLogMetrics(), StructuredLogTracer())
            ),
        ) as observability_configurer,
        mock.patch.object(
            runtime_module,
            "create_app",
            side_effect=capture_dependencies,
        ),
        mock.patch.object(
            runtime_module,
            "OpenAICompatibleLLMAdapter",
            wraps=OpenAICompatibleLLMAdapter,
        ) as adapter_factory,
        mock.patch.object(
            runtime_module,
            "SqlAlchemyUnitOfWork",
            autospec=True,
        ) as unit_of_work_constructor,
    ):
        runtime_module.create_app_from_env()
        observability_configurer.assert_called_once_with(log_level)
        assert captured_dependencies is not None, (
            "expected captured dependencies, got None"
        )
        captured_dependencies.uow_factory()

        adapter_call = adapter_factory.call_args
        unit_of_work_call = unit_of_work_constructor.call_args
        assert adapter_call is not None, "expected an adapter constructor call"
        assert unit_of_work_call is not None, "expected a unit-of-work constructor call"
        adapter_kwargs = typ.cast("dict[str, object]", adapter_call.kwargs)
        unit_of_work_kwargs = typ.cast("dict[str, object]", unit_of_work_call.kwargs)

    assert captured_dependencies is not None, "expected captured dependencies, got None"
    return captured_dependencies, adapter_kwargs, unit_of_work_kwargs


@pytest.mark.asyncio
async def test_create_app_from_env_shares_production_observability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Composition-root adapters should share production observability ports."""
    from episodic.generation import InProcessGenerationRunLauncher
    from episodic.observability import StructuredLogMetrics, StructuredLogTracer

    dependencies, adapter_kwargs, uow_kwargs = (
        _compose_runtime_observability_dependencies(monkeypatch, tmp_path)
    )
    assert isinstance(dependencies.launcher, InProcessGenerationRunLauncher), (
        f"expected an in-process launcher, got {type(dependencies.launcher).__name__}"
    )

    assert isinstance(dependencies.metrics, StructuredLogMetrics), (
        "the composition root must install structured-log metrics"
    )
    assert isinstance(dependencies.tracer, StructuredLogTracer), (
        "the composition root must install structured-log tracing"
    )
    assert dependencies.launcher.metrics is dependencies.metrics, (
        "the launcher must share the composition root's metrics sink"
    )
    assert dependencies.launcher.tracer is dependencies.tracer, (
        "the launcher must share the composition root's tracer"
    )
    adapter_runtime = typ.cast("OpenAICompatibleLLMRuntime", adapter_kwargs["runtime"])
    uow_runtime = typ.cast("UnitOfWorkRuntime", uow_kwargs["runtime"])
    assert adapter_runtime.metrics is dependencies.launcher.metrics, (
        "the LLM adapter must receive the launcher's metrics sink"
    )
    assert adapter_runtime.tracer is dependencies.tracer, (
        "the LLM adapter must receive the composition root's tracer"
    )
    assert uow_runtime.metrics is dependencies.launcher.metrics, (
        "the unit of work must receive the launcher's metrics sink"
    )
    assert uow_runtime.tracer is dependencies.tracer, (
        "the unit of work must receive the composition root's tracer"
    )

    await dependencies.shutdown_hooks[0]()


@pytest.mark.asyncio
async def test_runtime_disables_info_telemetry_above_info_level(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Warning-level runtime logging keeps API errors without INFO telemetry."""
    from episodic.observability import NoopMetrics, NoopTracer

    dependencies, _, _ = _compose_runtime_observability_dependencies(
        monkeypatch,
        tmp_path,
        log_level="WARNING",
    )

    assert isinstance(dependencies.metrics, NoopMetrics), (
        "INFO structured metrics must be disabled above INFO"
    )
    assert isinstance(dependencies.tracer, NoopTracer), (
        "INFO structured spans must be disabled above INFO"
    )
    await dependencies.shutdown_hooks[0]()


@pytest.mark.asyncio
async def test_generation_route_metrics_use_injected_monotonic_clock() -> None:
    """Generation-route latency uses the dependency-injected clock seam."""
    from episodic.api import ApiDependencies, create_app

    metrics = _RecordingMetrics()
    clock = _SteppingMonotonicClock(iter((10.0, 10.25)))
    dependencies = ApiDependencies(
        uow_factory=scaffold_support.unexpected_uow_factory,
        metrics=metrics,
        monotonic_clock=clock,
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/v1/generation-runs/not-a-uuid")

    expected_labels = {"operation": "generation_run.read", "outcome": "rejected"}
    assert response.status_code == 400, response.text
    assert metrics.counters == [("generation_api_request_total", expected_labels)], (
        metrics.counters
    )
    assert metrics.latencies == [
        ("generation_api_request_latency_ms", 250.0, expected_labels)
    ], metrics.latencies
