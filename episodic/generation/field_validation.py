"""Field validators shared by the generation tools' data contracts."""


def ensure_non_empty_fields(instance: object, *field_names: str) -> None:
    """Reject blank or whitespace-only string fields on a dataclass instance.

    Parameters
    ----------
    instance : object
        The dataclass instance whose fields are checked, normally ``self`` from
        a ``__post_init__`` hook.
    *field_names : str
        Names of the attributes that must hold a non-blank string.

    Raises
    ------
    ValueError
        If a named attribute is not a string, or is empty or only whitespace.
        A non-string value raises ``ValueError`` as well, not ``TypeError``,
        so every generation contract reports one error type.

    Examples
    --------
    >>> import dataclasses as dc
    >>> @dc.dataclass
    ... class Entry:
    ...     title: str
    >>> ensure_non_empty_fields(Entry("Intro"), "title")
    >>> ensure_non_empty_fields(Entry("  "), "title")
    Traceback (most recent call last):
        ...
    ValueError: title must be non-empty.
    """
    for field_name in field_names:
        value = getattr(instance, field_name)
        if not isinstance(value, str) or not value.strip():
            msg = f"{field_name} must be non-empty."
            raise ValueError(msg)
