"""Field validators shared by the generation tools' data contracts."""


def ensure_non_empty_fields(instance: object, *field_names: str) -> None:
    """Reject blank or whitespace-only string fields on a dataclass instance."""
    for field_name in field_names:
        value = getattr(instance, field_name)
        if not isinstance(value, str) or not value.strip():
            msg = f"{field_name} must be non-empty."
            raise ValueError(msg)
