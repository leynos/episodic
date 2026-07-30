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


def _redact_helm_checksums(manifest: str) -> str:
    """Replace generated config checksums while preserving manifest structure."""
    redacted_manifest = re.sub(
        r"(?m)(^\s*checksum/config:\s*)[0-9a-f]{64}$",
        r"\1<checksum>",
        manifest,
    )
    return redacted_manifest.rstrip()


def test_helm_chart_lints() -> None:
    """Keep the chart valid under Helm's built-in checks."""
    output = _run_helm(["lint", str(CHART_PATH)])
    match = re.search(r"(?P<linted>\d+) chart\(s\) linted, (?P<failed>\d+)", output)

    assert match is not None, f"unexpected helm lint output: {output}"
    assert int(match["failed"]) == 0, f"unexpected helm lint failures: {output}"


def test_helm_local_manifest_snapshot(snapshot: SnapshotAssertion) -> None:
    """Capture the local preview manifest shape."""
    manifest = _redact_helm_checksums(_render_local_chart())
    assert manifest == snapshot, "Expected values to match"


def test_helm_local_manifest_includes_nile_valley_contract(
    snapshot: SnapshotAssertion,
) -> None:
    """Render the local values expected by Nile Valley preview flows."""
    manifest = _redact_helm_checksums(_render_local_chart())

    assert manifest == snapshot, "actual output must match snapshot"


def test_helm_external_secret_manifest_renders(snapshot: SnapshotAssertion) -> None:
    """Support ExternalSecret-backed deployments without fixed secret stores."""
    manifest = _redact_helm_checksums(
        _run_helm([
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
    )

    assert manifest == snapshot, "actual output must match snapshot"


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
