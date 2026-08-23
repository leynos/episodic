"""Persistence and contention tests for duplication-gate allow entries."""

import subprocess  # noqa: S404 - tests exercise copied gate commands.
import tomllib
from pathlib import Path

import pytest
from duplication_gate_test_support import (
    copied_gate_workspace,
    gate,
    gate_command,
    gate_environment,
)


class TestAppendAllowEntry:
    """Persisting reasoned entries to ``pyproject.toml``."""

    def test_round_trips_unit_and_pair_entries(self, tmp_path: Path) -> None:
        """Appended entries load again and preserve existing TOML content."""
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
            "Unit entry must retain its target."
        )
        assert entries[1].units == ("episodic/b.py::beta", "episodic/c.py::gamma"), (
            "Pair entry must retain both targets."
        )
        assert entries[1].reason == "updated pair reason", (
            "Repeated pair must update its reason."
        )
        assert len(entries) == 2, "Repeated pair must not create a duplicate entry."
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        assert data["project"]["name"] == "x", (
            "Appending must preserve existing TOML content."
        )

    def test_atomic_write_preserves_mode_and_original_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failed replacement retains contents, mode, and a usable lock."""
        pyproject = tmp_path / "pyproject.toml"
        original = '[project]\nname = "x"\nversion = "0"\n'
        pyproject.write_text(original, encoding="utf-8")
        pyproject.chmod(0o640)
        original_replace = Path.replace

        def fail_replace(_source: Path, _destination: Path) -> None:
            msg = "replacement failed"
            raise OSError(msg)

        monkeypatch.setattr(Path, "replace", fail_replace)
        with pytest.raises(OSError, match="replacement failed"):
            gate.append_allow_entry(
                pyproject,
                first="episodic/a.py::alpha",
                second=None,
                reason="unit reason",
            )
        monkeypatch.setattr(Path, "replace", original_replace)

        assert pyproject.read_text(encoding="utf-8") == original, (
            "Failed replacement must preserve the original TOML."
        )
        gate.append_allow_entry(
            pyproject,
            first="episodic/a.py::alpha",
            second=None,
            reason="unit reason",
        )
        assert pyproject.stat().st_mode & 0o777 == 0o640, (
            "Replacement must preserve the destination mode."
        )

    def test_concurrent_allow_commands_preserve_both_entries(
        self, tmp_path: Path
    ) -> None:
        """Two blocked writers retain both exceptions after the lock releases."""
        _, script = copied_gate_workspace(tmp_path)
        with gate._locked_file(script.parent.parent / "pyproject.toml"):
            first = subprocess.Popen(  # noqa: S603 - fixed copied gate command.
                gate_command(
                    script,
                    "allow",
                    "--first",
                    "episodic/a.py::alpha",
                    "--reason",
                    "first writer",
                ),
                cwd=script.parent.parent,
                env=gate_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            second = subprocess.Popen(  # noqa: S603 - fixed copied gate command.
                gate_command(
                    script,
                    "allow",
                    "--first",
                    "episodic/b.py::beta",
                    "--reason",
                    "second writer",
                ),
                cwd=script.parent.parent,
                env=gate_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert first.poll() is None, "First writer must wait for the lock."
            assert second.poll() is None, "Second writer must wait for the lock."

        assert first.wait(timeout=10) == 0, "First writer must exit successfully."
        assert second.wait(timeout=10) == 0, "Second writer must exit successfully."

        entries = tomllib.loads(
            (script.parent.parent / "pyproject.toml").read_text(encoding="utf-8")
        )["tool"]["duplication_gate"]["allow"]
        recorded_units = {entry["unit"] for entry in entries}
        assert recorded_units == {"episodic/a.py::alpha", "episodic/b.py::beta"}, (
            "Concurrent commands must preserve both independently added entries."
        )
