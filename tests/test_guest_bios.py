"""Guest biography generation and TEI enrichment tests."""

import json
import typing as typ

import pytest
import tei_rapporteur as tei

from episodic.generation.guest_bios import (
    GuestBioEntry,
    GuestBiosGenerator,
    GuestBiosResponseFormatError,
    GuestBiosResult,
    enrich_tei_with_guest_bios,
)
from episodic.llm import LLMResponse, LLMUsage

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
