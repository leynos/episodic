"""Tests for production metrics wiring in the runtime composition root."""

import typing as typ
from unittest import mock

import pytest

if typ.TYPE_CHECKING:
    from pathlib import Path

    from episodic.api.dependencies import ApiDependencies


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
