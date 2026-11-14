"""Verify generation-run source-intake errors reach the app's error emitter."""

import asyncio
import dataclasses as dc
import typing as typ
from unittest import mock

import httpx
import pytest

import episodic.api.app as api_app
import episodic.api.errors as api_errors
from episodic.api import create_app
from episodic.api.resources import generation_runs
from episodic.canonical.source_intake_errors import SourceIntakeError
from tests.fixtures.api import build_api_dependencies
from tests.fixtures.generation_run_api import (
    HeaderPrincipalAuthorization,
    RecordingLauncher,
    create_ready_ingestion_job,
    generation_payload,
)

if typ.TYPE_CHECKING:
    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.fixtures.api_errors import SpyLogger


class _UnexpectedMaterialisationError(SourceIntakeError):
    """Represent a credential-bearing materialisation failure in this test."""

    def __init__(self) -> None:
        """Keep the source message local to the test exception type."""
        super().__init__("Materialisation failure: private marker")


@pytest.mark.asyncio
async def test_generation_run_materialisation_error_uses_configured_emitter(
    session_factory: async_sessionmaker[AsyncSession],
    spy_logger: SpyLogger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The serializer emits generation-run failures through the app dependency."""
    default_logger = mock.Mock()
    monkeypatch.setattr(api_app, "log_error", default_logger)
    monkeypatch.setattr(api_errors, "log_error", default_logger)
    dependencies = dc.replace(
        build_api_dependencies(session_factory),
        authorization=HeaderPrincipalAuthorization(),
        launcher=RecordingLauncher(),
        unmapped_error_emitter=spy_logger,
    )
    headers = {"Authorization": "Bearer principal-a"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=typ.cast("_ASGIApp", create_app(dependencies))
        ),
        base_url="http://testserver",
    ) as client:
        ingestion_job_id = await create_ready_ingestion_job(client, headers)

        async def fail_materialisation(
            *_args: object,
            **_kwargs: object,
        ) -> typ.NoReturn:
            """Raise an unmapped intake error during episode materialisation."""
            await asyncio.sleep(0)
            raise _UnexpectedMaterialisationError

        monkeypatch.setattr(
            generation_runs,
            "materialise_episode_from_ingestion",
            fail_materialisation,
        )
        response = await client.post(
            f"/v1/ingestion-jobs/{ingestion_job_id}/generation-runs",
            headers={**headers, "Idempotency-Key": "unmapped-materialisation"},
            json=generation_payload(),
        )

    assert response.status_code == 500, response.text
    assert response.json() == {
        "code": "internal_error",
        "message": "Unexpected source-intake error.",
        "details": {},
    }, response.text
    assert "private marker" not in response.text, response.text
    assert len(spy_logger.calls) == 1, spy_logger.calls
    assert default_logger.call_count == 0, (
        "the app must not replace its injected emitter"
    )
