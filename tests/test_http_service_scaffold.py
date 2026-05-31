"""Tests for HTTP service dependency validation."""

import asyncio
import typing as typ

import pytest

import tests.test_http_service_scaffold_support as scaffold_support

if typ.TYPE_CHECKING:
    from episodic.api.dependencies import ReadinessProbe as ReadinessProbeType
    from episodic.api.types import UowFactory


def test_api_dependencies_require_callable_uow_factory() -> None:
    """Reject dependency objects without a canonical unit-of-work factory."""
    from episodic.api import ApiDependencies

    with pytest.raises(TypeError, match="uow_factory"):
        ApiDependencies(uow_factory=typ.cast("UowFactory", None))


def test_api_dependencies_require_authorization_port() -> None:
    """Reject authorization dependencies that do not implement the port."""
    from episodic.api import ApiDependencies

    with pytest.raises(TypeError, match="authorization"):
        ApiDependencies(
            uow_factory=scaffold_support.unexpected_uow_factory,
            authorization=typ.cast("typ.Any", object()),
        )


def test_readiness_probe_requires_async_check() -> None:
    """Reject sync readiness callbacks that would fail when awaited."""
    from episodic.api import ReadinessProbe

    def check_database() -> bool:
        return True

    with pytest.raises(TypeError, match="async callable"):
        ReadinessProbe(
            name="database",
            check=typ.cast("typ.Any", check_database),
        )


def test_api_dependencies_validate_readiness_probe_entries() -> None:
    """Reject malformed readiness probe objects at dependency construction."""
    from episodic.api import ApiDependencies

    async def check_database() -> bool:
        await asyncio.sleep(0)
        return True

    invalid_probe = typ.cast(
        "object",
        type(
            "_InvalidProbe",
            (),
            {"name": "database", "check": lambda: True},
        )(),
    )
    nameless_probe = typ.cast(
        "object",
        type("_NamelessProbe", (), {"check": check_database})(),
    )

    with pytest.raises(TypeError, match="async callable"):
        ApiDependencies(
            uow_factory=scaffold_support.unexpected_uow_factory,
            readiness_probes=(typ.cast("ReadinessProbeType", invalid_probe),),
        )

    with pytest.raises(TypeError, match="string name"):
        ApiDependencies(
            uow_factory=scaffold_support.unexpected_uow_factory,
            readiness_probes=(typ.cast("ReadinessProbeType", nameless_probe),),
        )
