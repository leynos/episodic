"""Contracts that each event runs the test suite once, under coverage.

`ci.yml` used to run `make test` on a push to main while `coverage-main.yml`
ran the same suite under coverage on the same push, so every trunk commit ran
every test twice. The plain run is gone. These contracts hold the three facts
that make its removal safe:

- `ci.yml` runs no plain suite on any event, so nothing reintroduces the
  second run;
- `coverage-main.yml` runs the whole suite on every push to main, with no
  input that narrows what pytest collects;
- the CrossHair PEP 316 proof, which `make test` also ran through its
  `crosshair` prerequisite, is a test in that suite and a default collection
  still selects it.
"""

import re
import subprocess  # noqa: S404  # Runs a fixed pytest collection command.
import sys

import pytest

from tests.test_codescene_workflow_contract_support import (
    REPOSITORY_ROOT,
    WORKFLOWS_DIRECTORY,
    mapping,
    named_step,
    trigger_config,
    workflow_jobs,
    workflow_steps,
)

CI_WORKFLOW = WORKFLOWS_DIRECTORY / "ci.yml"
COVERAGE_MAIN_WORKFLOW = WORKFLOWS_DIRECTORY / "coverage-main.yml"
COVERAGE_MAIN_JOB = "coverage-upload"
GENERATE_COVERAGE_ACTION = "leynos/shared-actions/.github/actions/generate-coverage@"
#: A command that runs the suite, or part of it, outside the coverage action.
#: Variable assignments and options may precede the target (`make -j2 test`).
PLAIN_SUITE = re.compile(r"\bpytest\b|\bmake\s+((?:\S+=\S+|-\S+)\s+)*test(?![-\w])")
#: The publisher inputs that leave pytest's collection untouched. Anything else
#: could narrow the suite this contract relies on, so it must be read first.
COLLECTION_NEUTRAL_INPUTS = frozenset({
    "language",
    "format",
    "output-path",
    "python-source",
    "with-ratchet",
    "publish-baseline",
    "pytest-workers",
})
CROSSHAIR_NODE = (
    "tests/test_chrono_contracts.py::TestChronoContracts::"
    "test_chrono_crosshair_contracts_pass"
)


def test_ci_runs_no_plain_suite() -> None:
    """Refuse a `ci.yml` step that runs pytest or `make test` directly.

    The pull-request coverage step is the suite's only run in this workflow.
    A plain run beside it duplicates the coverage run on a pull request, and
    on a push it duplicates `coverage-main.yml`.
    """
    plain = [
        (job_name, str(step.get("name", "")))
        for job_name in workflow_jobs(CI_WORKFLOW)
        for step in workflow_steps(CI_WORKFLOW, str(job_name))
        if PLAIN_SUITE.search(str(step.get("run", "")))
    ]

    assert not plain, f"ci.yml runs the suite outside coverage in {plain!r}"


@pytest.mark.parametrize(
    ("command", "runs_suite"),
    [
        ("make test", True),
        ("make -j2 test", True),
        ("make PYTEST_XDIST_WORKERS=4 test", True),
        ("make -k PYTEST_XDIST_WORKERS=4 test", True),
        ("uv run pytest -v", True),
        ("make test-workflow-contracts", False),
        ("make typecheck", False),
    ],
)
def test_the_plain_suite_pattern(command: str, *, runs_suite: bool) -> None:
    """Recognize every spelling of a plain suite run, and nothing longer."""
    assert bool(PLAIN_SUITE.search(command)) is runs_suite, command


def test_the_publisher_runs_the_whole_suite_on_every_push_to_main() -> None:
    """Require an unguarded, uncut coverage run on every push to main."""
    push = trigger_config(COVERAGE_MAIN_WORKFLOW, "push")
    assert push is not None, "coverage-main.yml must trigger on push"
    assert push.get("branches") == ["main"], "the push trigger must name main"

    job = mapping(
        workflow_jobs(COVERAGE_MAIN_WORKFLOW)[COVERAGE_MAIN_JOB],
        subject="coverage-upload job",
    )
    assert job.get("if") == "github.ref == 'refs/heads/main'", (
        "the publisher job may be guarded only by the main ref"
    )

    step = named_step(COVERAGE_MAIN_WORKFLOW, COVERAGE_MAIN_JOB, "Generate coverage")
    assert str(step.get("uses", "")).startswith(GENERATE_COVERAGE_ACTION), (
        "the publisher must run the shared coverage generator"
    )
    assert "if" not in step, "the coverage step must run on every publisher run"
    inputs = mapping(step.get("with"), subject="Generate coverage inputs")
    assert inputs.get("language") == "python", "the publisher must run pytest"
    unread = {str(name) for name in inputs} - COLLECTION_NEUTRAL_INPUTS
    assert not unread, f"inputs that could narrow collection: {sorted(unread)}"


def test_a_default_collection_selects_the_crosshair_proof() -> None:
    """Require the CrossHair proof in the suite the coverage lanes run.

    Collection goes through pytest with the repository's own configuration
    and no path argument, as the coverage run's does, so a `testpaths`
    narrowing, a marker deselection in `addopts` or a collection hook drops
    the node here exactly as it would there.
    """
    completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False, no user input.
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, (
        f"collection failed:\n{completed.stdout}\n{completed.stderr}"
    )
    assert CROSSHAIR_NODE in completed.stdout.splitlines(), (
        f"a default collection no longer selects {CROSSHAIR_NODE}"
    )
