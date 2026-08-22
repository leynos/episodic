"""Tool-neutral data shapes for the duplication benchmark."""

import dataclasses as dc
import enum


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
        """Report whether this fragment shares a source line with ``other``."""
        return (
            self.path == other.path
            and self.start_line <= other.end_line
            and other.start_line <= self.end_line
        )


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class Expectation:
    """One labelled clone or non-clone pair in the benchmark corpus."""

    identifier: str
    lane: Lane
    is_clone: bool
    first: Fragment
    second: Fragment


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class PairFinding:
    """One detector-reported duplicate pair in benchmark-neutral form."""

    first: Fragment
    second: Fragment
    lane: Lane
    category: str
    similarity: float


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class LaneScore:
    """Confusion-matrix totals for one benchmark lane."""

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    unmatched_findings: int
