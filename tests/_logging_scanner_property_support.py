"""Hypothesis source generation for logging-port scanner properties."""

import typing as typ

import hypothesis.strategies as st


class ScannerSource(typ.NamedTuple):
    """Generated source and independent expectations for one scanner case.

    Attributes
    ----------
    source : str
        Python source containing generated imports, aliases and a logger call.
    has_stdlib_logging_import : bool
        Whether the generated import statement names the absolute stdlib
        ``logging`` package or one of its submodules.
    should_find_logger_call : bool
        Whether the generated final call uses a recognised logger-level
        method on a handle returned by an imported logger factory.
    """

    source: str
    has_stdlib_logging_import: bool
    should_find_logger_call: bool


class _ScannerImport(typ.NamedTuple):
    """A generated import, the factory it exposes and whether it is absolute."""

    statement: str
    factory_reference: str
    is_absolute: bool


_ASSIGNMENT_STYLES = ("plain", "annotated", "tuple", "list")
_EXPECTED_LOGGER_METHODS = frozenset({
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
})
_SCANNER_METHODS = (
    *sorted(_EXPECTED_LOGGER_METHODS),
    "close",
    "emit",
    "flush",
    "setLevel",
    "write",
)


def _scanner_import(draw: st.DrawFn, suffix: int) -> _ScannerImport:
    """Build an absolute or relative import with its modelled classification."""
    import_shape = draw(
        st.sampled_from((
            "absolute_module",
            "absolute_submodule",
            "absolute_factory",
            "relative_module",
            "relative_factory",
        ))
    )
    module_alias = f"logging_module_{suffix}"
    imported_factory = f"imported_factory_{suffix}"
    match import_shape:
        case "absolute_module":
            return _ScannerImport(
                f"import logging as {module_alias}",
                f"{module_alias}.getLogger",
                is_absolute=True,
            )
        case "absolute_submodule":
            statement = "\n".join((
                f"import logging.config as {module_alias}",
                f"from logging import getLogger as {imported_factory}",
            ))
            return _ScannerImport(statement, imported_factory, is_absolute=True)
        case "absolute_factory":
            return _ScannerImport(
                f"from logging import getLogger as {imported_factory}",
                imported_factory,
                is_absolute=True,
            )
        case "relative_module":
            return _ScannerImport(
                f"from . import logging as {module_alias}",
                f"{module_alias}.getLogger",
                is_absolute=False,
            )
        case "relative_factory":
            return _ScannerImport(
                f"from .logging import getLogger as {imported_factory}",
                imported_factory,
                is_absolute=False,
            )
        case _:
            message = f"unknown generated import shape: {import_shape}"
            raise AssertionError(message)


def _assignment_statement(
    name: str,
    value: str,
    ignored_name: str,
    style: str,
) -> str:
    """Render one plain, annotated, tuple, or list assignment."""
    match style:
        case "plain":
            return f"{name} = {value}"
        case "annotated":
            return f"{name}: object = {value}"
        case "tuple":
            return f"{name}, {ignored_name} = {value}"
        case "list":
            return f"[{name}, {ignored_name}] = {value}"
        case _:
            message = f"unknown generated assignment style: {style}"
            raise AssertionError(message)


def _factory_aliases(
    draw: st.DrawFn,
    factory_reference: str,
    suffix: int,
) -> tuple[list[str], str]:
    """Generate a bounded chain of aliases for an imported factory."""
    statements: list[str] = []
    alias_count = draw(st.integers(min_value=0, max_value=3))
    for alias_index in range(alias_count):
        alias = f"factory_alias_{suffix}_{alias_index}"
        statements.append(f"{alias} = {factory_reference}")
        factory_reference = alias
    return statements, factory_reference


def _logger_aliases(
    draw: st.DrawFn,
    handle_name: str,
    suffix: int,
) -> tuple[list[str], str]:
    """Generate logger-handle aliases with varied assignment targets."""
    statements: list[str] = []
    alias_count = draw(st.integers(min_value=0, max_value=3))
    for alias_index in range(alias_count):
        alias = f"logger_alias_{suffix}_{alias_index}"
        ignored = f"ignored_alias_target_{suffix}"
        style = draw(st.sampled_from(_ASSIGNMENT_STYLES))
        statements.append(_assignment_statement(alias, handle_name, ignored, style))
        handle_name = alias
    return statements, handle_name


def _logger_call_statements(
    draw: st.DrawFn,
    factory_reference: str,
    suffix: int,
) -> tuple[list[str], str]:
    """Build aliases and a final method call from one generated logger."""
    factory_statements, factory_reference = _factory_aliases(
        draw,
        factory_reference,
        suffix,
    )
    handle = f"logger_handle_{suffix}"
    ignored = f"ignored_target_{suffix}"
    style = draw(st.sampled_from(_ASSIGNMENT_STYLES))
    handle_assignment = _assignment_statement(
        handle,
        f'{factory_reference}("scope")',
        ignored,
        style,
    )
    alias_statements, final_handle = _logger_aliases(draw, handle, suffix)
    method = draw(st.sampled_from(_SCANNER_METHODS))
    return [
        *factory_statements,
        handle_assignment,
        *alias_statements,
        f'{final_handle}.{method}("message")',
    ], method


@st.composite
def scanner_sources(draw: st.DrawFn) -> ScannerSource:
    """Generate scanner source and expectations from the source model.

    Returns
    -------
    SearchStrategy[ScannerSource]
        Hypothesis strategy that generates absolute or relative imports,
        factory and logger aliases, varied assignment targets, and a final
        recognised or unrecognised logger method call. Expected classifications
        come from the generated source shape rather than the AST scanner.
    """
    suffix = draw(st.integers(min_value=0, max_value=999))
    imports = _scanner_import(draw, suffix)
    call_statements, method = _logger_call_statements(
        draw,
        imports.factory_reference,
        suffix,
    )
    source = "\n".join((imports.statement, *call_statements))
    return ScannerSource(
        source=source,
        has_stdlib_logging_import=imports.is_absolute,
        should_find_logger_call=method in _EXPECTED_LOGGER_METHODS,
    )
