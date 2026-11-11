"""The ``episodic`` command-line interface.

This module is the command's only writer of standard output and its only
source of process exit codes. Every other CLI module returns values and raises
:class:`~episodic.cli.errors.CliError`, which keeps the output boundary in one
reviewable place.
"""

import os
import sys
import typing as typ

import cyclopts

from episodic.cli.app import build_app
from episodic.cli.client import CliSinks
from episodic.cli.errors import CliError
from episodic.logging import get_logger
from episodic.observability import (
    PerfCounterClock,
    StructuredLogMetrics,
    StructuredLogTracer,
    admits_telemetry,
    configure_structured_logging,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    import httpx

USAGE_EXIT_CODE = 2
LOG_LEVEL_ENV = "EPISODIC_LOG_LEVEL"
# Warnings and errors still reach an operator who configured nothing, while a
# successful command keeps standard error silent. Telemetry is opt-in because
# the command's contract is JSON on standard output.
DEFAULT_LOG_LEVEL = "WARNING"


def _production_sinks() -> CliSinks:
    """Return the sinks a production invocation reports to.

    ``CliSinks`` itself defaults to no-op sinks so an embedding caller or a
    test stays silent; the command line is where structured log observations
    are actually wanted.

    Selecting these sinks also configures the process logger. A structured-log
    sink only delivers once the logging backend has a handler, and
    femtologging's logger registry starts empty, so without this call every
    span and latency record would be dropped. The level comes from
    ``EPISODIC_LOG_LEVEL`` and defaults to ``WARNING``; setting it to ``INFO``
    or lower enables the span and latency events.

    The pinned femtologging backend does not filter records by the configured
    level, so the command has to decline the sinks itself rather than rely on
    the backend: above ``INFO`` it keeps the no-op defaults and a successful
    run's standard error stays silent.

    Returns
    -------
    CliSinks
        Structured-log tracer and metrics sink with a performance-counter
        clock, or the no-op sinks when the level excludes ``INFO``.
    """
    level = configure_structured_logging(
        os.environ.get(LOG_LEVEL_ENV, DEFAULT_LOG_LEVEL)
    )
    if not admits_telemetry(level):
        return CliSinks()
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
        tracer and metrics sink a production invocation reports through, and
        configures process logging so they deliver; tests inject recording
        doubles and leave the process logger alone.

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
    is_production_invocation = sinks is None
    application = build_app(
        transport,
        sinks=_production_sinks() if is_production_invocation else sinks,
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
    else:
        if rendered is not None:
            text = str(rendered)
            print(text, end="" if text.endswith("\n") else "\n")
        return 0
    finally:
        if is_production_invocation:
            get_logger("root").flush()


def _report(error: CliError) -> None:
    """Write a failure and its optional hint to standard error."""
    print(f"episodic: {error}", file=sys.stderr)
    if error.hint is not None:
        print(f"episodic: {error.hint}", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover - exercised via the entry point
    sys.exit(main())
