"""OpenAI adapter validation and token-budget helper utilities.

This module re-exports the OpenAI-compatible adapter's configuration
validation, prompt token estimation, preflight budget enforcement, provider
usage-budget validation, and structured error-event logging helpers, which
live in the sibling `utils_logging`, `utils_config`, `utils_preflight`, and
`utils_usage` modules. The split keeps each module focused on one cohesive
responsibility while preserving this module's historical import path for
callers and tests.

Examples
--------
Import the module and call the estimation helper when checking the heuristic
used by preflight budget validation:

>>> from episodic.llm.openai_api import utils
>>> utils._estimate_token_count(4.0, "system", "prompt")
3
"""

from episodic.llm.openai_api.utils_config import (
    _validate_llm_config,  # ruff: ignore[unused-import]  # Re-exported for callers of the original path.
)
from episodic.llm.openai_api.utils_logging import (
    # Re-exported for callers of the original path.
    _log_error_event as _log_error_event,
)
from episodic.llm.openai_api.utils_logging import (
    # Re-exported for callers of the original path.
    _log_override as _log_override,
)
from episodic.llm.openai_api.utils_logging import (
    _operation_label,  # ruff: ignore[unused-import]  # Re-exported for callers of the original path.
)
from episodic.llm.openai_api.utils_preflight import (
    _estimate_token_count,  # ruff: ignore[unused-import]  # Re-exported for callers of the original path.
    _validate_preflight_budget,  # ruff: ignore[unused-import]  # Re-exported for callers of the original path.
)
from episodic.llm.openai_api.utils_usage import (
    _has_non_negative_int_mapping_value,  # ruff: ignore[unused-import]  # Re-exported for callers of the original path.
    _require_concrete_usage_counts,  # ruff: ignore[unused-import]  # Re-exported for callers of the original path.
    _validate_usage_budget,  # ruff: ignore[unused-import]  # Re-exported for callers of the original path.
)
