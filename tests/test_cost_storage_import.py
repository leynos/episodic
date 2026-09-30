"""Public import contracts for cost-accounting storage."""

import importlib
import multiprocessing
import sys
import typing as typ
from pathlib import Path

if typ.TYPE_CHECKING:
    from multiprocessing.connection import Connection


def _import_cost_storage_in_child(
    result: Connection,
    repository_root: str,
) -> None:
    """Import the public cost storage package in a clean spawned interpreter."""
    sys.path.insert(0, repository_root)
    try:
        importlib.import_module("episodic.cost.storage")
    except ImportError as error:
        result.send(f"{type(error).__name__}: {error}")
    else:
        result.send(None)
    finally:
        result.close()


def test_cost_storage_imports_without_preloading_canonical_storage() -> None:
    """The documented cost adapter import must work in a fresh process."""
    repository_root = str(Path(__file__).resolve().parents[1])
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_import_cost_storage_in_child,
        args=(child_connection, repository_root),
    )
    process.start()
    child_connection.close()
    try:
        import_error = parent_connection.recv()
    except EOFError:
        import_error = "spawned interpreter exited without reporting its import result"
    finally:
        parent_connection.close()
        process.join()

    assert process.exitcode == 0, "fresh import process must exit successfully"
    assert import_error is None, (
        "cost storage must import before canonical storage; "
        f"child error was {import_error!r}"
    )
