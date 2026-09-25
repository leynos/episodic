"""TEI body enrichment with generated show notes.

This module inserts a ``<div type="notes">`` element containing structured
show-notes metadata into a TEI P5 document. It is split out of
:mod:`episodic.generation.show_notes` so that module stays under the
project's line-count limit; import the public names from
:mod:`episodic.generation.show_notes` rather than from here.
"""

import typing as typ

import tei_rapporteur as tei

from episodic.generation.tei_payload import (
    body_blocks_payload,
    build_text_inline,
    is_div_payload,
)

if typ.TYPE_CHECKING:
    from episodic.generation.show_notes_models import ShowNotesEntry, ShowNotesResult


def _build_item_payload(entry: ShowNotesEntry) -> dict[str, object]:
    """Build one list-item payload from a `ShowNotesEntry`."""
    item_payload: dict[str, object] = {
        "label": {"content": build_text_inline(entry.topic)},
        "content": build_text_inline(entry.summary),
    }
    if entry.timestamp is not None:
        item_payload["n"] = entry.timestamp
    if entry.tei_locator is not None:
        item_payload["corresp"] = [entry.tei_locator]
    return item_payload


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


def enrich_tei_with_show_notes(
    tei_xml: str,
    result: ShowNotesResult,
) -> str:
    """Insert show-notes metadata into a TEI document body.

    Parameters
    ----------
    tei_xml : str
        TEI P5 XML document to enrich.
    result : ShowNotesResult
        Show-notes entries to insert.

    Returns
    -------
    str
        Enriched TEI XML as a string.

    Notes
    -----
    The enrichment creates a ``<div type="notes">`` element containing a
    ``<list>`` with ``<item>`` entries. Each item includes:

    - ``<label>``: topic text (required)
    - inline text: summary text (follows the label)
    - ``@n``: optional timestamp attribute
    - ``@corresp``: optional TEI locator attribute

    If the result has no entries, the original TEI is returned unchanged.

    This function uses `tei_rapporteur`'s structured document exchange to
    parse the TEI, append a `div` block to the body payload, then emit the
    enriched document back to XML. Malformed TEI raises `ValueError`.
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
    enriched_document = tei.from_dict(document_payload)
    return tei.emit_xml(enriched_document)
