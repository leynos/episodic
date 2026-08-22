# Benchmark source locations are intentionally stable.
"""Original routines that the reporting module clones for comparison."""


def order_total_price(items: list[dict[str, float]]) -> float:
    """Sum taxable order lines into a rounded total.

    Parameters
    ----------
    items : list[dict[str, float]]
        Order lines with ``price``, ``quantity``, and optional ``taxable``
        and ``discount`` entries.

    Returns
    -------
    float
        Rounded, non-negative order total.
    """
    total = 0.0
    for item in items:
        line_price = item["price"] * item["quantity"]
        if item.get("taxable"):
            line_price *= 1.2
        if item.get("discount"):
            line_price -= item["discount"]
        total += line_price
    if total < 0:
        total = 0.0
    return round(total, 2)


def recent_error_messages(
    events: list[dict[str, object]],
    limit: int,
) -> list[str]:
    """Collect the newest error messages up to a limit.

    Parameters
    ----------
    events : list[dict[str, object]]
        Event records ordered from newest to oldest.
    limit : int
        Maximum number of messages to collect.

    Returns
    -------
    list[str]
        Non-empty messages from error-level events.
    """
    if limit <= 0:
        return []
    messages: list[str] = []
    for event in events:
        if event.get("level") != "error":
            continue
        text = str(event.get("message", ""))
        if not text:
            continue
        messages.append(text)
        if len(messages) >= limit:
            break
    return messages


def summarize_latencies(samples: list[float]) -> dict[str, float]:
    """Summarize latency samples with bounds and a mean.

    Parameters
    ----------
    samples : list[float]
        Observed latency samples in milliseconds.

    Returns
    -------
    dict[str, float]
        Mapping with ``minimum``, ``maximum``, and ``mean`` entries.
    """
    if not samples:
        return {"minimum": 0.0, "maximum": 0.0, "mean": 0.0}
    minimum = samples[0]
    maximum = samples[0]
    total = 0.0
    for sample in samples:
        if sample < minimum:  # noqa: PLR1730 - retain the copied bounds-tracking fixture.
            minimum = sample
        if sample > maximum:  # noqa: PLR1730 - retain the copied bounds-tracking fixture.
            maximum = sample
        total += sample
    return {"minimum": minimum, "maximum": maximum, "mean": total / len(samples)}


def weighted_average_score(rows: list[dict[str, float]]) -> float:
    """Average valid row scores weighted by their sample size.

    Parameters
    ----------
    rows : list[dict[str, float]]
        Rows with ``score``, optional ``weight``, and a ``valid`` marker.

    Returns
    -------
    float
        Weighted mean score, or zero when no row is valid.
    """
    weighted_total = 0.0
    weight_sum = 0.0
    for row in rows:
        if not row.get("valid"):
            continue
        weight = row.get("weight", 1.0)
        weighted_total += row["score"] * weight
        weight_sum += weight
    if weight_sum == 0.0:
        return 0.0
    return weighted_total / weight_sum


class OrderExporter:
    """Export orders after structural validation."""

    def validate(  # noqa: PLR6301 - the method-clone fixture requires instance methods.
        self, payload: dict[str, object]
    ) -> list[str]:
        """Return the validation problems for an order payload.

        Parameters
        ----------
        payload : dict[str, object]
            Candidate order payload.

        Returns
        -------
        list[str]
            Human-readable validation problems; empty when valid.
        """
        problems: list[str] = []
        for field in ("identifier", "customer", "total"):
            if field not in payload:
                problems.append(f"missing field: {field}")  # noqa: PERF401 - retain the copied guard-loop fixture.
        raw_total = payload.get("total")
        if isinstance(raw_total, int | float) and raw_total < 0:
            problems.append("total must not be negative")
        if not payload.get("lines"):
            problems.append("at least one line is required")
        return problems
