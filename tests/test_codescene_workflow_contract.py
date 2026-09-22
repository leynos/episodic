"""Contracts for default-branch CodeScene coverage publication.

Pull requests execute arbitrary head-repository code. They enforce coverage
with the shared generator's local ratchet and never contact CodeScene; only a
default-branch push may upload the measured report.

Coverage is scoped to the application and migration packages, as the Slipcover
command this workflow replaced was. The scope is asserted rather than left to
the generator's discovery, because an unscoped run measures the test suite
alongside the code it exercises and omits a production module no test imports.
"""

import json
import typing as typ

from tests.test_codescene_workflow_contract_support import (
    REPOSITORY_ROOT,
    WORKFLOWS_DIRECTORY,
    Mapping,
    Step,
    all_workflow_steps,
    load_workflow,
    mapping,
    named_step,
    trigger_config,
    workflow_jobs,
    workflow_paths,
    workflow_steps,
    workflow_triggers,
    workflow_uses,
)

if typ.TYPE_CHECKING:
    import pathlib as pl

CI_WORKFLOW = WORKFLOWS_DIRECTORY / "ci.yml"
COVERAGE_MAIN_WORKFLOW = WORKFLOWS_DIRECTORY / "coverage-main.yml"
CI_JOB = "lint-test"
COVERAGE_MAIN_JOB = "coverage-upload"
GENERATE_COVERAGE_ACTION = "leynos/shared-actions/.github/actions/generate-coverage"
UPLOAD_CODESCENE_ACTION = (
    "leynos/shared-actions/.github/actions/upload-codescene-coverage"
)
APPROVED_REVISION = "dbe2e22ceaf498d85512679ccded38be9dbe7777"
ON_MAIN = "github.ref == 'refs/heads/main'"
UPLOAD_GUARD = f"{ON_MAIN} && env.CS_ACCESS_TOKEN != ''"
MAIN_PUSH_TRIGGER = {"branches": ["main"]}
ACTION_REVISIONS = (
    REPOSITORY_ROOT / "tests" / "support" / "approved_action_revisions.json"
)
TRACKED_ACTIONS = frozenset({GENERATE_COVERAGE_ACTION, UPLOAD_CODESCENE_ACTION})
PULL_REQUEST_TRIGGERS = frozenset({"pull_request", "pull_request_target"})
CODESCENE_ACCESS_ENV = "CS_ACCESS_TOKEN"
CODESCENE_HOST = "codescene.io"
PRODUCTION_SOURCE_SCOPE = "episodic,alembic"
EXPECTED_UPLOAD_INPUTS = {
    "format": "cobertura",
    "mode": "upload",
    "path": "coverage.xml",
    "access-token": "${{ env.CS_ACCESS_TOKEN }}",
}


def _codescene_contacts() -> list[tuple[pl.Path, str, Step]]:
    """Return steps that call the CodeScene action or its command-line client."""
    contacts = []
    for workflow_path, job_name, step in all_workflow_steps():
        calls_action = UPLOAD_CODESCENE_ACTION in str(step.get("uses", ""))
        invokes_client = "cs-coverage" in str(step.get("run", ""))
        if calls_action or invokes_client:
            contacts.append((workflow_path, job_name, step))
    return contacts


def _revision_fixture() -> Mapping:
    """Return the offline approved-action and retired-pin record."""
    fixture = json.loads(ACTION_REVISIONS.read_text(encoding="utf-8"))
    return mapping(fixture, subject="approved action revisions fixture")


def test_workflow_yaml_is_parseable() -> None:
    """Every repository workflow must remain valid YAML."""
    for workflow_path in workflow_paths():
        _ = load_workflow(workflow_path)


def test_codescene_is_contacted_only_from_a_default_branch_push() -> None:
    """One default-branch-guarded upload is the sole CodeScene contact."""
    contacts = _codescene_contacts()
    assert len(contacts) == 1, f"expected one CodeScene contact, found {contacts!r}"

    workflow_path, job_name, upload = contacts[0]
    assert workflow_path == COVERAGE_MAIN_WORKFLOW, (
        "only coverage-main.yml may contact CodeScene"
    )
    assert job_name == COVERAGE_MAIN_JOB, (
        "only the default-branch coverage job may upload"
    )
    assert upload["name"] == "Upload coverage data to CodeScene", (
        "upload step label drifted"
    )
    assert upload["uses"] == f"{UPLOAD_CODESCENE_ACTION}@{APPROVED_REVISION}", (
        "CodeScene upload must use the approved shared action revision"
    )
    assert upload["if"] == UPLOAD_GUARD, (
        "upload must be guarded by the default branch and a token"
    )
    assert mapping(upload["env"], subject="CodeScene upload environment") == {
        "CS_ACCESS_TOKEN": "${{ secrets.CS_ACCESS_TOKEN }}"
    }, "upload must expose only the repository secret as its step environment"


def test_default_branch_upload_uses_the_measured_cobertura_report() -> None:
    """The upload must publish the report generated in its own job."""
    upload = named_step(
        COVERAGE_MAIN_WORKFLOW,
        COVERAGE_MAIN_JOB,
        "Upload coverage data to CodeScene",
    )
    upload_inputs = mapping(upload["with"], subject="CodeScene upload inputs")
    assert upload_inputs == EXPECTED_UPLOAD_INPUTS, (
        "upload must use the measured Cobertura report"
    )

    step_names = [
        step.get("name")
        for step in workflow_steps(COVERAGE_MAIN_WORKFLOW, COVERAGE_MAIN_JOB)
    ]
    assert step_names.index("Generate coverage") < step_names.index(
        "Upload coverage data to CodeScene"
    ), "coverage must be generated before it is uploaded"


def test_pull_requests_enforce_coverage_with_the_local_ratchet() -> None:
    """Both coverage jobs use the reviewed ratcheting generator revision."""
    main_coverage = named_step(
        COVERAGE_MAIN_WORKFLOW, COVERAGE_MAIN_JOB, "Generate coverage"
    )
    pull_request_coverage = named_step(CI_WORKFLOW, CI_JOB, "Generate coverage")
    for coverage in (main_coverage, pull_request_coverage):
        assert coverage["uses"] == f"{GENERATE_COVERAGE_ACTION}@{APPROVED_REVISION}", (
            "coverage must use the approved shared generator revision"
        )
        inputs = mapping(coverage["with"], subject="coverage generation inputs")
        assert inputs["language"] == "python", "coverage must use the Python runner"
        assert inputs["format"] == "cobertura", "coverage must produce Cobertura output"
        assert inputs["output-path"] == "coverage.xml", "coverage output path drifted"
        assert inputs["with-ratchet"] == "true", "coverage ratchet must be enabled"
        assert not inputs["pytest-workers"], (
            "coverage must preserve serial pytest execution"
        )
        assert inputs["python-source"] == PRODUCTION_SOURCE_SCOPE, (
            "coverage must measure the application and migration packages only"
        )

    main_inputs = mapping(main_coverage["with"], subject="main coverage inputs")
    assert main_inputs["publish-baseline"] == "always", (
        "manual default-branch dispatches must refresh the baseline"
    )
    pull_request_inputs = mapping(
        pull_request_coverage["with"], subject="pull-request coverage inputs"
    )
    assert "publish-baseline" not in pull_request_inputs, (
        "the shared action's safe auto default must keep pull requests from "
        "publishing a baseline"
    )
    assert pull_request_coverage["if"] == "github.event_name == 'pull_request'", (
        "pull-request coverage must remain scoped to pull requests"
    )


def test_always_publish_is_restricted_to_main() -> None:
    """Manual dispatches may save the baseline only when they run on main."""
    main_job = mapping(
        workflow_jobs(COVERAGE_MAIN_WORKFLOW)[COVERAGE_MAIN_JOB],
        subject="default-branch coverage job",
    )
    assert main_job["if"] == "github.ref == 'refs/heads/main'", (
        "always publishing must be restricted to the default branch"
    )


def test_coverage_jobs_use_read_only_repository_tokens() -> None:
    """Coverage generation and upload do not require repository write access."""
    for workflow_path, job_name in (
        (CI_WORKFLOW, CI_JOB),
        (COVERAGE_MAIN_WORKFLOW, COVERAGE_MAIN_JOB),
    ):
        job = mapping(workflow_jobs(workflow_path)[job_name], subject=f"{job_name} job")
        assert job["permissions"] == {"contents": "read"}, (
            f"{job_name} needs only read access to repository contents"
        )


def test_no_checksum_or_changed_line_gate_machinery_remains() -> None:
    """The caller must not maintain a digest or request a CodeScene check."""
    assert not (WORKFLOWS_DIRECTORY / "get-codescene-sha.yml").exists(), (
        "the obsolete checksum-refresh workflow must be deleted"
    )
    forbidden = (
        "CODESCENE_CLI_SHA256",
        "installer-checksum",
        "archive-checksum",
        "project-url",
        "mode: check",
    )
    for workflow_path in workflow_paths():
        text = workflow_path.read_text(encoding="utf-8")
        for item in forbidden:
            assert item not in text, f"{workflow_path} must not contain {item}"


def test_ci_checkout_no_longer_fetches_history_for_codescene() -> None:
    """CI's ordinary checkout no longer fetches history for the removed check."""
    checkout = named_step(CI_WORKFLOW, CI_JOB, "Check out repository")
    checkout_inputs = mapping(checkout.get("with", {}), subject="CI checkout inputs")
    assert "fetch-depth" not in checkout_inputs, (
        "CI needs no full history after removing the changed-line check"
    )


def test_every_codescene_upload_uses_the_approved_full_sha() -> None:
    """The upload action must remain on the approved immutable revision."""
    references = [
        revision
        for action, revision in workflow_uses()
        if action == UPLOAD_CODESCENE_ACTION
    ]
    assert references == [APPROVED_REVISION], (
        "every CodeScene upload must use the approved full SHA"
    )


def test_tracked_composites_carry_no_retired_dependency() -> None:
    """Offline records must reject selected composites that reach retired pins."""
    fixture = _revision_fixture()
    retired = mapping(fixture["retired"], subject="retired action pins")
    approved = mapping(fixture["approved"], subject="approved action pins")

    tracked_references = [
        (action, revision)
        for action, revision in workflow_uses()
        if action in TRACKED_ACTIONS
    ]
    assert tracked_references, (
        "coverage workflows must reference tracked shared actions"
    )
    for action, revision in tracked_references:
        action_revisions = mapping(approved.get(action), subject=f"approved {action}")
        assert revision in action_revisions, (
            f"{action}@{revision} is not recorded in "
            f"{ACTION_REVISIONS.relative_to(REPOSITORY_ROOT)}"
        )
        details = mapping(action_revisions[revision], subject=f"{action}@{revision}")
        nested_uses = mapping(
            details["nested_uses"], subject=f"{action}@{revision} dependencies"
        )
        for dependency in nested_uses:
            assert dependency not in retired, (
                f"{action}@{revision} reaches retired dependency {dependency}"
            )


def test_retired_pins_do_not_reappear_in_workflows() -> None:
    """Every retired pin in the checked-in record remains absent from workflows."""
    retired = mapping(_revision_fixture()["retired"], subject="retired action pins")
    for workflow_path in workflow_paths():
        text = workflow_path.read_text(encoding="utf-8")
        for pin in retired:
            assert str(pin) not in text, f"{workflow_path} references retired pin {pin}"


def test_the_publisher_serves_no_pull_request() -> None:
    """The uploading workflow answers default-branch events only.

    A workflow that both publishes and serves pull requests would be required
    to upload and forbidden from uploading at once.
    """
    triggers = workflow_triggers(COVERAGE_MAIN_WORKFLOW)
    assert triggers == frozenset({"push", "workflow_dispatch"}), (
        "the publisher must answer only a main push or a dispatch, got "
        f"{sorted(triggers)}"
    )
    assert trigger_config(COVERAGE_MAIN_WORKFLOW, "push") == MAIN_PUSH_TRIGGER, (
        "the publisher's push trigger must be restricted to the default branch"
    )


def test_pull_request_workflows_never_receive_the_codescene_token() -> None:
    """No workflow reachable from a fork's head may hold the CodeScene token."""
    pull_request_workflows = [
        path
        for path in workflow_paths()
        if workflow_triggers(path) & PULL_REQUEST_TRIGGERS
    ]
    assert CI_WORKFLOW in pull_request_workflows, (
        "the pull-request lane must be enumerated, or this contract asserts nothing"
    )
    contacts = {path for path, _, _ in _codescene_contacts()}
    for path in pull_request_workflows:
        assert path not in contacts, (
            f"{path} serves pull requests and contacts CodeScene"
        )
        text = path.read_text(encoding="utf-8")
        assert CODESCENE_ACCESS_ENV not in text, (
            f"{path} serves pull requests and must not reference {CODESCENE_ACCESS_ENV}"
        )
        # A step could reach the service without the action, the client or the
        # token name, for instance by curling the project API. Forbid the host
        # itself, so the lane is closed rather than only its known doors. The
        # comparison folds case because DNS names do; the token check above does
        # not, because an environment variable name is case-sensitive.
        assert CODESCENE_HOST not in text.casefold(), (
            f"{path} serves pull requests and must not reference {CODESCENE_HOST}"
        )
