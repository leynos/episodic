"""TEI enrichment for chapter-marker results."""

import typing as typ
import uuid

import tei_rapporteur as tei

from episodic.generation.chapter_marker_common import (
    _EMPTY_CHAPTER_SUMMARY_SENTINEL_PREFIX,
    logger,
)
from episodic.generation.tei_payload import (
    body_blocks_payload,
    build_text_inline,
    is_div_payload,
    require_mapping,
    require_sequence,
)
from episodic.logging import log_info

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.generation.chapter_marker_models import (
        ChapterMarker,
        ChapterMarkersResult,
    )


def _build_item_payload(chapter: ChapterMarker) -> dict[str, object]:
    """Build one list-item payload from a `ChapterMarker`."""
    item_payload: dict[str, object] = {
        "label": {"content": build_text_inline(chapter.title)},
        "n": chapter.start,
    }
    if chapter.summary:
        item_payload["content"] = build_text_inline(chapter.summary)
    if chapter.tei_locator is not None:
        item_payload["corresp"] = [chapter.tei_locator]
    return item_payload


def _build_chapters_div_payload(
    chapters: tuple[ChapterMarker, ...],
) -> dict[str, object]:
    """Build the structured TEI payload for the chapters div."""
    items = [_build_item_payload(chapter) for chapter in chapters]
    for item in items:
        if "content" not in item:
            item["_empty_chapter_summary"] = True
    return {
        "type": "div",
        "div_type": "chapters",
        "content": [
            {
                "type": "list",
                "items": items,
            }
        ],
    }


def _iter_list_item_payloads(
    list_payload: dict[str, object],
) -> cabc.Iterator[dict[str, object]]:
    """Yield validated item payloads from a single list-type payload."""
    for item in require_sequence(
        list_payload.get("items"),
        "chapters.content[].items",
        error_cls=ValueError,
    ):
        yield require_mapping(
            item,
            "chapters.content[].items[]",
            error_cls=ValueError,
        )


def _iter_chapter_block_item_payloads(
    block_payload: dict[str, object],
) -> cabc.Iterator[dict[str, object]]:
    """Yield item payloads from all list nodes inside a chapters div block."""
    for block_content in require_sequence(
        block_payload.get("content"),
        "chapters.content",
        error_cls=ValueError,
    ):
        list_payload = require_mapping(
            block_content,
            "chapters.content[]",
            error_cls=ValueError,
        )
        if list_payload.get("type") != "list":
            continue
        yield from _iter_list_item_payloads(list_payload)


def _iter_chapter_item_payloads(
    document_payload: dict[str, object],
) -> cabc.Iterator[dict[str, object]]:
    """Yield list-item payloads inside chapter div blocks."""
    body_blocks = body_blocks_payload(document_payload)
    for body_block in body_blocks:
        if not is_div_payload(body_block, "chapters"):
            continue
        block_payload = typ.cast("dict[str, object]", body_block)
        yield from _iter_chapter_block_item_payloads(block_payload)


def _prepare_empty_chapter_summaries_for_tei_rapporteur(
    document_payload: dict[str, object],
) -> str | None:
    """Bridge optional chapter summaries to tei_rapporteur's required item content."""
    sentinel = f"{_EMPTY_CHAPTER_SUMMARY_SENTINEL_PREFIX}{uuid.uuid4().hex}__"
    inserted_sentinel = False
    for item_payload in _iter_chapter_item_payloads(document_payload):
        if item_payload.pop("_empty_chapter_summary", False):
            item_payload["content"] = build_text_inline(sentinel)
            inserted_sentinel = True
    return sentinel if inserted_sentinel else None


def enrich_tei_with_chapter_markers(
    tei_xml: str,
    result: ChapterMarkersResult,
) -> str:
    """Insert chapter-marker metadata into a TEI document body."""
    document = tei.parse_xml(tei_xml)
    document_payload = typ.cast("dict[str, object]", tei.to_dict(document))
    body_blocks = body_blocks_payload(document_payload)
    original_block_count = len(body_blocks)
    body_blocks[:] = [
        body_block
        for body_block in body_blocks
        if not is_div_payload(body_block, "chapters")
    ]
    removed_block_count = original_block_count - len(body_blocks)
    if result.chapters:
        body_blocks.append(_build_chapters_div_payload(result.chapters))
    elif removed_block_count == 0:
        return tei_xml
    sentinel = _prepare_empty_chapter_summaries_for_tei_rapporteur(document_payload)
    enriched_document = tei.from_dict(document_payload)
    enriched_xml = tei.emit_xml(enriched_document)
    if sentinel is not None:
        enriched_xml = enriched_xml.replace(sentinel, "")
    log_info(
        logger,
        "chapter_markers_tei_enriched chapter_count=%s removed_chapter_blocks=%s",
        len(result.chapters),
        removed_block_count,
    )
    return enriched_xml
