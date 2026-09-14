"""Contract tests for the repository's Namespace runner assignments."""

import pathlib as pl
import typing as typ

import pytest
import yaml

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
WORKFLOWS_ROOT = REPOSITORY_ROOT / ".github" / "workflows"
NAMESPACE_RUNNER = "namespace-profile-default"

REPOSITORY_LINUX_JOBS = {
    "bootstrap-gitops-repo.yml": ("bootstrap",),
    "ci.yml": ("lint-test",),
    "coverage-main.yml": ("coverage-upload",),
    "get-codescene-sha.yml": ("refresh-sha",),
    "provision-doks.yml": ("provision",),
    "release.yml": ("pure-wheel", "release"),
}


def _load_workflow(filename: str) -> dict[typ.Any, typ.Any]:
    """Parse a workflow file and return its YAML mapping."""
    workflow = yaml.safe_load((WORKFLOWS_ROOT / filename).read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), f"{filename} must contain a mapping"
    return workflow


@pytest.mark.parametrize(
    ("filename", "job_names"),
    REPOSITORY_LINUX_JOBS.items(),
)
def test_repository_linux_jobs_use_namespace_runner(
    filename: str,
    job_names: tuple[str, ...],
) -> None:
    """Keep every repository-owned Linux job on the shared Namespace profile."""
    jobs = _load_workflow(filename).get("jobs")
    assert isinstance(jobs, dict), f"{filename} must declare jobs"

    for job_name in job_names:
        assert jobs[job_name]["runs-on"] == NAMESPACE_RUNNER, (
            f"{filename}:{job_name} must use {NAMESPACE_RUNNER!r}"
        )


def test_native_wheel_matrix_retains_github_hosted_runners() -> None:
    """Keep native wheel builds on their operating-system matrix runners."""
    jobs = _load_workflow("build-wheels.yml")["jobs"]
    matrix = jobs["build"]["strategy"]["matrix"]["include"]

    assert [entry["os"] for entry in matrix] == [
        "ubuntu-latest",
        "ubuntu-latest",
        "windows-latest",
        "windows-latest",
        "macos-latest",
        "macos-latest",
    ], "native wheel matrix must retain its six platform runner entries"
    assert jobs["build"]["runs-on"] == "${{ matrix.os }}", (
        "native wheel builds must resolve runs-on from the operating-system matrix"
    )


def test_actionlint_registers_namespace_runner_labels() -> None:
    """Keep actionlint aware of both supported Namespace runner labels."""
    config = yaml.safe_load(
        (REPOSITORY_ROOT / ".github" / "actionlint.yaml").read_text(encoding="utf-8")
    )

    assert config == {
        "self-hosted-runner": {
            "labels": [
                "namespace-profile-default",
                "namespace-profile-default-arm64",
            ]
        }
    }, "actionlint must register both supported Namespace runner labels"
