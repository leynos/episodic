"""Tests for transport-free health observation semantics."""

import asyncio
import collections.abc as cabc
import typing as typ

import pytest
from hypothesis import given
from hypothesis import strategies as st

type HealthProbe = cabc.Callable[[], cabc.Awaitable[bool]]


async def _probe_returns_true() -> bool:
    await asyncio.sleep(0)
    return True


async def _probe_returns_false() -> bool:
    await asyncio.sleep(0)
    return False


async def _probe_raises() -> bool:
    await asyncio.sleep(0)
    msg = "database unavailable"
    raise RuntimeError(msg)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("probe", "use_list", "expect_ok"),
    [
        (_probe_returns_true, False, True),
        (_probe_raises, False, False),
        (_probe_returns_false, False, False),
        (_probe_returns_true, True, True),
    ],
    ids=["success", "exception", "false-result", "iterable-pair"],
)
async def test_probe_health_observer_single_database_check(
    probe: HealthProbe,
    use_list: object,
    expect_ok: object,
) -> None:
    """Observe a single database probe across check shapes and outcomes."""
    from episodic.canonical.health import HealthStatus, ProbeHealthObserver

    checks_input: list[tuple[str, HealthProbe]] | dict[str, HealthProbe] = (
        [("database", probe)] if use_list is True else {"database": probe}
    )

    observer = ProbeHealthObserver.from_checks(typ.cast("typ.Any", checks_input))

    report = await observer.observe()

    expected = HealthStatus.OK if expect_ok is True else HealthStatus.ERROR
    assert report.status is expected, f"Expected overall status {expected!r}"
    assert [(check.name, check.status) for check in report.checks] == [
        ("database", expected)
    ], f"Expected database check to report {expected!r}"


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
