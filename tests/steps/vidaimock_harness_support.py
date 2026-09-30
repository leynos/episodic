"""Stand-in Vidai Mock children for the harness's focused tests.

The harness is exercised without a real binary. Each helper here builds a
small Python program that impersonates one failure or success mode a live
server can present: a rejected argument, a bind race, a child that never
listens, and a child that really serves. They are kept apart from the tests
themselves so the test module reads as the list of contracts it pins rather
than as a collection of programs-to-run.
"""

import contextlib
import dataclasses as dc
import subprocess  # noqa: S404 - starts a controlled local test child.
import sys
import typing as typ

from tests.steps.vidaimock_harness import (
    VidaiMockServer,
    find_free_port,
    terminate_process_gracefully,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

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
