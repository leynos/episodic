"""Assembly of the Cyclopts application and its global options.

The global options live on the application's meta launcher, which cyclopts runs
before dispatching to a command. That ordering is what lets the command tree be
built once and still read the arguments the operator actually supplied.
"""

import dataclasses as dc
import typing as typ

import cyclopts

from episodic.cli import qa
from episodic.cli.client import (
    BASE_URL_ENV,
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    TOKEN_ENV,
    CliRuntime,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    import httpx

APP_NAME = "episodic"
_APP_HELP = "Inspect canonical episodes and the QA artefacts recorded for them."
_BASE_URL_HELP = f"API root URL. Defaults to ${BASE_URL_ENV}, then {DEFAULT_BASE_URL}."
_TOKEN_HELP = f"Bearer token. Defaults to ${TOKEN_ENV}. Never printed."
_TIMEOUT_HELP = "Request timeout in seconds."


@dc.dataclass(slots=True)
class CliApplication:
    """The assembled command tree and the runtime its commands read.

    Attributes
    ----------
    app : cyclopts.App
        Root application, including the meta launcher owning global options.
    runtime : CliRuntime
        State the launcher fills before dispatching to a command.
    """

    app: cyclopts.App
    runtime: CliRuntime

    def run(self, tokens: cabc.Sequence[str]) -> object:
        """Parse ``tokens``, run the selected command, and return its value.

        Parameters
        ----------
        tokens : collections.abc.Sequence[str]
            Command-line arguments without the program name.

        Returns
        -------
        object
            Whatever the selected command returned, or ``None`` when the
            invocation only printed help.
        """
        return self.app.meta(list(tokens))


def build_app(transport: httpx.BaseTransport | None = None) -> CliApplication:
    """Assemble the CLI command tree.

    Parameters
    ----------
    transport : httpx.BaseTransport | None
        Transport the HTTP client uses. Tests inject a mock or bridging
        transport; production leaves it unset so httpx uses the network.

    Returns
    -------
    CliApplication
        Root application together with the runtime its commands share.
    """
    runtime = CliRuntime(transport=transport)
    app = cyclopts.App(
        name=APP_NAME,
        help=_APP_HELP,
        result_action="return_value",
        exit_on_error=False,
        print_error=False,
    )

    @app.meta.default
    def launcher(
        *tokens: typ.Annotated[
            str,
            cyclopts.Parameter(show=False, allow_leading_hyphen=True),
        ],
        base_url: typ.Annotated[
            str | None,
            cyclopts.Parameter(help=_BASE_URL_HELP),
        ] = None,
        token: typ.Annotated[
            str | None,
            cyclopts.Parameter(help=_TOKEN_HELP),
        ] = None,
        timeout: typ.Annotated[
            float,
            cyclopts.Parameter(help=_TIMEOUT_HELP),
        ] = DEFAULT_TIMEOUT_SECONDS,
    ) -> object:
        """Resolve the global options and dispatch to the selected command."""
        runtime.configure(base_url=base_url, token=token, timeout=timeout)
        return app(tokens)

    qa.register(app, runtime)
    return CliApplication(app=app, runtime=runtime)
