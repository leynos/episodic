"""Tool-neutral data shapes for the duplication benchmark.

The models give detector reports and the labelled corpus one stable vocabulary
for source spans, clone lanes, findings, and confusion-matrix scores. Parsers
construct these values before the benchmark scorer compares detector output
with its expectations.
"""

import dataclasses as dc
import enum


class Lane(enum.StrEnum):
    """A distinct static-analysis meaning of duplicated code.

    Attributes
    ----------
    SYNTACTIC_CLONE : str
        A clone detected from structural or textual similarity.
    SEMANTIC_CLONE : str
        A clone detected from equivalent behaviour despite different syntax.
    """

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

    Notes
    -----
    Paths are relative to the benchmark corpus. Parsers validate line
    positivity and ordering before constructing a fragment.
    """

    path: str
    start_line: int
    end_line: int

    def overlaps(self, other: Fragment) -> bool:
        """Report whether this fragment shares a source line with ``other``.

        Parameters
        ----------
        other : Fragment
            The source span to compare with this fragment.

        Returns
        -------
        bool
            ``True`` when both spans are in the same file and their inclusive
            line ranges intersect; otherwise ``False``.
        """
        return (
            self.path == other.path
            and self.start_line <= other.end_line
            and other.start_line <= self.end_line
        )


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class Expectation:
    """One labelled clone or non-clone pair in the benchmark corpus.

    Parameters
    ----------
    identifier : str
        Stable label for the pair in the benchmark oracle.
    lane : Lane
        Analysis lane in which the pair is scored.
    is_clone : bool
        Whether the pair is expected to be reported as a clone.
    first, second : Fragment
        The two source spans that make up the pair.
    """

    identifier: str
    lane: Lane
    is_clone: bool
    first: Fragment
    second: Fragment


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class PairFinding:
    """One detector-reported duplicate pair in benchmark-neutral form.

    Parameters
    ----------
    first, second : Fragment
        The two source spans reported by a detector.
    lane : Lane
        Benchmark lane used to compare the finding with expectations.
    category : str
        Detector-specific clone category retained for reporting.
    similarity : float
        Normalized detector similarity score in the inclusive range [0, 1].
    """

    first: Fragment
    second: Fragment
    lane: Lane
    category: str
    similarity: float


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class LaneScore:
    """Confusion-matrix totals for one benchmark lane.

    Parameters
    ----------
    true_positives, false_positives : int
        Expected clone pairs correctly reported and unexpected pairs reported.
    false_negatives, true_negatives : int
        Expected clone pairs missed and non-clone pairs correctly omitted.
    unmatched_findings : int
        Findings that could not be matched to an oracle expectation.

    Notes
    -----
    The scorer creates one instance per :class:`Lane` and uses the counters to
    derive precision and recall in its benchmark report.
    """

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    unmatched_findings: int
