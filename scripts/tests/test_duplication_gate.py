"""Tests for the code-duplication gate helper script.

The gate depends on PyChase, which imports removed ``ast`` aliases on
Python 3.14, so the whole module is skipped when that import fails; the
``make duplication-test`` target runs these tests on Python 3.13.
"""

import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

SCRIPT_DIRECTORY = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

# A tuple constant keeps the handler parseable on Python 3.13, where the
# repository formatter's PEP 758 style (`except A, B:`) is a syntax error.
_GATE_IMPORT_ERRORS = (ImportError, AttributeError)

try:
    import duplication_gate as gate
except _GATE_IMPORT_ERRORS:  # pragma: no cover - Python 3.14 path
    pytest.skip(
        "duplication_gate requires PyChase, which needs Python < 3.14",
        allow_module_level=True,
    )


def _finding(
    first: str = "episodic/a.py::alpha",
    second: str = "episodic/b.py::beta",
    score: float = 1.0,
) -> gate.Finding:
    """Build a finding with derived locations for partitioning tests."""
    return gate.Finding(
        first=first,
        second=second,
        location_first=f"{first.split('::')[0]}:1-20",
        location_second=f"{second.split('::')[0]}:1-20",
        score=score,
    )


class TestAllowEntry:
    """Matching semantics for unit and pair allow entries."""

    def test_unit_entry_matches_either_side(self) -> None:
        """A unit entry silences any pair the unit participates in."""
        entry = gate.AllowEntry(units=("episodic/a.py::alpha",), reason="r")
        assert entry.matches("episodic/a.py::alpha", "episodic/b.py::beta"), (
            "Unit entry must match its left member."
        )
        assert entry.matches("episodic/b.py::beta", "episodic/a.py::alpha"), (
            "Unit entry must match its right member."
        )
        assert not entry.matches("episodic/b.py::beta", "episodic/c.py::gamma"), (
            "Unit entry must not match unrelated members."
        )

    def test_pair_entry_matches_unordered(self) -> None:
        """A pair entry silences only that unordered pair."""
        entry = gate.AllowEntry(
            units=("episodic/a.py::alpha", "episodic/b.py::beta"),
            reason="r",
        )
        assert entry.matches("episodic/b.py::beta", "episodic/a.py::alpha"), (
            "Pair entry must ignore member order."
        )
        assert not entry.matches("episodic/a.py::alpha", "episodic/c.py::gamma"), (
            "Pair entry must not match a different pair."
        )


class TestNormalizeFindings:
    """Normalization of raw PyChase pair payloads."""

    def test_orders_by_descending_score_then_location(self) -> None:
        """Findings sort by score, then by source location."""
        raw: list[gate._DetectorPairPayload] = [
            {
                "score": 0.9,
                "left": {
                    "file": "episodic/z.py",
                    "start_line": 1,
                    "end_line": 20,
                    "qualname": "one",
                },
                "right": {
                    "file": "episodic/z.py",
                    "start_line": 30,
                    "end_line": 50,
                    "qualname": "two",
                },
            },
            {
                "score": 1.0,
                "left": {
                    "file": "episodic/a.py",
                    "start_line": 5,
                    "end_line": 25,
                    "qualname": "three",
                },
                "right": {
                    "file": "episodic/b.py",
                    "start_line": 5,
                    "end_line": 25,
                    "qualname": "four",
                },
            },
        ]
        findings = gate.normalize_findings(raw)
        assert [f.score for f in findings] == [1.0, 0.9], (
            "Findings must descend by similarity."
        )
        assert findings[0].first == "episodic/a.py::three", (
            "Higher-scored finding must sort first."
        )
        assert findings[0].location_first == "episodic/a.py:5-25", (
            "Normalized location must retain source lines."
        )


class TestLoadAllowlist:
    """Allowlist parsing and validation."""

    def _write(self, tmp_path: Path, body: str) -> Path:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(textwrap.dedent(body), encoding="utf-8")
        return pyproject

    def test_loads_unit_and_pair_entries(self, tmp_path: Path) -> None:
        """Unit and pair entries load with their reasons."""
        pyproject = self._write(
            tmp_path,
            """\
            [[tool.duplication_gate.allow]]
            unit = "episodic/a.py::alpha"
            reason = "declarative"

            [[tool.duplication_gate.allow]]
            pair = ["episodic/b.py::beta", "episodic/c.py::gamma"]
            reason = "parallel contracts"
            """,
        )
        entries = gate.load_allowlist(pyproject)
        assert entries[0].units == ("episodic/a.py::alpha",), (
            "Unit entry must retain its target."
        )
        assert entries[1].units == ("episodic/b.py::beta", "episodic/c.py::gamma"), (
            "Pair entry must retain both targets."
        )
        assert entries[1].reason == "parallel contracts", (
            "Allow entry must retain its reason."
        )

    def test_missing_gate_table_yields_empty_allowlist(self, tmp_path: Path) -> None:
        """A pyproject without the gate table produces no entries."""
        pyproject = self._write(tmp_path, "[project]\nname = 'x'\nversion = '0'\n")
        assert gate.load_allowlist(pyproject) == (), (
            "Missing gate table must mean no allow entries."
        )

    @pytest.mark.parametrize(
        "body",
        [
            '[[tool.duplication_gate.allow]]\nunit = "episodic/a.py::alpha"\n',
            '[[tool.duplication_gate.allow]]\nunit = "a"\nreason = "r"\n',
            '[[tool.duplication_gate.allow]]\npair = ["a.py::x"]\nreason = "r"\n',
            '[[tool.duplication_gate.allow]]\nreason = "r"\n',
            (
                '[[tool.duplication_gate.allow]]\nunit = "episodic/a.py::x"\n'
                'pair = ["episodic/a.py::x", "episodic/b.py::y"]\nreason = "r"\n'
            ),
        ],
        ids=[
            "no-reason",
            "malformed-unit",
            "one-member-pair",
            "no-target",
            "both-kinds",
        ],
    )
    def test_rejects_malformed_entries(self, tmp_path: Path, body: str) -> None:
        """Malformed entries raise a configuration error."""
        pyproject = self._write(tmp_path, body)
        with pytest.raises(gate.GateConfigError):
            gate.load_allowlist(pyproject)


class TestPartitionFindings:
    """Blocking, allowed, and stale-entry partitioning."""

    def test_unmatched_findings_block(self) -> None:
        """A finding with no matching entry blocks the gate."""
        blocking, allowed, stale = gate.partition_findings([_finding()], [])
        assert len(blocking) == 1, "Unmatched finding must block."
        assert not allowed, "Unmatched finding must not be allowed."
        assert not stale, "Empty allowlist must not yield stale entries."

    def test_matched_findings_are_allowed(self) -> None:
        """Entries silence their findings and are not reported stale."""
        entry = gate.AllowEntry(units=("episodic/a.py::alpha",), reason="r")
        blocking, allowed, stale = gate.partition_findings([_finding()], [entry])
        assert not blocking, "Matching entry must prevent blocking."
        assert len(allowed) == 1, "Matching entry must allow the finding."
        assert not stale, "Used entry must not be stale."

    def test_unused_entries_are_stale(self) -> None:
        """Entries matching nothing are reported for removal."""
        entry = gate.AllowEntry(units=("episodic/gone.py::old",), reason="r")
        blocking, _allowed, stale = gate.partition_findings([_finding()], [entry])
        assert len(blocking) == 1, "Unmatched finding must remain blocking."
        assert stale == [entry], "Unused allow entry must be stale."


class TestAppendAllowEntry:
    """Appending reasoned entries to pyproject."""

    def test_round_trips_unit_and_pair_entries(self, tmp_path: Path) -> None:
        """Appended entries are re-loadable and preserve existing content."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "x"\nversion = "0"\n', encoding="utf-8")
        gate.append_allow_entry(
            pyproject,
            first="episodic/a.py::alpha",
            second=None,
            reason="unit reason",
        )
        gate.append_allow_entry(
            pyproject,
            first="episodic/b.py::beta",
            second="episodic/c.py::gamma",
            reason="pair reason",
        )
        gate.append_allow_entry(
            pyproject,
            first="episodic/c.py::gamma",
            second="episodic/b.py::beta",
            reason="updated pair reason",
        )
        entries = gate.load_allowlist(pyproject)
        assert entries[0].units == ("episodic/a.py::alpha",), (
            "Unit entry must round-trip."
        )
        assert entries[1].units == ("episodic/b.py::beta", "episodic/c.py::gamma"), (
            "Pair entry must round-trip."
        )
        assert entries[1].reason == "updated pair reason", (
            "Repeated pair must update its reason."
        )
        assert len(entries) == 2, "Repeated pair must not create a duplicate entry."
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        assert data["project"]["name"] == "x", (
            "Appending must preserve existing TOML content."
        )

    def test_atomic_write_leaves_original_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed atomic replacement leaves the existing configuration intact."""
        pyproject = tmp_path / "pyproject.toml"
        original = '[project]\nname = "x"\nversion = "0"\n'
        pyproject.write_text(original, encoding="utf-8")
        error_message = "replacement failed"

        def fail_replace(_source: Path, _destination: Path) -> None:
            raise OSError(error_message)

        monkeypatch.setattr(Path, "replace", fail_replace)
        with pytest.raises(OSError, match=error_message):
            gate.append_allow_entry(
                pyproject,
                first="episodic/a.py::alpha",
                second=None,
                reason="unit reason",
            )
        assert pyproject.read_text(encoding="utf-8") == original, (
            "Failed replacement must preserve the original TOML."
        )


class TestGateCommands:
    """CLI command orchestration and deterministic user-facing reports."""

    def test_check_reports_blocking_findings(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The check command emits the blocking report and status one."""
        monkeypatch.setattr(gate, "load_allowlist", lambda _path: ())
        monkeypatch.setattr(gate, "run_detector", lambda: [_finding()])
        with pytest.raises(SystemExit) as error:
            gate.check()
        assert error.value.code == 1, "Blocking findings must return status one."
        assert capsys.readouterr().out == (
            "duplicate code: 1 unsuppressed pair(s)\n"
            "  episodic/a.py:1-20 ~ episodic/b.py:1-20 (similarity 1.00)\n"
            "    units: episodic/a.py::alpha ~ episodic/b.py::beta\n"
            "Extract the shared logic into one helper, or record a considered "
            "exception:\n"
            "  make duplication-allow FIRST='<path::qualname>' "
            "[SECOND='<path::qualname>'] REASON='<why this stays>'\n"
        ), "Blocking report must remain actionable and deterministic."

    def test_deterministic_hashing_reexecs_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unpinned process re-execs itself with a deterministic hash seed."""
        calls: list[tuple[str, list[str]]] = []
        monkeypatch.delenv("PYTHONHASHSEED", raising=False)
        monkeypatch.setattr(
            gate.os,
            "execv",
            lambda executable, arguments: calls.append((executable, arguments)),
        )
        gate._ensure_deterministic_hashing()
        assert gate.os.environ["PYTHONHASHSEED"] == "0", (
            "Re-exec must pin the hash seed."
        )
        assert calls == [
            (gate.sys.executable, [gate.sys.executable, *gate.sys.argv])
        ], "Re-exec must retain the current interpreter and arguments."


class TestDetectorIntegration:
    """End-to-end detection over a fixture tree with the pinned PyChase."""

    def test_reports_a_planted_verbatim_copy(self, tmp_path: Path) -> None:
        """The engine reports a planted copy that normalization equates."""
        body = textwrap.dedent(
            """\
            def NAME(items):
                total = 0.0
                for item in items:
                    price = item["price"] * item["quantity"]
                    if item.get("taxable"):
                        price *= 1.2
                    if item.get("discount"):
                        price -= item["discount"]
                    total += price
                if total < 0:
                    total = 0.0
                return round(total, 2)
            """
        )
        module = tmp_path / "mod.py"
        module.write_text(
            body.replace("NAME", "first_total")
            + "\n\n"
            + body.replace("NAME", "second_total"),
            encoding="utf-8",
        )
        from pychase.cli import (  # ty: ignore[unresolved-import]  # pychase installs only in the gate's Python 3.13 environment.
            Config,
        )
        from pychase.engine import (  # ty: ignore[unresolved-import]  # pychase installs only in the gate's Python 3.13 environment.
            find,
        )

        config = Config()
        config.threshold = 0.9
        config.min_lines = 5
        config.min_nodes = 10
        findings = gate.normalize_findings(find([str(module)], config)["pairs"])
        assert len(findings) == 1, "Planted copy must produce one pair."
        assert findings[0].score == 1.0, "Verbatim copy must have perfect similarity."
        assert findings[0].first.endswith("::first_total"), (
            "First unit key must use its qualname."
        )
        assert findings[0].second.endswith("::second_total"), (
            "Second unit key must use its qualname."
        )
