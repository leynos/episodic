"""Behavioural tests for the Chrono spoken-runtime estimator."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

from pytest_bdd import given, scenario, then, when

from episodic.qa.chrono import ChronoEvaluationRequest, ChronoRuntimeEstimator

if typ.TYPE_CHECKING:
    from episodic.qa.chrono import ChronoRuntimeEstimate


@dc.dataclass(slots=True)
class ChronoBDDContext:
    """Shared state between Chrono BDD steps."""

    request: ChronoEvaluationRequest | None = None
    result: ChronoRuntimeEstimate | None = None


@scenario(
    "../features/chrono.feature",
    "Chrono estimates spoken runtime from TEI dialogue",
)
def test_chrono_behaviour() -> None:
    """Run the Chrono behaviour scenario."""


@given(
    "a TEI-backed Chrono evaluation request is prepared",
    target_fixture="chrono_context",
)
def prepare_request() -> ChronoBDDContext:
    """Create a canonical Chrono request with TEI XML.

    Vidai Mock is intentionally not launched here because Chrono has no
    inference-service boundary in roadmap item 2.2.6.
    """
    return ChronoBDDContext(
        request=ChronoEvaluationRequest(
            script_tei_xml=(
                "<TEI><text><body>"
                "<sp><speaker>Host</speaker><p>Welcome to the show today.</p></sp>"
                "<sp><speaker>Guest</speaker><p>Thank you for inviting me.</p></sp>"
                "</body></text></TEI>"
            )
        )
    )


@when("Chrono estimates the spoken runtime")
def estimate_runtime(chrono_context: ChronoBDDContext) -> None:
    """Run Chrono over the local deterministic estimator."""
    request = typ.cast("ChronoEvaluationRequest", chrono_context.request)
    chrono_context.result = ChronoRuntimeEstimator().estimate(request)


@then("Chrono returns estimated seconds and estimator metadata")
def assert_result(chrono_context: ChronoBDDContext) -> None:
    """Assert the runtime estimate and metadata survive the behaviour path."""
    result = typ.cast("ChronoRuntimeEstimate", chrono_context.result)
    request = typ.cast("ChronoEvaluationRequest", chrono_context.request)

    assert result.estimated_seconds == 4
    assert result.metadata.estimator_name == "chrono-naive-word-count"
    assert result.metadata.estimator_version == "1"
    assert result.metadata.spoken_word_count == 10
    assert result.metadata.words_per_minute == 150
    assert result.metadata.input_character_count == len(request.script_tei_xml)
