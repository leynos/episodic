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
from episodic.cli.client import CliSinks
from episodic.cli.errors import CliError
from episodic.observability import (
    PerfCounterClock,
    StructuredLogMetrics,
    StructuredLogTracer,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    import httpx

USAGE_EXIT_CODE = 2


def _production_sinks() -> CliSinks:
    """Return the sinks a production invocation reports to.

    ``CliSinks`` itself defaults to no-op sinks so an embedding caller or a
    test stays silent; the command line is where structured log observations
    are actually wanted.

    Returns
    -------
    CliSinks
        Structured-log tracer and metrics sink with a performance-counter
        clock.
    """
    return CliSinks(
        tracer=StructuredLogTracer(),
        metrics=StructuredLogMetrics(),
        clock=PerfCounterClock(),
    )


def main(
    argv: cabc.Sequence[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    sinks: CliSinks | None = None,
) -> int:
    """Run the CLI and return its process exit code.

    Parameters
    ----------
    argv : collections.abc.Sequence[str] | None
        Arguments without the program name. Defaults to ``sys.argv[1:]``.
    transport : httpx.BaseTransport | None
        Transport the HTTP client uses. Tests inject a mock or bridging
        transport; production leaves it unset so httpx uses the network.
    sinks : CliSinks | None
        Observability sinks for API calls. ``None`` selects the structured-log
        tracer and metrics sink a production invocation reports through; tests
        inject recording doubles.

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
        sinks=_production_sinks() if sinks is None else sinks,
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
