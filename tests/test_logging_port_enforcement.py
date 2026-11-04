"""Regression tests for logging-port call-site enforcement."""

import ast
import pathlib as pl
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]  # The test invokes a fixed local typechecker command.

from hypothesis import given

from tests._logging_scanner_property_support import ScannerSource, scanner_sources

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
    factory_names = _logger_factory_names(module)
    logger_names = CONVENTIONAL_LOGGER_NAMES.copy()

    while True:
        newly_bound_names = {
            target_name
            for node in ast.walk(module)
            for target_name in _logger_names_assigned_by(
                node,
                factory_names,
                logger_names,
            )
        }
        new_names = newly_bound_names - logger_names
        if not new_names:
            break
        logger_names.update(new_names)

    return any(
        _is_direct_logger_level_call(node, logger_names) for node in ast.walk(module)
    )


def _logger_factory_names(module: ast.Module) -> set[str]:
    """Return factory names imported or aliased in the source module."""
    factory_names = {"getLogger", "get_logger"}
    for node in ast.walk(module):
        factory_names.update(_imported_logger_factory_names(node))
    return _logger_factory_aliases(module, factory_names)


def _imported_logger_factory_names(node: ast.AST) -> set[str]:
    """Return logger factory names introduced by one import statement."""
    match node:
        case ast.ImportFrom(names=aliases):
            return {
                alias.asname or alias.name
                for alias in aliases
                if alias.name in {"getLogger", "get_logger"}
            }
        case _:
            return set()


def _logger_factory_aliases(
    module: ast.Module,
    factory_names: set[str],
) -> set[str]:
    """Follow assignments that alias an imported logger factory."""
    while True:
        newly_bound_names = {
            name
            for node in ast.walk(module)
            for name in _logger_factory_names_assigned_by(node, factory_names)
        }
        new_names = newly_bound_names - factory_names
        if not new_names:
            return factory_names
        factory_names.update(new_names)


def _logger_factory_names_assigned_by(
    node: ast.AST,
    factory_names: set[str],
) -> set[str]:
    """Return names assigned from one known logger factory reference."""
    return {
        name
        for value, targets in _assignment_values_and_targets(node)
        if _is_logger_factory_reference(value, factory_names)
        for target in targets
        for name in _assigned_names(target)
    }


def _logger_names_assigned_by(
    node: ast.AST,
    factory_names: set[str],
    logger_names: set[str],
) -> set[str]:
    """Return names assigned from a logger factory or existing handle alias."""
    assigned_names: set[str] = set()
    for value, targets in _assignment_values_and_targets(node):
        match value:
            case ast.Call() if _is_logger_factory_call(value, factory_names):
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


def _is_logger_factory_call(
    expression: ast.expr,
    factory_names: set[str],
) -> bool:
    """Recognize calls that create a stdlib or application logger handle."""
    match expression:
        case ast.Call(func=function):
            return _is_logger_factory_reference(function, factory_names)
        case _:
            return False


def _is_logger_factory_reference(
    expression: ast.expr,
    factory_names: set[str],
) -> bool:
    """Match a known factory name or a conventional factory attribute."""
    match expression:
        case ast.Name(id=name):
            return name in factory_names
        case ast.Attribute(attr=name):
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


@given(case=scanner_sources())
def test_scanner_properties_match_the_source_shape_oracle(
    case: ScannerSource,
) -> None:
    """Generated import and alias shapes follow the independent source model."""
    assert _imports_stdlib_logging(case.source) is case.has_stdlib_logging_import, (
        f"stdlib import classification disagreed with the generated source model:\n"
        f"{case.source}"
    )
    assert _has_direct_logger_level_call(case.source) is case.should_find_logger_call, (
        f"logger-call classification disagreed with the generated source model:\n"
        f"{case.source}"
    )
