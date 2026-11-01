"""Shared payloads and helpers for the QA retrieval CLI unit tests.

Both :mod:`tests.test_qa_cli` and :mod:`tests.test_qa_cli_errors` drive the same
CLI through a stubbed transport, so the canned page and the request helpers
live here rather than being copied into each module.
"""

import dataclasses as dc
import typing as typ

import httpx
import pytest

from tests.snapshot_redaction import redact_snapshot_uuids

if typ.TYPE_CHECKING:
    import collections.abc as cabc

EPISODE_ID = "0199a0c2-0000-7000-8000-000000000010"
CLI_ENVIRONMENT_VARIABLES = ("EPISODIC_API_URL", "EPISODIC_API_TOKEN")

_PEDANTE = {
    "id": "0199a0c2-0000-7000-8000-000000000001",
    "episode_id": EPISODE_ID,
    "generation_run_id": "0199a0c2-0000-7000-8000-000000000020",
    "evaluator": "pedante",
    "evaluator_version": "pedante-1.0",
    "artefact_schema_version": 1,
    "compliance_policy_version": 1,
    "compliance_status": "non_compliant",
    "summary": "Three claims were checked.",
    "rubric_score": None,
    "runtime_estimate_seconds": None,
    "finding_count": 3,
    "evaluator_metadata": {},
    "evaluated_at": "2026-10-31T10:00:00+00:00",
}
_CHRONO = {
    **_PEDANTE,
    "id": "0199a0c2-0000-7000-8000-000000000002",
    "evaluator": "chrono",
    "evaluator_version": "chrono-1.0",
    "compliance_status": "not_applicable",
    "summary": "Estimated 412 seconds of speech.",
    "runtime_estimate_seconds": 412,
    "finding_count": 0,
    "evaluated_at": "2026-10-31T10:05:00+00:00",
}
_ANTHEM = {
    **_PEDANTE,
    "id": "0199a0c2-0000-7000-8000-000000000003",
    "evaluator": "anthem",
    "evaluator_version": "anthem-1.0",
    "compliance_status": "errored",
    "summary": "Anthem did not respond before the deadline.",
    "finding_count": 0,
    "evaluated_at": "2026-10-31T10:10:00+00:00",
}
PAGE: dict[str, object] = {
    "items": [_ANTHEM, _CHRONO, _PEDANTE],
    "limit": 20,
    "offset": 0,
    "total": 3,
}
EMPTY_PAGE: dict[str, object] = {
    "items": [],
    "limit": 20,
    "offset": 0,
    "total": 0,
}


@dc.dataclass(slots=True)
class RecordedRequests:
    """Requests the stubbed transport received."""

    seen: list[httpx.Request] = dc.field(default_factory=list)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the CLI from the operator's own API settings."""
    for name in CLI_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def canned(
    payload: object,
    *,
    status: int = 200,
    headers: cabc.Mapping[str, str] | None = None,
) -> tuple[httpx.MockTransport, RecordedRequests]:
    """Return a transport answering every request with one JSON body."""
    recorded = RecordedRequests()

    def handle(request: httpx.Request) -> httpx.Response:
        recorded.seen.append(request)
        return httpx.Response(status, json=payload, headers=headers)

    return httpx.MockTransport(handle), recorded


def list_arguments(*extra: str) -> list[str]:
    """Return the arguments for a listing of the fixture episode."""
    return ["qa", "evaluations", "list", EPISODE_ID, *extra]


def redacted(payload: dict[str, object]) -> dict[str, object]:
    """Return ``payload`` with the incidental UUIDs replaced."""
    return typ.cast("dict[str, object]", redact_snapshot_uuids(payload))
