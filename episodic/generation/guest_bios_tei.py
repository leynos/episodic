"""TEI body enrichment with generated guest biography content.

This module inserts a ``<div type="guest-bios">`` element containing
structured guest biography metadata into a TEI P5 document. It is split out
of :mod:`episodic.generation.guest_bios` so that module stays under the
project's line-count limit; import the public names from
:mod:`episodic.generation.guest_bios` rather than from here.
"""

import typing as typ

import tei_rapporteur as tei

from episodic.generation.tei_payload import (
    body_blocks_payload,
    build_text_inline,
    is_div_payload,
)

if typ.TYPE_CHECKING:
    from episodic.generation.guest_bios_models import GuestBioEntry, GuestBiosResult


def _build_item_payload(entry: GuestBioEntry) -> dict[str, object]:
    """Build one guest-bio list item payload."""
    item_payload: dict[str, object] = {
        "label": {"content": build_text_inline(entry.display_name)},
        "content": build_text_inline(entry.bio),
        "corresp": [entry.get_external_corresp_id()],
    }
    if entry.role is not None:
        item_payload["n"] = entry.role
    if entry.tei_locator is not None:
        item_payload["ana"] = [entry.tei_locator]
    return item_payload


def _build_guest_bios_div_payload(
    entries: tuple[GuestBioEntry, ...],
) -> dict[str, object]:
    """Build the canonical TEI body payload for guest biographies."""
    return {
        "type": "div",
        "div_type": "guest-bios",
        "content": [
            {
                "type": "list",
                "items": [_build_item_payload(entry) for entry in entries],
            }
        ],
    }


def enrich_tei_with_guest_bios(tei_xml: str, result: GuestBiosResult) -> str:
    """Insert guest biographies into a TEI document body."""
    if not result.entries:
        return tei_xml

    document = tei.parse_xml(tei_xml)
    document_payload = typ.cast("dict[str, object]", tei.to_dict(document))
    body_blocks = body_blocks_payload(document_payload)
    body_blocks[:] = [
        body_block
        for body_block in body_blocks
        if not is_div_payload(body_block, "guest-bios")
    ]
    body_blocks.append(_build_guest_bios_div_payload(result.entries))
    enriched_document = tei.from_dict(document_payload)
    return tei.emit_xml(enriched_document)
