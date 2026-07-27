"""Workflow integration tests for the GitOps bootstrap workflow."""

from pathlib import Path

import pytest

from tests.test_workflow_utils import assert_validation_workflow_result, run_act

EVENT = Path("tests/fixtures/bootstrap_gitops_repo.event.json")


@pytest.mark.act
def test_bootstrap_gitops_repo_workflow(tmp_path: Path) -> None:
    """Assert that the bootstrap workflow produces a success result."""
    artifact_dir = tmp_path / "act-artifacts"
    code, logs = run_act(
        job_name="bootstrap",
        artifact_dir=artifact_dir,
        event_path=EVENT,
    )
    assert_validation_workflow_result(
        code,
        logs,
        artifact_dir,
        "bootstrap-result.json",
    )
