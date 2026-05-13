"""Syrupy regression snapshots for Chrono runtime-estimation artefacts."""

import dataclasses
import typing as typ

import pytest

from episodic.qa.chrono import (
    ChronoEvaluationRequest,
    ChronoRuntimeEstimator,
)
from episodic.qa.chrono_langgraph import ChronoGraphState, build_chrono_graph

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


def _tei_document(body: str) -> str:
    """Return a minimal TEI document string wrapping the provided body content."""
    return (
        "<TEI><teiHeader><fileDesc><title>Chrono snapshot</title></fileDesc>"
        f"</teiHeader><text><body>{body}</body></text></TEI>"
    )


def test_chrono_estimate_snapshot(snapshot: SnapshotAssertion) -> None:
    """Serialised Chrono estimate must match the stored snapshot."""
    request = ChronoEvaluationRequest(
        script_tei_xml=_tei_document(
            "<sp><speaker>Host</speaker><p>Hello there, welcome today.</p></sp>"
        )
    )
    result = ChronoRuntimeEstimator().estimate(request)
    assert dataclasses.asdict(result) == snapshot, (
        "Chrono estimate serialized output does not match snapshot"
    )


@pytest.mark.asyncio
async def test_chrono_graph_snapshot(snapshot: SnapshotAssertion) -> None:
    """Serialised Chrono graph result must match the stored snapshot."""
    request = ChronoEvaluationRequest(
        script_tei_xml=_tei_document(
            "<sp><speaker>Host</speaker><p>Hello there, welcome today.</p></sp>"
        )
    )
    graph = build_chrono_graph(ChronoRuntimeEstimator())
    state = await graph.ainvoke(ChronoGraphState(chrono_request=request))
    chrono_result = state["chrono_result"]
    assert dataclasses.asdict(chrono_result) == snapshot, (
        f"Chrono graph snapshot mismatch: got {dataclasses.asdict(chrono_result)}"
    )
