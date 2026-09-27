"""Guest-bios data contracts and their field validators.

This module holds the value objects exchanged by the guest biography
generator (``GuestBioSource``, ``GuestBioEntry``, ``GuestBiosResult``,
``GuestBiosEnrichmentRequest``, ``GuestBiosEnrichmentResult``, and
``GuestBiosGeneratorConfig``) along with the small validation helpers their
``__post_init__`` hooks call. It is split out of
:mod:`episodic.generation.guest_bios` so that module stays under the
project's line-count limit; import the public names from
:mod:`episodic.generation.guest_bios` rather than from here.
"""

import dataclasses as dc
import typing as typ

from episodic.llm import (
    LLMProviderOperation,
    LLMTokenBudget,
    LLMUsage,
    ProviderCallUsage,
)

if typ.TYPE_CHECKING:
    import uuid

type JsonMapping = dict[str, object]

_DEFAULT_SYSTEM_PROMPT = (
    "The assistant acts as a podcast guest biography writer. Given TEI P5 "
    "episode context and pinned guest profile reference documents, summarize "
    "only facts present in the supplied profiles. Return JSON only with key "
    '"guests". Each guest must include "display_name", "bio", and '
    '"reference_document_revision_id". Optional fields: "role" and '
    '"tei_locator".'
)


def _ensure_non_empty_fields(instance: object, *field_names: str) -> None:
    """Reject blank or whitespace-only string fields on a dataclass instance."""
    for field_name in field_names:
        value = getattr(instance, field_name)
        if not isinstance(value, str) or not value.strip():
            msg = f"{field_name} must be non-empty."
            raise ValueError(msg)


def _normalize_optional_string(value: str | None) -> str | None:
    """Normalize blank optional strings to None."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


@dc.dataclass(frozen=True, slots=True)
class GuestBioSource:
    """Pinned guest profile input used to generate one biography."""

    display_name: str
    reference_document_id: str
    reference_document_revision_id: str
    source_content: str
    role: str | None = None

    def __post_init__(self) -> None:
        """Reject blank source identifiers and source text."""
        _ensure_non_empty_fields(
            self,
            "display_name",
            "reference_document_id",
            "reference_document_revision_id",
            "source_content",
        )
        object.__setattr__(self, "role", _normalize_optional_string(self.role))


@dc.dataclass(frozen=True, slots=True)
class GuestBioEntry:
    """A generated guest biography tied to one pinned reference revision."""

    display_name: str
    bio: str
    reference_document_revision_id: str
    role: str | None = None
    tei_locator: str | None = None

    def __post_init__(self) -> None:
        """Reject blank required fields and normalize optional metadata."""
        _ensure_non_empty_fields(
            self,
            "display_name",
            "bio",
            "reference_document_revision_id",
        )
        object.__setattr__(self, "role", _normalize_optional_string(self.role))
        object.__setattr__(
            self,
            "tei_locator",
            _normalize_optional_string(self.tei_locator),
        )

    def get_external_corresp_id(self) -> str:
        """Return the external TEI correspondence identifier for this source."""
        return (
            "urn:episodic:reference-document-revision:"
            f"{self.reference_document_revision_id}"
        )


@dc.dataclass(frozen=True, slots=True)
class GuestBiosResult:
    """Guest-bio generation result with entries and provider metadata."""

    entries: tuple[GuestBioEntry, ...]
    usage: LLMUsage
    model: str = ""
    provider_response_id: str = ""
    finish_reason: str | None = None
    provider_call_usage: ProviderCallUsage | None = None


@dc.dataclass(frozen=True, slots=True)
class GuestBiosEnrichmentResult:
    """Guest-bio enrichment output for a resolved binding context."""

    tei_xml: str
    generation_result: GuestBiosResult
    sources: tuple[GuestBioSource, ...]


@dc.dataclass(frozen=True, slots=True)
class GuestBiosEnrichmentRequest:
    """Binding-resolution and generation context for one guest-bios enrichment call."""

    series_profile_id: uuid.UUID
    tei_xml: str
    template_id: uuid.UUID | None = None
    episode_id: uuid.UUID | None = None
    template_structure: JsonMapping | None = None


@dc.dataclass(frozen=True, slots=True)
class GuestBiosGeneratorConfig:
    """Configuration for the guest biography generator service."""

    model: str
    provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )
    token_budget: LLMTokenBudget | None = None
    system_prompt: str = _DEFAULT_SYSTEM_PROMPT
