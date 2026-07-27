"""Normalize and score dead-code detector findings against labelled source."""

from __future__ import annotations

import dataclasses as dc
import enum
import typing as typ
from collections import abc as cabc
from pathlib import Path


class Lane(enum.StrEnum):
    """A distinct static-analysis meaning of dead code."""

    UNUSED_SYMBOL = "unused-symbol"
    UNREACHABLE_STATEMENT = "unreachable-statement"


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class Expectation:
    """A tool-neutral liveness label at one source location."""

    identifier: str
    path: str
    line: int
    lane: Lane
    is_dead: bool


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class Finding:
    """A normalized detector finding at one source location."""

    path: str
    line: int
    lane: Lane
    category: str


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class LaneScore:
    """A confusion matrix for one dead-code analysis lane."""

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    unmatched_findings: int


def _mapping(value: object, *, context: str) -> cabc.Mapping[str, object]:
    if not isinstance(value, cabc.Mapping):
        msg = f"{context} must be a JSON object"
        raise TypeError(msg)
    if not all(isinstance(key, str) for key in value):
        msg = f"{context} keys must be strings"
        raise TypeError(msg)
    return typ.cast("cabc.Mapping[str, object]", value)


def _sequence(value: object, *, context: str) -> cabc.Sequence[object]:
    if not isinstance(value, cabc.Sequence) or isinstance(value, (str, bytes)):
        msg = f"{context} must be a JSON array"
        raise TypeError(msg)
    return value


def _string(value: object, *, context: str) -> str:
    if not isinstance(value, str):
        msg = f"{context} must be a string"
        raise TypeError(msg)
    return value


def _positive_line(value: object, *, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"{context} must be a positive integer"
        raise TypeError(msg)
    if value < 1:
        msg = f"{context} must be positive"
        raise ValueError(msg)
    return value


def _relative_source_path(raw_path: object, corpus_root: Path) -> str:
    root = corpus_root.resolve()
    path = Path(_string(raw_path, context="finding path"))
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError as error:
        msg = f"finding path {path} is outside corpus root {root}"
        raise ValueError(msg) from error


def parse_pyscn_findings(
    payload: object,
    *,
    corpus_root: Path,
) -> tuple[Finding, ...]:
    """Extract pyscn control-flow findings from its unified JSON report."""
    root = _mapping(payload, context="pyscn payload")
    dead_code = _mapping(root.get("dead_code"), context="pyscn dead_code")
    files = _sequence(dead_code.get("files"), context="pyscn dead_code.files")
    findings: list[Finding] = []

    for file_index, raw_file in enumerate(files):
        file_payload = _mapping(raw_file, context=f"pyscn files[{file_index}]")
        functions = _sequence(
            file_payload.get("functions"),
            context=f"pyscn files[{file_index}].functions",
        )
        for function_index, raw_function in enumerate(functions):
            function = _mapping(
                raw_function,
                context=f"pyscn functions[{function_index}]",
            )
            raw_findings = _sequence(
                function.get("findings"),
                context=f"pyscn functions[{function_index}].findings",
            )
            for finding_index, raw_finding in enumerate(raw_findings):
                finding = _mapping(
                    raw_finding,
                    context=f"pyscn findings[{finding_index}]",
                )
                location = _mapping(
                    finding.get("location"),
                    context=f"pyscn findings[{finding_index}].location",
                )
                findings.append(
                    Finding(
                        path=_relative_source_path(
                            location.get("file_path"),
                            corpus_root,
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
                )

    return tuple(findings)


_SKYLOS_UNUSED_CATEGORIES = (
    "unused_functions",
    "unused_imports",
    "unused_classes",
    "unused_variables",
    "unused_parameters",
)


def parse_skylos_findings(
    payload: object,
    *,
    corpus_root: Path,
) -> tuple[Finding, ...]:
    """Extract Skylos findings from its unused-symbol result arrays."""
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
                    path=_relative_source_path(finding.get("file"), corpus_root),
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
    """Score unique finding locations without discarding unmatched reports."""
    expectations_by_location: dict[tuple[str, int], Expectation] = {}
    for expectation in expectations:
        location = (expectation.path, expectation.line)
        if location in expectations_by_location:
            msg = (
                f"duplicate expectation location: {expectation.path}:{expectation.line}"
            )
            raise ValueError(msg)
        expectations_by_location[location] = expectation

    counts = {
        lane: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "unmatched": 0} for lane in Lane
    }
    matched_expectations: set[str] = set()
    seen_finding_locations: set[tuple[str, int]] = set()

    for finding in findings:
        location = (finding.path, finding.line)
        if location in seen_finding_locations:
            continue
        seen_finding_locations.add(location)
        expectation = expectations_by_location.get(location)
        if expectation is None:
            counts[finding.lane]["unmatched"] += 1
            continue

        matched_expectations.add(expectation.identifier)
        key = "tp" if expectation.is_dead else "fp"
        counts[expectation.lane][key] += 1

    for expectation in expectations:
        if expectation.identifier in matched_expectations:
            continue
        key = "fn" if expectation.is_dead else "tn"
        counts[expectation.lane][key] += 1

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
