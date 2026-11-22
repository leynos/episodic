"""Request-error precedence for generation-run creation (INV-12).

These cases pin the pre-4.4.1 ordering: request-shape and capability errors
are reported before a reused idempotency key can turn them into a conflict,
and before a missing-launcher 503.
"""

import dataclasses as dc
import typing as typ

import pytest

from episodic.canonical.generation_quality import QualityMode
from tests.fixtures.generation_run_api import create_ready_ingestion_job
from tests.test_generation_run_api import _assert_error_envelope, _ExpectedError
from tests.test_generation_run_api_quality_modes import (
    _GATED_ENDPOINT,
    _HEADERS,
    _client,
    _dependencies,
    _gated_payload,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dc.dataclass(frozen=True, slots=True)
class _RequestCase:
    """One request-error precedence case."""

    headers: dict[str, str]
    payload: dict[str, object]
    expected: _ExpectedError


_REQUEST_CASES: dict[str, _RequestCase] = {
    "unaccepted-mode-without-launcher": _RequestCase(
        headers=_HEADERS,
        payload=_gated_payload(),
        expected=_ExpectedError(
            status=422,
            code="quality_mode_unsupported",
            message="Unsupported quality_mode: qa_gated.",
            details={"quality_mode": "qa_gated"},
        ),
    ),
    "malformed-budget-without-launcher": _RequestCase(
        headers=_HEADERS,
        payload={
            "quality_mode": "draft_without_qa",
            "skip_qa_rationale": "Vertical slice.",
            "budget_hints": ["not", "an", "object"],
        },
        expected=_ExpectedError(
            status=400,
            code="validation_error",
            message="budget_hints must be a JSON object.",
            details={"field": "budget_hints", "constraint": "object"},
        ),
    ),
    "keyed-unaccepted-mode-without-launcher": _RequestCase(
        headers={**_HEADERS, "Idempotency-Key": "no-launcher-precedence"},
        payload=_gated_payload(),
        expected=_ExpectedError(
            status=422,
            code="quality_mode_unsupported",
            message="Unsupported quality_mode: qa_gated.",
            details={"quality_mode": "qa_gated"},
        ),
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    _REQUEST_CASES.values(),
    ids=tuple(_REQUEST_CASES),
)
async def test_request_errors_outrank_a_missing_launcher(
    session_factory: async_sessionmaker[AsyncSession],
    case: _RequestCase,
) -> None:
    """A request error is reported before the missing-launcher 503."""
    dependencies = dc.replace(
        _dependencies(session_factory, frozenset({QualityMode.DRAFT_WITHOUT_QA})),
        launcher=None,
    )
    async with _client(dependencies) as client:
        job = await create_ready_ingestion_job(client, _HEADERS)
        response = await client.post(
            _GATED_ENDPOINT.format(job=job),
            headers=case.headers,
            json=case.payload,
        )

    _assert_error_envelope(response, case.expected)


@pytest.mark.asyncio
async def test_reused_key_still_reports_the_body_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A reused key does not pre-empt a malformed-body error."""
    headers = {**_HEADERS, "Idempotency-Key": "reused-malformed-budget"}
    async with _client(
        _dependencies(session_factory, frozenset({QualityMode.DRAFT_WITHOUT_QA}))
    ) as client:
        job = await create_ready_ingestion_job(client, _HEADERS)
        endpoint = _GATED_ENDPOINT.format(job=job)
        first = await client.post(
            endpoint,
            headers=headers,
            json={
                "quality_mode": "draft_without_qa",
                "skip_qa_rationale": "First attempt.",
            },
        )
        second = await client.post(
            endpoint,
            headers=headers,
            json={
                "quality_mode": "draft_without_qa",
                "skip_qa_rationale": "Second attempt.",
                "budget_hints": ["not", "an", "object"],
            },
        )

    assert first.status_code == 202, first.text
    _assert_error_envelope(
        second,
        _ExpectedError(
            status=400,
            code="validation_error",
            message="budget_hints must be a JSON object.",
            details={"field": "budget_hints", "constraint": "object"},
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_body", [False, True], ids=["replay", "conflict"])
async def test_no_qa_missing_launcher_outranks_idempotency(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    changed_body: bool,
) -> None:
    """A removed launcher is a 503 before replay or conflict, as in the base."""
    headers = {**_HEADERS, "Idempotency-Key": "launcher-removed"}
    body: dict[str, object] = {
        "quality_mode": "draft_without_qa",
        "skip_qa_rationale": "First attempt.",
    }
    async with _client(
        _dependencies(session_factory, frozenset({QualityMode.DRAFT_WITHOUT_QA}))
    ) as client:
        job = await create_ready_ingestion_job(client, _HEADERS)
        endpoint = _GATED_ENDPOINT.format(job=job)
        first = await client.post(endpoint, headers=headers, json=body)
    assert first.status_code == 202, first.text

    without_launcher = dc.replace(
        _dependencies(session_factory, frozenset({QualityMode.DRAFT_WITHOUT_QA})),
        launcher=None,
    )
    if changed_body:
        body = {**body, "skip_qa_rationale": "Second attempt."}
    async with _client(without_launcher) as client:
        response = await client.post(
            _GATED_ENDPOINT.format(job=job),
            headers=headers,
            json=body,
        )

    _assert_error_envelope(
        response,
        _ExpectedError(
            status=503,
            code="service_unavailable",
            message="Generation launcher is not configured.",
            details={},
        ),
    )
