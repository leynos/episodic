"""Unit tests for the async boundary of the Chrono spoken-runtime estimator."""

import asyncio

import pytest

from episodic.qa.chrono import (
    ChronoEstimatorConfig,
    ChronoEvaluationRequest,
    ChronoRuntimeEstimate,
    ChronoRuntimeEstimator,
)


def _tei_document(body: str) -> str:
    """Wrap a TEI body fixture with the required document header."""
    return (
        "<TEI><teiHeader><fileDesc><title>Chrono test</title></fileDesc>"
        f"</teiHeader><text><body>{body}</body></text></TEI>"
    )


@pytest.mark.asyncio
async def test_chrono_estimator_async_evaluate_matches_sync_estimate() -> None:
    """Async evaluate() should produce the same result as sync estimate()."""
    config = ChronoEstimatorConfig(
        estimator_name="chrono-naive-word-count",
        estimator_version="2",
        words_per_minute=60,
    )
    request = ChronoEvaluationRequest(
        script_tei_xml=_tei_document("<sp><p>one two three</p></sp>")
    )
    estimator = ChronoRuntimeEstimator(config=config)

    sync_result = estimator.estimate(request)
    async_result = await estimator.evaluate(request)

    assert async_result == sync_result, (
        "evaluate() must delegate to estimate() and return an identical result"
    )


@pytest.mark.asyncio
async def test_chrono_estimator_evaluate_yields_before_estimating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """evaluate() must yield to the event loop before doing synchronous work."""
    events: list[str] = []
    unpatched_estimate = ChronoRuntimeEstimator.estimate

    def _recording_estimate(
        self: ChronoRuntimeEstimator,
        request: ChronoEvaluationRequest,
    ) -> ChronoRuntimeEstimate:
        """Record the point at which the synchronous estimate begins."""
        events.append("estimate")
        return unpatched_estimate(self, request)

    async def _competitor() -> None:
        """Record that an unrelated coroutine got a turn on the loop."""
        events.append("competitor")
        await asyncio.sleep(0)

    monkeypatch.setattr(ChronoRuntimeEstimator, "estimate", _recording_estimate)
    config = ChronoEstimatorConfig(words_per_minute=60)
    estimator = ChronoRuntimeEstimator(config=config)
    request = ChronoEvaluationRequest(
        script_tei_xml=_tei_document("<sp><p>one two three</p></sp>")
    )

    evaluation = asyncio.ensure_future(estimator.evaluate(request))
    competitor = asyncio.ensure_future(_competitor())
    result = await evaluation
    await competitor

    assert events == ["competitor", "estimate"], (
        "evaluate() must suspend at its yield point before calling estimate(), "
        f"letting a coroutine scheduled after it run first; observed {events}"
    )
    assert result.metadata.spoken_word_count == 3, (
        "the yielded evaluation must still count every spoken word"
    )
    assert result.estimated_seconds == 3, (
        "three words at 60 words per minute must estimate three seconds"
    )


@pytest.mark.asyncio
async def test_chrono_estimator_handles_concurrent_evaluations() -> None:
    """A shared estimator should handle concurrent immutable requests."""
    estimator = ChronoRuntimeEstimator()
    requests = [
        ChronoEvaluationRequest(
            script_tei_xml=_tei_document(f"<sp><p>{'token ' * (index + 1)}</p></sp>")
        )
        for index in range(5)
    ]
    expected_word_counts = list(range(1, 6))

    results = await asyncio.gather(
        *(estimator.evaluate(request) for request in requests)
    )

    assert [r.metadata.spoken_word_count for r in results] == expected_word_counts, (
        "concurrent evaluate() calls must preserve per-request word counts"
    )
    assert results == [estimator.estimate(request) for request in requests], (
        "concurrent evaluate() calls must match independent sync estimates"
    )
