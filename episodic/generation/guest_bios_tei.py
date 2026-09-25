"""Encode guest biographies as canonical TEI body content."""

import typing as typ

import tei_rapporteur as tei

if typ.TYPE_CHECKING:
    from episodic.generation.guest_bios import GuestBioEntry, GuestBiosResult


def enrich_tei_with_guest_bios(tei_xml: str, result: GuestBiosResult) -> str:
    """Insert guest biographies into a TEI document body idempotently."""
    if not result.entries:
        return tei_xml
    document = tei.parse_xml(tei_xml)
    document_payload = typ.cast("dict[str, object]", tei.to_dict(document))
    body_blocks = _body_blocks_payload(document_payload)
    body_blocks[:] = [
        block for block in body_blocks if not _is_guest_bios_div_payload(block)
    ]
    body_blocks.append(_build_guest_bios_div_payload(result.entries))
    return tei.emit_xml(tei.from_dict(document_payload))


def _build_guest_bios_div_payload(
    entries: tuple[GuestBioEntry, ...],
) -> dict[str, object]:
    """Build the canonical TEI body payload for guest biographies."""
    return {
        "type": "div",
        "div_type": "guest-bios",
        "content": [
            {"type": "list", "items": [_build_item_payload(entry) for entry in entries]}
        ],
    }


def _build_item_payload(entry: GuestBioEntry) -> dict[str, object]:
    """Build one guest-bio list item payload."""
    item_payload: dict[str, object] = {
        "label": {"content": _text_inline(entry.display_name)},
        "content": _text_inline(entry.bio),
        "corresp": [entry.get_external_corresp_id()],
    }
    if entry.role is not None:
        item_payload["n"] = entry.role
    if entry.tei_locator is not None:
        item_payload["ana"] = [entry.tei_locator]
    return item_payload


def _body_blocks_payload(document_payload: dict[str, object]) -> list[object]:
    """Return the mutable TEI body blocks list from a document payload."""
    text_payload = _require_object(document_payload.get("text"), "text")
    body_payload = _require_object(text_payload.get("body"), "text.body")
    blocks = body_payload.get("blocks")
    if not isinstance(blocks, list):
        msg = "TEI payload field text.body.blocks must be a list."
        raise TypeError(msg)
    return typ.cast("list[object]", blocks)


def _require_object(value: object, field_name: str) -> dict[str, object]:
    """Require a mapping inside a TEI payload."""
    if not isinstance(value, dict):
        msg = f"TEI payload field {field_name} must be an object."
        raise TypeError(msg)
    return typ.cast("dict[str, object]", value)


def _is_guest_bios_div_payload(value: object) -> bool:
    """Return whether a body block is the canonical guest-bios div."""
    if not isinstance(value, dict):
        return False
    payload = typ.cast("dict[str, object]", value)
    return payload.get("type") == "div" and payload.get("div_type") == "guest-bios"


def _text_inline(text: str) -> list[dict[str, str]]:
    """Build a plain text inline payload for tei_rapporteur."""
    return [{"type": "text", "value": text}]
