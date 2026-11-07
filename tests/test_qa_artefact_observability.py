"""Observability coverage for the QA-artefact retrieval endpoints.

Each test pins the span a QA route opens, the attributes it carries, and the
route counter the composition root emits for it. Observations arrive through the
dependency seams, so the assertions describe only bounded labels: no request
payload or principal data reaches a span or a metric.
"""

import dataclasses as dc
import typing as typ
import uuid

import pytest

from episodic.observability import RecordingTracer
from tests.fixtures.api import api_async_client
from tests.steps.qa_artefact_retrieval_seed import PRINCIPAL_A
from tests.steps.qa_artefact_retrieval_support import (
    build_qa_dependencies,
    seed_background_evaluations,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.dependencies import ApiDependencies

_REQUEST_TOTAL = "generation_api_request_total"
_REQUEST_LATENCY = "generation_api_request_latency_ms"


class _RecordingMetrics:
    """Capture bounded route observations for assertion."""

    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, str]]] = []
        self.latencies: list[tuple[str, float, dict[str, str]]] = []

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record one bounded counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record one bounded latency observation."""
        self.latencies.append((name, value, dict(labels)))


def _instrumented_dependencies(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[ApiDependencies, RecordingTracer, _RecordingMetrics]:
    """Build QA dependencies carrying a recording tracer and metrics sink."""
    tracer = RecordingTracer()
    metrics = _RecordingMetrics()
    dependencies = dc.replace(
        build_qa_dependencies(session_factory),
        tracer=tracer,
        metrics=metrics,
    )
    return dependencies, tracer, metrics


def _metric_labels(operation: str, outcome: str) -> dict[str, str]:
    """Return the bounded labels an instrumented route emits."""
    return {"operation": operation, "outcome": outcome}


@pytest.mark.asyncio
async def test_list_route_records_rejected_span_and_bounded_metric(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An unusable episode identifier is observable without its raw value."""
    dependencies, tracer, metrics = _instrumented_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        response = await client.get(
            "/v1/episodes/not-a-uuid/qa-evaluations",
            headers=PRINCIPAL_A,
        )

    assert response.status_code == 400, response.text
    assert [span.name for span in tracer.spans] == ["qa_evaluations.list"], tracer.spans
    assert tracer.spans[0].attributes == {
        "operation": "qa_evaluations.list",
        "outcome": "rejected",
        "failure_category": "invalid_input",
    }, tracer.spans
    assert metrics.counters == [
        (_REQUEST_TOTAL, _metric_labels("qa_evaluations.list", "rejected"))
    ], metrics.counters
    assert metrics.latencies[0][0] == _REQUEST_LATENCY, metrics.latencies
    assert metrics.latencies[0][2] == _metric_labels(
        "qa_evaluations.list", "rejected"
    ), metrics.latencies


@pytest.mark.asyncio
async def test_detail_route_records_not_found_span(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An unknown evaluation is a bounded not-found span, not a silent 404."""
    dependencies, tracer, metrics = _instrumented_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        response = await client.get(
            f"/v1/qa-evaluations/{uuid.uuid4()}",
            headers=PRINCIPAL_A,
        )

    assert response.status_code == 404, response.text
    assert [span.name for span in tracer.spans] == ["qa_evaluation.read"], tracer.spans
    assert tracer.spans[0].attributes == {
        "operation": "qa_evaluation.read",
        "outcome": "not_found",
        "failure_category": "evaluation.not_found",
    }, tracer.spans
    assert metrics.counters == [
        (_REQUEST_TOTAL, _metric_labels("qa_evaluation.read", "rejected"))
    ], metrics.counters


@pytest.mark.asyncio
async def test_list_route_records_success_span_with_pagination(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A served page records success and the pagination mode it used.

    The episode is seeded through uninstrumented dependencies so the spans and
    counters under assertion belong to the listing request alone.
    """
    episode = await seed_background_evaluations(build_qa_dependencies(session_factory))
    dependencies, tracer, metrics = _instrumented_dependencies(session_factory)
    async with api_async_client(dependencies) as client:
        response = await client.get(
            f"/v1/episodes/{episode.episode_id}/qa-evaluations",
            headers=PRINCIPAL_A,
        )

    assert response.status_code == 200, response.text
    assert [span.name for span in tracer.spans] == ["qa_evaluations.list"], tracer.spans
    assert tracer.spans[0].attributes == {
        "operation": "qa_evaluations.list",
        "pagination": "offset",
        "outcome": "success",
    }, tracer.spans
    assert metrics.counters == [
        (_REQUEST_TOTAL, _metric_labels("qa_evaluations.list", "success"))
    ], metrics.counters
