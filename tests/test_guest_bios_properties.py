"""Property tests for guest biography TEI enrichment."""

import typing as typ

import pytest
import tei_rapporteur as tei
from hypothesis import given
from hypothesis import strategies as st

from episodic.generation.guest_bios import (
    GuestBioEntry,
    GuestBiosResult,
    enrich_tei_with_guest_bios,
)
from episodic.llm import LLMUsage

SCRIPT_TEI = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
    "<teiHeader><fileDesc><title>Guest Bio Properties</title></fileDesc></teiHeader>"
    "<text><body><p>Episode body.</p></body></text>"
    "</TEI>"
)


def _is_xml_compatible_text(value: str) -> bool:
    """Return True when all characters are valid XML 1.0 text characters."""

    def is_allowed(char: str) -> bool:
        codepoint = ord(char)
        is_noncharacter = 0xFDD0 <= codepoint <= 0xFDEF or codepoint & 0xFFFF in {
            0xFFFE,
            0xFFFF,
        }
        return not is_noncharacter and (
            char in "\t\n\r"
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        )

    return all(is_allowed(char) for char in value)


_TEXT = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cc", "Cs"),
        blacklist_characters="<>&",
    ),
    min_size=1,
    max_size=48,
).filter(lambda value: bool(value.strip()) and _is_xml_compatible_text(value))


def _usage() -> LLMUsage:
    return LLMUsage(input_tokens=1, output_tokens=1, total_tokens=2)


@st.composite
def _guest_entries(draw: st.DrawFn) -> tuple[GuestBioEntry, ...]:
    names = draw(st.lists(_TEXT, min_size=1, max_size=4, unique=True))
    entries: list[GuestBioEntry] = []
    for index, name in enumerate(names):
        entries.append(
            GuestBioEntry(
                display_name=name,
                bio=draw(_TEXT),
                reference_document_revision_id=f"rev-{index}",
            )
        )
    return tuple(entries)


def _result(entries: tuple[GuestBioEntry, ...]) -> GuestBiosResult:
    return GuestBiosResult(entries=entries, usage=_usage())


def _guest_bio_items(xml: str) -> list[dict[str, object]]:
    document_payload = typ.cast("dict[str, object]", tei.to_dict(tei.parse_xml(xml)))
    text_payload = typ.cast("dict[str, object]", document_payload["text"])
    body_payload = typ.cast("dict[str, object]", text_payload["body"])
    blocks = typ.cast("list[object]", body_payload["blocks"])
    guest_bios = _guest_bio_divs(blocks)
    content = typ.cast("list[object]", guest_bios[0]["content"])
    list_payload = typ.cast("dict[str, object]", content[0])
    return [
        typ.cast("dict[str, object]", item)
        for item in typ.cast("list[object]", list_payload["items"])
    ]


def _guest_bio_divs(blocks: list[object]) -> list[dict[str, object]]:
    """Return parsed guest-bios div blocks."""
    return [
        typ.cast("dict[str, object]", block)
        for block in blocks
        if isinstance(block, dict)
        and typ.cast("dict[str, object]", block).get("div_type") == "guest-bios"
    ]


def _inline_text(value: object) -> str:
    content = typ.cast("list[object]", value)
    text_parts: list[str] = []
    for item in content:
        if isinstance(item, dict):
            item_payload = typ.cast("dict[str, object]", item)
            if item_payload.get("type") == "text":
                text_parts.append(typ.cast("str", item_payload["value"]))
    return "".join(text_parts)


def _label_text(item: dict[str, object]) -> str:
    label = typ.cast("dict[str, object]", item["label"])
    return _inline_text(label["content"])


@given(_guest_entries())
def test_enriched_guest_bios_round_trip(entries: tuple[GuestBioEntry, ...]) -> None:
    """Generated guest-bio TEI remains parseable across varied text inputs."""
    enriched = enrich_tei_with_guest_bios(SCRIPT_TEI, _result(entries))

    document = tei.parse_xml(enriched)
    document.validate()
    assert 'type="guest-bios"' in tei.emit_xml(document)


@given(_guest_entries())
def test_enriched_guest_bios_preserves_entry_order(
    entries: tuple[GuestBioEntry, ...],
) -> None:
    """Guest-bio items are emitted in generator result order."""
    enriched = enrich_tei_with_guest_bios(SCRIPT_TEI, _result(entries))
    item_labels = [_label_text(item) for item in _guest_bio_items(enriched)]

    assert item_labels == [entry.display_name for entry in entries]


@given(_guest_entries(), _guest_entries())
def test_enriched_guest_bios_replaces_prior_guest_bios_div(
    first_entries: tuple[GuestBioEntry, ...],
    second_entries: tuple[GuestBioEntry, ...],
) -> None:
    """A second enrichment replaces the previous guest-bios block."""
    once = enrich_tei_with_guest_bios(SCRIPT_TEI, _result(first_entries))
    twice = enrich_tei_with_guest_bios(once, _result(second_entries))
    item_bios = [_inline_text(item["content"]) for item in _guest_bio_items(twice)]

    document_payload = typ.cast("dict[str, object]", tei.to_dict(tei.parse_xml(twice)))
    text_payload = typ.cast("dict[str, object]", document_payload["text"])
    body_payload = typ.cast("dict[str, object]", text_payload["body"])
    guest_bios_divs = _guest_bio_divs(typ.cast("list[object]", body_payload["blocks"]))
    assert len(guest_bios_divs) == 1
    assert item_bios == [entry.bio for entry in second_entries]


@given(_TEXT)
def test_empty_guest_bios_result_is_no_op(script_text: str) -> None:
    """Empty guest-bios results leave the input TEI unchanged."""
    tei_xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Guest Bio Properties</title>"
        "</fileDesc></teiHeader>"
        f"<text><body><p>{script_text}</p></body></text>"
        "</TEI>"
    )

    assert enrich_tei_with_guest_bios(tei_xml, _result(())) == tei_xml


@given(st.text(max_size=12).filter(lambda value: not value.strip()))
def test_guest_bio_entries_reject_blank_biography(blank_bio: str) -> None:
    """Guest-bio entries require non-empty biography text."""
    with pytest.raises(ValueError, match="bio"):
        GuestBioEntry(
            display_name="Ada Lovelace",
            bio=blank_bio,
            reference_document_revision_id="rev-ada",
        )
