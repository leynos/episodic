#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["cyclopts", "pychase==0.1.0", "tomlkit"]
# ///
# Python 3.13 is required rather than the standard 3.14: pychase 0.1.0
# imports the ast.Str/ast.Bytes/ast.Num aliases that Python 3.14 removed.
"""Blocking code-duplication gate over the pinned PyChase detector.

The gate runs PyChase with the repository's ``[tool.pychase]`` settings,
removes pairs covered by reasoned ``[tool.duplication_gate]`` allow entries,
and fails while unsuppressed duplicate pairs remain. Stale allow entries are
reported so that resolved duplication does not leave dead configuration
behind.

Allow entries name either one unit (``unit = "path::qualname"``), silencing
every pair that unit participates in, or one unordered pair
(``pair = ["path::qualname", "path::qualname"]``). Every entry records a
reason so exceptions stay reviewable in version control.
"""

from __future__ import annotations

import dataclasses as dc
import os
import sys
import tomllib
import typing as typ
from pathlib import Path

import cyclopts
import tomlkit
from pychase.cli import (  # ty: ignore[unresolved-import]  # pychase installs only in this script's Python 3.13 environment.
    Config,
    _collect_files,
)
from pychase.engine import (  # ty: ignore[unresolved-import]  # pychase installs only in this script's Python 3.13 environment.
    find,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

app = cyclopts.App(help="Run or configure the code-duplication gate.")

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"

type FindingPayload = dict[str, typ.Any]


@dc.dataclass(frozen=True, slots=True)
class AllowEntry:
    """One reasoned exception from the duplication gate.

    Attributes
    ----------
    units : tuple[str, ...]
        One unit key for a unit entry, or two for a pair entry. Unit keys
        take the form ``"path::qualname"`` with a repository-relative path.
    reason : str
        Reviewable justification recorded alongside the entry.
    """

    units: tuple[str, ...]
    reason: str

    def matches(self, first: str, second: str) -> bool:
        """Report whether this entry silences the pair ``(first, second)``."""
        if len(self.units) == 1:
            return self.units[0] in {first, second}
        return {first, second} == set(self.units)


@dc.dataclass(frozen=True, slots=True)
class Finding:
    """One reported duplicate pair in gate-neutral form.

    Attributes
    ----------
    first : str
        Unit key of the first member.
    second : str
        Unit key of the second member.
    location_first : str
        ``path:start-end`` source span of the first member.
    location_second : str
        ``path:start-end`` source span of the second member.
    score : float
        Detector-reported structural similarity.
    """

    first: str
    second: str
    location_first: str
    location_second: str
    score: float


class GateConfigError(RuntimeError):
    """Raised when the gate configuration is malformed."""


def _unit_key(member: FindingPayload) -> str:
    """Build the ``path::qualname`` key for one reported member."""
    return f"{Path(member['file']).as_posix()}::{member['qualname']}"


def _location(member: FindingPayload) -> str:
    """Build the ``path:start-end`` span for one reported member."""
    path = Path(member["file"]).as_posix()
    return f"{path}:{member['start_line']}-{member['end_line']}"


def normalize_findings(pairs: cabc.Iterable[FindingPayload]) -> list[Finding]:
    """Convert raw PyChase pairs into gate findings.

    Parameters
    ----------
    pairs : collections.abc.Iterable[dict]
        Raw pair payloads from the PyChase engine.

    Returns
    -------
    list[Finding]
        Findings ordered by descending score then location.
    """
    findings = [
        Finding(
            first=_unit_key(pair["left"]),
            second=_unit_key(pair["right"]),
            location_first=_location(pair["left"]),
            location_second=_location(pair["right"]),
            score=float(pair["score"]),
        )
        for pair in pairs
    ]
    findings.sort(key=lambda f: (-f.score, f.location_first, f.location_second))
    return findings


def load_allowlist(pyproject_path: Path) -> tuple[AllowEntry, ...]:
    """Load the reasoned allow entries from ``[tool.duplication_gate]``.

    Parameters
    ----------
    pyproject_path : pathlib.Path
        Path to the repository ``pyproject.toml``.

    Returns
    -------
    tuple[AllowEntry, ...]
        Parsed allow entries in file order.

    Raises
    ------
    GateConfigError
        If an entry is missing a reason or names neither a unit nor a pair.
    """
    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)
    table = data.get("tool", {}).get("duplication_gate", {})
    entries: list[AllowEntry] = []
    for index, raw in enumerate(table.get("allow", [])):
        reason = raw.get("reason", "")
        if not isinstance(reason, str) or not reason.strip():
            msg = f"duplication_gate.allow[{index}] requires a non-empty reason"
            raise GateConfigError(msg)
        entries.append(AllowEntry(units=_entry_units(raw, index), reason=reason))
    return tuple(entries)


def _entry_units(raw: dict[str, typ.Any], index: int) -> tuple[str, ...]:
    """Extract and validate the unit keys named by one allow entry."""
    unit = raw.get("unit")
    pair = raw.get("pair")
    context = f"duplication_gate.allow[{index}]"
    if (unit is None) == (pair is None):
        msg = f"{context} must set exactly one of 'unit' or 'pair'"
        raise GateConfigError(msg)
    if unit is not None:
        if not isinstance(unit, str) or "::" not in unit:
            msg = f"{context} unit must be a 'path::qualname' string"
            raise GateConfigError(msg)
        return (unit,)
    match pair:
        case [str() as first, str() as second] if "::" in first and "::" in second:
            return (first, second)
        case _:
            msg = f"{context} pair must be two 'path::qualname' strings"
            raise GateConfigError(msg)


def partition_findings(
    findings: cabc.Sequence[Finding],
    allowlist: cabc.Sequence[AllowEntry],
) -> tuple[list[Finding], list[Finding], list[AllowEntry]]:
    """Split findings into blocking and allowed, and spot stale entries.

    Parameters
    ----------
    findings : collections.abc.Sequence[Finding]
        Normalized detector findings.
    allowlist : collections.abc.Sequence[AllowEntry]
        Reasoned exceptions from the repository configuration.

    Returns
    -------
    tuple[list[Finding], list[Finding], list[AllowEntry]]
        Blocking findings, silenced findings, and allow entries that no
        longer match any finding.
    """
    blocking: list[Finding] = []
    allowed: list[Finding] = []
    used: set[int] = set()
    for finding in findings:
        matched = False
        for position, entry in enumerate(allowlist):
            if entry.matches(finding.first, finding.second):
                used.add(position)
                matched = True
        (allowed if matched else blocking).append(finding)
    stale = [entry for position, entry in enumerate(allowlist) if position not in used]
    return blocking, allowed, stale


def run_detector() -> list[Finding]:
    """Run PyChase with the repository configuration and normalize output."""
    config = Config.from_pyproject(str(PYPROJECT))
    files = _collect_files(config.paths, config.exclude)
    result = find(files, config)
    return normalize_findings(result["pairs"])


def _report(
    blocking: list[Finding], allowed: list[Finding], stale: list[AllowEntry]
) -> None:
    """Print the gate outcome in a concise, actionable form."""
    for entry in stale:
        joined = " ~ ".join(entry.units)
        print(f"stale allow entry ({joined}): remove it; the duplication is gone")
    if not blocking:
        suffix = f"; {len(allowed)} allowed by reasoned exceptions" if allowed else ""
        print(f"duplication gate passed{suffix}")
        return
    print(f"duplicate code: {len(blocking)} unsuppressed pair(s)")
    for finding in blocking:
        print(
            f"  {finding.location_first} ~ {finding.location_second} "
            f"(similarity {finding.score:.2f})"
        )
        print(f"    units: {finding.first} ~ {finding.second}")
    print(
        "Extract the shared logic into one helper, or record a considered "
        "exception:\n  make duplication-allow FIRST='<path::qualname>' "
        "[SECOND='<path::qualname>'] REASON='<why this stays>'"
    )


@app.command
def check() -> None:
    """Run the blocking duplication gate and exit non-zero on findings."""
    os.chdir(REPO_ROOT)
    try:
        allowlist = load_allowlist(PYPROJECT)
    except GateConfigError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    findings = run_detector()
    blocking, allowed, stale = partition_findings(findings, allowlist)
    _report(blocking, allowed, stale)
    if blocking:
        raise SystemExit(1)


@app.command
def allow(
    *,
    first: str,
    second: str | None = None,
    reason: str,
) -> None:
    """Record one reasoned exception in ``[tool.duplication_gate]``.

    Parameters
    ----------
    first : str
        Unit key (``path::qualname``) of the first or only member.
    second : str | None
        Optional second unit key; when set, the entry silences only this
        pair rather than every pair involving ``first``.
    reason : str
        Reviewable justification for keeping the duplication.

    Raises
    ------
    SystemExit
        If the reason is empty or a unit key is malformed.
    """
    if not reason.strip():
        print("REASON must not be empty", file=sys.stderr)
        raise SystemExit(2)
    for key in (first, second) if second else (first,):
        if "::" not in key:
            print(f"'{key}' is not a 'path::qualname' unit key", file=sys.stderr)
            raise SystemExit(2)
    append_allow_entry(PYPROJECT, first=first, second=second, reason=reason)
    label = first if second is None else f"{first} ~ {second}"
    print(f"recorded duplication exception for {label}")


def append_allow_entry(
    pyproject_path: Path,
    *,
    first: str,
    second: str | None,
    reason: str,
) -> None:
    """Append one allow entry to ``[tool.duplication_gate]`` in place.

    Parameters
    ----------
    pyproject_path : pathlib.Path
        Path to the ``pyproject.toml`` to update.
    first : str
        Unit key of the first or only member.
    second : str | None
        Optional second unit key for a pair entry.
    reason : str
        Reviewable justification recorded with the entry.
    """
    document = tomlkit.parse(pyproject_path.read_text(encoding="utf-8"))
    tool = document.setdefault("tool", tomlkit.table(is_super_table=True))
    gate = tool.setdefault("duplication_gate", tomlkit.table())
    entries = gate.setdefault("allow", tomlkit.aot())
    entry = tomlkit.table()
    if second is None:
        entry["unit"] = first
    else:
        entry["pair"] = [first, second]
    entry["reason"] = reason
    entries.append(entry)
    pyproject_path.write_text(tomlkit.dumps(document), encoding="utf-8")


def _ensure_deterministic_hashing() -> None:
    """Re-exec with a fixed hash seed so LSH bucketing is reproducible.

    PyChase buckets MinHash signatures with the built-in ``hash()`` over
    strings, which Python randomizes per process unless ``PYTHONHASHSEED``
    is pinned. Without this, near-threshold pairs appear and disappear
    between runs, which a blocking gate cannot tolerate.
    """
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable, *sys.argv])  # noqa: S606 - re-exec of the same interpreter with a pinned hash seed


if __name__ == "__main__":
    _ensure_deterministic_hashing()
    app()
