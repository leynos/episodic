"""Property tests for duplication-gate matching and normalization invariants."""

import itertools

from duplication_gate_test_support import gate
from hypothesis import given
from hypothesis import strategies as st

_UNIT_KEYS = st.sampled_from((
    "episodic/a.py::alpha",
    "episodic/b.py::beta",
    "episodic/c.py::gamma",
    "episodic/d.py::delta",
))


def _finding(first: str, second: str, score: float = 1.0) -> gate.Finding:
    """Build a finding with stable spans for matching properties."""
    return gate.Finding(
        first=first,
        second=second,
        location_first=f"{first.split('::')[0]}:1-20",
        location_second=f"{second.split('::')[0]}:30-50",
        score=score,
    )


@given(first=_UNIT_KEYS, second=_UNIT_KEYS)
def test_unit_allows_match_either_member(first: str, second: str) -> None:
    """A unit allow entry is invariant to finding member order."""
    entry = gate.AllowEntry(units=(first,), reason="property")
    assert entry.matches(first, second), (
        "Unit allows must match their first occurrence."
    )
    assert entry.matches(second, first), (
        "Unit allows must match their reversed occurrence."
    )


@given(
    first=_UNIT_KEYS,
    second=_UNIT_KEYS.filter(lambda value: value != "episodic/a.py::alpha"),
)
def test_pair_allows_match_only_their_unordered_members(
    first: str,
    second: str,
) -> None:
    """A pair allow matches both orders and no third member."""
    entry = gate.AllowEntry(units=(first, second), reason="property")
    assert entry.matches(first, second), "Pair allows must match their stored order."
    assert entry.matches(second, first), "Pair allows must match reversed order."
    if second != "episodic/a.py::alpha":
        assert not entry.matches(first, "episodic/a.py::alpha"), (
            "Pair allows must not match a different unordered pair."
        )


@st.composite
def _allow_entries(draw: st.DrawFn) -> list[gate.AllowEntry]:
    """Build valid unit and unordered-pair allow entries."""
    entries: list[gate.AllowEntry] = []
    for index in range(draw(st.integers(min_value=0, max_value=8))):
        units = draw(
            st.one_of(
                st.tuples(_UNIT_KEYS),
                st.lists(_UNIT_KEYS, min_size=2, max_size=2, unique=True).map(tuple),
            )
        )
        entries.append(gate.AllowEntry(units=units, reason=f"property-{index}"))
    return entries


@given(
    pairs=st.lists(
        st.lists(_UNIT_KEYS, min_size=2, max_size=2, unique=True).map(tuple),
        max_size=12,
    ),
    allowlist=_allow_entries(),
)
def test_partition_conserves_findings_and_identifies_stale_entries(
    pairs: list[tuple[str, str]],
    allowlist: list[gate.AllowEntry],
) -> None:
    """Every finding is exactly blocking or allowed and stale entries match none."""
    findings = list(itertools.starmap(_finding, pairs))
    blocking, allowed, stale = gate.partition_findings(findings, allowlist)

    assert len(blocking) + len(allowed) == len(findings), (
        "Partitioning must retain every reported finding exactly once."
    )
    assert all(
        any(entry.matches(finding.first, finding.second) for entry in allowlist)
        for finding in allowed
    ), "Allowed findings must have a matching allow entry."
    assert all(
        not any(entry.matches(finding.first, finding.second) for entry in allowlist)
        for finding in blocking
    ), "Blocking findings must have no matching allow entry."
    assert all(
        not any(entry.matches(finding.first, finding.second) for finding in findings)
        for entry in stale
    ), "Stale entries must not match any current finding."


@given(
    scores=st.lists(st.integers(min_value=0, max_value=100), min_size=1, max_size=12),
    locations=st.permutations(("episodic/a.py", "episodic/b.py", "episodic/c.py")),
)
def test_normalization_orders_scores_then_locations(
    scores: list[int],
    locations: tuple[str, ...],
) -> None:
    """Normalized findings use the documented deterministic ordering."""
    pairs: list[gate._DetectorPairPayload] = []
    location_cycle = itertools.cycle(locations)
    for index, score in enumerate(scores, start=1):
        left_path = next(location_cycle)
        right_path = next(location_cycle)
        pairs.append({
            "score": float(score),
            "left": {
                "file": left_path,
                "qualname": f"left_{index}",
                "start_line": index,
                "end_line": index + 1,
            },
            "right": {
                "file": right_path,
                "qualname": f"right_{index}",
                "start_line": index + 10,
                "end_line": index + 11,
            },
        })

    findings = gate.normalize_findings(pairs)
    sort_keys = [
        (-finding.score, finding.location_first, finding.location_second)
        for finding in findings
    ]
    assert sort_keys == sorted(sort_keys), (
        "Normalization must sort by descending score then source locations."
    )
