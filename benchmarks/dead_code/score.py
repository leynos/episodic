"""Normalize and score dead-code detector findings against labelled source.

Overview
--------
The public parsers normalize the distinct JSON reports emitted by pyscn and
Skylos into the benchmark's tool-neutral findings.

Scoring
-------
The scorer compares normalized findings with labelled expectations, preserving
lane-specific confusion counts and reporting unique unmatched findings.

Utility
-------
Validation and path-normalization helpers keep parser errors consistent while
ensuring that findings remain relative to the corpus root.

Benchmark consumers
-------------------
The benchmark tests, score-generation script, and retained result reports use
these public parsers and scorer to compare detector runs.

Benchmark contract
------------------
Public data shapes, finding order, source locations, validation behaviour, and
scoring semantics are stable inputs to the benchmark evidence.
"""

from __future__ import annotations

import dataclasses as dc
import enum
import typing as typ

from benchmarks.score_support import (
    mapping as _mapping,
)

if typ.TYPE_CHECKING:
    from collections import abc as cabc
    from pathlib import Path
from benchmarks.score_support import (
    positive_line as _positive_line,
)
from benchmarks.score_support import (
    relative_source_path,
)
from benchmarks.score_support import (
    sequence as _sequence,
)
from benchmarks.score_support import (
    string as _string,
)


class Lane(enum.StrEnum):
    """A distinct static-analysis meaning of dead code."""

    UNUSED_SYMBOL = "unused-symbol"
    UNREACHABLE_STATEMENT = "unreachable-statement"


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class Expectation:
    """A tool-neutral liveness label at one source location.

    Attributes
    ----------
    identifier : str
        Stable identifier for the labelled expectation.
    path : str
        Corpus-relative source path containing the expectation.
    line : int
        One-based source line for the expectation.
    lane : Lane
        Static-analysis lane used to score the expectation.
    is_dead : bool
        Whether the labelled source is expected to be dead.
    """

    identifier: str
    path: str
    line: int
    lane: Lane
    is_dead: bool


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class Finding:
    """A normalized detector finding at one source location.

    Attributes
    ----------
    path : str
        Corpus-relative source path reported by the detector.
    line : int
        One-based source line reported by the detector.
    lane : Lane
        Static-analysis lane represented by the finding.
    category : str
        Detector-specific category or reason for the finding.
    """

    path: str
    line: int
    lane: Lane
    category: str


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class LaneScore:
    """A confusion matrix for one dead-code analysis lane.

    Attributes
    ----------
    true_positives : int
        Dead expectations correctly reported by the detector.
    false_positives : int
        Live expectations incorrectly reported by the detector.
    false_negatives : int
        Dead expectations not reported by the detector.
    true_negatives : int
        Live expectations not reported by the detector.
    unmatched_findings : int
        Unique detector findings without a labelled expectation.
    """

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    unmatched_findings: int


def parse_pyscn_findings(
    payload: object,
    *,
    corpus_root: Path,
) -> tuple[Finding, ...]:
    """Extract pyscn control-flow findings from its unified JSON report.

    Parameters
    ----------
    payload : object
        Parsed pyscn JSON report payload.
    corpus_root : pathlib.Path
        Root directory used to normalize reported source paths.

    Returns
    -------
    tuple[Finding, ...]
        Normalized control-flow findings in report order.
    """
    root = _mapping(payload, context="pyscn payload")
    dead_code = _mapping(root.get("dead_code"), context="pyscn dead_code")
    files = _sequence(dead_code.get("files"), context="pyscn dead_code.files")
    return tuple(
        _parse_pyscn_finding(
            raw_finding,
            finding_index=finding_index,
            corpus_root=corpus_root,
        )
        for finding_index, raw_finding in _iter_pyscn_findings_from_files(files)
    )


def _iter_pyscn_findings_from_files(
    files: cabc.Sequence[object],
) -> cabc.Iterator[tuple[int, object]]:
    """Yield raw pyscn findings in report order after validating traversal nodes."""
    for file_index, raw_file in enumerate(files):
        file_payload = _mapping(raw_file, context=f"pyscn files[{file_index}]")
        functions = _sequence(
            file_payload.get("functions"),
            context=f"pyscn files[{file_index}].functions",
        )
        yield from _iter_pyscn_findings_from_functions(functions)


def _iter_pyscn_findings_from_functions(
    functions: cabc.Sequence[object],
) -> cabc.Iterator[tuple[int, object]]:
    """Yield findings from each validated pyscn function payload."""
    for function_index, raw_function in enumerate(functions):
        function = _mapping(
            raw_function,
            context=f"pyscn functions[{function_index}]",
        )
        raw_findings = _sequence(
            function.get("findings"),
            context=f"pyscn functions[{function_index}].findings",
        )
        yield from enumerate(raw_findings)


def _parse_pyscn_finding(
    raw_finding: object,
    *,
    finding_index: int,
    corpus_root: Path,
) -> Finding:
    """Normalize one validated pyscn finding while retaining its error context."""
    finding = _mapping(raw_finding, context=f"pyscn findings[{finding_index}]")
    location = _mapping(
        finding.get("location"),
        context=f"pyscn findings[{finding_index}].location",
    )
    return Finding(
        path=relative_source_path(
            location.get("file_path"),
            corpus_root,
            subject="finding",
        ),
        line=_positive_line(
            location.get("start_line"),
            context="pyscn finding start_line",
        ),
        lane=Lane.UNREACHABLE_STATEMENT,
        category=_string(
            finding.get("reason"),
            context="pyscn finding reason",
        ),
    )


_SKYLOS_UNUSED_CATEGORIES = (
    "unused_functions",
    "unused_imports",
    "unused_classes",
    "unused_variables",
    "unused_parameters",
)


type Location = tuple[str, int]
type MutableLaneCounts = dict[str, int]
type LaneCounts = dict[Lane, MutableLaneCounts]


def parse_skylos_findings(
    payload: object,
    *,
    corpus_root: Path,
) -> tuple[Finding, ...]:
    """Extract Skylos findings from its unused-symbol result arrays.

    Parameters
    ----------
    payload : object
        Parsed Skylos JSON report payload.
    corpus_root : pathlib.Path
        Root directory used to normalize reported source paths.

    Returns
    -------
    tuple[Finding, ...]
        Normalized unused-symbol findings in category and report order.
    """
    root = _mapping(payload, context="Skylos payload")
    findings: list[Finding] = []

    for category in _SKYLOS_UNUSED_CATEGORIES:
        raw_findings = _sequence(root.get(category), context=f"Skylos {category}")
        for finding_index, raw_finding in enumerate(raw_findings):
            finding = _mapping(
                raw_finding,
                context=f"Skylos {category}[{finding_index}]",
            )
            findings.append(
                Finding(
                    path=relative_source_path(
                        finding.get("file"),
                        corpus_root,
                        subject="finding",
                    ),
                    line=_positive_line(
                        finding.get("line"),
                        context=f"Skylos {category} line",
                    ),
                    lane=Lane.UNUSED_SYMBOL,
                    category=category,
                )
            )

    return tuple(findings)


def score_findings(
    expectations: cabc.Sequence[Expectation],
    findings: cabc.Sequence[Finding],
) -> cabc.Mapping[Lane, LaneScore]:
    """Score unique finding locations without discarding unmatched reports.

    Parameters
    ----------
    expectations : collections.abc.Sequence[Expectation]
        Tool-neutral liveness labels used as the scoring reference.
    findings : collections.abc.Sequence[Finding]
        Normalized detector reports to compare with the labels.

    Returns
    -------
    collections.abc.Mapping[Lane, LaneScore]
        Confusion-matrix scores and unmatched report counts for every lane.
    """
    expectations_by_location = _index_expectations(expectations)
    counts: LaneCounts = {
        lane: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "unmatched": 0} for lane in Lane
    }
    matched_expectation_identifiers = _score_unique_findings(
        findings,
        expectations_by_location=expectations_by_location,
        counts=counts,
    )
    _score_unmatched_expectations(
        expectations,
        matched_expectation_identifiers=matched_expectation_identifiers,
        counts=counts,
    )
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


def _index_expectations(
    expectations: cabc.Sequence[Expectation],
) -> dict[tuple[str, int], Expectation]:
    """Index labels by location and reject ambiguous benchmark expectations."""
    expectations_by_location: dict[Location, Expectation] = {}
    for expectation in expectations:
        location = (expectation.path, expectation.line)
        if location in expectations_by_location:
            msg = (
                f"duplicate expectation location: {expectation.path}:{expectation.line}"
            )
            raise ValueError(msg)
        expectations_by_location[location] = expectation
    return expectations_by_location


def _score_unique_findings(
    findings: cabc.Sequence[Finding],
    *,
    expectations_by_location: cabc.Mapping[Location, Expectation],
    counts: LaneCounts,
) -> set[str]:
    """Account for one report per location and return matched label identifiers."""
    matched_expectation_identifiers: set[str] = set()
    seen_locations: set[Location] = set()
    for finding in findings:
        location = (finding.path, finding.line)
        if location in seen_locations:
            continue
        seen_locations.add(location)
        expectation = expectations_by_location.get(location)
        if expectation is None:
            counts[finding.lane]["unmatched"] += 1
            continue
        count_key = "tp" if expectation.is_dead else "fp"
        counts[expectation.lane][count_key] += 1
        matched_expectation_identifiers.add(expectation.identifier)
    return matched_expectation_identifiers


def _score_unmatched_expectations(
    expectations: cabc.Sequence[Expectation],
    *,
    matched_expectation_identifiers: cabc.Set[str],
    counts: LaneCounts,
) -> None:
    """Record false negatives and true negatives for labels without a report."""
    for expectation in expectations:
        if expectation.identifier in matched_expectation_identifiers:
            continue
        count_key = "fn" if expectation.is_dead else "tn"
        counts[expectation.lane][count_key] += 1
