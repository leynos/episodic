"""Shared validation primitives for canonical domain record value objects."""


def require_positive_integer(value: object, field_name: str) -> None:
    """Require an exact positive integer, excluding boolean values."""
    if type(value) is not int or value < 1:
        msg = f"{field_name} must be a positive integer."
        raise ValueError(msg)


def require_value(value: object, field_name: str) -> None:
    """Require a non-null provenance value."""
    if value is None:
        msg = f"{field_name} must be set."
        raise ValueError(msg)


def validate_non_empty_text(value: str, field_name: str) -> None:
    """Validate a required non-blank string field."""
    if not isinstance(value, str):
        msg = f"{field_name} must be a string."
        raise TypeError(msg)
    if not value.strip():
        msg = f"{field_name} must be a non-empty string."
        raise ValueError(msg)


def validate_optional_text(value: str | None, field_name: str) -> None:
    """Validate an optional string field when present."""
    if value is not None:
        validate_non_empty_text(value, field_name)


def copy_json_mapping(owner: object, field_name: str) -> None:
    """Validate and defensively copy a JSON mapping dataclass field."""
    value = getattr(owner, field_name)
    if not isinstance(value, dict):
        msg = f"{field_name} must be a JSON mapping."
        raise TypeError(msg)
    object.__setattr__(owner, field_name, dict(value))
