"""Unit tests for no-QA behavioural-slice infrastructure."""

import asyncio
import typing as typ

import pytest

from tests.steps.no_qa_generation_slice_support import NoQaGenerationSliceContext


class _FailingLauncher:
    """Fail shutdown to exercise process cleanup after asynchronous failure."""

    async def shutdown(self) -> None:
        """Raise the controlled teardown failure."""
        msg = "launcher shutdown failed"
        raise RuntimeError(msg)


class _Process:
    """Record process cleanup calls."""

    terminated = False

    def terminate(self) -> None:
        """Record graceful termination."""
        self.terminated = True

    def wait(self, *, timeout: float) -> None:
        """Complete the graceful wait."""


def test_tear_down_terminates_vidai_mock_after_async_cleanup_failure() -> None:
    """The child process is terminated even when launcher shutdown raises."""
    process = _Process()
    with asyncio.Runner() as runner:
        context = NoQaGenerationSliceContext(
            session_factory=typ.cast("typ.Any", object()),
            runner=runner,
            process=typ.cast("typ.Any", process),
            launcher=typ.cast("typ.Any", _FailingLauncher()),
        )

        with pytest.raises(RuntimeError, match="launcher shutdown failed"):
            context.tear_down()

    assert process.terminated, "expected Vidai Mock termination after cleanup failure"
