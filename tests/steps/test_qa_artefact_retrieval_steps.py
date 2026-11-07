"""Behavioural coverage for QA-artefact retrieval over the REST API."""

from __future__ import annotations

import asyncio  # ruff: ignore[typing-only-standard-library-import]  # pytest-bdd evaluates step annotations.
import typing as typ

import pytest
from pytest_bdd import given, parsers, scenario, then, when
from sqlalchemy.ext.asyncio import (  # ruff: ignore[typing-only-third-party-import]  # pytest-bdd evaluates step annotations.
    AsyncSession,
    async_sessionmaker,
)

from episodic.canonical.qa_artefacts import QaComplianceStatus, QaEvaluator
from tests.steps.qa_artefact_retrieval_seed import (
    PEDANTE_EVALUATION_ID,
    PRINCIPAL_B,
    require,
)
from tests.steps.qa_artefact_retrieval_support import (
    QaRetrievalContext,
    establish_generated_episode,
    record_anthem_failure_for_context,
    record_anthem_success_for_context,
    record_chrono_for_context,
    record_pedante_for_context,
    request_evaluations,
    request_listed_details,
    request_pedante_detail,
)

_FEATURE = "../features/qa_artefact_retrieval.feature"
_SUMMARY_FIELDS = (
    "id",
    "episode_id",
    "generation_run_id",
    "evaluator",
    "evaluator_version",
    "artefact_schema_version",
    "compliance_policy_version",
    "compliance_status",
    "summary",
    "rubric_score",
    "runtime_estimate_seconds",
    "finding_count",
    "evaluator_metadata",
    "evaluated_at",
)
_PEDANTE_FINDING_CODES = (
    "citation_absent",
    "accurate_quotation",
    "accurate_restatement",
)


@pytest.fixture
def context(
    session_factory: async_sessionmaker[AsyncSession],
    _function_scoped_runner: asyncio.Runner,
) -> QaRetrievalContext:
    """Provide shared scenario state for one retrieval scenario."""
    return QaRetrievalContext(
        session_factory=session_factory,
        runner=_function_scoped_runner,
    )


@scenario(_FEATURE, "Retrieving every QA evaluation for an episode over HTTP")
def test_retrieves_every_evaluation() -> None:
    """Run the unfiltered listing scenario."""


@scenario(_FEATURE, "The listed finding count matches the detail representation")
def test_listed_finding_count_matches_detail() -> None:
    """Run the list/detail consistency scenario."""


@scenario(_FEATURE, "Filtering QA evaluations by evaluator over HTTP")
def test_filters_by_evaluator() -> None:
    """Run the evaluator-filter scenario."""


@scenario(_FEATURE, "Filtering QA evaluations by compliance status over HTTP")
def test_filters_by_compliance_status() -> None:
    """Run the compliance-status-filter scenario."""


@scenario(_FEATURE, "Combining evaluator and compliance filters over HTTP")
def test_combines_filters() -> None:
    """Run the combined-filter scenario."""


@scenario(_FEATURE, "Retrieving one QA evaluation with its findings")
def test_retrieves_one_evaluation_with_findings() -> None:
    """Run the detail scenario."""


@scenario(
    _FEATURE,
    "A different principal cannot read another owner's QA evaluations",
)
def test_hides_evaluations_from_another_principal() -> None:
    """Run the cross-principal scenario."""


@scenario(_FEATURE, "Rejecting an unknown evaluator filter")
def test_rejects_unknown_evaluator() -> None:
    """Run the unknown-evaluator scenario."""


@scenario(_FEATURE, "A successful evaluation supersedes an earlier errored one")
def test_successful_evaluation_supersedes_failure() -> None:
    """Run the supersession scenario."""


@given("a canonical episode with a generated TEI draft")
def generated_episode(context: QaRetrievalContext) -> None:
    """Create an owned episode whose TEI draft a generation run produced."""
    establish_generated_episode(context)


@given("a recorded Pedante evaluation with 3 findings, one of them blocking")
def recorded_pedante(context: QaRetrievalContext) -> None:
    """Record the Pedante evaluation the listing scenarios read."""
    record_pedante_for_context(context)


@given("a recorded Chrono evaluation with a runtime estimate and no findings")
def recorded_chrono(context: QaRetrievalContext) -> None:
    """Record the Chrono evaluation the listing scenarios read."""
    record_chrono_for_context(context)


@given("a recorded Anthem evaluation that failed to execute")
def recorded_anthem_failure(context: QaRetrievalContext) -> None:
    """Record the errored Anthem evaluation the listing scenarios read."""
    record_anthem_failure_for_context(context)


@when(parsers.re(r"^the owner requests the episode's QA evaluations$"))
def owner_requests_evaluations(context: QaRetrievalContext) -> None:
    """Request every evaluation for the Background episode."""
    request_evaluations(context)


@when(
    parsers.re(
        r"^the owner requests the episode\'s QA evaluations for evaluator "
        r'"(?P<evaluator>[^"]+)"$'
    )
)
def owner_requests_by_evaluator(
    context: QaRetrievalContext,
    evaluator: str,
) -> None:
    """Request the episode's evaluations filtered by evaluator."""
    request_evaluations(context, evaluator=evaluator)


@when(
    parsers.re(
        r"^the owner requests the episode\'s QA evaluations with compliance "
        r'status "(?P<compliance_status>[^"]+)"$'
    )
)
def owner_requests_by_status(
    context: QaRetrievalContext,
    compliance_status: str,
) -> None:
    """Request the episode's evaluations filtered by compliance status."""
    request_evaluations(context, compliance_status=compliance_status)


@when(
    parsers.re(
        r"^the owner requests the episode\'s QA evaluations for evaluator "
        r'"(?P<evaluator>[^"]+)" with compliance status '
        r'"(?P<compliance_status>[^"]+)"$'
    )
)
def owner_requests_by_evaluator_and_status(
    context: QaRetrievalContext,
    evaluator: str,
    compliance_status: str,
) -> None:
    """Request the episode's evaluations filtered by both parameters."""
    request_evaluations(
        context,
        evaluator=evaluator,
        compliance_status=compliance_status,
    )


@when("the owner requests each listed evaluation by identifier")
def owner_requests_listed_details(context: QaRetrievalContext) -> None:
    """Request the detail representation of every listed evaluation."""
    request_listed_details(context)


@when("the owner requests the recorded Pedante evaluation by identifier")
def owner_requests_pedante_detail(context: QaRetrievalContext) -> None:
    """Request the detail representation of the Pedante evaluation."""
    request_pedante_detail(context)


@when("a different principal requests the episode's QA evaluations")
def different_principal_requests(context: QaRetrievalContext) -> None:
    """Request the episode's evaluations as a different principal."""
    request_evaluations(context, headers=PRINCIPAL_B)


@when("the Anthem evaluation is recorded again with a successful outcome")
def anthem_is_recorded_again(context: QaRetrievalContext) -> None:
    """Record a successful Anthem retry over the errored artefact."""
    record_anthem_success_for_context(context)


def _listed_items(context: QaRetrievalContext) -> list[dict[str, object]]:
    """Return the items of the last successful listing."""
    listing = require(context.listed, "evaluation listing")
    return typ.cast("list[dict[str, object]]", listing["items"])


@then("the response lists 3 evaluations ordered newest first")
def lists_three_newest_first(context: QaRetrievalContext) -> None:
    """Assert the listing carries all three evaluations, newest first."""
    items = _listed_items(context)
    assert [item["evaluator"] for item in items] == [
        "anthem",
        "chrono",
        "pedante",
    ], "the listing did not order evaluations newest first"


@then("each evaluation reports its evaluator and compliance status")
def reports_evaluator_and_status(context: QaRetrievalContext) -> None:
    """Assert every listed item carries the documented vocabulary."""
    evaluators = {member.value for member in QaEvaluator}
    statuses = {member.value for member in QaComplianceStatus}
    for item in _listed_items(context):
        assert item["evaluator"] in evaluators, item
        assert item["compliance_status"] in statuses, item


@then(parsers.re(r"^the response lists (?P<count>\d+) evaluations?$"))
def lists_counted_evaluations(
    context: QaRetrievalContext,
    count: str,
) -> None:
    """Assert the listing carries the expected number of evaluations.

    The step text is deliberately number-agnostic in its noun: a scenario says
    "1 evaluation" and "0 evaluations", and one definition keeps both spellings
    asserting the same thing.
    """
    assert len(_listed_items(context)) == int(count), context.listed


@then(parsers.parse("the response reports a total of {total:d}"))
def reports_total(context: QaRetrievalContext, total: int) -> None:
    """Assert the listing's unpaged total matches the filters."""
    listing = require(context.listed, "evaluation listing")
    assert listing["total"] == total, listing


@then(parsers.parse('the evaluation\'s evaluator is "{evaluator}"'))
def evaluation_evaluator_is(
    context: QaRetrievalContext,
    evaluator: str,
) -> None:
    """Assert the single listed evaluation has the expected evaluator."""
    items = _listed_items(context)
    assert len(items) == 1, items
    assert items[0]["evaluator"] == evaluator, items[0]


@then(parsers.parse('the evaluation\'s compliance status is "{status}"'))
def evaluation_status_is(context: QaRetrievalContext, status: str) -> None:
    """Assert the single listed evaluation has the expected verdict."""
    items = _listed_items(context)
    assert len(items) == 1, items
    assert items[0]["compliance_status"] == status, items[0]


@then(parsers.parse("the response status is {status:d}"))
def response_status_is(context: QaRetrievalContext, status: int) -> None:
    """Assert the HTTP status of the most recent request."""
    assert context.status_code == status, context.error_payload


@then(parsers.parse('the error code is "{code}"'))
def error_code_is(context: QaRetrievalContext, code: str) -> None:
    """Assert the error envelope carries the expected code."""
    payload = require(context.error_payload, "error payload")
    assert payload["code"] == code, payload


@then(parsers.parse('the error details name the "{field}" field'))
def error_details_name_field(context: QaRetrievalContext, field: str) -> None:
    """Assert validation details identify the offending parameter."""
    payload = require(context.error_payload, "error payload")
    details = typ.cast("dict[str, object]", payload["details"])
    assert details["field"] == field, payload


@then("the response includes the evaluation summary")
def response_includes_summary(context: QaRetrievalContext) -> None:
    """Assert the detail payload carries every summary field."""
    detail = _pedante_detail(context)
    missing = [field for field in _SUMMARY_FIELDS if field not in detail]
    assert not missing, f"detail payload is missing {missing!r}"
    assert detail["id"] == str(PEDANTE_EVALUATION_ID), detail
    assert detail["evaluator"] == "pedante", detail
    assert detail["compliance_status"] == "non_compliant", detail


@then("the response includes 3 findings ordered as the evaluator emitted them")
def response_includes_ordered_findings(context: QaRetrievalContext) -> None:
    """Assert the detail findings preserve the evaluator's order."""
    findings = typ.cast("list[dict[str, object]]", _pedante_detail(context)["findings"])
    assert [finding["ordinal"] for finding in findings] == [0, 1, 2], findings
    assert tuple(finding["code"] for finding in findings) == (_PEDANTE_FINDING_CODES), (
        findings
    )
    assert [finding["subject_id"] for finding in findings] == [
        "claim-1",
        "claim-2",
        "claim-3",
    ], findings
    assert [finding["is_blocking"] for finding in findings] == [
        True,
        False,
        False,
    ], findings


@then("each finding includes its remediation guidance")
def findings_include_remediation(context: QaRetrievalContext) -> None:
    """Assert every finding carries the remediation the evaluator proposed."""
    findings = typ.cast("list[dict[str, object]]", _pedante_detail(context)["findings"])
    for finding in findings:
        remediation = finding["remediation"]
        assert isinstance(remediation, str), finding
        assert remediation.strip(), finding


@then("every listed finding count equals the number of findings in its detail response")
def finding_counts_agree(context: QaRetrievalContext) -> None:
    """Assert each list item's count matches its detail findings."""
    for item in _listed_items(context):
        evaluation_id = typ.cast("str", item["id"])
        detail = context.details[evaluation_id]
        findings = typ.cast("list[object]", detail["findings"])
        assert item["finding_count"] == len(findings), (item, detail)


def _pedante_detail(context: QaRetrievalContext) -> dict[str, object]:
    """Return the recorded Pedante detail payload."""
    return context.details[str(PEDANTE_EVALUATION_ID)]
