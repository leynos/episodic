"""HTTP client and error translation for the Episodic CLI.

The CLI is a REST client: it opens no database session and imports no domain
service. Failures are translated here into the small exception hierarchy that
:mod:`episodic.cli` maps onto process exit codes, so the command modules never
inspect status codes themselves.
"""

import dataclasses as dc
import enum
import math
import os
import typing as typ

import httpx

from episodic.cli.base_url import validated_base_url
from episodic.cli.errors import (
    ApiError,
    ApiUnavailableError,
    InvalidConfigError,
    RateLimitedError,
)
from episodic.cli.responses import decode_page
from episodic.observability import (
    MetricsPort,
    MonotonicClockPort,
    NoopMetrics,
    NoopTracer,
    PerfCounterClock,
    TracerPort,
)
from episodic.operation_observation import OperationObservation

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.qa_artefacts import QaComplianceStatus, QaEvaluator

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
BASE_URL_ENV = "EPISODIC_API_URL"
TOKEN_ENV = "EPISODIC_API_TOKEN"  # ruff: ignore[hardcoded-password-string]  # An environment-variable name, not a credential.
DEFAULT_TIMEOUT_SECONDS = 30.0


@dc.dataclass(frozen=True, slots=True)
class ClientOptions:
    """Connection settings resolved from one invocation's global options."""

    base_url: str = DEFAULT_BASE_URL
    token: str | None = None
    timeout: float = DEFAULT_TIMEOUT_SECONDS


@dc.dataclass(frozen=True, slots=True)
class CliSinks:
    """Observability sinks one CLI invocation reports to.

    Every sink has a no-op or stdlib default, so a production invocation
    constructs ``CliSinks()`` and a test passes its recording doubles. Grouping
    them keeps the invocation entry point's parameter list bounded as sinks are
    added.

    Attributes
    ----------
    tracer : TracerPort
        Span sink for each API call.
    metrics : MetricsPort
        Latency sink for each API call.
    clock : MonotonicClockPort
        Elapsed-time source for the latency observations.
    """

    tracer: TracerPort = dc.field(default_factory=NoopTracer)
    metrics: MetricsPort = dc.field(default_factory=NoopMetrics)
    clock: MonotonicClockPort = dc.field(default_factory=PerfCounterClock)


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
    tracer : TracerPort
        Span sink for one bounded span per API call. The default is a no-op
        sink: a CLI invocation's observable surface is its output and exit
        code, and tests or an embedding deployment may inject a real sink.
    metrics : MetricsPort
        Latency sink for each API call, defaulting to a no-op sink.
    clock : MonotonicClockPort
        Elapsed-time source for the call latency observations.
    """

    transport: httpx.BaseTransport | None = None
    options: ClientOptions = dc.field(default_factory=ClientOptions)
    tracer: TracerPort = dc.field(default_factory=NoopTracer)
    metrics: MetricsPort = dc.field(default_factory=NoopMetrics)
    clock: MonotonicClockPort = dc.field(default_factory=PerfCounterClock)

    def configure(
        self,
        *,
        base_url: str | None,
        token: str | None,
        timeout: float,
    ) -> None:
        """Resolve the global arguments against the environment."""
        if not math.isfinite(timeout) or timeout <= 0:
            # ``httpx`` hands the value to socket timeout calls, which raise
            # ``ValueError`` or ``OverflowError`` for a negative or non-finite
            # value; neither is an ``httpx.HTTPError``, so it would escape
            # ``main`` as a traceback. Zero silently disables the timeout.
            invalid = (
                "The request timeout must be a positive, finite number of "
                "seconds; check --timeout"
            )
            raise InvalidConfigError(invalid)
        resolved_token = _first_present(token, os.environ.get(TOKEN_ENV))
        if resolved_token is not None and not _is_header_safe(resolved_token):
            # ``httpx`` raises ``UnicodeEncodeError`` while building the client
            # for a value a header cannot carry, and that is not an
            # ``httpx.HTTPError``, so it would escape ``main`` as a traceback.
            # Surrounding whitespace is printable but h11 rejects it, and the
            # resulting protocol error quotes the header, so reject it here
            # rather than letting the token reach standard error.
            invalid = (
                "The API token must be printable ASCII with no surrounding "
                "whitespace; check --token or EPISODIC_API_TOKEN"
            )
            raise InvalidConfigError(invalid)
        resolved_url = (
            _first_present(base_url, os.environ.get(BASE_URL_ENV)) or DEFAULT_BASE_URL
        )
        self.options = ClientOptions(
            base_url=validated_base_url(resolved_url, token=resolved_token),
            token=resolved_token,
            timeout=timeout,
        )


def _first_present(*values: str | None) -> str | None:
    """Return the first non-empty value, treating empty variables as unset."""
    for value in values:
        if value:
            return value
    return None


def _is_header_safe(token: str) -> bool:
    """Return whether ``token`` can travel as an HTTP header value."""
    # ``isprintable()`` accepts a space, but h11 refuses trailing whitespace in
    # a field value and quotes the rejected bytes in its error message.
    return token.isascii() and token.isprintable() and token == token.strip()


def _redact(text: str, secret: str | None) -> str:
    """Return ``text`` with ``secret`` masked so an error cannot echo it."""
    if not secret:
        return text
    return text.replace(secret, "[redacted]")


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
        """
        options = self._runtime.options
        observation = OperationObservation(
            tracer=self._runtime.tracer,
            metrics=self._runtime.metrics,
            clock=self._runtime.clock,
            span_name="cli.qa_evaluations.list",
        )
        with observation:
            try:
                page = self._fetch(query)
            except httpx.InvalidURL as error:
                observation.failed("invalid_url")
                invalid = f"Invalid Episodic API URL {options.base_url}: {error}"
                raise InvalidConfigError(invalid) from error
            except httpx.HTTPError as error:
                observation.failed("transport_failure")
                # A protocol error can quote the header it rejected, so mask
                # the configured token before the text reaches standard error.
                detail = _redact(str(error), options.token)
                unreachable = (
                    f"Cannot reach the Episodic API at {options.base_url}: {detail}"
                )
                raise ApiUnavailableError(unreachable) from error
            except RateLimitedError:
                observation.failed("rate_limited")
                raise
            except ApiError:
                observation.failed("api_error")
                raise
            observation.succeeded("success")
            return page

    def _fetch(self, query: QaEvaluationQuery) -> dict[str, object]:
        """Send the request and decode the page; failures propagate untranslated."""
        options = self._runtime.options
        url = f"{options.base_url.rstrip('/')}{query.path()}"
        with httpx.Client(
            transport=self._runtime.transport,
            timeout=options.timeout,
            headers=self._authorization(),
        ) as client:
            response = client.get(url, params=query.params())
        return decode_page(response, token_configured=options.token is not None)

    def _authorization(self) -> dict[str, str]:
        """Return the authorization header, omitting an unset token."""
        token = self._runtime.options.token
        return {} if token is None else {"Authorization": f"Bearer {token}"}
