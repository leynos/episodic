"""Tests for fallback and failure behaviour at the logging port."""

import functools
import logging
import typing as typ
from unittest import mock

import pytest

from episodic import logging as episodic_logging

if typ.TYPE_CHECKING:
    import collections.abc as cabc


class _LogOnlyBackend:
    """Collect records sent through a backend's generic log method."""

    def __init__(self) -> None:
        """Initialize an empty list of emitted records."""
        self.calls: list[
            tuple[int | episodic_logging.LogLevel, str, object | None, bool]
        ] = []

    def log(
        self,
        level: int | episodic_logging.LogLevel,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record a generic logging call."""
        self.calls.append((level, message, exc_info, stack_info))


class _LegacyDebugBackend(_LogOnlyBackend):
    """Collect a generic call beside an older DEBUG method signature."""

    def __init__(self) -> None:
        """Initialize generic logging and the DEBUG attempt count."""
        super().__init__()
        self.debug_calls = 0

    def debug(self, message: str, /) -> None:
        """Record a DEBUG method call that cannot accept helper options."""
        del message
        self.debug_calls += 1


class _FailingDebugBackend(_LogOnlyBackend):
    """Record a compatible DEBUG call before raising an emission error."""

    def __init__(self) -> None:
        """Initialize generic logging and the DEBUG attempt count."""
        super().__init__()
        self.debug_calls = 0

    def debug(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Raise after recording one compatible DEBUG attempt."""
        del message, exc_info, stack_info
        self.debug_calls += 1
        msg = "debug emission failed"
        raise TypeError(msg)


def _debug_without_logging_options(message: str, /) -> None:
    """Represent a decorated method's narrower wrapped signature."""
    del message


class _DecoratedFailingDebugBackend(_LogOnlyBackend):
    """Record one decorated DEBUG call before raising an emission error."""

    def __init__(self) -> None:
        """Initialize generic logging and the DEBUG attempt count."""
        super().__init__()
        self.debug_calls = 0

    @functools.wraps(_debug_without_logging_options)
    def debug(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Record the accepted DEBUG call, then raise an internal error."""
        self.debug_calls += 1
        self.calls.append((logging.DEBUG, message, exc_info, stack_info))
        msg = "decorated debug emission failed"
        raise TypeError(msg)


class _NonCallableLogFallbackBackend:
    """Expose a legacy DEBUG method beside a non-callable generic fallback."""

    log = None

    def __init__(self) -> None:
        """Initialize the DEBUG attempt counter."""
        self.debug_calls = 0

    def debug(self, message: str, /) -> None:
        """Count a DEBUG call if the unsupported keyword guard regresses."""
        del message
        self.debug_calls += 1


class _UninspectableDebugMethod:
    """Represent a callable whose DEBUG signature cannot be inspected."""

    @property
    def __signature__(self) -> typ.Never:
        """Make signature inspection report that metadata is unavailable."""
        msg = "signature unavailable"
        raise ValueError(msg)

    def __call__(self, message: str, /) -> None:
        """Expose a legacy call shape that rejects helper keyword arguments."""
        del message


class _UninspectableDebugBackend(_LogOnlyBackend):
    """Pair an uninspectable DEBUG callable with a working generic logger."""

    def __init__(self) -> None:
        """Initialize generic logging and the uninspectable DEBUG callable."""
        super().__init__()
        self.debug = _UninspectableDebugMethod()


@pytest.mark.parametrize(
    ("wrapper", "method_name", "expected_exc_info"),
    [
        (episodic_logging.log_info, "info", None),
        (episodic_logging.log_warning, "warning", None),
        (episodic_logging.log_error, "error", None),
        (episodic_logging.log_exception, "exception", True),
    ],
    ids=["info", "warning", "error", "exception"],
)
def test_non_debug_helpers_do_not_retry_failed_convenience_methods(
    wrapper: cabc.Callable[..., None],
    method_name: str,
    expected_exc_info: object | None,
) -> None:
    """Propagate emission failures without a second generic log call."""
    backend = mock.Mock()
    convenience_method = getattr(backend, method_name)
    convenience_method.side_effect = TypeError("emission failed")
    logger = episodic_logging.LoggerHandle(
        typ.cast("episodic_logging._CompatibleLogger", backend)
    )

    with pytest.raises(TypeError, match="emission failed"):
        wrapper(logger, "Loaded %s documents", 3)

    convenience_method.assert_called_once_with(
        "Loaded 3 documents",
        exc_info=expected_exc_info,
        stack_info=False,
    )
    backend.log.assert_not_called()


def test_debug_falls_back_when_signature_rejects_helper_keywords() -> None:
    """Fall back when a legacy DEBUG method rejects helper keyword arguments."""
    backend = _LegacyDebugBackend()
    logger = episodic_logging.LoggerHandle(backend)

    episodic_logging.log_debug(logger, "Loaded %s documents", 3)

    assert backend.debug_calls == 0, "signature mismatch must fail before method entry"
    assert backend.calls == [(logging.DEBUG, "Loaded 3 documents", None, False)], (
        "a rejected DEBUG call should fall back through log()"
    )


def test_debug_fallback_preserves_explicit_exc_info() -> None:
    """Forward caller-supplied exception information through the fallback."""
    backend = _LegacyDebugBackend()
    logger = episodic_logging.LoggerHandle(backend)
    exc_info = (RuntimeError, RuntimeError("adapter failed"), None)

    episodic_logging.log_debug(
        logger,
        "Loaded %s documents",
        3,
        exc_info=exc_info,
    )

    assert backend.debug_calls == 0, "signature mismatch must fail before method entry"
    assert backend.calls == [(logging.DEBUG, "Loaded 3 documents", exc_info, False)], (
        "fallback logging must preserve the caller's exception information"
    )
    assert backend.calls[0][2] is exc_info, "fallback should forward the same object"


def test_debug_preserves_internal_type_error_without_retry() -> None:
    """Propagate a compatible DEBUG failure to avoid a duplicate record."""
    backend = _FailingDebugBackend()
    logger = episodic_logging.LoggerHandle(backend)

    with pytest.raises(TypeError, match="debug emission failed"):
        episodic_logging.log_debug(logger, "Loaded %s documents", 3)

    assert backend.debug_calls == 1, "the compatible DEBUG method should be attempted"
    assert not backend.calls, "internal failures must not retry through log()"


def test_debug_does_not_retry_decorated_method_after_internal_type_error() -> None:
    """Avoid duplicate records when a decorated DEBUG method fails internally."""
    backend = _DecoratedFailingDebugBackend()
    logger = episodic_logging.LoggerHandle(backend)

    with pytest.raises(TypeError, match="decorated debug emission failed"):
        episodic_logging.log_debug(logger, "Loaded %s documents", 3)

    assert backend.debug_calls == 1, "the decorated DEBUG method should be attempted"
    assert backend.calls == [(logging.DEBUG, "Loaded 3 documents", None, False)], (
        "an internal failure must not duplicate the record through log()"
    )


def test_debug_preserves_signature_error_without_generic_fallback() -> None:
    """Keep the original signature error when no generic log method exists."""

    class _DebugOnlyBackend:
        """Expose a legacy DEBUG method without the generic fallback."""

        def debug(self, message: str, /) -> None:
            """Reject the helper's unsupported keyword arguments."""
            del message

    backend = _DebugOnlyBackend()
    logger = episodic_logging.LoggerHandle(
        typ.cast("episodic_logging._CompatibleLogger", backend)
    )

    with pytest.raises(TypeError, match="exc_info"):
        episodic_logging.log_debug(logger, "Loaded %s documents", 3)


def test_debug_preserves_signature_error_when_generic_log_is_not_callable() -> None:
    """Keep the original call error when the fallback attribute is not callable."""
    backend = _NonCallableLogFallbackBackend()
    logger = episodic_logging.LoggerHandle(
        typ.cast("episodic_logging._CompatibleLogger", backend)
    )

    with pytest.raises(TypeError, match="exc_info"):
        episodic_logging.log_debug(logger, "Loaded %s documents", 3)

    assert backend.debug_calls == 0, "signature mismatch must fail before method entry"


def test_debug_preserves_signature_error_when_method_is_uninspectable() -> None:
    """Avoid a generic retry when DEBUG signature inspection is inconclusive."""
    backend = _UninspectableDebugBackend()
    logger = episodic_logging.LoggerHandle(backend)

    with pytest.raises(TypeError, match="exc_info"):
        episodic_logging.log_debug(logger, "Loaded %s documents", 3)

    assert not backend.calls, "an uninspectable method must not fall back through log()"
