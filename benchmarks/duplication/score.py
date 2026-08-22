"""Score normalized clone-detector findings against labelled pairs.

Detector-specific parsing lives in :mod:`benchmarks.duplication.parsers` and
the shared report-schema validation belongs to :mod:`benchmarks.score_support`.
This module owns only pair-specific matching and score accounting.
"""

from __future__ import annotations

import typing as typ

from .models import Expectation, Fragment, Lane, LaneScore, PairFinding
from .parsers import parse_pychase_pairs, parse_pyscn_pairs

if typ.TYPE_CHECKING:
    from collections import abc as cabc

__all__ = (
    "Expectation",
    "Fragment",
    "Lane",
    "LaneScore",
    "PairFinding",
    "parse_pychase_pairs",
    "parse_pyscn_pairs",
    "score_findings",
)

type _PairKey = tuple[tuple[str, int, int], tuple[str, int, int]]


class _MutableLaneCounts(typ.TypedDict):
    """Mutable score counters for one benchmark lane."""

    tp: int
    fp: int
    fn: int
    tn: int
    unmatched: int


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
