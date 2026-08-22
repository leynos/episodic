"""Tests for the Episodic Helm chart contract."""

import pathlib as pl
import re
import shutil
import subprocess  # noqa: S404 - chart tests invoke the Helm CLI.
import typing as typ

import pytest
import yaml

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
CHART_PATH = REPOSITORY_ROOT / "charts" / "episodic"
LOCAL_VALUES_PATH = CHART_PATH / "values.local.yaml"

# The boot-required runtime settings the local preview ConfigMap must carry.
_EXPECTED_LOCAL_CONFIGMAP_DATA = {
    "EPISODIC_ENV": "local",
    "SOURCE_INTAKE_OBJECT_STORE_ROOT": "/tmp/episodic-object-store",  # noqa: S108 - pod-local preview path.
    "PRICING_SNAPSHOT_DIRECTORY": "/app/config/pricing-snapshots",
    "API_AUTHORIZATION_PRINCIPAL_ID": "local-preview",
    "DRAFT_MODEL": "gpt-5.6-sol",
    "OPENAI_REASONING_EFFORT": "low",
    "OPENAI_TOKEN_LIMIT_PARAM": "max_completion_tokens",
    "OPENAI_TIMEOUT_SECONDS": "600",
    "GENERATION_MAX_OUTPUT_TOKENS": "32768",
}


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


@pytest.fixture(scope="module")
def local_chart_manifest() -> str:
    """Render the local preview chart once for its contract tests."""
    return _render_local_chart()


def test_helm_chart_lints() -> None:
    """Keep the chart valid under Helm's built-in checks."""
    output = _run_helm(["lint", str(CHART_PATH)])
    match = re.search(r"(?P<linted>\d+) chart\(s\) linted, (?P<failed>\d+)", output)

    assert match is not None, f"unexpected helm lint output: {output}"
    assert int(match["failed"]) == 0, f"unexpected helm lint failures: {output}"


def test_helm_local_manifest_has_required_resources(
    local_chart_manifest: str,
) -> None:
    """Render the local preview's required resource kinds."""
    resource_kinds = tuple(
        document["kind"]
        for document in yaml.safe_load_all(local_chart_manifest)
        if document is not None
    )
    assert resource_kinds == (
        "ServiceAccount",
        "ConfigMap",
        "Service",
        "Deployment",
        "Ingress",
    ), "local preview manifest must contain its required resource kinds"


def _local_resources(local_chart_manifest: str) -> _LocalResources:
    """Return the rendered local manifest indexed by resource kind."""
    documents = [
        _string_key_mapping(typ.cast("object", document), "rendered Helm document")
        for document in yaml.safe_load_all(local_chart_manifest)
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


def test_helm_local_configmap_carries_the_preview_environment(
    local_chart_manifest: str,
) -> None:
    """Nile Valley preview flows read EPISODIC_ENV from the local ConfigMap."""
    config_map = _local_resources(local_chart_manifest)["ConfigMap"]

    assert config_map["metadata"]["name"] == "episodic", (
        f"the local ConfigMap must be named episodic; got {config_map['metadata']}"
    )
    assert config_map["data"] == _EXPECTED_LOCAL_CONFIGMAP_DATA, (
        f"the local ConfigMap must expose the boot-required runtime settings; "
        f"got {config_map['data']}"
    )


def test_helm_local_deployment_wires_the_preview_image_and_secret(
    local_chart_manifest: str,
) -> None:
    """The local Deployment must run the preview image with its secret env."""
    deployment = _local_resources(local_chart_manifest)["Deployment"]
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
    env_by_name = {variable["name"]: variable for variable in container["env"]}
    assert set(env_by_name) == {
        "DATABASE_URL",
        "API_AUTHORIZATION_BEARER_TOKEN",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
    }, f"the container must declare the local secret env keys; got {container['env']}"
    expected_secret_keys = {
        "DATABASE_URL": ("database-url", False),
        "API_AUTHORIZATION_BEARER_TOKEN": ("api-bearer-token", False),
        "OPENAI_BASE_URL": ("openai-base-url", True),
        "OPENAI_API_KEY": ("openai-api-key", True),
    }
    for env_name, (secret_key, optional) in expected_secret_keys.items():
        secret_ref = env_by_name[env_name]["valueFrom"]["secretKeyRef"]
        assert secret_ref["name"] == "episodic-local", (
            f"{env_name} must come from the local secret; got {secret_ref}"
        )
        assert secret_ref["key"] == secret_key, (
            f"{env_name} must read the {secret_key} secret key; got {secret_ref}"
        )
        assert secret_ref["optional"] is optional, (
            f"{env_name} optionality must be {optional}; got {secret_ref}"
        )


def test_helm_local_deployment_hardens_the_container(
    local_chart_manifest: str,
) -> None:
    """Preview parity requires the same security context as other environments."""
    deployment = _local_resources(local_chart_manifest)["Deployment"]
    pod_security = deployment["spec"]["template"]["spec"]["securityContext"]
    container_security = _container(deployment)["securityContext"]

    assert pod_security["runAsNonRoot"] is True, (
        f"the pod must refuse to run as root; got {pod_security}"
    )
    assert container_security["readOnlyRootFilesystem"] is True, (
        f"the local container must keep the chart's read-only root filesystem; "
        f"got {container_security}"
    )
    assert container_security["allowPrivilegeEscalation"] is False, (
        f"the container must not allow privilege escalation; got {container_security}"
    )
    pod_spec = _string_key_mapping(
        typ.cast("object", deployment["spec"]["template"]["spec"]),
        "Deployment pod spec",
    )
    assert pod_spec.get("volumes") == [{"name": "tmp", "emptyDir": {}}], (
        f"the local pod must carry the tmp emptyDir volume; got {pod_spec}"
    )
    container_mounts = _string_key_mapping(
        typ.cast("object", _container(deployment)),
        "container",
    ).get("volumeMounts")
    assert container_mounts == [{"name": "tmp", "mountPath": "/tmp"}], (  # noqa: S108 - pod-local emptyDir mount path.
        f"the container must mount the tmp emptyDir at /tmp for the "
        f"source-intake object store; got {container_mounts}"
    )


def test_helm_local_ingress_publishes_the_preview_host(
    local_chart_manifest: str,
) -> None:
    """Nile Valley previews reach the service through episodic.localhost."""
    ingress = _local_resources(local_chart_manifest)["Ingress"]
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
