"""Command-line behaviour tests for the duplication gate."""

import dataclasses as dc
import json
import subprocess  # noqa: S404 - tests exercise copied gate and Make commands.
import sys
import textwrap
import typing as typ

import pytest
from duplication_gate_test_support import (
    REPOSITORY_ROOT,
    allowlist,
    copied_gate_workspace,
    detector,
    gate,
    gate_environment,
    run_gate_command,
    write_stub_nose,
)

if typ.TYPE_CHECKING:
    from pathlib import Path


def _finding() -> detector.Finding:
    """Build a representative blocking finding."""
    return detector.Finding(
        witness="copy-paste",
        value=22.1,
        locations=(
            detector.Location(file="episodic/a.py", start=1, end=20, name=None),
            detector.Location(file="episodic/b.py", start=30, end=49, name="beta"),
        ),
    )


class TestGateCommands:
    """CLI orchestration and real workflow contracts."""

    def test_check_reports_blocking_findings(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The check command emits the blocking report and status one."""
        monkeypatch.chdir(typ.cast("Path", tmp_path))
        monkeypatch.setattr(gate, "load_allowlist", lambda _path: ())
        monkeypatch.setattr(gate, "detect_findings", lambda: [_finding()])
        with pytest.raises(SystemExit) as error:
            gate.check()
        assert error.value.code == 1, "Blocking findings must return status one."
        assert capsys.readouterr().out == (
            "duplicate code: 1 unsuppressed family/families\n"
            "  episodic/a.py:1-20 ~ episodic/b.py:30-49 beta "
            "(copy-paste, value 22.1)\n"
            "Extract the shared logic into one helper, or record a considered "
            "exception:\n"
            "  make duplication-allow FIRST='<path[::name]>' "
            "[SECOND='<path[::name]>'] REASON='<why this stays>'\n"
        ), "Blocking report must remain actionable and deterministic."

    def test_check_reports_stale_entries(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Allow entries covering nothing are reported for removal."""
        monkeypatch.chdir(typ.cast("Path", tmp_path))
        entry = allowlist.AllowEntry(keys=("episodic/gone.py",), reason="resolved")
        monkeypatch.setattr(gate, "load_allowlist", lambda _path: (entry,))
        monkeypatch.setattr(gate, "detect_findings", lambda: [])
        gate.check()
        assert capsys.readouterr().out == (
            "stale allow entry (episodic/gone.py): remove it; "
            "the duplication is gone\n"
            "duplication gate passed\n"
        ), "Stale entries must be reported alongside a passing gate."

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(OSError("unreadable configuration"), id="allowlist-io"),
            pytest.param(OSError("detector executable unavailable"), id="detector-io"),
            pytest.param(
                RuntimeError("detector runtime failed"), id="detector-runtime"
            ),
        ],
    )
    def test_check_inputs_wrap_environment_failures(self, error: Exception) -> None:
        """Injected reader and detector failures become explicit gate errors."""
        if str(error).startswith("unreadable"):

            def reader(_path: object) -> tuple[allowlist.AllowEntry, ...]:
                raise error

            def detect() -> list[detector.Finding]:
                return []

        else:

            def reader(_path: object) -> tuple[allowlist.AllowEntry, ...]:
                return ()

            def detect() -> list[detector.Finding]:
                raise error

        with pytest.raises(gate.GateExecutionError, match=str(error)):
            gate._check_inputs(allowlist_reader=reader, detector=detect)

    def test_check_reports_detector_schema_errors(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Malformed detector reports exit cleanly instead of showing a traceback."""
        monkeypatch.chdir(typ.cast("Path", tmp_path))
        monkeypatch.setattr(gate, "load_allowlist", lambda _path: ())

        def raise_schema_error() -> list[detector.Finding]:
            msg = "nose report families must be an array"
            raise TypeError(msg)

        monkeypatch.setattr(gate, "detect_findings", raise_schema_error)
        with pytest.raises(SystemExit) as error:
            gate.check()

        assert error.value.code == 2, "Malformed detector reports must return two."
        assert capsys.readouterr().err == (
            "configuration error: nose report families must be an array\n"
        ), "Schema errors must use the configuration diagnostic."

    def test_check_reports_a_version_mismatch(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An unpinned detector fails the gate with a remediation message."""
        workspace = typ.cast("Path", tmp_path)
        stub = write_stub_nose(workspace, version="nose 0.19.0")
        monkeypatch.setenv("NOSE_BIN", str(stub))
        monkeypatch.chdir(workspace)
        monkeypatch.setattr(gate, "load_allowlist", lambda _path: ())
        with pytest.raises(SystemExit) as error:
            gate.check()
        assert error.value.code == 2, "A version mismatch must return two."
        assert "make install-nose" in capsys.readouterr().err, (
            "The mismatch diagnostic must name the install remediation."
        )

    def test_allow_reports_malformed_existing_entries(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Malformed existing allows exit cleanly instead of showing a traceback."""
        pyproject = typ.cast("Path", tmp_path) / "pyproject.toml"
        pyproject.write_text(
            '[[tool.duplication_gate.allow]]\nunit = "episodic/a.py"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(gate, "PYPROJECT", pyproject)

        with pytest.raises(SystemExit) as error:
            gate.allow(first="episodic/b.py", reason="reviewed exception")

        assert error.value.code == 2, "Malformed existing allows must return two."
        assert capsys.readouterr().err == (
            "configuration error: duplication_gate.allow[0] "
            "requires a non-empty reason\n"
        ), "Malformed allows must use the configuration diagnostic."

    def test_allow_rejects_malformed_keys(
        self,
        tmp_path: object,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An absolute key is refused before anything is written."""
        pyproject = typ.cast("Path", tmp_path) / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'x'\n", encoding="utf-8")
        monkeypatch.setattr(gate, "PYPROJECT", pyproject)

        with pytest.raises(SystemExit) as error:
            gate.allow(first="/episodic/a.py", reason="reviewed exception")

        assert error.value.code == 2, "Malformed keys must return two."
        assert "repository-relative" in capsys.readouterr().err, (
            "The diagnostic must explain the key requirement."
        )
        assert "duplication_gate" not in pyproject.read_text(encoding="utf-8"), (
            "A rejected key must not be recorded."
        )

    @pytest.mark.parametrize(
        ("second", "expected_keys"),
        [
            pytest.param(None, ("episodic/a.py",), id="unit"),
            pytest.param(
                ["episodic/b.py::beta"],
                ("episodic/a.py", "episodic/b.py::beta"),
                id="members",
            ),
        ],
    )
    def test_allow_cli_round_trips_unit_and_members(
        self,
        tmp_path: object,
        second: list[str] | None,
        expected_keys: tuple[str, ...],
    ) -> None:
        """The real allow CLI records both supported exception forms."""
        _workspace, script = copied_gate_workspace(typ.cast("Path", tmp_path))
        arguments = ["allow", "--first", "episodic/a.py"]
        for key in second or ():
            arguments.extend(("--second", key))
        arguments.extend(("--reason", "reviewed exception"))

        result = run_gate_command(script, *arguments)
        assert result.returncode == 0, result.stderr
        entries = allowlist.load_allowlist(script.parent.parent / "pyproject.toml")
        assert entries[0].keys == expected_keys, "CLI must retain its requested keys."
        assert entries[0].reason == "reviewed exception", (
            "CLI must retain the supplied reason."
        )

    def test_check_cli_passes_with_a_stub_detector(self, tmp_path: object) -> None:
        """The gate exits zero through its real CLI when every family is allowed."""
        workspace, script = copied_gate_workspace(typ.cast("Path", tmp_path))
        stub = write_stub_nose(typ.cast("Path", tmp_path))
        (workspace / "pyproject.toml").write_text(
            textwrap.dedent(
                """\
                [tool.nose]
                version = "0.20.0"
                roots = ["episodic"]
                mode = "syntax"
                min-size = 24

                [[tool.duplication_gate.allow]]
                members = ["episodic/a.py", "episodic/b.py"]
                reason = "parallel wire contracts"
                """
            ),
            encoding="utf-8",
        )
        result = run_gate_command(
            script,
            "check",
            environment=gate_environment(NOSE_BIN=str(stub)),
        )
        assert result.returncode == 0, result.stderr
        assert "duplication gate passed" in result.stdout, (
            "An allowed family must leave the gate passing."
        )

    def test_real_check_cli_passes(self) -> None:
        """The checked-in gate runs successfully through its real CLI boundary."""
        result = subprocess.run(  # noqa: S603 - fixed repository gate command.
            [
                sys.executable,
                str(REPOSITORY_ROOT / "scripts" / "duplication_gate.py"),
                "check",
            ],
            cwd=REPOSITORY_ROOT,
            env=gate_environment(),
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "duplication gate passed" in result.stdout, (
            "Real check invocation must report its successful gate result."
        )

    def test_reports_a_planted_verbatim_copy(self, tmp_path: object) -> None:
        """The pinned detector reports a planted copy through normalization."""
        settings = detector.load_settings(REPOSITORY_ROOT / "pyproject.toml")
        try:
            binary = detector.resolve_binary(settings)
        except detector.GateExecutionError as error:  # pragma: no cover
            pytest.skip(str(error))
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
        workspace = typ.cast("Path", tmp_path)
        (workspace / "mod.py").write_text(
            body.replace("NAME", "first_total")
            + "\n\n"
            + body.replace("NAME", "second_total"),
            encoding="utf-8",
        )
        command = detector.build_command(
            binary, dc.replace(settings, roots=(".",), min_size=8)
        )
        result = subprocess.run(  # noqa: S603 - pinned, repository-owned binary.
            command,
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
        findings = detector.normalize_findings(json.loads(result.stdout))
        assert findings, "The planted copy must be reported."
        assert any(
            {location.name for location in finding.locations}
            == {"first_total", "second_total"}
            for finding in findings
        ), "The planted copy must name both duplicated functions."
