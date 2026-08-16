"""Contract tests for CI workflow coverage configuration."""

import pathlib as pl
import re

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
WORKFLOW_PATHS = (
    REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml",
    REPOSITORY_ROOT / ".github" / "workflows" / "coverage-main.yml",
)
SLIPCOVER_REQUIREMENT = "slipcover==1.0.18"
SLIPCOVER_COMMAND_RE = re.compile(
    r"uv run --with '(?P<requirement>slipcover[^']+)' python -m slipcover"
)


def test_coverage_workflows_pin_the_same_slipcover_version() -> None:
    """Keep pull-request and main coverage runs on the reviewed Slipcover release."""
    workflow_requirements = tuple(
        tuple(SLIPCOVER_COMMAND_RE.findall(path.read_text(encoding="utf-8")))
        for path in WORKFLOW_PATHS
    )

    assert workflow_requirements == (
        (SLIPCOVER_REQUIREMENT,),
        (SLIPCOVER_REQUIREMENT,),
    ), "CI coverage workflows must use the same exact Slipcover version"
