"""Detector-specific report parsing for the duplication benchmark."""

from __future__ import annotations

import typing as typ

from benchmarks.score_support import (
    mapping,
    positive_line,
    relative_source_path,
    sequence,
)

from .models import Fragment, Lane, PairFinding

if typ.TYPE_CHECKING:
    from collections import abc as cabc
    from pathlib import Path

_PYSCN_SEMANTIC_CLONE_TYPE = 4


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


def _fragment(
    payload: cabc.Mapping[str, object],
    *,
    path_key: str,
    context: str,
    corpus_root: Path,
) -> Fragment:
    """Normalize one reported fragment location."""
    start_line = positive_line(
        payload.get("start_line"), context=f"{context} start_line"
    )
    end_line = positive_line(payload.get("end_line"), context=f"{context} end_line")
    if start_line > end_line:
        msg = f"{context} start_line must not exceed end_line"
        raise ValueError(msg)
    return Fragment(
        path=relative_source_path(
            payload.get(path_key), corpus_root, subject="fragment"
        ),
        start_line=start_line,
        end_line=end_line,
    )


def parse_pyscn_pairs(
    payload: object,
    *,
    corpus_root: Path,
) -> tuple[PairFinding, ...]:
    """Extract pyscn clone pairs from its unified JSON report."""
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
        similarity=_similarity(pair.get("similarity"), context=f"{context} similarity"),
    )


def parse_pychase_pairs(
    payload: object,
    *,
    corpus_root: Path,
) -> tuple[PairFinding, ...]:
    """Extract PyChase candidate pairs from its JSON report."""
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
