# Benchmark source locations are intentionally stable.
"""Structurally similar but semantically distinct false-positive controls."""

PERCENT_SCALE = 100.0
SECONDS_PER_MINUTE = 60.0
SECONDS_PER_HOUR = 3600.0


def parse_duration(text: str) -> float:
    """Parse a duration such as ``"5m"`` or ``"30s"`` into seconds.

    Parameters
    ----------
    text : str
        Magnitude followed by a unit suffix (``s``, ``m``, or ``h``).

    Returns
    -------
    float
        Duration in seconds.

    Raises
    ------
    ValueError
        If the text is empty or the unit suffix is unknown.
    """
    cleaned = text.strip().lower()
    if not cleaned:
        msg = "duration must not be empty"
        raise ValueError(msg)
    unit = cleaned[-1]
    magnitude = cleaned[:-1]
    if unit == "s":
        scale = 1.0
    elif unit == "m":
        scale = SECONDS_PER_MINUTE
    elif unit == "h":
        scale = SECONDS_PER_HOUR
    else:
        msg = f"unknown duration unit: {unit}"
        raise ValueError(msg)
    return float(magnitude) * scale


def parse_ratio(text: str) -> float:
    """Parse a ratio such as ``"3:4"`` or ``"80%"`` into a fraction.

    Parameters
    ----------
    text : str
        Percentage, colon-separated ratio, or bare fraction.

    Returns
    -------
    float
        Ratio as a non-negative fraction.

    Raises
    ------
    ValueError
        If the text is empty, negative, or divides by zero.
    """
    cleaned = text.strip()
    if not cleaned:
        msg = "ratio must not be empty"
        raise ValueError(msg)
    if cleaned.endswith("%"):
        fraction = float(cleaned[:-1]) / PERCENT_SCALE
    elif ":" in cleaned:
        left, _, right = cleaned.partition(":")
        denominator = float(right)
        if not denominator:
            msg = "ratio denominator must not be zero"
            raise ValueError(msg)
        fraction = float(left) / denominator
    else:
        fraction = float(cleaned)
    if fraction < 0:
        msg = "ratio must not be negative"
        raise ValueError(msg)
    return fraction


def build_export_manifest(name: str, entries: list[str]) -> dict[str, object]:
    """Build the manifest describing one export bundle.

    Parameters
    ----------
    name : str
        Bundle name recorded in the manifest.
    entries : list[str]
        Relative paths included in the bundle.

    Returns
    -------
    dict[str, object]
        Manifest with the bundle name, sorted entries, and totals.
    """
    unique_entries = sorted(set(entries))
    manifest: dict[str, object] = {
        "bundle": name.strip(),
        "entries": unique_entries,
        "entry_count": len(unique_entries),
    }
    if len(unique_entries) != len(entries):
        manifest["deduplicated"] = True
    return manifest


def build_retention_policy(days: int, tiers: list[str]) -> dict[str, object]:
    """Build the retention policy for archived episodes.

    Parameters
    ----------
    days : int
        Retention window in days; non-positive means indefinite.
    tiers : list[str]
        Storage tiers the policy cascades through, cheapest last.

    Returns
    -------
    dict[str, object]
        Policy with the window, cascade order, and expiry flag.
    """
    cascade = [tier.strip().lower() for tier in tiers if tier.strip()]
    policy: dict[str, object] = {
        "window_days": max(days, 0),
        "cascade": cascade,
        "expires": days > 0,
    }
    if not cascade:
        policy["cascade"] = ["standard"]
    return policy


def longest_valid_streak(flags: list[bool]) -> int:
    """Measure the longest run of consecutive valid flags.

    Parameters
    ----------
    flags : list[bool]
        Validity flags in observation order.

    Returns
    -------
    int
        Length of the longest unbroken run of ``True`` values.
    """
    longest = 0
    current = 0
    for flag in flags:
        if flag:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def count_state_changes(states: list[str]) -> int:
    """Count how many times the observed state changes.

    Parameters
    ----------
    states : list[str]
        Observed states in observation order.

    Returns
    -------
    int
        Number of adjacent pairs with differing states.
    """
    changes = 0
    previous: str | None = None
    for state in states:
        if previous is not None and state != previous:
            changes += 1
        previous = state
    return changes
