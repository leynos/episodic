"""Guest biography TEI enrichment tests."""

import typing as typ

from episodic.generation.guest_bios import (
    GuestBioEntry,
    GuestBiosResult,
    enrich_tei_with_guest_bios,
)
from tests._guest_bios_helpers import SCRIPT_TEI, _body_blocks, _usage


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
