"""OpenAI Responses payload normalization."""

import collections.abc as cabc  # noqa: TC003  # Runtime casts use mapping aliases.
import typing as typ

from episodic.llm.ports import LLMResponse

from .openai_validation import (
    _INVALID_RESPONSES_PAYLOAD_MESSAGE,
    OpenAIResponseValidationError,
    _has_valid_identity,
    _is_non_empty_string,
    _is_string_keyed_mapping,
    _normalize_responses_provider_call_usage,
    _normalize_responses_usage,
)

_EMPTY_RESPONSES_CONTENT_MESSAGE = (
    "Invalid OpenAI Responses payload. No output_text item with non-empty text "
    "found in output content."
)


def _get_output_text_item(
    item: object,
) -> cabc.Mapping[str, object] | None:
    """Return *item* as a mapping when it is a non-empty output_text entry."""
    if not _is_string_keyed_mapping(item):
        return None
    item_mapping = typ.cast("cabc.Mapping[str, object]", item)
    if item_mapping.get("type") != "output_text":
        return None
    if not _is_non_empty_string(item_mapping.get("text")):
        return None
    return item_mapping


def _has_output_text_in_content(content: list[object]) -> bool:
    """Check whether content contains a non-empty ``output_text`` item."""
    return any(_get_output_text_item(item) is not None for item in content)


def _get_content_list(
    mapping: cabc.Mapping[str, object],
) -> list[object] | None:
    """Return the ``content`` list from *mapping*, or ``None`` when absent or empty."""
    content = mapping.get("content")
    if not isinstance(content, list) or not content:
        return None
    return typ.cast("list[object]", content)


def _find_output_item_with_text(
    item: object,
) -> cabc.Mapping[str, object] | None:
    """Return the item mapping if it contains an output_text content entry."""
    if not _is_string_keyed_mapping(item):
        return None
    item_mapping = typ.cast("cabc.Mapping[str, object]", item)
    content_items = _get_content_list(item_mapping)
    if content_items is None:
        return None
    if _has_output_text_in_content(content_items):
        return item_mapping
    return None


def _extract_first_output_mapping(
    payload_mapping: cabc.Mapping[str, object],
) -> cabc.Mapping[str, object]:
    """Validate and return the first output item containing output text."""
    output = payload_mapping.get("output")
    if not isinstance(output, list) or not output:
        raise OpenAIResponseValidationError(_INVALID_RESPONSES_PAYLOAD_MESSAGE)
    for item in output:
        candidate = _find_output_item_with_text(item)
        if candidate is not None:
            return candidate
    raise OpenAIResponseValidationError(_EMPTY_RESPONSES_CONTENT_MESSAGE)


def _extract_output_content_list(
    output_mapping: cabc.Mapping[str, object],
) -> list[object]:
    """Validate and return the content list from an output item mapping."""
    content = _get_content_list(output_mapping)
    if content is None:
        raise OpenAIResponseValidationError(_INVALID_RESPONSES_PAYLOAD_MESSAGE)
    return content


def _find_output_text_in_content(content: list[object]) -> str:
    """Return the stripped text of the first output_text item in content."""
    for item in content:
        mapping = _get_output_text_item(item)
        if mapping is not None:
            return typ.cast("str", mapping.get("text")).strip()
    raise OpenAIResponseValidationError(_EMPTY_RESPONSES_CONTENT_MESSAGE)


def _extract_responses_output_text(payload_mapping: cabc.Mapping[str, object]) -> str:
    """Extract assistant output text from an OpenAI Responses payload."""
    output_mapping = _extract_first_output_mapping(payload_mapping)
    content = _extract_output_content_list(output_mapping)
    return _find_output_text_in_content(content)


def _coerce_responses_usage_payload(
    payload_mapping: cabc.Mapping[str, object],
) -> cabc.Mapping[str, object] | None:
    """Extract and validate the optional usage field from a Responses payload."""
    usage_value = payload_mapping.get("usage")
    if usage_value is None:
        return None
    if _is_string_keyed_mapping(usage_value):
        return typ.cast("cabc.Mapping[str, object]", usage_value)
    raise OpenAIResponseValidationError(_INVALID_RESPONSES_PAYLOAD_MESSAGE)


class OpenAIResponsesAdapter:
    """Adapter entrypoint for OpenAI Responses payload normalization."""

    @staticmethod
    def normalize_response(payload: object) -> LLMResponse:
        """Validate and normalize a raw OpenAI Responses payload."""
        if not _is_string_keyed_mapping(payload):
            raise OpenAIResponseValidationError(_INVALID_RESPONSES_PAYLOAD_MESSAGE)

        payload_mapping = typ.cast("cabc.Mapping[str, object]", payload)
        if not _has_valid_identity(payload_mapping):
            raise OpenAIResponseValidationError(_INVALID_RESPONSES_PAYLOAD_MESSAGE)

        usage_payload = _coerce_responses_usage_payload(payload_mapping)
        finish_reason = (
            typ.cast("str", payload_mapping["status"])
            if isinstance(payload_mapping.get("status"), str)
            else None
        )

        return LLMResponse(
            text=_extract_responses_output_text(payload_mapping),
            model=typ.cast("str", payload_mapping["model"]),
            provider_response_id=typ.cast("str", payload_mapping["id"]),
            finish_reason=finish_reason,
            usage=_normalize_responses_usage(usage_payload),
            provider_call_usage=_normalize_responses_provider_call_usage(
                payload_mapping,
                usage_payload,
                finish_reason,
            ),
        )
