"""Configuration validation for the OpenAI-compatible adapter."""

import math
import typing as typ

from episodic.llm.openai_api.utils import _OpenAIConfigForValidation, _operation_label

if typ.TYPE_CHECKING:
    import collections.abc as cabc
else:
    cabc = typ.cast("object", object)


def validate_llm_config(
    config: _OpenAIConfigForValidation,
    *,
    log_error_event: cabc.Callable[..., None],
) -> None:
    """Validate required adapter configuration and log the rejected field."""
    base_url: object = config.base_url
    api_key: object = config.api_key
    chars_per_token: object = config.chars_per_token
    base_url_configured = _is_non_empty_string(base_url)
    api_key_configured = _is_non_empty_string(api_key)
    rejection_fields = {
        "provider_operation": _operation_label(config.provider_operation),
        "max_attempts": config.max_attempts,
        "retry_delay_seconds": config.retry_delay_seconds,
        "timeout_seconds": config.timeout_seconds,
        "chars_per_token": repr(chars_per_token),
        "base_url_configured": base_url_configured,
        "api_key_configured": api_key_configured,
    }
    for violated, field_name, msg in _config_checks(
        config,
        chars_per_token=chars_per_token,
        base_url_configured=base_url_configured,
        api_key_configured=api_key_configured,
    ):
        if violated:
            log_error_event(
                "openai_adapter.config_rejected", field=field_name, **rejection_fields
            )
            raise ValueError(msg)


def _config_checks(
    config: _OpenAIConfigForValidation,
    *,
    chars_per_token: object,
    base_url_configured: bool,
    api_key_configured: bool,
) -> list[tuple[bool, str, str]]:
    """Return the independent adapter configuration validation checks."""
    chars_per_token_msg = (
        f"chars_per_token must be finite and at least 0.001 (got {chars_per_token!r})."
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
        (not base_url_configured, "base_url", "base_url must be non-empty."),
        (not api_key_configured, "api_key", "api_key must be non-empty."),
    ]


def _is_positive_int(value: object) -> bool:
    """Return whether value is a positive integer, excluding booleans."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_non_negative_number(value: object) -> bool:
    """Return whether value is a finite non-negative number."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _is_positive_number(value: object) -> bool:
    """Return whether value is a finite positive number."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _is_non_empty_string(value: object) -> bool:
    """Return whether value is a non-empty, non-whitespace string."""
    return isinstance(value, str) and bool(value.strip())


_MIN_CHARS_PER_TOKEN = 0.001


def _is_valid_chars_per_token(value: object) -> bool:
    """Return whether value can produce stable token-count estimates."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= _MIN_CHARS_PER_TOKEN
    )
