"""py-pglite Node runtime plumbing for the database fixtures.

py-pglite runs `npm install` in every work directory it is handed, and it
gives that subprocess a fixed 60-second timeout which it does not catch, so
one slow registry response surfaces as `subprocess.TimeoutExpired` out of
`PGliteManager.start()`. Priming the modules once per session and pointing
each later work directory at the result turns a per-test network dependency
into a single attempt.
"""

import os
import shutil
import subprocess  # noqa: S404 - py-pglite shell-out shape is mirrored for retry handling.
import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from pathlib import Path

try:
    from py_pglite import (  # type: ignore[import-untyped]  # py-pglite does not publish type information for this optional test dependency.
        PGliteConfig,
        PGliteManager,
    )

    PGLITE_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    PGLITE_AVAILABLE = False


# py-pglite caps `npm install` at a fixed 60 seconds and does not catch the
# resulting timeout, so a slow registry fails the start. A per-test work
# directory pays that cost, and that risk, once per test; these attempts bound
# the single shared install instead.
PGLITE_START_ATTEMPTS = 3


def should_use_pglite() -> bool:
    """Return whether tests should use py-pglite, failing on invalid setup."""
    allowed_values = {"sqlite", "pglite"}
    target = os.getenv("EPISODIC_TEST_DB", "pglite").lower()
    if target not in allowed_values:
        msg = (
            f"Unsupported EPISODIC_TEST_DB value: {target!r}. "
            f"Allowed values are: {', '.join(sorted(allowed_values))}."
        )
        raise RuntimeError(msg)
    if target == "sqlite":
        return False
    if target == "pglite" and not PGLITE_AVAILABLE:
        msg = (
            "Database-backed tests requested via EPISODIC_TEST_DB="
            f"{target!r}, but py-pglite is not installed or unavailable. "
            "Install py-pglite (see docs/testing-sqlalchemy-with-pytest-and-"
            "py-pglite.md) or set EPISODIC_TEST_DB=sqlite."
        )
        raise RuntimeError(msg)
    return True


def prepare_pglite_work_dir(source: Path, destination: Path) -> Path:
    """Return ``destination`` ready to run, reusing already-installed modules.

    py-pglite skips its own install when the work directory already holds
    ``node_modules``, so linking the session's copy in keeps each work
    directory isolated while making the network call unnecessary. Only the
    module tree is shared: py-pglite regenerates ``package.json`` and
    ``pglite_manager.js`` for the destination, and the generated script has
    the destination's own socket path baked into it.

    Parameters
    ----------
    source : pathlib.Path
        Session directory whose ``node_modules`` was installed once.
    destination : pathlib.Path
        Per-test directory py-pglite will run the server from.

    Returns
    -------
    pathlib.Path
        ``destination``, with the shared module tree linked in.
    """
    destination.mkdir(parents=True, exist_ok=True)
    node_modules = destination / "node_modules"
    if not node_modules.exists():
        node_modules.symlink_to(source / "node_modules", target_is_directory=True)
    return destination


@pytest.fixture(scope="session")
def pglite_node_environment(
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """Return the session work root for py-pglite test processes."""
    if not should_use_pglite():
        pytest.skip("EPISODIC_TEST_DB=sqlite disables py-pglite-backed fixtures.")

    return tmp_path_factory.mktemp("pglite-node-env")


@pytest.fixture(scope="session")
def pglite_node_modules(pglite_node_environment: Path) -> Path:
    """Prime py-pglite's Node dependencies once for the whole session.

    The fixture starts one throwaway py-pglite server, which is what makes
    py-pglite stage its own ``package.json`` and install the modules into the
    session directory. A failed attempt clears any partial ``node_modules``
    first, so py-pglite retries the install rather than treating a truncated
    tree as usable.

    Returns
    -------
    pathlib.Path
        Session directory holding a populated ``node_modules``.

    Raises
    ------
    RuntimeError
        If py-pglite is unavailable or the server never starts.
    """
    if not PGLITE_AVAILABLE:  # pragma: no cover - defensive guard
        msg = "py-pglite is not available for runtime test fixtures."
        raise RuntimeError(msg)

    seed_dir = pglite_node_environment / "npm-seed"
    last_error: Exception | None = None
    for attempt in range(1, PGLITE_START_ATTEMPTS + 1):
        if attempt > 1:
            shutil.rmtree(seed_dir / "node_modules", ignore_errors=True)
        config = PGliteConfig(work_dir=seed_dir, timeout=90)
        manager = PGliteManager(config)
        try:
            manager.start()
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            last_error = exc
            manager.stop()
            continue
        manager.stop()
        return seed_dir

    msg = f"py-pglite dependency install failed after {PGLITE_START_ATTEMPTS} attempts"
    raise RuntimeError(msg) from last_error


__all__ = [
    "PGLITE_AVAILABLE",
    "PGLITE_START_ATTEMPTS",
    "pglite_node_environment",
    "pglite_node_modules",
    "prepare_pglite_work_dir",
    "should_use_pglite",
]
