"""Build and validate the provider and TEI representations of draft scripts."""

import dataclasses as dc
import json
import typing as typ

import tei_rapporteur as tei

from episodic.canonical.hashing import sha256_text
from episodic.generation.draft_script import (
    DraftIdFactory,
    DraftScriptRequest,
    DraftScriptResponseFormatError,
    DraftScriptResult,
    DraftScriptTeiError,
    DraftTurn,
    _ParsedDraft,
)
from episodic.generation.tei_payload import (
    require_mapping,
    require_non_empty_str_value,
    require_sequence,
)

if typ.TYPE_CHECKING:
    from episodic.llm import LLMResponse

type JsonMapping = dict[str, object]


def build_prompt(request: DraftScriptRequest) -> str:
    """Build a deterministic JSON prompt payload for draft generation."""
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


def result_from_response(
    response: LLMResponse,
    *,
    maximum_response_bytes: int,
    id_factory: DraftIdFactory,
) -> DraftScriptResult:
    """Validate a provider response and return its canonical draft result."""
    _require_response_size(response.text, maximum_response_bytes)
    tei_xml = _emit_tei(_parse_response(response), id_factory)
    return DraftScriptResult(
        tei_xml=tei_xml,
        content_hash=sha256_text(tei_xml),
        usage=response.usage,
        model=response.model,
        provider_response_id=response.provider_response_id,
        finish_reason=response.finish_reason,
        provider_call_usage=response.provider_call_usage,
    )


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
        payload, "response", error_cls=DraftScriptResponseFormatError
    )
    title = require_non_empty_str_value(
        payload_dict.get("title"), "title", error_cls=DraftScriptResponseFormatError
    ).strip()
    raw_turns = require_sequence(
        payload_dict.get("turns"), "turns", error_cls=DraftScriptResponseFormatError
    )
    turns = tuple(_parse_turn(raw_turn) for raw_turn in raw_turns)
    if not turns:
        msg = "turns must contain at least one turn."
        raise DraftScriptResponseFormatError(msg)
    return _ParsedDraft(title=title, turns=turns)


def _parse_turn(raw_turn: object) -> DraftTurn:
    """Parse one generated turn."""
    turn = require_mapping(raw_turn, "turn", error_cls=DraftScriptResponseFormatError)
    text = require_non_empty_str_value(
        turn.get("text"), "text", error_cls=DraftScriptResponseFormatError
    ).strip()
    return DraftTurn(text=text, speaker=_optional_non_empty_string(turn.get("speaker")))


def _optional_non_empty_string(value: object) -> str | None:
    """Return a stripped optional string or reject another JSON type."""
    if value is None:
        return None
    if not isinstance(value, str):
        msg = "speaker must be a string or null."
        raise DraftScriptResponseFormatError(msg)
    return value.strip() or None


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
    """Convert one generated turn to a ``tei_rapporteur`` body block."""
    content = [{"type": "text", "value": turn.text}]
    if turn.speaker is None:
        return {"type": "paragraph", "xml_id": id_factory("p"), "content": content}
    return {
        "type": "utterance",
        "speaker": turn.speaker,
        "xml_id": id_factory("u"),
        "content": content,
    }
