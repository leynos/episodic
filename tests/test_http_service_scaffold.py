"""Tests for the Falcon-on-Granian HTTP service scaffold."""

import asyncio
import typing as typ

import httpx
import pytest

if typ.TYPE_CHECKING:
    from httpx._transports.asgi import _ASGIApp

    from episodic.api.types import UowFactory
    from episodic.canonical.ports import CanonicalUnitOfWork


class _UnexpectedUnitOfWork:
    """Fail fast if a health endpoint tries to open a canonical unit of work."""

    async def __aenter__(self) -> _UnexpectedUnitOfWork:
        msg = "Health endpoints should not open a canonical unit of work."
        raise AssertionError(msg)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        del exc_type, exc, traceback


def _unexpected_uow_factory() -> CanonicalUnitOfWork:
    """Build a unit of work that should never be used by health probes."""
    return typ.cast("CanonicalUnitOfWork", _UnexpectedUnitOfWork())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "expected_body"),
    [
        pytest.param(
            "/health/live",
            {"status": "ok", "checks": [{"name": "application", "status": "ok"}]},
            id="liveness",
        ),
        pytest.param(
            "/health/ready",
            {"status": "ok", "checks": []},
            id="readiness_no_probes",
        ),
    ],
)
async def test_health_endpoints_without_probes_return_ok(
    endpoint: str,
    expected_body: dict[str, object],
) -> None:
    """Expose the baseline health contract when no probes are configured."""
    from episodic.api import ApiDependencies, create_app

    app = create_app(ApiDependencies(uow_factory=_unexpected_uow_factory))
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", app))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get(endpoint)

    assert response.status_code == 200
    assert response.json() == expected_body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("probe_result", "expected_status", "expected_body"),
    [
        pytest.param(
            True,
            200,
            {"status": "ok", "checks": [{"name": "database", "status": "ok"}]},
            id="probe_success",
        ),
        pytest.param(
            False,
            503,
            {"status": "error", "checks": [{"name": "database", "status": "error"}]},
            id="probe_failure",
        ),
    ],
)
async def test_health_ready_route_reflects_probe_result(
    probe_result: bool,  # noqa: FBT001
    expected_status: int,
    expected_body: dict[str, object],
) -> None:
    """Report probe results without mutating the domain."""
    from episodic.api import ApiDependencies, ReadinessProbe, create_app

    async def check_database() -> bool:
        await asyncio.sleep(0)
        return probe_result

    app = create_app(
        ApiDependencies(
            uow_factory=_unexpected_uow_factory,
            readiness_probes=(ReadinessProbe(name="database", check=check_database),),
        )
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", app))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == expected_status
    assert response.json() == expected_body


@pytest.mark.asyncio
async def test_health_ready_route_treats_probe_exceptions_as_failures() -> None:
    """Map unexpected probe exceptions to the documented not-ready response."""
    from episodic.api import ApiDependencies, ReadinessProbe, create_app

    async def check_database() -> bool:
        await asyncio.sleep(0)
        msg = "probe failed"
        raise RuntimeError(msg)

    app = create_app(
        ApiDependencies(
            uow_factory=_unexpected_uow_factory,
            readiness_probes=(ReadinessProbe(name="database", check=check_database),),
        )
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", app))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "checks": [{"name": "database", "status": "error"}],
    }


def test_api_dependencies_require_callable_uow_factory() -> None:
    """Reject dependency objects without a canonical unit-of-work factory."""
    from episodic.api import ApiDependencies

    with pytest.raises(TypeError, match="uow_factory"):
        ApiDependencies(uow_factory=typ.cast("UowFactory", None))


def test_readiness_probe_requires_async_check() -> None:
    """Reject sync readiness callbacks that would fail when awaited."""
    from episodic.api import ReadinessProbe

    def check_database() -> bool:
        return True

    with pytest.raises(TypeError, match="async callable"):
        ReadinessProbe(
            name="database",
            check=typ.cast("typ.Any", check_database),
        )


def test_api_dependencies_validate_readiness_probe_entries() -> None:
    """Reject malformed readiness probe objects at dependency construction."""
    from episodic.api import ApiDependencies, ReadinessProbe

    async def check_database() -> bool:
        await asyncio.sleep(0)
        return True

    invalid_probe = typ.cast(
        "object",
        type(
            "_InvalidProbe",
            (),
            {"name": "database", "check": lambda: True},
        )(),
    )
    nameless_probe = typ.cast(
        "object",
        type("_NamelessProbe", (), {"check": check_database})(),
    )

    with pytest.raises(TypeError, match="async callable"):
        ApiDependencies(
            uow_factory=_unexpected_uow_factory,
            readiness_probes=(typ.cast("ReadinessProbe", invalid_probe),),
        )

    with pytest.raises(TypeError, match="string name"):
        ApiDependencies(
            uow_factory=_unexpected_uow_factory,
            readiness_probes=(typ.cast("ReadinessProbe", nameless_probe),),
        )


@pytest.mark.asyncio
async def test_create_app_runs_shutdown_hooks_during_asgi_shutdown() -> None:
    """Expose a cleanup seam for runtime-managed resources like DB engines."""
    from episodic.api import ApiDependencies, create_app

    hook_calls: list[str] = []

    async def shutdown_hook() -> None:
        await asyncio.sleep(0)
        hook_calls.append("shutdown")

    app = create_app(
        ApiDependencies(
            uow_factory=_unexpected_uow_factory,
            shutdown_hooks=(shutdown_hook,),
        )
    )
    sent_events: list[dict[str, str]] = []
    receive_queue = asyncio.Queue[dict[str, str]]()
    await receive_queue.put({"type": "lifespan.startup"})
    await receive_queue.put({"type": "lifespan.shutdown"})

    async def receive() -> dict[str, str]:
        return await receive_queue.get()

    async def send(message: dict[str, str]) -> None:
        sent_events.append(message)
        await asyncio.sleep(0)

    await app(
        {
            "type": "lifespan",
            "asgi": {"spec_version": "2.0", "version": "3.0"},
        },
        receive,
        send,
    )

    assert hook_calls == ["shutdown"]
    assert sent_events == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.complete"},
    ]


@pytest.mark.asyncio
async def test_create_app_keeps_existing_canonical_routes_working(
    canonical_api_async_client: httpx.AsyncClient,
) -> None:
    """Keep the canonical-content routes available through the new seam."""
    response = await canonical_api_async_client.get("/series-profiles")

    assert response.status_code == 200
    assert response.json() == {"items": []}


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
    strip_driver: bool,  # noqa: FBT001
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
