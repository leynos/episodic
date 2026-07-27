"""Workflow integration tests for the DOKS provisioning workflow."""

from pathlib import Path

import pytest

from tests.test_workflow_utils import assert_validation_workflow_result, run_act

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
    assert_validation_workflow_result(
        code,
        logs,
        artifact_dir,
        "provision-result.json",
    )
