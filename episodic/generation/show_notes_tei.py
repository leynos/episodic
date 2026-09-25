"""Encode show-notes results as canonical TEI body content."""

import typing as typ

import tei_rapporteur as tei

from episodic.generation.tei_payload import (
    body_blocks_payload,
    build_text_inline,
    is_div_payload,
)

if typ.TYPE_CHECKING:
    from episodic.generation.show_notes import ShowNotesEntry, ShowNotesResult


def enrich_tei_with_show_notes(tei_xml: str, result: ShowNotesResult) -> str:
    """Insert show-notes metadata into a TEI document body.

    Empty results preserve the original document. Existing notes are replaced
    so repeating an enrichment remains idempotent.

    Returns
    -------
    str
        Enriched TEI XML, or the original document for an empty result.
    """
    if not result.entries:
        return tei_xml
    document = tei.parse_xml(tei_xml)
    document_payload = typ.cast("dict[str, object]", tei.to_dict(document))
    body_blocks = body_blocks_payload(document_payload)
    body_blocks[:] = [
        body_block
        for body_block in body_blocks
        if not is_div_payload(body_block, "notes")
    ]
    body_blocks.append(_build_notes_div_payload(result.entries))
    return tei.emit_xml(tei.from_dict(document_payload))


def _build_notes_div_payload(entries: tuple[ShowNotesEntry, ...]) -> dict[str, object]:
    """Build the structured TEI payload for the show-notes div."""
    return {
        "type": "div",
        "div_type": "notes",
        "content": [
            {
                "type": "list",
                "items": [_build_item_payload(entry) for entry in entries],
            }
        ],
    }


def _build_item_payload(entry: ShowNotesEntry) -> dict[str, object]:
    """Build one list-item payload from a show-notes entry."""
    item_payload: dict[str, object] = {
        "label": {"content": build_text_inline(entry.topic)},
        "content": build_text_inline(entry.summary),
    }
    if entry.timestamp is not None:
        item_payload["n"] = entry.timestamp
    if entry.tei_locator is not None:
        item_payload["corresp"] = [entry.tei_locator]
    return item_payload
