"""Test the nose family-report parser contract.

The nose detector reports duplication families rather than pairs, so its
parser contract covers family-to-pair expansion and witness-to-lane mapping in
addition to the report-shape validation and path normalization shared with the
other duplication benchmark parsers.
"""

import typing as typ

import pytest

from benchmarks.duplication.score import Fragment, Lane, parse_nose_pairs

if typ.TYPE_CHECKING:
    from pathlib import Path


def _fragment(path: str, start: int, end: int) -> Fragment:
    """Return one test fragment spanning the supplied source lines."""
    return Fragment(path=path, start_line=start, end_line=end)


def _nose_family(
    *,
    witness: str = "copy-paste",
    mean_score: float = 1.0,
    locations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Return one nose report family with the supplied members."""
    return {
        "witness": witness,
        "metrics": {"mean_score": mean_score},
        "locations": locations
        or [
            {"file": "pkg/a.py", "start": 4, "end": 12},
            {"file": "pkg/b.py", "start": 15, "end": 23},
        ],
    }


class TestParseNosePairs:
    """nose family report parsing."""

    def test_parses_family_members_and_similarity(self, tmp_path: Path) -> None:
        """Members, witness category, and mean score survive normalization."""
        payload = {"families": [_nose_family(mean_score=0.925)]}
        findings = parse_nose_pairs(payload, corpus_root=tmp_path)
        assert findings[0].first == _fragment("pkg/a.py", 4, 12), "first member"
        assert findings[0].second == _fragment("pkg/b.py", 15, 23), "second member"
        assert findings[0].lane is Lane.SYNTACTIC_CLONE, "copy-paste lane"
        assert findings[0].category == "copy-paste", "witness category"
        assert findings[0].similarity == 0.925, "mean score"

    def test_expands_multi_member_family_into_unordered_pairs(
        self, tmp_path: Path
    ) -> None:
        """A three-member family yields every unordered member pair."""
        payload = {
            "families": [
                _nose_family(
                    locations=[
                        {"file": "a.py", "start": 1, "end": 9},
                        {"file": "b.py", "start": 1, "end": 9},
                        {"file": "c.py", "start": 1, "end": 9},
                    ]
                )
            ]
        }
        findings = parse_nose_pairs(payload, corpus_root=tmp_path)
        pairs = {(finding.first.path, finding.second.path) for finding in findings}
        assert pairs == {("a.py", "b.py"), ("a.py", "c.py"), ("b.py", "c.py")}, (
            "three members must expand to three unordered pairs"
        )

    def test_exact_witness_maps_to_semantic_lane(self, tmp_path: Path) -> None:
        """The exact semantic witness normalizes into the semantic lane."""
        payload = {"families": [_nose_family(witness="exact")]}
        findings = parse_nose_pairs(payload, corpus_root=tmp_path)
        assert findings[0].lane is Lane.SEMANTIC_CLONE, "exact witness lane"

    @pytest.mark.parametrize(
        "witness",
        ["copy-paste", "subdag", "similar"],
    )
    def test_non_exact_witnesses_map_to_syntactic_lane(
        self, tmp_path: Path, witness: str
    ) -> None:
        """Syntax and near-channel witnesses normalize into the syntactic lane."""
        payload = {"families": [_nose_family(witness=witness)]}
        findings = parse_nose_pairs(payload, corpus_root=tmp_path)
        assert findings[0].lane is Lane.SYNTACTIC_CLONE, f"{witness} lane"

    @pytest.mark.parametrize(
        ("payload", "expected_error"),
        [
            ([], TypeError),
            ({"families": {}}, TypeError),
            (
                {
                    "families": [
                        {
                            "witness": 7,
                            "metrics": {"mean_score": 1.0},
                            "locations": [
                                {"file": "a.py", "start": 1, "end": 9},
                                {"file": "b.py", "start": 1, "end": 9},
                            ],
                        }
                    ]
                },
                TypeError,
            ),
            ({"families": [_nose_family(mean_score=1.5)]}, ValueError),
            (
                {
                    "families": [
                        _nose_family(locations=[{"file": "a.py", "start": 1, "end": 9}])
                    ]
                },
                ValueError,
            ),
            (
                {
                    "families": [
                        _nose_family(
                            locations=[
                                {"file": "a.py", "start": 9, "end": 1},
                                {"file": "b.py", "start": 1, "end": 9},
                            ]
                        )
                    ]
                },
                ValueError,
            ),
        ],
        ids=[
            "root-not-object",
            "families-not-array",
            "witness-not-string",
            "mean-score-range",
            "single-location-family",
            "inverted-span",
        ],
    )
    def test_rejects_malformed_reports(
        self, tmp_path: Path, payload: object, expected_error: type[Exception]
    ) -> None:
        """Shape violations raise instead of silently dropping findings."""
        with pytest.raises(expected_error):
            parse_nose_pairs(payload, corpus_root=tmp_path)

    def test_rejects_paths_outside_corpus_root(self, tmp_path: Path) -> None:
        """Absolute paths outside the corpus root are configuration errors."""
        payload = {
            "families": [
                _nose_family(
                    locations=[
                        {"file": "/somewhere/else.py", "start": 1, "end": 9},
                        {"file": "b.py", "start": 1, "end": 9},
                    ]
                )
            ]
        }
        with pytest.raises(ValueError, match="outside corpus root"):
            parse_nose_pairs(payload, corpus_root=tmp_path)
