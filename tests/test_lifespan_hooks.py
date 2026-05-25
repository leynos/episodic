"""Tests for HTTP app lifespan hook behaviour."""

import asyncio
import typing as typ

import pytest

import tests.test_http_service_scaffold_support as scaffold_support

if typ.TYPE_CHECKING:
    import httpx
    from httpx._transports.asgi import _ASGIApp


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
            uow_factory=scaffold_support.unexpected_uow_factory,
            shutdown_hooks=(shutdown_hook,),
        )
    )
    sent_events = await scaffold_support.run_asgi_lifespan(
        typ.cast("_ASGIApp", app),
        (
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ),
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
    response = await canonical_api_async_client.get("/v1/series-profiles")

    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 20, "offset": 0, "total": 0}
