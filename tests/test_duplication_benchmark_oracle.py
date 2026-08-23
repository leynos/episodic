"""Integrity checks for the checked-in duplication benchmark oracle."""

import json
from pathlib import Path

from benchmarks.duplication.score import Expectation, Fragment, Lane, score_findings

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = REPO_ROOT / "benchmarks" / "duplication"


def test_expectations_load_and_reference_real_units() -> None:
    """Every labelled unit names an existing corpus source span."""
    raw = json.loads((BENCHMARK_ROOT / "expectations.json").read_text(encoding="utf-8"))
    expectations = [
        Expectation(
            identifier=entry["identifier"],
            lane=Lane(entry["lane"]),
            is_clone=entry["is_clone"],
            first=Fragment(
                path=entry["first"]["path"],
                start_line=entry["first"]["start_line"],
                end_line=entry["first"]["end_line"],
            ),
            second=Fragment(
                path=entry["second"]["path"],
                start_line=entry["second"]["start_line"],
                end_line=entry["second"]["end_line"],
            ),
        )
        for entry in raw
    ]
    score_findings(expectations, [])
    for expectation in expectations:
        for member in (expectation.first, expectation.second):
            source = BENCHMARK_ROOT / "corpus" / member.path
            assert member.start_line >= 1, f"{member.path} span must start at one"
            assert member.start_line <= member.end_line, (
                f"{member.path} span must not be inverted"
            )
            line_count = len(source.read_text(encoding="utf-8").splitlines())
            assert member.end_line <= line_count, (
                f"{member.path} span exceeds file length"
            )
