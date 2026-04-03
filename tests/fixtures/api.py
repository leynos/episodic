"""Falcon HTTP/ASGI test-client fixtures."""

import typing as typ

import httpx
import pytest
import pytest_asyncio

if typ.TYPE_CHECKING:
    from falcon import testing
    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api import ApiDependencies


@pytest.fixture
def canonical_api_client(
    canonical_api_dependencies: ApiDependencies,
) -> testing.TestClient:
    """Build a Falcon test client for profile/template REST endpoints."""
    from falcon import testing

    from episodic.api import create_app

    app = create_app(canonical_api_dependencies)
    return testing.TestClient(app)


@pytest.fixture
def canonical_api_dependencies(
    session_factory: async_sessionmaker[AsyncSession],
) -> ApiDependencies:
    """Build typed API dependencies for in-memory ASGI tests."""
    from episodic.api import ApiDependencies
    from episodic.canonical.storage import SqlAlchemyUnitOfWork

    return ApiDependencies(uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory))


@pytest_asyncio.fixture
async def canonical_api_async_client(
    canonical_api_dependencies: ApiDependencies,
) -> typ.AsyncIterator[httpx.AsyncClient]:
    """Yield an async HTTP client bound to the Falcon ASGI app."""
    from episodic.api import create_app

    transport = httpx.ASGITransport(
        app=typ.cast("_ASGIApp", create_app(canonical_api_dependencies))
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client
