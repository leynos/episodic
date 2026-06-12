"""Tests for the Episodic Helm chart contract."""

import pathlib as pl
import re
import shutil
import subprocess  # noqa: S404 - chart tests invoke the Helm CLI.
import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
CHART_PATH = REPOSITORY_ROOT / "charts" / "episodic"
LOCAL_VALUES_PATH = CHART_PATH / "values.local.yaml"


def _helm_path() -> str:
    """Return the Helm executable path or skip when it is unavailable."""
    helm_path = shutil.which("helm")
    if helm_path is None:
        pytest.skip("helm executable not found in PATH")
    return helm_path


def _run_helm(args: list[str]) -> str:
    """Run Helm and return stdout, failing with useful stderr on errors."""
    result = subprocess.run(  # noqa: S603 - trusted Helm CLI args from tests.
        [_helm_path(), *args],
        check=False,
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"helm {' '.join(args)} failed\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result.stdout


def _render_local_chart() -> str:
    """Render the chart with local preview values."""
    return _run_helm([
        "template",
        "episodic",
        str(CHART_PATH),
        "--values",
        str(LOCAL_VALUES_PATH),
    ])


def test_helm_chart_lints() -> None:
    """Keep the chart valid under Helm's built-in checks."""
    output = _run_helm(["lint", str(CHART_PATH)])
    match = re.search(r"(?P<linted>\d+) chart\(s\) linted, (?P<failed>\d+)", output)

    assert match is not None, f"unexpected helm lint output: {output}"
    assert int(match["failed"]) == 0, f"unexpected helm lint failures: {output}"


def test_helm_local_manifest_snapshot(snapshot: SnapshotAssertion) -> None:
    """Capture the local preview manifest shape."""
    assert _render_local_chart() == snapshot


def test_helm_local_manifest_includes_nile_valley_contract() -> None:
    """Render the local values expected by Nile Valley preview flows."""
    manifest = _render_local_chart()

    assert "kind: Deployment" in manifest, "local render must include a Deployment."
    assert "kind: Service" in manifest, "local render must include a Service."
    assert "kind: ConfigMap" in manifest, "local render must include a ConfigMap."
    assert "kind: Ingress" in manifest, "local render must include an Ingress."
    assert 'image: "episodic:local"' in manifest, "local image tag must render."
    assert "path: /health/live" in manifest, "liveness probe path must render."
    assert "path: /health/ready" in manifest, "readiness probe path must render."
    assert "name: episodic-local" in manifest, "existing Secret reference must render."
    assert "optional: false" in manifest, "local secrets must be required."
    assert "checksum/config:" in manifest, (
        "ConfigMap-backed env vars must trigger pod rollout on config changes."
    )


def test_helm_external_secret_manifest_renders() -> None:
    """Support ExternalSecret-backed deployments without fixed secret stores."""
    manifest = _run_helm([
        "template",
        "episodic",
        str(CHART_PATH),
        "--set",
        "externalSecret.enabled=true",
        "--set",
        "externalSecret.secretStoreRef.name=vault",
        "--set",
        "externalSecret.creationPolicy=Merge",
        "--set",
        "externalSecret.data.database-url.key=episodic/database",
        "--set",
        "externalSecret.data.database-url.property=url",
        "--set",
        "existingSecretName=",
    ])

    assert "kind: ExternalSecret" in manifest, (
        "ExternalSecret must render when enabled."
    )
    assert "name: vault" in manifest, "secret store reference must render."
    assert "creationPolicy: Merge" in manifest, (
        "ExternalSecret creation policy must be configurable."
    )
    assert "secretKey: database-url" in manifest, "ExternalSecret data key must render."
    assert "property: url" in manifest, "remote secret property must render."


def test_helm_explicit_required_secret_overrides_missing_secret_fallback() -> None:
    """Preserve explicit optional=false when allowMissingSecret is true."""
    manifest = _run_helm([
        "template",
        "episodic",
        str(CHART_PATH),
        "--set",
        "allowMissingSecret=true",
        "--set",
        "secretEnvFromKeys.DATABASE_URL.optional=false",
    ])

    assert "optional: false" in manifest, (
        "explicit per-secret optional=false must survive Helm rendering."
    )
