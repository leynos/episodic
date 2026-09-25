"""Guest biography generation from reference document bindings.

The data contracts, JSON-response parsing helpers, and TEI enrichment helper
live in sibling modules (``guest_bios_models``, ``guest_bios_parsing``, and
``guest_bios_tei`` respectively) to keep this module under the project's
line-count limit; they are re-exported here so callers keep importing from
this module.
"""

import collections.abc as cabc
import dataclasses as dc
import json
import typing as typ

from episodic.canonical.domain import ReferenceDocumentKind
from episodic.canonical.reference_documents.resolution import resolve_bindings
from episodic.generation.guest_bios_models import (
    GuestBioEntry,
    GuestBiosEnrichmentRequest,
    GuestBiosEnrichmentResult,
    GuestBiosGeneratorConfig,
    GuestBioSource,
    GuestBiosResult,
    JsonMapping,
)
from episodic.generation.guest_bios_parsing import (
    GuestBiosResponseFormatError,
    _decode_object,
    _parse_entry,
    _require_list,
    _validate_revision_ids,
)
from episodic.generation.guest_bios_tei import enrich_tei_with_guest_bios
from episodic.llm import (
    LLMPort,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork
    from episodic.canonical.reference_documents.resolution import ResolvedBinding

__all__ = [
    "GuestBioEntry",
    "GuestBioSource",
    "GuestBiosEnrichmentRequest",
    "GuestBiosEnrichmentResult",
    "GuestBiosGenerator",
    "GuestBiosGeneratorConfig",
    "GuestBiosResponseFormatError",
    "GuestBiosResult",
    "enrich_tei_with_guest_bios",
    "generate_guest_bios_from_reference_bindings",
    "project_guest_bio_sources",
]

type BindingResolver = cabc.Callable[
    ...,
    cabc.Awaitable[list[ResolvedBinding]],
]


def _optional_content_string(value: object) -> str | None:
    """Return a stripped string from untrusted reference payload content."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _first_content_string(payload: JsonMapping, *field_names: str) -> str | None:
    """Return the first non-empty string from the given mapping fields."""
    for field_name in field_names:
        if content := _optional_content_string(payload.get(field_name)):
            return content
    return None


def _json_source_content(payload: JsonMapping) -> str:
    """Serialize structured reference content for source-grounded prompts."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def project_guest_bio_sources(
    resolved_bindings: list[ResolvedBinding],
) -> tuple[GuestBioSource, ...]:
    """Project resolved guest-profile bindings into generator source records."""
    sources: list[GuestBioSource] = []
    for resolved in resolved_bindings:
        if resolved.document.kind is not ReferenceDocumentKind.GUEST_PROFILE:
            continue

        revision_content = resolved.revision.content
        document_metadata = resolved.document.metadata
        display_name = _first_content_string(
            revision_content,
            "display_name",
            "name",
            "title",
        ) or _first_content_string(document_metadata, "display_name", "name", "title")
        if display_name is None:
            display_name = str(resolved.document.id)

        role = _first_content_string(revision_content, "role", "occupation")
        if role is None:
            role = _first_content_string(document_metadata, "role", "occupation")

        source_content = _first_content_string(
            revision_content,
            "source_content",
            "profile",
            "bio",
            "biography",
            "summary",
            "content",
            "text",
        )
        if source_content is None:
            source_content = _json_source_content(revision_content)

        sources.append(
            GuestBioSource(
                display_name=display_name,
                role=role,
                reference_document_id=str(resolved.document.id),
                reference_document_revision_id=str(resolved.revision.id),
                source_content=source_content,
            )
        )

    return tuple(sources)


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
