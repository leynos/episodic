"""Guest biography binding and source projection tests."""

import asyncio
import typing as typ
from uuid import uuid4

import pytest

from episodic.canonical.domain import ReferenceDocumentKind
from episodic.canonical.reference_documents.resolution import ResolvedBinding
from episodic.generation.guest_bios import (
    GuestBiosEnrichmentRequest,
    GuestBiosGenerator,
    GuestBiosGeneratorConfig,
    GuestBioSource,
    generate_guest_bios_from_reference_bindings,
    project_guest_bio_sources,
)
from tests._guest_bios_helpers import (
    SCRIPT_TEI,
    _FakeLLMPort,
    _reference_binding,
    _reference_document,
    _reference_revision,
    _response,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork


def test_project_guest_bio_sources_filters_guest_profiles() -> None:
    """Project only guest-profile resolved bindings into generator sources."""
    guest_document_id = uuid4()
    guest_revision_id = uuid4()
    style_document_id = uuid4()
    style_revision_id = uuid4()
    resolved = [
        ResolvedBinding(
            binding=_reference_binding(guest_revision_id),
            document=_reference_document(
                document_id=guest_document_id,
                kind=ReferenceDocumentKind.GUEST_PROFILE,
                metadata={"role": "Mathematician"},
            ),
            revision=_reference_revision(
                document_id=guest_document_id,
                revision_id=guest_revision_id,
                content={
                    "display_name": "Ada Lovelace",
                    "profile": "Ada wrote notes on the Analytical Engine.",
                },
            ),
        ),
        ResolvedBinding(
            binding=_reference_binding(style_revision_id),
            document=_reference_document(
                document_id=style_document_id,
                kind=ReferenceDocumentKind.STYLE_GUIDE,
            ),
            revision=_reference_revision(
                document_id=style_document_id,
                revision_id=style_revision_id,
                content={"display_name": "Style Guide", "profile": "Ignore me."},
            ),
        ),
    ]

    sources = project_guest_bio_sources(resolved)

    assert sources == (
        GuestBioSource(
            display_name="Ada Lovelace",
            role="Mathematician",
            reference_document_id=str(guest_document_id),
            reference_document_revision_id=str(guest_revision_id),
            source_content="Ada wrote notes on the Analytical Engine.",
        ),
    )


@pytest.mark.asyncio
async def test_generate_from_reference_bindings_resolves_and_enriches_tei() -> None:
    """Resolve guest-profile bindings and enrich TEI with generated bios."""
    guest_document_id = uuid4()
    guest_revision_id = uuid4()
    series_profile_id = uuid4()
    episode_id = uuid4()
    template_id = uuid4()
    calls: list[dict[str, object]] = []

    async def binding_resolver(
        uow: object,
        **kwargs: object,
    ) -> list[ResolvedBinding]:
        await asyncio.sleep(0)
        calls.append({"uow": uow, **kwargs})
        return [
            ResolvedBinding(
                binding=_reference_binding(guest_revision_id),
                document=_reference_document(
                    document_id=guest_document_id,
                    kind=ReferenceDocumentKind.GUEST_PROFILE,
                ),
                revision=_reference_revision(
                    document_id=guest_document_id,
                    revision_id=guest_revision_id,
                    content={
                        "display_name": "Ada Lovelace",
                        "profile": "Ada wrote notes on the Analytical Engine.",
                    },
                ),
            )
        ]

    llm = _FakeLLMPort(
        response=_response({
            "guests": [
                {
                    "display_name": "Ada Lovelace",
                    "bio": "Ada Lovelace wrote about analytical engines.",
                    "reference_document_revision_id": str(guest_revision_id),
                }
            ]
        }),
        requests=[],
    )
    generator = GuestBiosGenerator(
        llm=llm,
        config=GuestBiosGeneratorConfig(model="vidai-mock"),
    )
    uow = object()

    result = await generate_guest_bios_from_reference_bindings(
        typ.cast("CanonicalUnitOfWork", uow),
        GuestBiosEnrichmentRequest(
            series_profile_id=series_profile_id,
            tei_xml=SCRIPT_TEI,
            template_id=template_id,
            episode_id=episode_id,
        ),
        generator=generator,
        binding_resolver=binding_resolver,
    )

    assert calls == [
        {
            "uow": uow,
            "series_profile_id": series_profile_id,
            "episode_id": episode_id,
            "template_id": template_id,
        }
    ]
    assert result.sources[0].reference_document_revision_id == str(guest_revision_id)
    assert result.generation_result.entries[0].display_name == "Ada Lovelace"
    assert 'type="guest-bios"' in result.tei_xml
    assert "Ada Lovelace wrote about analytical engines." in result.tei_xml


@pytest.mark.asyncio
async def test_generate_from_reference_bindings_skips_llm_without_guest_profiles() -> (
    None
):
    """Return the original TEI when no guest-profile bindings resolve."""

    async def binding_resolver(
        uow: object,
        **kwargs: object,
    ) -> list[ResolvedBinding]:
        await asyncio.sleep(0)
        return []

    llm = _FakeLLMPort(
        response=_response({"guests": []}),
        requests=[],
    )
    generator = GuestBiosGenerator(
        llm=llm,
        config=GuestBiosGeneratorConfig(model="vidai-mock"),
    )

    result = await generate_guest_bios_from_reference_bindings(
        typ.cast("CanonicalUnitOfWork", object()),
        GuestBiosEnrichmentRequest(
            series_profile_id=uuid4(),
            tei_xml=SCRIPT_TEI,
        ),
        generator=generator,
        binding_resolver=binding_resolver,
    )

    assert result.tei_xml == SCRIPT_TEI
    assert result.sources == ()
    assert result.generation_result.entries == ()
    assert not llm.requests
