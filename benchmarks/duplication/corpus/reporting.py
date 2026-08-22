# Benchmark source locations are intentionally stable.
"""Clones of the pricing module used as labelled true positives."""


def order_total_price_copy(items: list[dict[str, float]]) -> float:
    """Sum taxable order lines into a rounded total for a report.

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
    # Type-1 clone: statements match pricing.order_total_price exactly.
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


def latest_alert_titles(
    records: list[dict[str, object]],
    maximum: int,
) -> list[str]:
    """Collect the newest alert titles up to a maximum.

    Parameters
    ----------
    records : list[dict[str, object]]
        Alert records ordered from newest to oldest.
    maximum : int
        Maximum number of titles to collect.

    Returns
    -------
    list[str]
        Non-empty titles from error-level alerts.
    """
    # Type-2 clone: identifiers renamed from pricing.recent_error_messages.
    if maximum <= 0:
        return []
    titles: list[str] = []
    for record in records:
        if record.get("level") != "error":
            continue
        label = str(record.get("message", ""))
        if not label:
            continue
        titles.append(label)
        if len(titles) >= maximum:
            break
    return titles


def summarize_throughput(readings: list[float]) -> dict[str, float]:
    """Summarize throughput readings with bounds, a mean, and a count.

    Parameters
    ----------
    readings : list[float]
        Observed throughput readings per interval.

    Returns
    -------
    dict[str, float]
        Mapping with ``minimum``, ``maximum``, ``mean``, and ``count``
        entries.
    """
    # Type-3 clone: pricing.summarize_latencies with small modifications.
    if not readings:
        return {"minimum": 0.0, "maximum": 0.0, "mean": 0.0, "count": 0.0}
    minimum = readings[0]
    maximum = readings[0]
    total = 0.0
    for reading in readings:
        if reading < minimum:  # noqa: PLR1730 - retain the copied bounds-tracking fixture.
            minimum = reading
        if reading > maximum:  # noqa: PLR1730 - retain the copied bounds-tracking fixture.
            maximum = reading
        total += reading
    count = float(len(readings))
    return {
        "minimum": minimum,
        "maximum": maximum,
        "mean": total / count,
        "count": count,
    }


def mean_weighted_rating(entries: list[dict[str, float]]) -> float:
    """Average valid entry ratings weighted by their sample size.

    Parameters
    ----------
    entries : list[dict[str, float]]
        Entries with ``score``, optional ``weight``, and a ``valid`` marker.

    Returns
    -------
    float
        Weighted mean rating, or zero when no entry is valid.
    """
    # Type-4 clone: pricing.weighted_average_score via comprehensions.
    weights = [entry.get("weight", 1.0) for entry in entries if entry.get("valid")]
    weighted = [
        entry["score"] * entry.get("weight", 1.0)
        for entry in entries
        if entry.get("valid")
    ]
    if not weights:
        return 0.0
    return sum(weighted) / sum(weights)


class InvoiceExporter:
    """Export invoices after structural validation."""

    def validate(  # noqa: PLR6301 - the method-clone fixture requires instance methods.
        self, document: dict[str, object]
    ) -> list[str]:
        """Return the validation problems for an invoice document.

        Parameters
        ----------
        document : dict[str, object]
            Candidate invoice document.

        Returns
        -------
        list[str]
            Human-readable validation problems; empty when valid.
        """
        # Type-2 method clone of pricing.OrderExporter.validate.
        faults: list[str] = []
        for field in ("identifier", "customer", "total"):
            if field not in document:
                faults.append(f"missing field: {field}")  # noqa: PERF401 - retain the copied guard-loop fixture.
        raw_amount = document.get("total")
        if isinstance(raw_amount, int | float) and raw_amount < 0:
            faults.append("total must not be negative")
        if not document.get("lines"):
            faults.append("at least one line is required")
        return faults
