"""Facade for the OpenAI-compatible outbound LLM adapter.

The implementation lives under `episodic.llm.openai_api`, where request
construction, response parsing, validation utilities, and the async adapter are
kept in focused modules. This facade preserves the historical import path for
tests and callers that import adapter internals directly.
"""

from episodic.llm.openai_api.adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)
from episodic.llm.openai_api.request import (
    _build_payload,
    _coerce_operation,
    _path_for_operation,
)
from episodic.llm.openai_api.response import (
    _check_http_status,
    _decode_json_response,
    _normalize_payload,
)
from episodic.llm.openai_api.utils import (
    _estimate_token_count,
    _has_non_negative_int_mapping_value,
    _operation_label,
    _require_concrete_usage_counts,
    _validate_llm_config,
    _validate_preflight_budget,
    _validate_usage_budget,
)

__all__ = [
    "OpenAICompatibleLLMAdapter",
    "OpenAICompatibleLLMConfig",
    "_build_payload",
    "_check_http_status",
    "_coerce_operation",
    "_decode_json_response",
    "_estimate_token_count",
    "_has_non_negative_int_mapping_value",
    "_normalize_payload",
    "_operation_label",
    "_path_for_operation",
    "_require_concrete_usage_counts",
    "_validate_llm_config",
    "_validate_preflight_budget",
    "_validate_usage_budget",
]
