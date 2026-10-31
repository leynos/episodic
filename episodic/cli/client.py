"""HTTP client and error translation for the Episodic CLI.

The CLI is a REST client: it opens no database session and imports no domain
service. Failures are translated here into the small exception hierarchy that
:mod:`episodic.cli` maps onto process exit codes, so the command modules never
inspect status codes themselves.
"""

import dataclasses as dc
import enum
import os
import typing as typ
import urllib.parse

import httpx

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.qa_artefacts import QaComplianceStatus, QaEvaluator

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
BASE_URL_ENV = "EPISODIC_API_URL"
TOKEN_ENV = "EPISODIC_API_TOKEN"  # ruff: ignore[hardcoded-password-string]  # An environment-variable name, not a credential.
DEFAULT_TIMEOUT_SECONDS = 30.0

MISSING_TOKEN_HINT = "no API token configured; set EPISODIC_API_TOKEN or pass --token"  # ruff: ignore[hardcoded-password-string]  # Guidance naming the variable, not a credential.


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


@dc.dataclass(frozen=True, slots=True)
class ClientOptions:
    """Connection settings resolved from one invocation's global options."""

    base_url: str = DEFAULT_BASE_URL
    token: str | None = None
    timeout: float = DEFAULT_TIMEOUT_SECONDS


@dc.dataclass(slots=True)
class CliRuntime:
    """State the meta launcher fills before a command runs.

    Attributes
    ----------
    transport : httpx.BaseTransport | None
        Transport the HTTP client uses. Tests inject a mock or bridging
        transport; production leaves it unset so httpx uses the network.
    options : ClientOptions
        Settings the global ``--base-url``, ``--token``, and ``--timeout``
        arguments resolved to.
    """

    transport: httpx.BaseTransport | None = None
    options: ClientOptions = dc.field(default_factory=ClientOptions)

    def configure(
        self,
        *,
        base_url: str | None,
        token: str | None,
        timeout: float,
    ) -> None:
        """Resolve the global arguments against the environment."""
        self.options = ClientOptions(
            base_url=_validated_base_url(
                _first_present(base_url, os.environ.get(BASE_URL_ENV))
                or DEFAULT_BASE_URL
            ),
            token=_first_present(token, os.environ.get(TOKEN_ENV)),
            timeout=timeout,
        )


def _first_present(*values: str | None) -> str | None:
    """Return the first non-empty value, treating empty variables as unset."""
    for value in values:
        if value:
            return value
    return None


def _validated_base_url(base_url: str) -> str:
    """Return ``base_url`` after checking it names an HTTP(S) host.

    ``httpx`` raises plain ``ValueError`` for a URL with no scheme, and its
    transport layer can raise ``httpx.InvalidURL`` later, so rejecting the
    obvious misconfiguration here gives one clean usage error instead of two
    different failure paths.

    Parameters
    ----------
    base_url : str
        API root resolved from ``--base-url`` or the environment.

    Returns
    -------
    str
        The base URL, unchanged.

    Raises
    ------
    InvalidConfigError
        If the URL has no HTTP(S) scheme or names no host.
    """
    try:
        parsed = urllib.parse.urlsplit(base_url)
    except ValueError as error:
        invalid = f"Invalid Episodic API URL {base_url}: {error}"
        raise InvalidConfigError(invalid) from error
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        invalid = (
            f"Invalid Episodic API URL {base_url}: "
            "expected an http or https URL with a host"
        )
        raise InvalidConfigError(invalid)
    return base_url


@dc.dataclass(frozen=True, slots=True)
class QaEvaluationQuery:
    """A filtered, paginated request for one episode's QA evaluations.

    Attributes
    ----------
    episode_id : uuid.UUID
        Episode whose evaluations are requested.
    evaluator : QaEvaluator | None
        Optional evaluator filter.
    compliance_status : QaComplianceStatus | None
        Optional compliance-status filter.
    limit : int | None
        Optional page size.
    offset : int | None
        Optional page offset.
    """

    episode_id: uuid.UUID
    evaluator: QaEvaluator | None = None
    compliance_status: QaComplianceStatus | None = None
    limit: int | None = None
    offset: int | None = None

    def path(self) -> str:
        """Return the resource path for the episode."""
        return f"/v1/episodes/{self.episode_id}/qa-evaluations"

    def params(self) -> dict[str, str]:
        """Return the query parameters, omitting filters that are unset."""
        pairs = (
            ("evaluator", _enum_value(self.evaluator)),
            ("compliance_status", _enum_value(self.compliance_status)),
            ("limit", None if self.limit is None else str(self.limit)),
            ("offset", None if self.offset is None else str(self.offset)),
        )
        return {name: value for name, value in pairs if value is not None}


def _enum_value[EnumT: enum.Enum](value: EnumT | None) -> str | None:
    """Return an enum member's wire value, or ``None`` when unset."""
    return None if value is None else str(value.value)


class QaApiClient:
    """Retrieve QA artefacts from the Episodic REST API.

    Parameters
    ----------
    runtime : CliRuntime
        Resolved connection settings and the optional transport override.
    """

    def __init__(self, runtime: CliRuntime) -> None:
        self._runtime = runtime

    def list_evaluations(
        self,
        query: QaEvaluationQuery,
    ) -> dict[str, object]:
        """Return one page of the episode's QA evaluations.

        Parameters
        ----------
        query : QaEvaluationQuery
            Episode identifier, filters, and pagination.

        Returns
        -------
        dict[str, object]
            The page envelope exactly as the API sent it.

        Raises
        ------
        ApiError
            If the API answered with an error envelope, or with a successful
            body that is not a page envelope.
        InvalidConfigError
            If the configured base URL is not a usable HTTP URL.
        ApiUnavailableError
            If the API could not be reached before the timeout elapsed.
        RateLimitedError
            If the API throttled the request.
        """  # ruff: ignore[docstring-extraneous-exception]  # _decode_page() raises them from this call.
        options = self._runtime.options
        url = f"{options.base_url.rstrip('/')}{query.path()}"
        try:
            with httpx.Client(
                transport=self._runtime.transport,
                timeout=options.timeout,
                headers=self._authorization(),
            ) as client:
                response = client.get(url, params=query.params())
        except httpx.InvalidURL as error:
            invalid = f"Invalid Episodic API URL {options.base_url}: {error}"
            raise InvalidConfigError(invalid) from error
        except httpx.HTTPError as error:
            unreachable = (
                f"Cannot reach the Episodic API at {options.base_url}: {error}"
            )
            raise ApiUnavailableError(unreachable) from error
        return _decode_page(
            response,
            token_configured=options.token is not None,
        )

    def _authorization(self) -> dict[str, str]:
        """Return the authorization header, omitting an unset token."""
        token = self._runtime.options.token
        return {} if token is None else {"Authorization": f"Bearer {token}"}


def _decode_page(
    response: httpx.Response,
    *,
    token_configured: bool,
) -> dict[str, object]:
    """Return a successful payload or raise the matching CLI error."""
    payload = _decode(response)
    if response.is_success:
        if not isinstance(payload.get("items"), list):
            unexpected = (
                f"{response.status_code} the API returned an unexpected response body"
            )
            raise ApiError(unexpected)
        return payload

    status = response.status_code
    code = _as_text(payload.get("code")) or "unknown_error"
    message = _as_text(payload.get("message")) or response.reason_phrase
    if status == httpx.codes.TOO_MANY_REQUESTS or code == "rate_limited":
        raise RateLimitedError(
            _throttled_message(status, message, response.headers.get("Retry-After"))
        )
    unauthorized = status == httpx.codes.UNAUTHORIZED and not token_configured
    hint = MISSING_TOKEN_HINT if unauthorized else None
    text = f"{status} {message}"
    raise ApiError(text, hint=hint)


def _decode(response: httpx.Response) -> dict[str, object]:
    """Decode a JSON object body, treating anything else as absent."""
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_text(value: object) -> str | None:
    """Return a non-empty string value, or ``None``."""
    return value if isinstance(value, str) and value else None


def _throttled_message(status: int, message: str, retry_after: str | None) -> str:
    """Compose a throttle message that names the retry delay when present."""
    text = f"{status} {message}"
    if retry_after:
        return f"{text} (retry after {retry_after} seconds)"
    return text
