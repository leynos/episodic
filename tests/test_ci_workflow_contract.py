"""Contract tests for main-owned CodeScene coverage publication."""

import pathlib as pl
import typing as typ

import yaml

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
CI_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
COVERAGE_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "coverage-main.yml"
GENERATE_COVERAGE_ACTION = (
    "leynos/shared-actions/.github/actions/generate-coverage@"
    "ac272c8de8d34b6b773274f7c1a11041e23cf1eb"
)
UPLOAD_COVERAGE_ACTION = (
    "leynos/shared-actions/.github/actions/upload-codescene-coverage@"
    "6b5cdc2d4c0bb72cafd5a66d24d248ac25827db9"
)
EXPECTED_GENERATE_COVERAGE_WITH = {
    "language": "python",
    "output-path": "coverage.xml",
    "format": "cobertura",
    "python-source": "episodic,alembic",
    "pytest-workers": "",
    "with-ratchet": "true",
}

Workflow = dict[typ.Any, typ.Any]


def _load_workflow(path: pl.Path) -> Workflow:
    """Load a workflow document as a mapping."""
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), f"{path.name} must contain a mapping"
    return workflow


def _triggers(workflow: Workflow, path: pl.Path) -> dict[str, typ.Any]:
    """Return the workflow's trigger mapping across PyYAML key semantics."""
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), f"{path.name} must declare an on: mapping"
    return triggers


def _jobs(workflow: Workflow, path: pl.Path) -> dict[str, Workflow]:
    """Return the workflow's typed jobs mapping."""
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), f"{path.name} must declare a jobs mapping"
    return typ.cast("dict[str, Workflow]", jobs)


def _job(workflow: Workflow, name: str, path: pl.Path) -> Workflow:
    """Return a named workflow job."""
    job = _jobs(workflow, path).get(name)
    assert isinstance(job, dict), f"{path.name} must declare jobs.{name}"
    return job


def _steps(job: Workflow, job_name: str, path: pl.Path) -> list[Workflow]:
    """Return a job's mapping-valued steps."""
    steps = job.get("steps")
    assert isinstance(steps, list), f"{path.name} jobs.{job_name}.steps must be a list"
    assert all(isinstance(step, dict) for step in steps), (
        f"{path.name} jobs.{job_name}.steps must contain mappings"
    )
    return typ.cast("list[Workflow]", steps)


def _named_step(job: Workflow, job_name: str, name: str, path: pl.Path) -> Workflow:
    """Return a named step from a job."""
    matches = [step for step in _steps(job, job_name, path) if step.get("name") == name]
    assert len(matches) == 1, (
        f"{path.name} jobs.{job_name} must contain one {name!r} step"
    )
    return matches[0]


def _contains_text(value: object, text: str) -> bool:
    """Return whether text occurs in a nested YAML value."""
    match value:
        case str():
            return text in value
        case dict():
            return any(
                _contains_text(key, text) or _contains_text(item, text)
                for key, item in value.items()
            )
        case list():
            return any(_contains_text(item, text) for item in value)
        case _:
            return False


def _assert_generate_coverage_step(step: Workflow, workflow_name: str) -> None:
    """Assert the shared action and the common Python ratchet inputs."""
    assert step.get("uses") == GENERATE_COVERAGE_ACTION, (
        f"{workflow_name} Generate coverage must use the pinned shared action"
    )
    with_block = step.get("with")
    assert isinstance(with_block, dict), (
        f"{workflow_name} Generate coverage must declare a with mapping"
    )
    for key, expected in EXPECTED_GENERATE_COVERAGE_WITH.items():
        assert with_block.get(key) == expected, (
            f"{workflow_name} Generate coverage with.{key} must be {expected!r}"
        )


def test_ci_coverage_is_pull_request_only_and_local() -> None:
    """Keep pull-request coverage local to the main-derived ratchet."""
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    triggers = _triggers(workflow, CI_WORKFLOW_PATH)
    assert "pull_request" in triggers, "ci.yml must trigger on pull requests"

    lint_test = _job(workflow, "lint-test", CI_WORKFLOW_PATH)
    generate = _named_step(
        lint_test, "lint-test", "Generate coverage", CI_WORKFLOW_PATH
    )
    _assert_generate_coverage_step(generate, "ci.yml")
    assert generate.get("if") == "github.event_name == 'pull_request'", (
        "ci.yml Generate coverage must run only for pull requests"
    )

    checkout_steps = [
        step
        for step in _steps(lint_test, "lint-test", CI_WORKFLOW_PATH)
        if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert checkout_steps, "ci.yml lint-test must check out the repository"
    assert all("fetch-depth" not in step.get("with", {}) for step in checkout_steps), (
        "ci.yml pull-request checkout must not request full history"
    )
    assert not _contains_text(workflow.get("env"), "CS_ACCESS_TOKEN"), (
        "ci.yml workflow env must not reference CS_ACCESS_TOKEN"
    )
    for job_name, job in _jobs(workflow, CI_WORKFLOW_PATH).items():
        assert not _contains_text(job.get("env"), "CS_ACCESS_TOKEN"), (
            f"ci.yml jobs.{job_name}.env must not reference CS_ACCESS_TOKEN"
        )
        for step in _steps(job, job_name, CI_WORKFLOW_PATH):
            assert not _contains_text(step.get("env"), "CS_ACCESS_TOKEN"), (
                f"ci.yml jobs.{job_name} step env must not reference CS_ACCESS_TOKEN"
            )

    assert not _contains_text(workflow, "upload-codescene-coverage"), (
        "ci.yml must not use the CodeScene coverage action"
    )
    assert not _contains_text(workflow, "https://api.codescene.io"), (
        "ci.yml must not contain a CodeScene project URL"
    )


def test_main_coverage_publishes_the_baseline() -> None:
    """Keep the main workflow as the sole CodeScene coverage publisher."""
    workflow = _load_workflow(COVERAGE_WORKFLOW_PATH)
    assert _triggers(workflow, COVERAGE_WORKFLOW_PATH) == {
        "push": {"branches": ["main"]},
        "workflow_dispatch": None,
    }, "coverage-main.yml must trigger only on pushes to main and dispatch"

    coverage_upload = _job(workflow, "coverage-upload", COVERAGE_WORKFLOW_PATH)
    generate = _named_step(
        coverage_upload,
        "coverage-upload",
        "Generate coverage",
        COVERAGE_WORKFLOW_PATH,
    )
    _assert_generate_coverage_step(generate, "coverage-main.yml")
    assert generate.get("with", {}).get("publish-baseline") == "always", (
        "coverage-main.yml Generate coverage must always publish the main baseline"
    )

    upload = _named_step(
        coverage_upload,
        "coverage-upload",
        "Upload coverage data to CodeScene",
        COVERAGE_WORKFLOW_PATH,
    )
    assert upload.get("uses") == UPLOAD_COVERAGE_ACTION, (
        "coverage-main.yml must use the pinned CodeScene upload action"
    )
    with_block = upload.get("with")
    assert isinstance(with_block, dict), "CodeScene upload must declare a with mapping"
    assert with_block.get("format") == "cobertura", (
        "CodeScene upload must use the Cobertura format"
    )
    assert with_block.get("path") == "coverage.xml", (
        "CodeScene upload must consume coverage.xml"
    )
    assert with_block.get("mode") == "upload", (
        "CodeScene upload must explicitly publish in upload mode"
    )

    assert not _contains_text(workflow.get("env"), "CS_ACCESS_TOKEN"), (
        "coverage-main.yml workflow env must not expose CS_ACCESS_TOKEN"
    )
    for job_name, job in _jobs(workflow, COVERAGE_WORKFLOW_PATH).items():
        if job_name == "coverage-upload":
            assert _contains_text(job.get("env"), "CS_ACCESS_TOKEN"), (
                "coverage-upload must expose CS_ACCESS_TOKEN to its upload step"
            )
        else:
            assert not _contains_text(job.get("env"), "CS_ACCESS_TOKEN"), (
                f"coverage-main.yml jobs.{job_name}.env must not expose CS_ACCESS_TOKEN"
            )
