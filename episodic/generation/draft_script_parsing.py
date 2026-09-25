"""Prompt building, response parsing, and TEI emission for draft scripts.

``LLMDraftScriptGenerator`` in ``episodic.generation.draft_script`` delegates
to these helpers to serialise the deterministic prompt payload, validate the
LLM's JSON completion against the draft schema, and emit the resulting turns
as TEI-P5 XML.
"""

import dataclasses as dc
import json
import typing as typ

import tei_rapporteur as tei

from episodic.generation.draft_script_errors import (
    DraftScriptResponseFormatError,
    DraftScriptTeiError,
)
from episodic.generation.draft_script_types import DraftIdFactory, DraftTurn
from episodic.generation.tei_payload import (
    require_mapping,
    require_non_empty_str_value,
    require_sequence,
)

if typ.TYPE_CHECKING:
    from episodic.generation.draft_script_types import DraftScriptRequest
    from episodic.llm import LLMResponse

type JsonMapping = dict[str, object]


@dc.dataclass(frozen=True, slots=True)
class _ParsedDraft:
    """Represent a parsed draft title and its ordered turns."""

    title: str
    turns: tuple[DraftTurn, ...]


def _build_prompt(request: DraftScriptRequest) -> str:
    """Build a deterministic JSON prompt payload."""
    payload: JsonMapping = {
        "episode_id": str(request.episode_id),
        "series_profile_id": str(request.series_profile_id),
        "title": request.title,
        "requested_at": request.clock().isoformat(),
        "sources": [dc.asdict(source) for source in request.sources],
        "presenter_profiles": [
            dc.asdict(profile) for profile in request.presenter_profiles
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _require_response_size(response_text: str, maximum_bytes: int) -> None:
    """Reject provider responses that exceed the configured byte limit."""
    if len(response_text.encode("utf-8")) > maximum_bytes:
        msg = "LLM response exceeds the configured maximum size."
        raise DraftScriptResponseFormatError(msg)


def _parse_response(response: LLMResponse) -> _ParsedDraft:
    """Parse and validate the LLM response JSON."""
    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as exc:
        msg = "LLM response is not valid JSON."
        raise DraftScriptResponseFormatError(msg) from exc

    payload_dict = require_mapping(
        payload,
        "response",
        error_cls=DraftScriptResponseFormatError,
    )
    title = require_non_empty_str_value(
        payload_dict.get("title"),
        "title",
        error_cls=DraftScriptResponseFormatError,
    ).strip()
    raw_turns = require_sequence(
        payload_dict.get("turns"),
        "turns",
        error_cls=DraftScriptResponseFormatError,
    )
    turns = tuple(_parse_turn(raw_turn) for raw_turn in raw_turns)
    if len(turns) == 0:
        msg = "turns must contain at least one turn."
        raise DraftScriptResponseFormatError(msg)
    return _ParsedDraft(title=title, turns=turns)


def _parse_turn(raw_turn: object) -> DraftTurn:
    """Parse one generated turn."""
    turn = require_mapping(
        raw_turn,
        "turn",
        error_cls=DraftScriptResponseFormatError,
    )
    text = require_non_empty_str_value(
        turn.get("text"),
        "text",
        error_cls=DraftScriptResponseFormatError,
    ).strip()
    speaker = _optional_non_empty_string(turn.get("speaker"), "speaker")
    return DraftTurn(text=text, speaker=speaker)


def _optional_non_empty_string(value: object, field_name: str) -> str | None:
    """Return an optional stripped string or raise a format error."""
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{field_name} must be a string or null."
        raise DraftScriptResponseFormatError(msg)
    stripped = value.strip()
    return stripped or None


def _emit_tei(parsed: _ParsedDraft, id_factory: DraftIdFactory) -> str:
    """Emit validated TEI XML from a parsed draft."""
    payload: JsonMapping = {
        "header": {"file_desc": {"title": parsed.title}},
        "text": {
            "body": {
                "blocks": [_turn_to_block(turn, id_factory) for turn in parsed.turns]
            }
        },
    }
    try:
        document = tei.from_dict(payload)
        document.validate()
        return tei.emit_xml(document)
    except (TypeError, ValueError) as exc:
        raise DraftScriptTeiError(str(exc)) from exc


def _turn_to_block(turn: DraftTurn, id_factory: DraftIdFactory) -> JsonMapping:
    """Convert one generated turn to a `tei_rapporteur` body block."""
    content = [{"type": "text", "value": turn.text}]
    if turn.speaker is None:
        return {
            "type": "paragraph",
            "xml_id": id_factory("p"),
            "content": content,
        }
    return {
        "type": "utterance",
        "speaker": turn.speaker,
        "xml_id": id_factory("u"),
        "content": content,
    }
