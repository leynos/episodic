"""Tests for HTTP app lifespan hook behaviour."""

import asyncio
import typing as typ

import pytest

import tests.test_http_service_scaffold_support as scaffold_support

if typ.TYPE_CHECKING:
    from pathlib import Path

    import httpx
    from httpx._transports.asgi import _ASGIApp


@pytest.mark.asyncio
async def test_create_app_runs_shutdown_hooks_during_asgi_shutdown() -> None:
    """Run lifecycle cleanup hooks sequentially in their supplied order."""
    from episodic.api import ApiDependencies, create_app

    hook_calls: list[str] = []
    first_hook_completed = False

    async def first_shutdown_hook() -> None:
        nonlocal first_hook_completed
        await asyncio.sleep(0)
        hook_calls.append("first")
        first_hook_completed = True

    async def second_shutdown_hook() -> None:
        await asyncio.sleep(0)
        assert first_hook_completed, "shutdown hooks must not run concurrently"
        hook_calls.append("second")

    app = create_app(
        ApiDependencies(
            uow_factory=scaffold_support.unexpected_uow_factory,
            shutdown_hooks=(first_shutdown_hook, second_shutdown_hook),
        )
    )
    sent_events = await scaffold_support.run_asgi_lifespan(
        typ.cast("_ASGIApp", app),
        (
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ),
    )

    assert hook_calls == ["first", "second"], (
        "shutdown hooks must run in supplied order"
    )
    assert sent_events == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.complete"},
    ], "sent_events must contain completed startup and shutdown events"


@pytest.mark.asyncio
async def test_shutdown_runs_remaining_hooks_after_failure() -> None:
    """Attempt all ordered shutdown hooks before surfacing the first failure."""
    from episodic.api.app import _ShutdownHooksMiddleware

    calls: list[str] = []

    async def failing_hook() -> None:
        await asyncio.sleep(0)
        calls.append("failing")
        msg = "first hook failed"
        raise RuntimeError(msg)

    async def later_hook() -> None:
        await asyncio.sleep(0)
        calls.append("later")

    middleware = _ShutdownHooksMiddleware((failing_hook, later_hook))

    with pytest.raises(RuntimeError, match="first hook failed"):
        await middleware.process_shutdown({}, {})

    assert calls == ["failing", "later"], calls


@pytest.mark.asyncio
async def test_runtime_lifespan_shuts_down_generation_before_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ensure runtime teardown cancels generation before disposing its database."""
    from unittest import mock

    from episodic.api import runtime as runtime_module

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/episodic")
    monkeypatch.setenv("SOURCE_INTAKE_OBJECT_STORE_ROOT", str(tmp_path))
    monkeypatch.setenv("API_AUTHORIZATION_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("API_AUTHORIZATION_PRINCIPAL_ID", "test-principal")
    events: list[str] = []

    async def shutdown_database() -> None:
        await asyncio.sleep(0)
        events.append("database.dispose")

    async def check_database() -> bool:
        await asyncio.sleep(0)
        return True

    async def shutdown_launcher() -> None:
        await asyncio.sleep(0)
        events.append("launcher.shutdown")

    async def close_llm() -> None:
        await asyncio.sleep(0)
        events.append("llm_port.aclose")

    def unit_of_work_factory() -> object:
        return object()

    probe = runtime_module.ReadinessProbe(name="database", check=check_database)
    launcher = mock.Mock()
    launcher.shutdown.side_effect = shutdown_launcher
    llm_port = mock.Mock()
    llm_port.aclose.side_effect = close_llm
    with (
        mock.patch.object(
            runtime_module,
            "_build_database_probe",
            return_value=(probe, unit_of_work_factory, shutdown_database),
        ),
        mock.patch.object(runtime_module, "_build_llm_port", return_value=llm_port),
        mock.patch.object(
            runtime_module,
            "_build_generation_launcher",
            return_value=launcher,
        ),
    ):
        app = runtime_module.create_app_from_env()

    sent_events = await scaffold_support.run_asgi_lifespan(
        typ.cast("_ASGIApp", app),
        (
            scaffold_support.LifespanEvent(type="lifespan.startup"),
            scaffold_support.LifespanEvent(type="lifespan.shutdown"),
        ),
    )

    assert events == [
        "launcher.shutdown",
        "llm_port.aclose",
        "database.dispose",
    ], f"unexpected runtime shutdown order: {events!r}"
    assert sent_events == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.complete"},
    ], f"unexpected lifespan events: {sent_events!r}"


@pytest.mark.asyncio
async def test_create_app_keeps_existing_canonical_routes_working(
    canonical_api_async_client: httpx.AsyncClient,
) -> None:
    """Keep the canonical-content routes available through the new seam."""
    response = await canonical_api_async_client.get("/v1/series-profiles")

    assert response.status_code == 200, "response status must be HTTP 200"
    assert response.json() == {"items": [], "limit": 20, "offset": 0, "total": 0}, (
        "response payload must match the empty series-profile page"
    )
