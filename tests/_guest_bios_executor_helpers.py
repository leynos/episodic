"""Shared helpers for guest-bios executor tests."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ
from uuid import UUID, uuid4

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)
from episodic.canonical.reference_documents.resolution import ResolvedBinding
from episodic.llm import LLMError
from episodic.orchestration import ActionKind, ModelTier, PlannedAction

if typ.TYPE_CHECKING:
    from episodic.generation import GuestBioSource, GuestBiosResult

SCRIPT_TEI = """\
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <title>Guest Bio Executor Fixture</title>
    </fileDesc>
  </teiHeader>
  <text>
    <body>
      <p>Welcome to the episode.</p>
    </body>
  </text>
</TEI>
"""


def _reference_document(document_id: UUID) -> ReferenceDocument:
    return ReferenceDocument(
        id=document_id,
        owner_series_profile_id=uuid4(),
        kind=ReferenceDocumentKind.GUEST_PROFILE,
        lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
        metadata={},
        created_at=dt.datetime.now(dt.UTC),
        updated_at=dt.datetime.now(dt.UTC),
    )


def _reference_revision(
    *,
    document_id: UUID,
    revision_id: UUID,
) -> ReferenceDocumentRevision:
    return ReferenceDocumentRevision(
        id=revision_id,
        reference_document_id=document_id,
        content={
            "display_name": "Ada Lovelace",
            "profile": "Ada wrote notes on the Analytical Engine.",
        },
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


def _guest_bios_action() -> PlannedAction:
    return PlannedAction(
        action_id="guest-bios-1",
        action_kind=ActionKind.GENERATE_GUEST_BIOS,
        rationale="Guest profiles are bound to this episode.",
        model_tier=ModelTier.EXECUTION,
        required_inputs=("script_tei_xml", "series_profile_id"),
    )


def _resolved_guest_binding(
    *,
    document_id: UUID,
    revision_id: UUID,
) -> ResolvedBinding:
    """Build one resolved guest-profile binding for executor tests."""
    return ResolvedBinding(
        binding=_reference_binding(revision_id),
        document=_reference_document(document_id),
        revision=_reference_revision(
            document_id=document_id,
            revision_id=revision_id,
        ),
    )


async def _single_guest_binding_resolver(
    uow: object,
    **kwargs: object,
) -> list[ResolvedBinding]:
    """Return one guest-profile binding after one async scheduling point."""
    del uow, kwargs
    await asyncio.sleep(0)
    return [
        _resolved_guest_binding(
            document_id=uuid4(),
            revision_id=uuid4(),
        )
    ]


class _RaisingGuestBiosGenerator:
    """Raise a configured exception from the guest-bios generator boundary."""

    def __init__(
        self,
        error: BaseException,
        *,
        expected_template_structure: dict[str, object] | None = None,
    ) -> None:
        self._error = error
        self._expected_template_structure = expected_template_structure

    async def generate(
        self,
        script_tei_xml: str,
        sources: tuple[GuestBioSource, ...],
        *,
        template_structure: dict[str, object] | None = None,
    ) -> GuestBiosResult:
        """Raise the configured error after validating call context."""
        if script_tei_xml != SCRIPT_TEI.strip():
            raise AssertionError
        if not sources:
            raise AssertionError
        if template_structure != self._expected_template_structure:
            raise AssertionError
        raise self._error


class _CustomLLMError(LLMError):
    """LLM error subclass without a dedicated log event mapping."""
