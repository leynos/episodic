"""Tests for transport-free health observation semantics."""

import asyncio
import typing as typ

import pytest
from hypothesis import given
from hypothesis import strategies as st


@pytest.mark.asyncio
async def test_probe_health_observer_reports_successful_checks() -> None:
    """Observe all configured checks without HTTP concepts."""
    from episodic.canonical.health import HealthStatus, ProbeHealthObserver

    async def database_ready() -> bool:
        await asyncio.sleep(0)
        return True

    observer = ProbeHealthObserver.from_checks({"database": database_ready})

    report = await observer.observe()

    assert report.status is HealthStatus.OK, (
        "Expected overall status OK for passing check"
    )
    assert [(check.name, check.status) for check in report.checks] == [
        ("database", HealthStatus.OK)
    ], "Expected database check to report OK status"


@pytest.mark.asyncio
async def test_probe_health_observer_treats_exceptions_as_failed_checks() -> None:
    """Convert unexpected readiness exceptions into failed observations."""
    from episodic.canonical.health import HealthStatus, ProbeHealthObserver

    async def database_ready() -> bool:
        await asyncio.sleep(0)
        msg = "database unavailable"
        raise RuntimeError(msg)

    observer = ProbeHealthObserver.from_checks({"database": database_ready})

    report = await observer.observe()

    assert report.status is HealthStatus.ERROR, (
        "Expected overall status ERROR when check raises exception"
    )
    assert [(check.name, check.status) for check in report.checks] == [
        ("database", HealthStatus.ERROR)
    ], "Expected database check to report ERROR status when check raises"


@pytest.mark.asyncio
async def test_probe_health_observer_treats_false_as_failed_check() -> None:
    """Convert explicit false probe results into failed observations."""
    from episodic.canonical.health import HealthStatus, ProbeHealthObserver

    async def database_ready() -> bool:
        await asyncio.sleep(0)
        return False

    observer = ProbeHealthObserver.from_checks({"database": database_ready})

    report = await observer.observe()

    assert report.status is HealthStatus.ERROR, (
        "Expected overall status ERROR for false check result"
    )
    assert [(check.name, check.status) for check in report.checks] == [
        ("database", HealthStatus.ERROR)
    ], "Expected database check to report ERROR status for false result"


@pytest.mark.asyncio
async def test_probe_health_observer_accepts_iterable_check_pairs() -> None:
    """Construct observers from iterable name/check pairs."""
    from episodic.canonical.health import HealthStatus, ProbeHealthObserver

    async def database_ready() -> bool:
        await asyncio.sleep(0)
        return True

    observer = ProbeHealthObserver.from_checks([("database", database_ready)])

    report = await observer.observe()

    assert report.status is HealthStatus.OK, (
        "Expected overall status OK for iterable check pair"
    )
    assert [(check.name, check.status) for check in report.checks] == [
        ("database", HealthStatus.OK)
    ], "Expected iterable database check to report OK status"


def test_probe_health_observer_rejects_invalid_check_names() -> None:
    """Require non-empty names at the health-port boundary."""
    from episodic.canonical.health import ProbeHealthObserver

    async def database_ready() -> bool:
        await asyncio.sleep(0)
        return True

    with pytest.raises(ValueError, match="non-empty"):
        ProbeHealthObserver.from_checks({" ": database_ready})


def test_probe_health_observer_rejects_non_async_checks() -> None:
    """Require asynchronous checks before observation begins."""
    from episodic.canonical.health import ProbeHealthObserver

    def database_ready() -> bool:
        return True

    invalid_checks = typ.cast("dict[str, typ.Any]", {"database": database_ready})

    with pytest.raises(TypeError, match="async callable"):
        ProbeHealthObserver.from_checks(invalid_checks)


@pytest.mark.asyncio
async def test_probe_health_observer_aggregates_mixed_check_results() -> None:
    """Report not-ready when any observed check fails."""
    from episodic.canonical.health import (
        HealthCheck,
        HealthReport,
        HealthStatus,
        ProbeHealthObserver,
    )

    async def database_ready() -> bool:
        await asyncio.sleep(0)
        return True

    async def queue_ready() -> bool:
        await asyncio.sleep(0)
        return False

    observer = ProbeHealthObserver.from_checks({
        "database": database_ready,
        "queue": queue_ready,
    })

    report = await observer.observe()

    assert report == HealthReport.from_checks((
        HealthCheck("database", HealthStatus.OK),
        HealthCheck("queue", HealthStatus.ERROR),
    )), "Expected mixed checks to aggregate to a not-ready health report"


@given(
    st.lists(
        st.booleans(),
        min_size=0,
        max_size=12,
    )
)
def test_health_report_status_is_ok_only_when_every_check_is_ok(
    probe_results: list[bool],
) -> None:
    """Aggregate readiness over a bounded range of check states."""
    from episodic.canonical.health import HealthCheck, HealthReport, HealthStatus

    checks = tuple(
        HealthCheck(
            name=f"check-{index}",
            status=HealthStatus.OK if result else HealthStatus.ERROR,
        )
        for index, result in enumerate(probe_results)
    )

    report = HealthReport.from_checks(checks)

    expected_status = HealthStatus.OK if all(probe_results) else HealthStatus.ERROR
    assert report.status is expected_status, (
        f"Expected status {expected_status} for probe results {probe_results}"
    )
