"""Normalize PyChase, pyscn, and nose reports for duplication scoring.

The public parser functions accept decoded detector JSON and a corpus root.
They validate each report's shape, normalize source locations, and return the
tool-neutral :class:`~benchmarks.duplication.models.PairFinding` values used by
the scorer. Detector-specific field names remain confined to this module.
"""

import dataclasses as dc
import itertools
import typing as typ

from benchmarks.score_support import (
    mapping,
    positive_line,
    relative_source_path,
    sequence,
    string,
)

from .models import Fragment, Lane, PairFinding

if typ.TYPE_CHECKING:
    from collections import abc as cabc
    from pathlib import Path

_PYSCN_SEMANTIC_CLONE_TYPE = 4
_NOSE_SEMANTIC_WITNESS = "exact"
_MINIMUM_FAMILY_LOCATIONS = 2


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


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class _LocationKeys:
    """Detector-specific field names for one reported source location."""

    path: str
    start: str = "start_line"
    end: str = "end_line"


_LINE_SUFFIXED_KEYS = _LocationKeys(path="file_path")
_PYCHASE_KEYS = _LocationKeys(path="file")
_NOSE_KEYS = _LocationKeys(path="file", start="start", end="end")


def _fragment(
    payload: cabc.Mapping[str, object],
    *,
    keys: _LocationKeys,
    context: str,
    corpus_root: Path,
) -> Fragment:
    """Normalize one reported fragment location."""
    start_line = positive_line(
        payload.get(keys.start), context=f"{context} {keys.start}"
    )
    end_line = positive_line(payload.get(keys.end), context=f"{context} {keys.end}")
    if start_line > end_line:
        msg = f"{context} {keys.start} must not exceed {keys.end}"
        raise ValueError(msg)
    return Fragment(
        path=relative_source_path(
            payload.get(keys.path), corpus_root, subject="fragment"
        ),
        start_line=start_line,
        end_line=end_line,
    )


def parse_pyscn_pairs(
    payload: object,
    *,
    corpus_root: Path,
) -> tuple[PairFinding, ...]:
    """Extract clone pairs from a pyscn unified JSON report.

    Parameters
    ----------
    payload : object
        Decoded pyscn report. It must contain an object-valued ``clone`` field
        with a ``clone_pairs`` sequence, or ``null`` for no pairs.
    corpus_root : pathlib.Path
        Root directory used to normalize and constrain reported file paths.

    Returns
    -------
    tuple[PairFinding, ...]
        Pyscn pairs in report order, with clone type four mapped to the
        semantic lane and other types mapped to the syntactic lane.

    Propagated errors
    -----------------
    TypeError
        If the report, pair fields, locations, or scalar fields have the wrong
        shape or type.
    ValueError
        If a line, similarity, or source path fails validation.
    """
    root = mapping(payload, context="pyscn payload")
    clone = mapping(root.get("clone"), context="pyscn clone")
    pairs = sequence(
        clone.get("clone_pairs"),
        context="pyscn clone.clone_pairs",
        none_is_empty=True,
    )
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
    pair = mapping(raw_pair, context=context)
    clone_type = pair.get("type")
    if not isinstance(clone_type, int) or isinstance(clone_type, bool):
        msg = f"{context} type must be an integer"
        raise TypeError(msg)
    members = [
        _fragment(
            mapping(
                mapping(pair.get(member_key), context=f"{context}.{member_key}").get(
                    "location"
                ),
                context=f"{context}.{member_key}.location",
            ),
            keys=_LINE_SUFFIXED_KEYS,
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
        similarity=_similarity(pair.get("similarity"), context=f"{context} similarity"),
    )


def parse_pychase_pairs(
    payload: object,
    *,
    corpus_root: Path,
) -> tuple[PairFinding, ...]:
    """Extract candidate pairs from a PyChase JSON report.

    Parameters
    ----------
    payload : object
        Decoded PyChase report containing a ``candidates`` sequence. Each
        candidate provides ``left`` and ``right`` member objects and a numeric
        ``score``.
    corpus_root : pathlib.Path
        Root directory used to normalize and constrain reported file paths.

    Returns
    -------
    tuple[PairFinding, ...]
        PyChase candidates in report order, normalized to the syntactic lane.

    Propagated errors
    -----------------
    TypeError
        If the report, candidates, members, or scalar fields have the wrong
        shape or type.
    ValueError
        If a line, score, or source path fails validation.
    """
    root = mapping(payload, context="PyChase payload")
    candidates = sequence(root.get("candidates"), context="PyChase candidates")
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
    candidate = mapping(raw_candidate, context=context)
    members = [
        _fragment(
            mapping(candidate.get(member_key), context=f"{context}.{member_key}"),
            keys=_PYCHASE_KEYS,
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


def parse_nose_pairs(
    payload: object,
    *,
    corpus_root: Path,
) -> tuple[PairFinding, ...]:
    """Extract location pairs from a nose ``query --format json`` report.

    Parameters
    ----------
    payload : object
        Decoded nose report containing a ``families`` sequence. Each family
        provides a ``witness`` label, a ``metrics`` object with a numeric
        ``mean_score``, and two or more member ``locations``.
    corpus_root : pathlib.Path
        Root directory used to normalize and constrain reported file paths.

    Returns
    -------
    tuple[PairFinding, ...]
        Every unordered member pair of every family, in report order. Families
        with the ``exact`` semantic witness map to the semantic lane; all other
        witnesses map to the syntactic lane.

    Propagated errors
    -----------------
    TypeError
        If the report, families, locations, or scalar fields have the wrong
        shape or type.
    ValueError
        If a line, score, or source path fails validation, or a family has
        fewer than two locations.
    """
    root = mapping(payload, context="nose payload")
    families = sequence(root.get("families"), context="nose families")
    return tuple(
        pair
        for index, raw_family in enumerate(families)
        for pair in _parse_nose_family(
            raw_family,
            family_index=index,
            corpus_root=corpus_root,
        )
    )


def _parse_nose_family(
    raw_family: object,
    *,
    family_index: int,
    corpus_root: Path,
) -> tuple[PairFinding, ...]:
    """Expand one validated nose family into unordered member pairs."""
    context = f"nose families[{family_index}]"
    family = mapping(raw_family, context=context)
    witness = string(family.get("witness"), context=f"{context} witness")
    metrics = mapping(family.get("metrics"), context=f"{context}.metrics")
    similarity = _similarity(
        metrics.get("mean_score"), context=f"{context} metrics.mean_score"
    )
    locations = sequence(family.get("locations"), context=f"{context}.locations")
    fragments = [
        _fragment(
            mapping(raw_location, context=f"{context}.locations[{location_index}]"),
            keys=_NOSE_KEYS,
            context=f"{context}.locations[{location_index}]",
            corpus_root=corpus_root,
        )
        for location_index, raw_location in enumerate(locations)
    ]
    if len(fragments) < _MINIMUM_FAMILY_LOCATIONS:
        msg = f"{context} must contain at least two locations"
        raise ValueError(msg)
    lane = (
        Lane.SEMANTIC_CLONE
        if witness == _NOSE_SEMANTIC_WITNESS
        else Lane.SYNTACTIC_CLONE
    )
    return tuple(
        PairFinding(
            first=first,
            second=second,
            lane=lane,
            category=witness,
            similarity=similarity,
        )
        for first, second in itertools.combinations(fragments, 2)
    )
