"""Composition-root agreement between the API and the launcher graph (D7).

The capability set the REST adapter advertises must be the one the launcher's
graph reports. Both are derived from one graph instance in the composition
root, and this test pins that they are the same object's answer.
"""

import asyncio
import pathlib
import typing as typ

import episodic.api.runtime as runtime_module
from episodic.api.dependencies import ReadinessProbe
from episodic.canonical.generation_graph_ports import QualityEvaluatorSet
from episodic.canonical.generation_quality import QualityMode
from episodic.generation import GenerationSourceLimits
from episodic.orchestration import LangGraphContentGenerationGraph

if typ.TYPE_CHECKING:
    import pytest

    from episodic.api.dependencies import ApiDependencies
    from episodic.llm import LLMRequest, LLMResponse
    from episodic.observability import TracerPort, ValueMetricsPort


class _UnusedLLMPort:
    """LLM port stub that is never invoked by launcher construction."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Fail if the composition root calls the unused port."""
        _ = request
        msg = "the unused LLM port must not be called"
        raise AssertionError(msg)

    async def aclose(self) -> None:
        """Accept shutdown without doing anything."""


async def _healthy() -> bool:
    """Return a healthy readiness result without blocking."""
    await asyncio.sleep(0)
    return True


def _unused_uow_factory() -> object:
    """Return a placeholder unit of work."""
    return object()


def _fake_database_probe(
    *args: object, **kwargs: object
) -> tuple[object, object, object]:
    """Return a healthy probe, an unused unit-of-work factory, and a hook."""
    _ = (args, kwargs)
    probe = ReadinessProbe(name="database", check=_healthy)
    return probe, _unused_uow_factory, _healthy


def _unused_object_store(*args: object, **kwargs: object) -> object:
    """Return a placeholder where the composition root expects an object store."""
    _ = (args, kwargs)
    return object()


def _unused_metrics(*args: object, **kwargs: object) -> ValueMetricsPort:
    """Return a placeholder metrics sink."""
    _ = (args, kwargs)
    return typ.cast("ValueMetricsPort", object())


def _unused_tracer(*args: object, **kwargs: object) -> TracerPort:
    """Return a placeholder tracer."""
    _ = (args, kwargs)
    return typ.cast("TracerPort", object())


def _config(tmp_path: pathlib.Path) -> object:
    """Build the runtime configuration the launcher needs."""
    return runtime_module.RuntimeConfig(
        database_url="postgresql+psycopg://unused",
        source_intake_object_store_root=tmp_path,
        llm_base_url="https://example.test/v1",
        llm_api_key="test-key",
        draft_model="draft-model",
        pricing_snapshot_directory=pathlib.Path("config/pricing-snapshots"),
        authorization_bearer_token="test-token",  # ruff: ignore[hardcoded-password-func-arg] - local-only test token.
        authorization_principal_id="runtime-test-principal",
        generation_source_limits=GenerationSourceLimits(),
    )


def test_launcher_uses_the_injected_graph(
    tmp_path: pathlib.Path,
) -> None:
    """The launcher stores the exact graph the composition root built."""
    graph = LangGraphContentGenerationGraph(QualityEvaluatorSet(()))
    launcher = runtime_module._build_generation_launcher(
        lambda: typ.cast("typ.Any", object()),
        typ.cast("typ.Any", _UnusedLLMPort()),
        runtime_module._GenerationLauncherRuntime(
            metrics=_unused_metrics(),
            tracer=_unused_tracer(),
            content_graph=graph,
        ),
        config=typ.cast("typ.Any", _config(tmp_path)),
    )

    assert launcher.content_graph is graph, "the launcher must use the injected graph"


def test_composition_root_advertises_the_graph_capability(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The advertised accepted modes equal the launcher graph's own answer."""
    captured: dict[str, ApiDependencies] = {}

    def _capture(dependencies: ApiDependencies) -> object:
        captured["dependencies"] = dependencies
        return object()

    monkeypatch.setattr(
        runtime_module, "_load_runtime_config", lambda: _config(tmp_path)
    )
    monkeypatch.setattr(
        runtime_module,
        "_build_database_probe",
        _fake_database_probe,
    )
    monkeypatch.setattr(runtime_module, "create_app", _capture)
    monkeypatch.setattr(
        runtime_module,
        "_build_llm_port",
        lambda *args, **kwargs: _UnusedLLMPort(),
    )
    monkeypatch.setattr(runtime_module, "FilesystemObjectStore", _unused_object_store)
    monkeypatch.setattr(runtime_module, "StructuredLogMetrics", _unused_metrics)
    monkeypatch.setattr(runtime_module, "StructuredLogTracer", _unused_tracer)

    runtime_module.create_app_from_env()

    dependencies = captured["dependencies"]
    assert dependencies.accepted_quality_modes == frozenset({
        QualityMode.DRAFT_WITHOUT_QA
    }), dependencies.accepted_quality_modes
    launcher = typ.cast("typ.Any", dependencies.launcher)
    assert (
        launcher.content_graph.accepted_quality_modes()
        == dependencies.accepted_quality_modes
    ), "the API capability set must equal the launcher graph's answer"
