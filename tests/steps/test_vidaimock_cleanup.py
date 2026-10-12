"""Exercise forced VidaiMock process cleanup without wall-clock waits."""

import io
import typing as typ
from unittest import mock

import pytest

import tests.steps.vidaimock_harness as harness

if typ.TYPE_CHECKING:
    import subprocess as subprocess_typing


def test_cleanup_kills_and_reaps_child_after_termination_timeout() -> None:
    """Escalate to kill and close stderr when the forced reap also times out."""
    process = mock.Mock()
    process.poll.return_value = None
    first_timeout = harness.subprocess.TimeoutExpired(
        "vidaimock", harness._VIDAIMOCK_TERMINATE_TIMEOUT
    )
    forced_reap_timeout = harness.subprocess.TimeoutExpired(
        "vidaimock", harness._VIDAIMOCK_TERMINATE_TIMEOUT
    )
    process.wait.side_effect = [first_timeout, forced_reap_timeout]
    stderr_capture = io.StringIO()

    with pytest.raises(harness.subprocess.TimeoutExpired) as raised:
        harness.terminate_process_gracefully(
            typ.cast("subprocess_typing.Popen[str]", process), stderr_capture
        )

    assert raised.value is forced_reap_timeout, (
        "the forced-reap timeout must propagate to the caller."
    )
    assert process.method_calls == [
        mock.call.poll(),
        mock.call.terminate(),
        mock.call.wait(timeout=harness._VIDAIMOCK_TERMINATE_TIMEOUT),
        mock.call.kill(),
        mock.call.wait(timeout=harness._VIDAIMOCK_TERMINATE_TIMEOUT),
    ], "a timed-out termination must be killed and waited on again."
    assert stderr_capture.closed, (
        "stderr must close even when forced reaping times out."
    )
