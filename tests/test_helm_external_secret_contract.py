"""Tests for Helm ExternalSecret rendering contracts."""

import re
import typing as typ

from tests.test_helm_chart_contract import CHART_PATH, _run_helm

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


def _redact_helm_checksums(manifest: str) -> str:
    """Replace generated config checksums while preserving manifest structure."""
    return re.sub(
        r"(?m)(^\s*checksum/config:\s*)[0-9a-f]{64}$",
        r"\1<checksum>",
        manifest,
    ).rstrip()


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
