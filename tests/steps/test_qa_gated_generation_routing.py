"""Behavioural coverage for QA-gated generation routing (4.4.1)."""

import dataclasses as dc
import typing as typ

from pytest_bdd import given, parsers, scenario, then, when

from episodic.canonical.generation_graph_ports import QualityEvaluatorSet
from episodic.orchestration import LangGraphContentGenerationGraph
from tests._content_graph_fakes import ScriptedEvaluator
from tests.steps.generation_slice_shared_steps import create_generation_run
from tests.steps.no_qa_generation_slice_support import (
    ErrorEnvelopeExpectation,
    NoQaGenerationSliceContext,
    assert_error_envelope,
    assert_response_status,
    require,
)

_FEATURE = "../features/qa_gated_generation_routing.feature"
_GATED_PAYLOAD: dict[str, object] = {
    "quality_mode": "qa_gated",
    "actor": "editor@example.com",
}


@scenario(_FEATURE, "A QA-gated run whose evaluators pass persists a QA-passed draft")
def test_qa_gated_run_persists_a_passed_draft() -> None:
    """Run the QA-gated happy path."""


@scenario(
    _FEATURE,
    "A QA-gated run whose evaluators fail escalates without persisting a draft",
)
def test_qa_gated_run_escalates_without_persisting() -> None:
    """Run the QA-gated escalation scenario."""


@scenario(_FEATURE, "A QA-gated run with a skip rationale is rejected")
def test_qa_gated_run_rejects_a_skip_rationale() -> None:
    """Run the gated-rationale rejection scenario."""


@scenario(_FEATURE, "QA-gated runs are unprocessable when no evaluators are configured")
def test_qa_gated_run_is_unprocessable_without_evaluators() -> None:
    """Run the capability-gate scenario."""


@scenario(
    _FEATURE,
    "A draft-without-QA run still takes the direct route when evaluators exist",
)
def test_no_qa_run_keeps_its_direct_route() -> None:
    """Run the no-QA direct-route scenario."""


def _bind_evaluators(
    context: NoQaGenerationSliceContext,
    evaluators: tuple[ScriptedEvaluator, ...],
) -> None:
    """Rebind the launcher and dependencies to a graph with these evaluators."""
    launcher = require(context.launcher, "generation launcher")
    dependencies = require(context.dependencies, "API dependencies")
    graph = LangGraphContentGenerationGraph(
        QualityEvaluatorSet(evaluators, evaluator_timeout_seconds=5.0)
    )
    context.launcher = dc.replace(launcher, content_graph=graph)
    context.dependencies = dc.replace(
        dependencies,
        launcher=context.launcher,
        accepted_quality_modes=graph.accepted_quality_modes(),
    )


@given("QA evaluation is configured with a passing evaluator")
def passing_evaluator_configured(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Bind a deterministic passing evaluator."""
    _bind_evaluators(
        generation_slice_context,
        (ScriptedEvaluator("pedante", "passed"),),
    )


@given("QA evaluation is configured with a failing evaluator")
def failing_evaluator_configured(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Bind a deterministic failing evaluator."""
    _bind_evaluators(
        generation_slice_context,
        (ScriptedEvaluator("pedante", "failed"),),
    )


@given("no QA evaluators are configured")
def no_evaluators_configured(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Rebind the stack to an empty evaluator set."""
    _bind_evaluators(generation_slice_context, ())


@when("I create a qa-gated generation run for the ingested episode")
def create_qa_gated_run(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Create one QA-gated generation run."""
    create_generation_run(
        generation_slice_context,
        dict(_GATED_PAYLOAD),
        key="qa-gated-run",
    )


@when("I create a qa-gated generation run with a skip_qa_rationale")
def create_qa_gated_run_with_rationale(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Create a QA-gated run that carries a no-QA rationale."""
    create_generation_run(
        generation_slice_context,
        {**_GATED_PAYLOAD, "skip_qa_rationale": "Not allowed."},
        key="qa-gated-rationale",
    )


def _run_body(context: NoQaGenerationSliceContext) -> dict[str, object]:
    """Return the polled run body."""
    return typ.cast(
        "dict[str, object]",
        require(context.run_response, "run response").json(),
    )


@then(
    parsers.parse(
        'the run is created with qa_status "{qa_status}" and no skip rationale'
    )
)
def run_created_pending_without_rationale(
    generation_slice_context: NoQaGenerationSliceContext,
    qa_status: str,
) -> None:
    """Verify creation records pending QA and no rationale."""
    body = generation_slice_context.responses[0].json()
    assert body["qa_status"] == qa_status, f"QA status: {body['qa_status']!r}"
    assert body["skip_qa_rationale"] is None, (
        f"rationale: {body['skip_qa_rationale']!r}"
    )


@then(parsers.parse('the run status is "{status}" with qa_status "{qa_status}"'))
def run_status_and_qa_status(
    generation_slice_context: NoQaGenerationSliceContext,
    status: str,
    qa_status: str,
) -> None:
    """Verify the terminal status and its recorded QA status."""
    body = _run_body(generation_slice_context)
    assert body["status"] == status, f"run status: {body['status']!r}"
    assert body["qa_status"] == qa_status, f"QA status: {body['qa_status']!r}"


@then(
    parsers.parse('the event log records "{first}", "{second}" and "{third}" in order')
)
def event_log_records_in_order(
    generation_slice_context: NoQaGenerationSliceContext,
    first: str,
    second: str,
    third: str,
) -> None:
    """Verify the named events appear in the given order."""
    items = require(
        generation_slice_context.events_response,
        "event response",
    ).json()["items"]
    kinds = [item["kind"] for item in items]
    positions = [kinds.index(kind) for kind in (first, second, third)]
    assert positions == sorted(positions), f"event kinds: {kinds!r}"


@then(
    parsers.parse(
        'the envelope reports quality_mode "{quality_mode}" and qa_status "{qa_status}"'
    )
)
def envelope_reports_provenance(
    generation_slice_context: NoQaGenerationSliceContext,
    quality_mode: str,
    qa_status: str,
) -> None:
    """Verify the TEI envelope reports the producing run's mode and QA status."""
    response = require(generation_slice_context.tei_response, "TEI response")
    assert_response_status(response, 200)
    assert response.json()["quality_mode"] == quality_mode, response.json()
    assert response.json()["qa_status"] == qa_status, response.json()


@then(parsers.parse('the run records the error category "{error_category}"'))
def run_records_error_category(
    generation_slice_context: NoQaGenerationSliceContext,
    error_category: str,
) -> None:
    """Verify the failed run's stable error category."""
    body = _run_body(generation_slice_context)
    assert body["error_category"] == error_category, (
        f"error category: {body['error_category']!r}"
    )


@then(
    parsers.parse('the event log contains a "{present}" event and no "{absent}" event')
)
def event_log_contains_and_lacks(
    generation_slice_context: NoQaGenerationSliceContext,
    present: str,
    absent: str,
) -> None:
    """Verify one event is present and another is absent."""
    items = require(
        generation_slice_context.events_response,
        "event response",
    ).json()["items"]
    kinds = {item["kind"] for item in items}
    assert present in kinds, f"event kinds: {kinds!r}"
    assert absent not in kinds, f"event kinds: {kinds!r}"


@then("the episode TEI is not found")
def episode_tei_is_not_found(
    generation_slice_context: NoQaGenerationSliceContext,
) -> None:
    """Verify no TEI is retrievable for the episode."""
    context = generation_slice_context
    episode_id = context.responses[0].json()["episode_id"]
    response = context.runner.run(
        context.request("GET", f"/v1/episodes/{episode_id}/tei")
    )
    assert_response_status(response, 404)


@then(parsers.parse('the response is 400 Bad Request with constraint "{constraint}"'))
def response_is_bad_request_with_constraint(
    generation_slice_context: NoQaGenerationSliceContext,
    constraint: str,
) -> None:
    """Verify the gated-rationale rejection names its constraint."""
    assert_error_envelope(
        generation_slice_context.responses[0],
        ErrorEnvelopeExpectation(
            status=400,
            code="validation_error",
            message=("skip_qa_rationale is not accepted with quality_mode qa_gated."),
            details={
                "field": "skip_qa_rationale",
                "constraint": constraint,
                "quality_mode": "qa_gated",
            },
        ),
    )


@then(parsers.parse('the event log contains no "{event_kind}" event'))
def event_log_lacks(
    generation_slice_context: NoQaGenerationSliceContext,
    event_kind: str,
) -> None:
    """Verify the named event never appears."""
    items = require(
        generation_slice_context.events_response,
        "event response",
    ).json()["items"]
    kinds = {item["kind"] for item in items}
    assert event_kind not in kinds, f"event kinds: {kinds!r}"
