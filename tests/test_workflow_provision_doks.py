"""Workflow integration tests for the DOKS provisioning workflow."""

from pathlib import Path

import pytest

from tests.workflow_test_utils import read_artifact_json, run_act

EVENT = Path("tests/fixtures/provision_doks.event.json")


@pytest.mark.act
def test_provision_doks_workflow(tmp_path: Path) -> None:
    """Assert that the provisioning workflow produces a success result."""
    artifact_dir = tmp_path / "act-artifacts"
    code, logs = run_act(
        job_name="provision",
        artifact_dir=artifact_dir,
        event_path=EVENT,
    )
    # Strict equality required: exit code contract demands explicit zero.
    assert code == 0, f"act failed:\n{logs}"  # pylint: disable=use-implicit-booleaness-not-comparison-to-zero

    data = read_artifact_json(artifact_dir, "provision-result.json", logs)
    assert data["status"] == "ok"
    assert data["execution_mode"] == "validate"
