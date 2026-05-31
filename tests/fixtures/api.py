"""Falcon HTTP/ASGI test-client fixtures."""

import dataclasses as dc
import typing as typ

import httpx
import pytest
import pytest_asyncio

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from falcon import testing
    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api import ApiDependencies
    from episodic.api.authorization import AuthorizationPort


@dc.dataclass(frozen=True, slots=True)
class CanonicalApiCreators:
    """Callable helpers that create canonical entities through the v1 API."""

    series_profile: cabc.Callable[[str], str]
    episode_template: cabc.Callable[[str], str]


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
    return build_api_dependencies(session_factory)


def build_api_dependencies(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    authorization: AuthorizationPort | None = None,
) -> ApiDependencies:
    """Build typed API dependencies with optional authorization override."""
    from episodic.api import ApiDependencies
    from episodic.canonical.storage import SqlAlchemyUnitOfWork

    if authorization is None:
        return ApiDependencies(
            uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory)
        )
    return ApiDependencies(
        uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
        authorization=authorization,
    )


@pytest_asyncio.fixture
async def canonical_api_async_client(
    canonical_api_dependencies: ApiDependencies,
) -> cabc.AsyncIterator[httpx.AsyncClient]:
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


@pytest.fixture
def canonical_api_creators(
    canonical_api_client: testing.TestClient,
) -> CanonicalApiCreators:
    """Bundle the canonical-API entity-creator callables for use in tests."""

    def _create_series_profile(slug: str) -> str:
        response = canonical_api_client.simulate_post(
            "/v1/series-profiles",
            json={
                "slug": slug,
                "title": "API Profile",
                "description": "Created through API",
                "configuration": {"tone": "precise"},
                "guardrails": {
                    "instruction": "Keep claims attributable.",
                    "banned_phrases": ["viral sensation"],
                },
                "actor": "api-user@example.com",
                "note": "Initial profile",
            },
        )
        assert response.status_code == 201, (
            f"Expected profile creation for slug={slug!r} to return 201, "
            f"got {response.status_code}: {response.text}"
        )
        return typ.cast("str", typ.cast("dict[str, object]", response.json)["id"])

    def _create_episode_template(profile_id: str) -> str:
        response = canonical_api_client.simulate_post(
            "/v1/episode-templates",
            json={
                "series_profile_id": profile_id,
                "slug": "api-template",
                "title": "API Template",
                "description": "Template through API",
                "structure": {"segments": ["intro", "main", "outro"]},
                "guardrails": {
                    "instruction": "End with a recap.",
                    "required_sections": ["intro", "main", "outro"],
                },
                "actor": "api-user@example.com",
                "note": "Initial template",
            },
        )
        assert response.status_code == 201, (
            f"Expected template creation for profile_id={profile_id!r} to return 201, "
            f"got {response.status_code}: {response.text}"
        )
        return typ.cast("str", typ.cast("dict[str, object]", response.json)["id"])

    return CanonicalApiCreators(
        series_profile=_create_series_profile,
        episode_template=_create_episode_template,
    )
