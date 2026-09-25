"""Focused tests for the shared Vidai Mock startup harness.

The harness is exercised on its own, without a real Vidai Mock binary. Its
failure paths are the ones a live-server scenario would otherwise reach only by
accident: a child that exits immediately, a child that stays alive without ever
accepting a connection, and a child whose standard error must reach the reported
message. The child is a small Python program that stands in for the binary, so
the readiness, retry, and diagnostic contracts are checked without depending on
Vidai Mock's own argument parsing.
"""

import contextlib
import dataclasses as dc
import subprocess  # noqa: S404 - starts a controlled local test child.
import sys
import typing as typ
from pathlib import Path

import pytest

from tests.steps.vidaimock_harness import (
    VidaiMockLaunch,
    VidaiMockServer,
    VidaiMockStartupError,
    find_free_port,
    start_vidaimock,
    start_vidaimock_process,
    terminate_process_gracefully,
    wait_for_port,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

#: A child that writes a diagnostic and exits non-zero straight away.
_EXIT_IMMEDIATELY = (
    "import sys\n"
    "sys.stderr.write(\"error: unexpected argument '--isolated' found\\n\")\n"
    "sys.exit(2)\n"
)
#: A child that stays alive without ever listening on its port.
_NEVER_READY = "import time\ntime.sleep(30)\n"


def _record_attempts(source: str, attempts: Path) -> str:
    """Append a marker per run so a test can count how often a child started."""
    return (
        "import pathlib, sys\n"
        f"log = pathlib.Path({str(attempts)!r})\n"
        "log.write_text((log.read_text() if log.exists() else '') + 'x')\n"
        f"{source}"
    )


def _write_child(tmp_path: Path, body: str) -> str:
    """Write an executable stand-in child program and return its path.

    The harness starts the server path directly, so the stand-in needs a
    shebang naming this interpreter and the execute bit.

    Returns
    -------
    str
        The path of the written, executable stand-in.
    """
    child = tmp_path / "child.py"
    child.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    child.chmod(0o755)
    return str(child)


def _argv_value(process: subprocess.Popen[str], option: str) -> str:
    """Return the value the child was started with for *option*.

    `Popen.args` is typed as a union that also admits `bytes` and `PathLike`,
    which cannot be indexed or searched. This process is always started from an
    argument list of `str`, so the assertion is the check the cast stands on.

    Returns
    -------
    str
        The argument following *option* in the child's argument list.
    """
    argv = typ.cast("cabc.Sequence[str]", process.args)
    assert option in argv, f"the child was started without {option}: {argv!r}"
    return argv[argv.index(option) + 1]


@dc.dataclass(slots=True)
class _FakeContext:
    """Stand in for a BDD context that records the running server."""

    process: subprocess.Popen[str] | None = None
    base_url: str = ""
    stderr_file: typ.TextIO | None = None


def _child_server_source() -> str:
    """Return a child that echoes its argv, binds its port, and serves."""
    return (
        "import socket, sys\n"
        "argv = sys.argv[1:]\n"
        "sys.stderr.write('argv=' + repr(argv) + '\\n')\n"
        "sys.stderr.flush()\n"
        "host = argv[argv.index('--host') + 1]\n"
        "port = int(argv[argv.index('--port') + 1])\n"
        "sock = socket.socket()\n"
        "sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        "sock.bind((host, port))\n"
        "sock.listen(5)\n"
        "while True:\n"
        "    connection, _ = sock.accept()\n"
        "    connection.close()\n"
    )


def test_process_start_fails_in_ci_when_executable_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail the behavioural story in CI when Vidai Mock is unavailable.

    A skipped live-server scenario in CI reduces coverage without saying so,
    so a missing binary has to stop the run there.
    """
    monkeypatch.setenv("CI", "1")
    monkeypatch.setattr("shutil.which", lambda _name: None)

    with pytest.raises(pytest.fail.Exception, match="vidaimock executable not found"):
        start_vidaimock_process(_FakeContext(), config_dir=Path(), port=0)


def test_process_start_skips_locally_when_executable_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the local developer skip when Vidai Mock is unavailable.

    A developer without the binary has chosen not to run the live scenarios,
    which is not a fault in the code under test.
    """
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    with pytest.raises(pytest.skip.Exception, match="vidaimock executable not found"):
        start_vidaimock_process(_FakeContext(), config_dir=Path(), port=0)


def test_a_ready_child_records_its_url_and_is_reaped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish the base URL, keep the child's stderr, and terminate it cleanly.

    The child here really listens, so this covers the success path the live
    scenarios depend on: the isolation arguments reach the child, the readiness
    probe returns once the port accepts, and the context receives both the base
    URL the adapters need and the capture of the child's output. The executable
    lookup is redirected at the child so the test never depends on an installed
    Vidai Mock.
    """
    child = _write_child(tmp_path, _child_server_source())
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    context = _FakeContext()
    monkeypatch.setattr("shutil.which", lambda _name: child)

    start_vidaimock_process(context, config_dir, label="the happy-path regression test")
    try:
        assert context.process is not None, "the harness must record the child"
        assert context.stderr_file is not None, "the harness must keep stderr"
        assert context.base_url.startswith("http://127.0.0.1:"), context.base_url
        assert context.base_url.endswith("/v1"), context.base_url

        # The child's echo proves the isolation arguments the fixtures need are
        # the ones actually passed, and that the URL names the bound port.
        context.stderr_file.flush()
        context.stderr_file.seek(0)
        captured = context.stderr_file.read() or ""
        assert "'--isolated'" in captured, f"child argv: {captured!r}"
        assert "'--config-dir'" in captured, f"child argv: {captured!r}"
        assert _argv_value(context.process, "--config-dir") == str(config_dir), (
            f"argv: {context.process.args!r}"
        )
        assert context.base_url == (
            f"http://127.0.0.1:{_argv_value(context.process, '--port')}/v1"
        ), context.base_url
    finally:
        terminate_process_gracefully(context.process, context.stderr_file)

    assert context.process.poll() is not None, "the child must be reaped"


def test_an_immediate_exit_reports_the_exit_code_and_stderr(tmp_path: Path) -> None:
    """Surface the child's own rejection instead of a readiness timeout.

    The message must name both the exit status and the bounded standard error,
    so a rejected argument or a bad configuration is diagnosable from the
    failure alone.
    """
    child = _write_child(tmp_path, _EXIT_IMMEDIATELY)
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    with pytest.raises(VidaiMockStartupError) as excinfo:
        start_vidaimock(
            VidaiMockLaunch(
                executable=child,
                config_dir=config_dir,
                label="the harness regression test",
            )
        )

    error = excinfo.value
    assert error.returncode == 2, f"exit code: {error.returncode!r}"
    assert "unexpected argument '--isolated' found" in str(error), (
        f"the child's standard error must reach the message: {error}"
    )
    assert "the harness regression test" in str(error), (
        f"the failure must name its scenario: {error}"
    )


def test_a_probe_that_raises_names_the_failing_scenario(tmp_path: Path) -> None:
    """Give every failure the label its scenario passes in.

    A diagnostic that cannot say which behavioural test failed sends the reader
    looking through every live-server scenario, so the label is part of the
    contract and is carried on the exception as well as in the text.
    """
    child = _write_child(tmp_path, _EXIT_IMMEDIATELY)
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    with pytest.raises(VidaiMockStartupError) as excinfo:
        start_vidaimock(
            VidaiMockLaunch(
                executable=child,
                config_dir=config_dir,
                label="the labelled-diagnostic regression test",
            )
        )

    error = excinfo.value
    assert error.label == "the labelled-diagnostic regression test", error.label
    assert error.reason == "exited before its port became reachable", error.reason
    assert error.stderr, "the capture must be kept on the exception too"


def test_a_rejected_argument_is_not_retried(tmp_path: Path) -> None:
    """Refuse to burn the retry budget on a deterministic rejection.

    Only a bind race is retried. An argument the binary rejects fails the same
    way every time, so the first exit must end the startup rather than hiding
    the cause behind a series of identical attempts.
    """
    attempts = tmp_path / "attempts.txt"
    child = _write_child(tmp_path, _record_attempts(_EXIT_IMMEDIATELY, attempts))
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    with pytest.raises(VidaiMockStartupError):
        start_vidaimock(
            VidaiMockLaunch(
                executable=child,
                config_dir=config_dir,
                label="the non-retry regression test",
            )
        )

    assert attempts.read_text(encoding="utf-8") == "x", (
        "a rejected argument must be tried exactly once"
    )


def test_a_bind_failure_is_retried(tmp_path: Path) -> None:
    """Spend another port on a bind race, and give up after the budget.

    A port another process grabbed between selection and binding is the one
    failure worth retrying, so the child runs more than once; every attempt
    still fails, so the last bind failure is what surfaces.
    """
    attempts = tmp_path / "attempts.txt"
    child = _write_child(
        tmp_path,
        _record_attempts(
            "import sys\n"
            "sys.stderr.write('Error: Address already in use (os error 98)\\n')\n"
            "sys.exit(1)\n",
            attempts,
        ),
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    with pytest.raises(VidaiMockStartupError) as excinfo:
        start_vidaimock(
            VidaiMockLaunch(
                executable=child,
                config_dir=config_dir,
                label="the bind-race regression test",
            )
        )

    assert len(attempts.read_text(encoding="utf-8")) > 1, (
        "a bind race must be retried on a fresh port"
    )
    assert "Address already in use" in str(excinfo.value), (
        f"the last bind failure must be reported: {excinfo.value}"
    )


@contextlib.contextmanager
def _stalled_server(tmp_path: Path) -> cabc.Iterator[VidaiMockServer]:
    """Yield a server whose child stays alive without ever listening.

    A `with` block cannot own this child: `Popen.__exit__` waits for the
    process rather than terminating it, which would hang on a child that never
    exits on its own. The harness's own teardown is used instead, so the
    reaping contract under test is the one the live scenarios rely on.

    Yields
    ------
    VidaiMockServer
        The running child, on a port nothing is listening on.
    """
    child = _write_child(tmp_path, _NEVER_READY)
    process = subprocess.Popen(  # noqa: S603 - fixed argv, trusted local child.
        [sys.executable, child],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        yield VidaiMockServer(
            process=process,
            host="127.0.0.1",
            port=find_free_port(),
            label="the readiness-timeout regression test",
        )
    finally:
        terminate_process_gracefully(process)


def test_a_readiness_timeout_is_reported_as_such(tmp_path: Path) -> None:
    """Report a child that stays alive without listening as a timeout.

    Waiting for a port that never opens is not a crash, so the message must say
    the child never accepted a connection rather than inventing an exit code
    for a process that is still running.
    """
    with _stalled_server(tmp_path) as server:
        with pytest.raises(VidaiMockStartupError) as excinfo:
            wait_for_port(server, timeout=0.5)
        process = server.process

    error = excinfo.value
    assert "did not accept a connection" in str(error), (
        f"a stalled child must be reported as unready: {error}"
    )
    assert error.returncode is None, (
        f"a running child must not be given an exit code: {error.returncode!r}"
    )
    assert process.poll() is not None, "the stalled child must be reaped by the harness"


def test_a_long_standard_error_capture_is_bounded(tmp_path: Path) -> None:
    """Keep a noisy child's diagnostics readable in a failure message.

    A child that dumps far more than a failure message can carry must not put
    all of it in the exception, because the useful first lines would be lost in
    a wall of text.
    """
    child = _write_child(
        tmp_path,
        "import sys\n"
        "sys.stderr.write('noisy-diagnostic-line\\n' * 5000)\n"
        "sys.exit(3)\n",
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    with pytest.raises(VidaiMockStartupError) as excinfo:
        start_vidaimock(
            VidaiMockLaunch(
                executable=child,
                config_dir=config_dir,
                label="the bounded-stderr regression test",
            )
        )

    message = str(excinfo.value)
    assert "noisy-diagnostic-line" in message, (
        f"the head of the capture must survive: {message[:200]!r}"
    )
    assert message.count("noisy-diagnostic-line") < 5000, (
        "the capture must be bounded before it reaches the message"
    )
    assert len(message) < 8000, f"message length: {len(message)}"
