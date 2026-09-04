"""Test the duplication benchmark parser and scorer contracts.

Parser contract tests verify report-shape validation, path normalization,
and finding order for the pyscn and PyChase result schemas; the nose family
parser is covered in :mod:`tests.test_duplication_benchmark_nose`. Scorer
contract tests verify lane attribution, pair deduplication, overlap matching,
and expectation classification so benchmark results remain comparable across
detector runs.
"""

import re
import typing as typ

import pytest

from benchmarks.duplication.score import (
    Expectation,
    Fragment,
    Lane,
    PairFinding,
    parse_pyscn_pairs,
    score_findings,
)

if typ.TYPE_CHECKING:
    from pathlib import Path


def _fragment(path: str = "a.py", start: int = 1, end: int = 20) -> Fragment:
    """Return one test fragment spanning the supplied source lines."""
    return Fragment(path=path, start_line=start, end_line=end)


def _expectation(
    identifier: str = "pair",
    *,
    lane: Lane = Lane.SYNTACTIC_CLONE,
    is_clone: bool = True,
    members: tuple[Fragment, Fragment] | None = None,
) -> Expectation:
    """Return one labelled test expectation with two fragments."""
    first, second = members or (_fragment("a.py", 1, 20), _fragment("b.py", 1, 20))
    return Expectation(
        identifier=identifier,
        lane=lane,
        is_clone=is_clone,
        first=first,
        second=second,
    )


def _finding(
    first: Fragment | None = None,
    second: Fragment | None = None,
    *,
    lane: Lane = Lane.SYNTACTIC_CLONE,
) -> PairFinding:
    """Return one normalized test detector finding."""
    return PairFinding(
        first=first or _fragment("a.py", 1, 20),
        second=second or _fragment("b.py", 1, 20),
        lane=lane,
        category="candidate",
        similarity=1.0,
    )


class TestParsePyscnPairs:
    """pyscn clone-pair report parsing."""

    def test_parses_locations_types_and_similarity(self, tmp_path: Path) -> None:
        """Members, clone types, and similarity survive normalization."""
        payload = {
            "clone": {
                "clone_pairs": [
                    {
                        "type": 4,
                        "similarity": 0.75,
                        "clone1": {
                            "location": {
                                "file_path": "pkg/a.py",
                                "start_line": 4,
                                "end_line": 12,
                            }
                        },
                        "clone2": {
                            "location": {
                                "file_path": str(tmp_path / "pkg" / "b.py"),
                                "start_line": 15,
                                "end_line": 23,
                            }
                        },
                    }
                ]
            }
        }
        findings = parse_pyscn_pairs(payload, corpus_root=tmp_path)
        assert findings[0].first == _fragment("pkg/a.py", 4, 12), "first member"
        assert findings[0].second == _fragment("pkg/b.py", 15, 23), "second member"
        assert findings[0].lane is Lane.SEMANTIC_CLONE, "type 4 lane"
        assert findings[0].category == "type-4", "category label"
        assert findings[0].similarity == 0.75, "similarity value"

    def test_null_pair_array_is_empty_report(self, tmp_path: Path) -> None:
        """Null pair arrays parse as empty pyscn reports."""
        payload = {"clone": {"clone_pairs": None}}
        assert parse_pyscn_pairs(payload, corpus_root=tmp_path) == (), (
            "null clone_pairs must parse as an empty report"
        )

    def test_syntactic_lane_for_types_one_to_three(self, tmp_path: Path) -> None:
        """Types 1-3 normalize into the syntactic lane."""
        payload = {
            "clone": {
                "clone_pairs": [
                    {
                        "type": clone_type,
                        "similarity": 0.9,
                        "clone1": {
                            "location": {
                                "file_path": "a.py",
                                "start_line": 1,
                                "end_line": 9,
                            }
                        },
                        "clone2": {
                            "location": {
                                "file_path": "b.py",
                                "start_line": 1,
                                "end_line": 9,
                            }
                        },
                    }
                    for clone_type in (1, 2, 3)
                ]
            }
        }
        findings = parse_pyscn_pairs(payload, corpus_root=tmp_path)
        assert all(f.lane is Lane.SYNTACTIC_CLONE for f in findings), (
            "types 1-3 must use the syntactic lane"
        )

    @pytest.mark.parametrize(
        ("payload", "expected_error", "diagnostic"),
        [
            ([], TypeError, "pyscn payload must be a JSON object"),
            ({"clone": []}, TypeError, "pyscn clone must be a JSON object"),
            (
                {"clone": {"clone_pairs": [{"type": "x"}]}},
                TypeError,
                "pyscn clone_pairs[0] type must be an integer",
            ),
            (
                {
                    "clone": {
                        "clone_pairs": [
                            {
                                "type": 1,
                                "similarity": 1.5,
                                "clone1": {
                                    "location": {
                                        "file_path": "a.py",
                                        "start_line": 1,
                                        "end_line": 2,
                                    }
                                },
                                "clone2": {
                                    "location": {
                                        "file_path": "b.py",
                                        "start_line": 1,
                                        "end_line": 2,
                                    }
                                },
                            }
                        ]
                    }
                },
                ValueError,
                "pyscn clone_pairs[0] similarity must be between 0.0 and 1.0",
            ),
        ],
        ids=["root-not-object", "clone-not-object", "type-not-int", "similarity-range"],
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
            parse_pyscn_pairs(payload, corpus_root=tmp_path)

    def test_rejects_paths_outside_corpus_root(self, tmp_path: Path) -> None:
        """Absolute paths outside the corpus root are configuration errors."""
        payload = {
            "clone": {
                "clone_pairs": [
                    {
                        "type": 1,
                        "similarity": 1.0,
                        "clone1": {
                            "location": {
                                "file_path": "/somewhere/else.py",
                                "start_line": 1,
                                "end_line": 2,
                            }
                        },
                        "clone2": {
                            "location": {
                                "file_path": "b.py",
                                "start_line": 1,
                                "end_line": 2,
                            }
                        },
                    }
                ]
            }
        }
        with pytest.raises(ValueError, match="outside corpus root"):
            parse_pyscn_pairs(payload, corpus_root=tmp_path)


class TestScoreFindings:
    """Scoring semantics over labelled pairs."""

    def test_clone_pair_reported_is_true_positive(self) -> None:
        """Reported clone labels count as lane true positives."""
        scores = score_findings([_expectation()], [_finding()])
        assert scores[Lane.SYNTACTIC_CLONE].true_positives == 1, "one true positive"
        assert scores[Lane.SYNTACTIC_CLONE].unmatched_findings == 0, "no unmatched"

    def test_control_pair_reported_is_false_positive(self) -> None:
        """Reported non-clone labels count as lane false positives."""
        scores = score_findings(
            [_expectation(is_clone=False)],
            [_finding()],
        )
        assert scores[Lane.SYNTACTIC_CLONE].false_positives == 1, "one false positive"

    def test_unreported_labels_split_by_liveness(self) -> None:
        """Unreported labels are false negatives or true negatives."""
        scores = score_findings(
            [
                _expectation("clone", is_clone=True),
                _expectation(
                    "control",
                    is_clone=False,
                    members=(_fragment("c.py", 1, 20), _fragment("d.py", 1, 20)),
                ),
            ],
            [],
        )
        assert scores[Lane.SYNTACTIC_CLONE].false_negatives == 1, "missed clone"
        assert scores[Lane.SYNTACTIC_CLONE].true_negatives == 1, "quiet control"

    def test_swapped_member_order_still_matches(self) -> None:
        """Finding member order does not affect matching."""
        finding = _finding(
            first=_fragment("b.py", 5, 15),
            second=_fragment("a.py", 5, 15),
        )
        scores = score_findings([_expectation()], [finding])
        assert scores[Lane.SYNTACTIC_CLONE].true_positives == 1, "swapped order match"

    def test_duplicate_pairs_count_once(self) -> None:
        """Identical reported pairs are deduplicated before scoring."""
        scores = score_findings(
            [_expectation()],
            [_finding(), _finding()],
        )
        assert scores[Lane.SYNTACTIC_CLONE].true_positives == 1, "deduplicated pair"

    def test_second_overlapping_pair_does_not_double_count(self) -> None:
        """A second distinct pair matching the same label is ignored."""
        nested = _finding(
            first=_fragment("a.py", 3, 18),
            second=_fragment("b.py", 3, 18),
        )
        scores = score_findings([_expectation()], [_finding(), nested])
        assert scores[Lane.SYNTACTIC_CLONE].true_positives == 1, "single credit"
        assert scores[Lane.SYNTACTIC_CLONE].unmatched_findings == 0, "no unmatched"

    def test_unmatched_findings_use_finding_lane(self) -> None:
        """Pairs without labels count against the reporting lane."""
        stray = _finding(
            first=_fragment("x.py", 1, 9),
            second=_fragment("y.py", 1, 9),
            lane=Lane.SEMANTIC_CLONE,
        )
        scores = score_findings([_expectation()], [stray])
        assert scores[Lane.SEMANTIC_CLONE].unmatched_findings == 1, "stray in own lane"
        assert scores[Lane.SYNTACTIC_CLONE].false_negatives == 1, "label unmet"

    def test_matched_findings_use_expectation_lane(self) -> None:
        """Matched pairs score in the label's lane, not the finding's."""
        semantic_label = _expectation("semantic", lane=Lane.SEMANTIC_CLONE)
        scores = score_findings([semantic_label], [_finding()])
        assert scores[Lane.SEMANTIC_CLONE].true_positives == 1, "label lane credited"
        assert scores[Lane.SYNTACTIC_CLONE].true_positives == 0, "finding lane not"

    def test_rejects_duplicate_expectation_identifiers(self) -> None:
        """Ambiguous labels are configuration errors."""
        with pytest.raises(ValueError, match="duplicate expectation"):
            score_findings(
                [
                    _expectation("same"),
                    _expectation(
                        "same",
                        members=(_fragment("c.py", 1, 5), _fragment("d.py", 1, 5)),
                    ),
                ],
                [],
            )

    def test_rejects_duplicate_expectation_pairs(self) -> None:
        """Two labels naming the same unordered pair are rejected."""
        with pytest.raises(ValueError, match="duplicate expectation"):
            score_findings(
                [
                    _expectation("one"),
                    _expectation(
                        "two",
                        members=(_fragment("b.py", 1, 20), _fragment("a.py", 1, 20)),
                    ),
                ],
                [],
            )
