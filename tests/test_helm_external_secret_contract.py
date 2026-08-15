"""Tests for Helm ExternalSecret rendering contracts."""

import typing as typ

import pytest
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


@pytest.fixture(scope="module")
def external_secret_manifest() -> str:
    """Render the chart with its ExternalSecret integration enabled."""
    return _run_helm([
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


def _rendered_resources(manifest: str) -> dict[str, dict[str, object]]:
    """Index the unique rendered Helm resources by kind."""
    resources: dict[str, dict[str, object]] = {}
    for document in yaml.safe_load_all(manifest):
        if document is None:
            continue
        resource = _string_key_mapping(
            typ.cast("object", document),
            "rendered Helm document",
        )
        kind = resource.get("kind")
        assert isinstance(kind, str), f"rendered Helm document lacks a kind: {resource}"
        assert kind not in resources, f"Helm rendering must not duplicate {kind}"
        resources[kind] = resource
    return resources


def test_helm_external_secret_manifest_renders(
    external_secret_manifest: str,
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot only the configured ExternalSecret contract."""
    external_secret = _rendered_resources(external_secret_manifest).get(
        "ExternalSecret"
    )
    assert external_secret is not None, "Helm rendering must contain an ExternalSecret"
    metadata = _string_key_mapping(external_secret.get("metadata"), "metadata")
    spec = _string_key_mapping(external_secret.get("spec"), "ExternalSecret spec")

    external_secret_contract = {
        "apiVersion": external_secret.get("apiVersion"),
        "kind": external_secret.get("kind"),
        "metadata": {"name": metadata.get("name")},
        "spec": spec,
    }

    assert external_secret_contract == snapshot, (
        "ExternalSecret contract must match its snapshot"
    )


def test_helm_external_secret_wires_database_url(
    external_secret_manifest: str,
) -> None:
    """Wire DATABASE_URL to the ExternalSecret target secret."""
    deployment = _rendered_resources(external_secret_manifest).get("Deployment")
    assert deployment is not None, "Helm rendering must contain a Deployment"
    container = _container(typ.cast("_Deployment", deployment))
    database_url_entries = [
        entry for entry in container["env"] if entry["name"] == "DATABASE_URL"
    ]

    assert len(database_url_entries) == 1, (
        "Deployment must render exactly one DATABASE_URL environment entry."
    )
    assert database_url_entries[0]["valueFrom"]["secretKeyRef"] == {
        "name": "episodic",
        "key": "database-url",
        "optional": False,
    }, "DATABASE_URL must reference the ExternalSecret target"


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
