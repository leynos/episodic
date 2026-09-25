"""TEI body enrichment with generated guest biography content.

This module inserts a ``<div type="guest-bios">`` element containing
structured guest biography metadata into a TEI P5 document. It is split out
of :mod:`episodic.generation.guest_bios` so that module stays under the
project's line-count limit; import the public names from
:mod:`episodic.generation.guest_bios` rather than from here.
"""

import typing as typ

import tei_rapporteur as tei

if typ.TYPE_CHECKING:
    from episodic.generation.guest_bios_models import GuestBioEntry, GuestBiosResult


def _require_payload_object(value: object, field_name: str) -> dict[str, object]:
    """Require a mapping inside a TEI payload or raise ValueError."""
    if not isinstance(value, dict):
        msg = f"TEI payload field {field_name} must be an object."
        # _require_payload_object treats this as invalid TEI payload content,
        # not Python call-site type misuse.
        raise ValueError(msg)  # noqa: TRY004
    return typ.cast("dict[str, object]", value)


def _require_payload_list(value: object, field_name: str) -> list[object]:
    """Require a list inside a TEI payload or raise ValueError."""
    if not isinstance(value, list):
        msg = f"TEI payload field {field_name} must be a list."
        # _require_payload_list treats this as invalid TEI payload content,
        # not Python call-site type misuse.
        raise ValueError(msg)  # noqa: TRY004
    return typ.cast("list[object]", value)


def _build_text_inline(text: str) -> list[dict[str, str]]:
    """Build a plain text inline payload for tei_rapporteur."""
    return [{"type": "text", "value": text}]


def _build_item_payload(entry: GuestBioEntry) -> dict[str, object]:
    """Build one guest-bio list item payload."""
    item_payload: dict[str, object] = {
        "label": {"content": _build_text_inline(entry.display_name)},
        "content": _build_text_inline(entry.bio),
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


def _body_blocks_payload(document_payload: dict[str, object]) -> list[object]:
    """Return the mutable TEI body blocks list from a document payload."""
    text_payload = _require_payload_object(document_payload.get("text"), "text")
    body_payload = _require_payload_object(text_payload.get("body"), "text.body")
    return _require_payload_list(body_payload.get("blocks"), "text.body.blocks")


def _is_guest_bios_div_payload(value: object) -> bool:
    """Return True when a body block payload is the canonical guest-bios div."""
    if not isinstance(value, dict):
        return False
    payload = typ.cast("dict[str, object]", value)
    return payload.get("type") == "div" and payload.get("div_type") == "guest-bios"


def enrich_tei_with_guest_bios(tei_xml: str, result: GuestBiosResult) -> str:
    """Insert guest biographies into a TEI document body."""
    if not result.entries:
        return tei_xml

    document = tei.parse_xml(tei_xml)
    document_payload = typ.cast("dict[str, object]", tei.to_dict(document))
    body_blocks = _body_blocks_payload(document_payload)
    body_blocks[:] = [
        body_block
        for body_block in body_blocks
        if not _is_guest_bios_div_payload(body_block)
    ]
    body_blocks.append(_build_guest_bios_div_payload(result.entries))
    enriched_document = tei.from_dict(document_payload)
    return tei.emit_xml(enriched_document)
