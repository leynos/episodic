"""Unit tests for dead-code benchmark result normalization."""

from pathlib import Path

from benchmarks.dead_code.score import (
    Expectation,
    Finding,
    Lane,
    parse_pyscn_findings,
    parse_skylos_findings,
    score_findings,
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
                                        "file_path": "/corpus/flow.py",
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
    )


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

    assert findings == (
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


def test_score_findings_counts_misses_and_unmatched_reports_by_lane() -> None:
    """Preserve false negatives and unmatched false positives in scores."""
    expectations = (
        Expectation(
            identifier="dead-unused",
            path="symbols.py",
            line=2,
            lane=Lane.UNUSED_SYMBOL,
            is_dead=True,
        ),
        Expectation(
            identifier="live-unused",
            path="symbols.py",
            line=5,
            lane=Lane.UNUSED_SYMBOL,
            is_dead=False,
        ),
        Expectation(
            identifier="missed-unreachable",
            path="flow.py",
            line=7,
            lane=Lane.UNREACHABLE_STATEMENT,
            is_dead=True,
        ),
        Expectation(
            identifier="live-flow",
            path="flow.py",
            line=12,
            lane=Lane.UNREACHABLE_STATEMENT,
            is_dead=False,
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
            line=5,
            lane=Lane.UNUSED_SYMBOL,
            category="unused_variables",
        ),
        Finding(
            path="other.py",
            line=20,
            lane=Lane.UNUSED_SYMBOL,
            category="unused_classes",
        ),
    )

    scores = score_findings(expectations, findings)

    assert scores[Lane.UNUSED_SYMBOL].true_positives == 1
    assert scores[Lane.UNUSED_SYMBOL].false_positives == 2
    assert scores[Lane.UNUSED_SYMBOL].false_negatives == 0
    assert scores[Lane.UNUSED_SYMBOL].true_negatives == 0
    assert scores[Lane.UNREACHABLE_STATEMENT].true_positives == 0
    assert scores[Lane.UNREACHABLE_STATEMENT].false_positives == 0
    assert scores[Lane.UNREACHABLE_STATEMENT].false_negatives == 1
    assert scores[Lane.UNREACHABLE_STATEMENT].true_negatives == 1
