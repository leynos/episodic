"""Regression tests for logging-port call-site enforcement."""

import ast
import pathlib as pl
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]  # The test invokes a fixed local typechecker command.

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
DIRECT_CALL_FIXTURE = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "typecheck"
    / "logging_handle_direct_call.py"
)
STDLIB_LOGGING_FIXTURES = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "logging_port" / "stdlib_module_alias.py",
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "logging_port"
    / "stdlib_named_receiver.py",
    REPOSITORY_ROOT / "tests" / "fixtures" / "logging_port" / "stdlib_from_import.py",
)
LOGGER_LEVEL_METHODS = {
    "debug",
    "info",
    "warning",
    "warn",
    "error",
    "exception",
    "critical",
    "fatal",
    "log",
    "isEnabledFor",
}
CONVENTIONAL_LOGGER_NAMES = {"logger", "_log", "_logger", "effective_log"}


def _imports_stdlib_logging(source: str) -> bool:
    """Return whether Python source imports the stdlib logging package."""
    module = ast.parse(source)
    return any(_is_stdlib_logging_import(node) for node in ast.walk(module))


def _is_stdlib_logging_import(node: ast.AST) -> bool:
    """Match an absolute import of the stdlib logging package."""
    match node:
        case ast.Import(names=aliases):
            return any(_is_stdlib_logging_module(alias.name) for alias in aliases)
        case ast.ImportFrom(module=module, level=0):
            return _is_stdlib_logging_module(module)
        case _:
            return False


def _is_stdlib_logging_module(module_name: str | None) -> bool:
    """Match the standard-library logging package and its submodules."""
    return module_name == "logging" or (
        module_name is not None and module_name.startswith("logging.")
    )


def _has_direct_logger_level_call(source: str) -> bool:
    """Find level-method calls on names bound to a logger factory."""
    module = ast.parse(source)
    logger_names = CONVENTIONAL_LOGGER_NAMES.copy()

    while True:
        newly_bound_names = {
            target_name
            for node in ast.walk(module)
            for target_name in _logger_names_assigned_by(node, logger_names)
        }
        new_names = newly_bound_names - logger_names
        if not new_names:
            break
        logger_names.update(new_names)

    return any(
        _is_direct_logger_level_call(node, logger_names) for node in ast.walk(module)
    )


def _logger_names_assigned_by(node: ast.AST, logger_names: set[str]) -> set[str]:
    """Return names assigned from a logger factory or existing handle alias."""
    assigned_names: set[str] = set()
    for value, targets in _assignment_values_and_targets(node):
        match value:
            case ast.Call() if _is_logger_factory_call(value):
                assigned_names.update(
                    name for target in targets for name in _assigned_names(target)
                )
            case ast.Name(id=name) if name in logger_names:
                assigned_names.update(
                    name for target in targets for name in _assigned_names(target)
                )
    return assigned_names


def _is_direct_logger_level_call(node: ast.AST, logger_names: set[str]) -> bool:
    """Match level-method calls on known logger handles."""
    match node:
        case ast.Call(func=ast.Attribute(attr=method, value=ast.Name(id=logger_name))):
            return method in LOGGER_LEVEL_METHODS and logger_name in logger_names
        case _:
            return False


def _assignment_values_and_targets(
    node: ast.AST,
) -> list[tuple[ast.expr, list[ast.expr]]]:
    """Return assignment values with the targets that receive each value."""
    match node:
        case ast.Assign(value=value, targets=targets):
            return [(value, targets)]
        case ast.AnnAssign(value=value, target=target) if value is not None:
            return [(value, [target])]
        case _:
            return []


def _is_logger_factory_call(expression: ast.expr) -> bool:
    """Recognize calls that create a stdlib or application logger handle."""
    match expression:
        case ast.Call(func=ast.Name(id=name)):
            return name in {"getLogger", "get_logger"}
        case ast.Call(func=ast.Attribute(attr=name)):
            return name in {"getLogger", "get_logger"}
        case _:
            return False


def _assigned_names(target: ast.expr) -> set[str]:
    """Collect names assigned by a simple or unpacked assignment target."""
    match target:
        case ast.Name(id=name):
            return {name}
        case ast.Tuple(elts=elements) | ast.List(elts=elements):
            return {name for element in elements for name in _assigned_names(element)}
        case _:
            return set()


def test_typechecker_rejects_direct_logger_handle_calls() -> None:
    """The opaque handle rejects raw level-method calls under ty."""
    make_executable = shutil.which("make")
    assert make_executable is not None, "Expected make to run the pinned ty release."
    completed_process = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # Static local command and fixture path.
        [
            make_executable,
            "--no-print-directory",
            "typecheck-path",
            f"TY_CHECK_PATH={DIRECT_CALL_FIXTURE}",
        ],
        check=False,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        text=True,
        timeout=120,
    )

    rendered = f"{completed_process.stdout}\n{completed_process.stderr}"
    assert completed_process.returncode != 0, rendered
    assert "info" in rendered, rendered
    assert "LoggerHandle" in rendered, rendered


def test_production_logger_calls_use_the_logging_port() -> None:
    """Production modules must not acquire stdlib loggers outside the port."""
    offending_paths = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in (REPOSITORY_ROOT / "episodic").glob("**/*.py")
        if path != REPOSITORY_ROOT / "episodic" / "logging.py"
        and (source := path.read_text(encoding="utf-8"))
        and (_imports_stdlib_logging(source) or _has_direct_logger_level_call(source))
    }

    assert not offending_paths, (
        "stdlib logging imports bypass the logging port in: "
        f"{sorted(offending_paths)!r}"
    )


def test_production_import_scanner_detects_logging_aliases_and_receivers() -> None:
    """The AST guard catches stdlib logger imports regardless of local names."""
    detected_fixtures = {
        path.name
        for path in STDLIB_LOGGING_FIXTURES
        if (source := path.read_text(encoding="utf-8"))
        and _imports_stdlib_logging(source)
        and _has_direct_logger_level_call(source)
    }

    expected_fixtures = {path.name for path in STDLIB_LOGGING_FIXTURES}
    assert detected_fixtures == expected_fixtures, (
        "the AST scanner must catch stdlib logging imports regardless of alias "
        f"or receiver name: {sorted(detected_fixtures)!r}"
    )


def test_production_import_scanner_ignores_relative_logging_imports() -> None:
    """Relative imports named logging do not import the stdlib package."""
    assert not _imports_stdlib_logging("from .logging import get_logger"), (
        "relative imports should not be classified as stdlib logging"
    )
