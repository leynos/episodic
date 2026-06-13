"""Tests for runtime environment wiring of the HTTP app."""

import hashlib
import typing as typ

import httpx
import pytest

import tests.test_http_service_scaffold_support as scaffold_support

if typ.TYPE_CHECKING:
    from pathlib import Path

    from httpx._transports.asgi import _ASGIApp


def test_create_app_from_env_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail clearly when the runtime composition root lacks database config."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from episodic.api.runtime import create_app_from_env

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_app_from_env()


def test_create_app_from_env_requires_object_store_root(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail clearly when the runtime composition root lacks object storage."""
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.delenv("SOURCE_INTAKE_OBJECT_STORE_ROOT", raising=False)

    from episodic.api.runtime import create_app_from_env

    with pytest.raises(RuntimeError, match="SOURCE_INTAKE_OBJECT_STORE_ROOT"):
        create_app_from_env()


def test_create_app_from_env_rejects_unsupported_database_driver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fail fast with a clear error for non-PostgreSQL database URLs."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///tmp/episodic.db")
    monkeypatch.setenv("SOURCE_INTAKE_OBJECT_STORE_ROOT", str(tmp_path))

    from episodic.api.runtime import create_app_from_env

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_app_from_env()


def test_normalize_database_urls_avoids_rendering_passwords() -> None:
    """Keep database secrets out of rendered runtime URL strings."""
    from episodic.api.runtime import _normalize_database_urls

    credential = "".join(("s3", "cr3t-value"))
    async_url, probe_kwargs = _normalize_database_urls(
        f"postgresql://api-user:{credential}@example.test:5432/episodic?sslmode=require"
    )

    assert async_url.password == credential
    assert credential not in async_url.render_as_string(hide_password=True)
    assert probe_kwargs["password"] == credential
    assert probe_kwargs["sslmode"] == "require"


def test_normalize_database_urls_uses_query_port_for_probe() -> None:
    """Pass Unix-socket query port settings to the psycopg readiness probe."""
    from episodic.api.runtime import _normalize_database_urls

    _, probe_kwargs = _normalize_database_urls(
        "postgresql:///episodic?host=/var/run/postgresql&port=6544"
    )

    assert probe_kwargs["host"] == "/var/run/postgresql"
    assert probe_kwargs["port"] == 6544


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
    tmp_path: Path,
    strip_driver: bool,  # noqa: FBT001  # pytest.mark.parametrize injects a bool fixture value directly
) -> None:
    """Use DATABASE_URL to build a live readiness probe in the runtime factory."""
    from urllib.parse import urlsplit, urlunsplit

    monkeypatch.setenv("SOURCE_INTAKE_OBJECT_STORE_ROOT", str(tmp_path / "objects"))
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
    try:
        transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", app))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            response = await client.get("/health/ready")
    finally:
        await scaffold_support.run_asgi_lifespan(
            typ.cast("_ASGIApp", app),
            (
                scaffold_support.LifespanEvent(type="lifespan.startup"),
                scaffold_support.LifespanEvent(type="lifespan.shutdown"),
            ),
        )

    assert response.status_code == 200, (
        f"unexpected readiness status code: {response.status_code}"
    )
    assert response.json() == {
        "status": "ok",
        "checks": [{"name": "database", "status": "ok"}],
    }, f"unexpected response body: {response.json()!r}"


@pytest.mark.asyncio
async def test_create_app_from_env_runs_shutdown_hooks_during_lifespan(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ensure create_app_from_env shutdown hooks run during ASGI lifespan."""
    from unittest import mock

    from episodic.api import runtime as runtime_module

    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.setenv("SOURCE_INTAKE_OBJECT_STORE_ROOT", str(tmp_path / "objects"))

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
    ], f"unexpected lifespan events: {sent_events!r}"
    assert shutdown_hook_called, "engine.dispose shutdown hook was not called"


@pytest.mark.asyncio
async def test_create_app_from_env_wires_object_store_for_uploads(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Runtime-created apps accept uploads when object storage is configured."""
    object_store_root = tmp_path / "objects"
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.setenv("SOURCE_INTAKE_OBJECT_STORE_ROOT", str(object_store_root))

    from episodic.api.runtime import create_app_from_env

    app = create_app_from_env()
    try:
        transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", app))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            payload = b"runtime upload\n"
            response = await client.post(
                "/v1/uploads",
                headers={"Idempotency-Key": "runtime-upload"},
                files={
                    "file": ("source.txt", payload, "text/plain"),
                    "content_type": (None, "text/plain"),
                    "declared_size": (None, str(len(payload))),
                    "declared_sha256": (None, hashlib.sha256(payload).hexdigest()),
                },
            )
    finally:
        await scaffold_support.run_asgi_lifespan(
            typ.cast("_ASGIApp", app),
            (
                scaffold_support.LifespanEvent(type="lifespan.startup"),
                scaffold_support.LifespanEvent(type="lifespan.shutdown"),
            ),
        )

    assert response.status_code == 201, response.text
    response_body = response.json()
    expected_hash = hashlib.sha256(payload).hexdigest()
    stored_path = object_store_root / "uploads" / response_body["id"]
    assert response_body["content_hash"] == f"sha256:{expected_hash}"
    assert stored_path.is_file(), f"expected upload payload at {stored_path}"
    assert stored_path.read_bytes() == payload
