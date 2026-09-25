"""Shared startup, readiness, and cleanup for live Vidai Mock BDD fixtures.

Several behavioural modules start a real Vidai Mock process over a temporary
provider/template directory. They differ only in the scenario label used in
diagnostics, so the lifecycle lives here once rather than being copied per
module.

Failure handling is deliberately shaped by how the binary actually fails:

* An unrecognized argument, or any other rejected configuration, exits before
  the server binds. Retrying it would only burn the startup budget and hide the
  cause, so a child that exits before its port is reachable is reported with
  its exit code and a bounded capture of its standard error, and is never
  retried.
* Only a bind failure is worth another port. Its standard error names the
  address in use, and a fresh ephemeral port resolves it.
* A server that stays alive without ever accepting a connection is a genuine
  readiness timeout, reported as such.

Standard error is captured to a temporary file rather than a pipe. A pipe would
block the child once its buffer filled, and the file also survives the child's
exit, so the diagnostics are still readable when the failure is reported. Only
a bounded prefix is ever put in a message.

A missing executable keeps its existing contract: a local skip, and a CI
failure, because a skipped live-server scenario in CI silently reduces
coverage.
"""

import contextlib
import dataclasses as dc
import os
import shutil
import socket
import subprocess  # noqa: S404 - starts a fixed local test server binary
import tempfile
import time
import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from pathlib import Path

#: How long a freshly started server has to accept a connection.
_VIDAIMOCK_STARTUP_TIMEOUT = 5.0
#: Delay between readiness probes.
_VIDAIMOCK_PROBE_INTERVAL = 0.2
#: Ports tried before the startup is declared failed. Only bind races retry.
_VIDAIMOCK_PORT_START_ATTEMPTS = 5
#: Upper bound on the standard-error text carried into a failure message.
_VIDAIMOCK_STDERR_LIMIT = 2000
#: Time allowed for a terminated child to exit before it is killed.
_VIDAIMOCK_TERMINATE_TIMEOUT = 5.0

#: How Vidai Mock reports that the address it was told to bind is taken. The
#: message is matched loosely, so a reworded release still retries the case it
#: describes while a rejected argument still does not.
_BIND_FAILURE_MARKERS = ("address already in use", "failed to bind")


class VidaiMockStartupError(RuntimeError):
    """A Vidai Mock process did not become reachable.

    Attributes
    ----------
    label : str
        Scenario label naming the failure site.
    reason : str
        What went wrong, phrased for the failure message.
    returncode : int | None
        Child exit status when it exited, otherwise ``None``.
    stderr : str
        Bounded capture of the child's standard error.
    """

    def __init__(
        self,
        label: str,
        reason: str,
        *,
        returncode: int | None = None,
        stderr: str = "",
    ) -> None:
        """Build a failure message carrying the child's own diagnostics."""
        detail = f"Vidai Mock {reason} for {label}."
        if returncode is not None:
            detail = f"{detail} Exit code: {returncode}."
        if stderr.strip():
            detail = f"{detail} Standard error:\n{stderr.strip()}"
        super().__init__(detail)
        self.label = label
        self.reason = reason
        self.returncode = returncode
        self.stderr = stderr


class VidaiMockProcessContext(typ.Protocol):
    """Minimal mutable state the harness needs from a BDD context."""

    process: subprocess.Popen[str] | None
    base_url: str
    stderr_file: typ.TextIO | None


@dc.dataclass(frozen=True, slots=True)
class VidaiMockLaunch:
    """Everything needed to start one Vidai Mock child.

    Attributes
    ----------
    executable : str
        Path of the Vidai Mock binary to run.
    config_dir : Path
        Directory holding the provider and template fixtures to serve.
    label : str
        Scenario label naming this server in failure messages.
    host : str
        Interface the child binds and the readiness probe targets.
    """

    executable: str
    config_dir: Path
    label: str
    host: str = "127.0.0.1"


@dc.dataclass(slots=True)
class VidaiMockServer:
    """A started Vidai Mock child together with the address it serves.

    The child, its address, and its standard-error capture travel together
    from the moment it starts, so they are passed as one value rather than as
    a loose argument list.

    Attributes
    ----------
    process : subprocess.Popen[str]
        The running child.
    host : str
        Interface the child bound.
    port : int
        Port the child bound.
    label : str
        Scenario label naming this server in failure messages.
    stderr_file : typ.TextIO | None
        File holding the child's standard error, when captured.
    """

    process: subprocess.Popen[str]
    host: str
    port: int
    label: str
    stderr_file: typ.TextIO | None = None

    @property
    def base_url(self) -> str:
        """Return the base URL the child's OpenAI-compatible routes serve.

        Returns
        -------
        str
            The `/v1` base URL to point an adapter at.
        """
        return f"http://{self.host}:{self.port}/v1"


def _is_bind_failure(stderr: str) -> bool:
    """Report whether *stderr* describes an already-bound address."""
    lowered = stderr.lower()
    return any(marker in lowered for marker in _BIND_FAILURE_MARKERS)


def _read_stderr(stderr_file: typ.TextIO | None) -> str:
    """Return the child's captured standard error, bounded for a message."""
    if stderr_file is None:
        return ""
    try:
        stderr_file.flush()
        stderr_file.seek(0)
        text = stderr_file.read() or ""
    except OSError, ValueError:  # pragma: no cover - defensive
        return ""
    if len(text) <= _VIDAIMOCK_STDERR_LIMIT:
        return text
    return text[:_VIDAIMOCK_STDERR_LIMIT] + "\n… (truncated)"


def _close_stderr(stderr_file: typ.TextIO | None) -> None:
    """Close a captured standard-error file, ignoring an already-closed one."""
    if stderr_file is None:
        return
    with contextlib.suppress(OSError):  # pragma: no cover - defensive
        stderr_file.close()


def terminate_process_gracefully(
    process: subprocess.Popen[str],
    stderr_file: typ.TextIO | None = None,
) -> None:
    """Terminate *process*, escalating to SIGKILL if it does not exit promptly.

    Both the success and the failure path route through here, so a failed
    attempt is reaped rather than leaked and an already-exited child is not
    waited on twice. The captured standard-error file, when given, is closed.
    """
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=_VIDAIMOCK_TERMINATE_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=_VIDAIMOCK_TERMINATE_TIMEOUT)
    finally:
        _close_stderr(stderr_file)


def find_free_port() -> int:
    """Bind to an ephemeral port and return its number before releasing it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _probe_once(host: str, port: int) -> bool:
    """Report whether a TCP connection to *host* and *port* succeeds."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def wait_for_port(
    server: VidaiMockServer,
    *,
    timeout: float = _VIDAIMOCK_STARTUP_TIMEOUT,
) -> None:
    """Wait until *server*'s child accepts connections on its port.

    Raises
    ------
    VidaiMockStartupError
        If the child exits before the port is reachable, or if it stays alive
        without ever accepting a connection before *timeout* elapses.
    """
    deadline = time.monotonic() + timeout
    while True:
        if server.process.poll() is not None:
            raise VidaiMockStartupError(
                server.label,
                "exited before its port became reachable",
                returncode=server.process.returncode,
                stderr=_read_stderr(server.stderr_file),
            )
        if _probe_once(server.host, server.port):
            return
        if time.monotonic() >= deadline:
            raise VidaiMockStartupError(
                server.label,
                f"did not accept a connection on {server.host}:{server.port} "
                f"within {timeout:g}s",
                stderr=_read_stderr(server.stderr_file),
            )
        time.sleep(_VIDAIMOCK_PROBE_INTERVAL)


def _start_once(
    launch: VidaiMockLaunch,
    port: int,
    stderr_file: typ.TextIO,
) -> subprocess.Popen[str]:
    """Start one Vidai Mock child over the given port with isolation enabled."""
    return subprocess.Popen(  # noqa: S603 - fixed trusted local binary.  # pylint: disable=consider-using-with
        [
            launch.executable,
            "--host",
            launch.host,
            "--port",
            str(port),
            "--config-dir",
            str(launch.config_dir),
            "--isolated",
        ],
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
        text=True,
    )


def start_vidaimock(launch: VidaiMockLaunch) -> VidaiMockServer:
    """Start Vidai Mock and wait for it to become reachable.

    Returns
    -------
    VidaiMockServer
        The running child, the address its OpenAI-compatible routes serve, and
        the file holding its standard error.

    Raises
    ------
    VidaiMockStartupError
        If the child exits before it is reachable for any reason other than a
        bind race, or if every attempt hits a bind race.
    """
    attempts = 0
    last_error: VidaiMockStartupError | None = None
    while attempts < _VIDAIMOCK_PORT_START_ATTEMPTS:
        port = find_free_port()
        # A fresh file per attempt keeps one attempt's diagnostics from
        # bleeding into the next.
        stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8")  # noqa: SIM115 - closed by terminate_process_gracefully.
        try:
            process = _start_once(launch, port, stderr_file)
        except BaseException:
            # `Popen` can fail before any child exists, for example when the
            # binary is not executable. No child will close the capture, so it
            # is closed here rather than leaked with its handle open.
            _close_stderr(stderr_file)
            raise
        server = VidaiMockServer(
            process=process,
            host=launch.host,
            port=port,
            label=launch.label,
            stderr_file=stderr_file,
        )
        try:
            wait_for_port(server)
        except VidaiMockStartupError as exc:
            terminate_process_gracefully(server.process, stderr_file)
            if not _is_bind_failure(exc.stderr):
                # A rejected argument or an unusable configuration is not a
                # race. Retrying would hide the cause behind a timeout.
                raise
            last_error = exc
            attempts += 1
            continue
        return server

    raise last_error or VidaiMockStartupError(launch.label, "could not be started")


def resolve_vidaimock_executable() -> str:
    """Return the Vidai Mock executable path, or skip/fail as the environment asks.

    Returns
    -------
    str
        The absolute path of the Vidai Mock binary on `PATH`.

    Raises
    ------
    pytest.fail.Exception
        In CI, where a missing binary must fail the scenario rather than skip
        it and quietly reduce coverage.
    pytest.skip.Exception
        Locally, where a missing binary is a developer's choice, not a fault.
    AssertionError
        Never, in practice. Both calls above raise; this keeps every path an
        explicit return or raise.
    """  # noqa: DOC502 - Both signals come from pytest.fail/pytest.skip below.
    path = shutil.which("vidaimock")
    if path is not None:
        return path
    reason = "vidaimock executable not found in PATH"
    if os.getenv("CI"):
        pytest.fail(reason)
    pytest.skip(reason)
    # Both calls above raise, so this is unreachable; it keeps every path in
    # this function an explicit return or raise for the reader and the linter.
    raise AssertionError(reason)  # pragma: no cover


def start_vidaimock_process(
    context: VidaiMockProcessContext,
    config_dir: Path,
    port: int | None = None,
    *,
    label: str = "the behavioural test",
) -> None:
    """Start Vidai Mock and record its child, base URL, and stderr on *context*.

    ``port`` is accepted for callers that already selected one. Port selection
    belongs to the harness so a bind race can retry, so a supplied value is a
    starting hint only and is not honoured as a fixed binding.
    """
    del port  # The harness owns port selection so it can retry a bind race.
    server = start_vidaimock(
        VidaiMockLaunch(
            executable=resolve_vidaimock_executable(),
            config_dir=config_dir,
            label=label,
        )
    )
    context.process = server.process
    context.base_url = server.base_url
    context.stderr_file = server.stderr_file
