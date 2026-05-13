"""Tests for runtime environment wiring of the HTTP app."""

import typing as typ

import httpx
import pytest

import tests.test_http_service_scaffold_support as scaffold_support

if typ.TYPE_CHECKING:
    from httpx._transports.asgi import _ASGIApp


def test_create_app_from_env_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail clearly when the runtime composition root lacks database config."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from episodic.api.runtime import create_app_from_env

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app_from_env()


def test_create_app_from_env_rejects_unsupported_database_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail fast with a clear error for non-PostgreSQL database URLs."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///tmp/episodic.db")

    from episodic.api.runtime import create_app_from_env

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_app_from_env()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "strip_driver",
    [
        pytest.param(False, id="async_dialect_url"),
        pytest.param(True, id="plain_postgresql_url"),
    ],
)
async def test_create_app_from_env_wires_database_readiness_probe(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    strip_driver: bool,  # noqa: FBT001  # pytest.mark.parametrize injects a bool fixture value directly
) -> None:
    """Use DATABASE_URL to build a live readiness probe in the runtime factory."""
    from urllib.parse import urlsplit, urlunsplit

    database_url = migrated_database_url
    if strip_driver:
        parsed_url = urlsplit(migrated_database_url)
        base_scheme = parsed_url.scheme.split("+", 1)[0]
        database_url = urlunsplit((
            base_scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.query,
            parsed_url.fragment,
        ))
    monkeypatch.setenv("DATABASE_URL", database_url)

    from episodic.api.runtime import create_app_from_env

    app = create_app_from_env()
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", app))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": [{"name": "database", "status": "ok"}],
    }


@pytest.mark.asyncio
async def test_create_app_from_env_runs_shutdown_hooks_during_lifespan(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure create_app_from_env shutdown hooks run during ASGI lifespan."""
    from unittest import mock

    from episodic.api import runtime as runtime_module

    monkeypatch.setenv("DATABASE_URL", migrated_database_url)

    shutdown_hook_called = False
    original_build = runtime_module._build_database_probe

    def _tracking_build(database_url: str) -> tuple[object, ...]:
        probe, uow, original_hook = original_build(database_url)

        async def _tracked_hook() -> None:
            nonlocal shutdown_hook_called
            shutdown_hook_called = True
            await original_hook()

        return probe, uow, _tracked_hook

    with mock.patch.object(
        runtime_module,
        "_build_database_probe",
        side_effect=_tracking_build,
    ):
        from episodic.api.runtime import create_app_from_env

        app = create_app_from_env()

    sent_events = await scaffold_support.run_asgi_lifespan(
        typ.cast("_ASGIApp", app),
        (
            scaffold_support.LifespanEvent(type="lifespan.startup"),
            scaffold_support.LifespanEvent(type="lifespan.shutdown"),
        ),
    )

    assert sent_events == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.complete"},
    ]
    assert shutdown_hook_called, "engine.dispose shutdown hook was not called"
