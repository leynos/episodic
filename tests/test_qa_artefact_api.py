"""Integration tests for the QA-artefact retrieval endpoints.

The REST API is retrieval-only, so each test seeds artefacts through the same
recording service the launcher will call, then exercises the HTTP contract.
"""

import typing as typ
import uuid

import pytest

from tests.fixtures.api import api_async_client
from tests.steps.qa_artefact_retrieval_seed import (
    ANTHEM_EVALUATION_ID,
    PRINCIPAL_A,
    PRINCIPAL_B,
    QaEpisodeFixture,
    create_generated_episode,
    record_anthem_success,
    record_background_evaluations,
)
from tests.steps.qa_artefact_retrieval_support import build_qa_dependencies

if typ.TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.dependencies import ApiDependencies


async def _seed(dependencies: ApiDependencies) -> QaEpisodeFixture:
    """Create one generated episode and its three background evaluations."""
    episode = await create_generated_episode(dependencies)
    await record_background_evaluations(dependencies, episode)
    return episode


def _items(response: httpx.Response) -> list[dict[str, object]]:
    """Return the items of a successful listing response."""
    payload = typ.cast("dict[str, object]", response.json())
    return typ.cast("list[dict[str, object]]", payload["items"])


def _envelope(response: httpx.Response) -> dict[str, object]:
    """Return an error response's envelope."""
    return typ.cast("dict[str, object]", response.json())


@pytest.mark.asyncio
async def test_list_returns_every_evaluation_newest_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The unfiltered listing carries the page envelope and newest-first order."""
    dependencies = build_qa_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        episode = await _seed(dependencies)
        response = await client.get(
            f"/v1/episodes/{episode.episode_id}/qa-evaluations",
            headers=PRINCIPAL_A,
        )

    payload = typ.cast("dict[str, object]", response.json())
    assert response.status_code == 200, response.text
    assert [item["evaluator"] for item in _items(response)] == [
        "anthem",
        "chrono",
        "pedante",
    ], payload
    assert payload["limit"] == 20, payload
    assert payload["offset"] == 0, payload
    assert payload["total"] == 3, payload
    assert [item["finding_count"] for item in _items(response)] == [0, 0, 3], payload


@pytest.mark.asyncio
async def test_list_filters_by_evaluator_and_compliance_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Either filter narrows the page and its unpaged total together."""
    dependencies = build_qa_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        episode = await _seed(dependencies)
        endpoint = f"/v1/episodes/{episode.episode_id}/qa-evaluations"
        pedante = await client.get(
            endpoint,
            headers=PRINCIPAL_A,
            params={"evaluator": "pedante"},
        )
        non_compliant = await client.get(
            endpoint,
            headers=PRINCIPAL_A,
            params={"compliance_status": "non_compliant"},
        )
        empty = await client.get(
            endpoint,
            headers=PRINCIPAL_A,
            params={"evaluator": "chrono", "compliance_status": "non_compliant"},
        )

    assert [item["evaluator"] for item in _items(pedante)] == ["pedante"], pedante.text
    assert typ.cast("dict[str, object]", pedante.json())["total"] == 1, pedante.text
    assert [item["compliance_status"] for item in _items(non_compliant)] == [
        "non_compliant"
    ], non_compliant.text
    assert _items(empty) == [], empty.text
    assert typ.cast("dict[str, object]", empty.json())["total"] == 0, empty.text


@pytest.mark.asyncio
async def test_list_paginates_and_echoes_the_requested_page(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A limit and offset select one page while the total stays unpaged."""
    dependencies = build_qa_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        episode = await _seed(dependencies)
        response = await client.get(
            f"/v1/episodes/{episode.episode_id}/qa-evaluations",
            headers=PRINCIPAL_A,
            params={"limit": 1, "offset": 1},
        )

    payload = typ.cast("dict[str, object]", response.json())
    assert response.status_code == 200, response.text
    assert [item["evaluator"] for item in _items(response)] == ["chrono"], payload
    assert payload["limit"] == 1, payload
    assert payload["offset"] == 1, payload
    assert payload["total"] == 3, payload


@pytest.mark.asyncio
async def test_list_rejects_out_of_range_pagination(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Pagination bounds are enforced before any query runs."""
    dependencies = build_qa_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        episode = await _seed(dependencies)
        response = await client.get(
            f"/v1/episodes/{episode.episode_id}/qa-evaluations",
            headers=PRINCIPAL_A,
            params={"limit": 0},
        )

    envelope = _envelope(response)
    assert response.status_code == 400, response.text
    assert envelope["code"] == "validation_error", envelope
    assert typ.cast("dict[str, object]", envelope["details"])["field"] == "limit", (
        envelope
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parameter", "value"),
    [("evaluator", "nonsuch"), ("compliance_status", "unknown")],
)
async def test_list_rejects_unknown_enum_filters(
    session_factory: async_sessionmaker[AsyncSession],
    parameter: str,
    value: str,
) -> None:
    """An unknown enum value names its offending parameter."""
    dependencies = build_qa_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        episode = await _seed(dependencies)
        response = await client.get(
            f"/v1/episodes/{episode.episode_id}/qa-evaluations",
            headers=PRINCIPAL_A,
            params={parameter: value},
        )

    envelope = _envelope(response)
    details = typ.cast("dict[str, object]", envelope["details"])
    assert response.status_code == 400, response.text
    assert envelope["code"] == "validation_error", envelope
    assert details["field"] == parameter, envelope


@pytest.mark.asyncio
async def test_detail_returns_findings_in_emitted_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The detail representation is the summary plus ordered findings."""
    dependencies = build_qa_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        episode = await _seed(dependencies)
        listing = await client.get(
            f"/v1/episodes/{episode.episode_id}/qa-evaluations",
            headers=PRINCIPAL_A,
            params={"evaluator": "pedante"},
        )
        evaluation_id = typ.cast("str", _items(listing)[0]["id"])
        response = await client.get(
            f"/v1/qa-evaluations/{evaluation_id}",
            headers=PRINCIPAL_A,
        )

    payload = typ.cast("dict[str, object]", response.json())
    findings = typ.cast("list[dict[str, object]]", payload["findings"])
    assert response.status_code == 200, response.text
    assert payload["id"] == evaluation_id, payload
    assert [finding["ordinal"] for finding in findings] == [0, 1, 2], findings
    assert [finding["is_blocking"] for finding in findings] == [
        True,
        False,
        False,
    ], findings
    assert payload["finding_count"] == len(findings), payload


@pytest.mark.asyncio
async def test_list_hides_foreign_and_unauthenticated_callers(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The listing is absent to a foreign principal and denied without one."""
    dependencies = build_qa_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        episode = await _seed(dependencies)
        endpoint = f"/v1/episodes/{episode.episode_id}/qa-evaluations"
        cross_principal = await client.get(endpoint, headers=PRINCIPAL_B)
        unauthenticated = await client.get(endpoint)

    envelope = _envelope(cross_principal)
    assert cross_principal.status_code == 404, cross_principal.text
    assert envelope["code"] == "qa_evaluation_not_found", envelope
    assert envelope["details"] == {"episode_id": str(episode.episode_id)}, envelope
    assert unauthenticated.status_code == 401, unauthenticated.text


@pytest.mark.asyncio
async def test_detail_hides_foreign_and_unauthenticated_callers(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The detail route applies its own ownership check, not just the listing."""
    dependencies = build_qa_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        episode = await _seed(dependencies)
        listing = await client.get(
            f"/v1/episodes/{episode.episode_id}/qa-evaluations",
            headers=PRINCIPAL_A,
        )
        evaluation_id = typ.cast("str", _items(listing)[0]["id"])
        endpoint = f"/v1/qa-evaluations/{evaluation_id}"
        cross_principal = await client.get(endpoint, headers=PRINCIPAL_B)
        unauthenticated = await client.get(endpoint)

    envelope = _envelope(cross_principal)
    assert cross_principal.status_code == 404, cross_principal.text
    assert envelope["code"] == "qa_evaluation_not_found", envelope
    assert envelope["details"] == {"evaluation_id": evaluation_id}, envelope
    assert unauthenticated.status_code == 401, unauthenticated.text


@pytest.mark.asyncio
async def test_unknown_evaluation_identifier_is_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A missing evaluation is indistinguishable from one owned elsewhere."""
    dependencies = build_qa_dependencies(session_factory)
    missing_id = uuid.uuid4()
    async with api_async_client(dependencies) as client:
        response = await client.get(
            f"/v1/qa-evaluations/{missing_id}",
            headers=PRINCIPAL_A,
        )

    envelope = _envelope(response)
    assert response.status_code == 404, response.text
    assert envelope["code"] == "qa_evaluation_not_found", envelope
    assert envelope["details"] == {"evaluation_id": str(missing_id)}, envelope


@pytest.mark.asyncio
async def test_successful_anthem_retry_supersedes_the_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A later success replaces the errored artefact and keeps its identifier."""
    dependencies = build_qa_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        episode = await _seed(dependencies)
        await record_anthem_success(dependencies, episode)
        listing = await client.get(
            f"/v1/episodes/{episode.episode_id}/qa-evaluations",
            headers=PRINCIPAL_A,
            params={"evaluator": "anthem"},
        )
        detail = await client.get(
            f"/v1/qa-evaluations/{ANTHEM_EVALUATION_ID}",
            headers=PRINCIPAL_A,
        )

    items = _items(listing)
    detail_payload = typ.cast("dict[str, object]", detail.json())
    assert len(items) == 1, listing.text
    assert items[0]["id"] == str(ANTHEM_EVALUATION_ID), items
    assert items[0]["compliance_status"] == "compliant", items
    assert items[0]["finding_count"] == 0, items
    assert detail_payload["compliance_status"] == "compliant", detail_payload
    assert detail_payload["findings"] == [], detail_payload
