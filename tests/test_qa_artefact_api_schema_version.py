"""Integration tests for the retrieval API's schema-version boundary.

A row written by a newer release must fail with the documented
``qa_artefact_schema_unsupported`` envelope on both routes, and must not confirm
its existence to a caller that does not own the episode. Both tests widen a
stored finding as well as the version, so a reader that validated findings
before checking the version would answer 500 instead.
"""

import typing as typ

import pytest

from episodic.canonical.qa_artefacts import QA_ARTEFACT_SCHEMA_VERSION
from tests.fixtures.api import api_async_client
from tests.steps.qa_artefact_retrieval_seed import PRINCIPAL_A, PRINCIPAL_B
from tests.steps.qa_artefact_retrieval_support import (
    build_qa_dependencies,
    error_envelope,
    listing_items,
    pretend_a_newer_release_wrote_the_row,
    seed_background_evaluations,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.asyncio
async def test_unsupported_schema_version_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A row written by a newer release fails loudly on either route."""
    dependencies = build_qa_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        episode = await seed_background_evaluations(dependencies)
        seeded = await client.get(
            f"/v1/episodes/{episode.episode_id}/qa-evaluations",
            headers=PRINCIPAL_A,
            params={"evaluator": "pedante"},
        )
        evaluation_id = typ.cast("str", listing_items(seeded)[0]["id"])
        await pretend_a_newer_release_wrote_the_row(session_factory, evaluation_id)
        listed = await client.get(
            f"/v1/episodes/{episode.episode_id}/qa-evaluations",
            headers=PRINCIPAL_A,
        )
        detailed = await client.get(
            f"/v1/qa-evaluations/{evaluation_id}",
            headers=PRINCIPAL_A,
        )

    for response in (listed, detailed):
        envelope = error_envelope(response)
        details = typ.cast("dict[str, object]", envelope["details"])
        assert response.status_code == 422, response.text
        assert envelope["code"] == "qa_artefact_schema_unsupported", envelope
        assert details["evaluation_id"] == evaluation_id, envelope
        assert details["artefact_schema_version"] == (QA_ARTEFACT_SCHEMA_VERSION + 1), (
            envelope
        )
        assert details["supported_artefact_schema_version"] == (
            QA_ARTEFACT_SCHEMA_VERSION
        ), envelope


@pytest.mark.asyncio
async def test_unsupported_schema_version_stays_hidden_from_foreign_callers(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An unreadable row owned elsewhere is still reported as absent."""
    dependencies = build_qa_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        episode = await seed_background_evaluations(dependencies)
        seeded = await client.get(
            f"/v1/episodes/{episode.episode_id}/qa-evaluations",
            headers=PRINCIPAL_A,
            params={"evaluator": "pedante"},
        )
        evaluation_id = typ.cast("str", listing_items(seeded)[0]["id"])
        await pretend_a_newer_release_wrote_the_row(session_factory, evaluation_id)
        foreign = await client.get(
            f"/v1/qa-evaluations/{evaluation_id}",
            headers=PRINCIPAL_B,
        )

    envelope = error_envelope(foreign)
    assert foreign.status_code == 404, foreign.text
    assert envelope["code"] == "qa_evaluation_not_found", envelope
