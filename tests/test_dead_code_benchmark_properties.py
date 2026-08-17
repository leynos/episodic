"""Property tests for repository-owned dead-code benchmark contracts.

Generated scorer cases exercise stable scoring invariants. Parser cases cover
only this project's JSON-shape validation; retained detector reports remain
integration evidence rather than an oracle for third-party detector behaviour.
"""

from pathlib import Path

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from benchmarks.dead_code.score import (
    Expectation,
    Finding,
    Lane,
    LaneScore,
    parse_pyscn_findings,
    parse_skylos_findings,
    score_findings,
)

_LANES = tuple(Lane)
_CATEGORIES = ("unused_functions", "unreachable_after_return")
_SKYLOS_RESULT_CATEGORIES = (
    "unused_functions",
    "unused_imports",
    "unused_classes",
    "unused_variables",
    "unused_parameters",
)
_NON_OBJECT_JSON_VALUES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.text(),
    st.lists(st.integers(), max_size=4),
)
_NON_ARRAY_JSON_VALUES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.text(),
    st.dictionaries(st.text(max_size=8), st.integers(), max_size=4),
)
_LABELLED_FINDING_RECORDS = st.lists(
    st.tuples(
        st.sampled_from(_LANES),
        st.booleans(),
        st.sampled_from(_LANES),
    ),
    min_size=1,
    max_size=8,
)


def _labelled_findings(
    records: list[tuple[Lane, bool, Lane]],
) -> tuple[tuple[Expectation, ...], tuple[Finding, ...]]:
    """Build unique labelled locations and their reported findings."""
    expectations = tuple(
        Expectation(
            identifier=f"expectation-{index}",
            path=f"generated/{index}.py",
            line=index + 1,
            lane=expectation_lane,
            is_dead=is_dead,
        )
        for index, (expectation_lane, is_dead, _) in enumerate(records)
    )
    findings = tuple(
        Finding(
            path=f"generated/{index}.py",
            line=index + 1,
            lane=reported_lane,
            category=_CATEGORIES[index % len(_CATEGORIES)],
        )
        for index, (_, _, reported_lane) in enumerate(records)
    )
    return expectations, findings


@st.composite
def _permuted_score_cases(
    draw: st.DrawFn,
) -> tuple[
    tuple[Expectation, ...],
    tuple[Finding, ...],
    tuple[Expectation, ...],
    tuple[Finding, ...],
]:
    """Generate a unique scoring case and independent input permutations."""
    expectations, findings = _labelled_findings(draw(_LABELLED_FINDING_RECORDS))
    return (
        expectations,
        findings,
        tuple(draw(st.permutations(expectations))),
        tuple(draw(st.permutations(findings))),
    )


@st.composite
def _duplicate_location_cases(
    draw: st.DrawFn,
) -> tuple[tuple[Expectation, ...], tuple[Finding, ...]]:
    """Generate one finding followed by reports at its same location."""
    expectation_lane = draw(st.sampled_from(_LANES))
    expectation = Expectation(
        identifier="labelled-location",
        path="generated/duplicate.py",
        line=1,
        lane=expectation_lane,
        is_dead=draw(st.booleans()),
    )
    first_finding = Finding(
        path=expectation.path,
        line=expectation.line,
        lane=draw(st.sampled_from(_LANES)),
        category=draw(st.sampled_from(_CATEGORIES)),
    )
    duplicates = tuple(
        Finding(
            path=expectation.path,
            line=expectation.line,
            lane=draw(st.sampled_from(_LANES)),
            category=draw(st.sampled_from(_CATEGORIES)),
        )
        for _ in range(draw(st.integers(min_value=1, max_value=8)))
    )
    return (expectation,), (first_finding, *duplicates)


@st.composite
def _conservation_cases(
    draw: st.DrawFn,
) -> tuple[tuple[Expectation, ...], tuple[Finding, ...]]:
    """Generate unique matched and unmatched reports for score conservation."""
    records = draw(
        st.lists(
            st.tuples(
                st.sampled_from(_LANES),
                st.booleans(),
                st.sampled_from(_LANES),
                st.booleans(),
            ),
            max_size=8,
        ),
    )
    expectations = tuple(
        Expectation(
            identifier=f"expectation-{index}",
            path=f"generated/{index}.py",
            line=index + 1,
            lane=expectation_lane,
            is_dead=is_dead,
        )
        for index, (expectation_lane, is_dead, _, _) in enumerate(records)
    )
    findings = [
        Finding(
            path=f"generated/{index}.py",
            line=index + 1,
            lane=reported_lane,
            category=_CATEGORIES[index % len(_CATEGORIES)],
        )
        for index, (_, _, reported_lane, is_reported) in enumerate(records)
        if is_reported
    ]
    unmatched_lanes = draw(st.lists(st.sampled_from(_LANES), max_size=8))
    findings.extend(
        Finding(
            path=f"unmatched/{index}.py",
            line=index + 1,
            lane=lane,
            category=_CATEGORIES[index % len(_CATEGORIES)],
        )
        for index, lane in enumerate(unmatched_lanes)
    )
    return expectations, tuple(findings)


def _expectation_outcomes(scores: dict[Lane, LaneScore]) -> int:
    """Count labelled expectations represented by the score matrix."""
    return sum(
        score.true_positives
        + score.false_positives
        + score.false_negatives
        + score.true_negatives
        for score in scores.values()
    )


def _reported_locations(scores: dict[Lane, LaneScore]) -> int:
    """Count unique reports represented by matched and unmatched score buckets."""
    return sum(
        score.true_positives + score.false_positives + score.unmatched_findings
        for score in scores.values()
    )


@given(case=_permuted_score_cases())
@settings(max_examples=100)
def test_score_findings_is_invariant_under_unique_input_permutations(
    case: tuple[
        tuple[Expectation, ...],
        tuple[Finding, ...],
        tuple[Expectation, ...],
        tuple[Finding, ...],
    ],
) -> None:
    """Permuting uniquely located labels and reports must not change scores."""
    expectations, findings, permuted_expectations, permuted_findings = case

    original = score_findings(expectations, findings)
    permuted = score_findings(permuted_expectations, permuted_findings)

    assert original == permuted, (
        "Expected unique input permutations to preserve scores."
    )


@given(case=_duplicate_location_cases())
@settings(max_examples=100)
def test_score_findings_ignores_later_reports_at_a_seen_location(
    case: tuple[tuple[Expectation, ...], tuple[Finding, ...]],
) -> None:
    """Only the first report at a source location may affect the score matrix."""
    expectations, findings = case

    first_report_scores = score_findings(expectations, findings[:1])
    duplicate_report_scores = score_findings(expectations, findings)

    assert first_report_scores == duplicate_report_scores, (
        "Expected duplicate source locations to be ignored after their first report."
    )


@given(
    expectation_lane=st.sampled_from(_LANES),
    is_dead=st.booleans(),
    unmatched_lane=st.sampled_from(_LANES),
)
@settings(max_examples=100)
def test_score_findings_attributes_matched_and_unmatched_reports_to_contract_lanes(
    expectation_lane: Lane,
    unmatched_lane: Lane,
    *,
    is_dead: bool,
) -> None:
    """Matched labels and unmatched reports must use their respective lanes."""
    reported_lane = (
        Lane.UNUSED_SYMBOL
        if expectation_lane is Lane.UNREACHABLE_STATEMENT
        else Lane.UNREACHABLE_STATEMENT
    )
    expectation = Expectation(
        identifier="labelled",
        path="generated/labelled.py",
        line=1,
        lane=expectation_lane,
        is_dead=is_dead,
    )
    findings = (
        Finding(
            path=expectation.path,
            line=expectation.line,
            lane=reported_lane,
            category="generated",
        ),
        Finding(
            path="generated/unmatched.py",
            line=1,
            lane=unmatched_lane,
            category="generated",
        ),
    )

    scores = score_findings((expectation,), findings)
    labelled_score = scores[expectation_lane]

    assert labelled_score.true_positives == int(is_dead), (
        "Expected a dead matched label to be counted in its expectation lane."
    )
    assert labelled_score.false_positives == int(not is_dead), (
        "Expected a live matched label to be counted in its expectation lane."
    )
    assert scores[reported_lane].true_positives == 0, (
        "Expected a report's lane not to override its matched expectation lane."
    )
    assert scores[reported_lane].false_positives == 0, (
        "Expected a report's lane not to override its matched expectation lane."
    )
    assert scores[unmatched_lane].unmatched_findings == 1, (
        "Expected an unmatched report to be counted in its reported lane."
    )


@given(case=_conservation_cases())
@settings(max_examples=100)
def test_score_findings_conserves_labels_and_unique_reports(
    case: tuple[tuple[Expectation, ...], tuple[Finding, ...]],
) -> None:
    """Every label and unique report must occupy exactly one score bucket."""
    expectations, findings = case

    scores = dict(score_findings(expectations, findings))

    assert _expectation_outcomes(scores) == len(expectations), (
        "Expected every label to be represented by one confusion-matrix outcome."
    )
    assert _reported_locations(scores) == len(findings), (
        "Expected every unique report to be matched or recorded as unmatched."
    )


@given(payload=_NON_OBJECT_JSON_VALUES)
@settings(max_examples=100)
def test_parse_pyscn_findings_rejects_non_object_payloads(payload: object) -> None:
    """The pyscn normalizer requires a JSON-object root payload."""
    with pytest.raises(TypeError, match="pyscn payload must be a JSON object"):
        parse_pyscn_findings(payload, corpus_root=Path("/corpus"))


@given(payload=_NON_ARRAY_JSON_VALUES)
@settings(max_examples=100)
def test_parse_pyscn_findings_rejects_non_array_file_groups(payload: object) -> None:
    """The pyscn normalizer requires a JSON array for reported files."""
    malformed_payload: object = {"dead_code": {"files": payload}}

    with pytest.raises(
        TypeError,
        match=r"pyscn dead_code\.files must be a JSON array",
    ):
        parse_pyscn_findings(malformed_payload, corpus_root=Path("/corpus"))


@given(
    category=st.sampled_from(_SKYLOS_RESULT_CATEGORIES),
    payload=_NON_ARRAY_JSON_VALUES,
)
@settings(max_examples=100)
def test_parse_skylos_findings_rejects_non_array_category_payloads(
    category: str,
    payload: object,
) -> None:
    """The Skylos normalizer requires JSON arrays for all result categories."""
    malformed_payload: dict[str, object] = {
        result_category: [] for result_category in _SKYLOS_RESULT_CATEGORIES
    }
    malformed_payload[category] = payload

    with pytest.raises(
        TypeError,
        match=f"Skylos {category} must be a JSON array",
    ):
        parse_skylos_findings(malformed_payload, corpus_root=Path("/corpus"))
