"""Workflow integration tests for the GitOps bootstrap workflow."""

from pathlib import Path

import pytest

from tests.workflow_test_utils import read_artifact_json, run_act

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
    # Strict equality required: exit code contract demands explicit zero.
    assert code == 0, f"act failed:\n{logs}"  # pylint: disable=use-implicit-booleaness-not-comparison-to-zero

    data = read_artifact_json(artifact_dir, "bootstrap-result.json", logs)
    assert data["status"] == "ok"
    assert data["execution_mode"] == "validate"
