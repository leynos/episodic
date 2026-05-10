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
    assert chrono_context.request is not None, (
        "Chrono request must be prepared before runtime estimation"
    )
    chrono_context.result = ChronoRuntimeEstimator().estimate(chrono_context.request)


@then("Chrono returns estimated seconds and estimator metadata")
def assert_result(chrono_context: ChronoBDDContext) -> None:
    """Assert the runtime estimate and metadata survive the behaviour path."""
    assert chrono_context.result is not None, (
        "Chrono result must be available after runtime estimation"
    )
    assert chrono_context.request is not None, (
        "Chrono request must be available for metadata checks"
    )
    result = chrono_context.result
    request = chrono_context.request

    assert result.estimated_seconds == 4, (
        "Expected 10 spoken words at 150 WPM to round to 4 seconds"
    )
    assert result.metadata.estimator_name == "chrono-naive-word-count", (
        "Estimator name must remain stable"
    )
    assert result.metadata.estimator_version == "1", (
        "Estimator version must remain stable"
    )
    assert result.metadata.spoken_word_count == 10, (
        "Spoken word count should match dialogue tokens"
    )
    assert result.metadata.words_per_minute == 150, (
        "Default WPM metadata must be preserved"
    )
    assert result.metadata.input_character_count == len(request.script_tei_xml), (
        "Input character count metadata must match the request payload length"
    )
