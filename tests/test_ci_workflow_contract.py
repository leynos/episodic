"""Contracts for the shared coverage generator in CI workflows."""

import pathlib as pl
import re

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
WORKFLOW_PATHS = (
    REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml",
    REPOSITORY_ROOT / ".github" / "workflows" / "coverage-main.yml",
)
GENERATE_COVERAGE_ACTION = "leynos/shared-actions/.github/actions/generate-coverage"
GENERATE_COVERAGE_REVISION = "a5765019912a8ab6882b12db049c7cde635f3a85"


def test_coverage_workflows_pin_the_same_generator_revision() -> None:
    """Keep the pull-request and default-branch coverage generators aligned."""
    action_pattern = re.compile(
        rf"{re.escape(GENERATE_COVERAGE_ACTION)}@(?P<revision>[0-9a-f]{{40}})"
    )
    workflow_revisions = tuple(
        tuple(action_pattern.findall(path.read_text(encoding="utf-8")))
        for path in WORKFLOW_PATHS
    )

    assert workflow_revisions == (
        (GENERATE_COVERAGE_REVISION,),
        (GENERATE_COVERAGE_REVISION,),
    ), "CI coverage workflows must use the same exact generator revision"
