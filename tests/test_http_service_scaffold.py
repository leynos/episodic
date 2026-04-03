"""Tests for the Falcon-on-Granian HTTP service scaffold."""

from __future__ import annotations

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
async def test_health_live_route_returns_application_ok() -> None:
    """Expose a deterministic liveness payload once the app has booted."""
    from episodic.api import ApiDependencies, create_app

    app = create_app(ApiDependencies(uow_factory=_unexpected_uow_factory))
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", app))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": [{"name": "application", "status": "ok"}],
    }


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


def test_api_dependencies_require_callable_uow_factory() -> None:
    """Reject dependency objects without a canonical unit-of-work factory."""
    from episodic.api import ApiDependencies

    with pytest.raises(TypeError, match="uow_factory"):
        ApiDependencies(uow_factory=typ.cast("UowFactory", None))


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


@pytest.mark.asyncio
async def test_create_app_from_env_wires_database_readiness_probe(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use DATABASE_URL to build a live readiness probe in the runtime factory."""
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)

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
