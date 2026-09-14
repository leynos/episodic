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


class _RecordingMetrics:
    """Capture bounded route observations for assertion."""

    def __init__(self) -> None:
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
        self._timestamps = timestamps

    def monotonic_seconds(self) -> float:
        """Return the next configured timestamp."""
        return next(self._timestamps)


@pytest.mark.asyncio
async def test_create_app_from_env_shares_production_metrics_sink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Runtime-created UoWs and launchers should share the production sink."""
    from episodic.api import runtime as runtime_module
    from episodic.generation import InProcessGenerationRunLauncher
    from episodic.observability import NoopMetrics, StructuredLogMetrics

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/episodic")
    monkeypatch.setenv("SOURCE_INTAKE_OBJECT_STORE_ROOT", str(tmp_path))
    monkeypatch.setenv("API_AUTHORIZATION_BEARER_TOKEN", "runtime-test-token")
    monkeypatch.setenv("API_AUTHORIZATION_PRINCIPAL_ID", "runtime-test-principal")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured_dependencies: ApiDependencies | None = None

    def capture_dependencies(dependencies: ApiDependencies) -> object:
        nonlocal captured_dependencies
        captured_dependencies = dependencies
        return object()

    with (
        mock.patch.object(
            runtime_module,
            "create_app",
            side_effect=capture_dependencies,
        ),
        mock.patch.object(
            runtime_module,
            "SqlAlchemyUnitOfWork",
            autospec=True,
        ) as unit_of_work_constructor,
    ):
        runtime_module.create_app_from_env()
        assert captured_dependencies is not None, (
            "expected captured dependencies, got None"
        )
        captured_dependencies.uow_factory()
        uow_metrics = unit_of_work_constructor.call_args.kwargs["metrics"]

    assert captured_dependencies is not None, "expected captured dependencies, got None"
    assert isinstance(captured_dependencies.launcher, InProcessGenerationRunLauncher), (
        "expected an in-process launcher, got "
        f"{type(captured_dependencies.launcher).__name__}"
    )

    assert isinstance(uow_metrics, StructuredLogMetrics), (
        f"expected structured-log metrics, got {type(uow_metrics).__name__}"
    )
    assert not isinstance(uow_metrics, NoopMetrics), (
        "expected a production metrics sink"
    )
    assert captured_dependencies.launcher.metrics is uow_metrics, (
        "runtime-created UoWs and launcher should share one metrics sink"
    )

    await captured_dependencies.shutdown_hooks[0]()


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


@pytest.mark.asyncio
async def test_create_app_from_env_shares_composition_root_tracer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The launcher must receive the same tracer instance as ApiDependencies."""
    from episodic.api import runtime as runtime_module
    from episodic.generation import InProcessGenerationRunLauncher
    from episodic.observability import StructuredLogTracer

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/episodic")
    monkeypatch.setenv("SOURCE_INTAKE_OBJECT_STORE_ROOT", str(tmp_path))
    monkeypatch.setenv("API_AUTHORIZATION_BEARER_TOKEN", "runtime-test-token")
    monkeypatch.setenv("API_AUTHORIZATION_PRINCIPAL_ID", "runtime-test-principal")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured_dependencies: ApiDependencies | None = None

    def capture_dependencies(dependencies: ApiDependencies) -> object:
        nonlocal captured_dependencies
        captured_dependencies = dependencies
        return object()

    from episodic.llm.openai_adapter import OpenAICompatibleLLMAdapter

    with (
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
        assert captured_dependencies is not None, (
            "expected captured dependencies, got None"
        )
        captured_dependencies.uow_factory()
        uow_kwargs = unit_of_work_constructor.call_args.kwargs

    assert captured_dependencies is not None, "expected captured dependencies, got None"
    assert isinstance(captured_dependencies.launcher, InProcessGenerationRunLauncher), (
        "expected an in-process launcher, got "
        f"{type(captured_dependencies.launcher).__name__}"
    )
    assert isinstance(captured_dependencies.tracer, StructuredLogTracer), (
        f"expected a structured-log tracer, got "
        f"{type(captured_dependencies.tracer).__name__}"
    )
    assert captured_dependencies.launcher.tracer is captured_dependencies.tracer, (
        "the launcher must share the composition root's tracer instance"
    )
    adapter_kwargs = adapter_factory.call_args.kwargs
    assert adapter_kwargs["tracer"] is captured_dependencies.tracer, (
        "the LLM adapter must receive the composition root's tracer"
    )
    assert adapter_kwargs["metrics"] is captured_dependencies.launcher.metrics, (
        "the LLM adapter must receive the production metrics sink"
    )
    assert uow_kwargs["tracer"] is captured_dependencies.tracer, (
        "runtime-created units of work must receive the production tracer"
    )

    await captured_dependencies.shutdown_hooks[0]()
