"""Public fixtures for authenticated generation-run REST integration tests.

The helpers create principal-owned ready ingestion jobs, provide valid no-QA
request bodies, and expose deterministic launcher and authorization fakes.
"""

import dataclasses as dc
import typing as typ
from unittest import mock

from episodic.api.authorization import (
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationResult,
)

if typ.TYPE_CHECKING:
    import uuid

    import httpx


@dc.dataclass(slots=True)
class RecordingLauncher:
    """Record generation runs scheduled by the HTTP adapter.

    Attributes
    ----------
    run_ids : list[uuid.UUID]
        Run identifiers recorded in launch order.
    """

    run_ids: list[uuid.UUID] = dc.field(default_factory=list)
    launch: mock.AsyncMock = dc.field(init=False)

    def __post_init__(self) -> None:
        """Bind the asynchronous launch surface to the run recorder."""
        self.launch = mock.AsyncMock(side_effect=self.run_ids.append)


class HeaderPrincipalAuthorization:
    """Authenticate test principals from fixed bearer-token values.

    The adapter permits ``Bearer principal-a`` and ``Bearer principal-b`` and
    rejects every other credential.
    """

    @staticmethod
    async def decide(
        context: AuthorizationContext,
    ) -> AuthorizationResult:
        """Map test bearer tokens to their principals."""
        principals = {
            "Bearer principal-a": "principal-a",
            "Bearer principal-b": "principal-b",
        }
        principal_id = principals.get(context.authorization_header or "")
        if principal_id is None:
            return AuthorizationResult(AuthorizationDecision.UNAUTHORIZED)
        return AuthorizationResult(AuthorizationDecision.PERMIT, principal_id)


async def create_ready_ingestion_job(
    client: httpx.AsyncClient,
    headers: dict[str, str] | None = None,
    key_prefix: str = "generation",
) -> str:
    """Create a ready source bundle owned by the supplied test principal.

    Parameters
    ----------
    client : httpx.AsyncClient
        ASGI client used to create the profile, ingestion job, and source.
    headers : dict[str, str] | None, optional
        Authorization headers determining the persisted job owner.
    key_prefix : str, default="generation"
        Prefix used to isolate the fixture's idempotency keys and the
        series-profile slug.

    Returns
    -------
    str
        Persisted ingestion-job identifier ready for draft generation.
    """
    request_headers = {} if headers is None else headers
    profile = await client.post(
        "/v1/series-profiles",
        headers={**request_headers, "Idempotency-Key": f"{key_prefix}-profile-key"},
        json={
            "slug": f"{key_prefix}-api-profile",
            "title": "Generation API profile",
            "description": "Generation endpoint fixture.",
            "configuration": {},
            "actor": "editor@example.com",
        },
    )
    assert profile.status_code == 201, profile.text
    job = await client.post(
        "/v1/ingestion-jobs",
        headers={**request_headers, "Idempotency-Key": f"{key_prefix}-job-key"},
        json={"series_profile_id": profile.json()["id"]},
    )
    assert job.status_code == 201, job.text
    source = await client.post(
        f"/v1/ingestion-jobs/{job.json()['id']}/sources",
        headers={**request_headers, "Idempotency-Key": f"{key_prefix}-source-key"},
        json={
            "type": "source_uri",
            "source_uri": "https://example.test/source.txt",
            "source_type": "research_note",
            "weight": 1.0,
            "metadata": {"content": "A concise source for the episode."},
        },
    )
    assert source.status_code == 201, source.text
    return typ.cast("str", job.json()["id"])


def generation_payload() -> dict[str, object]:
    """Return a valid no-QA generation request body.

    Returns
    -------
    dict[str, object]
        Payload accepted by the generation-run endpoint; its client actor is
        deliberately ignored in favour of the authenticated principal.
    """
    return {
        "quality_mode": "draft_without_qa",
        "skip_qa_rationale": "Initial editorial draft.",
        "actor": "editor@example.com",
        "template_id": "future-template",
        "prompt_overrides": {"tone": "clear"},
        "budget_hints": {"max_tokens": 1200},
    }
