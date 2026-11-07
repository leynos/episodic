"""Errors the Episodic CLI raises and the exit codes it maps them onto.

These types live apart from the HTTP client so that response decoding and the
command modules can name them without importing the client itself.
"""


class CliError(Exception):
    """Failure the CLI reports on standard error."""

    exit_code: int = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        """Record the message and an optional remediation hint."""
        super().__init__(message)
        self.hint = hint


class ApiError(CliError):
    """The API answered with an error envelope."""


class InvalidConfigError(CliError):
    """A global option names a value the HTTP client cannot use."""

    exit_code = 2


class ApiUnavailableError(CliError):
    """The API could not be reached within the configured timeout."""

    exit_code = 3


class RateLimitedError(CliError):
    """The API throttled the request."""

    exit_code = 4


MISSING_TOKEN_HINT = "no API token configured; set EPISODIC_API_TOKEN or pass --token"  # ruff: ignore[hardcoded-password-string]  # Guidance naming the variable, not a credential.
