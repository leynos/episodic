"""Best-effort observability for the authorization HTTP boundary."""

import enum
import hashlib
import sys
import typing as typ

from episodic.logging import LoggerHandle, log_warning
from episodic.observability import MetricsPort, NoopMetrics

_AUTHORIZATION_ADAPTER_FAILURE_TOTAL = "authorization_adapter_failure_total"
_AUTHORIZATION_WARNING_FALLBACK_MESSAGE = (
    "Authorization warning sink failed; request details omitted.\n"
)
_AUTHORIZATION_SINK_FAILURES = (
    AttributeError,
    IndexError,
    KeyError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)
# Exceptions outside this table intentionally use the fixed `unknown_error` label.
_AUTHORIZATION_FAILURE_CATEGORIES = (
    (AssertionError, "assertion_error"),
    (AttributeError, "attribute_error"),
    (IndexError, "index_error"),
    (KeyError, "key_error"),
    (OSError, "os_error"),
    (RuntimeError, "runtime_error"),
    (TypeError, "type_error"),
    (ValueError, "value_error"),
)
_AUTHORIZATION_LOG_RESOURCE_LABELS = {
    "episode-templates": "/v1/episode-templates",
    "episodes": "/v1/episodes",
    "generation-runs": "/v1/generation-runs",
    "ingestion-jobs": "/v1/ingestion-jobs",
    "qa-evaluations": "/v1/qa-evaluations",
    "reference-bindings": "/v1/reference-bindings",
    "reference-document-revisions": "/v1/reference-document-revisions",
    "series-profiles": "/v1/series-profiles",
    "uploads": "/v1/uploads",
}
_UNKNOWN_AUTHORIZATION_LOG_RESOURCE = "/v1/<unknown>"
_AUTHORIZATION_LOG_METHODS = frozenset({
    "DELETE",
    "GET",
    "HEAD",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
})
_OTHER_AUTHORIZATION_LOG_METHOD = "<other>"
_AUTHORIZATION_DECISION_LABELS = frozenset({
    "forbidden",
    "permit",
    "unauthorized",
})


class AuthorizationObservabilityPort(typ.Protocol):
    """Observe authorization outcomes without owning their HTTP responses."""

    def record_authorization_outcome(
        self,
        outcome: object,
        *,
        method: str,
        path: str,
    ) -> None:
        """Observe one authorization decision or adapter failure.

        Parameters
        ----------
        outcome : object
            A decision or adapter exception used to derive a safe event label.
        method : str
            Original HTTP method; unsafe values are replaced with a placeholder.
        path : str
            Original request path; only its allow-listed resource root is logged.
        """
        ...


class AuthorizationObserver:
    """Emit bounded authorization diagnostics through injected output ports.

    The observer is scoped to authorization because its best-effort fallback
    policy exists to preserve canonical HTTP responses when observability sinks
    fail. It is not a general-purpose logging or metrics adapter.

    Parameters
    ----------
    logger : LoggerHandle
        Central logging port handle used for authorization warning records.
    metrics : MetricsPort | None, optional
        Bounded metrics sink for adapter failures. When omitted, a no-op sink
        is used.
    """

    def __init__(
        self,
        logger: LoggerHandle,
        metrics: MetricsPort | None = None,
    ) -> None:
        """Store injected ports used to observe authorization outcomes."""
        self._logger = logger
        self._metrics = NoopMetrics() if metrics is None else metrics

    def record_authorization_outcome(
        self,
        outcome: object,
        *,
        method: str,
        path: str,
    ) -> None:
        """Record one decision or adapter exception with bounded labels.

        Parameters
        ----------
        outcome : object
            A decision or adapter exception used to derive a safe event label.
        method : str
            Original HTTP method; unsafe values are replaced with a placeholder.
        path : str
            Original request path; only its allow-listed resource root is logged.
        """
        try:
            if isinstance(outcome, Exception):
                self._record_adapter_failure(outcome, method=method, path=path)
                return
            self._record_denial(outcome, method=method, path=path)
        except Exception as observer_error:
            raise observer_error from None

    def _record_denial(
        self,
        decision: object,
        *,
        method: str,
        path: str,
    ) -> None:
        """Log a non-permit outcome without credentials or raw path segments."""
        self._log_warning(
            "Authorization denied with %s for %s %s.",
            _authorization_decision_label(decision),
            _authorization_method_label(method),
            _authorization_route_label(path),
        )

    def _record_adapter_failure(
        self,
        error: Exception,
        *,
        method: str,
        path: str,
    ) -> None:
        """Record bounded diagnostics for an adapter exception."""
        failure_category = _authorization_failure_category(error)
        self._record_adapter_failure_metric(failure_category)
        diagnostic_id = (
            _authorization_failure_diagnostic_id(error)
            if failure_category == "unknown_error"
            else ""
        )
        diagnostic_suffix = f" (diagnostic_id={diagnostic_id})" if diagnostic_id else ""
        self._log_warning(
            "Authorization adapter failed with %s%s for %s %s.",
            failure_category,
            diagnostic_suffix,
            _authorization_method_label(method),
            _authorization_route_label(path),
        )

    def _log_warning(self, template: str, *args: object) -> None:
        """Keep known logging-sink failures from masking HTTP responses."""
        try:
            log_warning(self._logger, template, *args)
        except _AUTHORIZATION_SINK_FAILURES:  # fmt: skip
            _write_authorization_warning_fallback()

    def _record_adapter_failure_metric(self, failure_category: str) -> None:
        """Record the bounded adapter-failure category on the metrics port."""
        try:
            self._metrics.increment_counter(
                _AUTHORIZATION_ADAPTER_FAILURE_TOTAL,
                labels={"category": failure_category},
            )
        except _AUTHORIZATION_SINK_FAILURES:  # fmt: skip
            self._log_warning(
                "Authorization adapter failure metric could not be recorded.",
            )


def _write_authorization_warning_fallback() -> None:
    """Write a fixed stderr marker when the central warning sink fails."""
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(_AUTHORIZATION_WARNING_FALLBACK_MESSAGE)
        stream.flush()
    except _AUTHORIZATION_SINK_FAILURES:  # fmt: skip
        return


def _authorization_failure_category(error: Exception) -> str:
    """Return a bounded category for a caught authorization adapter error."""
    return next(
        (
            category
            for error_type, category in _AUTHORIZATION_FAILURE_CATEGORIES
            if isinstance(error, error_type)
        ),
        "unknown_error",
    )


def _authorization_failure_diagnostic_id(error: Exception) -> str:
    """Fingerprint an unclassified exception type without logging its name."""
    error_type = type(error)
    module = type.__getattribute__(error_type, "__module__")
    qualified_name = type.__getattribute__(error_type, "__qualname__")
    if not isinstance(module, str) or not isinstance(qualified_name, str):
        module, qualified_name = "unknown", "exception"
    type_identity = f"{module}.{qualified_name}"
    return hashlib.sha256(
        type_identity.encode("utf-8", errors="backslashreplace"),
    ).hexdigest()[:12]


def _authorization_route_label(path: str) -> str:
    """Return an allow-listed route root without client-controlled path values."""
    if not path.startswith("/v1/"):
        return _UNKNOWN_AUTHORIZATION_LOG_RESOURCE
    resource = path.removeprefix("/v1/").partition("/")[0]
    return _AUTHORIZATION_LOG_RESOURCE_LABELS.get(
        resource,
        _UNKNOWN_AUTHORIZATION_LOG_RESOURCE,
    )


def _authorization_method_label(method: str) -> str:
    """Return a standard HTTP method name, or a fixed placeholder."""
    return (
        method
        if method in _AUTHORIZATION_LOG_METHODS
        else _OTHER_AUTHORIZATION_LOG_METHOD
    )


def _authorization_decision_label(decision: object) -> str:
    """Return a fixed label for known authorization decisions."""
    match decision:
        case enum.Enum() as known_decision:
            value = known_decision.value
            return (
                value
                if isinstance(value, str) and value in _AUTHORIZATION_DECISION_LABELS
                else "unknown"
            )
        case _:
            return "unknown"


__all__ = (
    "AuthorizationObservabilityPort",
    "AuthorizationObserver",
)
