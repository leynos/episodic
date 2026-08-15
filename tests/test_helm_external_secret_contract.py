"""Tests for Helm ExternalSecret rendering contracts."""

import re
import typing as typ

import yaml

from tests.test_helm_chart_contract import (
    CHART_PATH,
    _container,
    _run_helm,
    _string_key_mapping,
)

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

    from tests.test_helm_chart_contract import _Deployment


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

    documents = [
        _string_key_mapping(typ.cast("object", document), "rendered Helm document")
        for document in yaml.safe_load_all(manifest)
        if document is not None
    ]
    deployments = [
        document for document in documents if document.get("kind") == "Deployment"
    ]
    assert len(deployments) == 1, "Helm rendering must contain exactly one Deployment"

    container = _container(typ.cast("_Deployment", deployments[0]))
    database_url_entries = [
        entry for entry in container["env"] if entry["name"] == "DATABASE_URL"
    ]

    assert len(database_url_entries) == 1, (
        "Deployment must render exactly one DATABASE_URL environment entry."
    )
    assert database_url_entries[0]["valueFrom"]["secretKeyRef"]["optional"] is False, (
        "DATABASE_URL must preserve explicit optional=false in its secret reference."
    )
