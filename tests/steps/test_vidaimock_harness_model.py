"""Bounded model-based coverage for Vidai Mock startup retries and cleanup."""

import dataclasses as dc
import io
import typing as typ
from pathlib import Path

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

import tests.steps.vidaimock_harness as harness

if typ.TYPE_CHECKING:
    import subprocess  # noqa: S404 - the controlled process models the harness API.

_OUTCOMES = ("bind", "exit", "timeout", "unexpected", "success")


class _FakeProcess:
    """Small process double exposing the operations used by cleanup."""

    def __init__(self, outcome: str) -> None:
        self.outcome = outcome
        self.returncode: int | None = {
            "bind": 1,
            "exit": 2,
        }.get(outcome)
        self.reaped = False
        self.terminated = False
        self.waited = False
        self.killed = False

    def poll(self) -> int | None:
        """Return the exit code and record the poll that reaps an exited child."""
        if self.returncode is not None:
            self.reaped = True
        return self.returncode

    def terminate(self) -> None:
        """Record graceful termination of a running fake child."""
        self.terminated = True

    def wait(self, *, timeout: float | None = None) -> int:
        """Reap a running fake child without waiting on wall-clock time."""
        del timeout
        self.waited = True
        if self.returncode is None:
            self.returncode = 0
        self.reaped = True
        return self.returncode

    def kill(self) -> None:
        """Record escalation when the harness requests a kill."""
        self.killed = True
        self.returncode = -9


def _expected_run(outcomes: list[str]) -> tuple[int, str, int]:
    """Model the first terminal outcome or bounded bind-retry exhaustion."""
    for index, outcome in enumerate(outcomes[: harness._VIDAIMOCK_PORT_START_ATTEMPTS]):
        if outcome != "bind":
            return index + 1, outcome, index
    final_index = harness._VIDAIMOCK_PORT_START_ATTEMPTS - 1
    return harness._VIDAIMOCK_PORT_START_ATTEMPTS, "bind", final_index


@dc.dataclass(slots=True)
class _LifecycleDoubles:
    """Fresh process and capture doubles for one generated lifecycle example."""

    outcomes: list[str]
    processes: list[_FakeProcess] = dc.field(default_factory=list)
    captures: list[io.StringIO] = dc.field(default_factory=list)
    startup_errors: list[harness.VidaiMockStartupError] = dc.field(default_factory=list)
    unexpected_error: RuntimeError = dc.field(
        default_factory=lambda: RuntimeError("unexpected readiness exception")
    )

    def install(self, patch: pytest.MonkeyPatch) -> None:
        """Patch only external acquisition and readiness around real retries."""
        patch.setattr(harness, "find_free_port", self._next_port)
        patch.setattr(harness.tempfile, "TemporaryFile", self._new_capture)
        patch.setattr(harness, "_start_once", self._start_once)
        patch.setattr(harness, "wait_for_port", self._wait_for_port)

    def _next_port(self) -> int:
        return 30000 + len(self.processes)

    def _new_capture(self, *, mode: str, encoding: str) -> io.StringIO:
        assert mode == "w+", f"expected a readable capture mode, got {mode!r}."
        assert encoding == "utf-8", (
            f"expected UTF-8 capture encoding, got {encoding!r}."
        )
        capture = io.StringIO()
        self.captures.append(capture)
        return capture

    def _start_once(
        self,
        launch: harness.VidaiMockLaunch,
        port: int,
        stderr_file: typ.TextIO,
    ) -> subprocess.Popen[str]:
        del launch, port, stderr_file
        process = _FakeProcess(self.outcomes[len(self.processes)])
        self.processes.append(process)
        return typ.cast("subprocess.Popen[str]", process)

    def _wait_for_port(self, server: harness.VidaiMockServer) -> None:
        process = typ.cast("_FakeProcess", server.process)
        outcome = process.outcome
        capture = typ.cast("io.StringIO", server.stderr_file)
        diagnostic = f"attempt-{len(self.processes)} {outcome} diagnostic"
        capture.write(diagnostic)
        match outcome:
            case "success":
                return
            case "unexpected":
                raise self.unexpected_error
            case "bind":
                error = harness.VidaiMockStartupError(
                    server.label,
                    "could not bind to the requested address",
                    returncode=process.returncode,
                    stderr=f"failed to bind: {diagnostic}",
                )
            case "exit":
                error = harness.VidaiMockStartupError(
                    server.label,
                    "exited before its port became reachable",
                    returncode=process.returncode,
                    stderr=diagnostic,
                )
            case "timeout":
                error = harness.VidaiMockStartupError(
                    server.label,
                    "did not accept a connection before timeout",
                    stderr=diagnostic,
                )
            case _:
                msg = f"unsupported generated readiness outcome: {outcome!r}."
                raise AssertionError(msg)
        self.startup_errors.append(error)
        raise error


def _assert_successful_start(
    launch: harness.VidaiMockLaunch,
    expected_attempts: int,
    doubles: _LifecycleDoubles,
) -> None:
    """Keep the successful child and capture alive until caller cleanup."""
    server = harness.start_vidaimock(launch)
    assert len(doubles.processes) == expected_attempts, (
        f"expected {expected_attempts} attempts before success, "
        f"got {len(doubles.processes)}."
    )
    process = doubles.processes[-1]
    capture = doubles.captures[-1]
    assert process.reaped is False, "successful startup must leave the child running."
    assert capture.closed is False, "successful startup must retain its stderr capture."
    assert server.process is typ.cast("subprocess.Popen[str]", process), (
        "the returned server must hold the successful child."
    )
    assert server.stderr_file is capture, (
        "the returned server must hold the successful stderr capture."
    )

    harness.terminate_process_gracefully(server.process, server.stderr_file)

    assert process.reaped is True, "caller cleanup must reap the successful child."
    assert capture.closed is True, "caller cleanup must close the successful capture."


def _assert_failed_start(
    launch: harness.VidaiMockLaunch,
    terminal: str,
    terminal_index: int,
    doubles: _LifecycleDoubles,
) -> None:
    """Check terminal propagation, bind exhaustion, and failed-child cleanup."""
    expected_type = (
        RuntimeError if terminal == "unexpected" else harness.VidaiMockStartupError
    )
    with pytest.raises(expected_type) as raised:
        harness.start_vidaimock(launch)

    assert all(process.reaped for process in doubles.processes), (
        "every failed startup attempt must reap its child."
    )
    assert all(capture.closed for capture in doubles.captures), (
        "every failed startup attempt must close its stderr capture."
    )
    match terminal:
        case "unexpected":
            assert raised.value is doubles.unexpected_error, (
                "unexpected readiness failures must propagate unchanged."
            )
        case "bind":
            expected_error = doubles.startup_errors[-1]
            final_attempt = harness._VIDAIMOCK_PORT_START_ATTEMPTS
            assert raised.value is expected_error, (
                "bind exhaustion must raise the final startup error."
            )
            assert terminal_index == final_attempt - 1, (
                "bind exhaustion must consume the configured attempt budget."
            )
            assert f"attempt-{final_attempt} bind diagnostic" in str(raised.value), (
                "bind exhaustion must preserve the final attempt diagnostics."
            )
        case _:
            expected_error = doubles.startup_errors[-1]
            assert raised.value is expected_error, (
                "terminal startup failures must propagate without retry."
            )
            assert len(doubles.processes) == terminal_index + 1, (
                "a terminal startup failure must prevent later launches."
            )


def _assert_retry_sequence(
    expected_attempts: int,
    doubles: _LifecycleDoubles,
) -> None:
    """Only bind failures may be followed by another launched attempt."""
    assert len(doubles.processes) == expected_attempts, (
        f"expected {expected_attempts} attempts, got {len(doubles.processes)}."
    )
    assert len(doubles.processes) <= harness._VIDAIMOCK_PORT_START_ATTEMPTS, (
        "startup attempts must never exceed the configured budget."
    )
    assert all(process.outcome == "bind" for process in doubles.processes[:-1]), (
        f"only bind failures may lead to another launch: "
        f"{[process.outcome for process in doubles.processes]!r}"
    )


@example(outcomes=["success", "bind", "exit", "timeout", "unexpected"])
@example(outcomes=["bind", "success", "exit", "timeout", "unexpected"])
@example(outcomes=["bind", "bind", "bind", "bind", "bind"])
@example(outcomes=["exit", "bind", "success", "timeout", "unexpected"])
@example(outcomes=["timeout", "bind", "success", "exit", "unexpected"])
@example(outcomes=["unexpected", "bind", "success", "exit", "timeout"])
@given(outcomes=st.lists(st.sampled_from(_OUTCOMES), min_size=5, max_size=5))
def test_start_vidaimock_matches_bounded_retry_and_cleanup_model(
    outcomes: list[str],
) -> None:
    """Retry only binds, stop at terminal results, and clean every failed child."""
    expected_attempts, terminal, terminal_index = _expected_run(outcomes)
    with pytest.MonkeyPatch.context() as patch:
        doubles = _LifecycleDoubles(outcomes)
        doubles.install(patch)

        launch = harness.VidaiMockLaunch(
            executable="unused-test-double",
            config_dir=Path(),
            label="the generated lifecycle case",
        )
        match terminal:
            case "success":
                _assert_successful_start(launch, expected_attempts, doubles)
            case _:
                _assert_failed_start(launch, terminal, terminal_index, doubles)
        _assert_retry_sequence(expected_attempts, doubles)
