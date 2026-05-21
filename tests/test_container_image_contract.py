"""Tests for the production container image contract."""

import json
import os
import pathlib as pl
import shutil
import subprocess  # noqa: S404 - the opt-in smoke test drives Docker.

import pytest

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
DOCKERFILE_PATH = REPOSITORY_ROOT / "Dockerfile"
DOCKER_IMAGE_TAG = "episodic:contract-test"
CONTAINER_BIND_HOST = "0.0.0.0"  # noqa: S104 - container traffic must bind externally.


def _dockerfile_text() -> str:
    """Read the repository Dockerfile."""
    return DOCKERFILE_PATH.read_text(encoding="utf-8")


def _dockerfile_instruction(name: str) -> str:
    """Return the first Dockerfile instruction body matching ``name``."""
    prefix = f"{name} "
    for line in _dockerfile_text().splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    msg = f"Dockerfile instruction {name!r} was not found."
    raise AssertionError(msg)


def test_dockerfile_uses_multi_stage_python_build() -> None:
    """Build dependencies in one stage and run from a smaller Python image."""
    dockerfile = _dockerfile_text()

    assert (
        "FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder" in dockerfile
    ), "Dockerfile must build the wheel in a uv-backed Python 3.14 stage."
    assert "FROM python:3.14-slim AS runtime" in dockerfile, (
        "Dockerfile must run from a slim Python 3.14 runtime stage."
    )
    assert "COPY --from=builder /dist/*.whl /tmp/" in dockerfile, (
        "runtime stage must install the wheel built by the builder stage."
    )


def test_dockerfile_runs_granian_factory_as_non_root() -> None:
    """Keep the container command aligned with the runtime composition root."""
    from episodic.api import runtime

    command = json.loads(_dockerfile_instruction("CMD"))

    assert command == [
        "granian",
        runtime.GRANIAN_FACTORY_TARGET,
        "--interface",
        runtime.GRANIAN_INTERFACE,
        "--factory",
        "--host",
        CONTAINER_BIND_HOST,
        "--port",
        str(runtime.HTTP_BIND_PORT),
    ], f"unexpected container command: {command!r}"
    assert "USER 10001:10001" in _dockerfile_text(), (
        "runtime container must drop root before starting Granian."
    )


def test_dockerfile_exposes_stable_liveness_probe() -> None:
    """Expose the container port and liveness health check expected by k8s."""
    from episodic.api import runtime

    dockerfile = _dockerfile_text()

    assert _dockerfile_instruction("EXPOSE") == str(runtime.HTTP_BIND_PORT), (
        "Dockerfile must expose the configured HTTP bind port."
    )
    assert f"http://127.0.0.1:{runtime.HTTP_BIND_PORT}/health/live" in dockerfile, (
        "Docker health check must call the liveness endpoint on localhost."
    )
    assert "/health/ready" not in dockerfile, (
        "container health check must not depend on database readiness."
    )


def test_dockerignore_excludes_local_and_test_artifacts() -> None:
    """Keep local caches, tests, and operator scratch files out of the image."""
    ignored_paths = set(
        (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    )

    assert ".venv" in ignored_paths, (
        "virtual environments must not enter the build context."
    )
    assert ".uv-cache" in ignored_paths, "uv caches must not enter the build context."
    assert "tests" in ignored_paths, "tests must not enter the runtime build context."
    assert "docs/execplans" in ignored_paths, (
        "living planning documents must not enter the runtime build context."
    )


@pytest.mark.slow
def test_docker_image_serves_liveness_when_docker_smoke_enabled() -> None:
    """Build and run the image when explicitly enabled on a Docker host."""
    if os.environ.get("EPISODIC_RUN_DOCKER_TESTS") != "1":
        pytest.skip("set EPISODIC_RUN_DOCKER_TESTS=1 to run container smoke tests")
    docker_path = shutil.which("docker")
    if docker_path is None:
        pytest.skip("docker executable not found in PATH")

    from episodic.api import runtime

    build = subprocess.run(  # noqa: S603
        [docker_path, "build", "--tag", DOCKER_IMAGE_TAG, "."],
        check=False,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, (
        f"docker build failed\nstdout:\n{build.stdout}\nstderr:\n{build.stderr}"
    )

    run = subprocess.run(  # noqa: S603
        [
            docker_path,
            "run",
            "--rm",
            DOCKER_IMAGE_TAG,
            "python",
            "-c",
            (
                "from episodic.api import runtime; "
                "print(runtime.GRANIAN_FACTORY_TARGET); "
                "print(runtime.HTTP_BIND_PORT)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, (
        f"docker runtime probe failed\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}"
    )
    assert run.stdout.splitlines() == [
        runtime.GRANIAN_FACTORY_TARGET,
        str(runtime.HTTP_BIND_PORT),
    ], f"unexpected container runtime constants: {run.stdout!r}"
