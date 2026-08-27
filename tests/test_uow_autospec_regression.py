"""Regression coverage for runtime-evaluated unit-of-work annotations."""

from unittest import mock

from episodic.canonical.storage import SqlAlchemyUnitOfWork


def test_unit_of_work_supports_autospec_creation() -> None:
    """Autospeccing the unit of work must evaluate its annotations.

    ``mock.create_autospec`` calls ``inspect.signature``, which evaluates
    the ``__init__`` and ``__aexit__`` annotations at runtime. Those
    annotations reference ``collections.abc`` and ``types.TracebackType``,
    so this test fails with ``NameError`` if the imports move back behind
    ``typing.TYPE_CHECKING``.
    """
    specced = mock.create_autospec(SqlAlchemyUnitOfWork, instance=True)

    assert specced is not None, "expected an autospecced unit of work"
    assert isinstance(specced.__aenter__, mock.AsyncMock), (
        "the autospecced unit of work must expose an awaitable __aenter__"
    )
    assert isinstance(specced.__aexit__, mock.AsyncMock), (
        "the autospecced unit of work must expose an awaitable __aexit__"
    )
