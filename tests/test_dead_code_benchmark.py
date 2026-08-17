"""Unit tests for dead-code benchmark result normalization."""

import re
from pathlib import Path

import pytest

from benchmarks.dead_code.score import (
    Expectation,
    Finding,
    Lane,
    parse_pyscn_findings,
    parse_skylos_findings,
    score_findings,
)


@pytest.fixture
def mixed_lane_expectations() -> tuple[Expectation, ...]:
    """Provide one dead flow label and one live symbol label."""
    return (
        Expectation(
            identifier="dead-flow",
            path="flow.py",
            line=7,
            lane=Lane.UNREACHABLE_STATEMENT,
            is_dead=True,
        ),
        Expectation(
            identifier="live-symbol",
            path="symbols.py",
            line=2,
            lane=Lane.UNUSED_SYMBOL,
            is_dead=False,
        ),
    )


def test_parse_pyscn_findings_uses_control_flow_locations() -> None:
    """Extract pyscn findings from the nested dead-code report."""
    payload: object = {
        "dead_code": {
            "files": [
                {
                    "functions": [
                        {
                            "findings": [
                                {
                                    "location": {
                                        "file_path": "flow.py",
                                        "start_line": 7,
                                    },
                                    "reason": "unreachable_after_return",
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }

    findings = parse_pyscn_findings(payload, corpus_root=Path("/corpus"))

    assert findings == (
        Finding(
            path="flow.py",
            line=7,
            lane=Lane.UNREACHABLE_STATEMENT,
            category="unreachable_after_return",
        ),
    ), "Expected pyscn findings to retain normalized control-flow locations."


def test_parse_skylos_findings_uses_unused_symbol_categories() -> None:
    """Extract each supported Skylos unused-symbol category."""
    payload: object = {
        "unused_functions": [
            {"file": "/corpus/symbols.py", "line": 2, "type": "function"}
        ],
        "unused_imports": [{"file": "/corpus/symbols.py", "line": 5, "type": "import"}],
        "unused_classes": [],
        "unused_variables": [],
        "unused_parameters": [],
    }

    findings = parse_skylos_findings(payload, corpus_root=Path("/corpus"))

    expected_findings = (
        Finding(
            path="symbols.py",
            line=2,
            lane=Lane.UNUSED_SYMBOL,
            category="unused_functions",
        ),
        Finding(
            path="symbols.py",
            line=5,
            lane=Lane.UNUSED_SYMBOL,
            category="unused_imports",
        ),
    )
    assert findings == expected_findings, (
        "Expected Skylos findings to retain normalized category order."
    )


def test_score_findings_deduplicates_locations_across_lanes_and_categories() -> None:
    """Score only the first report for each source location."""
    expectations = (
        Expectation(
            identifier="dead-unused",
            path="symbols.py",
            line=2,
            lane=Lane.UNUSED_SYMBOL,
            is_dead=True,
        ),
    )
    findings = (
        Finding(
            path="symbols.py",
            line=2,
            lane=Lane.UNUSED_SYMBOL,
            category="unused_functions",
        ),
        Finding(
            path="symbols.py",
            line=2,
            lane=Lane.UNREACHABLE_STATEMENT,
            category="unreachable_after_return",
        ),
    )

    scores = score_findings(expectations, findings)

    assert scores[Lane.UNUSED_SYMBOL].true_positives == 1, (
        "Expected duplicate locations to count once as a true positive."
    )
    assert scores[Lane.UNREACHABLE_STATEMENT].unmatched_findings == 0, (
        "Expected the duplicate cross-lane report to be suppressed."
    )


def test_score_findings_counts_unmatched_findings_in_the_finding_lane() -> None:
    """Keep unlabelled reports separate from expectation outcomes."""
    finding = Finding(
        path="flow.py",
        line=7,
        lane=Lane.UNREACHABLE_STATEMENT,
        category="unreachable_after_return",
    )

    scores = score_findings((), (finding,))

    assert scores[Lane.UNREACHABLE_STATEMENT].unmatched_findings == 1, (
        "Expected an unmatched finding to count in its reported lane."
    )
    assert scores[Lane.UNUSED_SYMBOL].unmatched_findings == 0, (
        "Expected other lanes to remain unchanged by an unmatched finding."
    )


def test_score_findings_classifies_dead_and_live_matched_expectations(
    mixed_lane_expectations: tuple[Expectation, ...],
) -> None:
    """Use expectation labels and lanes for matched reports."""
    findings = (
        Finding(
            path="flow.py",
            line=7,
            lane=Lane.UNUSED_SYMBOL,
            category="unused_variables",
        ),
        Finding(
            path="symbols.py",
            line=2,
            lane=Lane.UNREACHABLE_STATEMENT,
            category="unreachable_after_return",
        ),
    )

    scores = score_findings(mixed_lane_expectations, findings)

    assert scores[Lane.UNREACHABLE_STATEMENT].true_positives == 1, (
        "Expected the dead matched expectation to be a true positive."
    )
    assert scores[Lane.UNUSED_SYMBOL].false_positives == 1, (
        "Expected the live matched expectation to be a false positive."
    )
    assert scores[Lane.UNUSED_SYMBOL].true_positives == 0, (
        "Expected the reported lane not to override the expectation lane."
    )
    assert scores[Lane.UNREACHABLE_STATEMENT].false_positives == 0, (
        "Expected no false positive in the dead expectation lane."
    )


def test_score_findings_classifies_dead_and_live_unmatched_expectations(
    mixed_lane_expectations: tuple[Expectation, ...],
) -> None:
    """Use expectation labels and lanes when no report is present."""
    scores = score_findings(mixed_lane_expectations, ())

    assert scores[Lane.UNREACHABLE_STATEMENT].false_negatives == 1, (
        "Expected the unmatched dead expectation to be a false negative."
    )
    assert scores[Lane.UNUSED_SYMBOL].true_negatives == 1, (
        "Expected the unmatched live expectation to be a true negative."
    )


def test_score_findings_rejects_duplicate_expectation_locations() -> None:
    """Reject labels that would make source-location scoring ambiguous."""
    expectations = (
        Expectation(
            identifier="first",
            path="symbols.py",
            line=2,
            lane=Lane.UNUSED_SYMBOL,
            is_dead=True,
        ),
        Expectation(
            identifier="second",
            path="symbols.py",
            line=2,
            lane=Lane.UNREACHABLE_STATEMENT,
            is_dead=False,
        ),
    )

    with pytest.raises(
        ValueError, match=re.escape("duplicate expectation location: symbols.py:2")
    ):
        score_findings(expectations, ())
