"""Typed shapes for the rendered Helm chart objects the contract tests read."""

import typing as typ


class Metadata(typ.TypedDict):
    """Name field shared by rendered metadata and object references."""

    name: str


class ConfigMap(typ.TypedDict):
    """Rendered ConfigMap with its metadata and string data."""

    metadata: Metadata
    data: dict[str, str]


class SecretKeyRef(typ.TypedDict):
    """Secret key reference with its optional flag."""

    name: str
    key: str
    optional: bool


class ContainerValueFrom(typ.TypedDict):
    """Value source that points at a secret key."""

    secretKeyRef: SecretKeyRef


class ContainerEnvironment(typ.TypedDict):
    """Environment variable entry sourced from a secret."""

    name: str
    valueFrom: ContainerValueFrom


class ContainerEnvironmentFrom(typ.TypedDict):
    """Environment source that references a ConfigMap by name."""

    configMapRef: Metadata


class ContainerSecurityContext(typ.TypedDict):
    """Container security context flags."""

    readOnlyRootFilesystem: bool
    allowPrivilegeEscalation: bool


class ApplicationContainer(typ.TypedDict):
    """Application container entry in a rendered pod spec."""

    name: str
    image: str
    imagePullPolicy: str
    envFrom: list[ContainerEnvironmentFrom]
    env: list[ContainerEnvironment]
    securityContext: ContainerSecurityContext


class PodSecurityContext(typ.TypedDict):
    """Pod security context flags."""

    runAsNonRoot: bool


class PodSpec(typ.TypedDict):
    """Pod spec with its containers and security context."""

    containers: list[ApplicationContainer]
    securityContext: PodSecurityContext


class PodTemplate(typ.TypedDict):
    """Pod template wrapping a pod spec."""

    spec: PodSpec


class DeploymentSpec(typ.TypedDict):
    """Deployment spec with its replica count and pod template."""

    replicas: int
    template: PodTemplate


class Deployment(typ.TypedDict):
    """Rendered Deployment with its spec."""

    spec: DeploymentSpec


class IngressServicePort(typ.TypedDict):
    """Named service port referenced by an ingress backend."""

    name: str


class IngressService(typ.TypedDict):
    """Service name and port referenced by an ingress backend."""

    name: str
    port: IngressServicePort


class IngressBackend(typ.TypedDict):
    """Ingress backend that points at a service."""

    service: IngressService


class IngressPath(typ.TypedDict):
    """HTTP path entry with its path type and backend."""

    path: str
    pathType: str
    backend: IngressBackend


class IngressHttp(typ.TypedDict):
    """HTTP block listing ingress paths."""

    paths: list[IngressPath]


class IngressRule(typ.TypedDict):
    """Ingress rule matching a host and its HTTP block."""

    host: str
    http: IngressHttp


class IngressSpec(typ.TypedDict):
    """Ingress spec with its class name and rules."""

    ingressClassName: str
    rules: list[IngressRule]


class Ingress(typ.TypedDict):
    """Rendered Ingress with its spec."""

    spec: IngressSpec


class LocalResources(typ.TypedDict):
    """Rendered local-preview resources keyed by kind."""

    ConfigMap: ConfigMap
    Deployment: Deployment
    Ingress: Ingress
