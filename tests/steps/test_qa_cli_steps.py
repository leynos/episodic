"""Behavioural coverage for QA-artefact retrieval through the CLI."""

from __future__ import annotations

import asyncio  # ruff: ignore[typing-only-standard-library-import]  # pytest-bdd evaluates step annotations.
import typing as typ

import pytest
from pytest_bdd import given, parsers, scenario, then, when
from sqlalchemy.ext.asyncio import (  # ruff: ignore[typing-only-third-party-import]  # pytest-bdd evaluates step annotations.
    AsyncSession,
    async_sessionmaker,
)

from tests.steps.qa_artefact_retrieval_support import (
    establish_generated_episode,
    record_anthem_failure_for_context,
    record_chrono_for_context,
    record_pedante_for_context,
)
from tests.steps.qa_cli_support import (
    FOREIGN_TOKEN,
    ListOptions,
    QaCliContext,
    build_cli_context,
    json_items,
    json_payload,
    list_evaluations,
    table_rows,
    table_summary,
)

_FEATURE = "../features/qa_cli_retrieval.feature"
_NEWEST_FIRST = ["anthem", "chrono", "pedante"]


@pytest.fixture
def cli(
    session_factory: async_sessionmaker[AsyncSession],
    _function_scoped_runner: asyncio.Runner,
) -> QaCliContext:
    """Provide shared scenario state for one CLI scenario."""
    return build_cli_context(session_factory, _function_scoped_runner)


@scenario(_FEATURE, "Listing evaluations in table form")
def test_lists_evaluations_as_a_table() -> None:
    """Run the table-listing scenario."""


@scenario(_FEATURE, "Listing evaluations as JSON")
def test_lists_evaluations_as_json() -> None:
    """Run the JSON-listing scenario."""


@scenario(_FEATURE, "Filtering evaluations by evaluator")
def test_filters_evaluations_by_evaluator() -> None:
    """Run the evaluator-filter scenario."""


@scenario(_FEATURE, "Combining filters that match nothing")
def test_reports_an_empty_page() -> None:
    """Run the empty-page scenario."""


@scenario(_FEATURE, "Hiding another principal's evaluations")
def test_hides_another_principals_evaluations() -> None:
    """Run the cross-principal scenario."""


@scenario(_FEATURE, "Naming the missing credential")
def test_names_the_missing_credential() -> None:
    """Run the missing-token scenario."""


@given("a canonical episode with a generated TEI draft")
def generated_episode(cli: QaCliContext) -> None:
    """Create an owned episode whose TEI draft a generation run produced."""
    establish_generated_episode(cli.retrieval)


@given("a recorded Pedante evaluation with 3 findings, one of them blocking")
def recorded_pedante(cli: QaCliContext) -> None:
    """Record the Pedante evaluation the CLI listings read."""
    record_pedante_for_context(cli.retrieval)


@given("a recorded Chrono evaluation with a runtime estimate and no findings")
def recorded_chrono(cli: QaCliContext) -> None:
    """Record the Chrono evaluation the CLI listings read."""
    record_chrono_for_context(cli.retrieval)


@given("a recorded Anthem evaluation that failed to execute")
def recorded_anthem_failure(cli: QaCliContext) -> None:
    """Record the errored Anthem evaluation the CLI listings read."""
    record_anthem_failure_for_context(cli.retrieval)


@when("the operator lists the episode's QA evaluations")
def operator_lists(cli: QaCliContext) -> None:
    """List the Background episode's evaluations as a table."""
    list_evaluations(cli, ListOptions())


@when("the operator lists the episode's QA evaluations as JSON")
def operator_lists_json(cli: QaCliContext) -> None:
    """List the Background episode's evaluations as JSON."""
    list_evaluations(cli, ListOptions(output_format="json"))


@when(
    parsers.re(
        r"^the operator lists the episode\'s QA evaluations for evaluator "
        r'"(?P<evaluator>[^"]+)"$'
    )
)
def operator_lists_by_evaluator(cli: QaCliContext, evaluator: str) -> None:
    """List the Background episode's evaluations filtered by evaluator."""
    list_evaluations(cli, ListOptions(evaluator=evaluator))


@when(
    parsers.re(
        r"^the operator lists the episode\'s QA evaluations for evaluator "
        r'"(?P<evaluator>[^"]+)" with compliance status '
        r'"(?P<compliance_status>[^"]+)"$'
    )
)
def operator_lists_by_both(
    cli: QaCliContext,
    evaluator: str,
    compliance_status: str,
) -> None:
    """List the Background episode's evaluations filtered by both parameters."""
    list_evaluations(
        cli,
        ListOptions(evaluator=evaluator, compliance_status=compliance_status),
    )


@when("a different principal lists the episode's QA evaluations")
def foreign_principal_lists(cli: QaCliContext) -> None:
    """List the episode's evaluations as a principal that does not own it."""
    list_evaluations(cli, ListOptions(token=FOREIGN_TOKEN))


@when("the operator lists the episode's QA evaluations without a token")
def operator_lists_without_token(cli: QaCliContext) -> None:
    """List the episode's evaluations without configuring a credential."""
    list_evaluations(cli, ListOptions(token=None))


@then(parsers.parse("the CLI exits with status {status:d}"))
def cli_exits_with(cli: QaCliContext, status: int) -> None:
    """Assert the process exit code of the last invocation."""
    assert cli.exit_code == status, cli.stderr


@then(parsers.parse("the table lists {count:d} evaluations newest first"))
def table_lists_newest_first(cli: QaCliContext, count: int) -> None:
    """Assert the table carries every evaluation in newest-first order."""
    rows = table_rows(cli)
    assert len(rows) == count, rows
    assert [row[0] for row in rows] == _NEWEST_FIRST[:count], rows
    assert [int(row[2]) for row in rows] == [0, 0, 3][:count], rows


@then(parsers.parse("the table lists {count:d} evaluation"))
def table_lists_one(cli: QaCliContext, count: int) -> None:
    """Assert the table carries the expected number of evaluations."""
    rows = table_rows(cli)
    assert len(rows) == count, rows
    assert rows[0][0] == "pedante", rows


@then(parsers.parse('the summary line reports "{summary}"'))
def summary_reports(cli: QaCliContext, summary: str) -> None:
    """Assert the page summary beneath the table."""
    assert table_summary(cli) == summary, table_summary(cli)


@then(parsers.parse("the JSON total is {total:d}"))
def json_total_is(cli: QaCliContext, total: int) -> None:
    """Assert the envelope's unpaged total."""
    assert json_payload(cli)["total"] == total, json_payload(cli)


@then(parsers.parse("the JSON lists {count:d} evaluations newest first"))
def json_lists_newest_first(cli: QaCliContext, count: int) -> None:
    """Assert the JSON page carries the same order as the table."""
    evaluators = [typ.cast("str", item["evaluator"]) for item in json_items(cli)]
    assert len(evaluators) == count, evaluators
    assert evaluators == _NEWEST_FIRST[:count], evaluators


@then(parsers.parse('the CLI reports "{fragment}"'))
def cli_reports(cli: QaCliContext, fragment: str) -> None:
    """Assert the standard error stream names the failure."""
    assert not cli.stdout, cli.stdout
    assert fragment in cli.stderr, cli.stderr
