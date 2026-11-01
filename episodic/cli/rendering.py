"""Pure renderers for a page of QA evaluations.

Both renderers are total functions from a decoded API payload to the string the
CLI prints. Keeping them free of I/O lets ``syrupy`` snapshot them without a
process boundary, which is what pins the CLI's observable output.
"""

import json
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_TABLE_COLUMNS = ("EVALUATOR", "STATUS", "FINDINGS", "EVALUATED AT", "ID")
_COLUMN_GAP = "  "
_SUMMARY_TEMPLATE = "{shown} of {total} evaluations"


def render_table(payload: cabc.Mapping[str, object]) -> str:
    """Render one page of evaluation summaries as a fixed-width table.

    Parameters
    ----------
    payload : collections.abc.Mapping[str, object]
        Decoded list envelope carrying ``items`` and the unpaged ``total``.

    Returns
    -------
    str
        A header row, one row per evaluation, and a summary line, terminated
        by a newline.

    Examples
    --------
    >>> print(render_table({"items": [], "total": 0}), end="")
    EVALUATOR  STATUS  FINDINGS  EVALUATED AT  ID
    0 of 0 evaluations
    """
    items = _items(payload)
    rows = [_table_row(item) for item in items]
    widths = [
        max(len(cell) for cell in column)
        for column in zip(_TABLE_COLUMNS, *rows, strict=True)
    ]
    lines = [_format_row(cells, widths) for cells in (_TABLE_COLUMNS, *rows)]
    summary = _SUMMARY_TEMPLATE.format(
        shown=len(items),
        total=_total(payload, len(items)),
    )
    lines.append(summary)
    return "\n".join(lines) + "\n"


def render_json(payload: cabc.Mapping[str, object]) -> str:
    """Render a decoded payload as pretty-printed JSON.

    Parameters
    ----------
    payload : collections.abc.Mapping[str, object]
        Decoded response body, printed without reordering its keys.

    Returns
    -------
    str
        Two-space-indented JSON terminated by a newline, ready to pipe into
        ``jq``.

    Examples
    --------
    >>> print(render_json({"limit": 20}), end="")
    {
      "limit": 20
    }
    """
    return json.dumps(payload, indent=2) + "\n"


def _as_mapping(entry: object) -> cabc.Mapping[str, object] | None:
    """Return ``entry`` when it is a JSON object, otherwise ``None``."""
    match entry:
        case dict() as mapping:
            return typ.cast("cabc.Mapping[str, object]", mapping)
        case _:
            return None


def _items(payload: cabc.Mapping[str, object]) -> list[cabc.Mapping[str, object]]:
    """Return the envelope's page items, ignoring a malformed value."""
    match payload.get("items"):
        case list() as entries:
            mappings = (
                _as_mapping(entry) for entry in typ.cast("list[object]", entries)
            )
            return [mapping for mapping in mappings if mapping is not None]
        case _:
            return []


def _total(payload: cabc.Mapping[str, object], fallback: int) -> int:
    """Return the envelope's unpaged total, falling back to the page length."""
    match payload.get("total"):
        # ``bool`` is an ``int`` subclass, but a boolean total is not a count.
        case bool():
            return fallback
        case int() as total:
            return total
        case _:
            return fallback


def _table_row(item: cabc.Mapping[str, object]) -> tuple[str, ...]:
    """Return one evaluation as its five printable cells."""
    return (
        _cell(item, "evaluator"),
        _cell(item, "compliance_status"),
        _cell(item, "finding_count"),
        _cell(item, "evaluated_at"),
        _cell(item, "id"),
    )


def _cell(item: cabc.Mapping[str, object], key: str) -> str:
    """Return one field as text, printing an absent field as empty."""
    value = item.get(key)
    return "" if value is None else str(value)


def _format_row(cells: tuple[str, ...], widths: list[int]) -> str:
    """Pad one row to the column widths, without trailing whitespace."""
    padded = (cell.ljust(width) for cell, width in zip(cells, widths, strict=True))
    return _COLUMN_GAP.join(padded).rstrip()
