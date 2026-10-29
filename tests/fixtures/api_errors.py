"""Shared fixtures for API error logging and handler tests."""

import dataclasses as dc
import logging
import types
import typing as typ

import pytest

from episodic.api import errors as api_errors

if typ.TYPE_CHECKING:
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


class EmptyUnitOfWorkFactory(typ.Protocol):
    """Describe a factory for the empty unit of work test double."""

    def __call__(self) -> CanonicalUnitOfWork:
        """Return an empty unit of work."""
        ...


API_ERROR_TEST_LOGGER_NAME = "test.episodic.api.errors"
type ExcInfo = (
    bool
    | BaseException
    | tuple[type[BaseException], BaseException, types.TracebackType | None]
    | tuple[None, None, None]
    | None
)


@dc.dataclass(slots=True)
class SpyLogger:
    """Capture error calls and forward them for caplog assertions."""

    calls: list[tuple[str, str, object]] = dc.field(default_factory=list)

    def error(
        self,
        message: str,
        /,
        *,
        exc_info: ExcInfo = None,
        stack_info: bool = False,
    ) -> None:
        """Record one ERROR call and forward it to the test logger."""
        self.calls.append(("ERROR", message, exc_info))
        logging.getLogger(API_ERROR_TEST_LOGGER_NAME).error(
            message,
            exc_info=exc_info,
            stack_info=stack_info,
        )


class EmptyUnitOfWork:
    """Provide a minimal asynchronous context for error-handler tests."""

    async def __aenter__(self) -> CanonicalUnitOfWork:
        """Enter the empty unit of work."""
        return typ.cast("CanonicalUnitOfWork", self)

    async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        """Exit without handling service exceptions."""


@pytest.fixture
def spy_logger(monkeypatch: pytest.MonkeyPatch) -> SpyLogger:
    """Patch the API-error logger with a shared recording logger."""
    spy = SpyLogger()
    monkeypatch.setattr(api_errors, "logger", spy)
    return spy


@pytest.fixture
def empty_uow_factory() -> EmptyUnitOfWorkFactory:
    """Return a factory for the minimal unit of work used by error tests."""

    def create_empty_uow() -> CanonicalUnitOfWork:
        return typ.cast("CanonicalUnitOfWork", EmptyUnitOfWork())

    return create_empty_uow
