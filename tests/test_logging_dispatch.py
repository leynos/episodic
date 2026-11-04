"""Tests for fallback and failure behaviour at the logging port."""

import logging
import typing as typ
from unittest import mock

import pytest

from episodic import logging as episodic_logging


class _LogOnlyBackend:
    """Collect records sent through a backend's generic log method."""

    def __init__(self) -> None:
        """Initialise an empty list of emitted records."""
        self.calls: list[tuple[int, str, object | None, bool]] = []

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
        """Initialise generic logging and the DEBUG attempt count."""
        super().__init__()
        self.debug_calls = 0

    def debug(self, message: str, /) -> None:
        """Record a DEBUG method call that cannot accept helper options."""
        del message
        self.debug_calls += 1


class _FailingDebugBackend(_LogOnlyBackend):
    """Record a compatible DEBUG call before raising an emission error."""

    def __init__(self) -> None:
        """Initialise generic logging and the DEBUG attempt count."""
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


@pytest.mark.parametrize(
    ("wrapper", "method_name"),
    [
        (episodic_logging.log_info, "info"),
        (episodic_logging.log_warning, "warning"),
        (episodic_logging.log_error, "error"),
    ],
    ids=["info", "warning", "error"],
)
def test_non_debug_helpers_do_not_retry_failed_convenience_methods(
    wrapper: typ.Callable[..., None],
    method_name: str,
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
        exc_info=None,
        stack_info=False,
    )
    backend.log.assert_not_called()


def test_debug_falls_back_when_signature_rejects_helper_keywords() -> None:
    """Fall back when a legacy DEBUG method rejects helper keyword arguments."""
    backend = _LegacyDebugBackend()
    logger = episodic_logging.LoggerHandle(backend)

    episodic_logging.log_debug(logger, "Loaded %s documents", 3)

    assert backend.debug_calls == 0, "signature mismatch must fail before method entry"
    assert backend.calls == [
        (logging.DEBUG, "Loaded 3 documents", None, False)
    ], "a rejected DEBUG call should fall back through log()"


def test_debug_preserves_internal_type_error_without_retry() -> None:
    """Propagate a compatible DEBUG failure to avoid a duplicate record."""
    backend = _FailingDebugBackend()
    logger = episodic_logging.LoggerHandle(backend)

    with pytest.raises(TypeError, match="debug emission failed"):
        episodic_logging.log_debug(logger, "Loaded %s documents", 3)

    assert backend.debug_calls == 1, "the compatible DEBUG method should be attempted"
    assert backend.calls == [], "internal failures must not retry through log()"


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
