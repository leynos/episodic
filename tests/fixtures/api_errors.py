"""Shared fixtures for API error logging and handler tests."""

import dataclasses as dc
import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


class EmptyUnitOfWorkFactory(typ.Protocol):
    """Describe a factory for the empty unit of work test double."""

    def __call__(self) -> CanonicalUnitOfWork:
        """Return an empty unit of work."""
        ...


type DetachedExcInfo = tuple[type[BaseException], BaseException, None]


def _is_detached_exc_info(value: object | None) -> typ.TypeGuard[DetachedExcInfo]:
    """Return whether a captured mapper diagnostic is a detached exception triple."""
    if not isinstance(value, tuple) or len(value) != 3:
        return False
    exception_type, exception, traceback_value = value
    return (
        isinstance(exception_type, type)
        and issubclass(exception_type, BaseException)
        and isinstance(exception, BaseException)
        and traceback_value is None
    )


@dc.dataclass(slots=True)
class SpyLogger:
    """Capture calls made to the injected error emitter."""

    calls: list[tuple[str, str, DetachedExcInfo]] = dc.field(default_factory=list)

    def __call__(
        self,
        template: str,
        /,
        *args: object,
        exc_info: object | None = None,
    ) -> None:
        """Record one sanitized error-port call for API boundary assertions."""
        message = template % args if args else template
        if not _is_detached_exc_info(exc_info):
            msg = "API mapper emitter must receive detached exception information."
            raise AssertionError(msg)
        self.calls.append(("ERROR", message, exc_info))


class EmptyUnitOfWork:
    """Provide a minimal asynchronous context for error-handler tests."""

    async def __aenter__(self) -> CanonicalUnitOfWork:
        """Enter the empty unit of work."""
        return typ.cast("CanonicalUnitOfWork", self)

    async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        """Exit without handling service exceptions."""


@pytest.fixture
def spy_logger() -> SpyLogger:
    """Return a recording logger for explicit API-boundary injection."""
    return SpyLogger()


@pytest.fixture
def empty_uow_factory() -> EmptyUnitOfWorkFactory:
    """Return a factory for the minimal unit of work used by error tests."""

    def create_empty_uow() -> CanonicalUnitOfWork:
        return typ.cast("CanonicalUnitOfWork", EmptyUnitOfWork())

    return create_empty_uow
