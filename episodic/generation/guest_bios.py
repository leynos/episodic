"""Guest biography generation from reference document bindings."""

import collections.abc as cabc
import dataclasses as dc
import json
import typing as typ

from episodic.canonical.reference_documents.resolution import resolve_bindings
from episodic.llm import (
    LLMPort,
    LLMProviderOperation,
    LLMRequest,
    LLMResponse,
    LLMTokenBudget,
    LLMUsage,
    ProviderCallUsage,
)

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.ports import CanonicalUnitOfWork
    from episodic.canonical.reference_documents.resolution import ResolvedBinding

type JsonMapping = dict[str, object]
type BindingResolver = cabc.Callable[
    ...,
    cabc.Awaitable[list[ResolvedBinding]],
]

_DEFAULT_SYSTEM_PROMPT = (
    "The assistant acts as a podcast guest biography writer. Given TEI P5 "
    "episode context and pinned guest profile reference documents, summarize "
    "only facts present in the supplied profiles. Return JSON only with key "
    '"guests". Each guest must include "display_name", "bio", and '
    '"reference_document_revision_id". Optional fields: "role" and '
    '"tei_locator".'
)


class GuestBiosResponseFormatError(ValueError):
    """Raised when the LLM response cannot be parsed into guest biographies."""


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


def _decode_object(value: object, field_name: str) -> dict[str, object]:
    """Decode a JSON value as an object or raise a format error."""
    if not isinstance(value, dict):
        msg = f"{field_name} must be an object."
        raise GuestBiosResponseFormatError(msg)
    return typ.cast("dict[str, object]", value)


def _require_non_empty_string(value: object, field_name: str) -> str:
    """Require a non-empty string from an LLM payload."""
    if not isinstance(value, str) or not value.strip():
        msg = f"{field_name} must be a non-empty string."
        raise GuestBiosResponseFormatError(msg)
    return value


def _require_optional_string(value: object, field_name: str) -> str | None:
    """Return an optional string from an LLM payload."""
    if value is not None and not isinstance(value, str):
        msg = f"{field_name} must be a string or null."
        raise GuestBiosResponseFormatError(msg)
    return value if isinstance(value, str) else None


def _require_list(value: object, field_name: str) -> list[object]:
    """Require a list from an LLM payload."""
    if not isinstance(value, list):
        msg = f"{field_name} must be a list."
        raise GuestBiosResponseFormatError(msg)
    return typ.cast("list[object]", value)


def _parse_entry(raw: dict[str, object]) -> GuestBioEntry:
    """Parse one guest-bio entry from a strict JSON object."""
    display_name = _require_non_empty_string(raw.get("display_name"), "display_name")
    bio = _require_non_empty_string(raw.get("bio"), "bio")
    revision_id = _require_non_empty_string(
        raw.get("reference_document_revision_id"),
        "reference_document_revision_id",
    )
    role = _require_optional_string(raw.get("role"), "role")
    tei_locator = _require_optional_string(raw.get("tei_locator"), "tei_locator")
    try:
        return GuestBioEntry(
            display_name=display_name,
            bio=bio,
            reference_document_revision_id=revision_id,
            role=role,
            tei_locator=tei_locator,
        )
    except ValueError as exc:
        raise GuestBiosResponseFormatError(str(exc)) from exc


def _validate_revision_ids(
    entries: tuple[GuestBioEntry, ...],
    expected_revision_ids: tuple[str, ...],
) -> None:
    """Reject invented, duplicate, or missing guest profile revisions."""
    expected = set(expected_revision_ids)
    seen: set[str] = set()
    for entry in entries:
        revision_id = entry.reference_document_revision_id
        if revision_id not in expected:
            msg = f"unknown revision identifier: {revision_id}"
            raise GuestBiosResponseFormatError(msg)
        if revision_id in seen:
            msg = f"duplicate revision identifier: {revision_id}"
            raise GuestBiosResponseFormatError(msg)
        seen.add(revision_id)
    missing = expected.difference(seen)
    if missing:
        missing_list = ", ".join(sorted(missing))
        msg = f"missing revision identifier: {missing_list}"
        raise GuestBiosResponseFormatError(msg)


@dc.dataclass(slots=True)
class GuestBiosGenerator:
    """Guest biography generator service backed by an LLM."""

    llm: LLMPort
    config: GuestBiosGeneratorConfig

    @staticmethod
    def build_prompt(
        script_tei_xml: str,
        sources: tuple[GuestBioSource, ...],
        *,
        template_structure: JsonMapping | None = None,
    ) -> str:
        """Build a source-grounded JSON prompt for guest biography generation."""
        prompt_payload: JsonMapping = {
            "script_tei_xml": script_tei_xml,
            "guest_profiles": [
                {
                    "display_name": source.display_name,
                    "role": source.role,
                    "reference_document_id": source.reference_document_id,
                    "reference_document_revision_id": (
                        source.reference_document_revision_id
                    ),
                    "source_content": source.source_content,
                }
                for source in sources
            ],
        }
        if template_structure is not None:
            prompt_payload["template_structure"] = template_structure
        return json.dumps(prompt_payload, indent=2)

    @staticmethod
    def result_from_response(
        response: LLMResponse,
        *,
        expected_revision_ids: tuple[str, ...],
    ) -> GuestBiosResult:
        """Parse an LLM response into a strict guest-bios result."""
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError as exc:
            msg = "LLM response is not valid JSON."
            raise GuestBiosResponseFormatError(msg) from exc

        payload_dict = _decode_object(payload, "response")
        guests_raw = _require_list(payload_dict.get("guests"), "guests")
        entries = tuple(_parse_entry(_decode_object(e, "guest")) for e in guests_raw)
        _validate_revision_ids(entries, expected_revision_ids)
        return GuestBiosResult(
            entries=entries,
            usage=response.usage,
            model=response.model,
            provider_response_id=response.provider_response_id,
            finish_reason=response.finish_reason,
            provider_call_usage=response.provider_call_usage,
        )

    async def generate(
        self,
        script_tei_xml: str,
        sources: tuple[GuestBioSource, ...],
        *,
        template_structure: JsonMapping | None = None,
    ) -> GuestBiosResult:
        """Generate guest biographies for the supplied pinned profile sources."""
        prompt = self.build_prompt(
            script_tei_xml,
            sources,
            template_structure=template_structure,
        )
        request = LLMRequest(
            model=self.config.model,
            prompt=prompt,
            system_prompt=self.config.system_prompt,
            provider_operation=self.config.provider_operation,
            token_budget=self.config.token_budget,
        )
        response = await self.llm.generate(request)
        return self.result_from_response(
            response,
            expected_revision_ids=tuple(
                source.reference_document_revision_id for source in sources
            ),
        )


async def generate_guest_bios_from_reference_bindings(
    uow: CanonicalUnitOfWork,
    request: GuestBiosEnrichmentRequest,
    *,
    generator: GuestBiosGenerator,
    binding_resolver: BindingResolver = resolve_bindings,
) -> GuestBiosEnrichmentResult:
    """Resolve guest profile bindings, generate bios, and enrich TEI."""
    from episodic.generation.guest_bios_sources import project_guest_bio_sources

    resolved_bindings = await binding_resolver(
        uow,
        series_profile_id=request.series_profile_id,
        template_id=request.template_id,
        episode_id=request.episode_id,
    )
    sources = project_guest_bio_sources(resolved_bindings)
    if not sources:
        return GuestBiosEnrichmentResult(
            tei_xml=request.tei_xml,
            generation_result=GuestBiosResult(
                entries=(),
                usage=LLMUsage(input_tokens=0, output_tokens=0, total_tokens=0),
            ),
            sources=(),
        )

    result = await generator.generate(
        request.tei_xml,
        sources,
        template_structure=request.template_structure,
    )
    return GuestBiosEnrichmentResult(
        tei_xml=enrich_tei_with_guest_bios(request.tei_xml, result),
        generation_result=result,
        sources=sources,
    )


def enrich_tei_with_guest_bios(tei_xml: str, result: GuestBiosResult) -> str:
    """Insert guest biographies into a TEI document body.

    Returns
    -------
    str
        Enriched TEI XML, or the original document for an empty result.
    """
    from episodic.generation.guest_bios_tei import enrich_tei_with_guest_bios as enrich

    return enrich(tei_xml, result)


def project_guest_bio_sources(
    resolved_bindings: list[ResolvedBinding],
) -> tuple[GuestBioSource, ...]:
    """Project resolved guest-profile bindings into immutable prompt sources."""
    from episodic.generation.guest_bios_sources import (
        project_guest_bio_sources as project,
    )

    return project(resolved_bindings)
