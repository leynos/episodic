"""Normalize and score clone-detector findings against labelled pairs.

Overview
--------
The public parsers normalize the distinct JSON reports emitted by pyscn and
PyChase into the benchmark's tool-neutral pair findings.

Scoring
-------
The scorer compares normalized pair findings with labelled expectations,
preserving lane-specific confusion counts and reporting unique unmatched
pairs.

Benchmark contract
------------------
Public data shapes, finding order, source locations, validation behaviour,
and scoring semantics are stable inputs to the benchmark evidence.
"""

import dataclasses as dc
import enum
import typing as typ
from collections import abc as cabc
from pathlib import Path


class Lane(enum.StrEnum):
    """A distinct static-analysis meaning of duplicated code."""

    SYNTACTIC_CLONE = "syntactic-clone"
    SEMANTIC_CLONE = "semantic-clone"


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class Fragment:
    """A contiguous source span reported or labelled as one clone member.

    Attributes
    ----------
    path : str
        Corpus-relative source path containing the fragment.
    start_line : int
        One-based first source line of the fragment.
    end_line : int
        One-based last source line of the fragment.
    """

    path: str
    start_line: int
    end_line: int

    def overlaps(self, other: Fragment) -> bool:
        """Report whether two fragments share at least one source line.

        Parameters
        ----------
        other : Fragment
            Fragment to compare against.

        Returns
        -------
        bool
            ``True`` when both fragments name the same path and their line
            ranges intersect.
        """
        return (
            self.path == other.path
            and self.start_line <= other.end_line
            and other.start_line <= self.end_line
        )


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class Expectation:
    """A tool-neutral duplication label for one pair of source units.

    Attributes
    ----------
    identifier : str
        Stable identifier for the labelled pair.
    lane : Lane
        Static-analysis lane used to score the pair.
    is_clone : bool
        Whether the labelled pair is expected to be reported as a clone.
    first : Fragment
        First labelled unit of the pair.
    second : Fragment
        Second labelled unit of the pair.
    """

    identifier: str
    lane: Lane
    is_clone: bool
    first: Fragment
    second: Fragment


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class PairFinding:
    """A normalized detector report naming two similar fragments.

    Attributes
    ----------
    first : Fragment
        First reported fragment.
    second : Fragment
        Second reported fragment.
    lane : Lane
        Static-analysis lane represented by the finding.
    category : str
        Detector-specific clone classification for the finding.
    similarity : float
        Detector-reported similarity between the fragments.
    """

    first: Fragment
    second: Fragment
    lane: Lane
    category: str
    similarity: float


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class LaneScore:
    """A confusion matrix for one duplication analysis lane.

    Attributes
    ----------
    true_positives : int
        Clone pairs correctly reported by the detector.
    false_positives : int
        Non-clone pairs incorrectly reported by the detector.
    false_negatives : int
        Clone pairs not reported by the detector.
    true_negatives : int
        Non-clone pairs not reported by the detector.
    unmatched_findings : int
        Unique detector pairs without a labelled expectation.
    """

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    unmatched_findings: int


def _mapping(value: object, *, context: str) -> cabc.Mapping[str, object]:
    """Validate and return a string-keyed mapping."""
    if not isinstance(value, cabc.Mapping):
        msg = f"{context} must be a JSON object"
        raise TypeError(msg)
    if not all(isinstance(key, str) for key in value):
        msg = f"{context} keys must be strings"
        raise TypeError(msg)
    return typ.cast("cabc.Mapping[str, object]", value)


def _sequence(value: object, *, context: str) -> cabc.Sequence[object]:
    """Validate and return a non-string sequence, treating null as empty.

    pyscn serializes empty Go slices as JSON ``null``, so an absent or null
    array is an empty report rather than a malformed one.

    Returns
    -------
    collections.abc.Sequence[object]
        The validated sequence, or an empty tuple for a null value.

    Raises
    ------
    TypeError
        If the value is neither null nor a JSON array.
    """
    if value is None:
        return ()
    if not isinstance(value, cabc.Sequence) or isinstance(value, (str, bytes)):
        msg = f"{context} must be a JSON array"
        raise TypeError(msg)
    return value


def _string(value: object, *, context: str) -> str:
    """Validate and return a string value."""
    if not isinstance(value, str):
        msg = f"{context} must be a string"
        raise TypeError(msg)
    return value


def _positive_line(value: object, *, context: str) -> int:
    """Validate and return a positive, non-boolean line number."""
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"{context} must be a positive integer"
        raise TypeError(msg)
    if value < 1:
        msg = f"{context} must be positive"
        raise ValueError(msg)
    return value


def _similarity(value: object, *, context: str) -> float:
    """Validate and return a similarity score between zero and one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"{context} must be a number"
        raise TypeError(msg)
    score = float(value)
    if not 0.0 <= score <= 1.0:
        msg = f"{context} must be between 0.0 and 1.0"
        raise ValueError(msg)
    return score


def _relative_source_path(raw_path: object, corpus_root: Path) -> str:
    """Normalize a fragment path relative to the corpus root."""
    root = corpus_root.resolve()
    path = Path(_string(raw_path, context="fragment path"))
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError as error:
        msg = f"fragment path {path} is outside corpus root {root}"
        raise ValueError(msg) from error


def _fragment(
    payload: cabc.Mapping[str, object],
    *,
    path_key: str,
    context: str,
    corpus_root: Path,
) -> Fragment:
    """Normalize one reported fragment location."""
    return Fragment(
        path=_relative_source_path(payload.get(path_key), corpus_root),
        start_line=_positive_line(
            payload.get("start_line"),
            context=f"{context} start_line",
        ),
        end_line=_positive_line(
            payload.get("end_line"),
            context=f"{context} end_line",
        ),
    )


_PYSCN_SEMANTIC_CLONE_TYPE = 4


def parse_pyscn_pairs(
    payload: object,
    *,
    corpus_root: Path,
) -> tuple[PairFinding, ...]:
    """Extract pyscn clone pairs from its unified JSON report.

    Parameters
    ----------
    payload : object
        Parsed pyscn JSON report payload.
    corpus_root : pathlib.Path
        Root directory used to normalize reported source paths.

    Returns
    -------
    tuple[PairFinding, ...]
        Normalized clone pairs in report order.
    """
    root = _mapping(payload, context="pyscn payload")
    clone = _mapping(root.get("clone"), context="pyscn clone")
    pairs = _sequence(clone.get("clone_pairs"), context="pyscn clone.clone_pairs")
    return tuple(
        _parse_pyscn_pair(raw_pair, pair_index=index, corpus_root=corpus_root)
        for index, raw_pair in enumerate(pairs)
    )


def _parse_pyscn_pair(
    raw_pair: object,
    *,
    pair_index: int,
    corpus_root: Path,
) -> PairFinding:
    """Normalize one validated pyscn clone pair."""
    context = f"pyscn clone_pairs[{pair_index}]"
    pair = _mapping(raw_pair, context=context)
    clone_type = pair.get("type")
    if not isinstance(clone_type, int) or isinstance(clone_type, bool):
        msg = f"{context} type must be an integer"
        raise TypeError(msg)
    members = [
        _fragment(
            _mapping(
                _mapping(
                    pair.get(member_key),
                    context=f"{context}.{member_key}",
                ).get("location"),
                context=f"{context}.{member_key}.location",
            ),
            path_key="file_path",
            context=f"{context}.{member_key}.location",
            corpus_root=corpus_root,
        )
        for member_key in ("clone1", "clone2")
    ]
    lane = (
        Lane.SEMANTIC_CLONE
        if clone_type == _PYSCN_SEMANTIC_CLONE_TYPE
        else Lane.SYNTACTIC_CLONE
    )
    return PairFinding(
        first=members[0],
        second=members[1],
        lane=lane,
        category=f"type-{clone_type}",
        similarity=_similarity(
            pair.get("similarity"),
            context=f"{context} similarity",
        ),
    )


def parse_pychase_pairs(
    payload: object,
    *,
    corpus_root: Path,
) -> tuple[PairFinding, ...]:
    """Extract PyChase candidate pairs from its JSON report.

    Parameters
    ----------
    payload : object
        Parsed PyChase JSON report payload.
    corpus_root : pathlib.Path
        Root directory used to normalize reported source paths.

    Returns
    -------
    tuple[PairFinding, ...]
        Normalized candidate pairs in report order.
    """
    root = _mapping(payload, context="PyChase payload")
    candidates = _sequence(root.get("candidates"), context="PyChase candidates")
    return tuple(
        _parse_pychase_candidate(
            raw_candidate,
            candidate_index=index,
            corpus_root=corpus_root,
        )
        for index, raw_candidate in enumerate(candidates)
    )


def _parse_pychase_candidate(
    raw_candidate: object,
    *,
    candidate_index: int,
    corpus_root: Path,
) -> PairFinding:
    """Normalize one validated PyChase candidate pair."""
    context = f"PyChase candidates[{candidate_index}]"
    candidate = _mapping(raw_candidate, context=context)
    members = [
        _fragment(
            _mapping(candidate.get(member_key), context=f"{context}.{member_key}"),
            path_key="file",
            context=f"{context}.{member_key}",
            corpus_root=corpus_root,
        )
        for member_key in ("left", "right")
    ]
    return PairFinding(
        first=members[0],
        second=members[1],
        lane=Lane.SYNTACTIC_CLONE,
        category="candidate",
        similarity=_similarity(candidate.get("score"), context=f"{context} score"),
    )


type _PairKey = tuple[tuple[str, int, int], tuple[str, int, int]]
type _MutableLaneCounts = dict[str, int]
type _LaneCounts = dict[Lane, _MutableLaneCounts]


def _finding_key(finding: PairFinding) -> _PairKey:
    """Build an unordered location key identifying one reported pair."""
    members = sorted(
        (
            (fragment.path, fragment.start_line, fragment.end_line)
            for fragment in (finding.first, finding.second)
        ),
    )
    return (members[0], members[1])


def _match_expectation(
    finding: PairFinding,
    expectations: cabc.Sequence[Expectation],
) -> Expectation | None:
    """Return the labelled pair whose units the finding overlaps, if any."""
    for expectation in expectations:
        direct = finding.first.overlaps(expectation.first) and finding.second.overlaps(
            expectation.second
        )
        swapped = finding.first.overlaps(
            expectation.second
        ) and finding.second.overlaps(expectation.first)
        if direct or swapped:
            return expectation
    return None


def score_findings(
    expectations: cabc.Sequence[Expectation],
    findings: cabc.Sequence[PairFinding],
) -> cabc.Mapping[Lane, LaneScore]:
    """Score unique reported pairs without discarding unmatched reports.

    Parameters
    ----------
    expectations : collections.abc.Sequence[Expectation]
        Tool-neutral duplication labels used as the scoring reference.
    findings : collections.abc.Sequence[PairFinding]
        Normalized detector reports to compare with the labels.

    Returns
    -------
    collections.abc.Mapping[Lane, LaneScore]
        Confusion-matrix scores and unmatched report counts for every lane.
    """
    _reject_duplicate_expectations(expectations)
    counts: _LaneCounts = {
        lane: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "unmatched": 0} for lane in Lane
    }
    matched_identifiers = _score_unique_findings(
        findings,
        expectations=expectations,
        counts=counts,
    )
    for expectation in expectations:
        if expectation.identifier in matched_identifiers:
            continue
        count_key = "fn" if expectation.is_clone else "tn"
        counts[expectation.lane][count_key] += 1
    return {
        lane: LaneScore(
            true_positives=values["tp"],
            false_positives=values["fp"],
            false_negatives=values["fn"],
            true_negatives=values["tn"],
            unmatched_findings=values["unmatched"],
        )
        for lane, values in counts.items()
    }


def _reject_duplicate_expectations(
    expectations: cabc.Sequence[Expectation],
) -> None:
    """Reject ambiguous benchmark labels sharing an identifier or pair."""
    identifiers: set[str] = set()
    pairs: set[_PairKey] = set()
    for expectation in expectations:
        members = sorted(
            (
                (fragment.path, fragment.start_line, fragment.end_line)
                for fragment in (expectation.first, expectation.second)
            ),
        )
        pair_key = (members[0], members[1])
        if expectation.identifier in identifiers or pair_key in pairs:
            msg = f"duplicate expectation: {expectation.identifier}"
            raise ValueError(msg)
        identifiers.add(expectation.identifier)
        pairs.add(pair_key)


def _score_unique_findings(
    findings: cabc.Sequence[PairFinding],
    *,
    expectations: cabc.Sequence[Expectation],
    counts: _LaneCounts,
) -> set[str]:
    """Account for one report per pair and return matched label identifiers."""
    matched_identifiers: set[str] = set()
    seen_pairs: set[_PairKey] = set()
    for finding in findings:
        key = _finding_key(finding)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        expectation = _match_expectation(finding, expectations)
        if expectation is None:
            counts[finding.lane]["unmatched"] += 1
            continue
        if expectation.identifier in matched_identifiers:
            continue
        count_key = "tp" if expectation.is_clone else "fp"
        counts[expectation.lane][count_key] += 1
        matched_identifiers.add(expectation.identifier)
    return matched_identifiers
