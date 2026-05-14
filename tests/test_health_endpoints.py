"""Tests for HTTP health endpoint behaviour."""

import asyncio
import typing as typ

import httpx
import pytest

import tests.test_http_service_scaffold_support as scaffold_support

if typ.TYPE_CHECKING:
    from httpx._transports.asgi import _ASGIApp


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

    app = create_app(
        ApiDependencies(uow_factory=scaffold_support.unexpected_uow_factory)
    )
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
    probe_result: bool,  # noqa: FBT001  # pytest.mark.parametrize injects a bool fixture value directly
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
            uow_factory=scaffold_support.unexpected_uow_factory,
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
            uow_factory=scaffold_support.unexpected_uow_factory,
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
