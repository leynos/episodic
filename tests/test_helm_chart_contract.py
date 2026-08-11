"""Tests for the Episodic Helm chart contract."""

import pathlib as pl
import re
import shutil
import subprocess  # noqa: S404 - chart tests invoke the Helm CLI.
import typing as typ

import pytest
import yaml

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
CHART_PATH = REPOSITORY_ROOT / "charts" / "episodic"
LOCAL_VALUES_PATH = CHART_PATH / "values.local.yaml"


class _Metadata(typ.TypedDict):
    name: str


class _ConfigMap(typ.TypedDict):
    metadata: _Metadata
    data: dict[str, str]


class _SecretKeyRef(typ.TypedDict):
    name: str
    key: str
    optional: bool


class _ContainerValueFrom(typ.TypedDict):
    secretKeyRef: _SecretKeyRef


class _ContainerEnvironment(typ.TypedDict):
    name: str
    valueFrom: _ContainerValueFrom


class _ContainerEnvironmentFrom(typ.TypedDict):
    configMapRef: _Metadata


class _ContainerSecurityContext(typ.TypedDict):
    readOnlyRootFilesystem: bool
    allowPrivilegeEscalation: bool


class _ApplicationContainer(typ.TypedDict):
    name: str
    image: str
    imagePullPolicy: str
    envFrom: list[_ContainerEnvironmentFrom]
    env: list[_ContainerEnvironment]
    securityContext: _ContainerSecurityContext


class _PodSecurityContext(typ.TypedDict):
    runAsNonRoot: bool


class _PodSpec(typ.TypedDict):
    containers: list[_ApplicationContainer]
    securityContext: _PodSecurityContext


class _PodTemplate(typ.TypedDict):
    spec: _PodSpec


class _DeploymentSpec(typ.TypedDict):
    replicas: int
    template: _PodTemplate


class _Deployment(typ.TypedDict):
    spec: _DeploymentSpec


class _IngressServicePort(typ.TypedDict):
    name: str


class _IngressService(typ.TypedDict):
    name: str
    port: _IngressServicePort


class _IngressBackend(typ.TypedDict):
    service: _IngressService


class _IngressPath(typ.TypedDict):
    path: str
    pathType: str
    backend: _IngressBackend


class _IngressHttp(typ.TypedDict):
    paths: list[_IngressPath]


class _IngressRule(typ.TypedDict):
    host: str
    http: _IngressHttp


class _IngressSpec(typ.TypedDict):
    ingressClassName: str
    rules: list[_IngressRule]


class _Ingress(typ.TypedDict):
    spec: _IngressSpec


class _LocalResources(typ.TypedDict):
    ConfigMap: _ConfigMap
    Deployment: _Deployment
    Ingress: _Ingress


def _string_key_mapping(value: object, description: str) -> dict[str, object]:
    """Return a string-keyed mapping or fail with a chart-contract diagnostic."""
    match value:
        case dict() as mapping if all(isinstance(key, str) for key in mapping):
            return {
                key: typ.cast("object", item)
                for key, item in mapping.items()
                if isinstance(key, str)
            }
        case _:
            pytest.fail(f"{description} must be a string-keyed mapping: {value!r}")


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
    return re.sub(
        r"(?m)(^\s*checksum/config:\s*)[0-9a-f]{64}$",
        r"\1<checksum>",
        manifest,
    ).rstrip()


def test_helm_chart_lints() -> None:
    """Keep the chart valid under Helm's built-in checks."""
    output = _run_helm(["lint", str(CHART_PATH)])
    match = re.search(r"(?P<linted>\d+) chart\(s\) linted, (?P<failed>\d+)", output)

    assert match is not None, f"unexpected helm lint output: {output}"
    assert int(match["failed"]) == 0, f"unexpected helm lint failures: {output}"


def test_helm_local_manifest_snapshot(snapshot: SnapshotAssertion) -> None:
    """Capture the local preview manifest shape."""
    manifest = _redact_helm_checksums(_render_local_chart())
    assert manifest == snapshot, (
        "redacted local Helm manifest must match its recorded snapshot"
    )


def _local_resources() -> _LocalResources:
    """Return the rendered local manifest indexed by resource kind."""
    documents = [
        _string_key_mapping(typ.cast("object", document), "rendered Helm document")
        for document in yaml.safe_load_all(_render_local_chart())
        if document is not None
    ]
    resources: dict[str, dict[str, object]] = {}
    for document in documents:
        kind = document.get("kind")
        assert isinstance(kind, str), f"rendered Helm document lacks a kind: {document}"
        resources[kind] = document

    assert len(resources) == len(documents), (
        "the local manifest must render at most one resource of each kind; "
        f"got kinds {[document['kind'] for document in documents]}"
    )
    match resources:
        case {
            "ConfigMap": config_map,
            "Deployment": deployment,
            "Ingress": ingress,
        }:
            return {
                "ConfigMap": typ.cast("_ConfigMap", config_map),
                "Deployment": typ.cast("_Deployment", deployment),
                "Ingress": typ.cast("_Ingress", ingress),
            }
        case _:
            pytest.fail(
                "local manifest must contain ConfigMap, Deployment, and Ingress "
                f"resources: {resources}"
            )


def _container(deployment: _Deployment) -> _ApplicationContainer:
    """Return the sole application container of the rendered Deployment."""
    pod_spec = _string_key_mapping(
        typ.cast("object", deployment["spec"]["template"]["spec"]),
        "Deployment pod spec",
    )
    containers = pod_spec.get("containers")
    assert isinstance(containers, list), (
        f"the Deployment pod spec must contain a container list; got {pod_spec}"
    )
    typed_containers = [
        typ.cast("_ApplicationContainer", _string_key_mapping(container, "container"))
        for container in containers
    ]

    assert [container["name"] for container in typed_containers] == ["episodic"], (
        "the Deployment must render exactly one episodic container; "
        f"got {typed_containers}"
    )
    return typed_containers[0]


def test_helm_local_configmap_carries_the_preview_environment() -> None:
    """Nile Valley preview flows read EPISODIC_ENV from the local ConfigMap."""
    config_map = _local_resources()["ConfigMap"]

    assert config_map["metadata"]["name"] == "episodic", (
        f"the local ConfigMap must be named episodic; got {config_map['metadata']}"
    )
    assert config_map["data"] == {"EPISODIC_ENV": "local"}, (
        f"the local ConfigMap must expose only EPISODIC_ENV=local; "
        f"got {config_map['data']}"
    )


def test_helm_local_deployment_wires_the_preview_image_and_secret() -> None:
    """The local Deployment must run the preview image with its secret env."""
    deployment = _local_resources()["Deployment"]
    container = _container(deployment)

    assert deployment["spec"]["replicas"] == 1, (
        f"local previews must run a single replica; got {deployment['spec']}"
    )
    assert container["image"] == "localhost/episodic:local", (
        f"the local Deployment must use the locally built image; got {container}"
    )
    assert container["imagePullPolicy"] == "IfNotPresent", (
        f"local previews must not pull from a registry; got {container}"
    )
    assert container["envFrom"] == [{"configMapRef": {"name": "episodic"}}], (
        f"the container must source configuration from the ConfigMap; got {container}"
    )
    assert [variable["name"] for variable in container["env"]] == ["DATABASE_URL"], (
        f"the container must declare only DATABASE_URL; got {container['env']}"
    )
    secret_ref = container["env"][0]["valueFrom"]["secretKeyRef"]
    assert secret_ref["name"] == "episodic-local", (
        f"DATABASE_URL must come from the local secret; got {secret_ref}"
    )
    assert secret_ref["key"] == "database-url", (
        f"DATABASE_URL must read the database-url secret key; got {secret_ref}"
    )
    assert secret_ref["optional"] is False, (
        f"DATABASE_URL must be a required secret key; got {secret_ref}"
    )


def test_helm_local_deployment_hardens_the_container() -> None:
    """Preview parity requires the same security context as other environments."""
    deployment = _local_resources()["Deployment"]
    pod_security = deployment["spec"]["template"]["spec"]["securityContext"]
    container_security = _container(deployment)["securityContext"]

    assert pod_security["runAsNonRoot"] is True, (
        f"the pod must refuse to run as root; got {pod_security}"
    )
    assert container_security["readOnlyRootFilesystem"] is True, (
        f"the container root filesystem must be read only; got {container_security}"
    )
    assert container_security["allowPrivilegeEscalation"] is False, (
        f"the container must not allow privilege escalation; got {container_security}"
    )


def test_helm_local_ingress_publishes_the_preview_host() -> None:
    """Nile Valley previews reach the service through episodic.localhost."""
    ingress = _local_resources()["Ingress"]
    spec = ingress["spec"]

    assert spec["ingressClassName"] == "traefik", (
        f"local previews must be served by Traefik; got {spec}"
    )
    assert [rule["host"] for rule in spec["rules"]] == ["episodic.localhost"], (
        f"the Ingress must publish only episodic.localhost; got {spec['rules']}"
    )
    paths = spec["rules"][0]["http"]["paths"]

    assert [(path["path"], path["pathType"]) for path in paths] == [("/", "Prefix")], (
        f"the Ingress must expose a single / prefix path; got {paths}"
    )
    service = paths[0]["backend"]["service"]
    assert service["name"] == "episodic", (
        f"the Ingress must route to the episodic Service; got {service}"
    )
    assert service["port"] == {"name": "http"}, (
        f"the Ingress must target the named http port; got {service}"
    )


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
