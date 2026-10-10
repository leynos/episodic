"""OpenAI-compatible adapter configuration validation helpers.

This module validates the OpenAI-compatible adapter's configuration fields
(base URL, API key, retry and timeout settings, and the preflight
token-estimation ratio) and emits a structured `openai_adapter.config_rejected`
error event before raising when any field is invalid.
"""

import json
import math
import typing as typ

from episodic.llm.openai_api.utils_logging import _log_error_event, _operation_label

if typ.TYPE_CHECKING:
    from episodic.llm.ports import LLMProviderOperation

_MIN_CHARS_PER_TOKEN = 0.001


class _OpenAIConfigForValidation(typ.Protocol):
    """Configuration fields required by `_validate_llm_config`."""

    @property
    def base_url(self) -> str:
        """The OpenAI-compatible provider base URL."""

    @property
    def api_key(self) -> str:
        """The provider API key."""

    @property
    def provider_operation(self) -> LLMProviderOperation | str:
        """The default provider operation."""

    @property
    def max_attempts(self) -> int:
        """The maximum retry attempts."""

    @property
    def retry_delay_seconds(self) -> float:
        """The retry backoff multiplier."""

    @property
    def timeout_seconds(self) -> float:
        """The provider request timeout."""

    @property
    def chars_per_token(self) -> float:
        """The preflight token-estimation divisor."""


def _is_positive_int(value: object) -> bool:
    """Return whether value is a positive integer, excluding booleans."""
    match value:
        case bool():
            return False
        case int() as number:
            return number > 0
        case _:
            return False


def _json_safe(value: object) -> object:
    """Return *value* in a form the error logger can always serialize.

    A rejected config value is logged before the validator raises. The logger
    encodes its fields with `json.dumps`, so an unserializable value such as
    `object()` would raise `TypeError` from the logging path and mask the
    documented `ValueError`. Values JSON already encodes are passed through
    unchanged, keeping the logged types stable for ordinary mistyping;
    anything else is described with `repr`, which always returns a string.

    Returns
    -------
    object
        *value* itself when JSON can encode it, otherwise ``repr(value)``.
    """
    try:
        json.dumps(value)
    except TypeError, ValueError:
        return repr(value)
    return value


def _meets_finite_numeric_floor(
    value: object,
    floor: float,
    *,
    inclusive: bool,
) -> bool:
    """Check a finite numeric value against an inclusive or strict floor."""
    match value:
        case bool():
            return False
        case (int() | float()) as number:
            meets_floor = number >= floor if inclusive else number > floor
            return math.isfinite(number) and meets_floor
        case _:
            return False


def _is_non_negative_number(value: object) -> bool:
    """Return whether value is a finite non-negative number."""
    return _meets_finite_numeric_floor(value, 0, inclusive=True)


def _is_positive_number(value: object) -> bool:
    """Return whether value is a finite positive number."""
    return _meets_finite_numeric_floor(value, 0, inclusive=False)


def _is_non_empty_string(value: object) -> bool:
    """Return True when *value* is a non-empty, non-whitespace string."""
    match value:
        case str() as text:
            return bool(text.strip())
        case _:
            return False


def _is_valid_chars_per_token(value: object) -> bool:
    """Return True when *value* can produce stable token-count estimates."""
    return _meets_finite_numeric_floor(
        value,
        _MIN_CHARS_PER_TOKEN,
        inclusive=True,
    )


def _llm_config_checks(
    config: _OpenAIConfigForValidation,
    *,
    chars_per_token: object,
    is_base_url_configured: bool,
    is_api_key_configured: bool,
) -> list[tuple[bool, str, str]]:
    """Return validation checks for OpenAI-compatible adapter config."""
    chars_per_token_msg = (
        f"chars_per_token must be finite and at least {_MIN_CHARS_PER_TOKEN} "
        f"(got {chars_per_token!r})."
    )
    return [
        (
            not _is_positive_int(config.max_attempts),
            "max_attempts",
            "max_attempts must be greater than zero.",
        ),
        (
            not _is_non_negative_number(config.retry_delay_seconds),
            "retry_delay_seconds",
            "retry_delay_seconds must be non-negative.",
        ),
        (
            not _is_positive_number(config.timeout_seconds),
            "timeout_seconds",
            "timeout_seconds must be greater than zero.",
        ),
        (
            not _is_valid_chars_per_token(chars_per_token),
            "chars_per_token",
            chars_per_token_msg,
        ),
        (not is_base_url_configured, "base_url", "base_url must be non-empty."),
        (not is_api_key_configured, "api_key", "api_key must be non-empty."),
    ]


def _validate_llm_config(config: _OpenAIConfigForValidation) -> None:
    """Validate OpenAI-compatible LLM configuration field values."""
    base_url: object = config.base_url
    api_key: object = config.api_key
    chars_per_token: object = config.chars_per_token
    is_base_url_configured = _is_non_empty_string(base_url)
    is_api_key_configured = _is_non_empty_string(api_key)
    rejection_fields = {
        "provider_operation": _operation_label(config.provider_operation),
        "max_attempts": _json_safe(config.max_attempts),
        "retry_delay_seconds": _json_safe(config.retry_delay_seconds),
        "timeout_seconds": _json_safe(config.timeout_seconds),
        "chars_per_token": repr(chars_per_token),
        "base_url_configured": is_base_url_configured,
        "api_key_configured": is_api_key_configured,
    }
    for violated, field_name, msg in _llm_config_checks(
        config,
        chars_per_token=chars_per_token,
        is_base_url_configured=is_base_url_configured,
        is_api_key_configured=is_api_key_configured,
    ):
        if violated:
            _log_error_event(
                "openai_adapter.config_rejected",
                field=field_name,
                **rejection_fields,
            )
            raise ValueError(msg)
