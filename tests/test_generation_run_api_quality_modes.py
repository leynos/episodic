"""REST capability gate for QA-gated generation runs (INV-12).

The accepted set decides whether ``qa_gated`` is processable. The check runs
inside the idempotent work, after the body parser and before the
gated-rationale rule, so the historical 422 stays byte-identical and a
corrected retry can reuse a released key.
"""

import dataclasses as dc
import typing as typ

import httpx
import pytest

from episodic.api import create_app
from episodic.canonical.generation_quality import QaStatus, QualityMode
from tests.fixtures.api import build_api_dependencies
from tests.fixtures.generation_run_api import (
    HeaderPrincipalAuthorization,
    RecordingLauncher,
    create_ready_ingestion_job,
)
from tests.test_generation_run_api import _assert_error_envelope, _ExpectedError

if typ.TYPE_CHECKING:
    from httpx._transports.asgi import _ASGIApp
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.dependencies import ApiDependencies

_HEADERS = {"Authorization": "Bearer principal-a"}
_GATED_ENDPOINT = "/v1/ingestion-jobs/{job}/generation-runs"
_ACCEPTING_MODES = frozenset({QualityMode.DRAFT_WITHOUT_QA, QualityMode.QA_GATED})


def _dependencies(
    session_factory: async_sessionmaker[AsyncSession],
    accepted: frozenset[QualityMode],
) -> ApiDependencies:
    """Build API dependencies advertising the supplied accepted modes."""
    return dc.replace(
        build_api_dependencies(session_factory),
        authorization=HeaderPrincipalAuthorization(),
        launcher=RecordingLauncher(),
        accepted_quality_modes=accepted,
    )


def _client(dependencies: ApiDependencies) -> httpx.AsyncClient:
    """Build an HTTP client bound to the dependencies' ASGI app."""
    transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", create_app(dependencies)))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _gated_payload(**overrides: object) -> dict[str, object]:
    """Return a QA-gated request body, optionally overridden."""
    payload: dict[str, object] = {"quality_mode": "qa_gated", "actor": "editor"}
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_accepted_gated_request_is_created_pending(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An accepted gated request returns 202 with pending QA and no rationale."""
    async with _client(_dependencies(session_factory, _ACCEPTING_MODES)) as client:
        job = await create_ready_ingestion_job(client, _HEADERS)
        response = await client.post(
            _GATED_ENDPOINT.format(job=job),
            headers={**_HEADERS, "Idempotency-Key": "gated-ok"},
            json=_gated_payload(),
        )

    assert response.status_code == 202, response.text
    location = response.headers["Location"]
    assert location.startswith("/v1/generation-runs/"), location
    body = response.json()
    assert body["quality_mode"] == QualityMode.QA_GATED.value, body
    assert body["qa_status"] == QaStatus.PENDING.value, body
    assert body["skip_qa_rationale"] is None, body


@pytest.mark.asyncio
async def test_accepted_gated_request_with_rationale_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A rationale on an accepted gated request is the named 400."""
    async with _client(_dependencies(session_factory, _ACCEPTING_MODES)) as client:
        job = await create_ready_ingestion_job(client, _HEADERS)
        response = await client.post(
            _GATED_ENDPOINT.format(job=job),
            headers={**_HEADERS, "Idempotency-Key": "gated-rationale"},
            json=_gated_payload(skip_qa_rationale="Not allowed here."),
        )

    _assert_error_envelope(
        response,
        _ExpectedError(
            status=400,
            code="validation_error",
            message=("skip_qa_rationale is not accepted with quality_mode qa_gated."),
            details={
                "field": "skip_qa_rationale",
                "constraint": "exclusive_with_quality_mode",
                "quality_mode": "qa_gated",
            },
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("with_rationale", [True, False])
async def test_unaccepted_gated_request_keeps_the_historical_422(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    with_rationale: bool,
) -> None:
    """Where the mode is unaccepted, the unchanged 422 wins either way."""
    overrides = {"skip_qa_rationale": "Ignored."} if with_rationale else {}
    async with _client(
        _dependencies(
            session_factory,
            frozenset({QualityMode.DRAFT_WITHOUT_QA}),
        )
    ) as client:
        job = await create_ready_ingestion_job(client, _HEADERS)
        response = await client.post(
            _GATED_ENDPOINT.format(job=job),
            headers={**_HEADERS, "Idempotency-Key": f"gated-422-{with_rationale}"},
            json=_gated_payload(**overrides),
        )

    _assert_error_envelope(
        response,
        _ExpectedError(
            status=422,
            code="quality_mode_unsupported",
            message="Unsupported quality_mode: qa_gated.",
            details={"quality_mode": "qa_gated"},
        ),
    )


@pytest.mark.asyncio
async def test_rejected_work_releases_the_idempotency_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A 400 inside work releases the key, so a corrected retry succeeds."""
    async with _client(_dependencies(session_factory, _ACCEPTING_MODES)) as client:
        job = await create_ready_ingestion_job(client, _HEADERS)
        endpoint = _GATED_ENDPOINT.format(job=job)
        headers = {**_HEADERS, "Idempotency-Key": "gated-retry"}
        rejected = await client.post(
            endpoint,
            headers=headers,
            json=_gated_payload(skip_qa_rationale="First attempt."),
        )
        corrected = await client.post(endpoint, headers=headers, json=_gated_payload())

    assert rejected.status_code == 400, rejected.text
    assert corrected.status_code == 202, corrected.text


@pytest.mark.asyncio
async def test_replay_after_capability_withdrawal_returns_the_stored_202(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A stored accepted response replays even after the deployment withdraws it."""
    body = _gated_payload()
    headers = {**_HEADERS, "Idempotency-Key": "gated-replay"}
    async with _client(_dependencies(session_factory, _ACCEPTING_MODES)) as client:
        job = await create_ready_ingestion_job(client, _HEADERS)
        endpoint = _GATED_ENDPOINT.format(job=job)
        first = await client.post(endpoint, headers=headers, json=body)

    async with _client(
        _dependencies(session_factory, frozenset({QualityMode.DRAFT_WITHOUT_QA}))
    ) as client:
        replay = await client.post(
            _GATED_ENDPOINT.format(job=job),
            headers=headers,
            json=body,
        )

    assert first.status_code == 202, first.text
    assert replay.status_code == 202, replay.text
    assert replay.json()["id"] == first.json()["id"], "replay must return the first run"


@pytest.mark.asyncio
async def test_unknown_mode_stays_a_400_enum_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An unknown quality mode is rejected by the parser, before work."""
    async with _client(_dependencies(session_factory, _ACCEPTING_MODES)) as client:
        job = await create_ready_ingestion_job(client, _HEADERS)
        response = await client.post(
            _GATED_ENDPOINT.format(job=job),
            headers={**_HEADERS, "Idempotency-Key": "unknown-mode"},
            json={"quality_mode": "advisory", "skip_qa_rationale": "x"},
        )

    _assert_error_envelope(
        response,
        _ExpectedError(
            status=400,
            code="validation_error",
            message="Invalid quality_mode: 'advisory'.",
            details={"field": "quality_mode", "constraint": "enum"},
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {**_HEADERS, "Idempotency-Key": "gated-budget-precedence"},
        _HEADERS,
    ],
    ids=["with-key", "without-key"],
)
async def test_unaccepted_mode_outranks_other_validation(
    session_factory: async_sessionmaker[AsyncSession],
    headers: dict[str, str],
) -> None:
    """An unaccepted mode keeps its 422 with or without an idempotency key."""
    async with _client(
        _dependencies(session_factory, frozenset({QualityMode.DRAFT_WITHOUT_QA}))
    ) as client:
        job = await create_ready_ingestion_job(client, _HEADERS)
        response = await client.post(
            _GATED_ENDPOINT.format(job=job),
            headers=headers,
            json=_gated_payload(budget_hints=["not", "an", "object"]),
        )

    _assert_error_envelope(
        response,
        _ExpectedError(
            status=422,
            code="quality_mode_unsupported",
            message="Unsupported quality_mode: qa_gated.",
            details={"quality_mode": "qa_gated"},
        ),
    )


@pytest.mark.asyncio
async def test_no_qa_budget_error_outranks_the_missing_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A malformed budget hint is reported before the missing-key error."""
    async with _client(
        _dependencies(session_factory, frozenset({QualityMode.DRAFT_WITHOUT_QA}))
    ) as client:
        job = await create_ready_ingestion_job(client, _HEADERS)
        response = await client.post(
            _GATED_ENDPOINT.format(job=job),
            headers=_HEADERS,
            json={
                "quality_mode": "draft_without_qa",
                "skip_qa_rationale": "Vertical slice.",
                "budget_hints": ["not", "an", "object"],
            },
        )

    _assert_error_envelope(
        response,
        _ExpectedError(
            status=400,
            code="validation_error",
            message="budget_hints must be a JSON object.",
            details={"field": "budget_hints", "constraint": "object"},
        ),
    )


@pytest.mark.asyncio
async def test_missing_key_with_an_accepted_mode_is_reported(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An acceptable request without a key still reports the missing header."""
    async with _client(_dependencies(session_factory, _ACCEPTING_MODES)) as client:
        job = await create_ready_ingestion_job(client, _HEADERS)
        response = await client.post(
            _GATED_ENDPOINT.format(job=job),
            headers=_HEADERS,
            json=_gated_payload(),
        )

    _assert_error_envelope(
        response,
        _ExpectedError(
            status=400,
            code="validation_error",
            message="Idempotency-Key header is required.",
            details={"field": "Idempotency-Key", "constraint": "required"},
        ),
    )
