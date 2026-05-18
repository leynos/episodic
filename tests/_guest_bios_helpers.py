"""Shared helpers for guest biography generation tests."""

import dataclasses as dc
import datetime as dt
import json
import typing as typ
from uuid import UUID, uuid4

import tei_rapporteur as tei

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)
from episodic.llm import LLMRequest, LLMResponse, LLMUsage


@dc.dataclass(slots=True)
class _FakeLLMPort:
    """Capture one guest-bios request and return a canned response."""

    response: LLMResponse
    requests: list[LLMRequest]

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return the canned response and capture the request."""
        self.requests.append(request)
        return self.response


SCRIPT_TEI = """\
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <title>Guest Bio Fixture</title>
    </fileDesc>
  </teiHeader>
  <text>
    <body>
      <p xml:id="intro">Welcome to the episode.</p>
    </body>
  </text>
</TEI>
"""


def _usage() -> LLMUsage:
    return LLMUsage(input_tokens=10, output_tokens=20, total_tokens=30)


def _response(payload: object) -> LLMResponse:
    return LLMResponse(
        text=json.dumps(payload),
        model="vidai-mock",
        provider_response_id="resp-guest-bios",
        finish_reason="stop",
        usage=_usage(),
    )


def _tei_payload(xml: str) -> dict[str, object]:
    document = tei.parse_xml(xml)
    return typ.cast("dict[str, object]", tei.to_dict(document))


def _body_blocks(xml: str) -> list[object]:
    payload = _tei_payload(xml)
    text = typ.cast("dict[str, object]", payload["text"])
    body = typ.cast("dict[str, object]", text["body"])
    return typ.cast("list[object]", body["blocks"])


def _reference_document(
    *,
    document_id: UUID,
    kind: ReferenceDocumentKind,
    metadata: dict[str, object] | None = None,
) -> ReferenceDocument:
    return ReferenceDocument(
        id=document_id,
        owner_series_profile_id=uuid4(),
        kind=kind,
        lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
        metadata=metadata or {},
        created_at=dt.datetime.now(dt.UTC),
        updated_at=dt.datetime.now(dt.UTC),
    )


def _reference_revision(
    *,
    document_id: UUID,
    revision_id: UUID,
    content: dict[str, object],
) -> ReferenceDocumentRevision:
    return ReferenceDocumentRevision(
        id=revision_id,
        reference_document_id=document_id,
        content=content,
        content_hash="hash",
        author=None,
        change_note=None,
        created_at=dt.datetime.now(dt.UTC),
    )


def _reference_binding(revision_id: UUID) -> ReferenceBinding:
    return ReferenceBinding(
        id=uuid4(),
        reference_document_revision_id=revision_id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=uuid4(),
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=dt.datetime.now(dt.UTC),
    )
