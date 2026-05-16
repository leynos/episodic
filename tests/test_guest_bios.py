"""Guest biography generation and TEI enrichment tests."""

# pylint: disable=too-many-lines

import asyncio
import dataclasses as dc
import datetime as dt
import json
import typing as typ
from uuid import UUID, uuid4

import pytest
import tei_rapporteur as tei

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)
from episodic.canonical.reference_documents.resolution import ResolvedBinding
from episodic.generation.guest_bios import (
    GuestBioEntry,
    GuestBiosGenerator,
    GuestBiosGeneratorConfig,
    GuestBioSource,
    GuestBiosResponseFormatError,
    GuestBiosResult,
    enrich_tei_with_guest_bios,
    generate_guest_bios_from_reference_bindings,
    project_guest_bio_sources,
)
from episodic.llm import LLMRequest, LLMResponse, LLMUsage

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork


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


def test_result_from_response_rejects_unknown_revision_identifier() -> None:
    """Reject LLM output that invents an unrequested source revision."""
    response = _response({
        "guests": [
            {
                "display_name": "Ada Lovelace",
                "bio": "Ada Lovelace writes about analytical engines.",
                "reference_document_revision_id": "rev-unknown",
            }
        ]
    })

    with pytest.raises(GuestBiosResponseFormatError, match="unknown revision"):
        GuestBiosGenerator.result_from_response(
            response,
            expected_revision_ids=("rev-ada",),
        )


def test_result_from_response_rejects_duplicate_revision_identifier() -> None:
    """Reject LLM output that emits two biographies for one source revision."""
    response = _response({
        "guests": [
            {
                "display_name": "Ada Lovelace",
                "bio": "Ada Lovelace writes about analytical engines.",
                "reference_document_revision_id": "rev-ada",
            },
            {
                "display_name": "Ada Lovelace",
                "bio": "Ada Lovelace studies computing history.",
                "reference_document_revision_id": "rev-ada",
            },
        ]
    })

    with pytest.raises(GuestBiosResponseFormatError, match="duplicate revision"):
        GuestBiosGenerator.result_from_response(
            response,
            expected_revision_ids=("rev-ada",),
        )


def test_result_from_response_rejects_missing_revision_identifier() -> None:
    """Reject LLM output that omits an expected source revision."""
    response = _response({
        "guests": [
            {
                "display_name": "Ada Lovelace",
                "bio": "Ada Lovelace writes about analytical engines.",
                "reference_document_revision_id": "rev-ada",
            }
        ]
    })

    with pytest.raises(GuestBiosResponseFormatError, match="missing revision"):
        GuestBiosGenerator.result_from_response(
            response,
            expected_revision_ids=("rev-ada", "rev-grace"),
        )


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


def test_build_prompt_includes_guest_profile_sources() -> None:
    """Include pinned profile content and identifiers in the LLM prompt."""
    source = GuestBioSource(
        display_name="Ada Lovelace",
        role="Mathematician",
        reference_document_id="doc-ada",
        reference_document_revision_id="rev-ada",
        source_content="Ada wrote notes on the Analytical Engine.",
    )

    prompt = GuestBiosGenerator.build_prompt(
        SCRIPT_TEI,
        (source,),
        template_structure={"segments": ["intro"]},
    )
    payload = json.loads(prompt)

    assert payload["script_tei_xml"] == SCRIPT_TEI
    assert payload["template_structure"] == {"segments": ["intro"]}
    assert payload["guest_profiles"] == [
        {
            "display_name": "Ada Lovelace",
            "role": "Mathematician",
            "reference_document_id": "doc-ada",
            "reference_document_revision_id": "rev-ada",
            "source_content": "Ada wrote notes on the Analytical Engine.",
        }
    ]


@pytest.mark.asyncio
async def test_generate_calls_llm_and_returns_guest_bios_result() -> None:
    """Call the LLM port and parse the response against expected revisions."""
    llm = _FakeLLMPort(
        response=_response({
            "guests": [
                {
                    "display_name": "Ada Lovelace",
                    "bio": "Ada Lovelace wrote about analytical engines.",
                    "reference_document_revision_id": "rev-ada",
                }
            ]
        }),
        requests=[],
    )
    generator = GuestBiosGenerator(
        llm=llm,
        config=GuestBiosGeneratorConfig(model="vidai-mock"),
    )
    source = GuestBioSource(
        display_name="Ada Lovelace",
        reference_document_id="doc-ada",
        reference_document_revision_id="rev-ada",
        source_content="Ada wrote notes on the Analytical Engine.",
    )

    result = await generator.generate(SCRIPT_TEI, (source,))

    assert len(llm.requests) == 1
    assert llm.requests[0].model == "vidai-mock"
    assert "Ada wrote notes on the Analytical Engine." in llm.requests[0].prompt
    assert result.entries == (
        GuestBioEntry(
            display_name="Ada Lovelace",
            bio="Ada Lovelace wrote about analytical engines.",
            reference_document_revision_id="rev-ada",
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
        series_profile_id=series_profile_id,
        episode_id=episode_id,
        template_id=template_id,
        tei_xml=SCRIPT_TEI,
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
        series_profile_id=uuid4(),
        tei_xml=SCRIPT_TEI,
        generator=generator,
        binding_resolver=binding_resolver,
    )

    assert result.tei_xml == SCRIPT_TEI
    assert result.sources == ()
    assert result.generation_result.entries == ()
    assert not llm.requests


def test_enrich_tei_with_guest_bios_appends_canonical_div() -> None:
    """Append a canonical guest-bios div that round-trips through TEI."""
    result = GuestBiosResult(
        entries=(
            GuestBioEntry(
                display_name="Ada Lovelace",
                bio="Ada Lovelace writes about analytical engines.",
                reference_document_revision_id="rev-ada",
                role="Mathematician",
            ),
        ),
        usage=_usage(),
    )

    enriched_xml = enrich_tei_with_guest_bios(SCRIPT_TEI, result)
    blocks = _body_blocks(enriched_xml)
    guest_bios = typ.cast("dict[str, object]", blocks[-1])

    assert guest_bios["type"] == "div"
    assert guest_bios["div_type"] == "guest-bios"
    content = typ.cast("list[object]", guest_bios["content"])
    guest_list = typ.cast("dict[str, object]", content[0])
    item = typ.cast(
        "dict[str, object]", typ.cast("list[object]", guest_list["items"])[0]
    )

    assert item["corresp"] == ["rev-ada"]
    assert item["n"] == "Mathematician"
    assert item["label"] == {"content": [{"type": "text", "value": "Ada Lovelace"}]}
    assert item["content"] == [
        {
            "type": "text",
            "value": "Ada Lovelace writes about analytical engines.",
        }
    ]


def test_enrich_tei_with_guest_bios_replaces_existing_guest_bios_div() -> None:
    """Replace a prior guest-bios div instead of appending duplicates."""
    first_result = GuestBiosResult(
        entries=(
            GuestBioEntry(
                display_name="Ada Lovelace",
                bio="Old biography.",
                reference_document_revision_id="rev-ada-old",
            ),
        ),
        usage=_usage(),
    )
    second_result = GuestBiosResult(
        entries=(
            GuestBioEntry(
                display_name="Grace Hopper",
                bio="Grace Hopper advanced compiler design.",
                reference_document_revision_id="rev-grace",
            ),
        ),
        usage=_usage(),
    )

    once = enrich_tei_with_guest_bios(SCRIPT_TEI, first_result)
    twice = enrich_tei_with_guest_bios(once, second_result)
    guest_bio_blocks = []
    for block in _body_blocks(twice):
        if isinstance(block, dict):
            block_payload = typ.cast("dict[str, object]", block)
            if block_payload.get("div_type") == "guest-bios":
                guest_bio_blocks.append(block_payload)

    assert len(guest_bio_blocks) == 1
    assert "Old biography." not in twice
    assert "Grace Hopper advanced compiler design." in twice


def test_enrich_tei_with_empty_guest_bios_result_returns_original() -> None:
    """Return the input TEI unchanged when there are no guest bios."""
    result = GuestBiosResult(entries=(), usage=_usage())

    assert enrich_tei_with_guest_bios(SCRIPT_TEI, result) == SCRIPT_TEI
