"""Test PyChase report parsing for the duplication benchmark."""

import re
import typing as typ

import pytest

from benchmarks.duplication.score import Fragment, Lane, parse_pychase_pairs

if typ.TYPE_CHECKING:
    from pathlib import Path


def _fragment(path: str, start_line: int, end_line: int) -> Fragment:
    """Return a normalized PyChase test fragment."""
    return Fragment(path=path, start_line=start_line, end_line=end_line)


class TestParsePychasePairs:
    """PyChase candidate report parsing."""

    def test_parses_candidates_in_report_order(self, tmp_path: Path) -> None:
        """Candidates normalize into syntactic-lane findings."""
        payload = {
            "candidates": [
                {
                    "score": 0.925,
                    "left": {
                        "file": "pkg/a.py",
                        "start_line": 4,
                        "end_line": 12,
                        "qualname": "alpha",
                    },
                    "right": {
                        "file": "pkg/b.py",
                        "start_line": 15,
                        "end_line": 23,
                        "qualname": "beta",
                    },
                }
            ]
        }
        findings = parse_pychase_pairs(payload, corpus_root=tmp_path)
        assert findings[0].first == _fragment("pkg/a.py", 4, 12), "left member"
        assert findings[0].second == _fragment("pkg/b.py", 15, 23), "right member"
        assert findings[0].lane is Lane.SYNTACTIC_CLONE, "candidate lane"
        assert findings[0].similarity == 0.925, "candidate score"

    @pytest.mark.parametrize(
        ("payload", "expected_error", "diagnostic"),
        [
            ([], TypeError, "PyChase payload must be a JSON object"),
            (
                {
                    "candidates": [
                        {
                            "score": "high",
                            "left": {
                                "file": "a.py",
                                "start_line": 1,
                                "end_line": 2,
                            },
                            "right": {
                                "file": "b.py",
                                "start_line": 1,
                                "end_line": 2,
                            },
                        }
                    ]
                },
                TypeError,
                "PyChase candidates[0] score must be a number",
            ),
            (
                {
                    "candidates": [
                        {
                            "score": 1.0,
                            "left": {"file": "a.py", "start_line": 0, "end_line": 2},
                            "right": {"file": "b.py", "start_line": 1, "end_line": 2},
                        }
                    ]
                },
                ValueError,
                "PyChase candidates[0].left start_line must be positive",
            ),
        ],
        ids=["root-not-object", "score-not-number", "line-not-positive"],
    )
    def test_rejects_malformed_reports(
        self,
        tmp_path: Path,
        payload: object,
        expected_error: type[Exception],
        diagnostic: str,
    ) -> None:
        """Shape violations raise instead of silently dropping findings."""
        with pytest.raises(expected_error, match=re.escape(diagnostic)):
            parse_pychase_pairs(payload, corpus_root=tmp_path)
