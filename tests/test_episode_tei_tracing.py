"""Integration coverage for episode-TEI retrieval tracing."""

import dataclasses as dc
import typing as typ

import httpx
import pytest

from episodic.api import create_app
from episodic.observability import RecordingTracer
from tests.fixtures.api import build_api_dependencies
from tests.fixtures.generation_run_api import HeaderPrincipalAuthorization

if typ.TYPE_CHECKING:
    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_episode_tei_trace_records_invalid_identifier(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Record invalid TEI reads without including the raw route value."""
    tracer = RecordingTracer()
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        authorization=HeaderPrincipalAuthorization(),
        tracer=tracer,
    )
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/v1/episodes/not-a-uuid/tei",
            headers={"Authorization": "Bearer principal-a"},
        )

    assert response.status_code == 400, response.text
    assert tracer.spans[0].name == "episode_tei.read", tracer.spans
    assert tracer.spans[0].attributes == {
        "operation": "episode_tei.read",
        "outcome": "rejected",
        "failure_category": "invalid_input",
    }, tracer.spans
