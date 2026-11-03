"""The ``episodic`` command-line interface.

This module is the command's only writer of standard output and its only
source of process exit codes. Every other CLI module returns values and raises
:class:`~episodic.cli.errors.CliError`, which keeps the output boundary in one
reviewable place.
"""

import sys
import typing as typ

import cyclopts

from episodic.cli.app import build_app
from episodic.cli.errors import CliError

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    import httpx

    from episodic.observability import (
        MetricsPort,
        MonotonicClockPort,
        TracerPort,
    )

USAGE_EXIT_CODE = 2


# pylint: disable-next=too-many-arguments  # Each injectable sink is a seam.
def main(  # ruff: ignore[too-many-arguments]  # Each injectable sink is a seam.
    argv: cabc.Sequence[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    tracer: TracerPort | None = None,
    metrics: MetricsPort | None = None,
    clock: MonotonicClockPort | None = None,
) -> int:
    """Run the CLI and return its process exit code.

    Parameters
    ----------
    argv : collections.abc.Sequence[str] | None
        Arguments without the program name. Defaults to ``sys.argv[1:]``.
    transport : httpx.BaseTransport | None
        Transport the HTTP client uses. Tests inject a mock or bridging
        transport; production leaves it unset so httpx uses the network.
    tracer : TracerPort | None
        Span sink for API calls. ``None`` selects the no-op tracer.
    metrics : MetricsPort | None
        Latency sink for API calls. ``None`` selects the no-op sink.
    clock : MonotonicClockPort | None
        Elapsed-time source for API-call latency. ``None`` selects the
        performance-counter clock.

    Returns
    -------
    int
        ``0`` on success, ``2`` for a usage error, ``3`` when the API is
        unreachable, ``4`` when it throttles the request, and ``1`` for an
        error envelope returned by the API.

    Examples
    --------
    >>> main(["qa", "evaluations", "list"])  # doctest: +SKIP
    2
    """
    tokens = list(sys.argv[1:] if argv is None else argv)
    application = build_app(
        transport,
        tracer=tracer,
        metrics=metrics,
        clock=clock,
    )
    try:
        rendered = application.run(tokens)
    except CliError as error:
        _report(error)
        return error.exit_code
    except cyclopts.CycloptsError as error:
        print(f"episodic: {error}", file=sys.stderr)
        return USAGE_EXIT_CODE
    except SystemExit as error:
        return typ.cast("int", error.code or 0)

    if rendered is not None:
        text = str(rendered)
        print(text, end="" if text.endswith("\n") else "\n")
    return 0


def _report(error: CliError) -> None:
    """Write a failure and its optional hint to standard error."""
    print(f"episodic: {error}", file=sys.stderr)
    if error.hint is not None:
        print(f"episodic: {error.hint}", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover - exercised via the entry point
    sys.exit(main())
